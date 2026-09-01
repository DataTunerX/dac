#!/usr/bin/env python3
"""Scaffold a skill package and publish it to skill-hub.

  python3 create_skill.py --name weather-report \
      --description "Answer weather questions for a city." \
      --detail-file body.md [--script helper.py] [--version 1.0.0]

Prints one JSON object describing what was published.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from appgen_common import (  # noqa: E402
    SKILL_HUB_URL, SKILL_NAMESPACE, AppGenError, http_json, skill_exists, validate_name)

FRONT_MATTER = """---
name: {name}
description: {description}
---

# {name}

{detail}
"""


def build_zip(name: str, version: str, skill_md: str, scripts: dict[str, str]) -> bytes:
    """Pack the layout skill-hub expects: <name>/SKILL.md plus <name>/_meta.json.

    _meta.json is required by the upload endpoint and skill-hub does not
    generate it -- a package without it cannot be published at all.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/SKILL.md", skill_md)
        zf.writestr(f"{name}/_meta.json",
                    json.dumps({"version": version, "slug": name}, indent=2) + "\n")
        for rel, content in scripts.items():
            zf.writestr(f"{name}/scripts/{rel}", content)
    return buf.getvalue()


def upload(name: str, version: str, archive: bytes) -> dict:
    """Publish via multipart POST. Same (namespace, name, version) overwrites."""
    boundary = "----appgen-boundary-7d41b2"
    filename = f"{name}-{version}.zip"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/zip\r\n\r\n",
        archive,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return http_json(
        f"{SKILL_HUB_URL}/namespaces/{SKILL_NAMESPACE}/skills",
        method="POST", body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="skill name, e.g. weather-report")
    ap.add_argument("--description", required=True,
                    help="one sentence; it becomes the agent card text used for capability routing")
    ap.add_argument("--detail", default="", help="skill body in markdown")
    ap.add_argument("--detail-file", default="", help="read the body from this file instead")
    ap.add_argument("--script", action="append", default=[],
                    help="path to a script to ship under scripts/; repeatable")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--overwrite", action="store_true",
                    help="allow replacing an existing skill of the same name")
    args = ap.parse_args()

    try:
        name = validate_name(args.name, "skill name")
        description = (args.description or "").strip()
        if not description:
            raise AppGenError("--description is required")

        if skill_exists(name) and not args.overwrite:
            raise AppGenError(
                f"skill {name!r} already exists in namespace {SKILL_NAMESPACE}; "
                "pass --overwrite to replace it"
            )

        detail = args.detail
        if args.detail_file:
            p = Path(args.detail_file)
            if not p.is_file():
                raise AppGenError(f"--detail-file not found: {p}")
            detail = p.read_text(encoding="utf-8")
        if not detail.strip():
            detail = f"{description}\n"

        scripts: dict[str, str] = {}
        for s in args.script:
            p = Path(s)
            if not p.is_file():
                raise AppGenError(f"--script not found: {p}")
            scripts[p.name] = p.read_text(encoding="utf-8")

        skill_md = FRONT_MATTER.format(name=name, description=description, detail=detail)
        info = upload(name, args.version, build_zip(name, args.version, skill_md, scripts))
    except AppGenError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "ok": True,
        "skill": info.get("name", name),
        "version": info.get("version", args.version),
        "namespace": SKILL_NAMESPACE,
        "scripts": sorted(scripts),
        "next": "run create_agent.py --skill %s to create an agent that loads it" % name,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
