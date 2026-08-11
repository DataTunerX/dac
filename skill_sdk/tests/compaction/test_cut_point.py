"""Unit tests for cut-point selection."""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from skill_sdk.compaction.cut_point import find_cut_point, is_cut_point_message, is_turn_start_message


class TestCutPointRules(unittest.TestCase):
    """Valid cut / turn-start classification."""

    def test_never_cut_tool_result(self) -> None:
        """ToolMessage is never a valid cut point."""
        self.assertFalse(is_cut_point_message(ToolMessage(content="out", tool_call_id="1")))

    def test_human_is_turn_start(self) -> None:
        """Human messages start turns and are valid cuts."""
        msg = HumanMessage(content="go")
        self.assertTrue(is_turn_start_message(msg))
        self.assertTrue(is_cut_point_message(msg))

    def test_assistant_is_cut_not_turn_start(self) -> None:
        """Assistant may be a cut point but does not start a turn."""
        msg = AIMessage(content="thinking")
        self.assertTrue(is_cut_point_message(msg))
        self.assertFalse(is_turn_start_message(msg))


class TestFindCutPoint(unittest.TestCase):
    """Budget walk and split-turn detection."""

    def test_keeps_recent_human_boundary(self) -> None:
        """With a small keep budget, cut snaps to a later human message."""
        dialog = [
            HumanMessage(content="old " * 200),  # large
            AIMessage(content="old reply " * 200),
            ToolMessage(content="tool " * 200, tool_call_id="1"),
            HumanMessage(content="recent"),
            AIMessage(content="recent reply"),
        ]
        # Keep only a tiny recent budget so we cut before the last human.
        result = find_cut_point(dialog, 0, len(dialog), keep_recent_tokens=20)
        self.assertGreaterEqual(result.first_kept_index, 3)
        self.assertFalse(result.is_split_turn)

    def test_does_not_cut_at_tool_message(self) -> None:
        """When accumulation lands on a tool result, snap forward to a valid cut."""
        dialog = [
            HumanMessage(content="q1"),
            AIMessage(
                content="a1",
                tool_calls=[{"name": "grep", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            ToolMessage(content="x" * 4000, tool_call_id="1"),
            AIMessage(content="a2"),
        ]
        result = find_cut_point(dialog, 0, len(dialog), keep_recent_tokens=10)
        kept = dialog[result.first_kept_index]
        self.assertFalse(isinstance(kept, ToolMessage))

    def test_split_turn_when_cut_on_assistant(self) -> None:
        """Cutting mid-turn at an assistant sets is_split_turn."""
        dialog = [
            HumanMessage(content="big request " * 500),
            AIMessage(content="step1 " * 500),
            ToolMessage(content="out1 " * 500, tool_call_id="1"),
            AIMessage(content="step2 recent"),
            ToolMessage(content="out2", tool_call_id="2"),
        ]
        result = find_cut_point(dialog, 0, len(dialog), keep_recent_tokens=30)
        if not is_turn_start_message(dialog[result.first_kept_index]):
            self.assertTrue(result.is_split_turn)
            self.assertEqual(result.turn_start_index, 0)


if __name__ == "__main__":
    unittest.main()
