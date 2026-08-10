"""Batch LLM relevance scoring for complete code snippets (post-search)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

from langchain_core.messages import HumanMessage
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from agent.prompts import BATCH_SNIPPET_SCORE_PROMPT
from agent.tool_call_utils import invoke_llm_with_tool, validate_pydantic, format_llm_output
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

langfuse = get_client()
langfuse_handler = CallbackHandler()


@dataclass
class LangfuseTraceContext:
    """Trace identifiers propagated to Langfuse for snippet LLM scoring."""

    user_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    agent_id: str = ""

_DEFAULT_BATCH_SIZE = 5
_DEFAULT_SINGLE_BLOCK_PREVIEW_CHARS = 15000
_DEFAULT_FALLBACK_SCORE = 5.0


class SnippetScoreItem(BaseModel):
    """单个代码片段的相关性评分结果。每个 snippet_id 对应一个完整的代码块，请勿拆分理解。"""
    snippet_id: int = Field(description="代码片段在列表中的序号（从0开始），必须为列表中每个 snippet_id 返回一条结果")
    relevance_score: float = Field(
        ge=0.0, le=10.0,
        description="相关度评分（0-10）。9-10：直接实现用户问题的核心逻辑；7-8：强相关依赖、关键数据模型或 API；4-6：间接相关，可作上下文参考；0-3：import、main、无关工具类或噪声"
    )
    description: str = Field(
        description="该代码块与用户问题的关系说明，1-2句话说明"
    )


class SnippetScoreBatchResult(BaseModel):
    """LLM 批量代码片段评分结果"""
    scores: List[SnippetScoreItem] = Field(
        default_factory=list,
        description="每个代码片段的相关性评分结果列表，必须为每个 snippet_id 返回一条结果"
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def batch_size() -> int:
    return max(1, _env_int("SNIPPET_SCORE_BATCH_SIZE", _DEFAULT_BATCH_SIZE))


def single_block_preview_chars() -> int:
    return _env_int(
        "SNIPPET_SCORE_SINGLE_BLOCK_PREVIEW_CHARS",
        _DEFAULT_SINGLE_BLOCK_PREVIEW_CHARS,
    )


def split_snippets_into_batches(
    snippets: Sequence[Dict[str, Any]],
    *,
    items_per_batch: Optional[int] = None,
) -> List[List[Dict[str, Any]]]:
    """Split snippets into batches of complete code blocks (never split one block)."""
    size = items_per_batch if items_per_batch is not None else batch_size()
    if size < 1:
        size = 1
    batches: List[List[Dict[str, Any]]] = []
    items = list(snippets)
    for i in range(0, len(items), size):
        batches.append(items[i : i + size])
    return batches


def _source_label(source: Optional[str]) -> str:
    labels = {
        "semantic": "SEMANTIC",
        "metadata": "METADATA_GREP",
        "local_grep": "LOCAL_GREP",
        "skill_read_code": "READ_CODE_SKILL",
        "call_chain": "CALL_CHAIN",
    }
    if not source:
        return "UNKNOWN"
    return labels.get(source, str(source).upper())


def _code_for_llm_prompt(code_content: str) -> str:
    if not code_content:
        return ""
    limit = single_block_preview_chars()
    if len(code_content) <= limit:
        return code_content
    return (
        code_content[:limit]
        + f"\n... [preview truncated at {limit} chars for LLM scoring; full block preserved in output]"
    )


def format_snippet_block(snippet_id: int, snippet: Dict[str, Any]) -> str:
    file_path = snippet.get("file_path") or "unknown"
    name = snippet.get("name") or "unknown"
    line_no = snippet.get("line_no") or "?"
    segment_type = snippet.get("segment_type") or "unknown"
    source = _source_label(snippet.get("source"))
    reason = snippet.get("relevance_reason") or ""
    business = snippet.get("business_meaning") or ""
    code = _code_for_llm_prompt(snippet.get("code_content") or "")

    parts = [
        "---",
        f"snippet_id: {snippet_id}",
        f"file: {file_path}",
        f"name: {name} | lines: {line_no} | type: {segment_type} | source: {source}",
    ]
    if reason:
        parts.append(f"existing_reason: {reason}")
    if business:
        parts.append(f"business_meaning: {business}")
    parts.append("code:")
    parts.append(code)
    parts.append("---")
    return "\n".join(parts)


def build_batch_score_prompt(query: str, batch: Sequence[Dict[str, Any]]) -> str:
    blocks = [format_snippet_block(i, snippet) for i, snippet in enumerate(batch)]
    return BATCH_SNIPPET_SCORE_PROMPT.format(
        query=query,
        snippets_block="\n".join(blocks),
    )


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
            sid = int(entry.get("snippet_id"))
        except (TypeError, ValueError):
            continue
        by_id[sid] = entry

    for i, snippet in enumerate(batch):
        entry = by_id.get(i)
        if not entry:
            snippet["relevance_score"] = fallback_score
            snippet["score_description"] = "评分缺失，使用默认分数"
            continue
        try:
            snippet["relevance_score"] = float(entry.get("relevance_score", fallback_score))
        except (TypeError, ValueError):
            snippet["relevance_score"] = fallback_score
        desc = entry.get("description") or entry.get("reason") or ""
        snippet["score_description"] = str(desc).strip() or "无描述"


def _fallback_batch_scores(batch: Sequence[Dict[str, Any]], *, reason: str) -> None:
    for snippet in batch:
        snippet["relevance_score"] = _DEFAULT_FALLBACK_SCORE
        snippet["score_description"] = reason


async def score_snippet_batch(
    batch: Sequence[Dict[str, Any]],
    *,
    query: str,
    llm: Any,
    trace: Optional[LangfuseTraceContext] = None,
    batch_index: int = 0,
    batch_total: int = 1,
) -> None:
    if not batch:
        return

    prompt = build_batch_score_prompt(query, batch)
    started = time.monotonic()

    try:
        score_tool = StructuredTool(
            name="score_snippets",
            description="为一批代码片段评分，返回每个片段与用户问题的相关度分数。",
            args_schema=SnippetScoreBatchResult,
            func=None,
            coroutine=None,
        )

        md = {
            "user_id": trace.user_id if trace else "",
            "run_id": trace.run_id if trace else "",
            "trace_id": trace.trace_id if trace else "",
        }

        data = await invoke_llm_with_tool(
            llm=llm,
            tool=score_tool,
            messages=[HumanMessage(content=prompt)],
            metadata=md,
            tool_choice="score_snippets",
            span_name=f"codeagent-snippet-score-batch-{batch_index}",
            span_input={
                "query": query,
                "batch_index": batch_index,
                "batch_total": batch_total,
                "snippet_count": len(batch),
            },
            retry=2,
            validate=validate_pydantic(SnippetScoreBatchResult),
            fallback_formatter=format_llm_output,
        )
        if data is None:
            raise ValueError("LLM did not call score_snippets tool")
        scores = data.get("scores") or []
        if not isinstance(scores, list):
            raise ValueError("LLM response missing scores list")
        _apply_batch_scores(batch, scores)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[SNIPPET LLM SCORE] batch %d/%d failed: %s",
            batch_index,
            batch_total,
            exc,
        )
        _fallback_batch_scores(batch, reason="LLM 评分失败，使用默认分数")

    elapsed = time.monotonic() - started
    logger.info(
        "[SNIPPET LLM SCORE] batch %d/%d: %d blocks scored in %.1fs",
        batch_index,
        batch_total,
        len(batch),
        elapsed,
    )
    for i, snippet in enumerate(batch):
        logger.info(
            "[SNIPPET LLM SCORE]   #%d %s %s score=%.1f desc=%s",
            i,
            snippet.get("name", "?"),
            snippet.get("line_no", "?"),
            float(snippet.get("relevance_score") or 0),
            (snippet.get("score_description") or "")[:120],
        )


async def score_snippets_batch_parallel(
    snippets: List[Dict[str, Any]],
    *,
    query: str,
    llm: Any,
    trace: Optional[LangfuseTraceContext] = None,
) -> List[Dict[str, Any]]:
    if not snippets:
        return snippets

    batches = split_snippets_into_batches(snippets)
    batch_total = len(batches)
    logger.info(
        "[SNIPPET LLM SCORE] query=%r snippets=%d batch_size=%d batches=%d (parallel) "
        "trace_id=%s run_id=%s user_id=%s agent_id=%s",
        (query or "")[:120],
        len(snippets),
        batch_size(),
        batch_total,
        (trace.trace_id if trace else ""),
        (trace.run_id if trace else ""),
        (trace.user_id if trace else ""),
        (trace.agent_id if trace else ""),
    )

    await asyncio.gather(
        *[
            score_snippet_batch(
                batch,
                query=query,
                llm=llm,
                trace=trace,
                batch_index=i + 1,
                batch_total=batch_total,
            )
            for i, batch in enumerate(batches)
        ],
        return_exceptions=False,
    )
    langfuse.flush()
    return snippets
