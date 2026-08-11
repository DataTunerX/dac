"""LangChain message helpers for compaction markers."""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.messages import BaseMessage, HumanMessage


COMPACTION_SUMMARY_PREFIX = (
    "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
)
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"

# Marker stored on HumanMessage.additional_kwargs for injected summaries.
COMPACTION_MARKER_KEY = "skill_sdk_compaction"


def is_compaction_summary_message(message: BaseMessage) -> bool:
    """Return True if ``message`` is an injected compaction summary.

    Args:
        message: Any chat message.

    Returns:
        True when the message carries the compaction marker or prefix.
    """
    if not isinstance(message, HumanMessage):
        return False
    extra = getattr(message, "additional_kwargs", None) or {}
    if isinstance(extra, Mapping) and extra.get(COMPACTION_MARKER_KEY):
        return True
    content = str(getattr(message, "content", "") or "")
    return content.startswith(COMPACTION_SUMMARY_PREFIX)


def make_compaction_summary_message(summary: str) -> HumanMessage:
    """Build the user-role message that injects a compaction summary into context.

    Args:
        summary: Structured summary text (may already include file-list tags).

    Returns:
        ``HumanMessage`` wrapped with the standard prefix/suffix and marker.
    """
    text = f"{COMPACTION_SUMMARY_PREFIX}{summary}{COMPACTION_SUMMARY_SUFFIX}"
    return HumanMessage(
        content=text,
        additional_kwargs={COMPACTION_MARKER_KEY: True},
    )


def message_role_label(message: BaseMessage) -> str:
    """Return a short role label for logging/serialization.

    Args:
        message: Chat message.

    Returns:
        One of ``system``, ``user``, ``assistant``, ``tool``, or ``unknown``.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    return "unknown"
