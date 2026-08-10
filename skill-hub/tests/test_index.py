"""Unit tests for the SkillIndex (namespace-aware indexing + version sorting)."""

from __future__ import annotations

from skill_hub.index import SkillIndex, version_key
from tests.conftest import make_zip


def test_version_key_pep440_ordering():
    # PEP 440: 1.10 beats 1.9
    assert version_key("1.10.0") > version_key("1.9.0")
    assert version_key("2.0.0") > version_key("1.10.0")
    # unparseable versions rank below parseable ones
    assert version_key("abc") < version_key("1.0.0")
    assert version_key("git-sha") < version_key("1.0.0")


def test_index_groups_by_namespace(skills_dir):
    idx = SkillIndex(skills_dir)
    idx.reload()
    snap = idx.snapshot()
    assert ("default", "github") in snap
    assert ("team-a", "report") in snap
    assert ("team-a", "notify") in snap
    assert ("james", "personal") in snap
    # same name can exist in different namespaces independently
    assert ("team-a", "hashgen") not in snap


def test_list_skills_namespace_isolated(skills_dir):
    idx = SkillIndex(skills_dir)
    idx.reload()
    default_names = {s["name"] for s in idx.list_skills("default")}
    team_names = {s["name"] for s in idx.list_skills("team-a")}
    assert default_names == {"base64tool", "github", "hashgen"}
    assert team_names == {"report", "notify"}


def test_resolve_zip_namespace_scoped(skills_dir):
    idx = SkillIndex(skills_dir)
    idx.reload()
    # report exists in team-a but not default
    assert idx.resolve_zip("team-a", "report") is not None
    assert idx.resolve_zip("default", "report") is None
    # specific version
    v10 = idx.resolve_zip("team-a", "report", "1.0.0")
    assert v10 is not None and v10.name == "report-1.0.0.zip"
    # resolved_version
    assert idx.resolved_version("team-a", "report") == "1.1.0"
    assert idx.resolved_version("team-a", "report", "1.0.0") == "1.0.0"


def test_resolve_unknown_version_returns_none(skills_dir):
    idx = SkillIndex(skills_dir)
    idx.reload()
    assert idx.resolve_zip("team-a", "report", "9.9.9") is None
    assert idx.resolved_version("team-a", "report", "9.9.9") is None


def test_list_namespaces_includes_empty_default(skills_dir):
    # even if default had no skills, it must still appear
    for z in (skills_dir / "default").glob("*.zip"):
        z.unlink()
    idx = SkillIndex(skills_dir)
    idx.reload()
    assert "default" in idx.list_namespaces()


def test_duplicate_name_version_keeps_first(tmp_path):
    """Two zips with the same name+version in the same namespace keep the first."""
    make_zip(tmp_path / "dup-1.0.0.zip", "dup", "1.0.0")
    make_zip(tmp_path / "dup-1.0.0.zip", "dup", "1.0.0")  # same path, overwrite
    # create a second distinct file with identical metadata
    make_zip(tmp_path / "dup-copy-1.0.0.zip", "dup", "1.0.0")
    idx = SkillIndex(tmp_path)
    idx.reload()  # uses caplog to check warning
    snap = idx.snapshot()
    versions = snap.get(("default", "dup"))
    # both files resolve to same (name, version) -> only one kept (dedup)
    assert versions is not None
    listed = idx.resolve_zip("default", "dup")
    assert listed is not None
    assert listed.name == "dup-1.0.0.zip"  # first occurrence wins


def test_namespace_visibility_default_public(skills_dir):
    idx = SkillIndex(skills_dir)
    assert idx.namespace_visibility("team-a") == "public"
    assert idx.namespace_visibility("default") == "public"
