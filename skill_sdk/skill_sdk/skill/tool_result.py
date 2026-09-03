"""
Unified tool result model — inspired by Pi Agent Loop's ToolResultMessage.

Every tool execution produces a ToolResult with identical structure,
regardless of success, failure, or policy block. The ``is_error`` flag
is informational (for the LLM to observe), not a control signal.

This is the single source of truth for tool output format. All tool
plugins and the runner's _dispatch_tool use this model.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Unified tool execution result.

    Mirrors Pi Agent Loop's ToolResultMessage structure:
      - ``content``: the human-readable result (text, JSON, or structured data)
      - ``is_error``: whether the execution encountered an error (informational)
      - ``details``: optional structured metadata (usage, file lists, etc.)

    The ``status`` field provides a quick summary for the LLM to interpret:
      - ``"success"``: tool executed normally
      - ``"error"``: tool failed (command error, file not found, timeout, etc.)
      - ``"blocked"``: tool was blocked by safety policy (destructive commands, etc.)
    """

    tool_name: str = Field(description="Name of the tool that was invoked")
    status: Literal["success", "error", "blocked"] = Field(
        description="Execution outcome: success, error, or policy-blocked"
    )
    is_error: bool = Field(
        default=False,
        description="True when the tool encountered an error (informational, not a control signal)",
    )
    content: str = Field(
        default="",
        description="Human-readable result content (Pi: content[{type:text, text:...}])",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured metadata (Pi: details field). May contain returncode, stdout, stderr, etc.",
    )

    def to_tool_message_content(self) -> str:
        """Serialize to JSON string for ToolMessage content.

        The LLM sees this JSON and interprets ``status`` / ``is_error`` / ``content``
        to decide the next action. The loop itself does not interpret these fields.
        """
        return json.dumps(self.model_dump(), ensure_ascii=False, default=str)

    @classmethod
    def success(cls, tool_name: str, content: str = "", details: dict[str, Any] | None = None) -> ToolResult:
        """Create a successful result."""
        return cls(
            tool_name=tool_name,
            status="success",
            is_error=False,
            content=content,
            details=details or {},
        )

    @classmethod
    def error(cls, tool_name: str, content: str, details: dict[str, Any] | None = None) -> ToolResult:
        """Create an error result. The LLM observes the error text and decides next steps."""
        return cls(
            tool_name=tool_name,
            status="error",
            is_error=True,
            content=content,
            details=details or {},
        )

    @classmethod
    def blocked(cls, tool_name: str, reason: str, details: dict[str, Any] | None = None) -> ToolResult:
        """Create a policy-blocked result. The LLM sees the reason and can choose another approach."""
        return cls(
            tool_name=tool_name,
            status="blocked",
            is_error=True,
            content=reason,
            details=details or {},
        )