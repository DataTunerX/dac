"""Unit tests for SG collaborative summary prompt builders.

Mirrors skill-agent: Execution Flow is the single source of truth;
``upstream_context`` JSON must not appear in the human prompt.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent.orchestrator_agent_semantic_group import (  # noqa: E402
    OrchestratorAgentExecutorSemanticGroup,
    _build_summarize_delegated_prompt,
)

_ZHANGSAN_FAIL = (
    '无法直接通过用户名"张三"查询订单，订单数据只有用户ID，不包含用户姓名。'
)

_ZHANGSAN_EF = [
    {
        "execution_id": "own-1-order-agent-t1",
        "turn": 1,
        "stage": "pre_exec",
        "agent": "order-agent",
        "role": "initiator",
        "task": "查询用户张三购买的商品，按用户名'张三'进行过滤",
        "result": _ZHANGSAN_FAIL,
        "reason": "订单数据只有用户ID，无法按姓名查询",
        "parent_execution_id": None,
        "delegated_by": None,
        "run_id": "ut-run",
        "trace_id": "",
        "user_id": "ut",
    }
]


class TestBuildSummarizeDelegatedPrompt:
    def test_uses_execution_flow_not_json_dump(self):
        system, human = _build_summarize_delegated_prompt(
            "张三买了哪些东西",
            execution_flow_tasks=_ZHANGSAN_EF,
            task_results={1: _ZHANGSAN_FAIL},
            delegate_results={},
            current_agent="order-agent",
        )
        assert "不要自我介绍" in system
        assert "## 执行流水账" in human
        assert "原始问题：张三买了哪些东西" in human
        assert "请直接输出答案" in human
        assert "上游传入上下文" not in human
        assert "executed_tasks" not in human
        assert "本层自身执行结果" not in human
        assert "委托给下游 SG" not in human
        assert human.count(_ZHANGSAN_FAIL) == 1

    def test_fallback_without_execution_flow(self):
        _, human = _build_summarize_delegated_prompt(
            "查询销售总额",
            execution_flow_tasks=None,
            task_results={1: "2024年1月销售总额为123456元。"},
            delegate_results={"user-agent": "张三=U001"},
        )
        assert "## 执行流水账" not in human
        assert "## 本层执行结果" in human
        assert "## 下游返回结果" in human
        assert "123456" in human
        assert "U001" in human
        assert "上游传入上下文" not in human

    def test_empty_results_placeholder(self):
        _, human = _build_summarize_delegated_prompt(
            "任意问题",
            execution_flow_tasks=[],
            task_results={},
            delegate_results={},
        )
        assert "暂无执行结果" in human
        assert "上游传入上下文" not in human

    def test_prompt_build_logs_single_line_box(self):
        import logging
        from orchestrator_agent import orchestrator_agent_semantic_group as sg_mod

        records: list[str] = []

        class _H(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        log = sg_mod.logger
        prev_level = log.level
        handler = _H()
        handler.setLevel(logging.INFO)
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            _build_summarize_delegated_prompt(
                "张三买了哪些东西",
                execution_flow_tasks=_ZHANGSAN_EF,
                current_agent="order-agent",
                agent_role="initiator",
            )
        finally:
            log.removeHandler(handler)
            log.setLevel(prev_level)
        text = "\n".join(records)
        assert "[SummaryPrompt] sg-summarize" in text
        assert "┌─" in text
        assert "├─ human prompt" in text
        assert "└─" in text
        assert "═" not in text
        assert "agent=order-agent" in text
        assert "## 执行流水账" in text


class TestResolveExecutionFlowForSummary:
    def test_prefers_explicit_ef(self):
        ex = object.__new__(OrchestratorAgentExecutorSemanticGroup)
        got = ex._resolve_execution_flow_for_summary(
            [{"execution_id": "a"}],
            {"execution_flow": [{"execution_id": "b"}]},
        )
        assert got == [{"execution_id": "a"}]

    def test_falls_back_to_upstream_context(self):
        ex = object.__new__(OrchestratorAgentExecutorSemanticGroup)
        got = ex._resolve_execution_flow_for_summary(
            None,
            {"execution_flow": [{"execution_id": "b"}]},
        )
        assert got == [{"execution_id": "b"}]


def test_summarize_delegated_result_sends_ef_messages_not_json():
    ex = object.__new__(OrchestratorAgentExecutorSemanticGroup)
    ex.agent_card = MagicMock()
    ex.agent_card.name = "order-agent"
    ex.agent_id = "order-agent"
    ex.semantic_group_id = "order"
    mock_resp = MagicMock()
    mock_resp.content = "张三无法按姓名查询。"
    ex.llm = MagicMock()
    ex.llm.ainvoke = AsyncMock(return_value=mock_resp)

    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)

    async def _run():
        with patch(
            "orchestrator_agent.orchestrator_agent_semantic_group.langfuse"
        ) as mock_lf:
            mock_lf.start_as_current_span.return_value = span
            with patch(
                "orchestrator_agent.orchestrator_agent_semantic_group.safe_langfuse_flush",
                AsyncMock(),
            ):
                return await ex._summarize_delegated_result(
                    query="张三买了哪些东西",
                    own_results={1: _ZHANGSAN_FAIL},
                    delegated_results={},
                    upstream_context={
                        "executed_tasks": [{"task_id": 1, "result": _ZHANGSAN_FAIL}],
                        "execution_flow": _ZHANGSAN_EF,
                    },
                    execution_flow_tasks=_ZHANGSAN_EF,
                )

    answer = asyncio.run(_run())

    assert answer == "张三无法按姓名查询。"
    messages = ex.llm.ainvoke.await_args.args[0]
    assert len(messages) == 2
    human = messages[1].content
    assert "## 执行流水账" in human
    assert "上游传入上下文" not in human
    assert "executed_tasks" not in human
    assert human.count(_ZHANGSAN_FAIL) == 1
