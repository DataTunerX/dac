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


def _norm_zip_name(name: str) -> str:
    return name.replace("\\", "/")


def _skill_root_prefix(names: list[str]) -> str:
    """Return zip member prefix for the skill root ('' or 'subdir/')."""
    normalized = [_norm_zip_name(n) for n in names if n and not n.endswith("/")]
    if any(n == "_meta.json" or n.endswith("/_meta.json") for n in normalized):
        for n in normalized:
            if n == "_meta.json":
                return ""
            if n.endswith("/_meta.json"):
                # single nesting level only (same as SkillLoader)
                prefix = n[: -len("_meta.json")]
                if prefix.count("/") == 1:
                    return prefix
        return ""
    return ""


def rebuild_skill_zip_bytes(existing_zip: bytes, req: CreateSkillRequest) -> bytes:
    """Rewrite SKILL.md / _meta.json inside an existing pack; keep other files.

    Used by the edit/update API so ``scripts/`` and resource dirs survive metadata
    changes. ``name`` in the request must match the pack's identity name (caller
    validates). ``version`` may change to publish a new version file.
    """
    name = req.name.strip()
    description = req.description.strip()
    version = req.version.strip()
    detail = req.detail if req.detail is not None else ""

    skill_md = render_skill_md(name=name, description=description, detail=detail)
    new_meta = build_meta_json(
        version=version,
        name=name,
        allowed_tools=req.allowed_tools,
    )

    src = io.BytesIO(existing_zip)
    out = io.BytesIO()
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(
        out, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        names = zin.namelist()
        prefix = _skill_root_prefix(names)
        meta_name = f"{prefix}_meta.json"
        skill_md_name = f"{prefix}SKILL.md"

        # Merge meta: keep unknown keys from the old pack (ownerId, etc.).
        old_meta: dict = {}
        try:
            raw_meta = zin.read(meta_name)
            parsed = json.loads(raw_meta.decode("utf-8"))
            if isinstance(parsed, dict):
                old_meta = parsed
        except (KeyError, ValueError, UnicodeDecodeError):
            old_meta = {}
        merged = {**old_meta, **new_meta}
        # Explicitly clear tools when the editor sends an empty allow-list.
        if not new_meta.get("allowed_tools"):
            merged.pop("allowed_tools", None)
        else:
            merged["allowed_tools"] = new_meta["allowed_tools"]
        merged["version"] = version
        merged["slug"] = name

        written = {meta_name, skill_md_name}
        zout.writestr(
            meta_name, json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        )
        zout.writestr(skill_md_name, skill_md)

        for info in zin.infolist():
            if info.is_dir():
                continue
            member = _norm_zip_name(info.filename)
            if member in written:
                continue
            # Skip duplicate SKILL.md / _meta.json under other casings/paths.
            base = member.rsplit("/", 1)[-1]
            if base in {"SKILL.md", "_meta.json"} and member.startswith(prefix):
                continue
            zout.writestr(info, zin.read(info.filename))

    return out.getvalue()
