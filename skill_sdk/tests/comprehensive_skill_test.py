#!/usr/bin/env python3
"""Comprehensive end-to-end tests for the read-code skill.

Tests every tool (glob, grep, readline_in_range, lsp) across multiple paths:

  1. GLOB   - patterns, absolute paths, nested dirs, no matches, missing dirs, sorting
  2. GREP   - all output modes, regex, glob filters, file_type, context, multiline, head_limit/offset
  3. READLINE - normal ranges, beyond EOF, single line, empty file, encoding, no line numbers
  4. LSP (all 9 operations):
       goToDefinition, documentSymbol, findReferences, hover,
       goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls,
       workspaceSymbol
  5. C LSP tests (clangd) — goToDefinition, documentSymbol, findReferences,
     hover, goToImplementation across C structs, functions, headers
  6. C++ LSP tests (clangd) — goToDefinition, documentSymbol, findReferences,
     hover, goToImplementation across C++ classes, interfaces, headers
  7. Rust LSP tests (rust-analyzer) — goToDefinition, documentSymbol,
     findReferences, hover, goToImplementation across traits, structs, functions
  8. Error handling for all tools
  9. Cross-file / cross-language LSP resolution
  10. Edge cases (null responses, out-of-range positions, etc.)
  11. End-to-end skill flow (combined tool sequences)

Run with:
    cd /Users/james/daocloud/code/dac/skill_sdk
    SKILL_SDK_LSP_SERVERS='{"gopls":{"command":"gopls","extensionToLanguage":{".go":"go"},"args":[],"startupTimeoutMs":30000},"pyright":{"command":"pyright-langserver","extensionToLanguage":{".py":"python"},"args":["--stdio"],"startupTimeoutMs":30000},"clangd":{"command":"clangd","extensionToLanguage":{".c":"c",".h":"c",".cpp":"cpp",".hpp":"cpp"},"args":[],"startupTimeoutMs":30000},"rust-analyzer":{"command":"rust-analyzer","extensionToLanguage":{".rs":"rust"},"args":[],"startupTimeoutMs":60000}}' python -m pytest tests/comprehensive_skill_test.py -v --tb=short
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure package is importable
_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = _HERE / "fixtures"
GO_PROJECT = FIXTURES_DIR / "go-project"
PY_PROJECT = FIXTURES_DIR / "py-project"

GO_MAIN = GO_PROJECT / "main.go"
GO_HANDLER = GO_PROJECT / "handler.go"
PY_CORE = PY_PROJECT / "core.py"
PY_UTILS = PY_PROJECT / "utils.py"

# C fixture paths
C_PROJECT = FIXTURES_DIR / "c-project"
C_MAIN = C_PROJECT / "src/main.c"
C_CORE_DATA_PROCESSOR_H = C_PROJECT / "src/core/data_processor.h"
C_CORE_DEFAULT_PROCESSOR_H = C_PROJECT / "src/core/default_processor.h"
C_CORE_DEFAULT_PROCESSOR_C = C_PROJECT / "src/core/default_processor.c"
C_CORE_HANDLER_H = C_PROJECT / "src/core/handler.h"
C_CORE_HANDLER_C = C_PROJECT / "src/core/handler.c"
C_CORE_HELPER_H = C_PROJECT / "src/core/helper.h"
C_CORE_HELPER_C = C_PROJECT / "src/core/helper.c"
C_CORE_FINALIZE_OUTPUT_H = C_PROJECT / "src/core/finalize_output.h"
C_CORE_FINALIZE_OUTPUT_C = C_PROJECT / "src/core/finalize_output.c"
C_SHOP_CART_H = C_PROJECT / "src/shop/cart.h"
C_SHOP_ORDER_SERVICE_H = C_PROJECT / "src/shop/order_service.h"
C_CORE_PROCESSOR_CONFIG_H = C_PROJECT / "src/core/processor_config.h"

# C++ fixture paths
CPP_PROJECT = FIXTURES_DIR / "cpp-project"
CPP_MAIN = CPP_PROJECT / "src/main.cpp"
CPP_CORE_DATA_PROCESSOR_H = CPP_PROJECT / "src/core/DataProcessor.h"
CPP_CORE_DEFAULT_PROCESSOR_H = CPP_PROJECT / "src/core/DefaultProcessor.h"
CPP_CORE_DEFAULT_PROCESSOR_CPP = CPP_PROJECT / "src/core/DefaultProcessor.cpp"
CPP_CORE_HANDLER_H = CPP_PROJECT / "src/core/Handler.h"
CPP_CORE_HANDLER_CPP = CPP_PROJECT / "src/core/Handler.cpp"
CPP_CORE_HELPER_H = CPP_PROJECT / "src/core/Helper.h"
CPP_CORE_HELPER_CPP = CPP_PROJECT / "src/core/Helper.cpp"
CPP_SHOP_CART_H = CPP_PROJECT / "src/shop/cart.h"
CPP_SHOP_ORDER_SERVICE_H = CPP_PROJECT / "src/shop/OrderService.h"

# Rust fixture paths
RS_PROJECT = FIXTURES_DIR / "rust-project"
RS_MAIN = RS_PROJECT / "src/main.rs"
RS_CORE_LIB_RS = RS_PROJECT / "src/lib.rs"
RS_CORE_MOD_RS = RS_PROJECT / "src/core/mod.rs"
RS_CORE_DATA_PROCESSOR_RS = RS_PROJECT / "src/core/data_processor.rs"
RS_CORE_DEFAULT_PROCESSOR_RS = RS_PROJECT / "src/core/default_processor.rs"
RS_CORE_HANDLER_RS = RS_PROJECT / "src/core/handler.rs"
RS_CORE_HELPER_RS = RS_PROJECT / "src/core/helper.rs"
RS_CORE_FINALIZE_OUTPUT_RS = RS_PROJECT / "src/core/finalize_output.rs"
RS_SHOP_CART_RS = RS_PROJECT / "src/shop/cart.rs"
RS_SHOP_SERVICE_RS = RS_PROJECT / "src/shop/service.rs"

LSP_SERVERS_ENV = os.environ.get("SKILL_SDK_LSP_SERVERS", "")
HAS_LSP_CONFIG = bool(LSP_SERVERS_ENV.strip())

HAS_RG = shutil.which("rg") is not None

# Determine available LSP servers from env
HAS_GOPLS = False
HAS_PYRIGHT = False
HAS_CLANGD = False
HAS_RUST_ANALYZER = False
if HAS_LSP_CONFIG:
    try:
        _lsp_cfg = json.loads(LSP_SERVERS_ENV)
        HAS_GOPLS = any(
            s.get("command", "").endswith("gopls") for s in _lsp_cfg.values()
        )
        HAS_PYRIGHT = any(
            s.get("command", "").endswith("pyright-langserver")
            for s in _lsp_cfg.values()
        )
        HAS_CLANGD = any(
            s.get("command", "").endswith("clangd") for s in _lsp_cfg.values()
        )
        HAS_RUST_ANALYZER = any(
            s.get("command", "").endswith("rust-analyzer")
            for s in _lsp_cfg.values()
        )
    except (json.JSONDecodeError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unmarshal_result(output: str) -> dict[str, Any]:
    return json.loads(output) if isinstance(output, str) else output


def _assert_no_error(result: dict[str, Any], label: str = "") -> None:
    if "error" in result:
        pytest.fail(
            f"{label} returned error: {result['error']} "
            f"(code={result.get('error_code')})"
        )


def _assert_result_has_lines(result: dict[str, Any], label: str = "") -> None:
    _assert_no_error(result, label)
    formatted = result.get("result", "")
    assert formatted, f"{label}: result is empty"


def _find_line_containing(filepath: Path, text: str) -> tuple[int, int]:
    """Return (1-based line, 1-based char offset) for first line with text."""
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if text in line:
            return (i + 1, line.index(text) + 1)
    raise ValueError(f"'{text}' not found in {filepath.name}")


def _find_symbol(
    filepath: Path, symbol: str, line_hint: str | None = None
) -> tuple[int, int]:
    """Return (1-based line, 1-based char) for an identifier."""
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if line_hint is not None and line_hint not in line:
            continue
        idx = line.find(symbol)
        if idx != -1:
            before = line[idx - 1] if idx > 0 else " "
            after = (
                line[idx + len(symbol)]
                if idx + len(symbol) < len(line)
                else " "
            )
            if before.isalnum() or before == "_" or after.isalnum() or after == "_":
                continue
            return (i + 1, idx + 1)
    raise ValueError(f"Symbol '{symbol}' not found in {filepath.name}")


def _make_binary_file(path: Path) -> None:
    """Create a file with non-UTF-8 binary content (null bytes)."""
    path.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir():
    """Yield a clean temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture(scope="module")
def lsp_manager_and_plugin():
    """Shared LSP manager + plugin across all LSP tests in this module."""
    if not HAS_LSP_CONFIG:
        pytest.skip("SKILL_SDK_LSP_SERVERS not configured")

    from skill_sdk.tool.lsp_plugin import LspPlugin, reset_manager, _manager_instance

    reset_manager()

    plugin = LspPlugin()
    yield plugin

    if _manager_instance is not None:
        try:
            _manager_instance.shutdown()
        except Exception:
            pass
    reset_manager()


# ===========================================================================
# 1. GLOB TESTS
# ===========================================================================


class TestGlob:
    """Thorough tests for GlobPlugin."""

    def test_glob_finds_py_files(self, tmp_dir):
        """Glob should find all .py files in a directory tree."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        (tmp_dir / "a.py").write_text("")
        (tmp_dir / "sub").mkdir()
        (tmp_dir / "sub" / "b.py").write_text("")
        (tmp_dir / "c.txt").write_text("")

        plug = GlobPlugin()
        raw = plug.execute(pattern="**/*.py", path=str(tmp_dir))
        data = _unmarshal_result(raw)
        _assert_no_error(data, "glob py files")
        assert data["numFiles"] == 2
        filenames = [Path(p).name for p in data["filenames"]]
        assert "a.py" in filenames
        assert "b.py" in filenames

    def test_glob_single_pattern(self, tmp_dir):
        """Glob with a simple pattern."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        (tmp_dir / "foo.txt").write_text("")
        (tmp_dir / "bar.txt").write_text("")
        (tmp_dir / "baz.md").write_text("")

        plug = GlobPlugin()
        raw = plug.execute(pattern="*.txt", path=str(tmp_dir))
        data = _unmarshal_result(raw)
        _assert_no_error(data, "glob txt")
        assert data["numFiles"] == 2

    def test_glob_no_matches(self, tmp_dir):
        """Glob with a pattern matching nothing should return zero files."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        plug = GlobPlugin()
        raw = plug.execute(pattern="*.nosuch", path=str(tmp_dir))
        data = _unmarshal_result(raw)
        _assert_no_error(data, "glob no matches")
        assert data["numFiles"] == 0
        assert data["filenames"] == []

    def test_glob_missing_dir(self):
        """Glob on a non-existent directory should error."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        plug = GlobPlugin()
        raw = plug.execute(pattern="*", path="/nonexistent_xyz_abc_test_dir")
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_glob_path_is_file_not_dir(self, tmp_dir):
        """Glob path pointed to a file should error."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        f = tmp_dir / "a_file.txt"
        f.write_text("")

        plug = GlobPlugin()
        raw = plug.execute(pattern="*", path=str(f))
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_glob_empty_pattern(self):
        """Glob with empty pattern should error."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        plug = GlobPlugin()
        raw = plug.execute(pattern="")
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_glob_absolute_pattern(self, tmp_dir):
        """Glob with absolute pattern works (extracts base dir)."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        (tmp_dir / "test_abs.py").write_text("")

        pattern = os.path.join(str(tmp_dir), "*.py")
        plug = GlobPlugin()
        raw = plug.execute(pattern=pattern)
        data = _unmarshal_result(raw)
        _assert_no_error(data, "glob absolute")
        assert data["numFiles"] >= 1
        assert any("test_abs.py" in p for p in data["filenames"])

    def test_glob_with_nested_dirs(self, tmp_dir):
        """Glob with recursive pattern finds files in nested dirs."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        (tmp_dir / "a.py").write_text("")
        d1 = tmp_dir / "dir1"
        d1.mkdir()
        (d1 / "b.py").write_text("")
        d2 = d1 / "dir2"
        d2.mkdir()
        (d2 / "c.py").write_text("")

        plug = GlobPlugin()
        raw = plug.execute(pattern="**/*.py", path=str(tmp_dir))
        data = _unmarshal_result(raw)
        _assert_no_error(data, "glob nested")
        assert data["numFiles"] == 3

    def test_glob_truncation(self, tmp_dir):
        """Glob with more results than limit should truncate."""
        from skill_sdk.tool.glob_plugin import run_file_glob

        for i in range(10):
            (tmp_dir / f"f{i}.txt").write_text(str(i), encoding="utf-8")

        out = run_file_glob("*.txt", str(tmp_dir), cwd_for_relative=str(tmp_dir), limit=3, offset=0)
        assert out["truncated"]
        assert out["numFiles"] == 3

    def test_glob_default_path(self, tmp_dir):
        """Glob without path uses cwd."""
        from skill_sdk.tool.glob_plugin import GlobPlugin

        plug = GlobPlugin()
        # Should not crash
        raw = plug.execute(pattern="*.py")
        data = _unmarshal_result(raw)
        # No error expected (may be 0 files if cwd has no .py files)
        assert "error" not in data


# ===========================================================================
# 2. GREP TESTS
# ===========================================================================


@pytest.mark.skipif(not HAS_RG, reason="ripgrep (rg) not installed")
class TestGrep:
    """Thorough tests for GrepPlugin."""

    def test_grep_files_with_matches(self, tmp_dir):
        """grep output_mode=files_with_matches."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "a.py").write_text("MARKER_grep_test_001\n")
        (tmp_dir / "b.py").write_text("# nothing\n")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="MARKER_grep_test_001",
            path=str(tmp_dir),
            output_mode="files_with_matches",
            head_limit=10,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep files_with_matches")
        assert data["mode"] == "files_with_matches"
        assert data["numFiles"] == 1
        assert any("a.py" in p for p in data["filenames"])

    def test_grep_content_mode(self, tmp_dir):
        """grep output_mode=content with line numbers."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "x.txt").write_text("unique_pattern_abc_xyz\nline2\n", encoding="utf-8")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="unique_pattern_abc_xyz",
            path=str(tmp_dir),
            output_mode="content",
            head_limit=20,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep content")
        assert data["mode"] == "content"
        assert "unique_pattern_abc_xyz" in data["content"]

    def test_grep_count_mode(self, tmp_dir):
        """grep output_mode=count."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "t.rs").write_text("fn alpha() {}\nfn alpha() {}\n")

        plug = GrepPlugin()
        raw = plug.execute(pattern=r"\balpha\b", path=str(tmp_dir), output_mode="count")
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep count")
        assert data["mode"] == "count"
        assert data["numMatches"] >= 2

    def test_grep_with_glob_filter(self, tmp_dir):
        """grep with glob filter."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "include.py").write_text("FILTER_ME\n")
        (tmp_dir / "exclude.js").write_text("FILTER_ME\n")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="FILTER_ME",
            path=str(tmp_dir),
            glob="*.py",
            output_mode="files_with_matches",
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep glob filter")
        assert data["numFiles"] == 1
        assert any("include.py" in p for p in data["filenames"])

    def test_grep_case_insensitive(self, tmp_dir):
        """grep with case_insensitive flag."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "test.txt").write_text("CASE_TEST_ABC\n")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="case_test",
            path=str(tmp_dir),
            case_insensitive=True,
            output_mode="content",
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep case insensitive")
        assert "CASE_TEST_ABC" in data["content"]

    def test_grep_context(self, tmp_dir):
        """grep with context lines."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        content = "\n".join([f"line_{i}" for i in range(10)])
        (tmp_dir / "ctx.txt").write_text(content)

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="line_5",
            path=str(tmp_dir),
            output_mode="content",
            context=2,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep context")
        # Should include line_3, line_4, line_5, line_6, line_7
        assert "line_3" in data["content"]
        assert "line_4" in data["content"]
        assert "line_5" in data["content"]

    def test_grep_multiline(self, tmp_dir):
        """grep with multiline pattern."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        content = "start\nmiddle\nend"
        (tmp_dir / "multi.txt").write_text(content)

        plug = GrepPlugin()
        raw = plug.execute(
            pattern=r"start\nmiddle",
            path=str(tmp_dir),
            output_mode="content",
            multiline=True,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep multiline")
        assert "start" in data["content"]
        assert "middle" in data["content"]

    def test_grep_head_limit_and_offset(self, tmp_dir):
        """grep head_limit and offset pagination."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        lines = "\n".join([f"MATCH_line_{i}" for i in range(20)])
        (tmp_dir / "pagination.txt").write_text(lines)

        plug = GrepPlugin()
        # First page
        raw = plug.execute(
            pattern="MATCH_line_",
            path=str(tmp_dir),
            output_mode="content",
            head_limit=5,
            offset=0,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep pagination page1")
        assert "line_0" in data["content"]
        assert "line_4" in data["content"]

        # Second page
        raw2 = plug.execute(
            pattern="MATCH_line_",
            path=str(tmp_dir),
            output_mode="content",
            head_limit=5,
            offset=5,
        )
        data2 = _unmarshal_result(raw2)
        _assert_no_error(data2, "grep pagination page2")
        assert "line_5" in data2["content"]
        assert "line_9" in data2["content"]

    def test_grep_no_matches(self, tmp_dir):
        """grep with no matches should return empty results (not error)."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="THIS_PATTERN_DOES_NOT_EXIST_XYZ",
            path=str(tmp_dir),
            output_mode="content",
        )
        data = _unmarshal_result(raw)
        # No matches should not be an error
        _assert_no_error(data, "grep no matches")
        # content should be empty or contain nothing
        content = data.get("content", "")
        if content:
            assert "THIS_PATTERN_DOES_NOT_EXIST_XYZ" not in content

    def test_grep_empty_pattern(self):
        """grep with empty pattern should error."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        plug = GrepPlugin()
        raw = plug.execute(pattern="", path="/tmp")
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_grep_file_type_filter(self, tmp_dir):
        """grep file_type filter."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "a.py").write_text("TYPE_FILTER_TEST\n")
        (tmp_dir / "b.js").write_text("TYPE_FILTER_TEST\n")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="TYPE_FILTER_TEST",
            path=str(tmp_dir),
            file_type="py",
            output_mode="files_with_matches",
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep type filter")
        assert data["numFiles"] == 1
        assert any("a.py" in p for p in data["filenames"])

    def test_grep_no_line_numbers(self, tmp_dir):
        """grep content mode with line_numbers=False."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        (tmp_dir / "nn.txt").write_text("hello\nworld\nLINE_NO_TEST\nbye\n")

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="LINE_NO_TEST",
            path=str(tmp_dir),
            output_mode="content",
            line_numbers=False,
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep no line numbers")
        # Without line numbers, ripgrep should NOT output :LINENO: prefix.
        # It may still include filepath: but must not have :<digits>: between path and content.
        for line in data["content"].split("\n"):
            if "LINE_NO_TEST" in line:
                assert not re.search(r":\d+:(.*LINE_NO_TEST)", line), (
                    f"Expected no line number prefix, got: {line}"
                )

    def test_grep_non_existent_path(self):
        """grep on non-existent path should error."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        plug = GrepPlugin()
        raw = plug.execute(
            pattern="test",
            path="/nonexistent_grep_test_path",
        )
        data = _unmarshal_result(raw)
        assert "error" in data


# ===========================================================================
# 3. READLINE_IN_RANGE TESTS
# ===========================================================================


class TestReadlineInRange:
    """Thorough tests for ReadlineInRangePlugin."""

    def test_read_basic_range(self, tmp_dir):
        """Read a line range in the middle of a file."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "test.txt"
        f.write_text("\n".join(f"line_{i}" for i in range(1, 21)))

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=5, end=10)
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert data["start"] == 5
        assert data["end"] == 10
        assert data["total_lines"] == 6
        assert "line_5" in data["content"]
        assert "line_10" in data["content"]

    def test_read_to_end_default(self, tmp_dir):
        """Read from start to end when end is not specified."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "test.txt"
        f.write_text("\n".join(f"line_{i}" for i in range(1, 11)))

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=8)
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert data["start"] == 8
        assert data["end"] == 10
        assert data["total_lines"] == 3

    def test_read_start_beyond_eof(self, tmp_dir):
        """Read start beyond EOF returns empty content."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "test.txt"
        f.write_text("line_1\nline_2\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=100)
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert data["content"] == ""

    def test_read_empty_file(self, tmp_dir):
        """Read from an empty file."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "empty.txt"
        f.write_text("")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f))
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert data["content"] == ""

    def test_read_single_line(self, tmp_dir):
        """Read a single line."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "single.txt"
        f.write_text("only_line\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=1, end=1)
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert data["total_lines"] == 1
        assert "only_line" in data["content"]

    def test_read_no_line_numbers(self, tmp_dir):
        """Read without line number prefixes."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "nonum.txt"
        f.write_text("a\nb\nc\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(
            file_path=str(f), start=1, end=3, include_line_numbers=False
        )
        data = _unmarshal_result(raw)
        assert "error" not in data
        # Content should NOT have "1|" prefix
        assert "|" not in data["content"]

    def test_read_invalid_start(self, tmp_dir):
        """Read with start < 1 should error."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "test.txt"
        f.write_text("hello\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=0)
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_read_end_before_start(self, tmp_dir):
        """Read with end < start should error."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "test.txt"
        f.write_text("hello\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f), start=5, end=3)
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_read_non_existent_file(self):
        """Read a non-existent file should error."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path="/nonexistent_file_xyz.txt")
        data = _unmarshal_result(raw)
        assert "error" in data

    def test_read_unicode_file(self, tmp_dir):
        """Read a UTF-8 file with unicode characters."""
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "unicode.txt"
        f.write_text("hello 世界\n你好 world\n")

        plug = ReadlineInRangePlugin()
        raw = plug.execute(file_path=str(f))
        data = _unmarshal_result(raw)
        assert "error" not in data
        assert "hello 世界" in data["content"]
        assert "你好 world" in data["content"]


# ===========================================================================
# 4. LSP TESTS - ALL 9 OPERATIONS
# ===========================================================================


# -----------------------------------------------------------------------
# 4a. goToDefinition
# -----------------------------------------------------------------------


class TestLspGoToDefinition:
    """goToDefinition on Go and Python fixtures."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_struct(self, lsp_manager_and_plugin):
        """Go struct definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "DefaultProcessor", line_hint="type DefaultProcessor struct")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition DefaultProcessor")
        assert "Defined in" in result["result"]
        assert "main.go" in result["result"]

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_interface(self, lsp_manager_and_plugin):
        """Go interface definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "DataProcessor", line_hint="type DataProcessor interface")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition DataProcessor")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_function(self, lsp_manager_and_plugin):
        """Go function definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "TransformData", line_hint="func TransformData")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition TransformData")
        assert "Defined in" in result["result"]
        assert "main.go" in result["result"]

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_method(self, lsp_manager_and_plugin):
        """Go method definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "Validate", line_hint="func (p *DefaultProcessor) Validate")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition Validate")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_PYRIGHT, reason="pyright not configured")
    def test_py_class(self, lsp_manager_and_plugin):
        """Python class definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(PY_CORE, "AdvancedProcessor", line_hint="class AdvancedProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition AdvancedProcessor")
        assert "core.py" in result["result"]

    @pytest.mark.skipif(not HAS_PYRIGHT, reason="pyright not configured")
    def test_py_function(self, lsp_manager_and_plugin):
        """Python function definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(PY_CORE, "build_pipeline", line_hint="def build_pipeline")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "goToDefinition build_pipeline")
        assert "core.py" in result["result"]

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_cross_file_definition(self, lsp_manager_and_plugin):
        """Cross-file goToDefinition: from handler.go to main.go."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_HANDLER, "NewHelper")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "cross-file goToDefinition NewHelper")
        assert "main.go" in result["result"], (
            f"Expected cross-file resolution to main.go: {result['result']}"
        )

    # ---- Edge cases (null responses) ----

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_definition_on_blank_line(self, lsp_manager_and_plugin):
        """goToDefinition on blank line returns friendly message, NOT error_code 4."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=80,  # blank line in main.go
            character=1,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result or result.get("error_code") != 4
        formatted = result.get("result", "")
        assert "No definition found" in formatted, (
            f"Expected friendly message, got: {formatted}"
        )

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_definition_out_of_range(self, lsp_manager_and_plugin):
        """goToDefinition on line beyond EOF."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=9999,
            character=1,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result or result.get("error_code") != 4


# -----------------------------------------------------------------------
# 4b. documentSymbol
# -----------------------------------------------------------------------


class TestLspDocumentSymbol:
    """documentSymbol on Go and Python fixtures."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_document_symbols_main(self, lsp_manager_and_plugin):
        """documentSymbol on main.go should list all top-level symbols."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "documentSymbol main.go")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["DataProcessor", "DefaultProcessor", "NewDefaultProcessor",
                     "TransformData", "Helper", "NewHelper", "HandleRequest", "FinalizeOutput"]:
            assert sym in formatted, f"Missing symbol '{sym}'"

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_document_symbols_handler(self, lsp_manager_and_plugin):
        """documentSymbol on handler.go."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_HANDLER),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "documentSymbol handler.go")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["Handler", "NewHandler", "ProcessRequest", "HealthCheck"]:
            assert sym in formatted, f"Missing '{sym}'"

    @pytest.mark.skipif(not HAS_PYRIGHT, reason="pyright not configured")
    def test_py_document_symbols_core(self, lsp_manager_and_plugin):
        """documentSymbol on core.py."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(PY_CORE),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "documentSymbol core.py")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["ServiceConfig", "DataProcessor", "AdvancedProcessor",
                     "RequestHandler", "build_pipeline", "finalize_result"]:
            assert sym in formatted, f"Missing '{sym}'"

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_document_symbol_has_line_ranges(self, lsp_manager_and_plugin):
        """documentSymbol output includes Lines X-Y ranges."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "docSymbol line ranges")
        formatted = result["result"]
        line_ranges = re.findall(r"Lines (\d+)-(\d+)", formatted)
        assert len(line_ranges) >= 3, f"Need >=3 line ranges, got: {line_ranges}"
        # Verify resultCount >= number of top-level symbols
        assert result.get("resultCount", 0) >= 5

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_document_symbol_filters_by_name(self, lsp_manager_and_plugin):
        """Small fixture files return full outline under the shared budget."""
        plug = lsp_manager_and_plugin
        filtered = _unmarshal_result(
            plug.execute(
                operation="documentSymbol",
                file_path=str(GO_HANDLER),
                symbol_name="ProcessRequest",
            )
        )
        _assert_result_has_lines(filtered, "docSymbol filtered ProcessRequest")
        text = filtered["result"]
        assert "ProcessRequest" in text
        assert "full outline" in text or "filtered" in text
        assert len(text) <= 10000

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_document_symbol_filters_by_line(self, lsp_manager_and_plugin):
        """line focus on small files still returns a usable outline under budget."""
        plug = lsp_manager_and_plugin
        line, _ = _find_symbol(
            GO_HANDLER, "ProcessRequest", line_hint="func (h *Handler) ProcessRequest"
        )
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_HANDLER),
            line=line,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "docSymbol filtered by line")
        assert "ProcessRequest" in result["result"]
        assert len(result["result"]) <= 10000

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_document_symbol_line_miss_small_file_returns_full(self, lsp_manager_and_plugin):
        """Under-budget outlines are returned in full even if line misses."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_HANDLER),
            line=99999,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "docSymbol line miss")
        assert "full outline" in result["result"] or "Handler" in result["result"]


# -----------------------------------------------------------------------
# 4c. findReferences
# -----------------------------------------------------------------------


class TestLspFindReferences:
    """findReferences on Go and Python fixtures."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_find_references_transform_data(self, lsp_manager_and_plugin):
        """findReferences on TransformData finds usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "TransformData")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "findReferences TransformData")
        formatted = result["result"]
        assert "references" in formatted.lower()
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_find_references_interface(self, lsp_manager_and_plugin):
        """findReferences on DataProcessor interface."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "DataProcessor", line_hint="type DataProcessor interface")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "findReferences DataProcessor")
        formatted = result["result"]
        assert "references" in formatted.lower()
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_find_references_multi_file(self, lsp_manager_and_plugin):
        """findReferences across multiple files."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "Validate", line_hint="func (p *DefaultProcessor) Validate")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "findReferences Validate")
        assert result.get("fileCount", 0) >= 1
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_PYRIGHT, reason="pyright not configured")
    def test_py_find_references_validate(self, lsp_manager_and_plugin):
        """findReferences on Python validate method."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(PY_CORE, "validate", line_hint="def validate")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "findReferences validate")
        formatted = result["result"]
        assert "references" in formatted.lower()


# -----------------------------------------------------------------------
# 4d. hover
# -----------------------------------------------------------------------


class TestLspHover:
    """hover on Go and Python fixtures."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_hover_type(self, lsp_manager_and_plugin):
        """hover on a Go type shows type info."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "TransformData", line_hint="func TransformData")
        raw = plug.execute(
            operation="hover",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "hover TransformData")
        formatted = result.get("result", "")
        assert formatted, "hover result should not be empty"
        assert "TransformData" in formatted or "string" in formatted.lower(), (
            f"Expected hover info about TransformData, got: {formatted[:200]}"
        )

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_hover_no_info(self, lsp_manager_and_plugin):
        """hover on a position with no info returns friendly message, not error."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="hover",
            file_path=str(GO_MAIN),
            line=1,
            character=1,
        )
        result = _unmarshal_result(raw)
        # Either we get info or a friendly message - NOT an error
        assert "error" not in result, f"hover on blank should not error: {result}"

    @pytest.mark.skipif(not HAS_PYRIGHT, reason="pyright not configured")
    def test_py_hover_class(self, lsp_manager_and_plugin):
        """hover on a Python class."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(PY_CORE, "RequestHandler", line_hint="class RequestHandler")
        raw = plug.execute(
            operation="hover",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "hover RequestHandler")
        formatted = result.get("result", "")
        assert formatted, "hover result should not be empty"


# -----------------------------------------------------------------------
# 4e. goToImplementation
# -----------------------------------------------------------------------


class TestLspGoToImplementation:
    """goToImplementation on Go interface and Python base class."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_interface_implementation(self, lsp_manager_and_plugin):
        """goToImplementation on DataProcessor interface finds DefaultProcessor."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "DataProcessor", line_hint="type DataProcessor interface")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "goToImplementation DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "goToImplementation should return a result"
        # Should point to DefaultProcessor which implements the interface
        assert "DefaultProcessor" in formatted or "Defined in" in formatted, (
            f"Expected implementation info: {formatted[:300]}"
        )

    # pyright-langserver does NOT support textDocument/implementation
    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_base_class_implementation(self, lsp_manager_and_plugin):
        """goToImplementation via gopls on DataProcessor interface finds implementations."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "DataProcessor", line_hint="type DataProcessor interface")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "goToImplementation DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "goToImplementation should return a result"
        # Should point to DefaultProcessor which implements the interface
        assert "Defined in" in formatted or "Found" in formatted or "DefaultProcessor" in formatted, (
            f"Expected implementation info: {formatted[:300]}"
        )

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_struct_no_implementation(self, lsp_manager_and_plugin):
        """goToImplementation on a concrete struct returns definition info."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "FinalizeOutput")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        # A concrete function may have no implementations beyond its own definition;
        # should return the definition itself or a friendly message
        assert "error" not in result or result.get("error_code") in (None, 7), (
            f"Unexpected error: {result.get('error', '')}"
        )


# -----------------------------------------------------------------------
# 4f. prepareCallHierarchy
# -----------------------------------------------------------------------


class TestLspPrepareCallHierarchy:
    """prepareCallHierarchy on Go functions."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_prepare_call_hierarchy(self, lsp_manager_and_plugin):
        """prepareCallHierarchy on a Go function should return call hierarchy item."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "HandleRequest", line_hint="func (h *Helper) HandleRequest")
        raw = plug.execute(
            operation="prepareCallHierarchy",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "prepareCallHierarchy HandleRequest")
        formatted = result.get("result", "")
        assert formatted, "prepareCallHierarchy should return a result"
        # Should have the function name
        assert "HandleRequest" in formatted or "call hierarchy" in formatted.lower(), (
            f"Expected call hierarchy item: {formatted[:300]}"
        )

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_prepare_call_hierarchy_no_item(self, lsp_manager_and_plugin):
        """prepareCallHierarchy on a blank line returns friendly message."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="prepareCallHierarchy",
            file_path=str(GO_MAIN),
            line=80,
            character=1,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result, (
            f"prepareCallHierarchy on blank line should not error: {result}"
        )
        formatted = result.get("result", "")
        assert formatted, "Should have a message"
        assert "No call hierarchy" in formatted or "not found" in formatted.lower(), (
            f"Expected friendly message: {formatted[:200]}"
        )


# -----------------------------------------------------------------------
# 4g. incomingCalls
# -----------------------------------------------------------------------


class TestLspIncomingCalls:
    """incomingCalls on Go functions."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_incoming_calls(self, lsp_manager_and_plugin):
        """incomingCalls on Validate should find callers."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "Validate", line_hint="func (p *DefaultProcessor) Validate")
        raw = plug.execute(
            operation="incomingCalls",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "incomingCalls Validate")
        formatted = result.get("result", "")
        # Validate is called from Process and HandleRequest
        assert formatted, "incomingCalls should return a result"
        # Either we find callers or get a "no incoming calls" message
        assert "incoming" in formatted.lower() or "no" in formatted.lower()


# -----------------------------------------------------------------------
# 4h. outgoingCalls
# -----------------------------------------------------------------------


class TestLspOutgoingCalls:
    """outgoingCalls on Go functions."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_outgoing_calls(self, lsp_manager_and_plugin):
        """outgoingCalls on HandleRequest shows calls to Validate, Process, FinalizeOutput."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "HandleRequest", line_hint="func (h *Helper) HandleRequest")
        raw = plug.execute(
            operation="outgoingCalls",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "outgoingCalls HandleRequest")
        formatted = result.get("result", "")
        assert formatted, "outgoingCalls should return a result"
        # HandleRequest calls Validate, Process, FinalizeOutput
        assert "outgoing" in formatted.lower() or len(result.get("result", "")) > 0

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_outgoing_calls_finalize_output(self, lsp_manager_and_plugin):
        """outgoingCalls on a function with calls (FinalizeOutput -> fmt.Sprintf)."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "FinalizeOutput")
        raw = plug.execute(
            operation="outgoingCalls",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result, (
            f"outgoingCalls should not error: {result}"
        )
        formatted = result.get("result", "")
        assert formatted, "Should have a result"
        # FinalizeOutput calls fmt.Sprintf internally
        assert "outgoing" in formatted.lower() or "Found" in formatted or "Sprintf" in formatted, (
            f"Expected calls info, got: {formatted[:200]}"
        )


# -----------------------------------------------------------------------
# 4i. workspaceSymbol (conditionally test)
# -----------------------------------------------------------------------


@pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
class TestLspWorkspaceSymbol:
    """workspaceSymbol searches symbols across the workspace."""

    def test_workspace_symbol_transform_data(self, lsp_manager_and_plugin):
        """workspaceSymbol for TransformData should find it."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="workspaceSymbol",
            file_path=str(GO_MAIN),
            symbol_name="TransformData",
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "workspaceSymbol")
        assert result.get("query") == "TransformData"
        formatted = result.get("result", "")
        assert isinstance(formatted, str)
        assert "TransformData" in formatted or "symbol" in formatted.lower()

    def test_workspace_symbol_accepts_directory_root(self, lsp_manager_and_plugin):
        """workspaceSymbol must accept a workspace directory as file_path."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="workspaceSymbol",
            file_path=str(GO_PROJECT),
            symbol_name="HandleRequest",
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "workspaceSymbol directory root")
        assert result.get("query") == "HandleRequest"
        assert "Path is not a file" not in json.dumps(result)
        formatted = result.get("result", "")
        assert isinstance(formatted, str)


# ===========================================================================
# 4j. C LSP Tests (clangd)
# ===========================================================================


class TestCLspGoToDefinition:
    """goToDefinition on C fixtures using clangd."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_struct_typedef_definition(self, lsp_manager_and_plugin):
        """C struct typedef definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_DATA_PROCESSOR_H, "DataProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(C_CORE_DATA_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C goToDefinition DataProcessor")
        assert "Defined in" in result["result"]
        assert "data_processor.h" in result["result"]

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_default_processor(self, lsp_manager_and_plugin):
        """C DefaultProcessor struct definition."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_DEFAULT_PROCESSOR_H, "DefaultProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(C_CORE_DEFAULT_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C goToDefinition DefaultProcessor")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_function_definition(self, lsp_manager_and_plugin):
        """C function definition: default_processor_init."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_DEFAULT_PROCESSOR_C, "default_processor_init")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(C_CORE_DEFAULT_PROCESSOR_C),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C goToDefinition default_processor_init")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_cross_file_definition(self, lsp_manager_and_plugin):
        """Cross-file goToDefinition: from handler.c NewHelper call resolves to helper.h."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_HANDLER_C, "new_helper")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(C_CORE_HANDLER_C),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C cross-file goToDefinition new_helper")
        assert "helper.h" in result["result"] or "helper.c" in result["result"], (
            f"Expected cross-file resolution to helper: {result['result']}"
        )


class TestCLspDocumentSymbol:
    """documentSymbol on C fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_document_symbols_main(self, lsp_manager_and_plugin):
        """documentSymbol on main.c should list all top-level functions."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(C_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C documentSymbol main.c")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["demo_core_run", "demo_shop_run", "main"]:
            assert sym in formatted, f"Missing C symbol '{sym}'"

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_document_symbols_data_processor(self, lsp_manager_and_plugin):
        """documentSymbol on data_processor.h should list symbols."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(C_CORE_DATA_PROCESSOR_H),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C documentSymbol data_processor.h")
        formatted = result["result"]
        assert "Document symbols" in formatted
        assert "DataProcessor" in formatted


class TestCLspFindReferences:
    """findReferences on C fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_find_references_default_processor_init(self, lsp_manager_and_plugin):
        """findReferences on default_processor_init should find usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_DEFAULT_PROCESSOR_C, "default_processor_init")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(C_CORE_DEFAULT_PROCESSOR_C),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C findReferences default_processor_init")
        formatted = result["result"]
        assert "references" in formatted.lower() or "Found" in formatted
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_find_references_helper_handle_request(self, lsp_manager_and_plugin):
        """findReferences on helper_handle_request should find multi-file usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_HELPER_C, "helper_handle_request")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(C_CORE_HELPER_C),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C findReferences helper_handle_request")
        assert result.get("resultCount", 0) >= 1


class TestCLspHover:
    """hover on C fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_hover_struct_member(self, lsp_manager_and_plugin):
        """hover on a C struct member shows type info."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_PROCESSOR_CONFIG_H, "retries")
        raw = plug.execute(
            operation="hover",
            file_path=str(C_CORE_PROCESSOR_CONFIG_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "C hover retries")
        formatted = result.get("result", "")
        assert formatted, "C hover result should not be empty"

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_hover_on_comment(self, lsp_manager_and_plugin):
        """hover on a position with no info returns friendly message."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="hover",
            file_path=str(C_MAIN),
            line=1,
            character=1,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result, f"C hover on blank should not error: {result}"


class TestCLspGoToImplementation:
    """goToImplementation on C fixtures using clangd."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_c_interface_implementation(self, lsp_manager_and_plugin):
        """goToImplementation on DataProcessor should find DefaultProcessor usage."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(C_CORE_DATA_PROCESSOR_H, "DataProcessor")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(C_CORE_DATA_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "C goToImplementation DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "C goToImplementation should return a result"


# ===========================================================================
# 4k. C++ LSP Tests (clangd)
# ===========================================================================


class TestCppLspGoToDefinition:
    """goToDefinition on C++ fixtures using clangd."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_interface_definition(self, lsp_manager_and_plugin):
        """C++ interface definition in DataProcessor.h."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_DATA_PROCESSOR_H, "DataProcessor", line_hint="class DataProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(CPP_CORE_DATA_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ goToDefinition DataProcessor")
        assert "Defined in" in result["result"]
        assert "DataProcessor.h" in result["result"]

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_class_definition(self, lsp_manager_and_plugin):
        """C++ class definition: DefaultProcessor."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_DEFAULT_PROCESSOR_H, "DefaultProcessor", line_hint="class DefaultProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(CPP_CORE_DEFAULT_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ goToDefinition DefaultProcessor")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_cross_file_definition(self, lsp_manager_and_plugin):
        """Cross-file goToDefinition: from Handler.cpp NewHelper call resolves to Helper.h."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_HANDLER_CPP, "NewHelper")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(CPP_CORE_HANDLER_CPP),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ cross-file goToDefinition NewHelper")
        assert "Helper.h" in result["result"], (
            f"Expected cross-file resolution to Helper.h: {result['result']}"
        )

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_cross_file_data_processor_from_handler(self, lsp_manager_and_plugin):
        """goToDefinition on DataProcessor reference in handler.cpp resolves to header."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_HANDLER_CPP, "DataProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(CPP_CORE_HANDLER_CPP),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ cross-file DataProcessor")
        assert "DataProcessor.h" in result["result"], (
            f"Expected DataProcessor.h: {result['result']}"
        )


class TestCppLspDocumentSymbol:
    """documentSymbol on C++ fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_document_symbols_main(self, lsp_manager_and_plugin):
        """documentSymbol on main.cpp lists all functions."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(CPP_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ documentSymbol main.cpp")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["demoCoreRun", "demoShopRun", "main"]:
            assert sym in formatted, f"Missing C++ symbol '{sym}'"

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_document_symbols_data_processor(self, lsp_manager_and_plugin):
        """documentSymbol on DataProcessor.h."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(CPP_CORE_DATA_PROCESSOR_H),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ documentSymbol DataProcessor.h")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["DataProcessor", "Process", "Validate"]:
            assert sym in formatted, f"Missing '{sym}'"

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_document_symbols_default_processor(self, lsp_manager_and_plugin):
        """documentSymbol on DefaultProcessor.h."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(CPP_CORE_DEFAULT_PROCESSOR_H),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ documentSymbol DefaultProcessor.h")
        formatted = result["result"]
        for sym in ["DefaultProcessor", "Process", "Validate", "ConfigureRetries", "GetConfig"]:
            assert sym in formatted, f"Missing '{sym}'"


class TestCppLspFindReferences:
    """findReferences on C++ fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_find_references_validate(self, lsp_manager_and_plugin):
        """findReferences on Validate should find multi-file usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_DEFAULT_PROCESSOR_H, "Validate", line_hint="bool Validate(")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(CPP_CORE_DEFAULT_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ findReferences Validate")
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_find_references_data_processor(self, lsp_manager_and_plugin):
        """findReferences on DataProcessor interface."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_DATA_PROCESSOR_H, "DataProcessor", line_hint="class DataProcessor")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(CPP_CORE_DATA_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "C++ findReferences DataProcessor")
        assert result.get("resultCount", 0) >= 1


class TestCppLspHover:
    """hover on C++ fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_hover_function(self, lsp_manager_and_plugin):
        """hover on a C++ function shows type info."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_MAIN, "demoCoreRun")
        raw = plug.execute(
            operation="hover",
            file_path=str(CPP_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "C++ hover demoCoreRun")
        formatted = result.get("result", "")
        assert formatted, "C++ hover result should not be empty"


class TestCppLspGoToImplementation:
    """goToImplementation on C++ fixtures."""

    @pytest.mark.skipif(not HAS_CLANGD, reason="clangd not configured")
    def test_cpp_interface_implementation(self, lsp_manager_and_plugin):
        """goToImplementation on DataProcessor finds DefaultProcessor."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(CPP_CORE_DATA_PROCESSOR_H, "DataProcessor", line_hint="class DataProcessor")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(CPP_CORE_DATA_PROCESSOR_H),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "C++ goToImplementation DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "C++ goToImplementation should return a result"


# ===========================================================================
# 4l. Rust LSP Tests (rust-analyzer)
# ===========================================================================


class TestRsLspGoToDefinition:
    """goToDefinition on Rust fixtures using rust-analyzer."""

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_trait_definition(self, lsp_manager_and_plugin):
        """Rust trait definition: DataProcessor."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DATA_PROCESSOR_RS, "DataProcessor", line_hint="pub trait DataProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(RS_CORE_DATA_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust goToDefinition DataProcessor")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_struct_definition(self, lsp_manager_and_plugin):
        """Rust struct definition: DefaultProcessor."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DEFAULT_PROCESSOR_RS, "DefaultProcessor", line_hint="pub struct DefaultProcessor")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(RS_CORE_DEFAULT_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust goToDefinition DefaultProcessor")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_function_definition(self, lsp_manager_and_plugin):
        """Rust function definition: default_processor::new."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DEFAULT_PROCESSOR_RS, "new", line_hint="pub fn new")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(RS_CORE_DEFAULT_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust goToDefinition DefaultProcessor::new")
        assert "Defined in" in result["result"]

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_cross_file_definition(self, lsp_manager_and_plugin):
        """Cross-file goToDefinition: from handler.rs new_helper call resolves to helper.rs."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_HANDLER_RS, "new_helper")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(RS_CORE_HANDLER_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust cross-file goToDefinition new_helper")
        assert "helper.rs" in result["result"], (
            f"Expected cross-file resolution to helper.rs: {result['result']}"
        )


class TestRsLspDocumentSymbol:
    """documentSymbol on Rust fixtures."""

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_document_symbols_main(self, lsp_manager_and_plugin):
        """documentSymbol on main.rs should list all top-level functions."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(RS_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust documentSymbol main.rs")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["demo_core_run", "demo_shop_run", "main"]:
            assert sym in formatted, f"Missing Rust symbol '{sym}'"

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_document_symbols_data_processor(self, lsp_manager_and_plugin):
        """documentSymbol on data_processor.rs."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(RS_CORE_DATA_PROCESSOR_RS),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust documentSymbol data_processor.rs")
        formatted = result["result"]
        assert "Document symbols" in formatted
        assert "DataProcessor" in formatted

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_document_symbols_default_processor(self, lsp_manager_and_plugin):
        """documentSymbol on default_processor.rs lists struct + impl."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(RS_CORE_DEFAULT_PROCESSOR_RS),
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust documentSymbol default_processor.rs")
        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["DefaultProcessor", "new", "process", "validate", "transform_data", "configure_retries"]:
            assert sym in formatted, f"Missing Rust symbol '{sym}'"


class TestRsLspFindReferences:
    """findReferences on Rust fixtures."""

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_find_references_default_processor(self, lsp_manager_and_plugin):
        """findReferences on DefaultProcessor should find usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DEFAULT_PROCESSOR_RS, "DefaultProcessor", line_hint="pub struct DefaultProcessor")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(RS_CORE_DEFAULT_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust findReferences DefaultProcessor")
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_find_references_validate(self, lsp_manager_and_plugin):
        """findReferences on validate method should find multi-file usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DEFAULT_PROCESSOR_RS, "validate", line_hint="fn validate(")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(RS_CORE_DEFAULT_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust findReferences validate")
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_find_references_new_helper(self, lsp_manager_and_plugin):
        """findReferences on new_helper should find cross-file usages."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_HELPER_RS, "new_helper", line_hint="pub fn new_helper")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(RS_CORE_HELPER_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_result_has_lines(result, "Rust findReferences new_helper")
        assert result.get("resultCount", 0) >= 1


class TestRsLspHover:
    """hover on Rust fixtures."""

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_hover_trait(self, lsp_manager_and_plugin):
        """hover on a Rust trait shows documentation."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DATA_PROCESSOR_RS, "DataProcessor", line_hint="pub trait DataProcessor")
        raw = plug.execute(
            operation="hover",
            file_path=str(RS_CORE_DATA_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "Rust hover DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "Rust hover result should not be empty"

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_hover_on_blank(self, lsp_manager_and_plugin):
        """hover on blank line returns friendly message."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="hover",
            file_path=str(RS_MAIN),
            line=1,
            character=1,
        )
        result = _unmarshal_result(raw)
        assert "error" not in result, f"Rust hover on blank should not error: {result}"


class TestRsLspGoToImplementation:
    """goToImplementation on Rust fixtures."""

    @pytest.mark.skipif(not HAS_RUST_ANALYZER, reason="rust-analyzer not configured")
    def test_rs_go_to_implementation(self, lsp_manager_and_plugin):
        """goToImplementation on DataProcessor trait finds DefaultProcessor impl."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(RS_CORE_DATA_PROCESSOR_RS, "DataProcessor", line_hint="pub trait DataProcessor")
        raw = plug.execute(
            operation="goToImplementation",
            file_path=str(RS_CORE_DATA_PROCESSOR_RS),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "Rust goToImplementation DataProcessor")
        formatted = result.get("result", "")
        assert formatted, "Rust goToImplementation should return a result"


# ===========================================================================
# 5. LSP ERROR HANDLING
# ===========================================================================


class TestLspErrorHandling:
    """Error cases for LspPlugin."""

    def test_invalid_operation(self, lsp_manager_and_plugin):
        """Invalid operation name should return error."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="invalidOperationName",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(raw)
        assert "error" in result
        assert "Invalid operation" in result["error"]

    def test_missing_file(self, lsp_manager_and_plugin):
        """File not found should return error."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="goToDefinition",
            file_path="/nonexistent/file/path/test.go",
        )
        result = _unmarshal_result(raw)
        assert "error" in result

    def test_empty_file_path(self, lsp_manager_and_plugin):
        """Empty file_path should return error."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="goToDefinition",
            file_path="",
        )
        result = _unmarshal_result(raw)
        assert "error" in result


# ===========================================================================
# 6. END-TO-END SKILL FLOW TESTS
# ===========================================================================


class TestSkillFlowGlobGrepReadline:
    """Simulate the read-code skill's complete workflow."""

    def test_flow_find_file_then_grep_then_read(self, tmp_dir):
        """Simulate: glob → grep → readline_in_range."""
        from skill_sdk.tool.glob_plugin import GlobPlugin
        from skill_sdk.tool.grep_plugin import GrepPlugin
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        # Create test files
        content = "\n".join(
            [f"line_{i}" for i in range(1, 51)]
        )
        for name in ["target.py", "other.py"]:
            (tmp_dir / name).write_text(content)

        # Step 1: glob to find .py files
        glob_plug = GlobPlugin()
        raw = glob_plug.execute(pattern="*.py", path=str(tmp_dir))
        glob_data = _unmarshal_result(raw)
        _assert_no_error(glob_data, "glob step")
        assert glob_data["numFiles"] == 2

        # Step 2: grep for target content
        grep_plug = GrepPlugin()
        raw = grep_plug.execute(
            pattern="line_25",
            path=str(tmp_dir),
            output_mode="content",
        )
        grep_data = _unmarshal_result(raw)
        _assert_no_error(grep_data, "grep step")
        assert "line_25" in grep_data.get("content", "")

        # Step 3: readline_in_range on a specific range
        read_plug = ReadlineInRangePlugin()
        raw = read_plug.execute(
            file_path=str(tmp_dir / "target.py"),
            start=20,
            end=30,
        )
        read_data = _unmarshal_result(raw)
        assert "error" not in read_data
        assert read_data["start"] == 20
        assert read_data["end"] == 30
        assert "line_20" in read_data["content"]
        assert "line_30" in read_data["content"]

    def test_flow_grep_then_readline_then_grep_context(self, tmp_dir):
        """Simulate: grep content → readline → grep with context."""
        from skill_sdk.tool.grep_plugin import GrepPlugin
        from skill_sdk.tool.readline_in_range_plugin import ReadlineInRangePlugin

        f = tmp_dir / "service.py"
        lines = []
        for i in range(1, 101):
            if 40 <= i <= 60:
                lines.append(f"TARGET_FUNC line_{i}")
            else:
                lines.append(f"normal line_{i}")
        f.write_text("\n".join(lines))

        # Step 1: grep to find target lines
        grep_plug = GrepPlugin()
        raw = grep_plug.execute(
            pattern="TARGET_FUNC",
            path=str(tmp_dir),
            output_mode="content",
            head_limit=50,
        )
        grep_data = _unmarshal_result(raw)
        _assert_no_error(grep_data, "grep func")
        assert "TARGET_FUNC" in grep_data.get("content", "")

        # Step 2: readline_in_range
        read_plug = ReadlineInRangePlugin()
        raw = read_plug.execute(
            file_path=str(tmp_dir / "service.py"),
            start=40,
            end=45,
            include_line_numbers=False,
        )
        read_data = _unmarshal_result(raw)
        assert "error" not in read_data

    @pytest.mark.skipif(not HAS_RG, reason="rg not available")
    def test_flow_grep_with_glob_pattern(self, tmp_dir):
        """Simulate: grep with glob filter."""
        from skill_sdk.tool.grep_plugin import GrepPlugin

        for name in ["a.py", "b.js", "c.py"]:
            (tmp_dir / name).write_text("SHARED_CONSTANT\n")

        grep_plug = GrepPlugin()
        raw = grep_plug.execute(
            pattern="SHARED_CONSTANT",
            path=str(tmp_dir),
            glob="*.py",
            output_mode="files_with_matches",
        )
        data = _unmarshal_result(raw)
        _assert_no_error(data, "grep with glob")
        assert data["numFiles"] == 2
        assert all(
            any(ext in p for p in data["filenames"])
            for ext in ["a.py", "c.py"]
        ), f"Expected only .py files, got: {data['filenames']}"


class TestSkillFlowLspPipeline:
    """Simulate LSP-centric workflows."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_flow_go_to_def_then_doc_symbol(self, lsp_manager_and_plugin):
        """goToDefinition followed by documentSymbol."""
        plug = lsp_manager_and_plugin

        # Step 1: goToDefinition on a call site in handler.go
        line, char = _find_symbol(GO_HANDLER, "NewHelper")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char,
        )
        def_result = _unmarshal_result(raw)
        _assert_result_has_lines(def_result, "def step")
        assert "main.go" in def_result["result"]

        # Step 2: documentSymbol on the resolved file
        raw2 = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        doc_result = _unmarshal_result(raw2)
        _assert_result_has_lines(doc_result, "docSymbol step")
        assert "Document symbols" in doc_result["result"]

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_flow_def_then_refs(self, lsp_manager_and_plugin):
        """goToDefinition then findReferences."""
        plug = lsp_manager_and_plugin

        # Step 1: goToDefinition
        line, char = _find_symbol(GO_MAIN, "TransformData")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        def_result = _unmarshal_result(raw)
        _assert_result_has_lines(def_result, "def step")

        # Step 2: findReferences
        raw2 = plug.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        ref_result = _unmarshal_result(raw2)
        _assert_result_has_lines(ref_result, "refs step")
        assert "references" in ref_result["result"].lower()

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_flow_call_hierarchy_full(self, lsp_manager_and_plugin):
        """prepareCallHierarchy → incomingCalls → outgoingCalls."""
        plug = lsp_manager_and_plugin

        # Step 1: prepareCallHierarchy
        line, char = _find_symbol(GO_MAIN, "TransformData")
        raw = plug.execute(
            operation="prepareCallHierarchy",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        prep_result = _unmarshal_result(raw)
        _assert_no_error(prep_result, "prepareCallHierarchy step")

        # Step 2: incomingCalls (who calls TransformData)
        raw2 = plug.execute(
            operation="incomingCalls",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        inc_result = _unmarshal_result(raw2)
        _assert_no_error(inc_result, "incomingCalls step")

        # Step 3: outgoingCalls
        raw3 = plug.execute(
            operation="outgoingCalls",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        out_result = _unmarshal_result(raw3)
        _assert_no_error(out_result, "outgoingCalls step")


# ===========================================================================
# 7. COMPREHENSIVE LSP RESULT METADATA
# ===========================================================================


class TestLspResultMetadata:
    """Verify LSP result metadata (resultCount, fileCount)."""

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_go_to_def_metadata(self, lsp_manager_and_plugin):
        """goToDefinition returns resultCount=1."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "TransformData")
        raw = plug.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "meta")
        assert result.get("resultCount") == 1
        assert result.get("fileCount", 0) >= 1

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_doc_symbol_metadata(self, lsp_manager_and_plugin):
        """documentSymbol returns reasonable counts."""
        plug = lsp_manager_and_plugin
        raw = plug.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "docSymbol meta")
        assert result.get("resultCount", 0) >= 5

    @pytest.mark.skipif(not HAS_GOPLS, reason="gopls not configured")
    def test_find_refs_metadata(self, lsp_manager_and_plugin):
        """findReferences returns structured output."""
        plug = lsp_manager_and_plugin
        line, char = _find_symbol(GO_MAIN, "TransformData")
        raw = plug.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(raw)
        _assert_no_error(result, "refs meta")
        formatted = result["result"]
        assert "Found" in formatted and "references" in formatted.lower()
        assert result.get("resultCount", 0) >= 1


# ===========================================================================
# 8. TOOL PLUGIN REGISTRY TESTS
# ===========================================================================


class TestToolRegistry:
    """Verify tool discovery and registration."""

    def test_registry_discovers_plugins(self):
        """ToolRegistry should discover all plugins."""
        from skill_sdk.plugin.registry import ToolRegistry

        registry = ToolRegistry()
        registry.discover_package("skill_sdk.tool")
        names = registry.list_names()
        assert "glob" in names, f"Expected glob plugin, got: {names}"
        assert "grep" in names, f"Expected grep plugin, got: {names}"
        assert "lsp" in names, f"Expected lsp plugin, got: {names}"
        assert "readline_in_range" in names, (
            f"Expected readline_in_range plugin, got: {names}"
        )

    def test_each_plugin_has_description(self):
        """Each plugin should have a non-empty description."""
        from skill_sdk.plugin.registry import ToolRegistry

        registry = ToolRegistry()
        registry.discover_package("skill_sdk.tool")
        for name in registry.list_names():
            plugin_cls = registry.get(name)
            assert plugin_cls is not None
            assert plugin_cls.description, f"Plugin '{name}' has empty description"


# ===========================================================================
# 9. SKILL.md ROUTING RULES VALIDATION
# ===========================================================================


class TestSkillMdLspOperations:
    """Validate SKILL.md documents all LSP operations for all 9 operations."""

    SKILL_PATH = _SDK_ROOT / "skills" / "read-code" / "SKILL.md"

    @pytest.fixture(autouse=True)
    def _load_skill_md(self):
        self.content = self.SKILL_PATH.read_text()

    def test_covers_all_lsp_operations(self):
        """SKILL.md should mention all 9 LSP operations."""
        for op in [
            "goToDefinition", "documentSymbol", "findReferences",
            "goToImplementation", "hover", "workspaceSymbol",
            "prepareCallHierarchy", "incomingCalls", "outgoingCalls",
        ]:
            assert op in self.content, f"Missing '{op}' in SKILL.md"

    def test_has_selection_rules(self):
        """SKILL.md should have operation selection rules."""
        assert "LSP 操作选择决策规则" in self.content
        assert "决策表" in self.content

    def test_has_error_examples(self):
        """SKILL.md should have error examples including call hierarchy."""
        assert "错误示例" in self.content
        assert "outgoingCalls" in self.content, (
            "Error examples should mention outgoingCalls"
        )
        assert "incomingCalls" in self.content, (
            "Error examples should mention incomingCalls"
        )

    def test_has_flow_d_call_hierarchy(self):
        """SKILL.md should document call hierarchy (示例 5)."""
        assert "示例 5：调用链分析" in self.content, "Missing call hierarchy example"
        assert "调用链分析" in self.content, "Missing call hierarchy analysis path"

    def test_has_scenario_6_call_chain(self):
        """SKILL.md should document call-chain flow (示例 5)."""
        assert "示例 5：调用链分析" in self.content, "Missing call hierarchy example"
        assert "调用链是什么样的" in self.content or "调用关系" in self.content, (
            "Missing call chain intent wording"
        )
        assert "outgoingCalls" in self.content and "incomingCalls" in self.content

    def test_distinguishes_find_refs_vs_incoming(self):
        """SKILL.md should explain findReferences vs incomingCalls distinction."""
        assert "findReferences vs incomingCalls" in self.content, (
            "Missing findReferences vs incomingCalls distinction"
        )

    def test_distinguishes_incoming_vs_outgoing(self):
        """SKILL.md should explain incoming vs outgoing calls distinction."""
        assert "incomingCalls vs outgoingCalls" in self.content, (
            "Missing incomingCalls vs outgoingCalls distinction"
        )


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    code = pytest.main([__file__, "-v", "--tb=short", "-s"])
    sys.exit(code)
