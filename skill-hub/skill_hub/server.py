"""Skill-Hub HTTP service.

A lightweight FastAPI service that indexes skill zip packs sitting in a
local directory (default ``/app/skills/``) and exposes them to
skill-agent workers via two endpoints:

* ``GET /skills`` — list all available skills (name, latest version,
  description, all available versions). Uses the ``skill_sdk`` SDK to
  parse each zip so metadata stays consistent with what skill-agent
  consumes at runtime.
* ``GET /{name}.zip`` — download a skill zip by skill name. Matches the
  request shape used by ``skill-agent/agent/skill_download.py``. Accepts
  an optional ``?version=...`` query parameter; when omitted, the
  latest known version is served. ``GET /skills/{name}.zip`` is also
  accepted as an alias.

Environment variables
---------------------
SKILLS_DIR
    Directory holding the ``*.zip`` skill packs.
    Defaults to ``/app/skills/``.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from uvicorn.config import LOGGING_CONFIG

from skill_sdk.api.base import Skill
from skill_sdk.skill.loader import SkillLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


DEFAULT_SKILLS_DIR = "/app/skills/"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]+$")


class SkillInfo(BaseModel):
    """Public-facing metadata for a single skill (latest version)."""

    name: str = Field(..., description="Skill display name (from SKILL.md)")
    description: str = Field(..., description="Short summary of the skill")
    version: str = Field(
        ..., description="Latest version string parsed from _meta.json"
    )
    filename: str = Field(
        ..., description="Actual zip filename on disk for the latest version"
    )
    download_url: str = Field(
        ..., description="Relative URL that serves the latest version"
    )
    available_versions: list[str] = Field(
        default_factory=list,
        description="All known versions for this skill, newest first",
    )


class SkillListResponse(BaseModel):
    count: int = Field(..., description="Number of distinct skills")
    skills_dir: str = Field(..., description="Directory scanned on the server")
    skills: list[SkillInfo] = Field(default_factory=list)


@dataclass(frozen=True)
class _SkillVersion:
    """One concrete version of a skill on disk."""

    version: str
    path: Path
    description: str


def _version_key(raw: str) -> tuple[int, Any]:
    """Return a comparison key for a version string.

    Tries :class:`packaging.version.Version` (PEP 440) first so ``1.10``
    beats ``1.9`` properly, and falls back to a lexicographic tuple when
    the version is not parseable (e.g. git shas). Parseable versions
    always rank **above** unparseable ones, mirroring how other
    package registries behave.
    """
    try:
        from packaging.version import Version

        return (1, Version(raw))
    except Exception:  # noqa: BLE001
        return (0, raw)


class SkillIndex:
    """Loads skills from ``skills_dir`` using ``skill_sdk`` and keeps an index.

    For every ``*.zip`` found, the loader resolves the skill's declared
    ``name`` (from ``SKILL.md`` frontmatter) and ``version`` (from
    ``_meta.json``). Multiple versions of the same ``name`` are all
    kept; the index can be queried either for a specific version or for
    the latest one.
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).resolve()
        self._loader = SkillLoader()
        self._lock = threading.Lock()
        self._versions: dict[str, list[_SkillVersion]] = {}

    def reload(self) -> int:
        """Scan ``skills_dir`` and rebuild the name → versions map.

        Returns the number of distinct skill names that ended up in the index.
        """
        with self._lock:
            if not self.skills_dir.is_dir():
                logger.warning(
                    "[SkillHub] skills_dir=%s does not exist (yet) — index is empty",
                    self.skills_dir,
                )
                self._versions = {}
                return 0

            zips = sorted(
                (
                    p
                    for p in self.skills_dir.iterdir()
                    if p.is_file() and p.suffix.lower() == ".zip"
                ),
                key=lambda p: p.name.lower(),
            )

            versions: dict[str, list[_SkillVersion]] = {}
            seen_version_keys: dict[tuple[str, str], Path] = {}
            for zip_path in zips:
                try:
                    skill: Skill = self._loader.load(zip_path)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[SkillHub] failed to load skill zip %s — skipping",
                        zip_path,
                    )
                    continue

                name = (skill.name or "").strip()
                version = (skill.version or "").strip()
                if not name:
                    logger.warning(
                        "[SkillHub] skill from %s has empty name — skipping",
                        zip_path.name,
                    )
                    continue
                if not version:
                    logger.warning(
                        "[SkillHub] skill %s from %s has empty version — skipping",
                        name,
                        zip_path.name,
                    )
                    continue

                key = (name, version)
                if key in seen_version_keys:
                    logger.warning(
                        "[SkillHub] duplicate skill %s version %s "
                        "(first=%s, duplicate=%s) — keeping the first occurrence",
                        name,
                        version,
                        seen_version_keys[key].name,
                        zip_path.name,
                    )
                    continue
                seen_version_keys[key] = zip_path

                versions.setdefault(name, []).append(
                    _SkillVersion(
                        version=version,
                        path=zip_path,
                        description=skill.description or "",
                    )
                )

            # Sort each skill's versions newest-first so callers can trust
            # ``versions[name][0]`` to be the latest.
            for name, vs in versions.items():
                vs.sort(key=lambda v: _version_key(v.version), reverse=True)

            self._versions = versions
            total_versions = sum(len(v) for v in versions.values())
            logger.info(
                "[SkillHub] indexed %d skill(s) / %d version(s) from %s: %s",
                len(versions),
                total_versions,
                self.skills_dir,
                ", ".join(
                    f"{n}@{vs[0].version}(+{len(vs) - 1})"
                    if len(vs) > 1
                    else f"{n}@{vs[0].version}"
                    for n, vs in sorted(versions.items())
                )
                or "(none)",
            )
            return len(versions)

    def list_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            out: list[dict[str, Any]] = []
            for name in sorted(self._versions.keys()):
                vs = self._versions[name]
                if not vs:
                    continue
                latest = vs[0]
                out.append(
                    {
                        "name": name,
                        "description": latest.description,
                        "version": latest.version,
                        "filename": latest.path.name,
                        "download_url": f"/{name}.zip",
                        "available_versions": [v.version for v in vs],
                    }
                )
            return out

    def resolve_zip(self, name: str, version: str | None = None) -> Path | None:
        """Return the on-disk zip for ``name``.

        If ``version`` is ``None`` or empty, the latest known version is
        returned. If ``version`` is provided it must match one of the
        indexed versions exactly.
        """
        with self._lock:
            vs = self._versions.get(name)
            if not vs:
                return None
            if not version:
                return vs[0].path
            for v in vs:
                if v.version == version:
                    return v.path
            return None

    def resolved_version(self, name: str, version: str | None = None) -> str | None:
        """Return the concrete version string that would be served.

        Useful for logging and for reporting the served version back to
        clients (as a response header) when they requested "latest".
        """
        with self._lock:
            vs = self._versions.get(name)
            if not vs:
                return None
            if not version:
                return vs[0].version
            for v in vs:
                if v.version == version:
                    return v.version
            return None

    def close(self) -> None:
        try:
            self._loader.close()
        except Exception:  # noqa: BLE001
            logger.exception("[SkillHub] SkillLoader.close() raised")


index: SkillIndex | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global index
    skills_dir = os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)
    index = SkillIndex(skills_dir)
    index.reload()
    try:
        yield
    finally:
        if index is not None:
            index.close()
        logger.info("[SkillHub] shutdown complete")


app = FastAPI(title="skill-hub", version="0.1.0", lifespan=lifespan)


def _require_index() -> SkillIndex:
    if index is None:
        raise HTTPException(status_code=503, detail="skill index not initialised")
    return index


def _validate_skill_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="skill name must not be empty")
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail=(
                "skill name must only contain letters, digits, '.', '_' or '-'"
            ),
        )
    return name


def _validate_version(version: str | None) -> str | None:
    if version is None:
        return None
    version = version.strip()
    if not version:
        return None
    if not _VERSION_RE.fullmatch(version):
        raise HTTPException(
            status_code=400,
            detail=(
                "version must only contain letters, digits, '.', '_', '+' or '-'"
            ),
        )
    return version


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/skills", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    idx = _require_index()
    skills = idx.list_skills()
    return SkillListResponse(
        count=len(skills),
        skills_dir=str(idx.skills_dir),
        skills=[SkillInfo(**s) for s in skills],
    )


@app.post("/skills/reload", response_model=SkillListResponse)
async def reload_skills() -> SkillListResponse:
    """Rescan the skills directory and rebuild the in-memory index."""
    idx = _require_index()
    idx.reload()
    return await list_skills()


async def _download_by_name(name: str, version: str | None) -> FileResponse:
    idx = _require_index()
    clean_name = _validate_skill_name(name)
    clean_version = _validate_version(version)
    zip_path = idx.resolve_zip(clean_name, clean_version)
    if zip_path is None or not zip_path.is_file():
        if clean_version:
            detail = (
                f"skill '{clean_name}' version '{clean_version}' not found on this hub"
            )
        else:
            detail = f"skill '{clean_name}' not found on this hub"
        raise HTTPException(status_code=404, detail=detail)

    resolved = idx.resolved_version(clean_name, clean_version) or ""
    logger.info(
        "[SkillHub] download name=%s requested_version=%r resolved_version=%s file=%s",
        clean_name,
        clean_version,
        resolved,
        zip_path.name,
    )
    response = FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"{clean_name}.zip",
    )
    if resolved:
        response.headers["X-Skill-Version"] = resolved
    return response


@app.get("/skills/{name}.zip")
async def download_skill_under_skills(
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> FileResponse:
    return await _download_by_name(name, version)


# Compatible with skill-agent/agent/skill_download.py which issues
# ``GET {SKILL_HUB_URL}/{name}.zip`` at the root path.
@app.get("/{name}.zip")
async def download_skill_at_root(
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> FileResponse:
    return await _download_by_name(name, version)


@app.exception_handler(HTTPException)
async def _http_exc_handler(_request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind")
@click.option("--port", default=8000, type=int, help="Port to bind")
@click.option(
    "--skills-dir",
    default=None,
    help="Directory containing skill *.zip packs (overrides SKILLS_DIR env)",
)
def main(host: str, port: int, skills_dir: str | None) -> None:
    if skills_dir:
        os.environ["SKILLS_DIR"] = skills_dir

    log_config = LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    log_config["formatters"]["default"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(
        "[SkillHub] starting on %s:%d skills_dir=%s",
        host,
        port,
        os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR),
    )
    try:
        uvicorn.run(app, host=host, port=port, log_config=log_config)
    except Exception:
        logger.exception("[SkillHub] server startup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
