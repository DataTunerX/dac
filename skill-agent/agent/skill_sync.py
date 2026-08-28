"""Background watcher that keeps a skill-agent in sync with skill-hub.

At startup the agent downloads its subscribed skills once (see
:mod:`agent.skill_download`). This module adds the *ongoing* half: a daemon
thread that periodically polls the relevant Skill Hub namespace indexes and,
when it sees a **new** skill or a **newer version** of a watched skill, pulls the zip into
``SKILLS_DOWNLOAD_DIR`` (overwriting) and fires an ``on_change`` callback. The
server wires that callback to hot-reload the ``SkillRunner`` and re-register the
refreshed AgentCard — so a ``docker push``-style upload to the hub shows up on
running agents without a restart.

Environment variables
---------------------
SKILL_SYNC_ENABLED
    Master switch. ``true``/``1``/``yes`` (default) enables the watcher.
    Set to ``false`` to disable polling entirely.

SKILL_SYNC_INTERVAL
    Seconds between hub polls (float). Default ``60``. Values ``<= 0`` disable
    the watcher.

SKILL_SYNC_WATCH_ALL
    When truthy (default ``true``), the watcher also downloads unconfigured
    skills from the legacy ``default`` namespace. Set to ``false`` to track only
    the explicit namespace/name/version subscriptions in ``SKILLS``.

It also honours the same ``SKILL_HUB_URL`` / ``SKILLS`` / ``SKILLS_DOWNLOAD_DIR``
/ ``SKILL_DOWNLOAD_TIMEOUT`` / ``TAVILY_API_KEY`` variables as
``skill_download`` so both halves stay consistent.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import httpx

from .skill_download import (
    DEFAULT_NAMESPACE,
    DEFAULT_SKILL_HUB_URL,
    DEFAULT_SKILLS_DIR,
    DEFAULT_TIMEOUT,
    SkillRef,
    _parse_skills_env,
    _sanitize_skill_name,
    download_skills,
)

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DEFAULT_SYNC_INTERVAL = 60.0


def _env_truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def sync_enabled() -> bool:
    """Return whether the watcher should run given the current environment."""
    if not _env_truthy(os.getenv("SKILL_SYNC_ENABLED"), default=True):
        return False
    return _sync_interval() > 0


def _sync_interval() -> float:
    raw = (os.getenv("SKILL_SYNC_INTERVAL") or "").strip()
    if not raw:
        return DEFAULT_SYNC_INTERVAL
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "[SkillSync] invalid SKILL_SYNC_INTERVAL=%r — using %.0fs",
            raw,
            DEFAULT_SYNC_INTERVAL,
        )
        return DEFAULT_SYNC_INTERVAL


class SkillHubWatcher(threading.Thread):
    """Polls skill-hub and downloads new/updated skills, then calls ``on_change``.

    Parameters
    ----------
    on_change:
        Callback invoked with the list of skill names that were (re)downloaded in
        a poll cycle. Wired by the server to reload the runner and refresh the
        agent card. Exceptions from the callback are logged, never fatal.
    initial_versions:
        ``{name: version}`` already loaded at startup. Seeds the baseline so the
        first poll does not needlessly re-download skills that are already
        current on disk.
    """

    def __init__(
        self,
        *,
        on_change: Callable[[List[str]], None],
        base_url: Optional[str] = None,
        skills_dir: Optional[str] = None,
        subscribed: Optional[Sequence[Union[str, SkillRef]]] = None,
        watch_all: Optional[bool] = None,
        interval: Optional[float] = None,
        timeout: Optional[float] = None,
        initial_versions: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name="skill-hub-watcher", daemon=True)
        self._on_change = on_change
        self.base_url = (
            base_url or os.getenv("SKILL_HUB_URL") or DEFAULT_SKILL_HUB_URL
        ).rstrip("/")
        self.skills_dir = Path(
            skills_dir or os.getenv("SKILLS_DOWNLOAD_DIR") or DEFAULT_SKILLS_DIR
        )
        if subscribed is None:
            subscribed = _parse_skills_env(os.getenv("SKILLS"))
        subscribed_by_name: Dict[str, SkillRef] = {}
        for item in subscribed:
            if isinstance(item, SkillRef):
                ref = item
            else:
                name = _sanitize_skill_name(str(item))
                if not name:
                    continue
                ref = SkillRef(name=name)
            # The downloader writes <name>.zip into a flat directory, so the
            # same name cannot safely be subscribed from two namespaces.
            subscribed_by_name.setdefault(ref.name, ref)
        self.subscribed = subscribed_by_name
        self.watch_all = (
            _env_truthy(os.getenv("SKILL_SYNC_WATCH_ALL"), default=True)
            if watch_all is None
            else watch_all
        )
        self.interval = interval if interval is not None else _sync_interval()
        if timeout is None:
            try:
                timeout = float(os.getenv("SKILL_DOWNLOAD_TIMEOUT", DEFAULT_TIMEOUT))
            except ValueError:
                timeout = DEFAULT_TIMEOUT
        self.timeout = timeout
        # name -> last-synced latest version string
        self._known: Dict[str, str] = dict(initial_versions or {})
        # Do not call this ``_stop``: threading.Thread owns a private _stop()
        # method which join() invokes.
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=max(1.0, min(self.interval + 1.0, 10.0)))

    def _poll_hub(self) -> Optional[Dict[Tuple[str, str], Tuple[str, frozenset[str]]]]:
        """Return hub versions keyed by ``(namespace, name)``.

        ``watch_all`` retains its legacy meaning for the default namespace.
        Explicit subscriptions add any non-default namespaces that must also be
        queried. This keeps local DAC attachments namespace-aware without
        importing unrelated packages from those namespaces.
        """
        namespaces = {ref.namespace for ref in self.subscribed.values()}
        if self.watch_all:
            namespaces.add(DEFAULT_NAMESPACE)
        if not namespaces:
            return {}

        out: Dict[Tuple[str, str], Tuple[str, frozenset[str]]] = {}
        successful = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            for namespace in sorted(namespaces):
                if namespace == DEFAULT_NAMESPACE:
                    url = f"{self.base_url}/skills"
                else:
                    url = f"{self.base_url}/namespaces/{quote(namespace, safe='')}/skills"
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[SkillSync] poll %s failed: %s", url, exc)
                    continue
                skills = payload.get("skills") if isinstance(payload, dict) else None
                if not isinstance(skills, list):
                    logger.warning("[SkillSync] unexpected skills payload from %s", url)
                    continue
                successful += 1
                for entry in skills:
                    if not isinstance(entry, dict):
                        continue
                    name = _sanitize_skill_name(str(entry.get("name") or ""))
                    latest = str(entry.get("version") or "").strip()
                    raw_versions = entry.get("available_versions")
                    versions = (
                        frozenset(str(v).strip() for v in raw_versions if str(v).strip())
                        if isinstance(raw_versions, list)
                        else frozenset({latest} if latest else set())
                    )
                    if name and latest:
                        out[(namespace, name)] = (latest, versions)
        return out if successful else None

    def _select_targets(
        self,
        hub: Dict[Tuple[str, str], Tuple[str, frozenset[str]]],
    ) -> List[Tuple[SkillRef, str]]:
        """Return ``(download_ref, desired_version)`` entries needing refresh."""
        desired: Dict[str, Tuple[SkillRef, str]] = {}

        if self.watch_all:
            for (namespace, name), (latest, _versions) in hub.items():
                if namespace == DEFAULT_NAMESPACE:
                    desired[name] = (SkillRef(name=name), latest)

        # Explicit subscriptions override same-name watch-all entries and retain
        # their namespace/version pin.
        for name, ref in self.subscribed.items():
            entry = hub.get((ref.namespace, name))
            if entry is None:
                continue
            latest, versions = entry
            wanted = ref.version or latest
            if ref.version and ref.version not in versions:
                logger.warning(
                    "[SkillSync] pinned version missing: %s/%s@%s",
                    ref.namespace,
                    name,
                    ref.version,
                )
                continue
            desired[name] = (ref, wanted)

        targets: List[Tuple[SkillRef, str]] = []
        for name in sorted(desired):
            ref, wanted = desired[name]
            local_present = (self.skills_dir / f"{name}.zip").exists()
            if self._known.get(name) == wanted and local_present:
                continue
            targets.append((ref, wanted))
        return targets

    def _sync_once(self) -> None:
        hub = self._poll_hub()
        if hub is None:
            return
        targets = self._select_targets(hub)
        if not targets:
            return
        labels = [
            f"{ref.namespace}/{ref.name}" + (f"@{ref.version}" if ref.version else "")
            for ref, _wanted in targets
        ]
        logger.info(
            "[SkillSync] change detected — pulling %d skill(s): %s",
            len(targets),
            ", ".join(labels),
        )
        try:
            downloaded = download_skills(
                [ref for ref, _wanted in targets],
                skill_hub_url=self.base_url,
                target_dir=str(self.skills_dir),
                timeout=self.timeout,
                overwrite=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[SkillSync] download_skills raised")
            return

        got = {p.stem for p in downloaded}
        applied = [ref.name for ref, _wanted in targets if ref.name in got]
        for ref, wanted in targets:
            if ref.name in got:
                self._known[ref.name] = wanted
        if not applied:
            logger.warning(
                "[SkillSync] nothing was successfully downloaded (targets=%s)",
                ", ".join(labels),
            )
            return
        try:
            self._on_change(applied)
        except Exception:  # noqa: BLE001
            logger.exception("[SkillSync] on_change callback raised")

    def run(self) -> None:  # noqa: D401
        logger.info(
            "[SkillSync] watcher started: hub=%s dir=%s interval=%.0fs "
            "watch_all=%s subscribed=%s",
            self.base_url,
            self.skills_dir,
            self.interval,
            self.watch_all,
            [
                f"{ref.namespace}/{ref.name}" + (f"@{ref.version}" if ref.version else "")
                for ref in self.subscribed.values()
            ]
            or "(none)",
        )
        # Poll once immediately. The startup downloader fetched subscriptions,
        # while this initial registry scan also discovers every existing skill
        # when watch_all is enabled.
        try:
            self._sync_once()
        except Exception:  # noqa: BLE001
            logger.exception("[SkillSync] initial sync raised — continuing")
        while not self._stop_event.wait(self.interval):
            try:
                self._sync_once()
            except Exception:  # noqa: BLE001
                logger.exception("[SkillSync] sync cycle raised — continuing")
        logger.info("[SkillSync] watcher stopped")


def start_watcher(
    on_change: Callable[[List[str]], None],
    *,
    initial_versions: Optional[Dict[str, str]] = None,
) -> Optional[SkillHubWatcher]:
    """Construct and start a :class:`SkillHubWatcher` if enabled, else ``None``."""
    if not sync_enabled():
        logger.info(
            "[SkillSync] watcher disabled (SKILL_SYNC_ENABLED/SKILL_SYNC_INTERVAL)"
        )
        return None
    watcher = SkillHubWatcher(on_change=on_change, initial_versions=initial_versions)
    watcher.start()
    return watcher
