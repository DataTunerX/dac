"""Gate, sort, and select complete code snippets after LLM batch scoring."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TRIGGER_CHARS = 20000
_DEFAULT_MAX_SNIPPETS = 10


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off", "disabled")


def snippet_content_chars(snippet: Dict[str, Any]) -> int:
    return len(snippet.get("code_content") or "")


def total_snippet_chars(snippets: List[Dict[str, Any]]) -> int:
    return sum(snippet_content_chars(s) for s in snippets)


def score_trigger_chars() -> int:
    return _env_int("CODE_SEARCH_SCORE_TRIGGER_CHARS", _DEFAULT_TRIGGER_CHARS)


def llm_score_enabled() -> bool:
    return _env_bool("SNIPPET_LLM_SCORE_ENABLED", True)


def should_score_and_select(snippets: List[Dict[str, Any]]) -> bool:
    """True when LLM scoring/selection should run (total chars exceed trigger)."""
    if not snippets or not llm_score_enabled():
        return False
    total = total_snippet_chars(snippets)
    trigger = score_trigger_chars()
    return total > trigger


def select_snippets_by_score(
    snippets: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Sort by relevance_score desc; greedily pick top blocks until char budget.

    Output char budget uses ``CODE_SEARCH_SCORE_TRIGGER_CHARS`` (same as gate trigger).
    No minimum score cutoff — low-score blocks are dropped only when higher-score
    blocks already fill the budget.
    """
    if not snippets:
        return [], {"input_count": 0, "selected_count": 0, "output_chars": 0}

    max_output_chars = score_trigger_chars()
    max_snippets = _env_int("CODE_SEARCH_MAX_SNIPPETS", _DEFAULT_MAX_SNIPPETS)

    indexed = list(enumerate(snippets))

    def sort_key(item: Tuple[int, Dict[str, Any]]) -> Tuple[float, int, int]:
        idx, snippet = item
        score = float(snippet.get("relevance_score") or 0.0)
        chars = snippet_content_chars(snippet)
        return (-score, chars, idx)

    indexed.sort(key=sort_key)

    selected: List[Dict[str, Any]] = []
    output_chars = 0
    dropped_limit = 0

    for _idx, snippet in indexed:
        block_chars = snippet_content_chars(snippet)
        if len(selected) >= max_snippets:
            dropped_limit += 1
            continue
        if selected and output_chars + block_chars > max_output_chars:
            dropped_limit += 1
            continue
        if not selected and block_chars > max_output_chars:
            # Single block exceeds budget: keep whole block (no truncate).
            selected.append(snippet)
            output_chars += block_chars
            continue

        selected.append(snippet)
        output_chars += block_chars

    report = {
        "input_count": len(snippets),
        "selected_count": len(selected),
        "output_chars": output_chars,
        "max_output_chars": max_output_chars,
        "max_snippets": max_snippets,
        "dropped_limit": dropped_limit,
    }
    return selected, report


def log_selection_report(
    log: logging.Logger,
    *,
    report: Dict[str, Any],
    skipped: bool = False,
    total_chars: int = 0,
    trigger_chars: int = 0,
) -> None:
    if skipped:
        log.info(
            "[CODE SEARCH GATE] total_chars=%d <= trigger=%d → skip score/select, "
            "return dedup result as-is",
            total_chars,
            trigger_chars,
        )
        return

    log.info(
        "[CODE SEARCH SELECT] dedup后 %d 块 → 按分选取保留 %d 块, output_chars=%d "
        "(dropped_limit=%d char_budget=%d max_snippets=%d)",
        report.get("input_count", 0),
        report.get("selected_count", 0),
        report.get("output_chars", 0),
        report.get("dropped_limit", 0),
        report.get("max_output_chars", 0),
        report.get("max_snippets", 0),
    )
