"""Context-window overflow detection for provider errors and silent overflows."""

from __future__ import annotations

import re
from typing import Any, Mapping

from langchain_core.messages import AIMessage, BaseMessage

from skill_sdk.compaction.tokens import usage_from_ai_message


# Patterns matching provider errors when input exceeds the model context window.
OVERFLOW_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"prompt is too long", re.I),
    re.compile(r"request_too_large", re.I),
    re.compile(r"input is too long for requested model", re.I),
    re.compile(r"exceeds the context window", re.I),
    re.compile(
        r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
        re.I,
    ),
    re.compile(r"input token count.*exceeds the maximum", re.I),
    re.compile(r"maximum prompt length is \d+", re.I),
    re.compile(r"reduce the length of the messages", re.I),
    re.compile(r"maximum context length is \d+ tokens", re.I),
    re.compile(r"exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?", re.I),
    re.compile(
        r"input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)",
        re.I,
    ),
    re.compile(r"exceeds the limit of \d+", re.I),
    re.compile(r"exceeds the available context size", re.I),
    re.compile(r"greater than the context length", re.I),
    re.compile(r"context window exceeds limit", re.I),
    re.compile(r"exceeded model token limit", re.I),
    re.compile(r"too large for model with \d+ maximum context length", re.I),
    re.compile(
        r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?",
        re.I,
    ),
    re.compile(r"model_context_window_exceeded", re.I),
    re.compile(r"prompt too long; exceeded (?:max )?context length", re.I),
    re.compile(r"range of input length should be", re.I),
    re.compile(r"context[_ ]length[_ ]exceeded", re.I),
    re.compile(r"too many tokens", re.I),
    re.compile(r"token limit exceeded", re.I),
    re.compile(r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)", re.I),
    # DashScope: request body size limit (pre-token overflow, same root cause).
    re.compile(r"exceeded limit on max bytes", re.I),
    # DeepSeek / DashScope: max tokens per request.
    re.compile(r"exceeds the maximum number of tokens", re.I),
    re.compile(r"max tokens per request", re.I),
]

# Errors that look like overflow patterns but are rate limits / throttling.
NON_OVERFLOW_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(Throttling error|Service unavailable):", re.I),
    re.compile(r"rate limit", re.I),
    re.compile(r"too many requests", re.I),
]


def _exception_text(exc: BaseException) -> str:
    """Flatten an exception (and nested body fields) into searchable text.

    Args:
        exc: Raised provider / LangChain error.

    Returns:
        Concatenated string used for pattern matching.
    """
    parts: list[str] = [str(exc)]
    for attr in ("message", "body", "response", "args", "status_code", "type", "code", "request_id"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        if isinstance(value, (str, bytes)):
            parts.append(str(value))
        elif isinstance(value, (int, float)):
            parts.append(f"status_code={value}")
        elif isinstance(value, Mapping):
            parts.append(str(value))
        elif isinstance(value, (list, tuple)):
            parts.append(" ".join(str(x) for x in value))
        else:
            parts.append(str(value))
    # OpenAI-style: exc.body may be dict with error.message
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping):
            parts.append(str(err.get("message") or ""))
            parts.append(str(err.get("code") or ""))
            parts.append(str(err.get("type") or ""))
        # DashScope flat format: body.message / body.type directly (no error wrapper).
        body_msg = body.get("message")
        if isinstance(body_msg, (str, bytes)):
            parts.append(str(body_msg))
        body_type = body.get("type")
        if isinstance(body_type, (str, bytes)):
            parts.append(str(body_type))
        body_code = body.get("code")
        if body_code is not None:
            parts.append(str(body_code))
    return "\n".join(p for p in parts if p)


def is_overflow_error_text(text: str) -> bool:
    """Return True if ``text`` matches a known context-overflow error pattern.

    Args:
        text: Error message or flattened exception text.

    Returns:
        True when the text indicates context overflow (and is not excluded).
    """
    if not text:
        return False
    if any(p.search(text) for p in NON_OVERFLOW_PATTERNS):
        return False
    return any(p.search(text) for p in OVERFLOW_PATTERNS)


def is_overflow_exception(exc: BaseException) -> bool:
    """Detect context overflow from a raised exception.

    Args:
        exc: Exception from an LLM invoke.

    Returns:
        True if the exception indicates the prompt exceeded the context window.
    """
    return is_overflow_error_text(_exception_text(exc))


def _finish_reason(message: AIMessage) -> str:
    """Best-effort finish/stop reason from an assistant message.

    Args:
        message: Assistant message.

    Returns:
        Lowercased finish reason string, or empty string.
    """
    resp = getattr(message, "response_metadata", None) or {}
    if not isinstance(resp, Mapping):
        return ""
    for key in ("finish_reason", "stop_reason", "finishReason"):
        value = resp.get(key)
        if value:
            return str(value).lower()
    return ""


def is_context_overflow_message(
    message: BaseMessage,
    context_window: int | None = None,
) -> bool:
    """Detect overflow from a returned assistant message (non-exception path).

    Handles:
      1. Error-like content matching overflow patterns.
      2. Silent overflow: successful stop with input+cache_read > window.
      3. Length-stop with zero output while input fills >= 99% of the window.

    Args:
        message: Assistant message to inspect.
        context_window: Model window; required for silent / length-fill cases.

    Returns:
        True if the message indicates context overflow.
    """
    if not isinstance(message, AIMessage):
        return False

    content = str(getattr(message, "content", "") or "")
    if content and is_overflow_error_text(content):
        return True

    usage = usage_from_ai_message(message)
    finish = _finish_reason(message)

    if context_window and usage and finish in ("stop", "end_turn", ""):
        input_tokens = usage.input + usage.cache_read
        if input_tokens > context_window:
            return True

    if context_window and usage and finish == "length" and usage.output == 0:
        input_tokens = usage.input + usage.cache_read
        if input_tokens >= context_window * 0.99:
            return True

    return False


def is_silent_overflow_success(
    message: BaseMessage,
    context_window: int | None = None,
) -> bool:
    """Return True when overflow is detected but the call completed successfully.

    Silent success must compact without retrying the assistant turn.

    Args:
        message: Assistant message.
        context_window: Model window size.

    Returns:
        True for silent / length-fill overflow with a completed response path.
    """
    if not isinstance(message, AIMessage):
        return False
    if not context_window:
        return False
    usage = usage_from_ai_message(message)
    if not usage:
        return False
    finish = _finish_reason(message)
    input_tokens = usage.input + usage.cache_read
    if finish in ("stop", "end_turn", "") and input_tokens > context_window:
        return True
    if finish == "length" and usage.output == 0 and input_tokens >= context_window * 0.99:
        return True
    return False


def get_overflow_patterns() -> list[re.Pattern[str]]:
    """Return a copy of overflow regex patterns (for tests).

    Returns:
        List of compiled overflow patterns.
    """
    return list(OVERFLOW_PATTERNS)
