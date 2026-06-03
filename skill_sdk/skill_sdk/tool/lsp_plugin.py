"""LSP ToolPlugin — Language Server Protocol code intelligence (Claude Code LSPTool port).

Provides go-to-definition, find-references, hover, document/workspace symbols,
call hierarchy, and go-to-implementation via the skill_sdk LSP stack.

"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)

LSP_TOOL_NAME = "lsp"

DESCRIPTION = """Interact with Language Server Protocol (LSP) servers to get code intelligence features.

Supported operations:
- goToDefinition: Find where a symbol is defined
- findReferences: Find all references to a symbol
- hover: Get hover information (documentation, type info) for a symbol
- documentSymbol: Get all symbols (functions, classes, variables) in a document
- workspaceSymbol: Search for symbols across the entire workspace
- goToImplementation: Find implementations of an interface or abstract method
- prepareCallHierarchy: Get call hierarchy item at a position (functions/methods)
- incomingCalls: Find all functions/methods that call the function at a position
- outgoingCalls: Find all functions/methods called by the function at a position

All operations require:
- filePath: The file to operate on
- line: The line number (1-based). Required for goToDefinition, findReferences, hover,
      goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls.
      Optional (ignored) for documentSymbol, workspaceSymbol.
- character: The character offset (1-based). Same requirements as line.

Note: LSP servers must be configured for the file type. If no server is available, an error will be returned."""

MAX_LSP_FILE_SIZE_BYTES = 10_000_000


# ---------------------------------------------------------------------------
# LSP Operation types & dispatch
# ---------------------------------------------------------------------------

Operation = Literal[
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "prepareCallHierarchy",
    "incomingCalls",
    "outgoingCalls",
]

ALL_OPERATIONS: tuple[Operation, ...] = (
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "prepareCallHierarchy",
    "incomingCalls",
    "outgoingCalls",
)


def _is_valid_operation(value: str) -> bool:
    return value in ALL_OPERATIONS


# ---------------------------------------------------------------------------
# SymbolKind → human-readable name (LSP SymbolKind enum, same as TS formatters)
# ---------------------------------------------------------------------------

SYMBOL_KINDS: dict[int, str] = {
    1: "File",
    2: "Module",
    3: "Namespace",
    4: "Package",
    5: "Class",
    6: "Method",
    7: "Property",
    8: "Field",
    9: "Constructor",
    10: "Enum",
    11: "Interface",
    12: "Function",
    13: "Variable",
    14: "Constant",
    15: "String",
    16: "Number",
    17: "Boolean",
    18: "Array",
    19: "Object",
    20: "Key",
    21: "Null",
    22: "EnumMember",
    23: "Struct",
    24: "Event",
    25: "Operator",
    26: "TypeParameter",
}


def _symbol_kind_name(kind: int) -> str:
    return SYMBOL_KINDS.get(kind, "Unknown")


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


def _file_uri_to_path(uri: str) -> str:
    """Best-effort ``file://`` URI → local path (POSIX + common Windows URIs)."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    path = unquote(parsed.path or "")
    if parsed.netloc:
        return f"//{parsed.netloc}{path}"
    return path


def _format_uri(uri: str, cwd: str | None = None) -> str:
    """Format a URI to a (relative if possible) filesystem path."""
    if not uri:
        return "<unknown location>"
    file_path = _file_uri_to_path(uri)
    if cwd:
        try:
            rel = os.path.relpath(file_path, cwd).replace("\\", "/")
            if len(rel) < len(file_path) and not rel.startswith("../"):
                return rel
        except ValueError:
            pass
    return file_path.replace("\\", "/")


def _format_location(uri: str, line: int, character: int, cwd: str | None = None) -> str:
    """Format a location as ``path:line:char`` (1-based line/char)."""
    fp = _format_uri(uri, cwd)
    return f"{fp}:{line}:{character}"


# ---------------------------------------------------------------------------
# LSP param building
# ---------------------------------------------------------------------------


def _build_params(
    operation: Operation,
    file_path: str,
    line: int,
    character: int,
) -> tuple[str, Any]:
    """Map an LSPTool operation to a (LSP-method, params) pair.

    ``line`` / ``character`` are 1-based and converted to 0-based LSP protocol.
    """
    from pathlib import Path as _Path

    uri = _Path(file_path).resolve().as_uri()
    position = {"line": line - 1, "character": character - 1}

    method_map: dict[Operation, tuple[str, dict[str, Any]]] = {
        "goToDefinition": (
            "textDocument/definition",
            {"textDocument": {"uri": uri}, "position": position},
        ),
        "findReferences": (
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": position,
                "context": {"includeDeclaration": True},
            },
        ),
        "hover": (
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": position},
        ),
        "documentSymbol": (
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        ),
        "workspaceSymbol": (
            "workspace/symbol",
            {"query": ""},
        ),
        "goToImplementation": (
            "textDocument/implementation",
            {"textDocument": {"uri": uri}, "position": position},
        ),
        "prepareCallHierarchy": (
            "textDocument/prepareCallHierarchy",
            {"textDocument": {"uri": uri}, "position": position},
        ),
        "incomingCalls": (
            "textDocument/prepareCallHierarchy",
            {"textDocument": {"uri": uri}, "position": position},
        ),
        "outgoingCalls": (
            "textDocument/prepareCallHierarchy",
            {"textDocument": {"uri": uri}, "position": position},
        ),
    }
    return method_map[operation]


# ---------------------------------------------------------------------------
# Result formatters (port of formatters.ts)
# ---------------------------------------------------------------------------


def _multiline_list(items: list[str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}{item}" for item in items)


def _format_go_to_definition(result: Any, cwd: str | None = None) -> str:
    if not result:
        return (
            "No definition found. This may occur if the cursor is not on a symbol, "
            "or if the definition is in an external library not indexed by the LSP server."
        )

    # Normalise to list
    if not isinstance(result, list):
        result = [result]
    locations = [_to_location(item) for item in result if item is not None]
    valid = [loc for loc in locations if loc and loc.get("uri")]
    if not valid:
        return (
            "No definition found. This may occur if the cursor is not on a symbol, "
            "or if the definition is in an external library not indexed by the LSP server."
        )

    if len(valid) == 1:
        loc = valid[0]
        start_line = loc["range"]["start"]["line"] + 1
        end_line = loc["range"]["end"]["line"] + 1
        char = loc["range"]["start"]["character"] + 1
        return f"Defined in {_format_location(loc['uri'], start_line, char, cwd)} (lines {start_line}-{end_line})"

    lines = [f"Found {len(valid)} definitions:"]
    for loc in valid:
        line = loc["range"]["start"]["line"] + 1
        char = loc["range"]["start"]["character"] + 1
        lines.append(f"  {_format_location(loc['uri'], line, char, cwd)}")
    return "\n".join(lines)


def _to_location(item: Any) -> dict[str, Any] | None:
    """Normalise a Location or LocationLink to a Location-like dict."""
    if isinstance(item, dict):
        if "targetUri" in item:
            return {
                "uri": item["targetUri"],
                "range": item.get("targetSelectionRange") or item.get("targetRange", {}),
            }
        if "uri" in item:
            return item
    return None


def _format_find_references(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return (
            "No references found. This may occur if the symbol has no usages, "
            "or if the LSP server has not fully indexed the workspace."
        )
    valid = [loc for loc in result if loc and isinstance(loc, dict) and loc.get("uri")]
    if not valid:
        return (
            "No references found. This may occur if the symbol has no usages, "
            "or if the LSP server has not fully indexed the workspace."
        )

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = {}
    for loc in valid:
        fp = _format_uri(loc["uri"], cwd)
        by_file.setdefault(fp, []).append(loc)

    lines = [f"Found {len(valid)} references across {len(by_file)} files:"]
    for file_path, locs in by_file.items():
        lines.append(f"\n{file_path}:")
        for loc in locs:
            ln = loc["range"]["start"]["line"] + 1
            ch = loc["range"]["start"]["character"] + 1
            lines.append(f"  Line {ln}:{ch}")
    return "\n".join(lines)


def _extract_markup_text(contents: Any) -> str:
    """Extract text from Hover contents (MarkupContent | MarkedString | list)."""
    if contents is None:
        return ""
    if isinstance(contents, list):
        return "\n\n".join(
            item if isinstance(item, str) else (item.get("value", "") if isinstance(item, dict) else str(item))
            for item in contents
        )
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        if "kind" in contents:
            return contents.get("value", "")
        return contents.get("value", "")
    return str(contents)


def _format_hover(result: Any, cwd: str | None = None) -> str:
    if not result:
        return (
            "No hover information available. This may occur if the cursor is not on a symbol, "
            "or if the LSP server has not fully indexed the file."
        )
    content = _extract_markup_text(result.get("contents"))
    rng = result.get("range")
    if rng:
        ln = rng["start"]["line"] + 1
        ch = rng["start"]["character"] + 1
        return f"Hover info at {ln}:{ch}:\n\n{content}"
    return content


def _format_document_symbol_node(symbol: dict[str, Any], indent: int = 0) -> list[str]:
    prefix = "  " * indent
    kind = _symbol_kind_name(symbol.get("kind", 0))
    name = symbol.get("name", "?")
    detail = symbol.get("detail", "")
    rng = symbol.get("range", {})
    start_ln = (rng.get("start") or {}).get("line", 0) + 1
    end_ln = (rng.get("end") or {}).get("line", 0) + 1
    line = f"{prefix}{name} ({kind})"
    if detail:
        line += f" {detail}"
    line += f" - Lines {start_ln}-{end_ln}"
    lines = [line]
    for child in symbol.get("children", []):
        lines.extend(_format_document_symbol_node(child, indent + 1))
    return lines


def _format_document_symbol(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return (
            "No symbols found in document. This may occur if the file is empty, "
            "not supported by the LSP server, or if the server has not fully indexed the file."
        )

    first = result[0]
    is_symbol_info = isinstance(first, dict) and "location" in first

    if is_symbol_info:
        # Delegate to workspace symbol formatter
        return _format_workspace_symbol(result, cwd)

    # DocumentSymbol[] (hierarchical)
    lines = ["Document symbols:"]
    for sym in result:
        lines.extend(_format_document_symbol_node(sym))
    return "\n".join(lines)


def _format_workspace_symbol(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return (
            "No symbols found in workspace. This may occur if the workspace is empty, "
            "or if the LSP server has not finished indexing the project."
        )
    valid = [
        s
        for s in result
        if isinstance(s, dict) and s.get("location") and s["location"].get("uri")
    ]
    if not valid:
        return (
            "No symbols found in workspace. This may occur if the workspace is empty, "
            "or if the LSP server has not finished indexing the project."
        )

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = {}
    for sym in valid:
        fp = _format_uri(sym["location"]["uri"], cwd)
        by_file.setdefault(fp, []).append(sym)

    lines = [f"Found {len(valid)} {_plural(len(valid), 'symbol')} in workspace:"]
    for file_path, symbols in by_file.items():
        lines.append(f"\n{file_path}:")
        for sym in symbols:
            kind = _symbol_kind_name(sym.get("kind", 0))
            start_ln = sym["location"]["range"]["start"]["line"] + 1
            end_ln = sym["location"]["range"]["end"]["line"] + 1
            sl = f"  {sym.get('name', '?')} ({kind}) - Lines {start_ln}-{end_ln}"
            container = sym.get("containerName")
            if container:
                sl += f" in {container}"
            lines.append(sl)
    return "\n".join(lines)


def _format_call_hierarchy_item(item: dict[str, Any], cwd: str | None = None) -> str:
    uri = item.get("uri", "")
    kind = _symbol_kind_name(item.get("kind", 0))
    name = item.get("name", "?")
    start_ln = (item.get("range", {}) or {}).get("start", {}).get("line", 0) + 1
    end_ln = (item.get("range", {}) or {}).get("end", {}).get("line", 0) + 1
    fp = _format_uri(uri, cwd)
    result = f"{name} ({kind}) - {fp}:{start_ln}-{end_ln}"
    detail = item.get("detail")
    if detail:
        result += f" [{detail}]"
    return result


def _format_prepare_call_hierarchy(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return "No call hierarchy item found at this position"
    if len(result) == 1:
        return f"Call hierarchy item: {_format_call_hierarchy_item(result[0], cwd)}"
    lines = [f"Found {len(result)} call hierarchy items:"]
    for item in result:
        lines.append(f"  {_format_call_hierarchy_item(item, cwd)}")
    return "\n".join(lines)


def _format_incoming_calls(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return "No incoming calls found (nothing calls this function)"
    lines = [f"Found {len(result)} incoming {_plural(len(result), 'call')}:"]

    by_file: dict[str, list[dict[str, Any]]] = {}
    for call in result:
        if not isinstance(call, dict) or not call.get("from"):
            continue
        fp = _format_uri(call["from"].get("uri", ""), cwd)
        by_file.setdefault(fp, []).append(call)

    for file_path, calls in by_file.items():
        lines.append(f"\n{file_path}:")
        for call in calls:
            frm = call.get("from", {})
            kind = _symbol_kind_name(frm.get("kind", 0))
            start_ln = (frm.get("range", {}) or {}).get("start", {}).get("line", 0) + 1
            end_ln = (frm.get("range", {}) or {}).get("end", {}).get("line", 0) + 1
            cl = f"  {frm.get('name', '?')} ({kind}) - Lines {start_ln}-{end_ln}"
            from_ranges = call.get("fromRanges")
            if from_ranges:
                sites = ", ".join(
                    f"{r.get('start', {}).get('line', 0) + 1}:{r.get('start', {}).get('character', 0) + 1}"
                    for r in from_ranges
                )
                cl += f" [calls at: {sites}]"
            lines.append(cl)
    return "\n".join(lines)


def _format_outgoing_calls(result: Any, cwd: str | None = None) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        return "No outgoing calls found (this function calls nothing)"
    lines = [f"Found {len(result)} outgoing {_plural(len(result), 'call')}:"]

    by_file: dict[str, list[dict[str, Any]]] = {}
    for call in result:
        if not isinstance(call, dict) or not call.get("to"):
            continue
        fp = _format_uri(call["to"].get("uri", ""), cwd)
        by_file.setdefault(fp, []).append(call)

    for file_path, calls in by_file.items():
        lines.append(f"\n{file_path}:")
        for call in calls:
            to = call.get("to", {})
            kind = _symbol_kind_name(to.get("kind", 0))
            start_ln = (to.get("range", {}) or {}).get("start", {}).get("line", 0) + 1
            end_ln = (to.get("range", {}) or {}).get("end", {}).get("line", 0) + 1
            cl = f"  {to.get('name', '?')} ({kind}) - Lines {start_ln}-{end_ln}"
            from_ranges = call.get("fromRanges")
            if from_ranges:
                sites = ", ".join(
                    f"{r.get('start', {}).get('line', 0) + 1}:{r.get('start', {}).get('character', 0) + 1}"
                    for r in from_ranges
                )
                cl += f" [called from: {sites}]"
            lines.append(cl)
    return "\n".join(lines)


_FORMATTERS: dict[Operation, Any] = {
    "goToDefinition": _format_go_to_definition,
    "findReferences": _format_find_references,
    "hover": _format_hover,
    "documentSymbol": _format_document_symbol,
    "workspaceSymbol": _format_workspace_symbol,
    "goToImplementation": _format_go_to_definition,  # same format
    "prepareCallHierarchy": _format_prepare_call_hierarchy,
    "incomingCalls": _format_incoming_calls,
    "outgoingCalls": _format_outgoing_calls,
}


def _plural(n: int, singular: str) -> str:
    return singular if n == 1 else singular + "s"


# ---------------------------------------------------------------------------
# Helper: count symbols (including nested)
# ---------------------------------------------------------------------------


def _count_symbols(symbols: list[dict[str, Any]]) -> int:
    count = len(symbols)
    for sym in symbols:
        children = sym.get("children") or []
        count += _count_symbols(children)
    return count


def _count_unique_file_uris(items: list[dict[str, Any]], uri_key: str = "uri") -> int:
    uris = set()
    for item in items:
        u = item.get(uri_key)
        if isinstance(u, str):
            uris.add(u)
    return len(uris)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class LspInput(BaseModel):
    operation: str = Field(description="The LSP operation to perform")
    file_path: str = Field(
        description="The absolute or relative path to the file",
    )
    line: int = Field(
        default=1,
        ge=1,
        description="The line number (1-based, as shown in editors). Required for goToDefinition, "
        "findReferences, hover, goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls. "
        "Optional (ignored) for documentSymbol, workspaceSymbol.",
    )
    character: int | None = Field(
        default=None,
        description="[Deprecated] The character offset (1-based). Prefer using symbol_name instead — "
        "the SDK will auto-compute the exact offset from the line content, which is more reliable.",
    )
    symbol_name: str | None = Field(
        default=None,
        description="The identifier name (e.g. function/method/variable name) to look up. "
        "When provided, the SDK reads the specified line from the file and computes the exact "
        "character offset automatically. This is the recommended approach for all position-dependent "
        "operations (goToDefinition, findReferences, hover, goToImplementation, prepareCallHierarchy, "
        "incomingCalls, outgoingCalls). Ignored for documentSymbol and workspaceSymbol.",
    )


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class LspPlugin(ToolPlugin):
    """Code intelligence via LSP (go-to-definition, references, hover, symbols, call hierarchy)."""

    name = LSP_TOOL_NAME
    description = DESCRIPTION.strip()
    args_schema = LspInput

    def execute(self, **kwargs: Any) -> str:
        # ---- validate operation ------------------------------------------------
        operation_raw = kwargs.get("operation", "")
        if not _is_valid_operation(operation_raw):
            return json.dumps(
                {
                    "error": f"Invalid operation: {operation_raw!r}. "
                    f"Valid operations: {', '.join(ALL_OPERATIONS)}",
                    "error_code": 3,
                },
                ensure_ascii=False,
            )
        operation: Operation = operation_raw  # type: ignore[assignment]

        file_path = kwargs.get("file_path", "")
        line = int(kwargs.get("line", 1))

        # ---- resolve file ------------------------------------------------------
        if not file_path:
            return json.dumps(
                {"error": "file_path is required", "error_code": 1},
                ensure_ascii=False,
            )

        expanded = os.path.expanduser(file_path)
        abs_path = os.path.abspath(expanded)
        fp_path = Path(abs_path)

        if not fp_path.exists():
            return json.dumps(
                {"error": f"File does not exist: {file_path}", "error_code": 1},
                ensure_ascii=False,
            )
        if not fp_path.is_file():
            return json.dumps(
                {"error": f"Path is not a file: {file_path}", "error_code": 2},
                ensure_ascii=False,
            )

        # ---- auto-compute character from symbol_name ---------------------------
        symbol_name: str | None = kwargs.get("symbol_name")
        if symbol_name:
            try:
                with open(str(fp_path), "r", encoding="utf-8") as f:
                    file_lines = f.readlines()
                if line - 1 >= len(file_lines):
                    return json.dumps(
                        {
                            "error": f"line {line} exceeds file length ({len(file_lines)} lines)",
                            "error_code": 8,
                        },
                        ensure_ascii=False,
                    )
                line_content = file_lines[line - 1]
                idx = line_content.find(symbol_name)
                if idx == -1:
                    return json.dumps(
                        {
                            "error": f"symbol '{symbol_name}' not found on line {line}",
                            "error_code": 8,
                        },
                        ensure_ascii=False,
                    )
                character = idx + 1  # 1-based
            except Exception as exc:
                return json.dumps(
                    {"error": f"Failed to auto-compute character from symbol_name: {exc}", "error_code": 8},
                    ensure_ascii=False,
                )
        else:
            raw_char = kwargs.get("character")
            character = int(raw_char) if raw_char is not None else 1

        # ---- size check --------------------------------------------------------
        file_size = fp_path.stat().st_size
        if file_size > MAX_LSP_FILE_SIZE_BYTES:
            return json.dumps(
                {
                    "error": f"File too large for LSP analysis "
                    f"({(file_size + 999_999) // 1_000_000}MB exceeds 10MB limit)",
                },
                ensure_ascii=False,
            )

        cwd = os.getcwd()

        # ---- import LSP stack (lazy to avoid early init) -----------------------
        try:
            from skill_sdk.tool.lsp import LSPServerManager, create_lsp_server_manager
        except ImportError as exc:
            return json.dumps(
                {"error": f"LSP stack not available: {exc}", "error_code": 5},
                ensure_ascii=False,
            )

        # ---- acquire (or create) manager ---------------------------------------
        manager = _get_or_create_manager()
        if manager is None:
            return json.dumps(
                {"error": "LSP server manager not initialized", "error_code": 5},
                ensure_ascii=False,
            )

        # ---- ensure file is open in LSP ----------------------------------------
        try:
            _ensure_file_open(manager, str(fp_path.resolve()))
        except Exception as exc:
            logger.exception("Failed to open file in LSP server")
            return json.dumps(
                {"error": f"Failed to open file in LSP server: {exc}", "error_code": 6},
                ensure_ascii=False,
            )

        # ---- build method + params ---------------------------------------------
        method, params = _build_params(operation, str(fp_path.resolve()), line, character)

        # ---- send request ------------------------------------------------------
        server = manager.ensure_server_started(str(fp_path.resolve()))
        if server is None:
            ext = fp_path.suffix
            return json.dumps(
                {
                    "error": f"No LSP server available for file type: {ext}",
                    "error_code": 4,
                },
                ensure_ascii=False,
            )

        try:
            result = server.send_request(method, params)
        except Exception as exc:
            err_str = str(exc)
            # Treat "identifier not found" / "no result" from LSP as empty result
            if any(phrase in err_str.lower() for phrase in ["identifier not found", "no identifier found", "no definition found", "no result"]):
                result = None
            elif "unhandled method" in err_str.lower():
                return json.dumps(
                    {
                        "error": f"LSP server does not support operation '{operation}': {err_str}",
                        "error_code": 7,
                    },
                    ensure_ascii=False,
                )
            else:
                return json.dumps(
                    {
                        "error": f"Error performing {operation}: {err_str}",
                        "error_code": 7,
                    },
                    ensure_ascii=False,
                )

        # ---- two-step for incoming/outgoing calls ------------------------------
        if operation in ("incomingCalls", "outgoingCalls"):
            call_items = result if isinstance(result, list) else []
            if not call_items:
                return json.dumps(
                    {
                        "operation": operation,
                        "result": "No call hierarchy item found at this position",
                        "filePath": file_path,
                        "resultCount": 0,
                        "fileCount": 0,
                    },
                    ensure_ascii=False,
                )
            call_method = (
                "callHierarchy/incomingCalls"
                if operation == "incomingCalls"
                else "callHierarchy/outgoingCalls"
            )
            try:
                result = manager.send_request(str(fp_path.resolve()), call_method, {"item": call_items[0]})
            except Exception as exc:
                logger.exception("LSP call hierarchy request failed")
                result = None

        # ---- format result -----------------------------------------------------
        formatter = _FORMATTERS[operation]
        formatted = formatter(result, cwd)

        # ---- compute result/file counts ----------------------------------------
        result_count = _compute_result_count(operation, result)
        file_count = _compute_file_count(operation, result)

        return json.dumps(
            {
                "operation": operation,
                "result": formatted,
                "filePath": file_path,
                "resultCount": result_count,
                "fileCount": file_count,
            },
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Module-level manager singleton
# ---------------------------------------------------------------------------

_manager_instance: LSPServerManager | None = None


def _lsp_index_wait_ms_after_prestart() -> int:
    """Millis to sleep after all LSP servers pre-start so workspace indexing can catch up.

    Override with env ``SKILL_SDK_LSP_INDEX_WAIT_MS`` (``0`` disables). If unset,
    defaults to 5000 ms. Pytest sets this to ``0`` via ``tests/conftest.py`` setdefault.
    """
    raw = os.environ.get("SKILL_SDK_LSP_INDEX_WAIT_MS", "").strip()
    if not raw:
        return 5000
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid SKILL_SDK_LSP_INDEX_WAIT_MS=%r; using 0", raw)
        return 0


def _get_or_create_manager() -> LSPServerManager | None:
    """Return the existing manager singleton, or create one from env config.

    When a new manager is created, **all registered LSP servers are pre-started**
    so that startup failures (command not found, timeout, etc.) are surfaced
    immediately rather than on the first tool call.
    """
    global _manager_instance
    if _manager_instance is not None:
        return _manager_instance

    config_json = os.environ.get("SKILL_SDK_LSP_SERVERS", "").strip()
    if not config_json:
        logger.warning("SKILL_SDK_LSP_SERVERS not set; LSP tool unavailable")
        return None

    try:
        raw: dict[str, Any] = json.loads(config_json)
    except json.JSONDecodeError as exc:
        logger.warning("SKILL_SDK_LSP_SERVERS is not valid JSON: %s", exc)
        return None

    from skill_sdk.tool.lsp import LSPServerManager, ScopedLspServerConfig, create_lsp_server_manager

    servers: dict[str, ScopedLspServerConfig] = {}
    for name, cfg in raw.items():
        command = cfg.get("command", "")
        extension_to_language = cfg.get("extensionToLanguage") or cfg.get("extension_to_language") or {}
        args = cfg.get("args") or []
        env = cfg.get("env")
        workspace_folder = cfg.get("workspaceFolder") or cfg.get("workspace_folder")

        # Override from environment (applies to all servers)
        env_ws = os.environ.get("WORKSPACE_FOLDER", "").strip()
        if env_ws:
            workspace_folder = env_ws
        init_opts = cfg.get("initializationOptions") or cfg.get("initialization_options")
        max_restarts = cfg.get("maxRestarts") or cfg.get("max_restarts")
        startup_timeout_ms = cfg.get("startupTimeoutMs") or cfg.get("startup_timeout_ms")
        servers[name] = ScopedLspServerConfig(
            command=command,
            extension_to_language=extension_to_language,
            args=args,
            env=env,
            workspace_folder=workspace_folder,
            initialization_options=init_opts,
            max_restarts=max_restarts,
            startup_timeout_ms=startup_timeout_ms,
        )

    manager = create_lsp_server_manager()
    manager.initialize(servers)

    # ---- Pre-start all registered LSP servers -------------------------------
    started_count = 0
    failed_count = 0
    for server_name, server_cfg in servers.items():
        try:
            inst = manager.get_all_servers().get(server_name)
            if inst is None:
                continue
            inst.start()
            started_count += 1
            logger.info("LSP server '%s' pre-started successfully", server_name)
        except Exception as exc:
            failed_count += 1
            logger.error(
                "LSP server '%s' failed to pre-start: %s. "
                "It will be retried on demand when a tool call targets its file type.",
                server_name,
                exc,
            )

    if started_count == 0 and failed_count > 0:
        logger.error(
            "All %d LSP server(s) failed to pre-start. "
            "Check that the configured commands are installed and on PATH.",
            failed_count,
        )

    wait_ms = _lsp_index_wait_ms_after_prestart()
    if started_count > 0 and wait_ms > 0:
        delay_s = wait_ms / 1000.0
        logger.info(
            "LSP index warm-up: sleeping %.2fs (%d ms) after %d server(s) pre-started "
            "(set SKILL_SDK_LSP_INDEX_WAIT_MS=0 to skip)",
            delay_s,
            wait_ms,
            started_count,
        )
        time.sleep(delay_s)

    _manager_instance = manager
    return _manager_instance


def reset_manager() -> None:
    """Reset the manager singleton (useful for tests / re-configuration)."""
    global _manager_instance
    _manager_instance = None


# ---------------------------------------------------------------------------
# File open helper
# ---------------------------------------------------------------------------


def _ensure_file_open(manager: LSPServerManager, abs_path: str) -> None:
    """Read and didOpen the file if not already open in the LSP server."""
    if manager.is_file_open(abs_path):
        return
    with open(abs_path, "rb") as f:
        raw = f.read()
    content = raw.decode("utf-8", errors="replace")
    manager.open_file(abs_path, content)


# ---------------------------------------------------------------------------
# Result counting helpers
# ---------------------------------------------------------------------------


def _compute_result_count(operation: Operation, result: Any) -> int:
    if result is None:
        return 0
    if operation == "hover":
        return 1
    if isinstance(result, list):
        if operation == "documentSymbol":
            if result and isinstance(result[0], dict) and "location" in result[0]:
                return len(result)
            return _count_symbols(result)
        return len(result)
    return 1


def _compute_file_count(operation: Operation, result: Any) -> int:
    if result is None:
        return 0
    if operation in ("hover",):
        return 1
    if not isinstance(result, list):
        return 1

    if operation in ("incomingCalls",):
        return _count_unique_incoming_files(result)
    if operation in ("outgoingCalls",):
        return _count_unique_outgoing_files(result)
    if operation in ("prepareCallHierarchy",):
        return _count_unique_call_item_files(result)

    # goToDefinition / findReferences / goToImplementation: count unique URIs
    return _count_unique_uris_from_result(result)


def _count_unique_uris_from_result(result: list[Any]) -> int:
    uris: set[str] = set()
    for item in result:
        if isinstance(item, dict):
            uri = item.get("uri") or item.get("targetUri")
            if isinstance(uri, str):
                uris.add(uri)
    return len(uris)


def _count_unique_call_item_files(items: list[dict[str, Any]]) -> int:
    return _count_unique_file_uris(items, "uri")


def _count_unique_incoming_files(calls: list[dict[str, Any]]) -> int:
    uris: set[str] = set()
    for call in calls:
        frm = call.get("from") if isinstance(call, dict) else None
        if isinstance(frm, dict):
            u = frm.get("uri")
            if isinstance(u, str):
                uris.add(u)
    return len(uris)


def _count_unique_outgoing_files(calls: list[dict[str, Any]]) -> int:
    uris: set[str] = set()
    for call in calls:
        to = call.get("to") if isinstance(call, dict) else None
        if isinstance(to, dict):
            u = to.get("uri")
            if isinstance(u, str):
                uris.add(u)
    return len(uris)
