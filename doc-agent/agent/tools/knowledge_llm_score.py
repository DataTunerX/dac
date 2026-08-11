"""Batch LLM relevance scoring for complete knowledge blocks (post-selection).

使用 tool call 机制替代原始 JSON-in-prompt 方式。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from agent.prompts import BATCH_KNOWLEDGE_SCORE_PROMPT
from agent.schema import ScoresResult
from agent.tool_call_utils import invoke_llm_with_tool, validate_pydantic

logger = logging.getLogger(__name__)

langfuse = get_client()
langfuse_handler = CallbackHandler()


@dataclass
class LangfuseTraceContext:
    """Trace identifiers propagated to Langfuse for knowledge-block LLM scoring."""

    user_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    agent_id: str = ""


_DEFAULT_BATCH_SIZE = 5
_DEFAULT_SINGLE_BLOCK_PREVIEW_CHARS = 15000
_DEFAULT_FALLBACK_SCORE = 5.0


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def batch_size() -> int:
    return max(1, _env_int("DOC_KNOWLEDGE_SCORE_BATCH_SIZE", _DEFAULT_BATCH_SIZE))


def single_block_preview_chars() -> int:
    return _env_int(
        "DOC_KNOWLEDGE_SCORE_SINGLE_BLOCK_PREVIEW_CHARS",
        _DEFAULT_SINGLE_BLOCK_PREVIEW_CHARS,
    )


def split_blocks_into_batches(
    blocks: Sequence[Dict[str, Any]],
    *,
    items_per_batch: Optional[int] = None,
) -> List[List[Dict[str, Any]]]:
    """Split blocks into batches of complete knowledge records (never split one block)."""
    size = items_per_batch if items_per_batch is not None else batch_size()
    if size < 1:
        size = 1
    batches: List[List[Dict[str, Any]]] = []
    items = list(blocks)
    for i in range(0, len(items), size):
        batches.append(items[i : i + size])
    return batches


def _text_for_llm_prompt(text: str) -> str:
    if not text:
        return ""
    limit = single_block_preview_chars()
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n... [preview truncated at {limit} chars for LLM scoring; full block preserved in output]"
    )


def format_knowledge_block(block_id: int, block: Dict[str, Any]) -> str:
    knowledge_id = block.get("id") or "unknown"
    metadata_value = block.get("metadata_value") or ""
    text = _text_for_llm_prompt(block.get("text") or "")

    parts = [
        "---",
        f"block_id: {block_id}",
        f"knowledge_id: {knowledge_id}",
    ]
    if metadata_value:
        parts.append(f"summary: {metadata_value}")
    parts.append("content:")
    parts.append(text)
    parts.append("---")
    return "\n".join(parts)


def build_batch_score_prompt(query: str, batch: Sequence[Dict[str, Any]]) -> str:
    blocks = [format_knowledge_block(i, block) for i, block in enumerate(batch)]
    return BATCH_KNOWLEDGE_SCORE_PROMPT.format(
        query=query,
        knowledge_blocks="\n".join(blocks),
    )


def _default_parse_output(answer: Any) -> Dict[str, Any]:
    """Fallback parse when tool call extraction fails."""
    import json

    raw = getattr(answer, "content", "") or str(answer or "")
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _apply_batch_scores(
    batch: Sequence[Dict[str, Any]],
    scores: Sequence[Dict[str, Any]],
    *,
    fallback_score: float = _DEFAULT_FALLBACK_SCORE,
) -> None:
    by_id: Dict[int, Dict[str, Any]] = {}
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        try:
            block_id = int(entry.get("block_id"))
        except (TypeError, ValueError):
            continue
        by_id[block_id] = entry

    for i, block in enumerate(batch):
        entry = by_id.get(i)
        if not entry:
            block["relevance_score"] = fallback_score
            block["score_description"] = "评分缺失，使用默认分数"
            continue
        try:
            block["relevance_score"] = float(entry.get("relevance_score", fallback_score))
        except (TypeError, ValueError):
            block["relevance_score"] = fallback_score
        desc = entry.get("description") or entry.get("reason") or ""
        block["score_description"] = str(desc).strip() or "无描述"


def _fallback_batch_scores(batch: Sequence[Dict[str, Any]], *, reason: str) -> None:
    for block in batch:
        block["relevance_score"] = _DEFAULT_FALLBACK_SCORE
        block["score_description"] = reason


def _trace_to_metadata(trace: Optional[LangfuseTraceContext]) -> Dict[str, str]:
    if trace is None:
        return {}
    return {
        "user_id": trace.user_id,
        "run_id": trace.run_id,
        "trace_id": trace.trace_id,
    }


async def score_knowledge_block_batch(
    batch: Sequence[Dict[str, Any]],
    *,
    query: str,
    llm: Any,
    parse_output: Optional[Callable[[Any], Dict[str, Any]]] = None,
    trace: Optional[LangfuseTraceContext] = None,
    batch_index: int = 0,
    batch_total: int = 1,
) -> None:
    if not batch:
        return

    parser = parse_output or _default_parse_output
    prompt = build_batch_score_prompt(query, batch)
    message = HumanMessage(content=prompt)
    started = time.monotonic()

    # Tool Call: score_knowledge_blocks — 批量评分知识块
    score_knowledge_blocks_tool = StructuredTool(
        name="score_knowledge_blocks",
        description="Score the relevance of knowledge blocks to the user's question.",
        args_schema=ScoresResult,
        func=None,
        coroutine=None,
    )

    try:
        result = await invoke_llm_with_tool(
            llm=llm,
            metadata=_trace_to_metadata(trace),
            fallback_formatter=parser,
            tool=score_knowledge_blocks_tool,
            messages=[message],
            tool_choice="score_knowledge_blocks",
            span_name=f"doc-agent-knowledge-score-batch-{batch_index}",
            span_input={"query": query, "batch_index": batch_index, "block_count": len(batch)},
            retry=2,
            validate=validate_pydantic(ScoresResult),
        )

        if result is None:
            raise ValueError("LLM did not return scores")

        scores = result.get("scores") or []
        if not isinstance(scores, list):
            raise ValueError("LLM response missing scores list")
        _apply_batch_scores(batch, scores)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[DOC KNOWLEDGE LLM SCORE] batch %d/%d failed: %s",
            batch_index,
            batch_total,
            exc,
        )
        _fallback_batch_scores(batch, reason="LLM 评分失败，使用默认分数")

    elapsed = time.monotonic() - started
    logger.info(
        "[DOC KNOWLEDGE LLM SCORE] batch %d/%d: %d blocks scored in %.1fs",
        batch_index,
        batch_total,
        len(batch),
        elapsed,
    )
    for i, block in enumerate(batch):
        logger.info(
            "[DOC KNOWLEDGE LLM SCORE]   #%d id=%s score=%.1f desc=%s",
            i,
            block.get("id", "?"),
            float(block.get("relevance_score") or 0),
            (block.get("score_description") or "")[:120],
        )


async def score_knowledge_blocks_batch_parallel(
    blocks: List[Dict[str, Any]],
    *,
    query: str,
    llm: Any,
    parse_output: Optional[Callable[[Any], Dict[str, Any]]] = None,
    trace: Optional[LangfuseTraceContext] = None,
) -> List[Dict[str, Any]]:
    if not blocks:
        return blocks

    batches = split_blocks_into_batches(blocks)
    batch_total = len(batches)
    logger.info(
        "[DOC KNOWLEDGE LLM SCORE] query=%r blocks=%d batch_size=%d batches=%d (parallel) "
        "trace_id=%s run_id=%s user_id=%s agent_id=%s",
        (query or "")[:120],
        len(blocks),
        batch_size(),
        batch_total,
        (trace.trace_id if trace else ""),
        (trace.run_id if trace else ""),
        (trace.user_id if trace else ""),
        (trace.agent_id if trace else ""),
    )

    await asyncio.gather(
        *[
            score_knowledge_block_batch(
                batch,
                query=query,
                llm=llm,
                parse_output=parse_output,
                trace=trace,
                batch_index=i + 1,
                batch_total=batch_total,
            )
            for i, batch in enumerate(batches)
        ],
        return_exceptions=False,
    )
    langfuse.flush()
    return blocks