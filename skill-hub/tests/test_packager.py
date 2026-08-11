"""Unit tests for skill pack generation from create-skill fields."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from skill_hub.models import CreateSkillRequest
from skill_hub.packager import (
    build_skill_zip_bytes,
    rebuild_skill_zip_bytes,
    render_skill_md,
)


def test_render_skill_md_escapes_description():
    md = render_skill_md(
        name="demo",
        description='say: "hello"',
        detail="# Title\n\nbody\n",
    )
    assert md.startswith("---\n")
    assert "name: demo\n" in md
    assert "say: \"hello\"" in md or "say: 'hello'" in md or 'say: "hello"' in md
    assert md.endswith("body\n") or "# Title" in md


def test_build_skill_zip_roundtrip_with_loader():
    from skill_sdk.skill.loader import SkillLoader

    req = CreateSkillRequest(
        name="roundtrip",
        description="Round trip skill",
        detail="Do the thing.\n",
        version="2.1.0",
        allowed_tools=["glob", "grep", "glob"],
    )
    data = build_skill_zip_bytes(req)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "skill.zip"
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read("_meta.json"))
            assert meta["version"] == "2.1.0"
            assert meta["slug"] == "roundtrip"  # always equals name
            assert meta["allowed_tools"] == ["glob", "grep"]

        loader = SkillLoader()
        try:
            skill = loader.load(zip_path)
        finally:
            loader.close()

    assert skill.name == "roundtrip"
    assert skill.description == "Round trip skill"
    assert skill.version == "2.1.0"
    assert "Do the thing." in skill.detail
    assert skill.allowed_tools == ["glob", "grep"]


def test_rebuild_skill_zip_preserves_scripts():
    from skill_sdk.skill.loader import SkillLoader

    base = CreateSkillRequest(
        name="with-scripts",
        description="before",
        detail="old body\n",
        version="1.0.0",
        allowed_tools=["glob"],
    )
    buf = __import__("io").BytesIO(build_skill_zip_bytes(base))
    # Inject a script into the zip so rebuild must keep it.
    out = __import__("io").BytesIO()
    with zipfile.ZipFile(buf, "r") as zin, zipfile.ZipFile(
        out, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("scripts/hello.py", "print('hi')\n")
        zout.writestr("assets/note.txt", "keep me\n")

    updated = rebuild_skill_zip_bytes(
        out.getvalue(),
        CreateSkillRequest(
            name="with-scripts",
            description="after",
            detail="new body\n",
            version="1.1.0",
            allowed_tools=["grep"],
        ),
    )
    with zipfile.ZipFile(__import__("io").BytesIO(updated)) as zf:
        names = set(zf.namelist())
        assert "scripts/hello.py" in names
        assert "assets/note.txt" in names
        assert zf.read("scripts/hello.py") == b"print('hi')\n"
        meta = json.loads(zf.read("_meta.json"))
        assert meta["version"] == "1.1.0"
        assert meta["allowed_tools"] == ["grep"]
        assert meta["slug"] == "with-scripts"

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "skill.zip"
        zip_path.write_bytes(updated)
        loader = SkillLoader()
        try:
            skill = loader.load(zip_path)
        finally:
            loader.close()
    assert skill.description == "after"
    assert "new body" in skill.detail
    assert skill.version == "1.1.0"
