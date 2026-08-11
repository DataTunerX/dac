"""LLM invoke helpers with JSON parse / validation retry (default max 3 attempts)."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, List, Optional, Sequence

from langchain_core.messages import BaseMessage, HumanMessage

logger = logging.getLogger("llm_invoke_retry")

DEFAULT_LLM_JSON_PARSE_MAX_RETRIES = 3

JSON_CORRECTION_MESSAGE = (
    "上次输出无法解析为合法 JSON。请仅输出要求的 JSON 对象，"
    "使用 ASCII 双引号，不要 Markdown 代码块，不要额外说明文字。"
)


def llm_json_parse_max_retries() -> int:
    """Max LLM re-invocations when JSON parse/validation fails (env: LLM_JSON_PARSE_MAX_RETRIES)."""
    raw = os.getenv("LLM_JSON_PARSE_MAX_RETRIES", str(DEFAULT_LLM_JSON_PARSE_MAX_RETRIES))
    try:
        value = int(raw)
        return value if value >= 1 else DEFAULT_LLM_JSON_PARSE_MAX_RETRIES
    except (TypeError, ValueError):
        logger.warning(
            "Invalid LLM_JSON_PARSE_MAX_RETRIES=%r, using default %d",
            raw,
            DEFAULT_LLM_JSON_PARSE_MAX_RETRIES,
        )
        return DEFAULT_LLM_JSON_PARSE_MAX_RETRIES


def _default_dict_validator(parsed: Any) -> Optional[str]:
    if parsed is None:
        return "parse returned None"
    if not isinstance(parsed, dict):
        return f"expected dict, got {type(parsed).__name__}"
    return None


def invoke_llm_with_json_retry(
    llm: Any,
    messages: Sequence[BaseMessage],
    parse_fn: Callable[[Any], Any],
    *,
    validate: Optional[Callable[[Any], Optional[str]]] = None,
    label: str = "llm_json",
    max_retries: Optional[int] = None,
    correction_message: str = JSON_CORRECTION_MESSAGE,
) -> Any:
    """
    Invoke ``llm`` up to ``max_retries`` times until ``parse_fn(response)`` passes ``validate``.

    On failure, appends a correction HumanMessage and re-invokes (conversation context preserved).
    Returns the last successfully parsed value, or ``None`` if all attempts fail.
    """
    attempts = max_retries if max_retries is not None else llm_json_parse_max_retries()
    conversation: List[BaseMessage] = list(messages)
    validator = validate or _default_dict_validator

    last_err: Optional[str] = None
    for attempt in range(attempts):
        try:
            response = llm.invoke(conversation)
        except Exception as exc:
            parsed = None
            last_err = f"llm.invoke failed: {exc}"
        else:
            try:
                parsed = parse_fn(response)
            except Exception as exc:
                parsed = None
                last_err = str(exc)
            else:
                last_err = validator(parsed)

        if last_err is None:
            if attempt > 0:
                logger.info(
                    "%s succeeded on attempt %d/%d",
                    label,
                    attempt + 1,
                    attempts,
                )
            return parsed

        logger.warning(
            "%s failed attempt %d/%d: %s",
            label,
            attempt + 1,
            attempts,
            last_err,
        )
        if attempt + 1 < attempts:
            conversation = conversation + [HumanMessage(content=correction_message)]

    logger.error("%s exhausted %d attempts, last error: %s", label, attempts, last_err)
    return None
