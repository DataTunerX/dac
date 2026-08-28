"""Download skill zip packages from the skill-hub k8s service.

The list of skills to fetch is supplied via the ``SKILLS`` environment
variable. Each entry maps 1:1 to a ``<name>.zip`` file on the skill-hub
service — e.g. skill ``genhash`` → ``genhash.zip``.

Supported environment variables
-------------------------------
SKILLS
    Skill package references. Accepts a legacy JSON name array or structured
    ``namespace``/``name``/``version`` objects used by local DAC attachments.

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

The module can be used programmatically by calling
:func:`download_skills` or run standalone via
``python -m orchestrator_agent.skill_download``.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SKILL_HUB_URL = "http://skill-hub.dac.svc.cluster.local:8000"
DEFAULT_SKILLS_DIR = "/app/skills/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_DOWNLOAD_CONCURRENCY = 8

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DEFAULT_NAMESPACE = "default"


@dataclass(frozen=True)
class SkillRef:
    name: str
    namespace: str = DEFAULT_NAMESPACE
    version: str = ""

    def download_path(self) -> str:
        filename = f"{quote(self.name, safe='')}.zip"
        namespace = quote(self.namespace, safe="")
        version = quote(self.version, safe="")
        if self.namespace == DEFAULT_NAMESPACE and not self.version:
            return f"/skills/{filename}"
        if self.namespace == DEFAULT_NAMESPACE:
            return f"/skills/{filename}?version={version}"
        path = f"/namespaces/{namespace}/skills/{filename}"
        return f"{path}?version={version}" if self.version else path


def _ref_from_item(item: Any) -> Optional[SkillRef]:
    if isinstance(item, SkillRef):
        return item
    if isinstance(item, dict):
        name = _sanitize_skill_name(str(item.get("name") or ""))
        if not name:
            return None
        namespace = str(item.get("namespace") or DEFAULT_NAMESPACE).strip()
        return SkillRef(
            name=name,
            namespace=namespace or DEFAULT_NAMESPACE,
            version=str(item.get("version") or "").strip(),
        )
    name = _sanitize_skill_name(str(item))
    return SkillRef(name=name) if name else None


def _parse_skills_env(raw: Optional[str]) -> List[SkillRef]:
    """Parse legacy names or namespace/name/version objects from ``SKILLS``."""
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
                return [ref for item in parsed if (ref := _ref_from_item(item))]
        except json.JSONDecodeError:
            logger.warning(
                "[SkillDownload] SKILLS looked like JSON but failed to parse; "
                "falling back to delimiter split. raw=%r",
                raw,
            )

    # Otherwise split on common delimiters (comma, semicolon, whitespace).
    return [
        ref
        for piece in re.split(r"[\s,;]+", raw)
        if (ref := _ref_from_item(piece))
    ]


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


def _dedupe_preserve_order(refs: Sequence[SkillRef]) -> List[SkillRef]:
    seen: set[str] = set()
    out: List[SkillRef] = []
    for ref in refs:
        if ref.name not in seen:
            seen.add(ref.name)
            out.append(ref)
    return out


def _fetch_one_skill(
    ref: SkillRef,
    base_url: str,
    dest_dir: Path,
    timeout: float,
) -> Tuple[str, Optional[Path], Optional[str]]:
    """Download a single skill in a worker thread.

    Returns ``(name, dest_path, None)`` on success, or
    ``(name, None, error_message)`` on failure. Uses a dedicated
    :class:`httpx.Client` per call for thread safety.
    """
    filename = f"{ref.name}.zip"
    dest_path = dest_dir / filename
    url = f"{base_url}{ref.download_path()}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            path = _download_one(client, url, dest_path)
        return (ref.name, path, None)
    except Exception as exc:  # noqa: BLE001
        return (ref.name, None, str(exc))


def download_skills(
    skills: Optional[Sequence[Union[str, dict, SkillRef]]] = None,
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

    refs = [ref for item in skills if (ref := _ref_from_item(item))]

    if not refs:
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

    refs = _dedupe_preserve_order(refs)
    max_workers = _parse_concurrency_env()

    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "[SkillDownload] base_url=%s dest_dir=%s skills=%s overwrite=%s timeout=%ss "
        "concurrency=%d",
        base_url,
        dest_dir,
        [
            f"{ref.namespace}/{ref.name}" + (f"@{ref.version}" if ref.version else "")
            for ref in refs
        ],
        overwrite,
        timeout,
        max_workers,
    )

    # Per-name outcome: Path when skipped (kept) or downloaded successfully;
    # missing key means download failed.
    path_by_name: Dict[str, Path] = {}
    to_fetch: List[SkillRef] = []

    for ref in refs:
        name = ref.name
        filename = f"{name}.zip"
        dest_path = dest_dir / filename
        if dest_path.exists() and not overwrite:
            logger.info(
                "[SkillDownload] Skip %s — already present at %s (set SKILL_DOWNLOAD_OVERWRITE=true to refresh)",
                filename, dest_path,
            )
            path_by_name[name] = dest_path
        else:
            to_fetch.append(ref)

    if to_fetch:
        workers = min(max_workers, len(to_fetch))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_fetch_one_skill, ref, base_url, dest_dir, timeout): ref
                for ref in to_fetch
            }
            for fut in concurrent.futures.as_completed(future_map):
                name, path, err = fut.result()
                if err is not None:
                    ref = future_map[fut]
                    filename = f"{name}.zip"
                    url = f"{base_url}{ref.download_path()}"
                    logger.error(
                        "[SkillDownload] Failed to download %s from %s: %s",
                        filename, url, err,
                    )
                    continue
                assert path is not None  # for type checkers; success implies path
                path_by_name[name] = path

    downloaded = [path_by_name[ref.name] for ref in refs if ref.name in path_by_name]

    logger.info(
        "[SkillDownload] Completed. %d/%d skills available at %s",
        len(downloaded), len(refs), dest_dir,
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
