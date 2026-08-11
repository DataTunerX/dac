"""Token estimation and compaction threshold checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from skill_sdk.compaction.settings import CompactionSettings


# Conservative image-block char estimate used when content is multimodal.
_ESTIMATED_IMAGE_CHARS = 4800


@dataclass(frozen=True)
class UsageSnapshot:
    """Normalized token usage from a provider response."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ContextUsageEstimate:
    """Estimated context size for a message list."""

    tokens: int
    usage_tokens: int
    trailing_tokens: int
    last_usage_index: int | None


def _content_char_count(content: Any) -> int:
    """Count characters in LangChain message content (str or block list).

    Args:
        content: Message ``content`` field.

    Returns:
        Approximate character count including a fixed estimate for image blocks.
    """
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        chars = 0
        for block in content:
            if isinstance(block, str):
                chars += len(block)
            elif isinstance(block, Mapping):
                btype = block.get("type")
                if btype == "text":
                    chars += len(str(block.get("text") or ""))
                elif btype in ("image", "image_url"):
                    chars += _ESTIMATED_IMAGE_CHARS
                else:
                    chars += len(str(block))
            else:
                chars += len(str(block))
        return chars
    return len(str(content))


def estimate_tokens(message: BaseMessage) -> int:
    """Estimate tokens for one message using a chars/4 heuristic.

    The heuristic intentionally overestimates slightly so compaction triggers
    before a hard provider rejection.

    Args:
        message: A LangChain chat message.

    Returns:
        Estimated token count (ceiling of chars/4).
    """
    chars = _content_char_count(getattr(message, "content", None))
    if isinstance(message, AIMessage):
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if isinstance(call, Mapping):
                chars += len(str(call.get("name") or ""))
                chars += len(str(call.get("args") or call.get("arguments") or ""))
            else:
                chars += len(str(call))
        extra = getattr(message, "additional_kwargs", None) or {}
        if isinstance(extra, Mapping):
            reasoning = extra.get("reasoning_content")
            if reasoning:
                chars += len(str(reasoning))
    return max(0, math.ceil(chars / 4))


def calculate_context_tokens(usage: UsageSnapshot | Mapping[str, Any]) -> int:
    """Compute total context tokens from a usage object.

    Prefers ``total_tokens`` when present and positive; otherwise sums
    input + output + cache_read + cache_write.

    Args:
        usage: ``UsageSnapshot`` or a mapping with the same fields.

    Returns:
        Non-negative token total.
    """
    if isinstance(usage, UsageSnapshot):
        total = usage.total_tokens
        if total > 0:
            return total
        return usage.input + usage.output + usage.cache_read + usage.cache_write

    total = int(usage.get("total_tokens") or usage.get("totalTokens") or 0)
    if total > 0:
        return total
    return (
        int(usage.get("input") or usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        + int(usage.get("output") or usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        + int(usage.get("cache_read") or usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("cache_write") or usage.get("cache_creation_input_tokens") or 0)
    )


def usage_from_ai_message(message: BaseMessage) -> UsageSnapshot | None:
    """Extract provider usage from an ``AIMessage`` when available.

    Looks at ``usage_metadata`` and common ``response_metadata`` shapes.

    Args:
        message: Candidate assistant message.

    Returns:
        ``UsageSnapshot`` if usable usage is present; otherwise ``None``.
    """
    if not isinstance(message, AIMessage):
        return None

    meta = getattr(message, "usage_metadata", None)
    if isinstance(meta, Mapping) and meta:
        inp = int(meta.get("input_tokens") or meta.get("input") or 0)
        out = int(meta.get("output_tokens") or meta.get("output") or 0)
        total = int(meta.get("total_tokens") or 0)
        cache_read = int(
            meta.get("cache_read")
            or meta.get("cache_read_input_tokens")
            or (meta.get("input_token_details") or {}).get("cache_read", 0)
            or 0
        )
        cache_write = int(
            meta.get("cache_write")
            or meta.get("cache_creation_input_tokens")
            or (meta.get("input_token_details") or {}).get("cache_creation", 0)
            or 0
        )
        snap = UsageSnapshot(
            input=inp,
            output=out,
            cache_read=cache_read,
            cache_write=cache_write,
            total_tokens=total or (inp + out + cache_read + cache_write),
        )
        if calculate_context_tokens(snap) > 0:
            return snap

    resp = getattr(message, "response_metadata", None) or {}
    if isinstance(resp, Mapping):
        token_usage = resp.get("token_usage") or resp.get("usage") or {}
        if isinstance(token_usage, Mapping) and token_usage:
            inp = int(
                token_usage.get("prompt_tokens")
                or token_usage.get("input_tokens")
                or token_usage.get("input")
                or 0
            )
            out = int(
                token_usage.get("completion_tokens")
                or token_usage.get("output_tokens")
                or token_usage.get("output")
                or 0
            )
            total = int(token_usage.get("total_tokens") or 0)
            cache_read = int(token_usage.get("cache_read") or token_usage.get("cache_read_input_tokens") or 0)
            cache_write = int(
                token_usage.get("cache_write") or token_usage.get("cache_creation_input_tokens") or 0
            )
            snap = UsageSnapshot(
                input=inp,
                output=out,
                cache_read=cache_read,
                cache_write=cache_write,
                total_tokens=total or (inp + out + cache_read + cache_write),
            )
            if calculate_context_tokens(snap) > 0:
                return snap
    return None


def estimate_context_tokens(messages: Sequence[BaseMessage]) -> ContextUsageEstimate:
    """Estimate context tokens for a full message list.

    Uses the last assistant message with valid usage when present, then adds
    char/4 estimates for trailing messages after that index.

    Args:
        messages: Conversation messages in send order.

    Returns:
        ``ContextUsageEstimate`` with totals and the last usage index.
    """
    last_usage: UsageSnapshot | None = None
    last_index: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        usage = usage_from_ai_message(messages[i])
        if usage is not None:
            last_usage = usage
            last_index = i
            break

    if last_usage is None or last_index is None:
        estimated = sum(estimate_tokens(m) for m in messages)
        return ContextUsageEstimate(
            tokens=estimated,
            usage_tokens=0,
            trailing_tokens=estimated,
            last_usage_index=None,
        )

    usage_tokens = calculate_context_tokens(last_usage)
    trailing = 0
    for i in range(last_index + 1, len(messages)):
        trailing += estimate_tokens(messages[i])
    return ContextUsageEstimate(
        tokens=usage_tokens + trailing,
        usage_tokens=usage_tokens,
        trailing_tokens=trailing,
        last_usage_index=last_index,
    )


def should_compact(
    context_tokens: int,
    context_window: int,
    settings: CompactionSettings,
) -> bool:
    """Return whether context usage crossed the compaction threshold.

    Triggers when ``context_tokens > context_window - reserve_tokens``.

    Args:
        context_tokens: Current estimated or reported context size.
        context_window: Model context window.
        settings: Compaction settings (must be enabled).

    Returns:
        True if auto-compaction should run.
    """
    if not settings.enabled:
        return False
    if context_window <= 0:
        return False
    return context_tokens > context_window - settings.reserve_tokens


def split_system_and_dialog(
    messages: Sequence[BaseMessage],
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Split leading system messages from the remainder of the dialog.

    Leading contiguous ``SystemMessage`` instances are preserved as-is and never
    summarized. Everything after the first non-system message is dialog.

    Args:
        messages: Full message list.

    Returns:
        ``(system_messages, dialog_messages)``.
    """
    system: list[BaseMessage] = []
    idx = 0
    while idx < len(messages) and isinstance(messages[idx], SystemMessage):
        system.append(messages[idx])
        idx += 1
    return system, list(messages[idx:])


def estimate_messages_tokens(messages: Sequence[BaseMessage]) -> int:
    """Sum ``estimate_tokens`` across all messages.

    Args:
        messages: Messages to measure.

    Returns:
        Total estimated tokens.
    """
    return sum(estimate_tokens(m) for m in messages)
