"""Build a valid skill zip pack from structured create-skill fields.

The pack layout matches what :class:`skill_sdk.skill.loader.SkillLoader` expects:

- ``_meta.json`` — ``version`` (required), ``slug`` (= ``name``), optional ``allowed_tools``
- ``SKILL.md`` — YAML frontmatter with ``name`` + ``description``, body as ``detail``
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Sequence

import yaml

from .models import CreateSkillRequest


def render_skill_md(*, name: str, description: str, detail: str) -> str:
    """Render ``SKILL.md`` with YAML frontmatter + markdown body."""
    # Dump only the frontmatter mapping so description escaping stays correct
    # (quotes, colons, unicode, etc.).
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip() + "\n"
    body = (detail or "").lstrip("\n")
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{frontmatter}---\n\n{body}"


def build_meta_json(
    *,
    version: str,
    name: str,
    allowed_tools: Sequence[str] | None,
) -> dict:
    """Build the ``_meta.json`` object written into the pack.

    ``slug`` is always set to ``name``. skill_sdk/skill-hub identity uses
    ``SKILL.md`` name + ``version``; slug is pack metadata only and must stay
    aligned with name for create-from-form packs.
    """
    meta: dict = {"version": version, "slug": name}
    tools = [t.strip() for t in (allowed_tools or []) if t and str(t).strip()]
    if tools:
        # De-dupe while preserving order.
        seen: set[str] = set()
        ordered: list[str] = []
        for t in tools:
            if t not in seen:
                seen.add(t)
                ordered.append(t)
        meta["allowed_tools"] = ordered
    return meta


def build_skill_zip_bytes(req: CreateSkillRequest) -> bytes:
    """Return a zip archive (bytes) for the given create request."""
    name = req.name.strip()
    description = req.description.strip()
    version = req.version.strip()
    detail = req.detail if req.detail is not None else ""

    skill_md = render_skill_md(name=name, description=description, detail=detail)
    meta = build_meta_json(
        version=version,
        name=name,
        allowed_tools=req.allowed_tools,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_meta.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()
