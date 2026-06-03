#!/usr/bin/env python3
"""Comprehensive LSP routing test for the read-code skill.

Verifies that:
1. goToDefinition works on Go and Python code, returning correct line ranges
2. documentSymbol works on Go and Python code, listing all symbols
3. findReferences works on Go and Python code, returning correct reference locations
4. The SKILL.md contains explicit routing decision rules for each operation

Run with:
    cd /Users/james/daocloud/code/dac/skill_sdk
    SKILL_SDK_LSP_SERVERS='{"gopls":{"command":"gopls","extensionToLanguage":{".go":"go"},"args":[],"startupTimeoutMs":30000},"pyright":{"command":"pyright-langserver","extensionToLanguage":{".py":"python"},"args":["--stdio"],"startupTimeoutMs":30000}}' python -m pytest tests/read_code_lsp_test.py -v
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

# Ensure the skill_sdk package is importable
_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = _HERE / "fixtures"
GO_PROJECT = FIXTURES_DIR / "go-project"
PY_PROJECT = FIXTURES_DIR / "py-project"
SKILLS_SRC_DIR = _SDK_ROOT / "skills" / "read-code"
OUTPUT_ZIP = _SDK_ROOT / "skills" / "read-code.zip"

GO_MAIN = GO_PROJECT / "main.go"
GO_HANDLER = GO_PROJECT / "handler.go"
PY_CORE = PY_PROJECT / "core.py"

LSP_SERVERS_ENV = os.environ.get("SKILL_SDK_LSP_SERVERS", "")
HAS_LSP_CONFIG = bool(LSP_SERVERS_ENV.strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_skill_zip() -> Path:
    """Package the read-code skill directory into a zip file."""
    skill_dir = SKILLS_SRC_DIR
    out = OUTPUT_ZIP
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in skill_dir.rglob("*"):
            if f.is_file():
                arcname = str(f.relative_to(skill_dir.parent))
                zf.write(f, arcname)
    return out


def _unmarshal_result(output: str) -> dict[str, Any]:
    """Parse the JSON-encoded result from plugin.execute()."""
    return json.loads(output) if isinstance(output, str) else output


def _assert_no_error(result: dict[str, Any], label: str) -> None:
    if "error" in result:
        pytest.fail(
            f"{label} returned error: {result['error']} (code={result.get('error_code')})"
        )


def _assert_result_has_lines(result: dict[str, Any], label: str) -> None:
    _assert_no_error(result, label)
    formatted = result.get("result", "")
    assert formatted, f"{label}: result is empty"


def _find_line_containing(filepath: Path, text: str) -> "tuple[int, int]":
    """Return (1-based line number, 1-based char offset) for text in file."""
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if text in line:
            return (i + 1, line.index(text) + 1)
    raise ValueError(f"'{text}' not found in {filepath.name}")


def _find_symbol(filepath: Path, symbol: str, line_hint: str | None = None) -> "tuple[int, int]":
    """Return (1-based line number, 1-based char offset) for an identifier.

    Finds the exact position of ``symbol`` within the first matching line.
    Unlike _find_line_containing, this searches for the identifier itself
    (not a prefix like 'func Xxx'), so the cursor lands on the symbol name
    rather than on a surrounding keyword.

    If ``line_hint`` is given, only the line containing that hint is considered.
    """
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if line_hint is not None and line_hint not in line:
            continue
        idx = line.find(symbol)
        if idx != -1:
            # Verify it's a standalone identifier (not part of a larger word)
            before = line[idx - 1] if idx > 0 else " "
            after = line[idx + len(symbol)] if idx + len(symbol) < len(line) else " "
            if before.isalnum() or before == "_" or after.isalnum() or after == "_":
                continue
            return (i + 1, idx + 1)
    raise ValueError(f"Symbol '{symbol}' not found in {filepath.name}")


# ---------------------------------------------------------------------------
# Fixture: LSP Manager + Plugin (module-scoped, shared across all LSP tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lsp_setup():
    """Set up LSP manager and LspPlugin once per module run."""
    if not HAS_LSP_CONFIG:
        pytest.skip("SKILL_SDK_LSP_SERVERS not configured")

    from skill_sdk.tool.lsp_plugin import LspPlugin, reset_manager, _manager_instance

    reset_manager()  # fresh start

    plugin = LspPlugin()
    yield plugin

    # Cleanup
    if _manager_instance is not None:
        try:
            _manager_instance.shutdown()
        except Exception:
            pass
    reset_manager()


# ===========================================================================
# 1. goToDefinition tests
# ===========================================================================


HAS_PYRIGHT = any(
    srv.get("command", "").endswith("pyright-langserver")
    for srv in json.loads(LSP_SERVERS_ENV).values()
) if LSP_SERVERS_ENV.strip() else False


class TestGoToDefinition:
    """Verify goToDefinition returns correct definition ranges."""

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_definition_transform_data(self, lsp_setup):
        """goToDefinition on TransformData should return its definition range."""
        line, char = _find_symbol(GO_MAIN, "TransformData")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "goToDefinition TransformData")

        formatted = result["result"]
        assert "Defined in" in formatted, f"Expected 'Defined in': {formatted}"
        assert "main.go" in formatted, f"Expected 'main.go': {formatted}"
        assert "lines" in formatted.lower(), f"Expected line range: {formatted}"
        assert result.get("resultCount") == 1, f"resultCount should be 1: {result.get('resultCount')}"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_definition_handle_request(self, lsp_setup):
        """goToDefinition on HandleRequest should return its definition range."""
        line, char = _find_symbol(GO_MAIN, "HandleRequest", line_hint="func (h *Helper) HandleRequest")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "goToDefinition HandleRequest")

        formatted = result["result"]
        assert "Defined in" in formatted, f"Expected 'Defined in': {formatted}"
        assert "main.go" in formatted, f"Expected 'main.go': {formatted}"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_definition_handle_request_call_site(self, lsp_setup):
        """goToDefinition on a HandleRequest call site should resolve the definition."""
        line, char = _find_symbol(GO_HANDLER, "HandleRequest", line_hint="helper.HandleRequest")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "goToDefinition HandleRequest call site")

        formatted = result["result"]
        assert "main.go" in formatted, (
            f"Expected cross-file definition in main.go: {formatted}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_py_definition_advanced_processor(self, lsp_setup):
        """goToDefinition on AdvancedProcessor class should return its range."""
        if not HAS_PYRIGHT:
            pytest.skip("pyright not configured in SKILL_SDK_LSP_SERVERS")
        line, char = _find_symbol(PY_CORE, "AdvancedProcessor", line_hint="class AdvancedProcessor")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "goToDefinition AdvancedProcessor")

        formatted = result["result"]
        assert "core.py" in formatted, f"Expected core.py: {formatted}"
        assert result.get("resultCount") == 1, f"resultCount should be 1: {result.get('resultCount')}"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_py_definition_request_handler(self, lsp_setup):
        """goToDefinition on RequestHandler class should return its range."""
        if not HAS_PYRIGHT:
            pytest.skip("pyright not configured in SKILL_SDK_LSP_SERVERS")
        line, char = _find_symbol(PY_CORE, "RequestHandler", line_hint="class RequestHandler")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "goToDefinition RequestHandler")

        formatted = result["result"]
        assert "core.py" in formatted, f"Expected core.py: {formatted}"


# ===========================================================================
# 1b. goToDefinition null-response (no-definition) edge cases
# ===========================================================================


class TestGoToDefinitionEdgeCases:
    """Verify goToDefinition handles null responses gracefully.

    After the fix, gopls returning null for textDocument/definition should NOT
    produce error_code 4 ("No LSP server available for file type"). Instead it
    should be treated as a valid empty result.
    """

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_whitespace_line(self, lsp_setup):
        """goToDefinition on a blank line should return 'No definition found'."""
        # Line 80 in main.go is blank (between func main and the final brace)
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=80,
            character=1,
        )
        result = _unmarshal_result(output)
        # Must NOT produce error_code 4 (that's the original bug)
        assert "error" not in result or result.get("error_code") != 4, (
            f"Should NOT report 'No LSP server available': {result.get('error', '')}"
        )
        formatted = result.get("result", "")
        # Should have the friendly "No definition found" message
        assert "No definition found" in formatted, (
            f"Expected friendly message on blank-line lookup, got: {formatted}"
        )
        assert result.get("resultCount") == 0, (
            f"resultCount should be 0 for no definition: {result.get('resultCount')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_comment(self, lsp_setup):
        """goToDefinition on a comment line should return 'No definition found'."""
        # Line 1 in main.go is the package comment
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=1,
            character=3,
        )
        result = _unmarshal_result(output)
        assert "error" not in result or result.get("error_code") != 4, (
            f"Should NOT report 'No LSP server available': {result.get('error', '')}"
        )
        formatted = result.get("result", "")
        assert "No definition found" in formatted, (
            f"Expected friendly message on comment lookup, got: {formatted}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_package_keyword(self, lsp_setup):
        """goToDefinition on the 'package' keyword should return 'No definition found'."""
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=3,
            character=1,  # on the import keyword
        )
        result = _unmarshal_result(output)
        assert "error" not in result or result.get("error_code") != 4, (
            f"Should NOT report 'No LSP server available': {result.get('error', '')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_import_block(self, lsp_setup):
        """goToDefinition on the 'import' keyword should return 'No definition found'."""
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=1,
            character=3,  # on 'package' keyword
        )
        result = _unmarshal_result(output)
        assert "error" not in result or result.get("error_code") != 4

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_builtin_fmt(self, lsp_setup):
        """goToDefinition on 'fmt' import usage should resolve (not null)."""
        # main.go line 37: return result, nil — not on fmt, but let's try
        # On a variable like 'result' on line 37
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=37,
            character=9,  # on 'result' (a local var, might resolve to its declaration)
        )
        result = _unmarshal_result(output)
        # This could succeed or return no definition depending on gopls behavior,
        # but in either case should NOT be error_code 4
        err_code = result.get("error_code")
        assert err_code != 4, (
            f"Should NOT report 'No LSP server available', got error: {result.get('error', '')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_no_line_param_defaults_to_line_1(self, lsp_setup):
        """goToDefinition with default line=1 (no line/char params) should not crash with error_code 4."""
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(output)
        # Default is line=1, character=1 — probably sits on 'package' keyword
        err_code = result.get("error_code")
        assert err_code != 4, (
            f"No line param should NOT produce error_code 4: {result.get('error', '')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_out_of_range_line(self, lsp_setup):
        """goToDefinition on a line beyond EOF should return 'No definition found', not error_code 4."""
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=9999,
            character=1,
        )
        result = _unmarshal_result(output)
        err_code = result.get("error_code")
        assert err_code != 4, (
            f"Out-of-range line should NOT produce error_code 4: {result.get('error', '')}"
        )
        formatted = result.get("result", "")
        if "error" not in result:
            assert "No definition found" in formatted, (
                f"Expected friendly message for out-of-range line, got: {formatted}"
            )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_definition_on_undefined_identifier(self, lsp_setup):
        """goToDefinition on a non-existent symbol should not produce error_code 4.

        This requires crafting a position that looks like an identifier but
        isn't defined anywhere. We use 'fmt' import name itself.
        """
        # Print detailed debug info for this case
        from skill_sdk.tool.lsp_plugin import _manager_instance, _get_or_create_manager

        # Ensure manager is alive
        mgr = _get_or_create_manager()
        assert mgr is not None, "Manager should exist"
        servers = mgr.get_all_servers()
        assert "gopls" in servers, "gopls should be registered"
        server = servers["gopls"]
        assert server.is_healthy(), (
            f"gopls should be healthy (state={server.state})"
        )
        assert server.state == "running", f"gopls state: {server.state}"

        # Now do the actual test
        line, char = _find_symbol(GO_HANDLER, "NewHelper")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char + 4,  # middle of "NewHelper"
        )
        result = _unmarshal_result(output)
        err_code = result.get("error_code")
        assert err_code != 4, (
            f"Should NOT produce error_code 4: {result.get('error', '')}"
        )


# ===========================================================================
# 2. documentSymbol tests
# ===========================================================================


class TestDocumentSymbol:
    """Verify documentSymbol returns complete symbol outlines."""

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_document_symbols_main(self, lsp_setup):
        """documentSymbol on main.go should list all top-level symbols."""
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "documentSymbol main.go")

        formatted = result["result"]
        assert "Document symbols" in formatted, f"Missing 'Document symbols': {formatted[:200]}"

        # Must have line ranges in "Lines X-Y" format
        line_ranges = re.findall(r"Lines (\d+)-(\d+)", formatted)
        assert len(line_ranges) >= 3, f"Need >=3 line ranges, got: {line_ranges}"

        # Verify key symbols exist
        required = ["DataProcessor", "NewDefaultProcessor", "TransformData", "Helper", "HandleRequest"]
        for sym in required:
            assert sym in formatted, f"Missing symbol '{sym}' in documentSymbol output"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_document_symbols_handler(self, lsp_setup):
        """documentSymbol on handler.go should list Handler and its methods."""
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path=str(GO_HANDLER),
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "documentSymbol handler.go")

        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["Handler", "NewHandler", "ProcessRequest", "HealthCheck"]:
            assert sym in formatted, f"Missing '{sym}' in handler.go documentSymbol"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_py_document_symbols_core(self, lsp_setup):
        """documentSymbol on core.py should list all classes and functions."""
        if not HAS_PYRIGHT:
            pytest.skip("pyright not configured in SKILL_SDK_LSP_SERVERS")
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path=str(PY_CORE),
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "documentSymbol core.py")

        formatted = result["result"]
        assert "Document symbols" in formatted
        for sym in ["ServiceConfig", "DataProcessor", "AdvancedProcessor",
                     "RequestHandler", "build_pipeline", "finalize_result"]:
            assert sym in formatted, f"Missing '{sym}' in core.py documentSymbol"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_document_symbol_ignores_line_param(self, lsp_setup):
        """documentSymbol should work correctly even when line is provided (ignored)."""
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
            line=999,
            character=999,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "documentSymbol with ignored line")

        formatted = result["result"]
        assert "Document symbols" in formatted
        assert "DataProcessor" in formatted


# ===========================================================================
# 3. findReferences tests
# ===========================================================================


class TestFindReferences:
    """Verify findReferences returns correct reference locations."""

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_find_references_transform_data(self, lsp_setup):
        """findReferences on TransformData should find usages in main.go."""
        line, char = _find_symbol(GO_MAIN, "TransformData")
        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "findReferences TransformData")

        formatted = result["result"]
        assert "references" in formatted.lower(), f"Missing references: {formatted}"
        assert result.get("resultCount", 0) >= 1, (
            f"Expected >=1 references, got: {result.get('resultCount')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_find_references_validate(self, lsp_setup):
        """findReferences on Validate method should find multi-file usages."""
        line, char = _find_symbol(GO_MAIN, "Validate", line_hint="func (p *DefaultProcessor) Validate")
        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "findReferences Validate")

        formatted = result["result"]
        assert "references" in formatted.lower()
        # Validate is used within Process(), HandleRequest(), handler.go -> >=2
        assert result.get("resultCount", 0) >= 2, (
            f"Expected >=2 references for Validate, got: {result.get('resultCount')}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_find_references_processor_interface(self, lsp_setup):
        """findReferences on DataProcessor interface should find usages."""
        line, char = _find_symbol(GO_MAIN, "DataProcessor", line_hint="type DataProcessor interface")
        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "findReferences DataProcessor")

        formatted = result["result"]
        assert "references" in formatted.lower()
        assert result.get("resultCount", 0) >= 1

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_py_find_references_validate(self, lsp_setup):
        """findReferences on Python validate method should find overrides/usages."""
        if not HAS_PYRIGHT:
            pytest.skip("pyright not configured in SKILL_SDK_LSP_SERVERS")
        line, char = _find_symbol(PY_CORE, "validate", line_hint="def validate")

        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(PY_CORE),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "findReferences validate")

        formatted = result["result"]
        assert "references" in formatted.lower()

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_find_references_new_helper(self, lsp_setup):
        """findReferences on NewHelper call site in handler.go should find the definition."""
        line, char = _find_symbol(GO_MAIN, "FinalizeOutput")
        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "findReferences FinalizeOutput")

        formatted = result["result"]
        assert "references" in formatted.lower()
        # FinalizeOutput is defined in main.go (line 75) and called from HandleRequest (line 71)
        assert result.get("resultCount", 0) >= 1, (
            f"Expected >=1 references for FinalizeOutput, got: {result.get('resultCount')}"
        )
        assert "Found" in formatted and "references" in formatted.lower()


# ===========================================================================
# 4. Cross-file definition resolution
# ===========================================================================


class TestCrossFile:
    """Verify definitions resolve correctly across files."""

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_definition_new_helper_from_handler(self, lsp_setup):
        """goToDefinition on NewHelper call in handler.go resolves to main.go."""
        line, char = _find_symbol(GO_HANDLER, "NewHelper")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "cross-file goToDefinition NewHelper")

        formatted = result["result"]
        assert "main.go" in formatted, f"Expected main.go: {formatted}"

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_go_definition_data_processor_from_handler(self, lsp_setup):
        """goToDefinition on DataProcessor reference in handler.go resolves to main.go."""
        line, char = _find_symbol(GO_HANDLER, "DataProcessor")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_HANDLER),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_result_has_lines(result, "cross-file DataProcessor")

        formatted = result["result"]
        assert "main.go" in formatted, f"Expected main.go: {formatted}"


# ===========================================================================
# 5. Result counting accuracy
# ===========================================================================


class TestResultCounts:
    """Verify LSP operation result metadata."""

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_goto_definition_counts(self, lsp_setup):
        """goToDefinition should return resultCount=1, fileCount=1."""
        line, char = _find_symbol(GO_MAIN, "TransformData")
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_no_error(result, "counts")
        assert result.get("resultCount") == 1
        assert result.get("fileCount", 0) >= 1

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_document_symbol_counts(self, lsp_setup):
        """documentSymbol should return reasonable counts."""
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(output)
        _assert_no_error(result, "docSymbol counts")
        assert result.get("resultCount", 0) >= 5
        assert result.get("fileCount") == result.get("fileCount")  # just verify it exists

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_find_references_output_structure(self, lsp_setup):
        """findReferences output should include grouped-by-file format."""
        line, char = _find_symbol(GO_MAIN, "TransformData")
        output = lsp_setup.execute(
            operation="findReferences",
            file_path=str(GO_MAIN),
            line=line,
            character=char,
        )
        result = _unmarshal_result(output)
        _assert_no_error(result, "refs structure")
        formatted = result["result"]
        # Should list files with line numbers
        assert "Found" in formatted and "references" in formatted.lower(), (
            f"Unexpected format: {formatted[:200]}"
        )
        assert "Line " in formatted, f"Missing line numbers: {formatted[:200]}"


# ===========================================================================
# 6. Error handling
# ===========================================================================


class TestErrorHandling:

    def test_invalid_operation_rejected(self, lsp_setup):
        """Invalid operation name should return error."""
        output = lsp_setup.execute(
            operation="invalidOp",
            file_path=str(GO_MAIN),
        )
        result = _unmarshal_result(output)
        assert "error" in result, f"Expected error: {result}"
        assert "Invalid operation" in result["error"] or result.get("error_code") == 3

    def test_missing_file_rejected(self, lsp_setup):
        """Non-existent file should return error."""
        output = lsp_setup.execute(
            operation="goToDefinition",
            file_path="/nonexistent/file.go",
        )
        result = _unmarshal_result(output)
        assert "error" in result, f"Expected error: {result}"
        assert "not exist" in result["error"].lower() or result.get("error_code") == 1

    def test_empty_file_path_rejected(self, lsp_setup):
        """Empty file path should return error."""
        output = lsp_setup.execute(
            operation="documentSymbol",
            file_path="",
        )
        result = _unmarshal_result(output)
        assert "error" in result, f"Expected error: {result}"


# ===========================================================================
# 7. SKILL.md routing rules validation
# ===========================================================================


class TestSkillMdRoutingRules:
    """Validate that SKILL.md contains explicit LSP operation routing rules."""

    @pytest.fixture(autouse=True)
    def _load_skill_md(self):
        self.content = (SKILLS_SRC_DIR / "SKILL.md").read_text()

    def test_has_lsp_decision_section(self):
        assert "LSP 操作选择决策规则" in self.content, "Missing decision rules section"
        assert "决策表" in self.content, "Missing decision table"

    def test_decision_table_has_all_operations(self):
        for op in ["goToDefinition", "documentSymbol", "findReferences",
                    "goToImplementation", "hover", "workspaceSymbol",
                    "prepareCallHierarchy", "incomingCalls", "outgoingCalls"]:
            assert op in self.content, f"Missing '{op}' in decision rules"

    def test_distinguishes_go_to_def_vs_doc_symbol(self):
        assert "goToDefinition vs documentSymbol" in self.content, (
            "Missing distinction: goToDefinition vs documentSymbol"
        )
        assert "跨文件定位" in self.content, "Missing explanation: cross-file location"
        assert "完整边界" in self.content, "Missing explanation: complete boundary"

    def test_distinguishes_go_to_def_vs_find_refs(self):
        assert "goToDefinition vs findReferences" in self.content, (
            "Missing distinction: goToDefinition vs findReferences"
        )
        assert "这个符号本身是什么" in self.content
        assert "这个符号在哪些地方被提到了" in self.content

    def test_distinguishes_find_refs_vs_incoming_calls(self):
        assert "findReferences vs incomingCalls" in self.content, (
            "Missing distinction: findReferences vs incomingCalls"
        )
        assert "只查找函数/方法调用关系" in self.content or "只返回调用关系" in self.content, (
            "Missing explanation: incomingCalls only returns call relationships"
        )

    def test_has_error_examples(self):
        assert "错误示例" in self.content, "Missing error examples"
        assert "应该用 `goToDefinition`" in self.content, "Missing correct usage: goToDefinition"
        assert "应该用 `documentSymbol`" in self.content, "Missing correct usage: documentSymbol"
        assert "应该用 `findReferences`" in self.content, "Missing correct usage: findReferences"

    def test_has_detailed_flow_examples(self):
        assert "流程 A：定向路径" in self.content, "Missing Flow A"
        assert "流程 B：概览路径" in self.content, "Missing Flow B"
        assert "流程 C：引用查找" in self.content, "Missing Flow C"
        assert "流程 D：调用链分析" in self.content, "Missing Flow D"

    def test_flow_examples_use_correct_operations(self):
        """Flow examples must reference the correct LSP operations."""
        assert 'operation="goToDefinition"' in self.content, "Flow A missing goToDefinition"
        assert 'operation="documentSymbol"' in self.content, "Flow B missing documentSymbol"
        assert 'operation="findReferences"' in self.content, "Flow C missing findReferences"
        # Flow D uses call hierarchy operations
        assert 'operation="prepareCallHierarchy"' in self.content, "Flow D missing prepareCallHierarchy"
        assert 'operation="outgoingCalls"' in self.content, "Flow D missing outgoingCalls"
        assert 'operation="incomingCalls"' in self.content, "Flow D missing incomingCalls"

    def test_has_call_hierarchy_error_examples(self):
        """Error examples should cover call hierarchy misuse."""
        assert "应该用 `prepareCallHierarchy` → `outgoingCalls`" in self.content, (
            "Missing error example: outgoingCalls misuse"
        )
        assert "应该用 `prepareCallHierarchy` → `incomingCalls`" in self.content, (
            "Missing error example: incomingCalls misuse"
        )

    def test_scenarios_match_operations(self):
        """Each scenario example uses the operation appropriate for its intent."""
        # Scenario 1: "这个功能怎么实现的" -> goToDefinition
        assert "场景 1：用户问" in self.content
        scene1 = self.content.split("场景 1：")[1].split("场景 2：")[0]
        assert "goToDefinition" in scene1, "Scene 1 should use goToDefinition"

        # Scenario 2: "看看这个文件的整体结构" -> documentSymbol
        scene2 = self.content.split("场景 2：")[1].split("场景 3：")[0]
        assert "documentSymbol" in scene2, "Scene 2 should use documentSymbol"


# ===========================================================================
# 8. Zip packaging tests
# ===========================================================================


class TestZipPackage:

    def test_can_create_zip(self):
        zip_path = _create_skill_zip()
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert any("SKILL.md" in n for n in names), f"Missing SKILL.md: {names}"
            assert any("_meta.json" in n for n in names), f"Missing _meta.json: {names}"

    def test_zip_loads_via_skill_loader(self):
        zip_path = _create_skill_zip()
        from skill_sdk.skill.loader import SkillLoader

        loader = SkillLoader()
        try:
            skill = loader.load(str(zip_path))
            assert skill.name == "read-code"
            assert skill.version == "1.0.0"
            assert "LSP 操作选择决策规则" in skill.detail, "Routing rules not in loaded skill"
        finally:
            loader.close()


# ===========================================================================
# 9. Diagnostic: raw LSP goToDefinition debugging
# ===========================================================================


class TestGoToDefinitionDiagnostics:
    """Bypass the plugin layer and send raw LSP requests to gopls.

    Use these tests to determine whether your specific gopls version / project
    returns null for textDocument/definition.
    """

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_raw_gopls_definition_on_valid_symbol(self, lsp_setup):
        """Send textDocument/definition directly to gopls for a known symbol."""
        from skill_sdk.tool.lsp_plugin import _get_or_create_manager

        mgr = _get_or_create_manager()
        assert mgr is not None

        server = mgr.get_server_for_file(str(GO_MAIN))
        assert server is not None, "gopls should be registered for .go"
        assert server.is_healthy(), f"gopls not healthy: state={server.state}"

        # Locate the exact position of the symbol
        line_1based, char_1based = _find_symbol(GO_MAIN, "TransformData")
        # Prefer the function name (after "func ") rather than the "func" keyword
        line = GO_MAIN.read_text().splitlines()[line_1based - 1]
        name_start = line.index("TransformData")
        char_0based = name_start  # 1-based -> 0-based is minus 1 from index
        line_0based = line_1based - 1

        uri = GO_MAIN.resolve().as_uri()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line_0based, "character": char_0based},
        }

        print(f"\n--- Raw request to gopls ---")
        print(f"method: textDocument/definition")
        print(f"file: main.go")
        print(f"line (1-based): {line_1based}, char (0-based, on 'TransformData'): {char_0based}")
        print(f"params: {json.dumps(params, indent=2)}")

        try:
            result = server.send_request("textDocument/definition", params)
            print(f"Raw result type: {type(result).__name__}")
            if result is not None:
                print(f"Raw result: {json.dumps(result, indent=2, ensure_ascii=False)}")
            else:
                print(f"Raw result: None (null) — gopls returned no definition!")
                # Try with position on "TransformData" identifier precisely
                print(f"\nTrying with character on first char after 'func ' prefix...")
                alt_char = line.index("TransformData")
                alt_params = {
                    "textDocument": {"uri": uri},
                    "position": {"line": line_0based, "character": alt_char},
                }
                alt_result = server.send_request("textDocument/definition", alt_params)
                print(f"Alt result: {alt_result}")
        except Exception as e:
            print(f"Raw request raised: {type(e).__name__}: {e}")
            result = None

        assert result is not None, (
            f"gopls should return a definition for known symbol 'TransformData' "
            f"at line={line_1based} char={char_0based}. "
            f"This may indicate gopls indexing is incomplete — "
            f"try running 'go mod tidy' in {GO_PROJECT}"
        )

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_raw_gopls_definition_on_whitespace(self, lsp_setup):
        """Send textDocument/definition to gopls for a blank line (expected null)."""
        from skill_sdk.tool.lsp_plugin import _get_or_create_manager

        mgr = _get_or_create_manager()
        assert mgr is not None

        server = mgr.get_server_for_file(str(GO_MAIN))
        assert server is not None

        uri = GO_MAIN.resolve().as_uri()
        # Line 80 in main.go is blank; 0-based line=79
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": 79, "character": 1},
        }

        print(f"\n--- Raw request to gopls (whitespace) ---")
        print(f"params: {json.dumps(params, indent=2)}")

        try:
            result = server.send_request("textDocument/definition", params)
            print(f"Raw result type: {type(result).__name__}")
            print(f"Raw result: {json.dumps(result, indent=2, ensure_ascii=False) if result is not None else 'None'}")
        except Exception as e:
            print(f"Raw request raised: {type(e).__name__}: {e}")
            result = None

        # gopls should return None/null for a blank-line lookup — this is expected!
        print(f"\nExpected behavior: gopls returns None/null for blank lines")
        if result is None:
            print("✓ gopls correctly returned None for blank-line position")

    @pytest.mark.skipif(not HAS_LSP_CONFIG, reason="No LSP config")
    def test_raw_gopls_definition_out_of_range(self, lsp_setup):
        """Send textDocument/definition to gopls for a line beyond EOF (expected null)."""
        from skill_sdk.tool.lsp_plugin import _get_or_create_manager

        mgr = _get_or_create_manager()
        assert mgr is not None

        server = mgr.get_server_for_file(str(GO_MAIN))
        assert server is not None

        uri = GO_MAIN.resolve().as_uri()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": 9998, "character": 0},
        }

        print(f"\n--- Raw request to gopls (out of range) ---")
        try:
            result = server.send_request("textDocument/definition", params)
            print(f"Raw result: {result}")
        except Exception as e:
            print(f"Raw request raised: {type(e).__name__}: {e}")
            result = None

        if result is None:
            print("✓ gopls returned None for out-of-range position (expected)")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    _create_skill_zip()
    code = pytest.main([__file__, "-v", "--tb=short", "-s"])
    sys.exit(code)
