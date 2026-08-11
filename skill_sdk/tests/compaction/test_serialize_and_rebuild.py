"""Unit tests for serialization, file ops, and rebuild."""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skill_sdk.compaction.file_ops import (
    compute_file_lists,
    extract_file_ops_from_messages,
    format_file_operations,
)
from skill_sdk.compaction.messages import (
    COMPACTION_SUMMARY_PREFIX,
    is_compaction_summary_message,
    make_compaction_summary_message,
)
from skill_sdk.compaction.prepare import rebuild_messages
from skill_sdk.compaction.serialize import TOOL_RESULT_MAX_CHARS, serialize_conversation, truncate_for_summary


class TestSerialize(unittest.TestCase):
    """Conversation flattening for summarizer prompts."""

    def test_labels_and_tool_truncation(self) -> None:
        """Tool results longer than the cap are truncated with a marker."""
        huge = "Z" * (TOOL_RESULT_MAX_CHARS + 500)
        text = serialize_conversation(
            [
                HumanMessage(content="hello"),
                AIMessage(
                    content="calling",
                    tool_calls=[{"name": "grep", "args": {"path": "a.py"}, "id": "1", "type": "tool_call"}],
                ),
                ToolMessage(content=huge, tool_call_id="1"),
            ]
        )
        self.assertIn("[User]: hello", text)
        self.assertIn("[Assistant tool calls]:", text)
        self.assertIn("[Tool result]:", text)
        self.assertIn("more characters truncated", text)

    def test_truncate_helper(self) -> None:
        """truncate_for_summary keeps a prefix and marks the remainder."""
        out = truncate_for_summary("abcdef", max_chars=3)
        self.assertTrue(out.startswith("abc"))
        self.assertIn("truncated", out)


class TestFileOps(unittest.TestCase):
    """skill_sdk tool-name mapping into read/modified lists."""

    def test_readline_and_grep(self) -> None:
        """readline_in_range and grep paths land in readFiles."""
        msgs = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "readline_in_range",
                        "args": {"file_path": "/tmp/a.py"},
                        "id": "1",
                        "type": "tool_call",
                    },
                    {"name": "grep", "args": {"path": "/tmp/b.py"}, "id": "2", "type": "tool_call"},
                ],
            )
        ]
        ops = extract_file_ops_from_messages(msgs)
        read_files, modified = compute_file_lists(ops)
        self.assertIn("/tmp/a.py", read_files)
        self.assertIn("/tmp/b.py", read_files)
        self.assertEqual(modified, [])

    def test_format_tags(self) -> None:
        """File lists render as XML-ish tags."""
        blob = format_file_operations(["a.py"], ["b.py"])
        self.assertIn("<read-files>", blob)
        self.assertIn("a.py", blob)
        self.assertIn("<modified-files>", blob)
        self.assertIn("b.py", blob)


class TestRebuild(unittest.TestCase):
    """Message list rebuild after compaction."""

    def test_system_summary_kept(self) -> None:
        """Rebuilt context is system + summary human + kept tail."""
        system = [SystemMessage(content="sys")]
        kept = [HumanMessage(content="recent"), AIMessage(content="ok")]
        out = rebuild_messages(system, "## Goal\ntest", kept)
        self.assertIsInstance(out[0], SystemMessage)
        self.assertTrue(is_compaction_summary_message(out[1]))
        self.assertIn(COMPACTION_SUMMARY_PREFIX, str(out[1].content))
        self.assertEqual(out[2:], kept)

    def test_make_summary_message_marker(self) -> None:
        """Injected summary carries the compaction marker kwargs."""
        msg = make_compaction_summary_message("## Goal\nx")
        self.assertTrue(is_compaction_summary_message(msg))


if __name__ == "__main__":
    unittest.main()
