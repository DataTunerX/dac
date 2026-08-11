"""Input validation helpers for the skill-hub HTTP API."""

from __future__ import annotations

import re

from fastapi import HTTPException

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def validate_namespace(namespace: str) -> str:
    """Validate a namespace identifier and return it trimmed.

    Namespaces must match ``^[a-z0-9][a-z0-9._-]*$`` — lowercase letter or digit
    first, then letters/digits/``.``/``_``/``-``. This keeps the namespace usable
    as a safe directory name and avoids path traversal.
    """
    ns = (namespace or "").strip()
    if not ns:
        raise HTTPException(status_code=400, detail="namespace must not be empty")
    if not _NAMESPACE_RE.fullmatch(ns):
        raise HTTPException(
            status_code=400,
            detail=(
                "namespace must start with a lowercase letter or digit and only "
                "contain lowercase letters, digits, '.', '_' or '-'"
            ),
        )
    return ns


def validate_skill_name(name: str) -> str:
    """Validate a skill ``name`` and return it trimmed.

    Allowed characters: letters, digits, ``.``, ``_``, ``-``. This is the same
    contract as the legacy ``_NAME_RE`` so path segments stay filesystem-safe.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="skill name must not be empty")
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail=("skill name must only contain letters, digits, '.', '_' or '-'"),
        )
    return name


def validate_version(version: str | None) -> str | None:
    """Validate an optional version string for download/delete.

    ``None``/empty means "latest". When provided it must match the version
    character contract (letters, digits, ``.``, ``_``, ``+``, ``-``).
    """
    if version is None:
        return None
    version = version.strip()
    if not version:
        return None
    if not _VERSION_RE.fullmatch(version):
        raise HTTPException(
            status_code=400,
            detail=("version must only contain letters, digits, '.', '_', '+' or '-'"),
        )
    return version
