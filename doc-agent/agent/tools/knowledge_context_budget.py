"""Gate, sort, and select complete knowledge blocks after LLM batch scoring."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TRIGGER_CHARS = 30000
_DEFAULT_MAX_BLOCKS = 20


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


def block_content_chars(block: Dict[str, Any]) -> int:
    return len(block.get("text") or "")


def total_block_chars(blocks: List[Dict[str, Any]]) -> int:
    return sum(block_content_chars(b) for b in blocks)


def score_trigger_chars() -> int:
    return _env_int("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", _DEFAULT_TRIGGER_CHARS)


def llm_score_enabled() -> bool:
    return _env_bool("DOC_KNOWLEDGE_LLM_SCORE_ENABLED", True)


def should_score_and_select(blocks: List[Dict[str, Any]]) -> bool:
    """True when LLM scoring/selection should run (total chars exceed trigger)."""
    if not blocks or not llm_score_enabled():
        return False
    return total_block_chars(blocks) > score_trigger_chars()


def join_knowledge_blocks(blocks: List[Dict[str, Any]]) -> str:
    """Join complete knowledge blocks without splitting any block."""
    texts = [block.get("text") or "" for block in blocks]
    return "\n".join(text for text in texts if text)


def select_blocks_by_score(
    blocks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Sort by relevance_score desc; greedily pick top blocks until char budget.

    Output char budget uses ``DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS`` (same as gate trigger).
    No minimum score cutoff — low-score blocks are dropped only when higher-score
    blocks already fill the budget. Whole blocks are always kept intact.
    """
    if not blocks:
        return [], {"input_count": 0, "selected_count": 0, "output_chars": 0}

    max_output_chars = score_trigger_chars()
    max_blocks = _env_int("DOC_KNOWLEDGE_MAX_BLOCKS", _DEFAULT_MAX_BLOCKS)

    indexed = list(enumerate(blocks))

    def sort_key(item: Tuple[int, Dict[str, Any]]) -> Tuple[float, int, int]:
        idx, block = item
        score = float(block.get("relevance_score") or 0.0)
        chars = block_content_chars(block)
        return (-score, chars, idx)

    indexed.sort(key=sort_key)

    selected: List[Dict[str, Any]] = []
    output_chars = 0
    dropped_limit = 0

    for _idx, block in indexed:
        block_chars = block_content_chars(block)
        if len(selected) >= max_blocks:
            dropped_limit += 1
            continue
        if selected and output_chars + block_chars > max_output_chars:
            dropped_limit += 1
            continue
        if not selected and block_chars > max_output_chars:
            # Single block exceeds budget: keep whole block (no truncate).
            selected.append(block)
            output_chars += block_chars
            continue

        selected.append(block)
        output_chars += block_chars

    # 构建选中块详情列表（供日志与 DAC Progress 消费）
    block_details: List[Dict[str, Any]] = []
    for b in selected:
        bid = b.get("id", "")
        block_details.append({
            "id": str(bid) if bid else "?",
            "score": float(b.get("relevance_score") or 0),
            "summary": _block_summary(b),
        })

    report = {
        "input_count": len(blocks),
        "selected_count": len(selected),
        "output_chars": output_chars,
        "max_output_chars": max_output_chars,
        "max_blocks": max_blocks,
        "dropped_limit": dropped_limit,
        "blocks": block_details,
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
            "[DOC KNOWLEDGE GATE] total_chars=%d <= trigger=%d → skip score/select, "
            "return all selected blocks as-is",
            total_chars,
            trigger_chars,
        )
        return

    log.info(
        "[DOC KNOWLEDGE SELECT] 筛选后 %d 块 → 按分选取保留 %d 块, output_chars=%d "
        "(dropped_limit=%d char_budget=%d max_blocks=%d)",
        report.get("input_count", 0),
        report.get("selected_count", 0),
        report.get("output_chars", 0),
        report.get("dropped_limit", 0),
        report.get("max_output_chars", 0),
        report.get("max_blocks", 0),
    )


def _block_summary(block: Dict[str, Any]) -> str:
    desc = (block.get("score_description") or block.get("metadata_value") or "")
    return desc[:100] if desc else "-"


def log_final_knowledge_selection(
    log: logging.Logger,
    selected_blocks: List[Dict[str, Any]],
    *,
    total_input: int = 0,
) -> None:
    """Print final selection overview: only the selected blocks."""
    n_sel = len(selected_blocks)

    log.info(
        "[DOC KNOWLEDGE SELECT] ========== 最终选中 %d 块（共 %d 个待选）==========",
        n_sel,
        total_input,
    )

    sorted_selected = sorted(
        selected_blocks, key=lambda b: float(b.get("relevance_score") or 0), reverse=True
    )

    for i, b in enumerate(sorted_selected):
        bid = b.get("id", "?")
        score = float(b.get("relevance_score") or 0)
        summary = _block_summary(b)
        log.info(
            "[DOC KNOWLEDGE SELECT]   #%-2d id=%-36s score=%-4.1f %s",
            i + 1,
            bid,
            score,
            summary,
        )

    log.info("[DOC KNOWLEDGE SELECT] ========== 选块结果结束 ==========")
