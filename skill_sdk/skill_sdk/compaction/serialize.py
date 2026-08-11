"""Serialize chat messages to plain text for summarization prompts."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


TOOL_RESULT_MAX_CHARS = 2000


def truncate_for_summary(text: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    """Truncate text for inclusion in a summarization request.

    Keeps the beginning and appends a marker with how many characters were cut.

    Args:
        text: Original text.
        max_chars: Maximum characters to keep.

    Returns:
        Possibly truncated string.
    """
    if len(text) <= max_chars:
        return text
    truncated_chars = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... {truncated_chars} more characters truncated]"


def _tool_call_repr(call: Any) -> str:
    """Format one tool call as ``name(arg=...)``.

    Args:
        call: LangChain tool-call dict or object.

    Returns:
        Compact string representation.
    """
    if isinstance(call, Mapping):
        name = str(call.get("name") or "unknown")
        args = call.get("args")
        if args is None:
            args = call.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if isinstance(args, Mapping):
            args_str = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
        else:
            args_str = json.dumps(args, ensure_ascii=False) if args is not None else ""
        return f"{name}({args_str})"
    return str(call)


def serialize_conversation(messages: Sequence[BaseMessage]) -> str:
    """Flatten messages into tagged text so the model does not continue the dialog.

    Tool results are capped at ``TOOL_RESULT_MAX_CHARS`` to keep the summarizer
    request within a reasonable token budget.

    Args:
        messages: Messages to serialize (typically the span being summarized).

    Returns:
        Multi-block text with ``[User]`` / ``[Assistant]`` / ``[Tool result]`` labels.
    """
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = str(getattr(msg, "content", "") or "").strip()
            if content:
                parts.append(f"[User]: {content}")
        elif isinstance(msg, AIMessage):
            content = str(getattr(msg, "content", "") or "").strip()
            extra = getattr(msg, "additional_kwargs", None) or {}
            reasoning = ""
            if isinstance(extra, Mapping):
                reasoning = str(extra.get("reasoning_content") or "").strip()
            if reasoning:
                parts.append(f"[Assistant thinking]: {reasoning}")
            if content:
                parts.append(f"[Assistant]: {content}")
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                rendered = "; ".join(_tool_call_repr(c) for c in tool_calls)
                parts.append(f"[Assistant tool calls]: {rendered}")
        elif isinstance(msg, ToolMessage):
            content = str(getattr(msg, "content", "") or "").strip()
            if content:
                parts.append(f"[Tool result]: {truncate_for_summary(content)}")
    return "\n\n".join(parts)
