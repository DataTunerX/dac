"""Functional tests for CompactionGuard threshold and overflow recovery."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skill_sdk.compaction.guard import CompactionGuard
from skill_sdk.compaction.settings import CompactionConfig, CompactionSettings


def _big_dialog(n_turns: int = 8, chunk: str = "WORD ") -> list:
    """Build a large dialog that exceeds a tiny keep/reserve budget."""
    msgs: list = [SystemMessage(content="system prompt")]
    for i in range(n_turns):
        msgs.append(HumanMessage(content=f"user turn {i} " + chunk * 400))
        msgs.append(
            AIMessage(
                content=f"assistant turn {i} " + chunk * 400,
                tool_calls=[
                    {
                        "name": "readline_in_range",
                        "args": {"file_path": f"/tmp/f{i}.py"},
                        "id": f"c{i}",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 5000 + i * 2000,
                    "output_tokens": 100,
                    "total_tokens": 5100 + i * 2000,
                },
            )
        )
        msgs.append(ToolMessage(content=("result " + chunk) * 300, tool_call_id=f"c{i}"))
    return msgs


class TestGuardThreshold(unittest.IsolatedAsyncioTestCase):
    """Proactive compaction when usage crosses the threshold."""

    async def test_before_invoke_compacts(self) -> None:
        """Threshold hit rewrites messages to include a summary human message."""
        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(
            return_value=AIMessage(content="## Goal\nShrink context\n\n## Next Steps\n1. Continue")
        )
        # Some models expose bind(); make it return self.
        summarizer.bind = MagicMock(return_value=summarizer)

        config = CompactionConfig(
            context_window=20_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=5_000,
                keep_recent_tokens=800,
            ),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        messages = _big_dialog()
        # Last AI usage is large enough to exceed window - reserve.
        out = await guard.before_invoke(messages)
        self.assertLess(len(out), len(messages))
        from skill_sdk.compaction.messages import is_compaction_summary_message

        self.assertTrue(any(is_compaction_summary_message(m) for m in out))
        self.assertTrue(isinstance(out[0], SystemMessage))
        summarizer.ainvoke.assert_awaited()
        self.assertTrue(guard.boundaries)

    async def test_disabled_noop(self) -> None:
        """Disabled settings leave messages unchanged."""
        summarizer = AsyncMock()
        config = CompactionConfig(
            context_window=100,
            settings=CompactionSettings(enabled=False, reserve_tokens=10, keep_recent_tokens=10),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        messages = [SystemMessage(content="s"), HumanMessage(content="q")]
        out = await guard.before_invoke(messages)
        self.assertEqual(len(out), len(messages))
        summarizer.ainvoke.assert_not_called()


class TestGuardOverflow(unittest.IsolatedAsyncioTestCase):
    """Error overflow compact-and-retry once."""

    async def test_overflow_retry_once(self) -> None:
        """First overflow compacts and requests retry; second fails."""
        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nRecovered"))
        summarizer.bind = MagicMock(return_value=summarizer)

        config = CompactionConfig(
            context_window=8_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=2_000,
                keep_recent_tokens=500,
            ),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        messages = _big_dialog(n_turns=6)

        exc = RuntimeError("This model's maximum context length is 8000 tokens")
        recovery = await guard.on_invoke_error(messages, exc)
        self.assertIsNotNone(recovery)
        assert recovery is not None
        self.assertTrue(recovery.will_retry)
        self.assertFalse(recovery.failed)
        self.assertIsNotNone(recovery.messages)

        recovery2 = await guard.on_invoke_error(recovery.messages or messages, exc)
        self.assertIsNotNone(recovery2)
        assert recovery2 is not None
        self.assertTrue(recovery2.failed)
        self.assertIn("one compact-and-retry", recovery2.error_message)

    async def test_non_overflow_returns_none(self) -> None:
        """Unrelated errors must not be swallowed."""
        summarizer = AsyncMock()
        config = CompactionConfig(
            context_window=8_000,
            settings=CompactionSettings(enabled=True),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        recovery = await guard.on_invoke_error(
            [HumanMessage(content="q")],
            RuntimeError("connection reset by peer"),
        )
        self.assertIsNone(recovery)

    async def test_silent_overflow_after_invoke(self) -> None:
        """Silent success over window compacts without retry."""
        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nSilent"))
        summarizer.bind = MagicMock(return_value=summarizer)

        config = CompactionConfig(
            context_window=1_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=200,
                keep_recent_tokens=200,
            ),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        messages = _big_dialog(n_turns=4)
        ai = AIMessage(
            content="final",
            usage_metadata={"input_tokens": 5000, "output_tokens": 20, "total_tokens": 5020},
            response_metadata={"finish_reason": "stop"},
        )
        action = await guard.after_invoke(messages, ai)
        self.assertTrue(action.compacted)
        self.assertFalse(action.will_retry)
        self.assertIsNotNone(action.messages)


class TestGuardHook(unittest.IsolatedAsyncioTestCase):
    """on_before_compact can cancel or supply a custom summary."""

    async def test_cancel_hook(self) -> None:
        """Returning cancel leaves messages unchanged and skips summarizer."""
        summarizer = AsyncMock()
        summarizer.bind = MagicMock(return_value=summarizer)

        async def cancel_hook(**kwargs: Any) -> dict[str, Any]:
            return {"cancel": True}

        config = CompactionConfig(
            context_window=20_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=5_000,
                keep_recent_tokens=800,
            ),
            summarizer_llm=summarizer,
            on_before_compact=cancel_hook,
        )
        guard = CompactionGuard(config, summarizer)
        messages = _big_dialog()
        out = await guard.before_invoke(messages)
        self.assertEqual(len(out), len(messages))
        summarizer.ainvoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
