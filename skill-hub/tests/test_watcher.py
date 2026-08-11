"""Tests for the auto-reload watcher (file watching + index diff logging)."""

from __future__ import annotations

import asyncio

import pytest

from skill_hub.index import SkillIndex
from skill_hub.watcher import log_index_diff, watch_skills_dir
from tests.conftest import make_zip


def test_log_index_diff_new_removed_changed(caplog):
    before = {
        ("default", "a"): frozenset({"1.0.0"}),
        ("default", "b"): frozenset({"1.0.0"}),
        ("default", "c"): frozenset({"1.0.0"}),
    }
    after = {
        ("default", "b"): frozenset({"1.0.0", "2.0.0"}),  # changed
        ("default", "c"): frozenset({"1.0.0"}),  # unchanged
        ("team-a", "new"): frozenset({"1.0.0"}),  # added
        # "a" removed
    }
    with caplog.at_level("INFO"):
        log_index_diff(before, after)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "NEW skill team-a/new" in text
    assert "REMOVED skill default/a" in text
    assert "CHANGED skill default/b" in text


def test_log_index_diff_unchanged(caplog):
    state = {("default", "a"): frozenset({"1.0.0"})}
    with caplog.at_level("INFO"):
        log_index_diff(state, state)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "index unchanged" in text


def test_watch_ignores_non_zip(tmp_path, monkeypatch):
    """Only *.zip files trigger a reload; other changes are ignored."""
    make_zip(tmp_path / "a-1.0.0.zip", "a", "1.0.0")
    idx = SkillIndex(tmp_path)
    idx.reload()

    async def fake_awatch(*args, **kwargs):
        # yield a non-zip change first (ignored), then a zip change (triggers)
        yield [(1, str(tmp_path / "notes.txt"))]
        # create the actual zip on disk so reload can index it
        make_zip(tmp_path / "b-1.0.0.zip", "b", "1.0.0")
        yield [(1, str(tmp_path / "b-1.0.0.zip"))]
        await asyncio.sleep(3600)

    monkeypatch.setattr("skill_hub.watcher.awatch", fake_awatch)

    async def run():
        task = asyncio.create_task(watch_skills_dir(idx))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    # After the zip change (added b), the index should contain b.
    assert ("default", "b") in idx.snapshot()


def test_watch_cancelled_cleanly(tmp_path, monkeypatch):
    make_zip(tmp_path / "a-1.0.0.zip", "a", "1.0.0")
    idx = SkillIndex(tmp_path)
    idx.reload()

    async def fake_awatch(*args, **kwargs):
        while True:
            await asyncio.sleep(3600)
            yield []

    monkeypatch.setattr("skill_hub.watcher.awatch", fake_awatch)

    async def run():
        task = asyncio.create_task(watch_skills_dir(idx))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
