#!/usr/bin/env python3
"""Unit tests for documentSymbol size-budget policy (no LSP required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

from skill_sdk.tool.lsp_plugin import (  # noqa: E402
    _format_document_symbol,
    _symbol_name_matches,
    filter_document_symbol_result,
)


def _sym(
    name: str,
    kind: int,
    start: int,
    end: int,
    children: list | None = None,
) -> dict:
    """Build a minimal DocumentSymbol (0-based LSP lines)."""
    return {
        "name": name,
        "kind": kind,
        "range": {
            "start": {"line": start, "character": 0},
            "end": {"line": end, "character": 0},
        },
        "selectionRange": {
            "start": {"line": start, "character": 0},
            "end": {"line": start, "character": len(name)},
        },
        "children": children or [],
    }


# Class=5, Method=6, Function=12
SAMPLE_TREE = [
    _sym(
        "Handler",
        5,
        5,
        30,
        children=[
            _sym("NewHandler", 6, 10, 13),
            _sym("ProcessRequest", 6, 15, 25),
            _sym("HealthCheck", 6, 27, 30),
            _sym(
                "Nested",
                5,
                31,
                40,
                children=[_sym("InnerMethod", 6, 32, 39)],
            ),
        ],
    ),
    _sym("StandaloneFn", 12, 50, 60),
]


def _big_tree(n: int = 80) -> list[dict]:
    kids = [_sym(f"m{i}", 6, 10 + i, 10 + i) for i in range(n)]
    return [_sym("Big", 5, 0, 200, children=kids)]


class TestSymbolNameMatches:
    def test_exact(self):
        assert _symbol_name_matches("ProcessRequest", "ProcessRequest")

    def test_case_insensitive(self):
        assert _symbol_name_matches("ProcessRequest", "processrequest")

    def test_go_qualified(self):
        assert _symbol_name_matches("(*Handler).ProcessRequest", "ProcessRequest")
        assert _symbol_name_matches("Handler.ProcessRequest", "ProcessRequest")

    def test_no_substring(self):
        assert not _symbol_name_matches("ProcessRequest", "Process")
        assert not _symbol_name_matches("Process", "ProcessRequest")


class TestUnderBudgetReturnsFull:
    def test_small_tree_with_symbol_name_narrows(self):
        filtered, note = filter_document_symbol_result(
            SAMPLE_TREE, symbol_name="ProcessRequest", max_chars=1000
        )
        assert "focused" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert "ProcessRequest" in text
        # Top-level siblings outside the hit path should be gone
        assert "StandaloneFn" not in text
        # Enrich may keep one-level method siblings under Handler — that's OK
        assert "Handler" in text

    def test_small_tree_no_filters_returns_full(self):
        filtered, note = filter_document_symbol_result(SAMPLE_TREE, max_chars=1000)
        assert "full outline" in note
        assert "StandaloneFn" in _format_document_symbol(filtered, filter_note=note)


class TestOverBudgetFilters:
    def test_large_tree_without_hint_is_truncated(self):
        tree = _big_tree(80)
        filtered, note = filter_document_symbol_result(tree, max_chars=1000)
        assert "full=" in note or "over budget" in note or "filtered" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 1100
        assert filtered[0]["name"] == "Big"
        assert len(filtered[0]["children"]) < 80

    def test_large_tree_with_name_keeps_focus(self):
        tree = _big_tree(80)
        # Prefer a late method so we can see prefer_names keep it
        filtered, note = filter_document_symbol_result(
            tree, symbol_name="m50", max_chars=1000
        )
        assert "filtered" in note or "fitted" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 1100
        assert "m50" in text

    def test_large_tree_with_line_keeps_covering(self):
        tree = _big_tree(80)
        # m10 spans LSP line 20 → 1-based 21
        filtered, note = filter_document_symbol_result(
            tree, line_1based=21, max_chars=1000
        )
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 1100
        assert "m10" in text

    def test_filter_and_full_share_same_budget(self):
        tree = _big_tree(80)
        full_chars = len(_format_document_symbol(tree))
        assert full_chars > 1000
        filtered, note = filter_document_symbol_result(
            tree, symbol_name="Big", max_chars=1000
        )
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 1100
        assert "1000" in note


class TestForcedFilterOnSmallTree:
    """Force filter path on SAMPLE_TREE with a tiny budget."""

    def test_method_match_expands_siblings_under_tiny_budget(self):
        filtered, note = filter_document_symbol_result(
            SAMPLE_TREE, symbol_name="ProcessRequest", max_chars=200
        )
        assert "filtered" in note or "fitted" in note
        assert filtered[0]["name"] == "Handler"
        names = [k["name"] for k in filtered[0]["children"]]
        assert "ProcessRequest" in names
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 280

    def test_no_match_over_budget(self):
        filtered, note = filter_document_symbol_result(
            SAMPLE_TREE, symbol_name="DoesNotExist", max_chars=50
        )
        # Small tree may still be "full" if under 50? SAMPLE is larger than 50
        # so filter runs and finds nothing
        full_chars = len(_format_document_symbol(SAMPLE_TREE))
        if full_chars > 50:
            assert filtered == [] or "full outline" not in note


class TestFilterSymbolInformation:
    def test_flat_under_budget_returns_full(self):
        flat = [
            {
                "name": "Foo",
                "kind": 12,
                "location": {
                    "uri": "file:///a.go",
                    "range": {
                        "start": {"line": 10, "character": 0},
                        "end": {"line": 10, "character": 3},
                    },
                },
            },
            {
                "name": "Bar",
                "kind": 12,
                "location": {
                    "uri": "file:///a.go",
                    "range": {
                        "start": {"line": 20, "character": 0},
                        "end": {"line": 20, "character": 3},
                    },
                },
            },
        ]
        filtered, note = filter_document_symbol_result(
            flat, symbol_name="Bar", max_chars=1000
        )
        assert "focused" in note
        assert len(filtered) == 1
        assert filtered[0]["name"] == "Bar"


class TestUnfilteredPassthrough:
    def test_no_filters_small_tree(self):
        filtered, note = filter_document_symbol_result(SAMPLE_TREE, max_chars=1000)
        assert filtered is SAMPLE_TREE or len(filtered) == 2
        assert "full outline" in note


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
