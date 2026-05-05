"""Download skill zip packages from the skill-hub k8s service.

The list of skills to fetch is supplied via the ``SKILLS`` environment
variable. Each entry maps 1:1 to a ``<name>.zip`` file on the skill-hub
service — e.g. skill ``genhash`` → ``genhash.zip``.

Supported environment variables
-------------------------------
SKILLS
    List of skill names to download. Accepts either a JSON array
    (``'["genhash", "weather"]'``) or a comma/semicolon/whitespace
    separated string (``'genhash,weather'``). When unset or empty no
    download is attempted.

SKILL_HUB_URL
    Base URL of the skill-hub service. Defaults to
    ``http://skill-hub.dac.svc.cluster.local:8000``.

SKILLS_DOWNLOAD_DIR
    Target directory to write the zip files into. Defaults to
    ``/app/skills/``. The directory is created if it does not exist.

SKILL_DOWNLOAD_TIMEOUT
    Per-request HTTP timeout in seconds (float). Default ``30``.

SKILL_DOWNLOAD_OVERWRITE
    When truthy (``1``/``true``/``yes``) an existing local zip file is
    re-downloaded. Default ``false`` — existing files are kept.

SKILL_DOWNLOAD_CONCURRENCY
    Maximum parallel HTTP downloads (integer, ``>= 1``). Default ``8``.
    Each worker uses its own :class:`httpx.Client` instance.

Before any zip is fetched, the client calls ``GET {SKILL_HUB_URL}/healthz`` and
retries until the hub reports healthy: first pause after failure is ``5`` s,
then the delay doubles until ``60`` s (capped). Each probe uses
``SKILL_HUB_HEALTH_CHECK_TIMEOUT`` seconds per HTTP request.

SKILL_HUB_HEALTH_CHECK_TIMEOUT
    Per-request timeout in seconds for the health probe only. Default ``10``.

TAVILY_API_KEY
    When unset or blank (after strip), ``tavily-search`` is removed from the
    resolved download list even if it appears in ``SKILLS`` (no ``tavily-search.zip`` fetch).

The module can be used programmatically by calling
:func:`download_skills` or run standalone via
``python -m agent.skill_download``.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SKILL_HUB_URL = "http://skill-hub.dac.svc.cluster.local:8000"
DEFAULT_SKILLS_DIR = "/app/skills/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_DOWNLOAD_CONCURRENCY = 8
DEFAULT_HEALTH_TIMEOUT = 10.0
_HEALTH_RETRY_INITIAL_INTERVAL = 5.0
_HEALTH_RETRY_MAX_INTERVAL = 60.0

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _parse_skills_env(raw: Optional[str]) -> List[str]:
    """Parse the ``SKILLS`` env value into a clean list of skill names."""
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []

    # Try JSON array first so users can pass the idiomatic
    # ``SKILLS='["genhash", "weather"]'`` form.
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            logger.warning(
                "[SkillDownload] SKILLS looked like JSON but failed to parse; "
                "falling back to delimiter split. raw=%r",
                raw,
            )

    # Otherwise split on common delimiters (comma, semicolon, whitespace).
    return [piece for piece in re.split(r"[\s,;]+", raw) if piece]


def _sanitize_skill_name(name: str) -> Optional[str]:
    """Reject names that would escape the target directory."""
    name = name.strip()
    if not name:
        return None
    if name.endswith(".zip"):
        name = name[:-4]
    if "/" in name or "\\" in name or name in {".", ".."}:
        logger.warning("[SkillDownload] Skipping unsafe skill name: %r", name)
        return None
    return name


def _env_truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def _parse_concurrency_env() -> int:
    raw = os.getenv("SKILL_DOWNLOAD_CONCURRENCY")
    if raw is None or not str(raw).strip():
        return DEFAULT_DOWNLOAD_CONCURRENCY
    try:
        n = int(str(raw).strip())
    except ValueError:
        logger.warning(
            "[SkillDownload] Invalid SKILL_DOWNLOAD_CONCURRENCY=%r — fallback to %d",
            raw,
            DEFAULT_DOWNLOAD_CONCURRENCY,
        )
        return DEFAULT_DOWNLOAD_CONCURRENCY
    return max(1, n)


def _parse_health_check_timeout_env() -> float:
    raw = os.getenv("SKILL_HUB_HEALTH_CHECK_TIMEOUT")
    if raw is None or not str(raw).strip():
        return DEFAULT_HEALTH_TIMEOUT
    try:
        return max(1.0, float(str(raw).strip()))
    except ValueError:
        logger.warning(
            "[SkillDownload] Invalid SKILL_HUB_HEALTH_CHECK_TIMEOUT=%r — fallback to %ss",
            raw,
            DEFAULT_HEALTH_TIMEOUT,
        )
        return DEFAULT_HEALTH_TIMEOUT


def wait_for_skill_hub_ready(
    base_url: str,
    *,
    health_timeout: Optional[float] = None,
    initial_interval: float = _HEALTH_RETRY_INITIAL_INTERVAL,
    max_interval: float = _HEALTH_RETRY_MAX_INTERVAL,
) -> None:
    """GET ``/healthz`` until skill-hub responds with ``{"status": "ok"}``.

    Uses exponential backoff starting at ``initial_interval`` seconds between
    attempts, capped at ``max_interval``.
    """
    ht = (
        float(health_timeout)
        if health_timeout is not None
        else _parse_health_check_timeout_env()
    )
    url = f"{base_url.rstrip('/')}/healthz"
    interval = float(initial_interval)
    attempt = 0
    while True:
        attempt += 1
        try:
            with httpx.Client(timeout=ht, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"HTTP {resp.status_code} from skill-hub healthz"
                )
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("status") == "ok":
                logger.info(
                    "[SkillDownload] skill-hub healthy at %s (attempt %d)",
                    url,
                    attempt,
                )
                return
            raise RuntimeError(f"unexpected health payload: {payload!r}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[SkillDownload] skill-hub not ready at %s (attempt %d): %s — "
                "next retry in %.1fs",
                url,
                attempt,
                exc,
                interval,
            )
        time.sleep(interval)
        interval = min(interval * 2.0, max_interval)


def _dedupe_preserve_order(names: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _fetch_one_skill(
    name: str,
    base_url: str,
    dest_dir: Path,
    timeout: float,
) -> Tuple[str, Optional[Path], Optional[str]]:
    """Download a single skill in a worker thread.

    Returns ``(name, dest_path, None)`` on success, or
    ``(name, None, error_message)`` on failure. Uses a dedicated
    :class:`httpx.Client` per call for thread safety.
    """
    filename = f"{name}.zip"
    dest_path = dest_dir / filename
    url = f"{base_url}/{filename}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            path = _download_one(client, url, dest_path)
        return (name, path, None)
    except Exception as exc:  # noqa: BLE001
        return (name, None, str(exc))


def download_skills(
    skills: Optional[Sequence[str]] = None,
    *,
    skill_hub_url: Optional[str] = None,
    target_dir: Optional[str] = None,
    timeout: Optional[float] = None,
    overwrite: Optional[bool] = None,
) -> List[Path]:
    """Download the requested skills from skill-hub.

    All parameters fall back to the matching environment variables
    documented at the top of this module. Returns the list of files
    that were successfully written to disk (existing files that were
    kept are also included).
    """
    raw_env = os.getenv("SKILLS")
    if skills is None:
        skills = _parse_skills_env(raw_env)

    if not skills:
        if raw_env is None:
            logger.info("[SkillDownload] SKILLS env is not set — skip download.")
        else:
            logger.info(
                "[SkillDownload] SKILLS env is empty (value=%r) — skip download.",
                raw_env,
            )
        return []

    names: List[str] = []
    for raw in skills:
        clean = _sanitize_skill_name(raw)
        if clean:
            names.append(clean)

    if not names:
        logger.info(
            "[SkillDownload] SKILLS contained no usable skill names (value=%r) — skip download.",
            raw_env,
        )
        return []

    base_url = (skill_hub_url or os.getenv("SKILL_HUB_URL") or DEFAULT_SKILL_HUB_URL).rstrip("/")
    dest_dir = Path(target_dir or os.getenv("SKILLS_DOWNLOAD_DIR") or DEFAULT_SKILLS_DIR)

    if timeout is None:
        try:
            timeout = float(os.getenv("SKILL_DOWNLOAD_TIMEOUT", DEFAULT_TIMEOUT))
        except ValueError:
            logger.warning(
                "[SkillDownload] Invalid SKILL_DOWNLOAD_TIMEOUT, fallback to %ss",
                DEFAULT_TIMEOUT,
            )
            timeout = DEFAULT_TIMEOUT

    if overwrite is None:
        overwrite = _env_truthy(os.getenv("SKILL_DOWNLOAD_OVERWRITE"), default=False)

    names = _dedupe_preserve_order(names)
    if not (os.getenv("TAVILY_API_KEY") or "").strip():
        names = [n for n in names if n.lower() != "tavily-search"]
    max_workers = _parse_concurrency_env()

    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "[SkillDownload] base_url=%s dest_dir=%s skills=%s overwrite=%s timeout=%ss "
        "concurrency=%d",
        base_url, dest_dir, names, overwrite, timeout, max_workers,
    )

    # Per-name outcome: Path when skipped (kept) or downloaded successfully;
    # missing key means download failed.
    path_by_name: Dict[str, Path] = {}
    to_fetch: List[str] = []

    for name in names:
        filename = f"{name}.zip"
        dest_path = dest_dir / filename
        if dest_path.exists() and not overwrite:
            logger.info(
                "[SkillDownload] Skip %s — already present at %s (set SKILL_DOWNLOAD_OVERWRITE=true to refresh)",
                filename, dest_path,
            )
            path_by_name[name] = dest_path
        else:
            to_fetch.append(name)

    if to_fetch:
        wait_for_skill_hub_ready(base_url)
        workers = min(max_workers, len(to_fetch))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_fetch_one_skill, name, base_url, dest_dir, timeout): name
                for name in to_fetch
            }
            for fut in concurrent.futures.as_completed(future_map):
                name, path, err = fut.result()
                if err is not None:
                    filename = f"{name}.zip"
                    url = f"{base_url}/{filename}"
                    logger.error(
                        "[SkillDownload] Failed to download %s from %s: %s",
                        filename, url, err,
                    )
                    continue
                assert path is not None  # for type checkers; success implies path
                path_by_name[name] = path

    downloaded = [path_by_name[n] for n in names if n in path_by_name]

    logger.info(
        "[SkillDownload] Completed. %d/%d skills available at %s",
        len(downloaded), len(names), dest_dir,
    )
    return downloaded


def _download_one(client: httpx.Client, url: str, dest_path: Path) -> Path:
    """Stream a single skill zip to ``dest_path`` atomically."""
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    logger.info("[SkillDownload] GET %s -> %s", url, dest_path)

    bytes_written = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                fh.write(chunk)
                bytes_written += len(chunk)

    if bytes_written == 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"empty response body from {url}")

    tmp_path.replace(dest_path)
    logger.info(
        "[SkillDownload] Saved %s (%d bytes)", dest_path, bytes_written
    )
    return dest_path


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()],
    )

    try:
        result = download_skills()
    except Exception:  # noqa: BLE001
        logger.exception("[SkillDownload] Unhandled error")
        return 1
    return 0 if result or not _parse_skills_env(os.getenv("SKILLS")) else 2


if __name__ == "__main__":
    sys.exit(main())
