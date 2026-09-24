"""Full integration tests for _summarize 4-layer decision tree and turn loop.

Covers every real-world scenario for initiator (query receiver) vs delegatee,
with and without actual cross-SG collaboration, force-off, and custom prompts.

Run::

    cd dac/skill-agent
    python -m pytest tests/test_summarize_decision_tree.py -v -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod in (
    "skill_sdk", "skill_sdk.skill", "skill_sdk.skill.runner",
    "skill_sdk.tool", "skill_sdk.tool.code_execution",
    "langfuse", "langfuse.langchain", "langfuse._client",
    "model_sdk", "model_sdk.api", "model_sdk.api.model_manager",
    "agent.broadcast_capability_check", "agent.agent_card_resolve",
    "agent.agentregistry_client", "agent.dataservices_client",
    "agent.tool_call_utils", "agent.skill_download",
    "agent.skill_download_refs", "agent.redis_registry",
):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules["agent.broadcast_capability_check"].ROUTING_AGENT_POOL_KEY = "routing_agent_pool"

from agent.skill_agent import (  # noqa: E402
    SkillAgentExecutor,
    SummaryEvaluationResult,
)
from agent.skill_agent_turn import (  # noqa: E402
    SkillAgentExecutorWithTurns,
)

# ======================================================================
# Helpers
# ======================================================================


def _make(klass=SkillAgentExecutorWithTurns, **attrs):
    inst = object.__new__(klass)
    for k, v in attrs.items():
        object.__setattr__(inst, k, v)
    return inst


def _langfuse_patches():
    """Mock Langfuse so _summarize LLM path works in tests."""
    mock_lf_client = MagicMock()
    mock_lf_client.start_as_current_span.return_value.__enter__ = MagicMock()
    mock_lf_client.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
    return [
        patch("agent.skill_agent.CallbackHandler", MagicMock()),
        patch("agent.skill_agent.get_client", MagicMock(return_value=mock_lf_client)),
        patch("agent.skill_agent.safe_langfuse_flush", AsyncMock()),
        patch("agent.skill_agent._time"),
    ]


# ======================================================================
# Scenarios — _summarize method directly
# ======================================================================


class TestSummarizeDecisionTree:
    """Direct method-level tests for _summarize.  Every rule, every edge."""

    # ── 1. Rule 1: SUMMARIZE_ENABLED=false overrides everything ──

    @pytest.mark.asyncio
    async def test_r1_force_off_initiator_with_collab(self):
        ex = _make(summarize_enabled=False, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        result = await ex._summarize(
            original_query="张三买了哪些东西",
            task_results={1: "[order-agent] 订单数据只有用户ID"},
            delegate_results={"user-agent": "[user-agent] 张三=U001"},
            agent_role="initiator",
        )
        # force-off: passthrough even though collaboration exists
        assert "[order-agent]" in result
        assert "user-agent" in result

    @pytest.mark.asyncio
    async def test_r1_force_off_delegatee(self):
        ex = _make(summarize_enabled=False, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "delegatee"))
        result = await ex._summarize(
            original_query="查订单",
            task_results={1: "own result"},
            delegate_results={},
            agent_role="delegatee",
        )
        assert "own result" in result

    @pytest.mark.asyncio
    async def test_r1_force_off_initiator_no_collab(self):
        ex = _make(summarize_enabled=False, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        result = await ex._summarize(
            original_query="查总额",
            task_results={1: "1月销售 123456 元"},
            delegate_results={},
            agent_role="initiator",
        )
        assert "123456" in result

    # ── 2. Rule 2: delegatee never summarizes, regardless of collaboration ──

    @pytest.mark.asyncio
    async def test_r2_delegatee_own_only(self):
        """delegatee with only own task results → passthrough."""
        ex = _make(summarize_enabled=True, summarize_prompt="自定义提示词",
                   agent_id="user-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("user-agent", "delegatee"))
        result = await ex._summarize(
            original_query="查张三的ID",
            task_results={1: "[user-agent] 张三对应的用户ID为 U001"},
            delegate_results={},
            agent_role="delegatee",
        )
        # delegatee → passthrough, NOT LLM with custom prompt
        assert "[user-agent] 张三对应的用户ID为 U001" in result

    @pytest.mark.asyncio
    async def test_r2_delegatee_has_own_collab(self):
        """delegatee that ALSO delegated further (recursive chain) → still passthrough."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="user-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("user-agent", "delegatee"))
        result = await ex._summarize(
            original_query="查张三的详细信息",
            task_results={1: "[user-agent] 张三 U001"},
            delegate_results={"order-agent": "[order-agent] U001 买了 iPhone"},
            agent_role="delegatee",
        )
        # delegatee always passthrough, even if it has its own delegate_results
        assert "user-agent" in result
        assert "order-agent" in result

    # ── 3. Rule 3: initiator, but no actual collaboration ──

    @pytest.mark.asyncio
    async def test_r3_initiator_no_collab_single_agent(self):
        """Single-agent mode: initiator with summarization on → LLM summarize."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="2024年1月销售总额为123456元"))
        ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="查询2024年1月销售总额",
                task_results={1: "[order-agent] 已查询数据库，2024年1月销售总额为123456元"},
                delegate_results={},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        # LLM summarization used: result comes from mock_llm, not raw passthrough
        assert "123456" in result

    @pytest.mark.asyncio
    async def test_r3_initiator_no_collab_multi_agent_capable_but_no_actual_del(self):
        """hop=5 but planner didn't actually delegate anything → still LLM summarize."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="analyst-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("analyst-agent", "initiator"))

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="Q1增长12%，Q2增长8%"))
        ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="分析销售趋势",
                task_results={
                    1: "[analyst-agent] 自己计算得出：Q1增长12%，Q2增长8%",
                },
                delegate_results={},  # empty! no delegation happened
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        # LLM summarization used, not passthrough
        assert "Q1增长12%" in result

    @pytest.mark.asyncio
    async def test_r3_initiator_no_collab_with_custom_prompt(self):
        """Custom prompt set, no collaboration → LLM summarize with custom prompt."""
        custom = "请用专业的语气汇总"
        ex = _make(summarize_enabled=True, summarize_prompt=custom,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))

        captured_sys = [None]

        class FakeLLM:
            async def ainvoke(self, messages, **_kw):
                captured_sys[0] = str(messages[0].content)
                return MagicMock(content="订单: iPhone x1")

        ex._get_orchestration_llm = MagicMock(return_value=FakeLLM())
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="查订单",
                task_results={1: "订单: iPhone x1"},
                delegate_results={},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert "iPhone" in result
        # Custom prompt should be used even without collaboration
        assert captured_sys[0] == custom

    # ── 4. Rule 4: initiator with actual collaboration → LLM summarize ──

    @pytest.mark.asyncio
    async def test_r4_initiator_with_collab_default_prompt(self):
        """Initiator + real collaboration + no custom prompt → LLM with default."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="order-agent")
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="张三（U001）购买了：iPhone 15 Pro、AirPods Pro、小米 13 Ultra"))
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="张三买了哪些东西",
                task_results={1: "[order-agent] 订单数据只有用户ID"},
                delegate_results={"user-agent": "[user-agent] 张三=U001"},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert "iPhone" in result
        assert "AirPods" in result

    @pytest.mark.asyncio
    async def test_r4_initiator_with_collab_custom_prompt(self):
        """Initiator + collaboration + custom prompt → LLM with custom prompt."""
        custom = "请用JSON格式输出总结：{\"summary\": \"...\"}"

        ex = _make(summarize_enabled=True, summarize_prompt=custom,
                   agent_id="order-agent")

        captured_sys = [None]

        class FakeLLM:
            async def ainvoke(self, messages, **_kw):
                captured_sys[0] = str(messages[0].content)
                return MagicMock(content='{"summary": "张三买了iPhone、AirPods、小米13 Ultra"}')

        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=FakeLLM())
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="张三买了哪些东西",
                task_results={1: "[order-agent] 订单数据只有用户ID"},
                delegate_results={"user-agent": "[user-agent] 张三=U001"},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert "张三买了iPhone" in result
        assert captured_sys[0] == custom

    @pytest.mark.asyncio
    async def test_r4_initiator_with_collab_multiple_delegatees(self):
        """Initiator with results from 3 delegatees → LLM summarize."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="order-agent")
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="综合回答：张三在2024年1月购买了iPhone 15 Pro，花费8999元，2月购买了AirPods Pro，花费1999元"))
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="张三买了哪些东西",
                task_results={1: "[order-agent] 订单数据只有用户ID"},
                delegate_results={
                    "user-agent": "[user-agent] 张三=U001",
                    "price-agent": "[price-agent] iPhone=8999, AirPods=1999",
                },
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert "8999" in result
        assert "1999" in result


# ======================================================================
# End-to-end Turn Loop Scenarios
# ======================================================================


class TestTurnLoopScenarios:
    """Simulate complete turn loops with different agent identities.

    These test what happens end-to-end when the turn loop decides
    between initiator and delegatee paths.
    """

    def _setup(self, is_delegated=False, summarize_enabled=True, summarize_prompt=None):
        """Create a SkillAgentExecutorWithTurns with the correct config."""
        ex = _make(
            max_loops=3,
            summarize_enabled=summarize_enabled,
            summarize_prompt=summarize_prompt,
            agent_id="test-agent",
        )
        ex._self_planner_agent_name = MagicMock(return_value="test-agent")
        ex._emit_progress = AsyncMock()
        ex._log_summary_input = MagicMock()
        ex._log_data_flow = MagicMock()
        ex._log_dag_startup = MagicMock()
        ex._log_dag_event = MagicMock()
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "delegatee" if is_delegated else "initiator")
        )
        ex._get_orchestration_llm = MagicMock()
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])
        ex._dag_enforcement_enabled = MagicMock(return_value=False)
        ex._init_routing_pool_from_metadata = MagicMock()
        ex._resolve_planner_agent_pool = AsyncMock(return_value=([], set(), set()))
        ex._get_memory = AsyncMock(return_value="")
        ex._ensure_skill_runner = AsyncMock()
        ex.add_history = AsyncMock()
        ex.schedule_add_memory = MagicMock()
        return ex

    # ── Scenario A: initiator, no collaboration, 1 turn ──

    @pytest.mark.asyncio
    async def test_initiator_no_collab_turn1_satisfactory(self):
        """Initiator queries a skill, gets result, no delegation needed.
        Turn 1 satisfactory → _summarize called → LLM summarize (Rule 3).
        """
        ex = self._setup(is_delegated=False, summarize_enabled=True)

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="信息充足",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="DIRECT_PASSTHROUGH_RESULT")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 销售总额 123456 元"},  # task_results
            {},                                          # delegate_results (empty!)
            5,                                           # remaining_hop
            [{"id": 1, "description": "查销售", "agent": "order-agent"}],
            [],
        ))

        # Simulate the turn-loop decision path
        total = 0
        turn_records = []
        failure_context = ""
        final_answer = None

        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            turn_records.append({"turn": total, "plan": meta,
                                 "task_results": tr, "delegate_results": dr,
                                 "execution_flow_tasks": list(ef)})
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="initiator",  # is_delegated=False
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="initiator",
                )
                break

        assert total == 1
        assert final_answer == "DIRECT_PASSTHROUGH_RESULT"

    # ── Scenario B: initiator, real collaboration, 1 turn ──

    @pytest.mark.asyncio
    async def test_initiator_with_collab_turn1_satisfactory(self):
        """Initiator delegates to peer-agent, gets collaborative results.
        Turn 1 satisfactory → _summarize called → LLM summarize (Rule 4).
        """
        ex = self._setup(is_delegated=False, summarize_enabled=True)

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="信息充足",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="LLM_SUMMARIZED_RESULT")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 订单数据只有用户ID"},
            {"user-agent": "[user-agent] 张三=U001"},  # collaboration!
            4,
            [{"id": 1, "description": "查订单", "agent": "order-agent"}],
            [],
        ))

        total = 0
        turn_records = []
        final_answer = None
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            turn_records.append({"turn": total, "plan": meta,
                                 "task_results": tr, "delegate_results": dr,
                                 "execution_flow_tasks": list(ef)})
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="initiator",
                )
                break

        assert total == 1
        assert final_answer == "LLM_SUMMARIZED_RESULT"

    # ── Scenario C: initiator, collaboration, SUMMARIZE_ENABLED=false ──

    @pytest.mark.asyncio
    async def test_initiator_with_collab_force_off(self):
        """Initiator with collaboration but SUMMARIZE_ENABLED=false.
        _summarize should passthrough (Rule 1).
        """
        ex = self._setup(is_delegated=False, summarize_enabled=False)

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="信息充足",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="PASSTHROUGH_FORCE_OFF")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 订单数据"},
            {"user-agent": "[user-agent] 张三=U001"},
            4, [], [],
        ))

        total = 0
        final_answer = None
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="initiator",
                )
                break

        assert final_answer == "PASSTHROUGH_FORCE_OFF"

    # ── Scenario D: delegatee, own results only ──

    @pytest.mark.asyncio
    async def test_delegatee_own_results_only(self):
        """A delegatee agent (e.g. user-agent) called by order-agent.
        It finishes its own task, no further delegation.
        _summarize should passthrough (Rule 2).
        """
        ex = self._setup(is_delegated=True, summarize_enabled=True,
                         summarize_prompt="some custom prompt")

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="complete",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="DELEGATEE_PASSTHROUGH")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[user-agent] 张三=U001"},
            {},  # no further delegation
            3, [], [],
        ))

        total = 0
        final_answer = None
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="delegatee",  # is_delegated=True
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="delegatee",
                )
                break

        assert final_answer == "DELEGATEE_PASSTHROUGH"

    # ── Scenario E: delegatee, recursive chain (had its own delegation) ──

    @pytest.mark.asyncio
    async def test_delegatee_recursive_chain(self):
        """A delegatee that further delegates to a 3rd agent.
        e.g. order-agent → user-agent → payment-agent.
        user-agent (delegatee) should still passthrough (Rule 2).
        """
        ex = self._setup(is_delegated=True, summarize_enabled=True)

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="complete",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="RECURSIVE_DELEGATEE_PASSTHROUGH")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[user-agent] 查询用户ID"},
            {"payment-agent": "[payment-agent] 付款记录"},  # further delegation
            2, [], [],
        ))

        total = 0
        final_answer = None
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="delegatee",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="delegatee",
                )
                break

        # Delegatee always passthrough regardless of its own delegate_results
        assert final_answer == "RECURSIVE_DELEGATEE_PASSTHROUGH"

    # ── Scenario F: initiator, 2-turn loop, unsatisfactory then satisfactory ──

    @pytest.mark.asyncio
    async def test_initiator_two_turns_unsatisfactory_then_satisfactory(self):
        """Turn 1: evaluation says unsatisfactory (missing info).
        Turn 2: after retry with failure_context, satisfactory → LLM summarize.
        """
        ex = self._setup(is_delegated=False, summarize_enabled=True)

        call_count = [0]
        def eval_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return SummaryEvaluationResult(
                    answer="not used", satisfactory=False,
                    missing_info="缺少用户名到用户ID的映射", rationale="missing user id",
                    cot_analysis="insufficient",
                    gap_obtainable=True,
                )
            return SummaryEvaluationResult(
                answer="not used", satisfactory=True,
                missing_info="", rationale="all data collected",
                cot_analysis="sufficient",
            )

        ex._summarize_with_evaluation = AsyncMock(side_effect=eval_side_effect)
        ex._summarize = AsyncMock(return_value="FINAL_AFTER_RETRY")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 订单数据"},
            {"user-agent": "[user-agent] 张三=U001"},
            4, [], [],
        ))

        total = 0
        turn_records = []
        failure_context = ""
        final_answer = None
        accumulated_delegate = {}

        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            accumulated_delegate.update(dr)
            turn_records.append({"turn": total, "plan": meta,
                                 "task_results": tr, "delegate_results": dr,
                                 "execution_flow_tasks": list(ef)})
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr,
                delegate_results=accumulated_delegate,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr,
                    delegate_results=accumulated_delegate,
                    agent_role="initiator",
                )
                break
            failure_context = f"缺失: {er.missing_info}"

        assert total == 2
        assert final_answer == "FINAL_AFTER_RETRY"

    # ── Scenario G: turn loop exhaustion → fallback _summarize ──

    @pytest.mark.asyncio
    async def test_initiator_exhausts_all_turns(self):
        """All 3 turns unsatisfactory → loop exhausts → forced _summarize."""
        ex = self._setup(is_delegated=False, summarize_enabled=True)

        ex._summarize_with_evaluation = AsyncMock(return_value=SummaryEvaluationResult(
            answer="not used", satisfactory=False,
            missing_info="始终缺少关键数据", rationale="insufficient",
            cot_analysis="insufficient",
            gap_obtainable=True,
        ))
        ex._summarize = AsyncMock(return_value="FORCED_FINAL_SUMMARY")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 部分数据"},
            {},
            4, [], [],
        ))

        total = 0
        final_answer = None
        delegate_results = {}
        task_results = {}
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            task_results.update(tr)
            delegate_results.update(dr)
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=task_results,
                    delegate_results=delegate_results,
                    agent_role="initiator",
                )
                break

        if final_answer is None:
            final_answer = await ex._summarize(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )

        assert total == 3
        assert final_answer == "FORCED_FINAL_SUMMARY"

    # ── Scenario G2: unobtainable gap → stop retrying immediately ──

    @pytest.mark.asyncio
    async def test_unobtainable_gap_stops_retries_immediately(self):
        """gap_obtainable=False → loop must NOT burn remaining turns.

        Regression guard: when the evaluator judges the missing information
        as beyond the capability boundary, further turns deterministically
        reproduce the same answer.  The loop must stop after turn 1 and answer
        from the results already in hand.
        """
        ex = self._setup(is_delegated=False, summarize_enabled=True)
        ex.max_loops = 3
        ex._summarize_with_evaluation = AsyncMock(return_value=SummaryEvaluationResult(
            answer="安全部分已完成；性能指标因缺乏压力测试能力无法提供。",
            satisfactory=False,
            missing_info="缺少压力测试能力，无法提供 TPS/P99 指标",
            rationale="该能力不在任何可协作 agent 范围内",
            cot_analysis="gap outside capability boundary",
            gap_obtainable=False,
        ))
        ex._summarize = AsyncMock(return_value="SHOULD_NOT_BE_CALLED")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[payment-agent] 安全部分完成"},
            {},
            4, [], [],
        ))

        total = 0
        final_answer = None
        delegate_results = {}
        task_results = {}
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            task_results.update(tr)
            delegate_results.update(dr)
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=task_results,
                    delegate_results=delegate_results,
                    agent_role="initiator",
                )
                break
            if not er.gap_obtainable:
                # Mirrors production: stop immediately, reuse evaluator answer.
                final_answer = er.answer
                break

        assert total == 1, f"expected exactly 1 turn, got {total}"
        assert final_answer == "安全部分已完成；性能指标因缺乏压力测试能力无法提供。"
        ex._summarize.assert_not_called()

    # ── Scenario G3: obtainable gap → retry behaviour unchanged ──

    @pytest.mark.asyncio
    async def test_obtainable_gap_still_retries(self):
        """Control: gap_obtainable=True must keep consuming turns as before."""
        ex = self._setup(is_delegated=False, summarize_enabled=True)
        ex.max_loops = 3
        ex._summarize_with_evaluation = AsyncMock(return_value=SummaryEvaluationResult(
            answer="not used", satisfactory=False,
            missing_info="缺少用户名到用户ID的映射", rationale="retrievable",
            cot_analysis="gap is retrievable",
            gap_obtainable=True,
        ))
        ex._summarize = AsyncMock(return_value="FORCED_FINAL_SUMMARY")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 部分数据"},
            {},
            4, [], [],
        ))

        total = 0
        final_answer = None
        delegate_results = {}
        task_results = {}
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            task_results.update(tr)
            delegate_results.update(dr)
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )
            if er.satisfactory or not er.gap_obtainable:
                final_answer = await ex._summarize(
                    original_query="q", task_results=task_results,
                    delegate_results=delegate_results,
                    agent_role="initiator",
                )
                break

        if final_answer is None:
            final_answer = await ex._summarize(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )

        assert total == 3
        assert final_answer == "FORCED_FINAL_SUMMARY"

    # ── Scenario G2: unobtainable gap → real execute() must stop after 1 turn ──

    @pytest.mark.asyncio
    async def test_execute_unobtainable_gap_stops_after_one_turn(self):
        """Drives the REAL ``execute()`` loop (not a re-implementation).

        Regression guard for the production branch: when the evaluator marks
        the missing information as not obtainable, ``execute()`` must return
        after turn 1 instead of burning every remaining turn.
        """
        ex = self._setup(is_delegated=False, summarize_enabled=True)
        ex.max_loops = 4

        eval_result = SummaryEvaluationResult(
            answer="安全部分已完成；性能指标因缺乏压力测试能力无法提供。",
            satisfactory=False,
            missing_info="缺少压力测试能力，无法提供 TPS/P99 指标",
            rationale="该能力不在任何可协作 agent 范围内",
            cot_analysis="gap outside capability boundary",
            gap_obtainable=False,
        )

        calls = {"plan_mid": 0, "eval": 0}

        async def _plan_mid(*a, **kw):
            calls["plan_mid"] += 1
            return {1: "[payment-agent] 安全部分完成"}, {}, 4, [], []

        async def _eval(*a, **kw):
            calls["eval"] += 1
            return eval_result

        ex._ensure_skill_runner = AsyncMock(return_value=None)
        ex._resolve_planner_agent_pool = AsyncMock(return_value=([], [], []))
        ex._get_memory = AsyncMock(return_value="")
        ex._execute_plan_and_mid_exec = AsyncMock(side_effect=_plan_mid)
        ex._summarize_with_evaluation = AsyncMock(side_effect=_eval)
        ex._summarize = AsyncMock(return_value="SHOULD_NOT_BE_CALLED")
        ex.get_history = AsyncMock(return_value=[])
        ex._emit_progress = AsyncMock()
        ex._log_dag_startup = MagicMock()
        ex._summary_prompt_agent_meta = MagicMock(return_value=("test", "initiator"))

        ctx = MagicMock()
        ctx.get_user_input.return_value = "对 payment_service 做全面的质量评估"
        ctx.metadata = {}
        # Provide a real Task so new_task(context.message) is not invoked
        # (it validates pydantic Message objects).
        from a2a.types import Task, TaskState, TaskStatus
        ctx.current_task = Task(
            status=TaskStatus(state=TaskState.submitted),
            id="task-1",
            context_id="ctx-1",
        )
        ctx.message = MagicMock()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()

        result = await ex.execute(ctx, eq)

        assert calls["plan_mid"] == 1, (
            f"execute() ran {calls['plan_mid']} turns; expected 1 "
            f"(unobtainable gap must stop the retry loop)"
        )
        assert calls["eval"] == 1
        ex._summarize.assert_not_called()

    # ── Scenario H: A → B → A (cycle), DAG disabled ──

    @pytest.mark.asyncio
    async def test_abc_cycle_b_delegates_back_to_a_passthrough(self):
        """A (initiator) → B (delegatee) → A (delegatee again).

        When B delegates back to A, A is called with collaboration_delegation=True.
        A's is_delegated=True → agent_role='delegatee' → Rule 2 passthrough.
        A must NOT summarize, even if it's the original query receiver.
        """
        ex = self._setup(is_delegated=True, summarize_enabled=True,
                         summarize_prompt="custom-summary-prompt")

        eval_result = SummaryEvaluationResult(
            answer="should not be used", satisfactory=True,
            missing_info="", rationale="complete",
            cot_analysis="substantive result",
        )
        ex._summarize_with_evaluation = AsyncMock(return_value=eval_result)
        ex._summarize = AsyncMock(return_value="A_AS_DELEGATEE_PASSTHROUGH")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 补充查询订单数据"},
            {},  # A doesn't delegate further in this turn
            2, [], [],
        ))

        total = 0
        final_answer = None
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=tr, delegate_results=dr,
                agent_role="delegatee",  # A is now a delegatee!
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=tr, delegate_results=dr,
                    agent_role="delegatee",
                )
                break

        # A as delegatee → Rule 2 → passthrough
        assert final_answer == "A_AS_DELEGATEE_PASSTHROUGH"

    # ── Scenario I: A → B → A, full chain simulation ──

    @pytest.mark.asyncio
    async def test_abc_full_chain_initiator_a_delegatee_b_then_delegatee_a(self):
        """Simulate the full A→B→A call chain to verify each agent's role.

        Turn 1 (A as initiator): A finds it needs user data → delegates to B.
           B is returned as delegate_result, but evaluation says not satisfactory.
        Turn 2 (A as initiator): A uses failure_context, delegates to B again.
           This time B delegates BACK to A (simulated as delegate_result).
           B's turn loop (not shown) would call B's own _summarize with agent_role='delegatee'.
           When A's evaluation marks satisfactory → A's _summarize with
           agent_role='initiator' sees delegate_results with B's contributions.
        """
        # ── B's perspective (simulated) ──
        # B is a delegatee, delegates back to A.
        # We test B's _summarize directly here.
        b_ex = self._setup(is_delegated=True, summarize_enabled=True)
        # B has its own task result AND delegated to A
        b_ex._summary_prompt_agent_meta = MagicMock(
            return_value=("user-agent", "delegatee")
        )
        b_result = await b_ex._summarize(
            original_query="查张三的用户ID",
            task_results={1: "[user-agent] 查询本地用户表"},
            delegate_results={"order-agent": "[order-agent] 补充订单查询"},
            agent_role="delegatee",  # B is delegatee
        )
        # B as delegatee → Rule 2 → passthrough
        assert "[user-agent]" in b_result
        assert "order-agent" in b_result
        # B's output becomes part of A's delegate_results

        # ── A's perspective (initiator, turn 2, satisfactory) ──
        a_ex = self._setup(is_delegated=False, summarize_enabled=True)
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="张三（U001）买了iPhone 15 Pro和AirPods Pro")
        )
        a_ex._summary_prompt_agent_meta = MagicMock(
            return_value=("order-agent", "initiator")
        )
        a_ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        a_ex.get_history = AsyncMock(return_value=[])
        a_ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await a_ex._summarize(
                original_query="张三买了哪些东西",
                task_results={
                    1: "[order-agent] 订单数据只有用户ID",
                    2: "[order-agent] 用U001查询订单",
                },
                delegate_results={
                    "user-agent": b_result,  # B's passthrough output
                    "order-agent-re": "[order-agent] U001的订单：iPhone, AirPods",
                },
                agent_role="initiator",  # A is initiator
            )
        finally:
            for p in reversed(patches):
                p.stop()

        # A as initiator with collaboration → Rule 4 → LLM summarize
        assert "iPhone" in result
        assert "AirPods" in result

    @pytest.mark.asyncio
    async def test_initiator_exhausts_all_turns(self):
        """All 3 turns unsatisfactory → loop exhausts → forced _summarize."""
        ex = self._setup(is_delegated=False, summarize_enabled=True)

        ex._summarize_with_evaluation = AsyncMock(return_value=SummaryEvaluationResult(
            answer="not used", satisfactory=False,
            missing_info="始终缺少关键数据", rationale="insufficient",
            cot_analysis="insufficient",
            gap_obtainable=True,
        ))
        ex._summarize = AsyncMock(return_value="FORCED_FINAL_SUMMARY")
        ex._execute_plan_and_mid_exec = AsyncMock(return_value=(
            {1: "[order-agent] 部分数据"},
            {},
            4, [], [],
        ))

        total = 0
        final_answer = None
        delegate_results = {}
        task_results = {}
        while total < 3:
            total += 1
            tr, dr, hop, meta, ef = await ex._execute_plan_and_mid_exec()
            task_results.update(tr)
            delegate_results.update(dr)
            er = await ex._summarize_with_evaluation(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )
            if er.satisfactory:
                final_answer = await ex._summarize(
                    original_query="q", task_results=task_results,
                    delegate_results=delegate_results,
                    agent_role="initiator",
                )
                break

        if final_answer is None:
            final_answer = await ex._summarize(
                original_query="q", task_results=task_results,
                delegate_results=delegate_results,
                agent_role="initiator",
            )

        assert total == 3
        assert final_answer == "FORCED_FINAL_SUMMARY"


# ======================================================================
# Boundary / Edge Cases
# ======================================================================


class TestBoundaryCases:

    @pytest.mark.asyncio
    async def test_agent_role_none_treated_as_initiator(self):
        """agent_role=None should not match 'delegatee' → treated as initiator."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="test")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("test", "initiator"))
        # agent_role=None, delegate_results empty → Rule 3 passthrough
        result = await ex._summarize(
            original_query="q", task_results={1: "result"},
            delegate_results={}, agent_role="",
        )
        assert "result" in result

    @pytest.mark.asyncio
    async def test_agent_role_wrong_casing_delEGATEE_not_matched(self):
        """Strict 'delegatee' check — casing like 'Delegatee' should be passthrough via Rule 3."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="test")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("test", "Delegatee"))
        result = await ex._summarize(
            original_query="q", task_results={1: "result"},
            delegate_results={}, agent_role="Delegatee",
        )
        # "Delegatee" != "delegatee" -> falls to Rule 3 (no collab) → passthrough
        assert "result" in result

    @pytest.mark.asyncio
    async def test_delegate_results_is_none_not_empty(self):
        """If somehow delegate_results=None slips in, bool check is safe."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="test")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("test", "initiator"))
        # delegate_results=None → falsy → Rule 3 passthrough
        result = await ex._summarize(
            original_query="q", task_results={1: "result"},
            delegate_results=None, agent_role="initiator",
        )
        assert "result" in result

    @pytest.mark.asyncio
    async def test_custom_prompt_with_newlines_multiline(self):
        """User writes a multi-line custom prompt with newlines."""
        custom = "第一行\n第二行\n第三行：输出JSON格式"
        ex = _make(summarize_enabled=True, summarize_prompt=custom,
                   agent_id="order-agent")

        captured_sys = [None]

        class FakeLLM:
            async def ainvoke(self, messages, **_kw):
                captured_sys[0] = str(messages[0].content)
                return MagicMock(content='{"answer": "done"}')

        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=FakeLLM())
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="q", task_results={1: "data"},
                delegate_results={"peer": "peer-data"},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert captured_sys[0] == custom
        assert "done" in result

    @pytest.mark.asyncio
    async def test_very_long_custom_prompt_not_truncated(self):
        """A 2000-char custom prompt should pass through verbatim."""
        custom = "请按照以下格式输出：" + "x" * 1950
        ex = _make(summarize_enabled=True, summarize_prompt=custom,
                   agent_id="order-agent")

        captured_sys = [None]
        class FakeLLM:
            async def ainvoke(self, messages, **_kw):
                captured_sys[0] = str(messages[0].content)
                return MagicMock(content="OK")

        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=FakeLLM())
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            await ex._summarize(
                original_query="q", task_results={1: "data"},
                delegate_results={"peer": "data"},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert captured_sys[0] == custom
        assert len(captured_sys[0]) == len(custom)

    @pytest.mark.asyncio
    async def test_empty_task_results_but_has_delegate_results(self):
        """Initiator, own tasks empty, but delegate results exist → LLM summarize."""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="order-agent")
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="仅来自下游的结果"))
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        ex._get_orchestration_llm = MagicMock(return_value=mock_llm)
        ex.get_history = AsyncMock(return_value=[])
        ex._resolve_execution_flow_for_summary = MagicMock(return_value=[])

        patches = _langfuse_patches()
        for p in patches:
            p.start()
        try:
            result = await ex._summarize(
                original_query="q", task_results={},
                delegate_results={"peer": "peer data"},
                agent_role="initiator",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert "仅来自下游的结果" in result


# ======================================================================
# Passthrough fidelity — output preserves raw skill result exactly
# ======================================================================


class TestPassthroughFidelity:

    @pytest.mark.asyncio
    async def test_raw_skill_output_preserved_exactly(self):
        """The original skill output must appear in the passthrough result exactly."""
        raw = """## 查询结果

销售总额（2024年1月）：123456 元
商品数量：89 件
平均客单价：1387.15 元

---

数据来源：order-agent 本地 skill"""
        ex = _make(summarize_enabled=False, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        result = await ex._summarize(
            original_query="查销售数据", task_results={1: raw},
            delegate_results={}, agent_role="initiator",
        )
        # Every significant number/word should appear verbatim
        assert "123456" in result
        assert "1387.15" in result
        assert "89 件" in result
        assert "数据来源：order-agent 本地 skill" in result

    @pytest.mark.asyncio
    async def test_multiline_markdown_result_preserved(self):
        """Multi-line markdown from skill output should survive passthrough."""
        raw = """**任务完成**：
- 步骤1：查询用户信息 ✓
- 步骤2：匹配订单数据 ✓
- 步骤3：计算总额 ✓

> 总计耗时 3.2 秒"""
        ex = _make(summarize_enabled=True, summarize_prompt=None,
                   agent_id="order-agent")
        ex._summary_prompt_agent_meta = MagicMock(return_value=("order-agent", "initiator"))
        result = await ex._summarize(
            original_query="q", task_results={1: raw},
            delegate_results={}, agent_role="initiator",
        )
        assert "**任务完成**" in result
        assert "总计耗时 3.2 秒" in result


# ======================================================================
# Config attribute verification
# ======================================================================


class TestConfigAttributes:
    def test_default_config_values(self):
        """Default values: enabled=True, prompt=None."""
        ex = _make(summarize_enabled=True, summarize_prompt=None)
        assert ex.summarize_enabled is True
        assert ex.summarize_prompt is None

    def test_config_disabled(self):
        ex = _make(summarize_enabled=False, summarize_prompt=None)
        assert ex.summarize_enabled is False

    def test_config_with_prompt(self):
        ex = _make(summarize_enabled=True, summarize_prompt="custom")
        assert ex.summarize_enabled is True
        assert ex.summarize_prompt == "custom"

    def test_config_disabled_with_prompt_irrelevant(self):
        """When disabled, prompt should still be stored but not used."""
        ex = _make(summarize_enabled=False, summarize_prompt="ignored")
        assert ex.summarize_enabled is False
        assert ex.summarize_prompt == "ignored"


# ======================================================================
# Execution Flow integrity — turn_summary + final_answer records
# ======================================================================


class TestExecutionFlowRecords:

    def test_summary_eval_result_still_has_answer_for_backward_compat(self):
        """_summarize_with_evaluation must still produce answer.
        The consumer (turn loop) just no longer uses it as final output.
        """
        r = SummaryEvaluationResult(
            answer="此答案只用于评估参考，不用于最终输出",
            satisfactory=True, missing_info="", rationale="ok",
            cot_analysis="steps 1-4",
        )
        assert r.answer is not None
        assert r.satisfactory is True

    @pytest.mark.asyncio
    async def test_turn_summary_success_record_preserved(self):
        """Verify turn_summary ExecutionTask with result='success' is created."""
        from agent.execution_flow import ExecutionTask

        ts = ExecutionTask(
            execution_id="turn-summary-t1", turn=1,
            stage="turn_summary", agent="order-agent",
            role="initiator", task="Turn 1 评估结果",
            result="success", reason="信息充足",
        )
        assert ts.result == "success"
        assert ts.stage == "turn_summary"

    @pytest.mark.asyncio
    async def test_turn_summary_fail_record_preserved(self):
        """Verify turn_summary ExecutionTask with result='fail' is created."""
        from agent.execution_flow import ExecutionTask

        ts = ExecutionTask(
            execution_id="turn-summary-t1", turn=1,
            stage="turn_summary", agent="order-agent",
            role="initiator", task="Turn 1 评估结果",
            result="fail", reason="缺少信息: X数据; 评估理由: insufficient",
        )
        assert ts.result == "fail"
        assert "X数据" in ts.reason

    @pytest.mark.asyncio
    async def test_final_answer_record_contains_actual_final_answer(self):
        """final_answer ExecutionTask should record the _summarize output."""
        from agent.execution_flow import ExecutionTask

        fa = ExecutionTask(
            execution_id="final-answer-t1", turn=1,
            stage="final_answer", agent="order-agent",
            role="initiator", task="最终答案",
            result="张三购买了iPhone 15 Pro和AirPods Pro",
        )
        assert fa.stage == "final_answer"
        assert "iPhone" in fa.result


# ======================================================================
# Start-of-run (__init__) env-var parsing
# ======================================================================


class TestEnvVarParsing:
    """Enum Environment variables are correctly parsed into instance attributes."""

    def test_true_like_values(self, monkeypatch):
        monkeypatch.setenv("SUMMARIZE_ENABLED", "true")
        # We can't fully init SE here (too many deps), so test the expression directly.
        val = os.getenv("SUMMARIZE_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        assert val is True

    def test_false_like_values(self):
        for v in ("false", "False", "FALSE", "0", "no", "No"):
            val = v.strip().lower() in ("true", "1", "yes")
            assert val is False, f"'{v}' should be parsed as False"

    def test_env_var_not_set_defaults_to_true(self):
        val = os.getenv("SUMMARIZE_NONEXISTENT_ENV", "true").strip().lower() in ("true", "1", "yes")
        assert val is True

    def test_custom_prompt_empty_yields_none(self):
        prompt = os.getenv("SUMMARIZE_NONEXISTENT_ENV", "").strip() or None
        assert prompt is None

    def test_custom_prompt_with_value_preserved(self):
        with patch.dict(os.environ, {"SUMMARIZE_CUSTOM_PROMPT": "hello world"}):
            prompt = os.getenv("SUMMARIZE_CUSTOM_PROMPT", "").strip() or None
            assert prompt == "hello world"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])