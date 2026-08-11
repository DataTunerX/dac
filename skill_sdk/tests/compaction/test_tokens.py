"""Unit tests for compaction token helpers and threshold logic."""

from __future__ import annotations

import math
import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skill_sdk.compaction.settings import CompactionSettings
from skill_sdk.compaction.tokens import (
    UsageSnapshot,
    calculate_context_tokens,
    estimate_context_tokens,
    estimate_tokens,
    should_compact,
    split_system_and_dialog,
    usage_from_ai_message,
)


class TestEstimateTokens(unittest.TestCase):
    """Chars/4 heuristic for message sizing."""

    def test_human_message_chars_div_4(self) -> None:
        """Human text uses ceil(len/4)."""
        msg = HumanMessage(content="abcd" * 10)  # 40 chars
        self.assertEqual(estimate_tokens(msg), 10)

    def test_tool_message(self) -> None:
        """Tool results are estimated from content length."""
        msg = ToolMessage(content="x" * 100, tool_call_id="1")
        self.assertEqual(estimate_tokens(msg), 25)

    def test_ai_includes_tool_call_args(self) -> None:
        """Assistant tool_calls contribute to the estimate."""
        msg = AIMessage(
            content="ok",
            tool_calls=[{"name": "grep", "args": {"path": "/a/b"}, "id": "1", "type": "tool_call"}],
        )
        self.assertGreater(estimate_tokens(msg), estimate_tokens(AIMessage(content="ok")))


class TestShouldCompact(unittest.TestCase):
    """Threshold formula: tokens > window - reserve."""

    def test_below_threshold(self) -> None:
        """Just under the trigger must not compact."""
        settings = CompactionSettings(enabled=True, reserve_tokens=100, keep_recent_tokens=50)
        self.assertFalse(should_compact(900, 1000, settings))

    def test_above_threshold(self) -> None:
        """Crossing window - reserve must trigger."""
        settings = CompactionSettings(enabled=True, reserve_tokens=100, keep_recent_tokens=50)
        self.assertTrue(should_compact(901, 1000, settings))

    def test_disabled(self) -> None:
        """Disabled settings never trigger."""
        settings = CompactionSettings(enabled=False, reserve_tokens=100, keep_recent_tokens=50)
        self.assertFalse(should_compact(9999, 1000, settings))


class TestUsageExtraction(unittest.TestCase):
    """usage_metadata / response_metadata parsing."""

    def test_usage_metadata(self) -> None:
        """Prefer LangChain usage_metadata when present."""
        msg = AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        usage = usage_from_ai_message(msg)
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(calculate_context_tokens(usage), 15)

    def test_response_metadata_token_usage(self) -> None:
        """Fall back to response_metadata.token_usage."""
        msg = AIMessage(
            content="hi",
            response_metadata={"token_usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}},
        )
        usage = usage_from_ai_message(msg)
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage.input, 20)
        self.assertEqual(calculate_context_tokens(usage), 23)

    def test_estimate_context_with_trailing(self) -> None:
        """Trailing messages after last usage are added via estimate."""
        ai = AIMessage(
            content="a",
            usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
        )
        trail = HumanMessage(content="x" * 40)
        est = estimate_context_tokens([SystemMessage(content="s"), ai, trail])
        self.assertEqual(est.usage_tokens, 100)
        self.assertEqual(est.trailing_tokens, math.ceil(40 / 4))
        self.assertEqual(est.tokens, 100 + math.ceil(40 / 4))


class TestSplitSystem(unittest.TestCase):
    """Leading system messages stay outside the dialog cut span."""

    def test_split(self) -> None:
        """Only leading contiguous SystemMessages are peeled off."""
        msgs = [
            SystemMessage(content="sys1"),
            SystemMessage(content="sys2"),
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ]
        system, dialog = split_system_and_dialog(msgs)
        self.assertEqual(len(system), 2)
        self.assertEqual(len(dialog), 2)
        self.assertIsInstance(dialog[0], HumanMessage)


if __name__ == "__main__":
    unittest.main()
