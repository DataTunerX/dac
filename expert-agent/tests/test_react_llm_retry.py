"""Unit tests for ReAct LLM retry helpers and JSON parsing (no live LLM)."""
import asyncio

import httpx
import pytest

from agent.react import ReActRunner, _extract_http_status_code, _is_llm_retryable


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "error"):
        super().__init__(message)
        self.status_code = status_code


class _FakeResponseError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = type("R", (), {"status_code": status_code})()


def test_retryable_timeout():
    assert _is_llm_retryable(asyncio.TimeoutError()) is True


def test_retryable_httpx_timeout():
    assert _is_llm_retryable(httpx.ReadTimeout("read timeout")) is True


def test_retryable_429_and_5xx():
    assert _is_llm_retryable(_FakeHTTPError(429)) is True
    assert _is_llm_retryable(_FakeHTTPError(503)) is True
    assert _is_llm_retryable(_FakeResponseError(502)) is True


def test_not_retryable_4xx():
    assert _is_llm_retryable(_FakeHTTPError(400)) is False
    assert _is_llm_retryable(_FakeHTTPError(401)) is False
    assert _is_llm_retryable(_FakeHTTPError(404)) is False


def test_retryable_message_hints():
    assert _is_llm_retryable(Exception("Rate limit exceeded")) is True
    assert _is_llm_retryable(Exception("connection reset by peer")) is True


def test_extract_http_status_code():
    assert _extract_http_status_code(_FakeHTTPError(429)) == 429
    assert _extract_http_status_code(_FakeResponseError(500)) == 500
    assert _extract_http_status_code(ValueError("x")) is None


def test_parse_structured_thought_with_trailing_comma():
    raw = """Planning next step:
```json
{
  "sub_goals": ["top 10 sales"],
  "gaps": ["return rates"],
  "planned_action": "call:structured_mysql",
  "confidence": "high",
}
```"""
    parsed = ReActRunner._parse_structured_thought(raw)
    assert parsed["valid"] is True
    assert parsed["sub_goals"] == ["top 10 sales"]
    assert parsed["planned_action"] == "call:structured_mysql"


def test_log_text_preview_empty():
    assert ReActRunner._log_text_preview("") == "(empty)"


def test_log_text_preview_truncates_with_char_count():
    long_text = "word " * 500
    preview = ReActRunner._log_text_preview(long_text, max_chars=80)
    assert "chars)" in preview
    assert len(preview) < len(long_text)


def test_format_log_list():
    assert ReActRunner._format_log_list([]) == "无"
    assert ReActRunner._format_log_list(["a", "b"]) == "a；b"


def test_tool_index_label():
    assert ReActRunner._tool_index_label(1, 1) == "本步唯一工具"
    assert ReActRunner._tool_index_label(1, 3) == "本步第 1/3 个工具"
    assert ReActRunner._tool_index_label(2, 3) == "本步第 2/3 个工具"


def test_query_likely_needs_foundation_context():
    assert ReActRunner._query_likely_needs_foundation_context("先看代码规则再查数") is True
    assert ReActRunner._query_likely_needs_foundation_context("按月统计用户注册分布") is False


def test_parse_structured_thought_missing_json_is_hint_not_valid():
    parsed = ReActRunner._parse_structured_thought("I will query the structured agent next.")
    assert parsed["valid"] is False
    assert "query" in parsed.get("raw_thought", "")


def test_truncate_progress_message():
    assert ReActRunner._truncate_progress_message("short", 20) == "short"
    long_text = "a" * 30
    truncated = ReActRunner._truncate_progress_message(long_text, 10)
    assert truncated.endswith("...")
    assert len(truncated) == 10


@pytest.mark.asyncio
async def test_emit_progress_invokes_callback():
    captured = []

    async def _emitter(event, *, message, status="running", extra=None):
        captured.append(
            {"event": event, "message": message, "status": status, "extra": extra or {}}
        )

    await ReActRunner._emit_progress(
        _emitter,
        "sg_react_step_start",
        message="step 1",
        extra={"step": 1, "max_steps": 5, "message_count": 2},
    )
    assert len(captured) == 1
    assert captured[0]["event"] == "sg_react_step_start"
    assert captured[0]["extra"]["step"] == 1


@pytest.mark.asyncio
async def test_emit_progress_noop_when_emitter_none():
    await ReActRunner._emit_progress(None, "sg_react_step_start", message="ignored")
