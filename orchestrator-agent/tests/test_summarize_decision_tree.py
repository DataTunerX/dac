"""SG collaborative summary decision tree: initiator LLM vs delegatee passthrough.

Mirrors skill-agent ``test_summarize_decision_tree.py`` Rule 2 / Rule 3.

Run::

    cd dac/orchestrator-agent
    python -m pytest tests/test_summarize_decision_tree.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent.orchestrator_agent_semantic_group import (  # noqa: E402
    DEPENDENT_TASK_SKIP_DESCRIPTION,
    DEPENDENT_TASK_SKIP_MARKER,
    NONE_TASK_UNASSIGNED_RESULT,
    OrchestratorAgent,
    OrchestratorAgentExecutorSemanticGroup,
    _build_summary_passthrough,
    _collab_summary_ef_tasks,
    _is_summary_placeholder,
)


def _executor() -> OrchestratorAgentExecutorSemanticGroup:
    ex = object.__new__(OrchestratorAgentExecutorSemanticGroup)
    ex.agent_card = MagicMock()
    ex.agent_card.name = "UserAccountPaymentAgent-sg-7decc9db"
    ex.agent_id = "UserAccountPaymentAgent-sg-7decc9db"
    ex.semantic_group_id = "user-account"
    mock_resp = MagicMock()
    mock_resp.content = "LLM_SHOULD_NOT_RUN"
    ex.llm = MagicMock()
    ex.llm.ainvoke = AsyncMock(return_value=mock_resp)
    return ex


def _run_summarize(
    ex: OrchestratorAgentExecutorSemanticGroup,
    **kwargs,
) -> str:
    async def _go():
        with patch(
            "orchestrator_agent.orchestrator_agent_semantic_group.langfuse"
        ) as mock_lf:
            span = MagicMock()
            span.__enter__ = MagicMock(return_value=span)
            span.__exit__ = MagicMock(return_value=False)
            mock_lf.start_as_current_span.return_value = span
            with patch(
                "orchestrator_agent.orchestrator_agent_semantic_group.safe_langfuse_flush",
                AsyncMock(),
            ):
                return await ex._summarize_delegated_result(
                    query=kwargs.get("query", "根据用户ID查询用户详情"),
                    own_results=kwargs.get("own_results", {1: "用户ID=U001 用户名=zhangsan"}),
                    delegated_results=kwargs.get("delegated_results", {}),
                    upstream_context=kwargs.get("upstream_context", {}),
                    execution_flow_tasks=kwargs.get("execution_flow_tasks"),
                    agent_role=kwargs.get("agent_role", ""),
                )

    return asyncio.run(_go())


class TestBuildSummaryPassthrough:
    def test_joins_own_and_delegate_without_task_prefix(self):
        text = _build_summary_passthrough(
            {1: "订单用户ID为 U001"},
            {"user-agent": "张三=U001 邮箱=zhangsan@example.com"},
        )
        assert text == (
            "订单用户ID为 U001\n\n张三=U001 邮箱=zhangsan@example.com"
        )
        assert "[Task#" not in text

    def test_preserves_own_task_order(self):
        text = _build_summary_passthrough(
            {1: "first", 3: "third", 2: "second"},
            {},
        )
        # dict insertion order (plan emit order), not sorted by task id
        assert text == "first\n\nthird\n\nsecond"

    def test_drops_none_and_skip_placeholders(self):
        text = _build_summary_passthrough(
            {1: NONE_TASK_UNASSIGNED_RESULT, 2: "有效本层结果"},
            {"peer": DEPENDENT_TASK_SKIP_DESCRIPTION, "ok": "下游有效结果"},
        )
        assert text == "有效本层结果\n\n下游有效结果"
        assert NONE_TASK_UNASSIGNED_RESULT not in text
        assert DEPENDENT_TASK_SKIP_DESCRIPTION not in text

    def test_drops_skip_marker_prefix_variants(self):
        custom = DEPENDENT_TASK_SKIP_MARKER + "上游没有 user_id，跳过用户查询"
        assert _is_summary_placeholder(custom) is True
        text = _build_summary_passthrough(
            {1: custom, 2: "支付成功 99.00"},
            {"user": custom},
        )
        assert text == "支付成功 99.00"
        assert DEPENDENT_TASK_SKIP_MARKER not in text

    def test_empty_results(self):
        assert _build_summary_passthrough({}, {}) == ""
        assert _build_summary_passthrough(None, None) == ""


class TestSummarizeDecisionTree:
    def test_delegatee_own_only_passthrough_skips_llm(self):
        ex = _executor()
        own = {1: "[user-agent] 张三对应的用户ID为 U001"}
        result = _run_summarize(ex, own_results=own, agent_role="delegatee")
        assert result == own[1]
        ex.llm.ainvoke.assert_not_called()

    def test_delegatee_with_further_delegation_still_passthrough(self):
        ex = _executor()
        result = _run_summarize(
            ex,
            own_results={1: "[user-agent] 张三 U001"},
            delegated_results={"order-agent": "[order-agent] U001 买了 iPhone"},
            agent_role="delegatee",
        )
        assert "[user-agent] 张三 U001" in result
        assert "[order-agent] U001 买了 iPhone" in result
        ex.llm.ainvoke.assert_not_called()

    def test_cycle_original_receiver_as_delegatee_passthrough(self):
        """A was the query receiver, but this hop is A as delegatee (A→B→A)."""
        ex = _executor()
        ex.agent_card.name = "EcommerceOnlineTransactionAgent-sg-il324o25"
        result = _run_summarize(
            ex,
            query="查询订单和用户",
            own_results={1: "补充查询订单数据 ORD-2025-00001"},
            agent_role="delegatee",
        )
        assert result == "补充查询订单数据 ORD-2025-00001"
        ex.llm.ainvoke.assert_not_called()

    def test_initiator_calls_llm(self):
        ex = _executor()
        ex.llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="张三购买了订单 ORD-2025-00001")
        )
        result = _run_summarize(
            ex,
            query="张三买了什么",
            own_results={1: "订单用户ID=U001"},
            delegated_results={"user-agent": "U001=张三"},
            agent_role="initiator",
        )
        assert result == "张三购买了订单 ORD-2025-00001"
        ex.llm.ainvoke.assert_called_once()

    def test_default_role_is_initiator_and_calls_llm(self):
        ex = _executor()
        ex.llm.ainvoke = AsyncMock(return_value=MagicMock(content="LLM_OK"))
        result = _run_summarize(ex, agent_role="")
        assert result == "LLM_OK"
        ex.llm.ainvoke.assert_called_once()

    def test_delegatee_placeholder_only_returns_empty_without_llm(self):
        ex = _executor()
        result = _run_summarize(
            ex,
            own_results={1: NONE_TASK_UNASSIGNED_RESULT},
            delegated_results={
                "peer": DEPENDENT_TASK_SKIP_MARKER + "无关联键",
            },
            agent_role="delegatee",
        )
        assert result == ""
        ex.llm.ainvoke.assert_not_called()

    def test_delegatee_mixed_placeholders_keeps_facts_only(self):
        ex = _executor()
        result = _run_summarize(
            ex,
            own_results={
                1: "user_id=U001 username=zhangsan",
                2: DEPENDENT_TASK_SKIP_DESCRIPTION,
            },
            delegated_results={},
            agent_role="delegatee",
        )
        assert result == "user_id=U001 username=zhangsan"
        ex.llm.ainvoke.assert_not_called()


class TestCollabSummaryEfTasks:
    def test_initiator_emits_turn_summary_and_final_answer(self):
        tasks = _collab_summary_ef_tasks(
            sg_label="EcommerceOnlineTransactionAgent-sg-il324o25",
            is_delegated=False,
            summary="综合答案",
            run_id="r1",
        )
        assert [t.stage for t in tasks] == ["turn_summary", "final_answer"]
        assert all(t.role == "initiator" for t in tasks)
        assert tasks[1].result == "综合答案"
        assert tasks[1].execution_id.endswith(
            "EcommerceOnlineTransactionAgent-sg-il324o25"
        )

    def test_delegatee_skips_final_answer_and_uses_delegatee_role(self):
        tasks = _collab_summary_ef_tasks(
            sg_label="UserAccountPaymentAgent-sg-7decc9db",
            is_delegated=True,
            summary="用户ID=U001 用户名=zhangsan",
        )
        assert [t.stage for t in tasks] == ["turn_summary"]
        assert tasks[0].role == "delegatee"
        assert tasks[0].result == "success"
        assert all(t.stage != "final_answer" for t in tasks)


class TestCollabPassthroughProgress:
    def test_allowlist_keeps_count_extras(self):
        frame = OrchestratorAgent.build_progress_frame(
            "collab_passthrough",
            message="Delegatee passthrough: 1 own + 0 delegated",
            extra={
                "own_result_count": 1,
                "delegated_result_count": 0,
                "not_allowed": "drop-me",
            },
        )
        assert "[[DAC_PROGRESS]]" in frame
        assert "collab_passthrough" in frame
        assert "own_result_count" in frame
        assert "not_allowed" not in frame


@pytest.mark.asyncio
async def test_delegatee_passthrough_is_async_safe():
    ex = _executor()
    result = await ex._summarize_delegated_result(
        query="查用户",
        own_results={1: "raw user row"},
        delegated_results={},
        upstream_context={},
        agent_role="delegatee",
    )
    assert result == "raw user row"
    ex.llm.ainvoke.assert_not_called()
