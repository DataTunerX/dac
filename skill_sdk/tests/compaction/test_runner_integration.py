"""Integration tests: SkillRunner.run with and without compaction."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skill_sdk.api.base import Skill
from skill_sdk.compaction.guard import CompactionGuard
from skill_sdk.compaction.settings import CompactionConfig, CompactionSettings
from skill_sdk.skill.runner import SkillRunner


def _skill() -> Skill:
    """Minimal skill fixture for runner tests."""
    return Skill(
        name="demo",
        description="demo skill",
        detail="demo detail for tests",
        version="0.0.1",
        base_dir="/tmp",
        scripts=[],
    )


def _big_messages() -> list[Any]:
    """Build a large message list suitable for prepare_compaction."""
    msgs: list[Any] = [SystemMessage(content="sys"), HumanMessage(content="hello")]
    for i in range(8):
        msgs.append(HumanMessage(content=("bulk " * 300) + str(i)))
        msgs.append(AIMessage(content=("reply " * 300) + str(i)))
        msgs.append(ToolMessage(content=("out " * 300) + str(i), tool_call_id=f"t{i}"))
    return msgs


class _BoundLLM:
    """Stand-in for ``llm.bind_tools(...)`` returning a controllable invoker."""

    def __init__(self, invoker: Any) -> None:
        self._invoker = invoker

    async def ainvoke(self, messages: Any, config: Any = None) -> Any:
        """Delegate to the injected invoker callable/awaitable."""
        if callable(self._invoker):
            result = self._invoker(messages)
            if hasattr(result, "__await__"):
                return await result
            return result
        return await self._invoker.ainvoke(messages, config=config)


class TestRunnerWithoutCompaction(unittest.IsolatedAsyncioTestCase):
    """Regression: compaction=None keeps legacy behavior."""

    async def test_completed_finish(self) -> None:
        """A normal finish tool call completes without compaction."""
        call_count = {"n": 0}

        def invoker(messages: Any) -> AIMessage:
            call_count["n"] += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": {"final_answer": "done"},
                        "id": "f1",
                        "type": "tool_call",
                    }
                ],
            )

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=_BoundLLM(invoker))

        runner = SkillRunner(llm=llm, max_steps=5, compaction=None, use_skill_search=False)
        with patch.object(runner, "_tools_for_skill", return_value=runner._runner_tools):
            result = await runner.run(
                "hello",
                _skill(),
                user_id="u",
                run_id="r",
                trace_id="a" * 32,
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final_answer"], "done")
        self.assertEqual(call_count["n"], 1)


class TestGuardOverflowIntegration(unittest.IsolatedAsyncioTestCase):
    """Overflow recovery against a large in-memory history."""

    async def test_overflow_retry_then_second_fails(self) -> None:
        """First overflow compacts; second overflow reports failed recovery."""
        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nRecover"))
        summarizer.bind = MagicMock(return_value=summarizer)

        config = CompactionConfig(
            context_window=50_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=1_000,
                keep_recent_tokens=200,
            ),
            summarizer_llm=summarizer,
        )
        guard = CompactionGuard(config, summarizer)
        big = _big_messages()
        exc = RuntimeError("prompt is too long: 999999 tokens > 1000 maximum")

        r1 = await guard.on_invoke_error(big, exc)
        self.assertIsNotNone(r1)
        assert r1 is not None
        self.assertTrue(r1.will_retry)
        self.assertFalse(r1.failed)
        self.assertIsNotNone(r1.messages)
        assert r1.messages is not None
        self.assertLess(len(r1.messages), len(big))

        r2 = await guard.on_invoke_error(r1.messages, exc)
        self.assertIsNotNone(r2)
        assert r2 is not None
        self.assertTrue(r2.failed)
        self.assertIn("compact-and-retry", r2.error_message)


class TestRunnerEndToEndOverflow(unittest.IsolatedAsyncioTestCase):
    """Full SkillRunner.run path with compaction overflow recovery."""

    async def test_runner_overflow_retry_then_finish(self) -> None:
        """Runner: first LLM call overflows, compact, second call finishes."""
        state = {"n": 0}

        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nRecover"))
        summarizer.bind = MagicMock(return_value=summarizer)

        def invoker(messages: Any) -> AIMessage:
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("prompt is too long: 999999 tokens > 1000 maximum")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": {"final_answer": "recovered"},
                        "id": "f1",
                        "type": "tool_call",
                    }
                ],
            )

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=_BoundLLM(invoker))

        config = CompactionConfig(
            context_window=50_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=1_000,
                keep_recent_tokens=200,
            ),
            summarizer_llm=summarizer,
        )
        runner = SkillRunner(llm=llm, max_steps=5, compaction=config, use_skill_search=False)
        template = runner._compaction_template
        assert template is not None
        real_new = template.new_run_guard

        def new_guard_with_seed() -> CompactionGuard:
            """Seed a large history on the first before_invoke so overflow can compact."""
            guard = real_new()
            real_before = guard.before_invoke

            async def before_invoke(messages: Any) -> list[Any]:
                msgs = list(messages)
                if len(msgs) < 10:
                    msgs.extend(_big_messages()[2:])  # skip duplicate system/human
                return await real_before(msgs)

            guard.before_invoke = before_invoke  # type: ignore[method-assign]
            return guard

        with (
            patch.object(runner, "_tools_for_skill", return_value=runner._runner_tools),
            patch.object(template, "new_run_guard", side_effect=new_guard_with_seed),
        ):
            result = await runner.run(
                "hello",
                _skill(),
                user_id="u",
                run_id="r",
                trace_id="c" * 32,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final_answer"], "recovered")
        self.assertGreaterEqual(state["n"], 2)
        self.assertTrue(
            any(isinstance(e, dict) and e.get("compaction") for e in result["tool_history"])
        )

    async def test_runner_overflow_twice_status(self) -> None:
        """Runner returns context_overflow when recovery cannot clear the error."""
        summarizer = AsyncMock()
        summarizer.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nx"))
        summarizer.bind = MagicMock(return_value=summarizer)

        def invoker(messages: Any) -> AIMessage:
            raise RuntimeError("exceeds the context window of this model")

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=_BoundLLM(invoker))

        config = CompactionConfig(
            context_window=50_000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=1_000,
                keep_recent_tokens=200,
            ),
            summarizer_llm=summarizer,
        )
        runner = SkillRunner(llm=llm, max_steps=3, compaction=config, use_skill_search=False)
        template = runner._compaction_template
        assert template is not None
        real_new = template.new_run_guard

        def new_guard_with_seed() -> CompactionGuard:
            guard = real_new()
            real_before = guard.before_invoke

            async def before_invoke(messages: Any) -> list[Any]:
                msgs = list(messages)
                if len(msgs) < 10:
                    msgs.extend(_big_messages()[2:])
                return await real_before(msgs)

            guard.before_invoke = before_invoke  # type: ignore[method-assign]
            return guard

        with (
            patch.object(runner, "_tools_for_skill", return_value=runner._runner_tools),
            patch.object(template, "new_run_guard", side_effect=new_guard_with_seed),
        ):
            result = await runner.run(
                "hello",
                _skill(),
                user_id="u",
                run_id="r",
                trace_id="d" * 32,
            )

        self.assertEqual(result["status"], "context_overflow")
        self.assertIn("compact-and-retry", result["final_answer"])


class TestSkillConstructor(unittest.TestCase):
    """Skill model construction sanity for fixtures."""

    def test_skill_fields(self) -> None:
        """Skill fixture exposes expected attributes."""
        s = _skill()
        self.assertEqual(s.name, "demo")


if __name__ == "__main__":
    unittest.main()
