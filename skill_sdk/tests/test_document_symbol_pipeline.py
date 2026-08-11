#!/usr/bin/env python3
"""Accuracy tests: prune → budget → focus (always) / truncate when over budget.

Pipeline under test (``filter_document_symbol_result``):
  1. Prune Variable/Field/literal noise (unless KEEP_NOISE)
  2. If symbol_name/line provided → always focus (even under budget)
  3. Else if pruned outline ≤ budget → return full pruned tree
  4. Else → truncate to budget

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=. python -m pytest tests/test_document_symbol_pipeline.py -v
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

from skill_sdk.tool.lsp_plugin import (  # noqa: E402
    DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT,
    _format_document_symbol,
    _prune_document_symbol_noise,
    filter_document_symbol_result,
)


def _sym(name: str, kind: int, start: int, end: int, children: list | None = None) -> dict:
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


def _lines(text: str, name: str) -> tuple[int, int] | None:
    m = re.search(rf"{re.escape(name)}\s*\([^)]+\)\s*- Lines\s+(\d+)-(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _names(symbols: list) -> set[str]:
    out: set[str] = set()

    def walk(nodes: list) -> None:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            out.add(str(n.get("name", "")))
            walk(list(n.get("children") or []))

    walk(symbols)
    return out


def _noisy_small() -> list[dict]:
    """Prunes to a small outline well under default budget."""
    return [
        _sym("logger", 13, 0, 0),
        _sym(
            "Handler",
            5,
            5,
            40,
            children=[
                _sym("__init__", 6, 10, 18, children=[_sym("host", 13, 11, 11)]),
                _sym("ProcessRequest", 6, 20, 30),
                _sym("count", 8, 32, 32),
            ],
        ),
        _sym("StandaloneFn", 12, 50, 60),
    ]


def _big_methods(n: int = 400) -> list[dict]:
    kids = [_sym(f"m{i}", 6, 10 + i, 10 + i) for i in range(n)]
    return [_sym("Big", 5, 0, n + 20, children=kids)]


def _noisy_big(n_methods: int = 350) -> list[dict]:
    """Raw tree huge due to Variables; after prune still over a modest budget."""
    kids = []
    for i in range(n_methods):
        kids.append(
            _sym(
                f"m{i}",
                6,
                10 + i,
                10 + i,
                children=[_sym(f"tmp{i}", 13, 10 + i, 10 + i)],
            )
        )
    return [_sym("logger", 13, 0, 0), _sym("Big", 5, 1, n_methods + 20, children=kids)]


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SKILL_SDK_DOC_SYMBOL_KEEP_NOISE", raising=False)
    monkeypatch.delenv("SKILL_SDK_DOC_SYMBOL_FILTER_MAX_CHARS", raising=False)


# ---------------------------------------------------------------------------
# Stage 1: prune
# ---------------------------------------------------------------------------


class TestStage1Prune:
    def test_prune_drops_noise_keeps_useful(self):
        pruned = _prune_document_symbol_noise(_noisy_small())
        names = _names(pruned)
        assert "Handler" in names and "ProcessRequest" in names and "StandaloneFn" in names
        assert "logger" not in names and "host" not in names and "count" not in names

    def test_filter_applies_prune_before_budget_note(self):
        _, note = filter_document_symbol_result(
            _noisy_small(), max_chars=DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT
        )
        assert "full outline" in note
        assert "noise kinds omitted" in note


# ---------------------------------------------------------------------------
# Stage 2: under budget — full when unfocused; focus narrows when hints set
# ---------------------------------------------------------------------------


class TestStage2UnderBudgetFullPruned:
    def test_under_budget_with_symbol_name_narrows(self):
        filtered, note = filter_document_symbol_result(
            _noisy_small(),
            symbol_name="ProcessRequest",
            max_chars=DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT,
        )
        assert "focused" in note
        assert "full outline" not in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert "ProcessRequest" in text
        assert "StandaloneFn" not in text
        assert "logger" not in text
        assert _lines(text, "ProcessRequest") == (21, 31)

    def test_under_budget_with_line_narrows(self):
        filtered, note = filter_document_symbol_result(
            _noisy_small(),
            line_1based=21,  # inside ProcessRequest
            max_chars=DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT,
        )
        assert "focused" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert "ProcessRequest" in text
        assert "StandaloneFn" not in text

    def test_under_budget_no_focus_returns_full_pruned(self):
        filtered, note = filter_document_symbol_result(
            _noisy_small(),
            max_chars=DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT,
        )
        assert "full outline" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert "ProcessRequest" in text and "StandaloneFn" in text
        assert "logger" not in text

    def test_prune_can_bring_tree_under_budget(self):
        """Without prune, KEEP_NOISE tree may exceed a tight budget; with prune it fits."""
        tree = _noisy_big(80)
        raw_len = len(_format_document_symbol(tree))
        pruned_len = len(_format_document_symbol(_prune_document_symbol_noise(tree)))
        assert pruned_len < raw_len

        # Choose budget between pruned and raw so prune decides the path
        budget = (pruned_len + raw_len) // 2
        assert pruned_len <= budget < raw_len

        filtered, note = filter_document_symbol_result(tree, max_chars=budget)
        assert "full outline" in note
        assert "noise kinds omitted" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert "m0" in text and "tmp0" not in text and "logger" not in text

# ---------------------------------------------------------------------------
# Stage 3a: over budget, no focus → truncate
# ---------------------------------------------------------------------------


class TestStage3OverBudgetTruncate:
    def test_truncate_note_and_size(self):
        filtered, note = filter_document_symbol_result(
            _big_methods(400), max_chars=2000
        )
        assert "filtered" in note or "fitted" in note
        assert "full=" in note and "> 2000" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 2000 + 120
        assert "Big" in text
        assert len(filtered[0]["children"]) < 400

    def test_noisy_big_truncates_after_prune_not_raw(self):
        filtered, note = filter_document_symbol_result(
            _noisy_big(350), max_chars=2000
        )
        assert "filtered" in note or "fitted" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 2000 + 120
        assert "logger" not in text
        assert "tmp0" not in text  # nested Variables pruned before truncate


# ---------------------------------------------------------------------------
# Stage 3b: over budget + name / line focus
# ---------------------------------------------------------------------------


class TestStage3OverBudgetFocus:
    def test_name_focus_keeps_symbol_and_lines(self):
        filtered, note = filter_document_symbol_result(
            _noisy_big(350), symbol_name="m300", max_chars=2000
        )
        assert "name='m300'" in note
        assert "full=" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 2000 + 120
        assert "m300" in text
        assert _lines(text, "m300") == (311, 311)
        assert "tmp300" not in text

    def test_line_focus_keeps_covering_method(self):
        # m20 → 0-based start 30 → 1-based 31
        filtered, note = filter_document_symbol_result(
            _noisy_big(350), line_1based=31, max_chars=2000
        )
        assert "line=31" in note
        text = _format_document_symbol(filtered, filter_note=note)
        assert len(text) <= 2000 + 120
        assert "m20" in text
        assert _lines(text, "m20") == (31, 31)

    def test_name_and_line_miss_falls_back_to_name(self):
        filtered, note = filter_document_symbol_result(
            _big_methods(80),
            symbol_name="m10",
            line_1based=99999,
            max_chars=400,
        )
        text = _format_document_symbol(filtered, filter_note=note)
        assert "m10" in text
        assert "showing name matches" in note or "m10" in text

    def test_unknown_name_over_budget_empty(self):
        filtered, note = filter_document_symbol_result(
            _big_methods(80), symbol_name="DoesNotExist", max_chars=400
        )
        assert filtered == []
        assert "name=" in note or "filtered" in note

    def test_symbol_name_keeps_noise_variable_when_focused(self):
        """Focused Variable survives prune via keep_names on over-budget path."""
        filtered, note = filter_document_symbol_result(
            _noisy_small(),
            symbol_name="logger",
            max_chars=80,  # force over-budget after prune+keep
        )
        # Either under budget with logger kept in full pruned, or filtered with logger
        text = _format_document_symbol(filtered, filter_note=note)
        assert "logger" in text


# ---------------------------------------------------------------------------
# KEEP_NOISE / env interaction with budget gate
# ---------------------------------------------------------------------------


class TestKeepNoiseVsPruneBudgetGate:
    def test_keep_noise_can_force_filter_when_prune_would_fit(self, monkeypatch):
        tree = _noisy_big(80)
        pruned_len = len(_format_document_symbol(_prune_document_symbol_noise(tree)))
        raw_len = len(_format_document_symbol(tree))
        budget = (pruned_len + raw_len) // 2
        assert pruned_len <= budget < raw_len

        # Default prune → under budget → full
        _, note_pruned = filter_document_symbol_result(tree, max_chars=budget)
        assert "full outline" in note_pruned

        # KEEP_NOISE → still over budget → filter/truncate
        monkeypatch.setenv("SKILL_SDK_DOC_SYMBOL_KEEP_NOISE", "1")
        filtered, note_keep = filter_document_symbol_result(tree, max_chars=budget)
        assert "full outline" not in note_keep
        assert "filtered" in note_keep or "fitted" in note_keep or "over budget" in note_keep
        text = _format_document_symbol(filtered, filter_note=note_keep)
        assert len(text) <= budget + 120


# ---------------------------------------------------------------------------
# End-to-end accuracy matrix (20 micro-assertions in parametrize style)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,tree,kwargs,expect",
    [
        (
            "small_full",
            "_noisy_small",
            {"max_chars": 10000},
            {"note_has": "full outline", "has": ["Handler"], "missing": ["logger"]},
        ),
        (
            "small_name_focused",
            "_noisy_small",
            {"symbol_name": "ProcessRequest", "max_chars": 10000},
            {
                "note_has": "focused",
                "has": ["ProcessRequest"],
                "missing": ["StandaloneFn", "host"],
            },
        ),
        (
            "big_truncate",
            "_big_400",
            {"max_chars": 1500},
            {"note_has": "filtered", "has": ["Big"], "max_len": 1620},
        ),
        (
            "big_name",
            "_big_400",
            {"symbol_name": "m350", "max_chars": 1500},
            {"note_has": "m350", "has": ["m350"], "max_len": 1620},
        ),
        (
            "big_line",
            "_big_400",
            {"line_1based": 31, "max_chars": 1500},
            {"note_has": "line=31", "has": ["m20"], "max_len": 1620},
        ),
    ],
)
def test_pipeline_matrix(title, tree, kwargs, expect):
    trees = {
        "_noisy_small": _noisy_small(),
        "_big_400": _big_methods(400),
    }
    filtered, note = filter_document_symbol_result(trees[tree], **kwargs)
    assert expect["note_has"] in note, f"{title}: note={note}"
    text = _format_document_symbol(filtered, filter_note=note)
    for h in expect.get("has", []):
        assert h in text, f"{title}: missing {h}"
    for m in expect.get("missing", []):
        assert m not in text, f"{title}: unexpected {m}"
    if "max_len" in expect:
        assert len(text) <= expect["max_len"], f"{title}: len={len(text)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
