"""Prepare and execute context compaction against an in-memory message list.

File-operation tracking is disabled — expert-agent tools invoke remote agents
whose results are natural-language answers, not file paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.compaction.cut_point import find_cut_point
from agent.compaction.messages import is_compaction_summary_message, make_compaction_summary_message
from agent.compaction.prompts import (
    SUMMARIZATION_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT,
    TURN_PREFIX_SUMMARIZATION_PROMPT,
    UPDATE_SUMMARIZATION_PROMPT,
)
from agent.compaction.serialize import serialize_conversation
from agent.compaction.settings import CompactionSettings
from agent.compaction.tokens import (
    estimate_context_tokens,
    estimate_messages_tokens,
    split_system_and_dialog,
)

logger = logging.getLogger("compaction")


@dataclass
class CompactionBoundary:
    """In-memory record of a completed compaction (no disk persistence).

    Attributes:
        summary: Structured summary text.
        tokens_before: Estimated tokens before compaction.
        details: Empty dict (file tracking disabled in expert-agent).
        first_kept_fingerprint: Identity hint for the first kept dialog message.
    """

    summary: str
    tokens_before: int
    details: dict[str, Any] = field(default_factory=dict)
    first_kept_fingerprint: str = ""


@dataclass
class CompactionPreparation:
    """Inputs required to generate a compaction summary."""

    system_messages: list[BaseMessage]
    dialog: list[BaseMessage]
    messages_to_summarize: list[BaseMessage]
    turn_prefix_messages: list[BaseMessage]
    kept_messages: list[BaseMessage]
    is_split_turn: bool
    tokens_before: int
    previous_summary: str | None
    previous_details: dict[str, Any] | None
    settings: CompactionSettings
    first_kept_index: int


@dataclass
class CompactionResult:
    """Outcome of a successful compaction."""

    summary: str
    messages: list[BaseMessage]
    tokens_before: int
    estimated_tokens_after: int
    details: dict[str, Any]
    reason: str = "threshold"
    from_hook: bool = False


def _message_fingerprint(message: BaseMessage) -> str:
    """Build a stable-enough fingerprint for locating a kept message later.

    Args:
        message: Dialog message.

    Returns:
        Short string identity for boundary tracking.
    """
    role = type(message).__name__
    content = str(getattr(message, "content", "") or "")[:120]
    tool_id = getattr(message, "tool_call_id", "") or ""
    return f"{role}|{tool_id}|{content}"


def prepare_compaction(
    messages: Sequence[BaseMessage],
    settings: CompactionSettings,
    previous_boundary: CompactionBoundary | None = None,
) -> CompactionPreparation | None:
    """Compute cut points and message spans for a compaction pass.

    Args:
        messages: Full LLM context (system + dialog).
        settings: Compaction settings.
        previous_boundary: Prior compaction in this run, if any.

    Returns:
        Preparation payload, or ``None`` when there is nothing useful to summarize.
    """
    system_messages, dialog = split_system_and_dialog(messages)
    if not dialog:
        return None

    previous_summary = previous_boundary.summary if previous_boundary else None
    previous_details = previous_boundary.details if previous_boundary else None

    boundary_start = 0
    if previous_boundary and previous_boundary.first_kept_fingerprint:
        for i, msg in enumerate(dialog):
            if _message_fingerprint(msg) == previous_boundary.first_kept_fingerprint:
                boundary_start = i
                break
        else:
            # Fallback: start after the previous summary injection if present.
            for i, msg in enumerate(dialog):
                if is_compaction_summary_message(msg):
                    boundary_start = i + 1
                    break

    tokens_before = estimate_context_tokens(list(messages)).tokens
    cut = find_cut_point(dialog, boundary_start, len(dialog), settings.keep_recent_tokens)

    history_end = cut.turn_start_index if cut.is_split_turn else cut.first_kept_index
    messages_to_summarize = list(dialog[boundary_start:history_end])
    turn_prefix: list[BaseMessage] = []
    if cut.is_split_turn:
        turn_prefix = list(dialog[cut.turn_start_index : cut.first_kept_index])

    if not messages_to_summarize and not turn_prefix:
        return None

    kept = list(dialog[cut.first_kept_index :])
    return CompactionPreparation(
        system_messages=list(system_messages),
        dialog=dialog,
        messages_to_summarize=messages_to_summarize,
        turn_prefix_messages=turn_prefix,
        kept_messages=kept,
        is_split_turn=cut.is_split_turn,
        tokens_before=tokens_before,
        previous_summary=previous_summary,
        previous_details=previous_details,
        settings=settings,
        first_kept_index=cut.first_kept_index,
    )


def rebuild_messages(
    system_messages: Sequence[BaseMessage],
    summary: str,
    kept_messages: Sequence[BaseMessage],
) -> list[BaseMessage]:
    """Rebuild LLM context as system + summary human + kept recent messages.

    Args:
        system_messages: Leading system prompts to preserve.
        summary: Compaction summary body.
        kept_messages: Recent messages kept verbatim.

    Returns:
        New message list for subsequent LLM invokes.
    """
    return [
        *system_messages,
        make_compaction_summary_message(summary),
        *kept_messages,
    ]


async def _ainvoke_plain(llm: Any, messages: list[BaseMessage]) -> Any:
    """Invoke an LLM without tools (used for summarization).

    Args:
        llm: LangChain-compatible chat model.
        messages: Prompt messages.

    Returns:
        Model response object.
    """
    if hasattr(llm, "ainvoke"):
        return await llm.ainvoke(messages)
    import asyncio

    return await asyncio.to_thread(llm.invoke, messages)


def _response_text(resp: Any) -> str:
    """Extract plain text content from a summarizer response.

    Args:
        resp: LLM response (usually ``AIMessage``).

    Returns:
        Stripped text, or empty string.
    """
    content = getattr(resp, "content", None)
    if content is None:
        return str(resp or "").strip()
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content).strip()


async def generate_summary_text(
    llm: Any,
    current_messages: Sequence[BaseMessage],
    *,
    reserve_tokens: int,
    previous_summary: str | None = None,
    custom_instructions: str | None = None,
    turn_prefix: bool = False,
) -> str:
    """Call the summarizer LLM and return structured summary text.

    Args:
        llm: Chat model without tools.
        current_messages: Span to summarize.
        reserve_tokens: Used to derive max output tokens (~0.8 or 0.5).
        previous_summary: Prior summary for iterative update.
        custom_instructions: Optional extra focus instructions.
        turn_prefix: Use the turn-prefix prompt and smaller max tokens.

    Returns:
        Summary text from the model (may be empty on failure).
    """
    factor = 0.5 if turn_prefix else 0.8
    max_tokens = max(256, int(reserve_tokens * factor))

    if turn_prefix:
        prompt_kind = "turn_prefix"
        base_prompt = TURN_PREFIX_SUMMARIZATION_PROMPT
    elif previous_summary:
        prompt_kind = "update"
        base_prompt = UPDATE_SUMMARIZATION_PROMPT
    else:
        prompt_kind = "first"
        base_prompt = SUMMARIZATION_PROMPT
    if custom_instructions:
        base_prompt = f"{base_prompt}\n\nAdditional focus: {custom_instructions}"

    conversation_text = serialize_conversation(list(current_messages))
    prompt_text = f"<conversation>\n{conversation_text}\n</conversation>\n\n"
    if previous_summary and not turn_prefix:
        prompt_text += f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
    prompt_text += base_prompt

    summarizer_messages: list[BaseMessage] = [
        SystemMessage(content=SUMMARIZATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt_text),
    ]

    logger.info(
        "summarize START kind=%s msgs=%d prev_summary=%s max_tokens=%d input_chars=%d",
        prompt_kind,
        len(current_messages),
        bool(previous_summary),
        max_tokens,
        len(conversation_text),
    )

    # Prefer binding max_tokens when the model supports bind/kwargs.
    bound = llm
    try:
        if hasattr(llm, "bind"):
            bound = llm.bind(max_tokens=max_tokens)
    except Exception:
        bound = llm
        logger.debug("summarizer bind(max_tokens) failed; using unbound llm", exc_info=True)

    resp = await _ainvoke_plain(bound, summarizer_messages)
    text = _response_text(resp)
    logger.info(
        "summarize DONE kind=%s output_len=%d output_chars=%d",
        prompt_kind,
        len(text),
        len(text) if text else 0,
    )
    return text


async def compact(
    preparation: CompactionPreparation,
    llm: Any,
    *,
    reason: str = "threshold",
    custom_instructions: str | None = None,
) -> CompactionResult:
    """Generate summaries and rebuild the message list.

    File-operation tracking is disabled — expert-agent tools are remote
    agent calls, not file-level operations.

    Args:
        preparation: Output of ``prepare_compaction``.
        llm: Summarizer LLM.
        reason: Trigger reason (``threshold`` / ``overflow`` / ``manual``).
        custom_instructions: Optional focus for the summary.

    Returns:
        ``CompactionResult`` with rebuilt messages and metadata.
    """
    settings = preparation.settings

    if preparation.is_split_turn and preparation.turn_prefix_messages:
        logger.info(
            "summarize SPLIT_TURN history_msgs=%d turn_prefix_msgs=%d",
            len(preparation.messages_to_summarize),
            len(preparation.turn_prefix_messages),
        )
        history_text = "No prior history."
        if preparation.messages_to_summarize:
            history_text = await generate_summary_text(
                llm,
                preparation.messages_to_summarize,
                reserve_tokens=settings.reserve_tokens,
                previous_summary=preparation.previous_summary,
                custom_instructions=custom_instructions,
            )
        turn_prefix_text = await generate_summary_text(
            llm,
            preparation.turn_prefix_messages,
            reserve_tokens=settings.reserve_tokens,
            turn_prefix=True,
            custom_instructions=custom_instructions,
        )
        summary = (
            f"{history_text}\n\n---\n\n**Turn Context (split turn):**\n\n{turn_prefix_text}"
        )
    else:
        summary = await generate_summary_text(
            llm,
            preparation.messages_to_summarize,
            reserve_tokens=settings.reserve_tokens,
            previous_summary=preparation.previous_summary,
            custom_instructions=custom_instructions,
        )

    if not summary.strip():
        # Fallback heuristic so compaction still reduces context.
        summary = (
            "## Goal\n(unknown — summarizer returned empty)\n\n"
            "## Progress\n### Done\n- [x] Prior turns compacted\n\n"
            "## Next Steps\n1. Continue from the retained recent messages"
        )

    details: dict[str, Any] = {}

    new_messages = rebuild_messages(
        preparation.system_messages,
        summary,
        preparation.kept_messages,
    )
    return CompactionResult(
        summary=summary,
        messages=new_messages,
        tokens_before=preparation.tokens_before,
        estimated_tokens_after=estimate_messages_tokens(new_messages),
        details=details,
        reason=reason,
        from_hook=False,
    )


def boundary_from_result(
    result: CompactionResult,
    preparation: CompactionPreparation,
) -> CompactionBoundary:
    """Create an in-memory boundary record from a compaction result.

    Args:
        result: Completed compaction.
        preparation: The preparation used for that pass.

    Returns:
        ``CompactionBoundary`` for the next iterative compaction.
    """
    fingerprint = ""
    if preparation.kept_messages:
        fingerprint = _message_fingerprint(preparation.kept_messages[0])
    return CompactionBoundary(
        summary=result.summary,
        tokens_before=result.tokens_before,
        details=result.details,
        first_kept_fingerprint=fingerprint,
    )