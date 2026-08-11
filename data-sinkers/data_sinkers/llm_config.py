"""Shared LLM client settings for data-sinkers extractors."""

from __future__ import annotations

import os

DEFAULT_LLM_REQUEST_TIMEOUT = 180


def llm_request_timeout_seconds() -> float:
    """HTTP timeout per LLM request (env: LLM_REQUEST_TIMEOUT, default 180s)."""
    raw = os.getenv("LLM_REQUEST_TIMEOUT", str(DEFAULT_LLM_REQUEST_TIMEOUT))
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_LLM_REQUEST_TIMEOUT
    except (TypeError, ValueError):
        return DEFAULT_LLM_REQUEST_TIMEOUT
