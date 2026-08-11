#!/usr/bin/env python3
"""Unit + orchestrator-agent smoke tests for readline_in_range windowing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

from skill_sdk.tool.readline_in_range_plugin import (  # noqa: E402
    DEFAULT_MAX_READ_LINES,
    ReadlineInRangePlugin,
    SourceReadPolicyError,
    WindowTooLargeError,
    check_source_readline_policy,
    readline_in_range,
)

ORCH = Path("/Users/james/daocloud/code/dac/orchestrator-agent")
ORCH_LARGE = (
    ORCH / "orchestrator_agent" / "orchestrator_agent_semantic_group.py"
)
ORCH_MEDIUM = (
    ORCH / "orchestrator_agent" / "orchestrator_agent_semantic_domain.py"
)


def _write_lines(path: Path, n: int) -> None:
    path.write_text("".join(f"line-{i}\n" for i in range(1, n + 1)), encoding="utf-8")


class TestReadlineWindowing:
    def test_small_explicit_window(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, 50)
        r = readline_in_range(str(f), start=10, end=19)
        assert r.start == 10
        assert r.end == 19
        assert r.window_lines == 10
        assert r.next_start == 20
        assert "10|" in r.content
        assert "line-10" in r.content

    def test_end_none_caps_to_max_lines(self, tmp_path: Path):
        f = tmp_path / "big.py"
        _write_lines(f, 2000)
        r = readline_in_range(
            str(f), start=1, end=None, max_lines=500, skip_source_policy=True
        )
        assert r.start == 1
        assert r.end == 500
        assert r.window_lines == 500
        assert r.truncated_to_window is True
        assert r.next_start == 501
        assert r.max_lines == 500

    def test_end_none_short_file_no_next(self, tmp_path: Path):
        f = tmp_path / "short.py"
        _write_lines(f, 40)
        r = readline_in_range(str(f), start=1, end=None, max_lines=500)
        assert r.start == 1
        assert r.end == 40
        assert r.truncated_to_window is False
        assert r.next_start is None

    def test_window_too_large_raises(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, 100)
        with pytest.raises(WindowTooLargeError) as ei:
            readline_in_range(str(f), start=1, end=600, max_lines=500)
        assert "max_lines=500" in str(ei.value)
        assert "end=500" in str(ei.value)

    def test_middle_slice_on_large_file(self, tmp_path: Path):
        f = tmp_path / "huge.py"
        _write_lines(f, 20_000)
        r = readline_in_range(str(f), start=10_000, end=10_049, max_lines=500)
        assert r.start == 10_000
        assert r.end == 10_049
        assert "line-10000" in r.content
        assert "line-10049" in r.content
        assert r.next_start == 10_050

    def test_plugin_rejects_huge_window(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, 100)
        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=1, end=5000)
        data = json.loads(raw)
        assert "error" in data
        assert data["error_code"] == 400
        assert "max_lines" in data["error"]

    def test_plugin_end_none_returns_metadata(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, DEFAULT_MAX_READ_LINES + 300)
        plug = ReadlineInRangePlugin()
        # Without focus, large from-start reads are blocked by source policy.
        raw = plug.execute(file_path=str(f), start=1)
        data = json.loads(raw)
        assert data.get("blocked_by_policy") is True
        assert "unfocused" in data["error"].lower() or "near-whole" in data["error"].lower()

        # With focused=True (runner injects after documentSymbol focus), allowed.
        raw2 = plug.execute(file_path=str(f), start=1, focused=True)
        data2 = json.loads(raw2)
        assert "error" not in data2
        assert data2["end"] == DEFAULT_MAX_READ_LINES
        assert data2["next_start"] == DEFAULT_MAX_READ_LINES + 1
        assert data2["truncated_to_window"] is True
        assert data2["max_lines"] == DEFAULT_MAX_READ_LINES

    def test_plugin_undersized_window_adds_hint(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, 2000)
        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=100, end=224)
        data = json.loads(raw)
        assert "error" not in data
        assert data["window_lines"] == 125
        assert "hint" in data
        assert "max_lines" in data["hint"]

    def test_plugin_near_max_window_no_hint(self, tmp_path: Path):
        f = tmp_path / "a.py"
        _write_lines(f, 2000)
        plug = ReadlineInRangePlugin()
        # Half of max_lines should not trigger (threshold is window*2 < max)
        half = DEFAULT_MAX_READ_LINES // 2
        raw = plug.execute(file_path=str(f), start=200, end=200 + half - 1)
        data = json.loads(raw)
        assert "error" not in data
        assert "hint" not in data


class TestSourceReadPolicy:
    def test_near_whole_file_rejected(self, tmp_path: Path):
        f = tmp_path / "server.py"
        _write_lines(f, 356)
        with pytest.raises(SourceReadPolicyError) as ei:
            check_source_readline_policy(str(f), 1, 356, focused=True)
        assert "near-whole-file" in str(ei.value)

    def test_small_file_whole_read_ok(self, tmp_path: Path):
        f = tmp_path / "util.py"
        _write_lines(f, 80)
        check_source_readline_policy(str(f), 1, 80, focused=False)

    def test_unfocused_large_from_start_rejected(self, tmp_path: Path):
        f = tmp_path / "mod.py"
        _write_lines(f, 400)
        with pytest.raises(SourceReadPolicyError) as ei:
            check_source_readline_policy(str(f), 1, 200, focused=False)
        assert "unfocused" in str(ei.value).lower()

    def test_focused_method_span_ok(self, tmp_path: Path):
        f = tmp_path / "mod.py"
        _write_lines(f, 400)
        check_source_readline_policy(str(f), 100, 180, focused=True)

    def test_markdown_exempt(self, tmp_path: Path):
        f = tmp_path / "README.md"
        _write_lines(f, 500)
        check_source_readline_policy(str(f), 1, 500, focused=False)

    def test_plugin_blocks_whole_server_dump(self, tmp_path: Path):
        f = tmp_path / "server.py"
        _write_lines(f, 356)
        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=1, end=356, focused=True)
        data = json.loads(raw)
        assert data.get("blocked_by_policy") is True
        assert "near-whole-file" in data["error"]

@pytest.mark.skipif(not ORCH_LARGE.is_file(), reason="orchestrator-agent not present")
class TestOrchestratorAgentFiles:
    def test_semantic_group_end_none_one_window(self):
        r = readline_in_range(
            str(ORCH_LARGE),
            start=1,
            end=None,
            max_lines=500,
            skip_source_policy=True,
        )
        assert r.window_lines == 500
        assert r.next_start == 501
        assert r.truncated_to_window is True
        # Must not dump the whole 8k+ file
        assert r.content.count("\n") < 600

    def test_semantic_group_rejects_full_file_span(self):
        with pytest.raises((WindowTooLargeError, SourceReadPolicyError)):
            readline_in_range(str(ORCH_LARGE), start=1, end=8568, max_lines=500)

    def test_semantic_group_middle_window(self):
        r = readline_in_range(str(ORCH_LARGE), start=4000, end=4200, max_lines=500)
        assert r.start == 4000
        assert r.end == 4200
        assert r.window_lines == 201
        assert r.next_start == 4201

    def test_semantic_domain_plugin_path(self):
        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(ORCH_MEDIUM), start=100, end=None, focused=True)
        data = json.loads(raw)
        assert "error" not in data
        assert data["start"] == 100
        assert data["window_lines"] == DEFAULT_MAX_READ_LINES
        assert data["next_start"] == 100 + DEFAULT_MAX_READ_LINES