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

# Shared char budget for documentSymbol: return full outline if it fits; otherwise
# filter/truncate down to this same ceiling. Override via SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS.
DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT = 10000

DESCRIPTION = f"""Interact with Language Server Protocol (LSP) servers to get code intelligence features.

Supported operations:
- goToDefinition: Find where a symbol is defined
- findReferences: Find all references to a symbol
- hover: Get hover information (documentation, type info) for a symbol
- documentSymbol: Get symbols (functions, classes, methods) in a document.
  By default omits noise kinds (Variable/Field/literals) that rarely help readline
  boundaries; set SKILL_SDK_DOC_SYMBOL_KEEP_NOISE=1 for the raw LSP tree.
  Returns the **full** (pruned) outline when it fits in SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS
  (default {DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT}) **and** no symbol_name/line focus
  is provided. If symbol_name and/or line are set, always return that focused
  subtree (fitted to the same budget). If the outline exceeds the budget with no
  focus, truncate to the budget.
- workspaceSymbol: Search for symbols across the entire workspace
- goToImplementation: Find implementations of an interface or abstract method
- prepareCallHierarchy: Get call hierarchy item at a position (functions/methods)
- incomingCalls: Find all functions/methods that call the function at a position
- outgoingCalls: Find all functions/methods called by the function at a position

Most operations require:
- filePath: The source file to operate on
- line: The line number (1-based). Required for goToDefinition, findReferences, hover,
      goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls.
      For documentSymbol: optional focus — keep symbols covering this line
      (applied even when the outline is under budget).

documentSymbol size policy (client-side):
- default prune: drop Variable/Field/literal kinds (SKILL_SDK_DOC_SYMBOL_KEEP_NOISE=1 to keep)
- budget = SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS (default {DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT})
- with symbol_name and/or line → always focus to that subtree (under or over budget)
- no focus and pruned outline ≤ budget → return full pruned outline
- no focus and pruned outline > budget → truncate; result fitted to the same budget

workspaceSymbol:
- symbol_name: search query (fuzzy name match across the LSP workspace)
- filePath: optional workspace root directory OR any source file (only used to pick
  the language server). Directory roots are accepted. May be omitted if WORKSPACE_FOLDER is set.

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
    *,
    query: str = "",
) -> tuple[str, Any]:
    """Map an LSPTool operation to a (LSP-method, params) pair.

    ``line`` / ``character`` are 1-based and converted to 0-based LSP protocol.
    ``query`` is used only by ``workspaceSymbol``.
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
            {"query": query},
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


_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    "vendor",
}


def _normalized_exts_from_manager(manager: Any) -> set[str]:
    exts: set[str] = set()
    for srv in manager.get_all_servers().values():
        mapping = getattr(getattr(srv, "config", None), "extension_to_language", None) or {}
        for ext in mapping:
            e = str(ext).lower()
            if not e.startswith("."):
                e = f".{e}"
            exts.add(e)
    return exts


def _find_source_file_under(root: Path, exts: set[str]) -> Path | None:
    """Return the first source file under ``root`` matching ``exts`` (shallow-first)."""
    if not root.is_dir() or not exts:
        return None
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if entry.is_file() and entry.suffix.lower() in exts:
                return entry
    except OSError:
        return None

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        )
        for name in sorted(filenames):
            candidate = Path(dirpath) / name
            if candidate.suffix.lower() in exts:
                return candidate
    return None


def _resolve_workspace_symbol_seed(manager: Any, file_path: str) -> Path | None:
    """Resolve a path whose extension selects an LSP server for workspace/symbol.

    ``file_path`` may be a source file, a workspace directory, or empty
    (falls back to ``WORKSPACE_FOLDER`` / server workspace folders).
    """
    exts = _normalized_exts_from_manager(manager)
    roots: list[Path] = []

    raw = (file_path or "").strip()
    if raw:
        path = Path(os.path.abspath(os.path.expanduser(raw)))
        if path.is_file():
            return path
        if path.is_dir():
            roots.append(path)
        else:
            return None
    else:
        env_ws = os.environ.get("WORKSPACE_FOLDER", "").strip()
        if env_ws:
            roots.append(Path(os.path.abspath(os.path.expanduser(env_ws))))
        for srv in manager.get_all_servers().values():
            wf = getattr(getattr(srv, "config", None), "workspace_folder", None)
            if wf:
                roots.append(Path(os.path.abspath(os.path.expanduser(str(wf)))))

    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        found = _find_source_file_under(root, exts)
        if found is not None:
            return found
        # Extension-only seed: ensure_server_started keys off suffix; file need not exist.
        if exts and root.exists():
            return root / f"__workspace_symbol_seed{sorted(exts)[0]}"

    if exts:
        return Path.cwd() / f"__workspace_symbol_seed{sorted(exts)[0]}"
    return None


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
    rng = symbol.get("range", {})
    start_ln = (rng.get("start") or {}).get("line", 0) + 1
    end_ln = (rng.get("end") or {}).get("line", 0) + 1
    # Compact read-code outline: name, short-enough kind, line span only.
    # Skip LSP ``detail`` (signatures / types) — rarely needed before readline.
    lines = [f"{prefix}{name} ({kind}) - Lines {start_ln}-{end_ln}"]
    for child in symbol.get("children", []):
        lines.extend(_format_document_symbol_node(child, indent + 1))
    return lines


# LSP SymbolKind values that usually contain members worth outlining.
_CONTAINER_SYMBOL_KINDS = frozenset(
    {
        2,  # Module
        3,  # Namespace
        4,  # Package
        5,  # Class
        10,  # Enum
        11,  # Interface
        19,  # Object
        23,  # Struct
    }
)

# Prefer these kinds when capping a long child list (methods/ctors before fields).
_OUTLINE_PRIORITY_KINDS = frozenset(
    {
        5,  # Class (nested)
        6,  # Method
        9,  # Constructor
        11,  # Interface
        12,  # Function
        23,  # Struct
        10,  # Enum
    }
)

# Dropped from the default documentSymbol outline for read-code (save context).
# These rarely define useful readline boundaries compared with class/method/function.
# Override with SKILL_SDK_DOC_SYMBOL_KEEP_NOISE=1 to keep the full LSP tree.
_DOC_SYMBOL_NOISE_KINDS = frozenset(
    {
        8,  # Field
        13,  # Variable
        15,  # String
        16,  # Number
        17,  # Boolean
        18,  # Array
        20,  # Key
        21,  # Null
    }
)


def _doc_symbol_keep_noise() -> bool:
    raw = os.environ.get("SKILL_SDK_DOC_SYMBOL_KEEP_NOISE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _symbol_kind_int(symbol: dict[str, Any]) -> int:
    try:
        return int(symbol.get("kind") or 0)
    except (TypeError, ValueError):
        return 0


def _prune_document_symbol_noise(
    symbols: list[Any],
    *,
    keep_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Drop Variable/Field/literal leaves that bloat outlines without helping navigation.

    If a dropped node has children, those children are promoted. Names in
    ``keep_names`` are retained even when their kind is normally noise (so a
    focused ``symbol_name`` that hits a Variable still works).
    """
    keep = {n for n in (keep_names or set()) if n}
    out: list[dict[str, Any]] = []
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        kids = _prune_document_symbol_noise(
            list(sym.get("children") or []), keep_names=keep
        )
        name = str(sym.get("name", ""))
        kind = _symbol_kind_int(sym)
        if kind in _DOC_SYMBOL_NOISE_KINDS and name not in keep:
            out.extend(kids)
            continue
        node = dict(sym)
        node["children"] = kids
        out.append(node)
    return out


# Soft cap so a huge class outline stays usable but does not refill context.
# Final size is governed by DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT / env override.
_MAX_OUTLINE_CHILDREN = 200


def _filtered_doc_symbol_max_chars() -> int:
    """Resolve the shared documentSymbol char budget (full-or-filter ceiling)."""
    raw = os.environ.get(
        "SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS",
        str(DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT),
    ).strip()
    try:
        return max(200, int(raw))
    except ValueError:
        return DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT


def _symbol_name_matches(name: str, query: str) -> bool:
    """Exact (case-insensitive) match, or trailing identifier of ``Type.Method`` / ``(*T).Method``."""
    q = (query or "").strip()
    if not q or not name:
        return False
    if name == q or name.lower() == q.lower():
        return True
    tail = name.rsplit(".", 1)[-1]
    return tail.lower() == q.lower()


def _symbol_covers_line(symbol: dict[str, Any], line_1based: int) -> bool:
    """True if DocumentSymbol ``range`` covers the 1-based line."""
    rng = symbol.get("range") or {}
    start = (rng.get("start") or {}).get("line")
    end = (rng.get("end") or {}).get("line")
    if start is None or end is None:
        return False
    # LSP lines are 0-based
    return int(start) + 1 <= line_1based <= int(end) + 1


def _is_container_kind(kind: Any) -> bool:
    try:
        return int(kind) in _CONTAINER_SYMBOL_KINDS
    except (TypeError, ValueError):
        return False


def _shallow_outline_children(
    children: list[Any], *, max_children: int = _MAX_OUTLINE_CHILDREN
) -> tuple[list[dict[str, Any]], int]:
    """Keep one level of members (no grandchildren). Prefer methods when capping.

    Returns ``(shallow_children, omitted_count)``.
    """
    valid = [c for c in children if isinstance(c, dict)]
    if not valid:
        return [], 0

    def _prio(sym: dict[str, Any]) -> tuple[int, int]:
        kind = sym.get("kind", 0)
        try:
            k = int(kind)
        except (TypeError, ValueError):
            k = 0
        # lower tuple sorts first: priority kinds before others, then by start line
        is_prio = 0 if k in _OUTLINE_PRIORITY_KINDS else 1
        start = ((sym.get("range") or {}).get("start") or {}).get("line", 0)
        try:
            return (is_prio, int(start))
        except (TypeError, ValueError):
            return (is_prio, 0)

    ordered = sorted(valid, key=_prio)
    omitted = max(0, len(ordered) - max_children)
    selected = ordered[:max_children]
    # Restore source order among the selected set for readable outlines
    selected_ids = {id(s) for s in selected}
    in_source_order = [c for c in valid if id(c) in selected_ids]

    shallow: list[dict[str, Any]] = []
    for child in in_source_order:
        node = {k: v for k, v in child.items() if k != "children"}
        node["children"] = []
        shallow.append(node)
    return shallow, omitted


def _filter_document_symbol_node_by_name(
    symbol: dict[str, Any], query: str
) -> dict[str, Any] | None:
    """Keep node if it or a descendant matches ``query``; prune non-matching siblings.

    - Method/function self-match: no children (boundary is enough for readline).
    - Class/interface/… self-match: keep **one level** of members (method outline).
    - Ancestor of a name match: only the matching descendant path.
    """
    matched_children: list[dict[str, Any]] = []
    for child in symbol.get("children") or []:
        if not isinstance(child, dict):
            continue
        filtered = _filter_document_symbol_node_by_name(child, query)
        if filtered is not None:
            matched_children.append(filtered)

    self_match = _symbol_name_matches(str(symbol.get("name", "")), query)
    if not self_match and not matched_children:
        return None

    out = {k: v for k, v in symbol.items() if k != "children"}
    if matched_children:
        # Name hit is below this node — keep only the matching path
        out["children"] = matched_children
    elif self_match and _is_container_kind(symbol.get("kind")):
        shallow, _omitted = _shallow_outline_children(list(symbol.get("children") or []))
        out["children"] = shallow
        if _omitted:
            out["_outline_omitted"] = _omitted
    else:
        # Leaf-like self-match (method/function/…): boundary only
        out["children"] = []
    return out


def _filter_document_symbols_by_name(
    symbols: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        filtered = _filter_document_symbol_node_by_name(sym, query)
        if filtered is not None:
            out.append(filtered)
    return out


def _deepest_symbol_covering_line(
    symbols: list[dict[str, Any]], line_1based: int
) -> list[dict[str, Any]]:
    """Return a pruned tree: ancestors + deepest symbol whose range covers ``line_1based``.

    When the deepest hit is a container (e.g. class declaration line), attach a
    one-level member outline so callers still see methods without a full dump.
    """

    def walk(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        for node in nodes:
            if not isinstance(node, dict) or not _symbol_covers_line(node, line_1based):
                continue
            child_hit = walk(list(node.get("children") or []))
            out = {k: v for k, v in node.items() if k != "children"}
            if child_hit is not None:
                out["children"] = [child_hit]
            elif _is_container_kind(node.get("kind")):
                shallow, omitted = _shallow_outline_children(
                    list(node.get("children") or [])
                )
                out["children"] = shallow
                if omitted:
                    out["_outline_omitted"] = omitted
            else:
                out["children"] = []
            return out
        return None

    hit = walk(symbols)
    return [hit] if hit is not None else []


def _filter_symbol_information(
    symbols: list[dict[str, Any]],
    *,
    symbol_name: str | None = None,
    line_1based: int | None = None,
) -> list[dict[str, Any]]:
    """Filter flat SymbolInformation[] by name and/or covering line."""
    out: list[dict[str, Any]] = []
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        if symbol_name and not _symbol_name_matches(str(sym.get("name", "")), symbol_name):
            continue
        if line_1based is not None:
            loc = sym.get("location") or {}
            rng = loc.get("range") or {}
            start = (rng.get("start") or {}).get("line")
            end = (rng.get("end") or {}).get("line")
            if start is None or end is None:
                continue
            if not (int(start) + 1 <= line_1based <= int(end) + 1):
                continue
        out.append(sym)
    return out


def _refine_name_matches_by_line(
    symbols: list[dict[str, Any]], line_1based: int
) -> list[dict[str, Any]]:
    """Among an already name-filtered tree, keep branches that cover ``line_1based``."""
    covering = _deepest_symbol_covering_line(symbols, line_1based)
    return covering if covering else symbols


def _collect_outline_omitted(symbols: list[Any]) -> int:
    total = 0
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        omitted = sym.pop("_outline_omitted", None)
        if isinstance(omitted, int):
            total += omitted
        total += _collect_outline_omitted(list(sym.get("children") or []))
    return total


def _estimate_document_symbol_chars(
    symbols: list[Any], *, filter_note: str = ""
) -> int:
    lines = [f"Document symbols{filter_note}:"]
    for sym in symbols:
        if isinstance(sym, dict):
            lines.extend(_format_document_symbol_node(sym))
    return len("\n".join(lines))


def _clone_symbol_node(symbol: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in symbol.items() if k != "children"}
    out["children"] = [
        _clone_symbol_node(c)
        for c in (symbol.get("children") or [])
        if isinstance(c, dict)
    ]
    return out


def _clone_symbol_forest(symbols: list[Any]) -> list[dict[str, Any]]:
    return [_clone_symbol_node(s) for s in symbols if isinstance(s, dict)]


def _find_symbol_node(
    nodes: list[Any], *, name: str | None = None, start_line_0: int | None = None
) -> dict[str, Any] | None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        rng = node.get("range") or {}
        start = (rng.get("start") or {}).get("line")
        name_ok = name is None or str(node.get("name", "")) == name
        line_ok = start_line_0 is None or start == start_line_0
        if name_ok and line_ok:
            return node
        hit = _find_symbol_node(
            list(node.get("children") or []), name=name, start_line_0=start_line_0
        )
        if hit is not None:
            return hit
    return None


def _enrich_filtered_with_full_outline(
    filtered: list[dict[str, Any]], full: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expand narrow hits (e.g. Class→one Method) back to a one-level member outline.

    Uses the full documentSymbol tree as the source of siblings/members so a
    method query still shows neighboring methods within the char budget.
    """

    def enrich(node: dict[str, Any]) -> None:
        children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
        for child in children:
            enrich(child)

        if not _is_container_kind(node.get("kind")):
            return

        start = ((node.get("range") or {}).get("start") or {}).get("line")
        full_node = _find_symbol_node(
            full, name=str(node.get("name", "")), start_line_0=start
        )
        if full_node is None:
            full_node = _find_symbol_node(full, name=str(node.get("name", "")))
        if full_node is None:
            return

        full_shallow, omitted = _shallow_outline_children(
            list(full_node.get("children") or [])
        )
        if not full_shallow:
            return

        # Preserve any deeper match paths already present (e.g. nested hits),
        # then fill remaining slots with sibling outline from the full tree.
        existing_by_name = {str(c.get("name")): c for c in children}
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for shallow in full_shallow:
            n = str(shallow.get("name", ""))
            if n in existing_by_name and existing_by_name[n].get("children"):
                merged.append(existing_by_name[n])
            else:
                merged.append(shallow)
            seen.add(n)
        for c in children:
            n = str(c.get("name", ""))
            if n not in seen:
                merged.append(c)
        node["children"] = merged
        if omitted:
            node["_outline_omitted"] = int(node.get("_outline_omitted") or 0) + omitted

    out = _clone_symbol_forest(filtered)
    for root in out:
        enrich(root)
    return out


def _child_removal_score(
    child: dict[str, Any], prefer_names: set[str]
) -> tuple[int, int, int]:
    """Higher score = remove sooner."""
    name = str(child.get("name", ""))
    if name in prefer_names:
        return (-1, 0, 0)  # never prefer removing these (handled by caller)
    try:
        kind = int(child.get("kind", 0))
    except (TypeError, ValueError):
        kind = 0
    # Remove non-outline kinds first, then later lines
    kind_score = 0 if kind not in _OUTLINE_PRIORITY_KINDS else 1
    start = ((child.get("range") or {}).get("start") or {}).get("line", 0)
    try:
        start_i = int(start)
    except (TypeError, ValueError):
        start_i = 0
    # Prefer removing far-away / low-priority members first:
    # sort key for max(): higher removed first → use inverted priority
    return (0 if kind not in _OUTLINE_PRIORITY_KINDS else -1, start_i, len(name))


def _trim_outline_to_char_budget(
    symbols: list[dict[str, Any]],
    *,
    max_chars: int,
    filter_note: str,
    prefer_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Drop outline members until formatted size fits ``max_chars``.

    Can remove nested members **and** top-level symbols. Returns
    ``(trimmed_symbols, removed_count)``.
    """
    prefer = prefer_names or set()
    out = _clone_symbol_forest(symbols)
    removed = 0

    def remove_one() -> bool:
        nonlocal removed
        # (score, parent_or_None, child) — parent None means top-level list
        candidates: list[
            tuple[tuple[int, int, int], dict[str, Any] | None, dict[str, Any]]
        ] = []

        def consider(parent: dict[str, Any] | None, child: dict[str, Any], siblings: list) -> None:
            name = str(child.get("name", ""))
            if name in prefer and len(siblings) > 1:
                return
            if name in prefer:
                return
            score = _child_removal_score(child, prefer)
            candidates.append((score, parent, child))

        def walk(nodes: list[dict[str, Any]], parent: dict[str, Any] | None) -> None:
            kids = [c for c in nodes if isinstance(c, dict)]
            for child in kids:
                nested = [c for c in (child.get("children") or []) if isinstance(c, dict)]
                has_keep_path = bool(nested) and any(
                    str(gc.get("name", "")) in prefer for gc in nested
                )
                if has_keep_path:
                    walk(nested, child)
                    continue
                consider(parent, child, kids)
                if nested:
                    walk(nested, child)

        walk(out, None)
        if not candidates:
            return False
        candidates.sort(key=lambda x: x[0], reverse=True)
        _score, parent, child = candidates[0]
        if parent is None:
            out[:] = [c for c in out if c is not child]
        else:
            parent["children"] = [
                c for c in (parent.get("children") or []) if c is not child
            ]
        removed += 1
        return True

    for _ in range(10000):
        if _estimate_document_symbol_chars(out, filter_note=filter_note) <= max_chars:
            break
        if not remove_one():
            break
    return out, removed


def _fit_filtered_document_symbols(
    filtered: list[dict[str, Any]],
    full: list[dict[str, Any]],
    *,
    filter_note: str,
    prefer_names: set[str] | None = None,
    max_chars: int | None = None,
    enrich: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Optionally enrich narrow filters, then fit formatted output to the char budget."""
    budget = max_chars if max_chars is not None else _filtered_doc_symbol_max_chars()
    working = (
        _enrich_filtered_with_full_outline(filtered, full)
        if enrich
        else _clone_symbol_forest(filtered)
    )
    fitted, removed = _trim_outline_to_char_budget(
        working,
        max_chars=max(200, budget - 80),  # reserve room for fit_note suffix
        filter_note=filter_note,
        prefer_names=prefer_names,
    )
    note = ""
    final_chars = _estimate_document_symbol_chars(fitted, filter_note=filter_note)
    if removed:
        note = f"; fitted to ≤{budget} chars ({final_chars} chars, {removed} members omitted)"
    else:
        note = f"; {final_chars} chars (budget ≤{budget})"
    return fitted, note


def filter_document_symbol_result(
    result: Any,
    *,
    symbol_name: str | None = None,
    line_1based: int | None = None,
    max_chars: int | None = None,
) -> tuple[Any, str]:
    """Return documentSymbol output under a shared char budget.

    Policy (``budget`` = ``max_chars`` or ``SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS``,
    default ``DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT``):

    1. Prune noise kinds (unless KEEP_NOISE).
    2. If ``symbol_name`` / ``line`` provided → always apply that focus (even when
       the pruned outline fits in ``budget``).
    3. Else if pruned outline ≤ ``budget`` → return full pruned outline.
    4. Else (over budget, no focus) → truncate; focused results are fitted to
       the same ``budget``.

    Goal: prefer focused symbol spans for reading; otherwise give the most
    complete outline that still fits.
    """
    budget = max_chars if max_chars is not None else _filtered_doc_symbol_max_chars()

    if not result or not isinstance(result, list):
        return result, ""

    if not result:
        return result, ""

    first = result[0]
    is_symbol_info = isinstance(first, dict) and "location" in first

    if is_symbol_info:
        full_text = _format_workspace_symbol(result, cwd=None)
        full_chars = len(full_text)
        name_q = (symbol_name or "").strip() or None
        has_focus = bool(name_q) or line_1based is not None
        if full_chars <= budget and not has_focus:
            return result, f" (full outline, {full_chars} chars ≤ {budget})"

        filtered = _filter_symbol_information(
            result, symbol_name=name_q, line_1based=line_1based
        )
        if name_q and line_1based is not None and not filtered:
            filtered = _filter_symbol_information(
                result, symbol_name=name_q, line_1based=None
            )
        if not filtered:
            if has_focus:
                return [], (
                    f" (focused: full={full_chars}, name={name_q!r}, "
                    f"line={line_1based}; no matches)"
                    if full_chars <= budget
                    else (
                        f" (filtered: full={full_chars} > {budget}, "
                        f"name={name_q!r}, line={line_1based}; no matches)"
                    )
                )
            # Still over budget with nothing matched — keep head of full list
            filtered = list(result)
        # Trim flat list by dropping trailing symbols until under budget
        kept = list(filtered)
        while kept and len(_format_workspace_symbol(kept, cwd=None)) > budget:
            kept.pop()
        if full_chars <= budget and has_focus:
            note = (
                f" (focused under budget: {full_chars} chars ≤ {budget}; "
                f"kept {len(_format_workspace_symbol(kept, cwd=None))} chars)"
            )
        else:
            note = (
                f" (over budget: full={full_chars} > {budget}; "
                f"filtered to {len(_format_workspace_symbol(kept, cwd=None))} chars)"
            )
        return kept, note

    # Hierarchical DocumentSymbol[]
    name_q = (symbol_name or "").strip() or None
    prefer_keep = {name_q} if name_q else set()
    pruned_note = ""
    working: list[dict[str, Any]] = result
    if not _doc_symbol_keep_noise():
        working = _prune_document_symbol_noise(
            _clone_symbol_forest(result), keep_names=prefer_keep
        )
        pruned_note = "; noise kinds omitted (Variable/Field/…)"

    full_chars = _estimate_document_symbol_chars(working, filter_note="")
    has_focus = bool(name_q) or line_1based is not None
    if full_chars <= budget and not has_focus:
        return working, f" (full outline, {full_chars} chars ≤ {budget}{pruned_note})"

    # Focused (any size) or over budget — filter / truncate on the pruned tree
    prefer = prefer_keep

    if full_chars <= budget and has_focus:
        parts: list[str] = [f"under budget {full_chars} ≤ {budget}"]
        if pruned_note:
            parts.append("noise omitted")
        if name_q:
            parts.append(f"name={name_q!r}")
        if line_1based is not None:
            parts.append(f"line={line_1based}")
        suffix = f" (focused: {', '.join(parts)})"
    else:
        parts = [f"full={full_chars} > {budget}"]
        if pruned_note:
            parts.append("noise omitted")
        if name_q:
            parts.append(f"name={name_q!r}")
        if line_1based is not None:
            parts.append(f"line={line_1based}")
        suffix = f" (filtered: {', '.join(parts)})"

    filtered: list[dict[str, Any]]
    if name_q and line_1based is not None:
        by_name = _filter_document_symbols_by_name(working, name_q)
        refined = _refine_name_matches_by_line(by_name, line_1based)
        if refined is not by_name and refined:
            filtered = refined
        elif by_name:
            if not _deepest_symbol_covering_line(by_name, line_1based):
                kind = "focused" if full_chars <= budget else "filtered"
                suffix = (
                    f" ({kind}: full={full_chars}, name={name_q!r}; "
                    f"no match covering line={line_1based}, showing name matches)"
                )
            filtered = by_name
        else:
            return [], suffix
        do_enrich = True
    elif name_q:
        filtered = _filter_document_symbols_by_name(working, name_q)
        if not filtered:
            return [], suffix
        do_enrich = True
    elif line_1based is not None:
        filtered = _deepest_symbol_covering_line(working, line_1based)
        if not filtered:
            return [], suffix
        do_enrich = True
    else:
        # No focus hint: truncate the pruned outline to the shared budget
        filtered = _clone_symbol_forest(working)
        do_enrich = False

    _collect_outline_omitted(filtered)
    fitted, fit_note = _fit_filtered_document_symbols(
        filtered,
        working,
        filter_note=suffix,
        prefer_names=prefer,
        max_chars=budget,
        enrich=do_enrich,
    )
    return fitted, suffix + fit_note


def _format_document_symbol(
    result: Any,
    cwd: str | None = None,
    *,
    filter_note: str = "",
) -> str:
    if not result or not isinstance(result, list) or len(result) == 0:
        if filter_note:
            return (
                f"No document symbols matching filter{filter_note}. "
                "Try a different symbol_name/line, or omit filters for the full outline."
            )
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
    lines = [f"Document symbols{filter_note}:"]
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
        default="",
        description=(
            "Absolute or relative path. Required source file for most operations. "
            "For workspaceSymbol: optional workspace root directory OR any source file "
            "(only used to select the language server); may be omitted if WORKSPACE_FOLDER is set."
        ),
    )
    line: int | None = Field(
        default=None,
        ge=1,
        description=(
            "The line number (1-based, as shown in editors). Required for goToDefinition, "
            "findReferences, hover, goToImplementation, prepareCallHierarchy, incomingCalls, "
            "outgoingCalls (defaults to 1 if omitted). "
            "For documentSymbol: optional focus — keep symbols covering this line "
            "(applied even when the outline fits the char budget). "
            "Ignored for workspaceSymbol."
        ),
    )
    character: int | None = Field(
        default=None,
        description="[Deprecated] The character offset (1-based). Prefer using symbol_name instead — "
        "the SDK will auto-compute the exact offset from the line content, which is more reliable.",
    )
    symbol_name: str | None = Field(
        default=None,
        description=(
            "For position-based operations: identifier on the given line (SDK computes character). "
            "For workspaceSymbol: the search query string passed to workspace/symbol. "
            "For documentSymbol: optional focus — prefer matching this symbol (plus useful "
            "outline); applied even when the outline fits the shared char budget."
        ),
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
            return self._format_error(
                f"Invalid operation: {operation_raw!r}. "
                f"Valid operations: {', '.join(ALL_OPERATIONS)}",
                error_code=3,
            )
        operation: Operation = operation_raw  # type: ignore[assignment]

        file_path = kwargs.get("file_path", "") or ""
        line_raw = kwargs.get("line")
        line: int | None = int(line_raw) if line_raw is not None else None
        symbol_name: str | None = kwargs.get("symbol_name")
        cwd = os.getcwd()

        # ---- workspaceSymbol: directory roots + symbol_name → query ------------
        if operation == "workspaceSymbol":
            manager = _get_or_create_manager()
            if manager is None:
                return self._format_error("LSP server manager not initialized", error_code=5)

            seed = _resolve_workspace_symbol_seed(manager, file_path)
            if seed is None:
                return self._format_error(
                    "workspaceSymbol could not select an LSP server. "
                    "Pass file_path as the workspace root directory or any source file, "
                    "or set WORKSPACE_FOLDER / SKILL_SDK_LSP_SERVERS workspaceFolder.",
                    error_code=1,
                )
            if file_path.strip():
                provided = Path(os.path.abspath(os.path.expanduser(file_path.strip())))
                if not provided.exists():
                    return self._format_error(f"File does not exist: {file_path}", error_code=1)

            query = (symbol_name or "").strip()
            seed_path = str(seed.resolve())
            server = manager.ensure_server_started(seed_path)
            if server is None:
                ext = Path(seed_path).suffix
                return self._format_error(f"No LSP server available for file type: {ext}", error_code=4)

            method, params = _build_params(
                operation, seed_path, 1, 1, query=query
            )
            try:
                result = server.send_request(method, params)
            except Exception as exc:
                err_str = str(exc)
                if "unhandled method" in err_str.lower():
                    return self._format_error(
                        f"LSP server does not support operation "
                        f"'workspaceSymbol': {err_str}",
                        error_code=7,
                    )
                return self._format_error(
                    f"Error performing workspaceSymbol: {err_str}", error_code=7
                )

            formatted = _FORMATTERS[operation](result, cwd)
            result_count = _compute_result_count(operation, result)
            file_count = _compute_file_count(operation, result)
            return json.dumps(
                {
                    "operation": operation,
                    "result": formatted,
                    "filePath": file_path or seed_path,
                    "query": query,
                    "resultCount": result_count,
                    "fileCount": file_count,
                },
                ensure_ascii=False,
            )

        # ---- resolve file (other operations) -----------------------------------
        if not file_path:
            return self._format_error("file_path is required", error_code=1)

        expanded = os.path.expanduser(file_path)
        abs_path = os.path.abspath(expanded)
        fp_path = Path(abs_path)

        if not fp_path.exists():
            return self._format_error(f"File does not exist: {file_path}", error_code=1)
        if not fp_path.is_file():
            return self._format_error(f"Path is not a file: {file_path}", error_code=2)

        # documentSymbol does not use cursor position; symbol_name/line are client-side filters.
        # Skip character resolution so symbol_name can filter without a precise line hit.
        character = 1
        if operation != "documentSymbol":
            if line is None:
                line = 1
            # ---- auto-compute character from symbol_name -----------------------
            if symbol_name:
                try:
                    with open(str(fp_path), "r", encoding="utf-8") as f:
                        file_lines = f.readlines()
                    if line - 1 >= len(file_lines):
                        return self._format_error(
                            f"line {line} exceeds file length ({len(file_lines)} lines)",
                            error_code=8,
                        )
                    line_content = file_lines[line - 1]
                    idx = line_content.find(symbol_name)
                    if idx == -1:
                        return self._format_error(
                            f"symbol '{symbol_name}' not found on line {line}", error_code=8
                        )
                    character = idx + 1  # 1-based
                except Exception as exc:
                    return self._format_error(
                        f"Failed to auto-compute character from symbol_name: {exc}", error_code=8
                    )
            else:
                raw_char = kwargs.get("character")
                character = int(raw_char) if raw_char is not None else 1
        else:
            # documentSymbol request itself ignores position; keep a dummy for _build_params
            if line is None:
                line = 1

        # ---- size check --------------------------------------------------------
        file_size = fp_path.stat().st_size
        if file_size > MAX_LSP_FILE_SIZE_BYTES:
            return self._format_error(
                f"File too large for LSP analysis "
                f"({(file_size + 999_999) // 1_000_000}MB exceeds 10MB limit)",
            )

        cwd = os.getcwd()

        # ---- import LSP stack (lazy to avoid early init) -----------------------
        try:
            from skill_sdk.tool.lsp import LSPServerManager, create_lsp_server_manager
        except ImportError as exc:
            return self._format_error(f"LSP stack not available: {exc}", error_code=5)

        # ---- acquire (or create) manager ---------------------------------------
        manager = _get_or_create_manager()
        if manager is None:
            return self._format_error("LSP server manager not initialized", error_code=5)

        # ---- ensure file is open in LSP ----------------------------------------
        try:
            _ensure_file_open(manager, str(fp_path.resolve()))
        except Exception as exc:
            logger.exception("Failed to open file in LSP server")
            return self._format_error(f"Failed to open file in LSP server: {exc}", error_code=6)

        # ---- build method + params ---------------------------------------------
        # For documentSymbol, line/character are unused by the LSP request.
        method, params = _build_params(operation, str(fp_path.resolve()), line or 1, character)

        # ---- send request ------------------------------------------------------
        server = manager.ensure_server_started(str(fp_path.resolve()))
        if server is None:
            ext = fp_path.suffix
            return self._format_error(f"No LSP server available for file type: {ext}", error_code=4)

        try:
            result = server.send_request(method, params)
        except Exception as exc:
            err_str = str(exc)
            # Treat "identifier not found" / "no result" from LSP as empty result
            if any(phrase in err_str.lower() for phrase in ["identifier not found", "no identifier found", "no definition found", "no result"]):
                result = None
            elif "unhandled method" in err_str.lower():
                return self._format_error(
                    f"LSP server does not support operation '{operation}': {err_str}",
                    error_code=7,
                )
            else:
                return self._format_error(
                    f"Error performing {operation}: {err_str}", error_code=7
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

        # ---- documentSymbol client-side filter (shrink context for large files)
        filter_note = ""
        if operation == "documentSymbol":
            # Re-read raw filters: line may have been defaulted to 1 for _build_params
            filter_line = int(line_raw) if line_raw is not None else None
            filter_name = (symbol_name or "").strip() or None
            result, filter_note = filter_document_symbol_result(
                result, symbol_name=filter_name, line_1based=filter_line
            )

        # ---- format result -----------------------------------------------------
        formatter = _FORMATTERS[operation]
        if operation == "documentSymbol":
            formatted = formatter(result, cwd, filter_note=filter_note)
        else:
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
