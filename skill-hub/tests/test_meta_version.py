"""Version must come from ``_meta.json``, never from the zip filename.

Skill zips may have a filename with NO version (e.g. ``code_execution.zip``)
while their ``_meta.json`` declares ``version: "1.0.0"``. The index must key on
the loader-parsed ``version`` (from ``_meta.json``), not the filename.
"""

from __future__ import annotations

from skill_hub.index import SkillIndex
from tests.conftest import make_zip


def test_version_without_version_in_filename(tmp_path):
    """A zip named ``name.zip`` (no version) still indexes by _meta.json version."""
    # filename has no version at all
    make_zip(tmp_path / "code_execution.zip", "code_execution", "1.0.0")
    # filename has a version that differs from _meta.json; _meta.json must win
    make_zip(tmp_path / "hashgen-9.9.9.zip", "hashgen", "2.0.0")

    idx = SkillIndex(tmp_path)
    idx.reload()
    snap = idx.snapshot()

    assert ("default", "code_execution") in snap
    assert snap[("default", "code_execution")] == frozenset({"1.0.0"})

    # filename says 9.9.9 but _meta.json says 2.0.0 -> 2.0.0 wins
    assert ("default", "hashgen") in snap
    assert snap[("default", "hashgen")] == frozenset({"2.0.0"})

    # resolve by name works regardless of filename
    zp = idx.resolve_zip("default", "code_execution")
    assert zp is not None and zp.name == "code_execution.zip"


def test_real_skills_no_version_filenames():
    """Commercial skills whose filenames lack a version still index correctly."""
    real = __import__("pathlib").Path(__file__).resolve().parents[1] / "skills"
    if not real.is_dir():
        return  # tests may run without the bundled skills/ dir
    idx = SkillIndex(real)
    idx.reload()
    snap = idx.snapshot()
    for name in ("code_execution", "read-code", "web_fetch", "tavily-search"):
        key = ("default", name)
        assert key in snap, f"{name} should be indexed from _meta.json"
        assert snap[key] == frozenset({"1.0.0"}), (
            f"{name} version should come from _meta.json (1.0.0), got {snap[key]}"
        )
