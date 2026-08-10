"""Download skill zip packages from the skill-hub k8s service.

code-agent defaults (no env required in cluster):
- ``SKILL_HUB_URL``: ``http://skill-hub.dac.svc.cluster.local:8000``
- ``SKILLS``: ``read-code`` (code analysis skill)
- ``LOCAL_SKILLS_DIR`` / ``SKILLS_DOWNLOAD_DIR``: ``/app/skills/``

Set ``SKILLS=`` (empty) to disable download at startup.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SKILL_HUB_URL = "http://skill-hub.dac.svc.cluster.local:8000"
DEFAULT_SKILLS_DIR = "/app/skills/"
DEFAULT_SKILL_NAMES = ("read-code",)
DEFAULT_TIMEOUT = 30.0
DEFAULT_DOWNLOAD_CONCURRENCY = 8

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _parse_skills_env(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []

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

    return [piece for piece in re.split(r"[\s,;]+", raw) if piece]


def _resolve_skill_names(skills: Optional[Sequence[str]] = None) -> List[str]:
    """Resolve which skill zips to fetch from env, explicit arg, or defaults."""
    if skills is not None:
        return list(skills)

    raw_env = os.getenv("SKILLS")
    if raw_env is None:
        logger.info(
            "[SkillDownload] SKILLS not set — using default %s",
            list(DEFAULT_SKILL_NAMES),
        )
        return list(DEFAULT_SKILL_NAMES)

    parsed = _parse_skills_env(raw_env)
    if not parsed:
        logger.info(
            "[SkillDownload] SKILLS is empty (value=%r) — skip download.",
            raw_env,
        )
    return parsed


def _skills_download_enabled() -> bool:
    """Whether startup should attempt any skill download."""
    raw_env = os.getenv("SKILLS")
    if raw_env is None:
        return True
    return bool(_parse_skills_env(raw_env))


def _sanitize_skill_name(name: str) -> Optional[str]:
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
    filename = f"{name}.zip"
    dest_path = dest_dir / filename
    url = f"{base_url}/skills/{filename}"
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
    skills = _resolve_skill_names(skills)

    if not skills:
        return []

    names: List[str] = []
    for raw in skills:
        clean = _sanitize_skill_name(raw)
        if clean:
            names.append(clean)

    if not names:
        logger.info(
            "[SkillDownload] No usable skill names in %r — skip download.",
            skills,
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
    max_workers = _parse_concurrency_env()

    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "[SkillDownload] base_url=%s dest_dir=%s skills=%s overwrite=%s timeout=%ss "
        "concurrency=%d",
        base_url, dest_dir, names, overwrite, timeout, max_workers,
    )

    path_by_name: Dict[str, Path] = {}
    to_fetch: List[str] = []

    for name in names:
        filename = f"{name}.zip"
        dest_path = dest_dir / filename
        if dest_path.exists() and not overwrite:
            logger.info(
                "[SkillDownload] Skip %s — already present at %s",
                filename, dest_path,
            )
            path_by_name[name] = dest_path
        else:
            to_fetch.append(name)

    if to_fetch:
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
                    url = f"{base_url}/skills/{filename}"
                    logger.error(
                        "[SkillDownload] Failed to download %s from %s: %s",
                        filename, url, err,
                    )
                    continue
                assert path is not None
                path_by_name[name] = path

    downloaded = [path_by_name[n] for n in names if n in path_by_name]
    logger.info(
        "[SkillDownload] Completed. %d/%d skills available at %s",
        len(downloaded), len(names), dest_dir,
    )
    return downloaded


def _download_one(client: httpx.Client, url: str, dest_path: Path) -> Path:
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
    logger.info("[SkillDownload] Saved %s (%d bytes)", dest_path, bytes_written)
    return dest_path


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )
    try:
        result = download_skills()
    except Exception:  # noqa: BLE001
        logger.exception("[SkillDownload] Unhandled error")
        return 1
    return 0 if result or not _skills_download_enabled() else 2


if __name__ == "__main__":
    sys.exit(main())
