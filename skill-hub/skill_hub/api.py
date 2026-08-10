"""HTTP route handlers for skill-hub.

Routes are registered onto the FastAPI app defined in :mod:`skill_hub.server`.
This module keeps the transport layer (FastAPI) separate from the index logic
(:mod:`skill_hub.index`) so each stays small and testable.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .index import SkillIndex
from .models import (
    DEFAULT_NAMESPACE,
    NamespaceExistsResponse,
    NamespaceInfo,
    NamespaceListResponse,
    SkillInfo,
    SkillListResponse,
)
from .validation import validate_namespace, validate_skill_name, validate_version

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MiB safety cap for uploaded zips.


def _require_index() -> SkillIndex:
    """Return the global index, or raise 503 if not initialised yet."""
    from .server import index  # local import to avoid a circular dependency

    if index is None:
        raise HTTPException(status_code=503, detail="skill index not initialised")
    return index


router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/skills", response_model=SkillListResponse)
async def list_default_skills() -> SkillListResponse:
    """List skills in the built-in ``default`` namespace (legacy endpoint)."""
    idx = _require_index()
    skills = idx.list_skills(DEFAULT_NAMESPACE)
    return SkillListResponse(
        count=len(skills),
        skills_dir=str(idx.namespace_dir(DEFAULT_NAMESPACE)),
        skills=[SkillInfo(**s) for s in skills],
    )


@router.post("/skills/reload", response_model=SkillListResponse)
async def reload_skills() -> SkillListResponse:
    """Rescan the skills directory and rebuild the in-memory index."""
    idx = _require_index()
    idx.reload()
    return await list_default_skills()


@router.get("/namespaces", response_model=NamespaceListResponse)
async def list_namespaces() -> NamespaceListResponse:
    """List all namespaces present in the index."""
    idx = _require_index()
    namespaces = [
        NamespaceInfo(id=ns, visibility=idx.namespace_visibility(ns))
        for ns in idx.list_namespaces()
    ]
    return NamespaceListResponse(count=len(namespaces), namespaces=namespaces)


@router.get(
    "/namespaces/{namespace}/exists",
    response_model=NamespaceExistsResponse,
)
async def namespace_exists(namespace: str) -> NamespaceExistsResponse:
    """Check whether a namespace exists.

    Always returns ``200`` with ``{"namespace": "...", "exists": true|false}``.
    Invalid namespace names still return ``400``.
    """
    ns = validate_namespace(namespace)
    idx = _require_index()
    exists = idx.namespace_exists(ns)
    logger.info("[SkillHub] namespace exists check: ns=%s exists=%s", ns, exists)
    return NamespaceExistsResponse(namespace=ns, exists=exists)


@router.post(
    "/namespaces/{namespace}",
    response_model=NamespaceInfo,
    status_code=201,
)
async def create_namespace(namespace: str) -> NamespaceInfo:
    """Explicitly create a namespace.

    Creates the on-disk directory for ``namespace`` and makes it visible in the
    index. If the namespace already exists, a ``409 Conflict`` is returned
    (idempotent creation is NOT assumed — the caller should treat an existing
    namespace as an error to surface a conflict).
    """
    ns = validate_namespace(namespace)
    idx = _require_index()

    # default is the built-in namespace (skills_dir/default/); it is reserved
    # and cannot be created via the API.
    if ns == DEFAULT_NAMESPACE:
        logger.warning("[SkillHub] create namespace rejected: %s is reserved", ns)
        raise HTTPException(
            status_code=400,
            detail=f"namespace '{ns}' is reserved and cannot be created",
        )

    ns_dir = idx.namespace_dir(ns)

    # Reject an existing namespace with 409 so callers can detect the conflict.
    if ns_dir.is_dir():
        logger.warning(
            "[SkillHub] create namespace rejected: %s already exists (dir=%s)",
            ns,
            ns_dir,
        )
        raise HTTPException(
            status_code=409,
            detail=f"namespace '{ns}' already exists",
        )

    # parents=True also creates the parent skills_dir if it somehow doesn't
    # exist yet (e.g. a fresh deployment before any data was laid down).
    ns_dir.mkdir(parents=True)
    logger.info("[SkillHub] created namespace %s (dir=%s)", ns, ns_dir)
    # Reload so an empty namespace shows up in GET /namespaces immediately.
    idx.reload()
    return NamespaceInfo(id=ns, visibility=idx.namespace_visibility(ns))


@router.delete("/namespaces/{namespace}", status_code=204)
async def delete_namespace(namespace: str) -> Response:
    """Delete an empty namespace.

    Only namespaces that contain no skills can be deleted. Non-empty
    namespaces are rejected with ``409 Conflict`` so a namespace is never
    destroyed together with its skills by accident. The built-in ``default``
    namespace cannot be deleted. The index is reloaded immediately so the
    deletion is reflected right away.
    """
    ns = validate_namespace(namespace)
    idx = _require_index()

    # The built-in default namespace always exists and must not be removable.
    if ns == DEFAULT_NAMESPACE:
        logger.warning("[SkillHub] delete namespace rejected: %s is reserved", ns)
        raise HTTPException(
            status_code=400,
            detail=f"namespace '{ns}' is reserved and cannot be deleted",
        )

    ns_dir = idx.namespace_dir(ns)
    if not ns_dir.is_dir():
        logger.warning(
            "[SkillHub] delete namespace rejected: %s does not exist (dir=%s)",
            ns,
            ns_dir,
        )
        raise HTTPException(status_code=404, detail=f"namespace '{ns}' not found")

    # Only empty namespaces can be deleted; refuse to wipe skills implicitly.
    # list_skills returns the indexed skills for the namespace; an empty list
    # means the namespace holds no skill and can be safely removed.
    ns_skills = list(idx.list_skills(ns))
    if ns_skills:
        logger.warning(
            "[SkillHub] delete namespace rejected: %s is not empty (%d skill(s))",
            ns,
            len(ns_skills),
        )
        raise HTTPException(
            status_code=409,
            detail=f"namespace '{ns}' is not empty; delete its skills first",
        )

    # rmdir only succeeds on an empty directory. We already verified there are
    # no indexed skills, so this is the final guard against deleting alongside
    # any stray files that weren't indexed (defensive).
    ns_dir.rmdir()
    logger.info("[SkillHub] deleted namespace %s (dir=%s)", ns, ns_dir)
    idx.reload()
    return Response(status_code=204)


@router.get("/namespaces/{namespace}/skills", response_model=SkillListResponse)
async def list_namespace_skills(namespace: str) -> SkillListResponse:
    """List skills in a specific namespace."""
    ns = validate_namespace(namespace)
    idx = _require_index()
    skills = idx.list_skills(ns)
    return SkillListResponse(
        count=len(skills),
        skills_dir=str(idx.namespace_dir(ns)),
        skills=[SkillInfo(**s) for s in skills],
    )


async def _download_by_namespace(
    namespace: str, name: str, version: str | None
) -> FileResponse:
    idx = _require_index()
    ns = validate_namespace(namespace)
    clean_name = validate_skill_name(name)
    clean_version = validate_version(version)
    zip_path = idx.resolve_zip(ns, clean_name, clean_version)
    if zip_path is None or not zip_path.is_file():
        if clean_version:
            detail = f"skill '{ns}/{clean_name}' version '{clean_version}' not found"
        else:
            detail = f"skill '{ns}/{clean_name}' not found"
        raise HTTPException(status_code=404, detail=detail)

    resolved = idx.resolved_version(ns, clean_name, clean_version) or ""
    logger.info(
        "[SkillHub] download ns=%s name=%s requested_version=%r "
        "resolved_version=%s file=%s",
        ns,
        clean_name,
        clean_version,
        resolved,
        zip_path.name,
    )
    # Serve the original zip filename (which may be e.g. hashgen-1.0.0.zip),
    # but report it as the canonical "<name>.zip" for a stable client filename.
    response = FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"{clean_name}.zip",
    )
    if resolved:
        response.headers["X-Skill-Version"] = resolved
    return response


@router.get("/namespaces/{namespace}/skills/{name}.zip")
async def download_namespace_skill(
    namespace: str,
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> FileResponse:
    return await _download_by_namespace(namespace, name, version)


@router.get("/skills/{name}.zip")
async def download_skill_under_skills(
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> FileResponse:
    return await _download_by_namespace(DEFAULT_NAMESPACE, name, version)


# Legacy root-path alias for default-namespace downloads. Agents now use
# ``GET /skills/{name}.zip``; this endpoint is kept for older callers that
# still issue ``GET {SKILL_HUB_URL}/{name}.zip``.
@router.get("/{name}.zip")
async def download_skill_at_root(
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> FileResponse:
    return await _download_by_namespace(DEFAULT_NAMESPACE, name, version)


@router.post(
    "/namespaces/{namespace}/skills",
    response_model=SkillInfo,
    status_code=201,
)
async def upload_skill(
    namespace: str,
    file: UploadFile = File(...),
) -> SkillInfo:
    """Upload a skill zip to a namespace (multipart ``file``).

    ``name`` and ``version`` are parsed from the zip itself. If a skill with the
    same ``name`` + ``version`` already exists in the namespace, the file is
    overwritten (the on-disk filename is identical, so it replaces in place).
    If the namespace does not exist yet, it is created lazily on the first
    upload (Docker-Hub style). The index is reloaded immediately so the newly
    uploaded skill is available right away.
    """
    ns = validate_namespace(namespace)
    idx = _require_index()

    # Lazily create the namespace directory on first upload. This mirrors the
    # Docker-Hub model: pushing to a not-yet-existing repo initialises it rather
    # than failing. The directory becomes a namespace as soon as it exists, and
    # the immediate reload below makes it visible right away.
    ns_dir = idx.namespace_dir(ns)
    if not ns_dir.is_dir():
        ns_dir.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "[SkillHub] upload auto-created namespace %s (dir=%s)",
            ns,
            ns_dir,
        )

    # Read and size-limit the upload.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload too large (limit {MAX_UPLOAD_BYTES} bytes)",
        )

    # Parse the zip to validate it and extract name/version.
    name, version = _parse_upload_zip(data, file.filename or "upload.zip")

    # Deterministic target filename so re-upload of the same name+version overwrites.
    target = ns_dir / f"{name}-{version}.zip"
    target.write_bytes(data)
    logger.info(
        "[SkillHub] uploaded skill ns=%s name=%s version=%s file=%s size=%d",
        ns,
        name,
        version,
        target.name,
        len(data),
    )

    # Reload immediately so the uploaded skill is addressable right away
    # (do not wait for the watchfiles debounce).
    idx.reload()

    info = _find_latest(idx, ns, name)
    if info is None:
        # Shouldn't happen after a successful reload, but guard defensively.
        raise HTTPException(
            status_code=500,
            detail=f"upload succeeded but skill '{ns}/{name}' not indexed",
        )
    return SkillInfo(**info)


@router.delete(
    "/namespaces/{namespace}/skills/{name}.zip",
    status_code=204,
)
async def delete_namespace_skill(
    namespace: str,
    name: str,
    version: str | None = Query(
        default=None,
        description="Optional skill version. Defaults to the latest indexed version.",
    ),
) -> Response:
    """Delete a skill (or a specific version) from a namespace.

    When ``version`` is omitted, the latest version is deleted. When it is the
    last remaining version, the skill disappears entirely. The index is reloaded
    immediately so the deletion is reflected right away.
    """
    ns = validate_namespace(namespace)
    clean_name = validate_skill_name(name)
    clean_version = validate_version(version)
    idx = _require_index()

    zip_path = idx.resolve_zip(ns, clean_name, clean_version)
    if zip_path is None or not zip_path.is_file():
        if clean_version:
            detail = f"skill '{ns}/{clean_name}' version '{clean_version}' not found"
        else:
            detail = f"skill '{ns}/{clean_name}' not found"
        raise HTTPException(status_code=404, detail=detail)

    resolved = idx.resolved_version(ns, clean_name, clean_version) or ""
    zip_path.unlink(missing_ok=True)
    logger.info(
        "[SkillHub] deleted skill ns=%s name=%s resolved_version=%s file=%s",
        ns,
        clean_name,
        resolved,
        zip_path.name,
    )
    idx.reload()
    return Response(status_code=204)


def _parse_upload_zip(data: bytes, original_filename: str) -> tuple[str, str]:
    """Validate an uploaded zip and return ``(name, version)``.

    Uses ``SkillLoader`` to parse the archive (which also validates the zip is not
    malformed / unsafe). The ``name`` comes from ``SKILL.md`` frontmatter and
    ``version`` from ``_meta.json``.
    """
    from skill_sdk.skill.loader import SkillLoader

    loader = SkillLoader()
    try:
        with tempfile.TemporaryDirectory(prefix="skillhub_upload_") as tmp:
            tmp_path = Path(tmp) / "upload.zip"
            tmp_path.write_bytes(data)
            skill = loader.load(tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid skill zip: {exc}")
    finally:
        loader.close()

    name = (skill.name or "").strip()
    version = (skill.version or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="skill has empty name")
    if not version:
        raise HTTPException(status_code=400, detail="skill has empty version")
    # Reuse the same char validation as the download path so the name/version can
    # be safely used in a filename.
    name = validate_skill_name(name)
    version = validate_version(version) or ""
    return name, version


def _find_latest(idx: SkillIndex, namespace: str, name: str) -> dict | None:
    """Return the latest-version summary dict for ``(namespace, name)`` or None."""
    for s in idx.list_skills(namespace):
        if s["name"] == name:
            return s
    return None


def register_exception_handlers(app) -> None:
    """Attach a uniform JSON error body for HTTPException on the app."""

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(_request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "status_code": exc.status_code},
        )
