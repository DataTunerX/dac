"""LangChain message helpers for compaction markers and internal messages."""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.messages import BaseMessage, HumanMessage


COMPACTION_SUMMARY_PREFIX = (
    "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
)
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"

# Marker stored on HumanMessage.additional_kwargs for injected summaries.
COMPACTION_MARKER_KEY = "skill_sdk_compaction"

# Marker stored on HumanMessage.additional_kwargs for internal (non-user) messages
# such as nudge hints and step-analysis results.  These messages belong to the
# current ReAct turn and must not be treated as turn-start boundaries.
INTERNAL_MESSAGE_KEY = "sg_react_internal"


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


def is_internal_message(message: BaseMessage) -> bool:
    """Return True if ``message`` is an internal (non-user) HumanMessage.

    Internal messages are injected by the ReAct loop (nudge hints, step
    analysis results) and should not be treated as turn-start boundaries
    nor included in compaction summaries.

    Args:
        message: Any chat message.

    Returns:
        True when the message carries the internal marker.
    """
    if not isinstance(message, HumanMessage):
        return False
    extra = getattr(message, "additional_kwargs", None) or {}
    if isinstance(extra, Mapping) and extra.get(INTERNAL_MESSAGE_KEY):
        return True
    return False


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