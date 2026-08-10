"""Auto-reload watcher — watches SKILLS_DIR for changes and rebuilds the index."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchfiles import Change, awatch

from .index import SkillIndex, version_key

logger = logging.getLogger(__name__)

AUTO_RELOAD_DEBOUNCE_MS = 2000


def _is_skill_zip(path: str) -> bool:
    """Whether a watched path change is relevant (a ``*.zip`` file)."""
    return Path(path).suffix.lower() == ".zip"


async def watch_skills_dir(idx: SkillIndex) -> None:
    """Auto-reload the index whenever the skills directory changes.

    Watches the directory for add/modify/remove events on ``*.zip`` files and
    calls :meth:`SkillIndex.reload`. Events are debounced so a burst of file
    operations (e.g. multiple zips copied at once) triggers a single rescan.
    """
    watched_dir = idx.skills_dir
    if not watched_dir.is_dir():
        logger.warning(
            "[SkillHub] auto-watch: %s does not exist — not watching",
            watched_dir,
        )
        return

    logger.info(
        "[SkillHub] auto-watch started dir=%s debounce=%dms",
        watched_dir,
        AUTO_RELOAD_DEBOUNCE_MS,
    )
    try:
        async for changes in awatch(
            str(watched_dir),
            debounce=AUTO_RELOAD_DEBOUNCE_MS,
            stop_event=asyncio.Event(),
        ):
            relevant = [c for c in changes if _is_skill_zip(c[1])]
            if not relevant:
                continue
            # Log each concrete file event (which zip, which operation).
            for change, path in sorted(relevant, key=lambda item: (item[1], item[0])):
                logger.info(
                    "[SkillHub] auto-reload event: %s %s",
                    Change(change).name,
                    Path(path).name,
                )
            before = idx.snapshot()
            idx.reload()
            after = idx.snapshot()
            log_index_diff(before, after)
    except asyncio.CancelledError:
        logger.info("[SkillHub] auto-watch stopped")
        raise
    except Exception:  # noqa: BLE001
        logger.exception("[SkillHub] auto-watch failed — index may be stale")


def log_index_diff(
    before: dict[tuple[str, str], frozenset[str]],
    after: dict[tuple[str, str], frozenset[str]],
) -> None:
    """Log the net skill changes between two index snapshots.

    Marks which skills were added, removed, or had a version change, so an
    auto-reload is traceable in the logs.
    """

    def _key_label(key: tuple[str, str]) -> str:
        ns, name = key
        return f"{ns}/{name}"

    added = sorted(set(after) - set(before), key=_key_label)
    removed = sorted(set(before) - set(after), key=_key_label)
    updated: list[tuple[tuple[str, str], frozenset[str], frozenset[str]]] = []
    for key in sorted(set(before) & set(after), key=_key_label):
        if before[key] != after[key]:
            updated.append((key, before[key], after[key]))

    for key in added:
        logger.info(
            "[SkillHub] auto-reload result: NEW skill %s (versions %s)",
            _key_label(key),
            _fmt_versions(after[key]),
        )
    for key in removed:
        logger.info("[SkillHub] auto-reload result: REMOVED skill %s", _key_label(key))
    for key, old_versions, new_versions in updated:
        logger.info(
            "[SkillHub] auto-reload result: CHANGED skill %s versions %s -> %s",
            _key_label(key),
            _fmt_versions(old_versions),
            _fmt_versions(new_versions),
        )
    if not added and not removed and not updated:
        logger.info("[SkillHub] auto-reload result: index unchanged")


def _fmt_versions(versions: frozenset[str]) -> str:
    ordered = sorted(versions, key=version_key, reverse=True)
    return ", ".join(ordered) if ordered else "(none)"
