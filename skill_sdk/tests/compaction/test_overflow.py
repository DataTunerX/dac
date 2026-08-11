"""Unit tests for overflow detection."""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage

from skill_sdk.compaction.overflow import (
    is_context_overflow_message,
    is_overflow_error_text,
    is_overflow_exception,
    is_silent_overflow_success,
)


class TestOverflowPatterns(unittest.TestCase):
    """Provider error string matching."""

    def test_anthropic_style(self) -> None:
        """Anthropic 'prompt is too long' is overflow."""
        self.assertTrue(is_overflow_error_text("prompt is too long: 213462 tokens > 200000 maximum"))

    def test_openai_style(self) -> None:
        """OpenAI context window phrasing is overflow."""
        self.assertTrue(is_overflow_error_text("Your input exceeds the context window of this model"))

    def test_rate_limit_excluded(self) -> None:
        """Rate-limit text must not be treated as overflow."""
        self.assertFalse(is_overflow_error_text("Rate limit exceeded: too many tokens, please wait"))

    def test_exception_wrapper(self) -> None:
        """Exceptions are flattened and matched."""
        self.assertTrue(is_overflow_exception(RuntimeError("maximum context length is 128000 tokens")))

    def test_dashscope_max_bytes(self) -> None:
        """DashScope 'Exceeded limit on max bytes' is overflow."""
        self.assertTrue(is_overflow_error_text(
            "Error code: 400 - {'error': {'message': 'Exceeded limit on max bytes to request body : 6291456', 'type': 'invalid_request_error'}}"
        ))

    def test_max_tokens_per_request(self) -> None:
        """DeepSeek/DashScope 'exceeds the maximum number of tokens' is overflow."""
        self.assertTrue(is_overflow_error_text(
            "The input exceeds the maximum number of tokens configured for this model."
        ))


class TestSilentOverflow(unittest.TestCase):
    """Usage-based silent / length-fill overflow."""

    def test_silent_stop_over_window(self) -> None:
        """Successful stop with input above window is silent overflow."""
        msg = AIMessage(
            content="done",
            usage_metadata={"input_tokens": 2000, "output_tokens": 10, "total_tokens": 2010},
            response_metadata={"finish_reason": "stop"},
        )
        self.assertTrue(is_context_overflow_message(msg, context_window=1000))
        self.assertTrue(is_silent_overflow_success(msg, context_window=1000))

    def test_length_zero_output(self) -> None:
        """finish_reason=length with zero output near full window is overflow."""
        msg = AIMessage(
            content="",
            usage_metadata={"input_tokens": 990, "output_tokens": 0, "total_tokens": 990},
            response_metadata={"finish_reason": "length"},
        )
        self.assertTrue(is_context_overflow_message(msg, context_window=1000))
        self.assertTrue(is_silent_overflow_success(msg, context_window=1000))

    def test_normal_message_not_overflow(self) -> None:
        """Normal replies under the window are not overflow."""
        msg = AIMessage(
            content="ok",
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            response_metadata={"finish_reason": "stop"},
        )
        self.assertFalse(is_context_overflow_message(msg, context_window=1000))
        self.assertFalse(is_silent_overflow_success(msg, context_window=1000))

    def test_human_never_overflow(self) -> None:
        """Non-assistant messages are ignored."""
        self.assertFalse(is_context_overflow_message(HumanMessage(content="x"), 100))


if __name__ == "__main__":
    unittest.main()
