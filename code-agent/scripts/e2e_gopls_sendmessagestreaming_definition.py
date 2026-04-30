#!/usr/bin/env python3
"""E2E: start gopls via code-agent ``agent/tools/lsp.py``, resolve SendMessageStreaming definition."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

CODE_AGENT_ROOT = Path(__file__).resolve().parents[1]
_LSP_PATH = CODE_AGENT_ROOT / "agent" / "tools" / "lsp.py"

_spec = importlib.util.spec_from_file_location("code_agent_lsp_e2e", _LSP_PATH)
if _spec is None or _spec.loader is None:
    sys.exit(f"Cannot load {_LSP_PATH}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

ScopedLspServerConfig = _mod.ScopedLspServerConfig
create_lsp_server_manager = _mod.create_lsp_server_manager

# Repository paths (adjust if layout changes)
def _file_uri_to_path(uri: str) -> str:
    """Best-effort ``file://`` URI → local path (POSIX)."""
    from urllib.parse import unquote

    uri = uri.replace("file://", "", 1)
    return unquote(uri)


def _find_symbol_containing_line(
    symbols: list[dict[str, Any]],
    target_line: int,
) -> dict[str, Any] | None:
    """Recursively find the deepest DocumentSymbol whose range contains *target_line*."""
    best: dict[str, Any] | None = None
    for sym in symbols:
        rng = sym.get("range") or {}
        sr = (rng.get("start") or {}).get("line")
        er = (rng.get("end") or {}).get("line")
        if sr is not None and er is not None and sr <= target_line <= er:
            best = sym  # keep outermost match
            # Recurse: a child is narrower → better
            children = sym.get("children")
            if children:
                deeper = _find_symbol_containing_line(children, target_line)
                if deeper:
                    best = deeper
    return best


CLIENT_GO = Path(
    "/Users/james/daocloud/code/dac/dac-apiserver/internal/infrastructure/a2a/client.go",
).resolve()
WORKSPACE = CLIENT_GO.parents[3]  # .../dac-apiserver


def main() -> int:
    gopls = shutil.which("gopls")
    if not gopls:
        print("ERROR: gopls not on PATH")
        return 1
    if not CLIENT_GO.is_file():
        print(f"ERROR: missing {CLIENT_GO}")
        return 1
    go_mod = WORKSPACE / "go.mod"
    if not go_mod.is_file():
        print(f"ERROR: expected go.mod at {go_mod}")
        return 1

    text = CLIENT_GO.read_text(encoding="utf-8")
    line_idx: int | None = None
    char_idx: int | None = None
    for i, line in enumerate(text.splitlines()):
        if "func " in line and "SendMessageStreaming" in line:
            line_idx = i
            char_idx = line.index("SendMessageStreaming")
            break
    if line_idx is None or char_idx is None:
        print("ERROR: could not locate SendMessageStreaming method line")
        return 1

    mgr = create_lsp_server_manager()
    mgr.initialize(
        {
            "gopls": ScopedLspServerConfig(
                command=gopls,
                args=["serve"],
                workspace_folder=str(WORKSPACE),
                extension_to_language={".go": "go"},
                startup_timeout_ms=120_000,
            ),
        },
    )

    uri = CLIENT_GO.as_uri()
    params_def = {
        "textDocument": {"uri": uri},
        "position": {"line": line_idx, "character": char_idx},
    }

    try:
        mgr.open_file(str(CLIENT_GO), text)
        print(
            "=== E2E gopls + code-agent/agent/tools/lsp.py ===",
            f"\nworkspace: {WORKSPACE}",
            f"\nfile: {CLIENT_GO}",
            f"\ncursor (0-based): line={line_idx}, character={char_idx}",
            "\nSnippet: ",
            repr(text.splitlines()[line_idx][:120]),
            sep="",
        )

        definition = mgr.send_request(str(CLIENT_GO), "textDocument/definition", params_def)
        print("\n--- textDocument/definition ---")
        print(json.dumps(definition, indent=2, ensure_ascii=False))

        refs = mgr.send_request(
            str(CLIENT_GO),
            "textDocument/references",
            {
                **params_def,
                "context": {"includeDeclaration": True},
            },
        )
        print("\n--- textDocument/references (count) ---")
        print(len(refs) if isinstance(refs, list) else refs)

        # --- Get the definition's code block range via documentSymbol ---
        # The definition result may be in the same file or a different file.
        # Extract the URI and open the target file.
        def_uri: str | None = None
        def_line: int | None = None
        def_char: int | None = None

        if isinstance(definition, list) and len(definition) > 0:
            loc = definition[0]
        elif isinstance(definition, dict):
            loc = definition
        else:
            loc = None

        if loc:
            def_uri = loc.get("uri") or (
                loc.get("targetUri") if "targetUri" in loc else None
            )
            rng = loc.get("range") or loc.get("targetRange") or {}
            start = rng.get("start") or {}
            def_line = start.get("line")
            def_char = start.get("character")

        if def_uri and def_line is not None:
            def_path_str = _file_uri_to_path(def_uri)
            # Open the definition file if it's different from CLIENT_GO
            def_path = Path(def_path_str)
            if def_path_str != str(CLIENT_GO):
                def_text = def_path.read_text(encoding="utf-8")
                mgr.open_file(def_path_str, def_text)
                def_uri = def_path.as_uri()

            # Ask for document symbols in the definition file
            symbols = mgr.send_request(def_path_str, "textDocument/documentSymbol", {
                "textDocument": {"uri": def_uri},
            })

            print("\n--- documentSymbol → symbol containing the definition ---")
            if isinstance(symbols, list):
                found = _find_symbol_containing_line(symbols, def_line)
                if found:
                    print(f"Symbol: {found['name']} (kind={found['kind']})")
                    print(f"Full range (0-based):")
                    sr = found["range"]["start"]
                    er = found["range"]["end"]
                    print(f"  start: line={sr['line']}, character={sr['character']}")
                    print(f"  end:   line={er['line']}, character={er['character']}")
                    print(f"  → code block lines (1-based, inclusive): [{sr['line']+1}, {er['line']+1}]")
                    print(f"  → total lines: {er['line'] - sr['line'] + 1}")
                else:
                    print("(no symbol matched the definition line)")
            else:
                print(f"(unexpected result type: {type(symbols).__name__})")
        else:
            print("\n--- documentSymbol: skipped (no definition URI found) ---")

        print("\nOK: end-to-end finished.")
        return 0
    finally:
        mgr.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
