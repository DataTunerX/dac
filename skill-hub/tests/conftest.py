"""Shared pytest fixtures for skill-hub tests.

Spins up a temporary multi-namespace skills tree and a FastAPI TestClient.
"""

from __future__ import annotations

import json
import zipfile

import pytest
from fastapi.testclient import TestClient


def make_zip(path, name, version, description="test"):
    """Create a minimal valid skill zip (SKILL.md + _meta.json)."""
    meta = {
        "ownerId": "test-owner",
        "slug": name,
        "version": version,
        "publishedAt": 1767545344344,
    }
    skill_md = (
        "---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        "---\n\n"
        f"# {name} Skill\n\nTest skill for {name} v{version}.\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_meta.json", json.dumps(meta, indent=2))
        zf.writestr("SKILL.md", skill_md)


@pytest.fixture
def skills_dir(tmp_path):
    """Build a multi-namespace skills tree and return its path."""
    base = tmp_path / "skills"
    base.mkdir(parents=True)

    # default namespace lives in skills_dir/default/ (built-in namespace).
    default_dir = base / "default"
    default_dir.mkdir()
    make_zip(default_dir / "base64tool-1.0.0.zip", "base64tool", "1.0.0", "Base64")
    make_zip(default_dir / "github-1.0.0.zip", "github", "1.0.0", "GitHub")
    make_zip(default_dir / "hashgen-1.0.0.zip", "hashgen", "1.0.0", "Hash")
    make_zip(default_dir / "hashgen-1.10.0.zip", "hashgen", "1.10.0", "Hash")
    make_zip(default_dir / "hashgen-2.0.0.zip", "hashgen", "2.0.0", "Hash")

    # team-a namespace (multiple versions)
    team_a = base / "team-a"
    team_a.mkdir()
    make_zip(team_a / "report-1.0.0.zip", "report", "1.0.0", "Report")
    make_zip(team_a / "report-1.1.0.zip", "report", "1.1.0", "Report")
    make_zip(team_a / "notify-1.0.0.zip", "notify", "1.0.0", "Notify")

    # james namespace
    james = base / "james"
    james.mkdir()
    make_zip(james / "personal-1.0.0.zip", "personal", "1.0.0", "Personal")

    return base


@pytest.fixture
def client(skills_dir, monkeypatch):
    """A TestClient with SKILLS_DIR pointing at the temp tree and auto-reload off."""
    from skill_hub.server import app

    monkeypatch.setenv("SKILLS_DIR", str(skills_dir))
    monkeypatch.setenv("SKILLS_AUTO_RELOAD", "0")
    with TestClient(app) as c:
        yield c
