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

import hmac
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from skill_sdk.api.base import Skill
from skill_sdk.skill.loader import SkillLoader
from uvicorn.config import LOGGING_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


DEFAULT_SKILLS_DIR = "/app/skills/"
# Maximum accepted upload size for a pushed skill zip (bytes). Overridable via
# ``SKILL_HUB_MAX_UPLOAD_BYTES``. Skill packs are tiny (a few KB), so 50 MiB is
# a generous ceiling that also caps abusive/accidental huge uploads.
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 2048
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
# Characters allowed verbatim in an on-disk filename component; everything else
# is collapsed to ``-`` when composing ``<name>-<version>.zip`` for a push.
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._+-]+")


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


class PushResponse(BaseModel):
    """Result of a successful ``POST /skills`` push."""

    status: str = Field(default="ok")
    created: bool = Field(
        ..., description="True when this (name, version) did not exist before"
    )
    name: str = Field(..., description="Skill name parsed from the pushed zip")
    version: str = Field(..., description="Skill version parsed from the pushed zip")
    filename: str = Field(..., description="Filename the zip was stored under on disk")
    description: str = Field(default="")
    download_url: str = Field(..., description="Relative URL that serves this skill")
    available_versions: list[str] = Field(default_factory=list)


class DeleteResponse(BaseModel):
    status: str = Field(default="ok")
    name: str = Field(...)
    removed_versions: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)


class SkillValidationError(Exception):
    """Raised when a pushed zip cannot be parsed as a valid skill pack."""


class SkillConflictError(Exception):
    """Raised when a (name, version) already exists and overwrite was not set."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(f"skill '{name}' version '{version}' already exists")
        self.name = name
        self.version = version


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
        self._lock = threading.RLock()
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
                    if p.is_file()
                    and p.suffix.lower() == ".zip"
                    and not p.name.startswith(".")
                ),
                key=lambda p: p.name.lower(),
            )

            versions: dict[str, list[_SkillVersion]] = {}
            seen_version_keys: dict[tuple[str, str], Path] = {}
            loader = SkillLoader()
            try:
                for zip_path in zips:
                    try:
                        skill: Skill = loader.load(zip_path)
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
                            "[SkillHub] skill %s from %s has empty version — "
                            "skipping",
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
            finally:
                # Index entries retain metadata and archive paths only. Closing
                # here prevents one extraction temp tree leaking per reload.
                loader.close()

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

    def _entry_for(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            vs = self._versions.get(name)
            if not vs:
                return None
            latest = vs[0]
            return {
                "name": name,
                "description": latest.description,
                "version": latest.version,
                "filename": latest.path.name,
                "download_url": f"/{name}.zip",
                "available_versions": [v.version for v in vs],
            }

    def ingest(
        self,
        src_path: Path,
        *,
        overwrite: bool = False,
        expected_name: str | None = None,
    ) -> dict[str, Any]:
        """Validate ``src_path`` as a skill zip and store it under ``skills_dir``.

        The authoritative skill *name* and *version* come from the zip's
        ``SKILL.md`` / ``_meta.json`` (parsed with the same loader used for
        indexing), never from the uploaded filename — so a push is always
        self-describing, mirroring how a container registry derives the image
        digest from the layer rather than trusting the client.

        The zip is stored as ``<name>-<version>.zip``. Returns a dict with the
        stored ``filename``, whether it was newly ``created``, and the refreshed
        index entry. Raises :class:`SkillValidationError` on an unparseable pack
        and :class:`SkillConflictError` when the (name, version) already exists
        and ``overwrite`` is false.
        """
        with self._lock:
            _validate_archive_limits(src_path)
            loader = SkillLoader()
            try:
                skill: Skill = loader.load(src_path)
            except Exception as exc:  # noqa: BLE001
                raise SkillValidationError(
                    f"uploaded file is not a loadable skill zip: {exc}"
                ) from exc
            finally:
                loader.close()

            name = (skill.name or "").strip()
            version = (skill.version or "").strip()
            if not name:
                raise SkillValidationError(
                    "skill zip has no name (missing SKILL.md frontmatter?)"
                )
            if not version:
                raise SkillValidationError(
                    f"skill '{name}' zip has no version (missing _meta.json?)"
                )
            if not _NAME_RE.fullmatch(name):
                raise SkillValidationError(
                    "skill name must only contain letters, digits, '.', '_' or '-'"
                )
            if not _VERSION_RE.fullmatch(version):
                raise SkillValidationError(
                    "skill version must only contain letters, digits, '.', '_', "
                    "'+' or '-'"
                )
            if expected_name is not None and name != expected_name:
                raise SkillValidationError(
                    f"URL names skill '{expected_name}', but uploaded package "
                    f"declares '{name}'"
                )

            existing = self._versions.get(name, [])
            already = any(v.version == version for v in existing)
            if already and not overwrite:
                raise SkillConflictError(name, version)

            safe_name = _FILENAME_SAFE_RE.sub("-", name).strip("-") or "skill"
            safe_version = _FILENAME_SAFE_RE.sub("-", version).strip("-") or "0"
            dest = self.skills_dir / f"{safe_name}-{safe_version}.zip"

            self.skills_dir.mkdir(parents=True, exist_ok=True)
            # Move within the same directory tree — atomic on the same
            # filesystem; falls back to copy+replace across devices.
            try:
                os.replace(src_path, dest)
            except OSError:
                shutil.copyfile(src_path, dest)
                Path(src_path).unlink(missing_ok=True)

            created = not already
            logger.info(
                "[SkillHub] %s skill %s@%s stored as %s",
                "created" if created else "overwrote",
                name,
                version,
                dest.name,
            )

        # reload() re-acquires the lock, so run it outside the block above.
        self.reload()
        entry = self._entry_for(name) or {
            "name": name,
            "description": skill.description or "",
            "version": version,
            "filename": dest.name,
            "download_url": f"/{name}.zip",
            "available_versions": [version],
        }
        entry["created"] = created
        entry["_stored_filename"] = dest.name
        entry["_stored_version"] = version
        return entry

    def remove(self, name: str, version: str | None = None) -> dict[str, Any]:
        """Delete one version (or every version) of ``name`` from disk.

        Returns the list of removed versions/files. Raises ``KeyError`` when the
        skill (or the requested version) is not present.
        """
        with self._lock:
            vs = self._versions.get(name)
            if not vs:
                raise KeyError(name)
            if version:
                targets = [v for v in vs if v.version == version]
                if not targets:
                    raise KeyError(f"{name}@{version}")
            else:
                targets = list(vs)

            removed_versions: list[str] = []
            removed_files: list[str] = []
            for v in targets:
                try:
                    v.path.unlink(missing_ok=True)
                    removed_versions.append(v.version)
                    removed_files.append(v.path.name)
                except OSError:
                    logger.exception(
                        "[SkillHub] failed to delete %s for %s@%s",
                        v.path,
                        name,
                        v.version,
                    )

        self.reload()
        return {
            "name": name,
            "removed_versions": removed_versions,
            "removed_files": removed_files,
        }

    def seed_from(self, seed_dir: str | Path) -> int:
        """Copy any ``*.zip`` from ``seed_dir`` that is missing in ``skills_dir``.

        Used so a writable (PVC-backed) ``SKILLS_DIR`` is pre-populated with the
        skill packs baked into the image, while pushed skills persist across
        restarts. Existing files in ``skills_dir`` are never overwritten.
        Returns the number of files copied.
        """
        seed = Path(seed_dir).resolve()
        if not seed.is_dir() or seed == self.skills_dir:
            return 0
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        marker = self.skills_dir / ".skill-hub-seeded"
        if marker.exists():
            return 0
        copied = 0
        failed = False
        for src in seed.iterdir():
            if not (src.is_file() and src.suffix.lower() == ".zip"):
                continue
            dest = self.skills_dir / src.name
            if dest.exists():
                continue
            try:
                shutil.copyfile(src, dest)
                copied += 1
            except OSError:
                failed = True
                logger.exception("[SkillHub] failed to seed %s -> %s", src, dest)
        if not failed:
            marker.touch(exist_ok=True)
        if copied:
            logger.info(
                "[SkillHub] seeded %d skill zip(s) from %s into %s",
                copied,
                seed,
                self.skills_dir,
            )
        return copied

    def close(self) -> None:
        """Compatibility hook; reload/ingest close their short-lived loaders."""


index: SkillIndex | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global index
    skills_dir = os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)
    index = SkillIndex(skills_dir)
    # When SKILLS_DIR is a writable volume (e.g. a PVC) distinct from the
    # read-only skills baked into the image, seed the missing packs so the hub
    # still serves the built-ins while pushed skills persist across restarts.
    seed_dir = os.getenv("SKILL_HUB_SEED_DIR", "").strip()
    if seed_dir:
        index.seed_from(seed_dir)
    index.reload()
    if not _push_token():
        logger.warning(
            "[SkillHub] SKILL_HUB_PUSH_TOKEN is not set — push/delete endpoints "
            "are UNAUTHENTICATED. Set it to require a bearer token for writes."
        )
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


def _push_token() -> str:
    return (os.getenv("SKILL_HUB_PUSH_TOKEN") or "").strip()


def _max_upload_bytes() -> int:
    raw = (os.getenv("SKILL_HUB_MAX_UPLOAD_BYTES") or "").strip()
    if not raw:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        n = int(raw)
        return n if n > 0 else DEFAULT_MAX_UPLOAD_BYTES
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES


def _positive_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _validate_archive_limits(path: Path) -> None:
    """Reject zip bombs before SkillLoader extracts an uploaded package."""
    max_extracted = _positive_int_env(
        "SKILL_HUB_MAX_EXTRACTED_BYTES", DEFAULT_MAX_EXTRACTED_BYTES
    )
    max_entries = _positive_int_env(
        "SKILL_HUB_MAX_ARCHIVE_ENTRIES", DEFAULT_MAX_ARCHIVE_ENTRIES
    )
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise SkillValidationError(
                    f"skill zip contains more than {max_entries} entries"
                )
            total = sum(info.file_size for info in entries)
            if total > max_extracted:
                raise SkillValidationError(
                    f"skill zip expands beyond {max_extracted} bytes"
                )
    except SkillValidationError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise SkillValidationError(f"uploaded file is not a valid zip: {exc}") from exc


def _require_push_auth(authorization: str | None, x_token: str | None) -> None:
    """Enforce the push/delete bearer token when ``SKILL_HUB_PUSH_TOKEN`` is set.

    Accepts either ``Authorization: Bearer <token>`` or ``X-Skill-Hub-Token:
    <token>``. When the env var is empty the hub is open for writes (a warning is
    logged at startup) so it stays drop-in for trusted in-cluster use.
    """
    expected = _push_token()
    if not expected:
        return
    presented = ""
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            presented = parts[1].strip()
        else:
            presented = authorization.strip()
    if not presented and x_token:
        presented = x_token.strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid or missing push token")


async def _stream_to_temp(request: Request, dest_dir: Path) -> Path:
    """Stream the raw request body into a temp file under ``dest_dir``.

    Enforces the configured max upload size and rejects an empty body. Returns
    the temp file path (caller owns cleanup).
    """
    max_bytes = _max_upload_bytes()
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".upload-", suffix=".zip", dir=str(dest_dir))
    tmp_path = Path(tmp_name)
    total = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds max size of {max_bytes} bytes",
                    )
                fh.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"failed to read upload: {exc}")
    if total == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="empty request body")
    return tmp_path


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
async def reload_skills(
    authorization: str | None = Header(default=None),
    x_skill_hub_token: str | None = Header(default=None),
) -> SkillListResponse:
    """Rescan the skills directory and rebuild the in-memory index."""
    _require_push_auth(authorization, x_skill_hub_token)
    idx = _require_index()
    idx.reload()
    return await list_skills()


async def _push_skill(
    request: Request,
    overwrite: bool,
    authorization: str | None,
    x_token: str | None,
    expected_name: str | None = None,
) -> PushResponse:
    _require_push_auth(authorization, x_token)
    idx = _require_index()
    tmp_path = await _stream_to_temp(request, idx.skills_dir)
    try:
        entry = idx.ingest(
            tmp_path,
            overwrite=overwrite,
            expected_name=expected_name,
        )
    except SkillValidationError as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except SkillConflictError as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=(
                f"{exc} — pass ?overwrite=true to replace it"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        Path(tmp_path).unlink(missing_ok=True)
        logger.exception("[SkillHub] push failed")
        raise HTTPException(status_code=500, detail=f"push failed: {exc}")

    return PushResponse(
        status="ok",
        created=bool(entry.get("created")),
        name=entry["name"],
        version=entry.get("_stored_version") or entry.get("version") or "",
        filename=entry.get("_stored_filename") or entry.get("filename") or "",
        description=entry.get("description") or "",
        download_url=entry.get("download_url") or f"/{entry['name']}.zip",
        available_versions=entry.get("available_versions") or [],
    )


@app.post("/skills", response_model=PushResponse)
async def push_skill(
    request: Request,
    overwrite: bool = Query(
        default=False,
        description="Replace an existing (name, version) instead of failing with 409.",
    ),
    authorization: str | None = Header(default=None),
    x_skill_hub_token: str | None = Header(default=None),
) -> PushResponse:
    """Push (upload) a skill zip. The request body is the raw ``*.zip`` bytes.

    The skill name and version are read from the zip itself, so the same pack can
    be pushed regardless of the local filename. Analogous to ``docker push``.
    """
    return await _push_skill(request, overwrite, authorization, x_skill_hub_token)


# Alias so callers can also ``PUT`` to the same URL shape they download from.
# The package metadata remains authoritative and must match the URL name.
@app.put("/skills/{name}.zip", response_model=PushResponse)
async def push_skill_named(
    name: str,
    request: Request,
    overwrite: bool = Query(default=True),
    authorization: str | None = Header(default=None),
    x_skill_hub_token: str | None = Header(default=None),
) -> PushResponse:
    clean_name = _validate_skill_name(name)
    return await _push_skill(
        request,
        overwrite,
        authorization,
        x_skill_hub_token,
        expected_name=clean_name,
    )


@app.delete("/skills/{name}.zip", response_model=DeleteResponse)
async def delete_skill(
    name: str,
    version: str | None = Query(
        default=None,
        description="Delete only this version. Omit to delete every version.",
    ),
    authorization: str | None = Header(default=None),
    x_skill_hub_token: str | None = Header(default=None),
) -> DeleteResponse:
    """Delete a skill (or one version of it) from the hub. Like ``docker rmi``."""
    _require_push_auth(authorization, x_skill_hub_token)
    idx = _require_index()
    clean_name = _validate_skill_name(name)
    clean_version = _validate_version(version)
    try:
        result = idx.remove(clean_name, clean_version)
    except KeyError:
        detail = (
            f"skill '{clean_name}' version '{clean_version}' not found"
            if clean_version
            else f"skill '{clean_name}' not found"
        )
        raise HTTPException(status_code=404, detail=detail)
    return DeleteResponse(**result)


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
