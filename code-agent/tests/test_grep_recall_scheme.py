"""Tests for grep recall scheme resolution and skill snippet extraction."""

from __future__ import annotations

from agent.tools.skill_read_code_recall import (
    SCHEME_METADATA_LOCAL,
    SCHEME_READ_CODE,
    extract_code_snippets_from_tool_history,
    resolve_grep_recall_scheme,
)


def test_default_scheme_is_read_code_skill(monkeypatch):
    monkeypatch.delenv("GREP_RECALL_SCHEME", raising=False)
    assert resolve_grep_recall_scheme() == SCHEME_READ_CODE


def test_env_metadata_local_scheme(monkeypatch):
    monkeypatch.setenv("GREP_RECALL_SCHEME", "metadata_local")
    assert resolve_grep_recall_scheme() == SCHEME_METADATA_LOCAL


def test_legacy_use_local_grep_forces_metadata_local():
    assert (
        resolve_grep_recall_scheme(use_local_grep=True)
        == SCHEME_METADATA_LOCAL
    )


def test_explicit_read_code_scheme():
    assert resolve_grep_recall_scheme(explicit="read_code_skill") == SCHEME_READ_CODE


def test_extract_snippets_from_readline_tool_history():
    history = [
        {
            "tool": "readline_in_range",
            "args": {"file_path": "pkg/main.py", "start": 1, "end": 3},
            "result": '{"content": "class Foo:\\n    pass\\n", "start": 1, "end": 3}',
        }
    ]
    rows = extract_code_snippets_from_tool_history(
        history, query="find Foo", code_paths=["/tmp/repo"]
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "skill_read_code"
    assert rows[0]["name"] == "Foo"
