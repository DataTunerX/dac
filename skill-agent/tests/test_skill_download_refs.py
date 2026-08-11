"""Unit tests for skill_download_refs (SKILLS env parsing + download paths)."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python -m pytest` from skill-agent root or agent/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.skill_download_refs import (  # noqa: E402
    SkillRef,
    dedupe_refs,
    parse_skills_env,
)


def test_parse_legacy_string_array():
    refs = parse_skills_env('["weather","web_fetch"]')
    assert [r.name for r in refs] == ["weather", "web_fetch"]
    assert all(r.namespace == "default" and r.version == "" for r in refs)


def test_parse_object_array_with_namespace_version():
    raw = (
        '[{"namespace":"team-a","name":"report","version":"1.0.0"},'
        '{"namespace":"default","name":"weather","version":""}]'
    )
    refs = parse_skills_env(raw)
    assert len(refs) == 2
    assert refs[0] == SkillRef(name="report", namespace="team-a", version="1.0.0")
    assert refs[1] == SkillRef(name="weather", namespace="default", version="")


def test_download_path_default_latest():
    assert SkillRef(name="weather").download_path() == "/skills/weather.zip"


def test_download_path_default_versioned():
    assert (
        SkillRef(name="weather", version="1.2.0").download_path()
        == "/skills/weather.zip?version=1.2.0"
    )


def test_download_path_non_default_namespace():
    assert (
        SkillRef(name="report", namespace="team-a").download_path()
        == "/namespaces/team-a/skills/report.zip"
    )
    assert (
        SkillRef(name="report", namespace="team-a", version="2.0.0").download_path()
        == "/namespaces/team-a/skills/report.zip?version=2.0.0"
    )


def test_dedupe_by_name():
    refs = dedupe_refs(
        [
            SkillRef(name="weather", namespace="default"),
            SkillRef(name="weather", namespace="team-a"),
        ]
    )
    assert len(refs) == 1
    assert refs[0].namespace == "default"
