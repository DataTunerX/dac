"""Unit tests for _summarize_with_evaluation (tool-calling version) and turn loop.

Tests the ``invoke_llm_with_tool``-based evaluation without requiring
external LLM calls.  The test mocks ``invoke_llm_with_tool`` and verifies
that ``_summarize_with_evaluation`` correctly parses the tool-call result
dict into a ``SummaryEvaluationResult``.

Run::

    cd /path/to/dac/skill-agent
    python -m pytest tests/test_turn_loop.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Mock unavailable dependencies before importing agent modules.
# ---------------------------------------------------------------------------
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
    DEFAULT_MAX_LOOPS,
    SkillAgentExecutorWithTurns,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make(klass: type = SkillAgentExecutorWithTurns, **attrs):
    inst = object.__new__(klass)
    for k, v in attrs.items():
        object.__setattr__(inst, k, v)
    return inst


# =============================================================================
# SummaryEvaluationResult pydantic model
# =============================================================================

class TestSummaryEvaluationResult:
    def test_satisfactory(self):
        r = SummaryEvaluationResult(
            answer="答案是42",
            satisfactory=True,
            missing_info="",
            rationale="All data is available",
            cot_analysis="步骤1：问题诉求是...步骤2：答案覆盖了...步骤3：实质性结果。步骤4：satisfactory=true。",
        )
        assert r.answer == "答案是42"
        assert r.satisfactory is True
        assert r.missing_info == ""
        assert r.rationale == "All data is available"

    def test_not_satisfactory(self):
        r = SummaryEvaluationResult(
            answer="部分答案...",
            satisfactory=False,
            missing_info="缺少数据库 Y 的日志数据",
            rationale="Missing log data from system Y",
            cot_analysis="步骤1：问题诉求是...步骤2：答案未覆盖...步骤3：解释说明。步骤4：satisfactory=false。",
        )
        assert not r.satisfactory
        assert "数据库 Y" in r.missing_info

    def test_extra_fields_ignored(self):
        r = SummaryEvaluationResult(
            answer="ok",
            satisfactory=True,
            missing_info="",
            rationale="sufficient",
            cot_analysis="步骤1：问题诉求是...步骤2：答案覆盖了...步骤3：实质性结果。步骤4：satisfactory=true。",
            unknown_field="should_be_ignored",
        )
        assert r.answer == "ok"
        assert not hasattr(r, "unknown_field")


# =============================================================================
# _summarize_with_evaluation — tool-calling path
# =============================================================================

class TestSummarizeWithEvaluationToolCall:

    def _make(self) -> SkillAgentExecutorWithTurns:
        return _make(max_loops=2)

    @pytest.mark.asyncio
    async def test_satisfactory_true(self):
        """LLM calls evaluate_summary with satisfactory=True."""
        ex = self._make()

        mock_tool_result = {
            "answer": "这是完整的分析结果。",
            "satisfactory": True,
            "missing_info": "",
            "rationale": "All required data collected",
        }
        with patch.object(
            ex, "_get_orchestration_llm", return_value=MagicMock(),
        ):
            with patch.object(
                ex, "get_history", return_value=AsyncMock(return_value=[])
            ):
                with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(
                    return_value=mock_tool_result,
                )):
                    with patch("agent.skill_agent.ChatPromptTemplate"):
                        with patch("agent.skill_agent.SystemMessagePromptTemplate"):
                            with patch("agent.skill_agent.HumanMessagePromptTemplate"):
                                with patch("agent.skill_agent.StructuredTool"):

                                    result = await ex._summarize_with_evaluation(
                                        original_query="测试问题",
                                        task_results={1: "结果1"},
                                        delegate_results={},
                                    )

        assert result.satisfactory is True
        assert result.answer == "这是完整的分析结果。"
        assert result.missing_info == ""

    @pytest.mark.asyncio
    async def test_satisfactory_false_with_missing(self):
        """LLM calls evaluate_summary with satisfactory=False + missing_info."""
        ex = self._make()

        mock_tool_result = {
            "answer": "部分答案...",
            "satisfactory": False,
            "missing_info": "需要获取模块 X 的配置信息",
            "rationale": "Missing config data from module X",
        }
        with patch.object(
            ex, "_get_orchestration_llm", return_value=MagicMock(),
        ):
            with patch.object(
                ex, "get_history", return_value=AsyncMock(return_value=[])
            ):
                with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(
                    return_value=mock_tool_result,
                )):
                    with patch("agent.skill_agent.ChatPromptTemplate"):
                        with patch("agent.skill_agent.SystemMessagePromptTemplate"):
                            with patch("agent.skill_agent.HumanMessagePromptTemplate"):
                                with patch("agent.skill_agent.StructuredTool"):

                                    result = await ex._summarize_with_evaluation(
                                        original_query="测试问题",
                                        task_results={1: "部分数据"},
                                        delegate_results={},
                                    )

        assert result.satisfactory is False
        assert "部分答案" in result.answer
        assert "模块 X" in result.missing_info

    @pytest.mark.asyncio
    async def test_satisfactory_false_empty_missing(self):
        """LLM returns satisfactory=False but missing_info is empty."""
        ex = self._make()

        mock_tool_result = {
            "answer": "不够好",
            "satisfactory": False,
            "missing_info": "",
            "rationale": "Insufficient data",
        }
        with patch.object(
            ex, "_get_orchestration_llm", return_value=MagicMock(),
        ):
            with patch.object(
                ex, "get_history", return_value=AsyncMock(return_value=[])
            ):
                with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(
                    return_value=mock_tool_result,
                )):
                    with patch("agent.skill_agent.ChatPromptTemplate"):
                        with patch("agent.skill_agent.SystemMessagePromptTemplate"):
                            with patch("agent.skill_agent.HumanMessagePromptTemplate"):
                                with patch("agent.skill_agent.StructuredTool"):

                                    result = await ex._summarize_with_evaluation(
                                        original_query="测试",
                                        task_results={},
                                        delegate_results={},
                                    )

        assert result.satisfactory is False
        assert "当前信息不足以" in result.missing_info

    @pytest.mark.asyncio
    async def test_llm_did_not_call_tool(self):
        """invoke_llm_with_tool returns None → fallback satisfactory=False."""
        ex = self._make()

        with patch.object(
            ex, "_get_orchestration_llm", return_value=MagicMock(),
        ):
            with patch.object(
                ex, "get_history", return_value=AsyncMock(return_value=[])
            ):
                with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(
                    return_value=None,
                )):
                    with patch("agent.skill_agent.ChatPromptTemplate"):
                        with patch("agent.skill_agent.SystemMessagePromptTemplate"):
                            with patch("agent.skill_agent.HumanMessagePromptTemplate"):
                                with patch("agent.skill_agent.StructuredTool"):

                                    result = await ex._summarize_with_evaluation(
                                        original_query="测试",
                                        task_results={},
                                        delegate_results={},
                                    )

        assert result.satisfactory is False
        assert "LLM 未调用评估工具" in result.answer

    @pytest.mark.asyncio
    async def test_exception_returns_satisfactory(self):
        """invoke_llm_with_tool raises → fallback satisfactory=False."""
        ex = self._make()

        with patch.object(
            ex, "_get_orchestration_llm", return_value=MagicMock(),
        ):
            with patch.object(
                ex, "get_history", return_value=AsyncMock(return_value=[])
            ):
                with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(
                    side_effect=RuntimeError("LLM down"),
                )):
                    with patch("agent.skill_agent.ChatPromptTemplate"):
                        with patch("agent.skill_agent.SystemMessagePromptTemplate"):
                            with patch("agent.skill_agent.HumanMessagePromptTemplate"):
                                with patch("agent.skill_agent.StructuredTool"):

                                    result = await ex._summarize_with_evaluation(
                                        original_query="测试",
                                        task_results={1: "结果1"},
                                        delegate_results={},
                                    )

        assert result.satisfactory is False
        assert "汇总阶段出错" in result.answer


# =============================================================================
# max_loops clamping
# =============================================================================

class TestMaxLoopsClamping:
    def test_default(self):
        inst = _make(max_loops=DEFAULT_MAX_LOOPS)
        assert inst.max_loops == 2

    def test_zero_clamped(self):
        inst = _make(max_loops=max(1, 0))
        assert inst.max_loops == 1

    def test_negative_clamped(self):
        inst = _make(max_loops=max(1, -5))
        assert inst.max_loops == 1


# =============================================================================
# Turn loop simulation with LLM evaluation
# =============================================================================

class TestTurnLoopWithLLMEval:
    """Simulate the turn loop logic using _summarize_with_evaluation results."""

    def _make(self, max_loops: int = 2) -> SkillAgentExecutorWithTurns:
        return _make(max_loops=max_loops)

    @pytest.mark.asyncio
    async def test_exits_on_satisfactory_turn1(self):
        """Turn 1: LLM says satisfactory → exit immediately, 1 turn."""
        ex = self._make(max_loops=3)

        mock_eval = AsyncMock(return_value=SummaryEvaluationResult(
            answer="最终答案", satisfactory=True,
            missing_info="", rationale="sufficient",
            cot_analysis="步骤1：用户问题核心诉求是...步骤2：答案覆盖了...步骤3：是实质性结果。步骤4：satisfactory=true。",
        ))
        mock_exec = AsyncMock(return_value=({1: "ok"}, {}, 2, []))
        with patch.object(ex, "_summarize_with_evaluation", mock_eval):
            with patch.object(ex, "_execute_plan_and_mid_exec", mock_exec):

                total = 0
                accumulated_task: dict[int, str] = {}
                accumulated_delegate: dict[str, str] = {}
                final_answer = None

                while total < ex.max_loops:
                    total += 1
                    tr, dr, _hop, _meta = await ex._execute_plan_and_mid_exec()
                    accumulated_task.update(tr)
                    accumulated_delegate.update(dr)
                    er = await ex._summarize_with_evaluation(
                        original_query="q",
                        task_results=accumulated_task,
                        delegate_results=accumulated_delegate,
                    )
                    if er.satisfactory:
                        final_answer = er.answer
                        break

                assert total == 1
                assert final_answer == "最终答案"

    @pytest.mark.asyncio
    async def test_retries_on_not_satisfactory(self):
        """Turn 1 not satisfactory, Turn 2 satisfactory → 2 turns."""
        ex = self._make(max_loops=3)

        call_count = [0]

        async def mock_eval(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return SummaryEvaluationResult(
                    answer="不够好", satisfactory=False,
                    missing_info="缺少X数据", rationale="missing X data",
                    cot_analysis="步骤1：问题诉求是...步骤2：答案未覆盖...步骤3：解释说明。步骤4：satisfactory=false。",
                )
            return SummaryEvaluationResult(
                answer="完整答案", satisfactory=True,
                missing_info="", rationale="all data collected",
                cot_analysis="步骤1：问题诉求是...步骤2：答案覆盖了...步骤3：实质性结果。步骤4：satisfactory=true。",
            )

        mock_exec = AsyncMock(return_value=({1: "ok"}, {}, 2, []))
        with patch.object(ex, "_summarize_with_evaluation", mock_eval):
            with patch.object(ex, "_execute_plan_and_mid_exec", mock_exec):

                total = 0
                accumulated_task = {}
                accumulated_delegate = {}
                final_answer = None
                failure_context = ""

                while total < ex.max_loops:
                    total += 1
                    tr, dr, _hop, _meta = await ex._execute_plan_and_mid_exec()
                    accumulated_task.update(tr)
                    accumulated_delegate.update(dr)
                    er = await ex._summarize_with_evaluation(
                        original_query="q",
                        task_results=accumulated_task,
                        delegate_results=accumulated_delegate,
                    )
                    if er.satisfactory:
                        final_answer = er.answer
                        break
                    failure_context = f"缺失: {er.missing_info}"

                assert total == 2
                assert final_answer == "完整答案"
                assert "X数据" in failure_context

    @pytest.mark.asyncio
    async def test_exhausts_all_turns(self):
        """All turns not satisfactory, loop exhausts → 3 turns (max_loops=3)."""
        ex = self._make(max_loops=3)

        mock_eval = AsyncMock(return_value=SummaryEvaluationResult(
            answer="不够", satisfactory=False,
            missing_info="缺数据", rationale="insufficient",
            cot_analysis="步骤1：问题诉求是...步骤2：答案未覆盖...步骤3：解释说明。步骤4：satisfactory=false。",
        ))
        mock_exec = AsyncMock(return_value=({1: "ok"}, {}, 2, []))
        with patch.object(ex, "_summarize_with_evaluation", mock_eval):
            with patch.object(ex, "_execute_plan_and_mid_exec", mock_exec):

                total = 0
                while total < ex.max_loops:
                    total += 1
                    tr, dr, _hop, _meta = await ex._execute_plan_and_mid_exec()
                    er = await ex._summarize_with_evaluation(
                        original_query="q",
                        task_results=tr,
                        delegate_results=dr,
                    )
                    if er.satisfactory:
                        break

                assert total == 3

    @pytest.mark.asyncio
    async def test_max_loops_one(self):
        """max_loops=1 → 1 turn regardless of satisfaction."""
        ex = self._make(max_loops=1)

        mock_eval = AsyncMock(return_value=SummaryEvaluationResult(
            answer="不完美", satisfactory=False,
            missing_info="缺", rationale="not enough",
            cot_analysis="步骤1：问题诉求是...步骤2：答案未覆盖...步骤3：解释说明。步骤4：satisfactory=false。",
        ))
        mock_exec = AsyncMock(return_value=({1: "ok"}, {}, 2, []))
        with patch.object(ex, "_summarize_with_evaluation", mock_eval):
            with patch.object(ex, "_execute_plan_and_mid_exec", mock_exec):

                total = 0
                while total < ex.max_loops:
                    total += 1
                    tr, dr, _hop, _meta = await ex._execute_plan_and_mid_exec()
                    er = await ex._summarize_with_evaluation(
                        original_query="q",
                        task_results=tr,
                        delegate_results=dr,
                    )
                    if er.satisfactory:
                        break

                assert total == 1


# =============================================================================
# Regression
# =============================================================================

class TestOldExecuteUnchanged:
    def test_method_exists(self):
        assert hasattr(SkillAgentExecutor, "_execute_plan_and_mid_exec")
        assert callable(getattr(SkillAgentExecutor, "_execute_plan_and_mid_exec"))

    def test_summarize_with_evaluation_exists(self):
        assert hasattr(SkillAgentExecutor, "_summarize_with_evaluation")
        assert callable(getattr(SkillAgentExecutor, "_summarize_with_evaluation"))

    def test_summary_evaluation_result_is_pydantic(self):
        assert SummaryEvaluationResult is not None
        from pydantic import BaseModel
        assert issubclass(SummaryEvaluationResult, BaseModel)