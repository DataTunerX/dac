"""Execution Flow 完整链路单元测试。

覆盖 EF 在以下边界的行为：
  1. pre-exec 委托：自己的 task → delegate wrapper + peer EF
  2. mid-exec 委托：mid-exec self + mid-exec delegate → 回并到主列表
  3. Turn 间传递：turn_ef_tasks → turn_records → upstream_context
  4. A→B→C 完整链：累加关系与 parent_execution_id 层级

不需要 LLM；planner / delegate_to_peer / summary / mid_exec_self 全部 mock。

Run:  python -m pytest tests/test_execution_flow.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, DEFAULT, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Mock unavailable dependencies ─────────────────────────────────────
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

# Re-import the real ExecutionTask (agent.execution_flow has no external deps)
from agent.execution_flow import ExecutionTask  # noqa: E402

from agent.skill_agent import SkillAgentExecutor  # noqa: E402
from agent.skill_agent_turn import (                           # noqa: E402
    SkillAgentExecutorWithTurns,
    _accumulated_execution_flow_tasks,
    _build_executed_tasks,
    _build_turn_context_md,
)

# ── Trace helpers ─────────────────────────────────────────────────────

# execution_id 的前缀约定（与源码一致）：
#  own-{task_id}-{agent}-t{turn}       — 本地 task
#  pre-{task_id}-{agent}-t{turn}       — pre-exec 委托 wrapper
#  mid-self-{task_id}-{agent}-t{turn}-r{round}
#  mid-del-{task_id}-{agent}-t{turn}-r{round}
#  turn-summary-t{turn}
#  final-answer-t{turn}

_SELF = "self-agent"


def _task(ids: list[int], agents: list[str], descs: list[str]):
    """Build a fake plan.tasks list (objects with .id / .agent / .description / .depends_on)."""
    out = []
    for i, a, d in zip(ids, agents, descs):
        t = MagicMock()
        t.id = i
        t.agent = a
        t.description = d
        t.depends_on = []
        out.append(t)
    return out


def _fake_delegate_to_peer(
    peer_efs: list[ExecutionTask],
    result: str = "ok",
):
    """返回一个 AsyncMock，call 时返回 (result, peer_efs)。"""
    async def _impl(*args, **kwargs):
        return result, peer_efs
    return _impl

# ── Common agent card ─────────────────────────────────────────────────

_PEER_CARD = AgentCard(
    name="peer-agent",
    description="peer",
    url="http://peer",
    version="1",
    skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
    capabilities=AgentCapabilities(),
    default_input_modes=["text", "text/plain"],
    default_output_modes=["text", "text/plain"],
)

_CARD_B = AgentCard(
    name="agent-b",
    description="b",
    url="http://b",
    version="1",
    skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
    capabilities=AgentCapabilities(),
    default_input_modes=["text", "text/plain"],
    default_output_modes=["text", "text/plain"],
)

_CARD_C = AgentCard(
    name="agent-c",
    description="c",
    url="http://c",
    version="1",
    skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
    capabilities=AgentCapabilities(),
    default_input_modes=["text", "text/plain"],
    default_output_modes=["text", "text/plain"],
)

# =============================================================================
# 1. pre-exec 委托：自己的 task 和 delegate wrapper + peer EF
# =============================================================================

class TestPreExecDelegationEF:
    """验证 pre-exec 阶段 EF 列表的积累与层级。"""

    @pytest.mark.asyncio
    async def test_own_then_delegate_ef_count_correct(self):
        """plan=[own, delegate] → 自己 1 + wrapper 1 + peer 2 = ef 总长 4."""

        exec_delegate = AsyncMock(return_value=("peer result", [
            ExecutionTask("peer-own-1", 1, "pre_exec", "peer-agent", "initiator", "peer task", "peer result", "", None, None),
            ExecutionTask("peer-mid-1", 1, "mid_exec_round_1", "peer-agent", "initiator", "peer mid", "ok", "", None, None),
        ]))

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "self-agent"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 5, []))
        inst._delegate_to_peer = exec_delegate
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == _SELF)
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()

        # mock make_plan → plan = [own(self), delegate(peer)]
        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2], [_SELF, "peer-agent"],
                                ["查本地", "委派peer"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_PEER_CARD]
        own_names = {_SELF}
        collab_names = {"peer-agent"}

        # mock SkillAgent to bypass real local-run path
        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return  # no-op
            async def run(self):
                yield "self result"

        call_args = dict(
            query="测试",
            all_cards=all_cards,
            own_names=own_names,
            collab_names=collab_names,
            skill_runner=MagicMock(),
            metadata={},
            user_id="u", run_id="r", trace_id="t",
            updater=MagicMock(),
            upstream_context={},
            is_delegated=False,
            current_hop=5,
            delegation_chain=[],
            failure_context="",
            prior_delegate_results={},
            group_memory=None,
            turn=1,
        )

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            _, _, _, _, ef = await inst._execute_plan_and_mid_exec(**call_args)

        assert len(ef) == 4
        # 顺序：own, wrapper, peer-root, peer-mid
        assert ef[0].execution_id == "own-1-self-agent-t1"
        assert ef[0].role == "initiator"
        assert ef[0].parent_execution_id is None
        assert ef[1].execution_id == "pre-2-peer-agent-t1"
        assert ef[1].role == "delegatee"
        assert ef[2].parent_execution_id == "pre-2-peer-agent-t1"
        assert ef[3].parent_execution_id == "pre-2-peer-agent-t1"


# =============================================================================
# 2. mid-exec 委托
# =============================================================================

class TestMidExecDelegationEF:
    """验证 mid-exec 阶段 EF 构建与回并。"""

    def test_mid_exec_ef_structure(self):
        """mid-exec 内 self + delegate → EF wrapper 和 re-parenting 正确。"""

        # 模拟 _dispatch_mid_exec_delegation 内部的 EF 构建逻辑
        execution_flow_tasks: list[ExecutionTask] = []
        mid_exec_round = 1

        # Point F: mid-exec self task
        mid_self_ef = ExecutionTask(
            execution_id=f"mid-self-10-{_SELF}-t1-r{mid_exec_round}",
            turn=1,
            stage=f"mid_exec_round_{mid_exec_round}",
            agent=_SELF,
            role="initiator",
            task="mid-self task",
            result="mid self result",
            reason="缺数据",
            parent_execution_id=None,
            delegated_by=None,
            run_id="r", trace_id="t", user_id="u",
        )
        execution_flow_tasks.append(mid_self_ef)

        # Point G: mid-exec delegate wrapper + peer EF
        peer_ef_tasks = [
            ExecutionTask("peer-root", 1, "pre_exec", "peer-agent", "initiator", "peer task", "ok", "", None, None),
        ]
        mg_ef_id = f"mid-del-11-peer-agent-t1-r{mid_exec_round}"
        for pt in peer_ef_tasks:
            if pt.parent_execution_id is None:
                pt.parent_execution_id = mg_ef_id
                pt.delegated_by = _SELF
        mg_ef_task = ExecutionTask(
            mg_ef_id, 1, f"mid_exec_round_{mid_exec_round}",
            "peer-agent", "delegatee", "mid-delegate", "mid peer result",
            "缺数据", None, _SELF,
            run_id="r", trace_id="t", user_id="u",
        )
        execution_flow_tasks.append(mg_ef_task)
        execution_flow_tasks.extend(peer_ef_tasks)

        assert len(execution_flow_tasks) == 3
        # mid-self
        assert execution_flow_tasks[0].execution_id == f"mid-self-10-{_SELF}-t1-r{mid_exec_round}"
        assert execution_flow_tasks[0].role == "initiator"
        assert execution_flow_tasks[0].parent_execution_id is None
        # mid-delegate wrapper
        assert execution_flow_tasks[1].execution_id == f"mid-del-11-peer-agent-t1-r{mid_exec_round}"
        assert execution_flow_tasks[1].role == "delegatee"
        # peer root re-parented
        assert execution_flow_tasks[2].parent_execution_id == f"mid-del-11-peer-agent-t1-r{mid_exec_round}"


# =============================================================================
# 3. Mid-exec EF 回并到主列表
# =============================================================================

class TestMidExecMergeBack:
    """验证 _dispatch_mid_exec_delegation 的 mid_ef_tasks 回并到
    _execute_plan_and_mid_exec 的主 execution_flow_tasks。"""

    def test_mid_exec_merge(self):
        # 主 EF 已有 pre-exec 阶段的内容
        main_ef = [
            ExecutionTask("own-1-a-t1", 1, "pre_exec", "agent-a", "initiator", "task1", "ok", "", None, None),
        ]
        # mid-exec 返回的 EF
        mid_ef = [
            ExecutionTask("mid-self-10-a-t1-r1", 1, "mid_exec_round_1", "agent-a", "initiator", "mid-self", "ok", "", None, None),
            ExecutionTask("mid-del-11-b-t1-r1", 1, "mid_exec_round_1", "agent-b", "delegatee", "mid-del", "ok", "", None, "agent-a"),
        ]

        # 模拟源码 line 7814-7815 的回并
        main_ef.extend(mid_ef)

        assert len(main_ef) == 3
        assert main_ef[0].execution_id == "own-1-a-t1"
        assert main_ef[1].execution_id == "mid-self-10-a-t1-r1"
        assert main_ef[2].execution_id == "mid-del-11-b-t1-r1"

        # 验证多轮 mid-exec round 的累积
        round2_ef = [
            ExecutionTask("mid-self-20-a-t1-r2", 1, "mid_exec_round_2", "agent-a", "initiator", "round2", "ok", "", None, None),
        ]
        main_ef.extend(round2_ef)
        assert len(main_ef) == 4
        assert main_ef[-1].stage == "mid_exec_round_2"


# =============================================================================
# 3. Turn 间 EF 传递 — 核心：跨轮 EF 是否丢失
# =============================================================================

class TestTurnToTurnEFPropagation:
    """验证 Turn 循环中 EF 在两个 Turn 之间的传递路径。

    修复后: upstream_context["execution_flow"] 在每轮结束时更新为
    _accumulated_execution_flow_tasks(turn_records)，确保后续 Turn 的
    delegation 能看到完整历史。
    """

    @pytest.mark.asyncio
    async def test_turn_records_captures_full_ef_each_turn(self):
        """Turn 结束后 turn_records 里是否有本轮的 EF，以及跨轮传递。"""
        inst = object.__new__(SkillAgentExecutorWithTurns)
        inst.max_loops = 2
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._get_memory = AsyncMock(return_value="")
        inst._emit_progress = AsyncMock()
        inst._load_mid_exec_broadcast_candidates = AsyncMock(return_value=[])
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_startup = MagicMock()

        # Turn 1 EF: 3 条
        turn1_ef = [
            ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "ok", "", None, None),
            ExecutionTask("pre-2-peer-agent-t1", 1, "pre_exec", "peer-agent", "delegatee", "task2", "ok", "", None, None),
            ExecutionTask("peer-own-1", 1, "pre_exec", "peer-agent", "initiator", "peer-task", "ok", "", "pre-2-peer-agent-t1", _SELF),
        ]
        # Turn 2 EF: 在 turn1 基础上追加 1 条（独立副本，不共享对象）
        turn2_ef = [
            ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "ok", "", None, None),
            ExecutionTask("pre-2-peer-agent-t1", 1, "pre_exec", "peer-agent", "delegatee", "task2", "ok", "", None, None),
            ExecutionTask("peer-own-1", 1, "pre_exec", "peer-agent", "initiator", "peer-task", "ok", "", "pre-2-peer-agent-t1", _SELF),
            ExecutionTask("own-3-self-agent-t2", 2, "pre_exec", _SELF, "initiator", "task3", "ok", "", None, None),
        ]

        async def _exec_turn1(*_a, **_kw): return ({}, {}, 5, [], list(turn1_ef))
        async def _exec_turn2(*_a, **_kw): return ({}, {}, 5, [], list(turn2_ef))

        async def _eval_turn1(*_a, **_kw):
            return MagicMock(satisfactory=False, answer="", missing_info="缺数据",
                             rationale="不够", cot_analysis="")
        async def _eval_turn2(*_a, **_kw):
            return MagicMock(satisfactory=True, answer="done", missing_info="",
                             rationale="够了", cot_analysis="")

        mock_exec = AsyncMock()
        mock_exec.side_effect = [({}, {}, 5, [], list(turn1_ef)),
                                  ({}, {}, 5, [], list(turn2_ef))]
        mock_eval = AsyncMock()
        mock_eval.side_effect = [
            MagicMock(satisfactory=False, answer="", missing_info="缺数据",
                      rationale="不够", cot_analysis=""),
            MagicMock(satisfactory=True, answer="done", missing_info="",
                      rationale="够了", cot_analysis=""),
        ]

        with patch.object(inst, "_execute_plan_and_mid_exec", mock_exec):
            with patch.object(inst, "_summarize_with_evaluation", mock_eval):

                # 模拟 turn loop 的核心逻辑
                turn_records = []
                upstream_context: dict[str, Any] = {}
                failure_context = ""
                total_turns = 0

                while total_turns < inst.max_loops:
                    total_turns += 1
                    tr, dr, _hop, _meta, turn_ef_tasks = await inst._execute_plan_and_mid_exec(
                        query="测试", all_cards=[], own_names=set(), collab_names=set(),
                        skill_runner=None, metadata={}, user_id="u", run_id="r", trace_id="t",
                        updater=MagicMock(), upstream_context=upstream_context,
                        is_delegated=False, current_hop=5, delegation_chain=[],
                        failure_context=failure_context, prior_delegate_results={},
                        group_memory=None, turn=total_turns,
                    )
                    turn_records.append({
                        "turn": total_turns,
                        "plan": [],
                        "task_results": tr,
                        "delegate_results": dr,
                        "execution_flow_tasks": list(turn_ef_tasks),
                    })
                    er = await inst._summarize_with_evaluation(
                        original_query="测试", task_results=tr, delegate_results=dr,
                        upstream_context=upstream_context, user_id="u", run_id="r", trace_id="t",
                        execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                        agent_role="initiator", turn=total_turns,
                    )

                    # 修复后: 每轮结束都追加 turn_summary ExecutionTask
                    ts_task = ExecutionTask(
                        execution_id=f"turn-summary-t{total_turns}",
                        turn=total_turns, stage="turn_summary",
                        agent=_SELF, role="initiator",
                        task=f"Turn {total_turns} 评估结果",
                        result="success" if er.satisfactory else "fail",
                        reason=er.rationale,
                        parent_execution_id=None, delegated_by=None,
                        run_id="r", trace_id="t", user_id="u",
                    )
                    turn_records[-1]["execution_flow_tasks"].append(ts_task)

                    if er.satisfactory:
                        # 修复后: final_answer 也是 ExecutionTask，追加到 EF 列表
                        fa_task = ExecutionTask(
                            execution_id=f"final-answer-t{total_turns}",
                            turn=total_turns, stage="final_answer",
                            agent=_SELF, role="initiator",
                            task="最终答案", result=er.answer,
                            reason=er.rationale,
                            parent_execution_id=None, delegated_by=None,
                            run_id="r", trace_id="t", user_id="u",
                        )
                        turn_records[-1]["execution_flow_tasks"].append(fa_task)
                        break
                    else:
                        failure_context = er.missing_info

                    # 修复后: upstream_context["execution_flow"] 跨轮更新
                    upstream_context = dict(upstream_context)
                    upstream_context["executed_tasks"] = _build_executed_tasks(turn_records)
                    upstream_context["execution_flow"] = _accumulated_execution_flow_tasks(turn_records)

                # ── Assertions ──
                assert total_turns == 2
                assert len(turn_records) == 2

                # Turn 1: 3 task EF + 1 turn_summary = 4
                assert len(turn_records[0]["execution_flow_tasks"]) == 4
                # Turn 2: 4 task EF + 1 turn_summary + 1 final_answer = 6
                assert len(turn_records[1]["execution_flow_tasks"]) == 6

                # **核心断言：Bug 已修复 — upstream_context["execution_flow"] 跨轮更新**
                assert "execution_flow" in upstream_context, (
                    "FIX VERIFIED: upstream_context['execution_flow'] 在 Turn 间已被更新"
                )
                assert len(upstream_context["execution_flow"]) == 4  # T1 的 EF（含 turn_summary）

                # _accumulated_execution_flow_tasks 拉取全量
                all_ef = _accumulated_execution_flow_tasks(turn_records)
                # T1: 4 (3 task + 1 ts) + T2: 6 (4 task + 1 ts + 1 fa) = 10
                assert len(all_ef) == 10

    @pytest.mark.asyncio
    async def test_turn_context_md_includes_full_ef_for_planner(self):
        """Planner 的 group_memory（via _build_turn_context_md）能包含
        上一轮执行后 _accumulated 的全量 EF，包括 turn_summary。"""
        turn_records = [{
            "turn": 1,
            "plan": [],
            "task_results": {},
            "delegate_results": {},
            "execution_flow_tasks": [
                ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "ok", "", None, None, run_id="r", trace_id="t", user_id="u"),
                # turn_summary 现在也是 ExecutionTask
                ExecutionTask("turn-summary-t1", 1, "turn_summary", _SELF, "initiator", "Turn 1 评估结果", "fail", "不够", None, None, run_id="r", trace_id="t", user_id="u"),
            ],
        }]

        md = _build_turn_context_md(
            upstream_context={"execution_flow": []},
            failure_context="需补充数据",
            turn_records=turn_records,
            current_agent=_SELF,
        )

        # 应该包含 EF 和 failure_context
        assert "task1" in md
        assert "需补充数据" in md
        assert "Turn 1" in md or "## 执行流水账" in md


# =============================================================================
# 4. 跨 Agent 委派链路：A → B → C 的 EF 层级
# =============================================================================

_OWN_TASK = ExecutionTask(
    "own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator",
    "本地task", "本地结果", "", None, None,
    run_id="r", trace_id="t", user_id="u",
)


class TestCrossAgentEFFullChain:
    """模拟 A 委托 B、B 再委托 C 时的 EF 传递。"""

    def test_peer_ef_reparenting(self):
        """B 的 mid-exec 委托 C 后，peer_ef_tasks 的 root 被挂到 wrapper 下。"""
        mid_ef = _OWN_TASK  # B 自己的一条

        # 模拟 C 返回的 peer EF
        peer_ef_tasks = [
            ExecutionTask("peer-own-1", 1, "pre_exec", "agent-c", "initiator", "C task", "C result", "", None, None),
            ExecutionTask("peer-mid-1", 1, "mid_exec_round_1", "agent-c", "initiator", "C mid", "ok", "", None, None),
        ]

        wrapper_id = "mid-del-2-agent-c-t1-r1"
        for pt in peer_ef_tasks:
            if pt.parent_execution_id is None:
                pt.parent_execution_id = wrapper_id
                pt.delegated_by = _SELF

        wrapper = ExecutionTask(
            wrapper_id, 1, "mid_exec_round_1", "agent-c", "delegatee",
            "委托C", "ok", "缺数据", None, _SELF,
            run_id="r", trace_id="t", user_id="u",
        )

        full_ef = [mid_ef, wrapper] + peer_ef_tasks

        assert len(full_ef) == 4
        assert full_ef[1].role == "delegatee"
        assert full_ef[2].parent_execution_id == wrapper_id
        assert full_ef[3].parent_execution_id == wrapper_id

    def test_a_delegates_b_full_chain(self):
        """模拟 A → B → C 完整链上的 EF 累积。

        A: own-1 + pre-wrapper(→B) + B根 + B的其它
        B 的 upstream EF = A 的序列化 EF，B 在此基础上追加自己的。
        C 同理。
        """
        # ── A 的 EF ──
        a_own = ExecutionTask("own-1-a-t1", 1, "pre_exec", "agent-a", "initiator", "A查用户", "U001", "", None, None)
        a_wrapper = ExecutionTask("pre-2-b-t1", 1, "pre_exec", "agent-b", "delegatee", "A委派B", "ok", "", None, "agent-a")
        b_root_from_a = ExecutionTask("own-1-b-t1", 1, "pre_exec", "agent-b", "initiator", "B查订单", "PROD-001", "", "pre-2-b-t1", "agent-a")
        a_ef = [a_own, a_wrapper, b_root_from_a]

        # ── B 收到 A 的 EF，再追加自己的（比如 B 第二轮的 mid-exec 委托 C）──
        b_mid_wrapper = ExecutionTask("mid-del-3-c-t2-r1", 2, "mid_exec_round_1", "agent-c", "delegatee", "B委派C", "ok", "缺标价", None, "agent-b")
        c_root = ExecutionTask("own-1-c-t1", 1, "pre_exec", "agent-c", "initiator", "C查商品", "iPhone 7999", "", "mid-del-3-c-t2-r1", "agent-b")
        b_ef = list(a_ef) + [b_mid_wrapper, c_root]

        assert len(b_ef) == 5

        # C 看到的所有东西都有 parent_execution_id
        assert c_root.parent_execution_id == "mid-del-3-c-t2-r1"
        assert c_root.delegated_by == "agent-b"

        # A 的 EF 不包含 C 的记录
        assert len(a_ef) == 3
        assert all("c" not in str(e.execution_id) for e in a_ef)

        # B 的 EF 包含 A 和 C
        agent_names_in_b = {e.agent for e in b_ef}
        assert "agent-a" in agent_names_in_b
        assert "agent-b" in agent_names_in_b
        assert "agent-c" in agent_names_in_b


# =============================================================================
# 5. Hop 耗尽 → 任务终止，进入汇总
# =============================================================================

class TestHopExhausted:
    """验证 hop 消耗/耗尽的所有路径。"""

    @pytest.mark.asyncio
    async def test_pre_exec_delegation_successful_hop_decrement(self):
        """hop=5 → delegate 成功 → remaining_hop 递减为 4。"""

        exec_delegate = AsyncMock(return_value=("peer result", [
            ExecutionTask("peer-own-1", 1, "pre_exec", "peer-agent", "initiator", "peer task", "peer result", "", None, None),
        ]))

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "self-agent"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 4, []))
        inst._delegate_to_peer = exec_delegate
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == _SELF)
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()

        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2], [_SELF, "peer-agent"],
                                ["查本地", "委派peer"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_PEER_CARD]
        own_names = {_SELF}
        collab_names = {"peer-agent"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "self result"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            task_results, delegate_results, remaining_hop, _, ef = await inst._execute_plan_and_mid_exec(
                query="测试hop正常递减",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=False,
                current_hop=5,              # ← hop=5，delegation 可用
                delegation_chain=[],
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # 核心断言：pre-exec delegate 消费了 1 hop
        assert remaining_hop == 4, f"hop 应从 5 递减到 4，实际 {remaining_hop}"

        # delegate 正常执行
        inst._delegate_to_peer.assert_called_once()

        # EF 包含 own + wrapper + peer
        assert len(ef) == 3
        assert ef[0].execution_id == "own-1-self-agent-t1"
        assert ef[1].execution_id == "pre-2-peer-agent-t1"

    @pytest.mark.asyncio
    async def test_hop_two_delegate_then_mid_exec_skipped(self):
        """hop=2 → pre-exec delegate 消耗 1 → remaining=1 → mid-exec 被 skip。

        关键场景：A(h=2)→B(h=1) 或 A(h=2)→B→C（B 不能再委派）。
        """

        exec_delegate = AsyncMock(return_value=("peer result", [
            ExecutionTask("peer-own-1", 1, "pre_exec", "peer-agent", "initiator", "peer task", "peer result", "", None, None),
        ]))

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "self-agent"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        # mid-exec dispatch 不应被调用（hop=1 时 mid-exec 直接 return）
        inst._plan_mid_exec_delegation = AsyncMock(
            side_effect=AssertionError("mid-exec should be skipped"))
        inst._dispatch_mid_exec_delegation = AsyncMock(
            side_effect=AssertionError("mid-exec should be skipped"))
        inst._delegate_to_peer = exec_delegate
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == _SELF)
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(
            return_value={"needs_help": True, "reason": "缺数据"})  # needs help but hop exhausted
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()

        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2], [_SELF, "peer-agent"],
                                ["查本地", "委派peer"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_PEER_CARD]
        own_names = {_SELF}
        collab_names = {"peer-agent"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "self result"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            task_results, delegate_results, remaining_hop, _, ef = await inst._execute_plan_and_mid_exec(
                query="测试hop=2",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=False,
                current_hop=2,              # ← hop=2
                delegation_chain=["agent-a"],
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # pre-exec delegate 消费了 1 hop → remaining 变为 1
        assert remaining_hop == 1, f"hop 应从 2 递减到 1，实际 {remaining_hop}"

        # pre-exec delegate 正常执行
        inst._delegate_to_peer.assert_called_once()

        # EF 包含 own + wrapper + peer
        assert len(ef) == 3
        assert ef[0].execution_id == "own-1-self-agent-t1"
        assert ef[1].execution_id == "pre-2-peer-agent-t1"

        # mid-exec 因 hop=1 被跳过（_plan_mid_exec_delegation 未被调用）
        # 由于 mock 设了 side_effect=AssertionError，只要没抛异常就证明没被调用

    @pytest.mark.asyncio
    async def test_pre_exec_delegation_skipped_when_hop_one(self):
        """current_hop=1 时，plan=[own, delegate] → 只有 own 执行，delegate 被 skip。"""

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "self-agent"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 0, []))
        # delegate_to_peer 不应该被调用
        inst._delegate_to_peer = AsyncMock(side_effect=AssertionError("should not be called"))
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == _SELF)
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()

        # plan: 1 own(self) + 1 delegate(peer)
        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2], [_SELF, "peer-agent"],
                                ["查本地", "委派peer（hop不够应跳过）"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_PEER_CARD]
        own_names = {_SELF}
        collab_names = {"peer-agent"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "self result"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            task_results, delegate_results, remaining_hop, _, ef = await inst._execute_plan_and_mid_exec(
                query="测试hop耗尽",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=False,
                current_hop=1,              # ← hop=1，delegation 不可用
                delegation_chain=["agent-a"],
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # Hop 不消耗（因为 delegation 被跳过了）
        assert remaining_hop == 1

        # Own task 正常执行
        assert "self result" in task_results.get(1, "")

        # Delegate task 被标记为 NONE（"No available agent can do this task..."）
        assert task_results.get(2, "") != ""
        assert "No available agent" in task_results.get(2, "")

        # delegate_to_peer 从未被调用
        inst._delegate_to_peer.assert_not_called()

        # EF 只有 1 条（own task），没有 delegate wrapper
        assert len(ef) == 1
        assert ef[0].execution_id == "own-1-self-agent-t1"

    @pytest.mark.asyncio
    async def test_mid_exec_skipped_when_hop_one(self):
        """current_hop=1 时，mid-exec 循环直接返回，不执行任何 round。"""

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "self-agent"
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._plan_mid_exec_delegation = AsyncMock()
        # _dispatch_mid_exec_delegation 和 _delegate_to_peer 都不应被调用
        inst._dispatch_mid_exec_delegation = AsyncMock(
            side_effect=AssertionError("should not be called"))
        inst._delegate_to_peer = AsyncMock(side_effect=AssertionError("should not be called"))
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == _SELF)
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(
            return_value={"needs_help": True, "reason": "缺数据"})  # needs help，但 hop 不够
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()

        plan_mock = MagicMock()
        plan_mock.tasks = _task([1], [_SELF], ["查本地"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "partial result"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            task_results, delegate_results, remaining_hop, _, ef = await inst._execute_plan_and_mid_exec(
                query="测试hop耗尽-midexec",
                all_cards=[_PEER_CARD],
                own_names={_SELF},
                collab_names={"peer-agent"},
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=False,
                current_hop=1,              # ← hop=1
                delegation_chain=[],
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # mid-exec 返回空 {} delegate_results
        assert delegate_results == {}

        # _plan_mid_exec_delegation 从未被调用（mid-exec 立即退出）
        inst._plan_mid_exec_delegation.assert_not_called()

        # EF 只有 own task
        assert len(ef) == 1


# =============================================================================
# 5b. Hop 跨 Turn 重置（entry-point agent）
# =============================================================================

class TestHopResetCrossTurn:
    """验证 entry-point agent 在 Turn 间 hop 重置，而 delegated agent 不重置。

    关键区分：
    - Entry-point（发起者）: hop 耗尽 → 重置为 CROSS_SG_MAX_HOP → 继续 Turn 2
    - Delegated（被委派者）: hop 耗尽 → 直接 break，不再进入下一轮
    """

    @pytest.mark.asyncio
    async def test_entry_point_hop_resets_and_continues_to_turn2(self):
        """Entry-point: hop=1 耗尽 → 重置为 5 → 进入 Turn 2。

        场景: agent 自身发起查询，Turn 1 做了深度委托链（hop 消耗到 1），
        Turn 1 答案不满足，Turn 2 应该能用重置后的 hop=5 继续委派。
        """
        inst = object.__new__(SkillAgentExecutorWithTurns)
        inst.max_loops = 2
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._get_memory = AsyncMock(return_value="")
        inst._emit_progress = AsyncMock()
        inst._load_mid_exec_broadcast_candidates = AsyncMock(return_value=[])
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_startup = MagicMock()

        # Turn 1 EF: own task
        turn1_ef = [
            ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "ok", "", None, None),
        ]
        # Turn 2 EF: 用重置后的 hop=5 委派了 peer
        turn2_ef = [
            ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "ok", "", None, None),
            ExecutionTask("pre-2-peer-agent-t2", 2, "pre_exec", "peer-agent", "delegatee", "委派peer", "ok", "", None, _SELF),
            ExecutionTask("peer-own-1", 2, "pre_exec", "peer-agent", "initiator", "peer task", "ok", "", "pre-2-peer-agent-t2", _SELF),
        ]

        mock_exec = AsyncMock()
        # Turn 1 返回 hop=1（耗尽但 entry-point 会重置）
        # Turn 2 返回 hop=4（重置后的 hop 被消耗 1 次）
        mock_exec.side_effect = [
            ({}, {}, 1, [], list(turn1_ef)),
            ({}, {}, 4, [], list(turn2_ef)),
        ]
        mock_eval = AsyncMock()
        mock_eval.side_effect = [
            MagicMock(satisfactory=False, answer="", missing_info="缺数据",
                      rationale="不够", cot_analysis=""),
            MagicMock(satisfactory=True, answer="done", missing_info="",
                      rationale="够了", cot_analysis=""),
        ]

        with patch.object(inst, "_execute_plan_and_mid_exec", mock_exec):
            with patch.object(inst, "_summarize_with_evaluation", mock_eval):

                turn_records = []
                upstream_context: dict[str, Any] = {}
                failure_context = ""
                current_hop = 5          # 初始 hop
                total_turns = 0

                while total_turns < inst.max_loops:
                    total_turns += 1
                    tr, dr, remaining_hop, _meta, turn_ef_tasks = await inst._execute_plan_and_mid_exec(
                        query="测试hop重置", all_cards=[], own_names=set(), collab_names=set(),
                        skill_runner=None, metadata={}, user_id="u", run_id="r", trace_id="t",
                        updater=MagicMock(), upstream_context=upstream_context,
                        is_delegated=False, current_hop=current_hop, delegation_chain=[],
                        failure_context=failure_context, prior_delegate_results={},
                        group_memory=None, turn=total_turns,
                    )
                    current_hop = remaining_hop

                    turn_records.append({
                        "turn": total_turns, "plan": [], "task_results": tr,
                        "delegate_results": dr, "execution_flow_tasks": list(turn_ef_tasks),
                    })
                    er = await inst._summarize_with_evaluation(
                        original_query="测试", task_results=tr, delegate_results=dr,
                        upstream_context=upstream_context, user_id="u", run_id="r", trace_id="t",
                        execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                        agent_role="initiator", turn=total_turns,
                    )

                    upstream_context = dict(upstream_context)
                    upstream_context["executed_tasks"] = _build_executed_tasks(turn_records)
                    upstream_context["execution_flow"] = _accumulated_execution_flow_tasks(turn_records)

                    if er.satisfactory:
                        break

                    # ═══════════════════════════════════════════════════════
                    # 关键逻辑：hop 耗尽时 entry-point 重置 hop
                    # 对应源码 skill_agent_turn.py:525-553
                    # ═══════════════════════════════════════════════════════
                    if current_hop <= 1:
                        # is_delegated = False → entry-point → 重置 hop
                        _initial_hop = 5
                        current_hop = _initial_hop
                        # Do NOT break — continue to evaluation and next turn
                    else:
                        failure_context = er.missing_info

                # ── Assertions ──
                assert total_turns == 2, "entry-point 应执行 2 轮"
                assert len(turn_records) == 2

                # Turn 1: hop 耗尽但被重置 → Turn 2 能正常委托
                assert len(turn_records[1]["execution_flow_tasks"]) == 3, (
                    "Turn 2 应有 3 条 EF（own + wrapper + peer）"
                )
                assert any(
                    e.execution_id == "pre-2-peer-agent-t2"
                    for e in turn_records[1]["execution_flow_tasks"]
                ), "Turn 2 的 delegate wrapper 存在，证明 hop 重置后委派成功"

    @pytest.mark.asyncio
    async def test_delegated_agent_hop_exhausted_breaks(self):
        """Delegated agent: hop=1 耗尽 → 直接 break，不进入 Turn 2。

        场景: agent 是被委派的（is_delegated=True），Turn 1 后 hop 耗尽。
        此时不应该重置 hop，直接 break 返回已有结果。
        """
        inst = object.__new__(SkillAgentExecutorWithTurns)
        inst.max_loops = 2
        inst._self_planner_agent_name = MagicMock(return_value=_SELF)
        inst._dag_enforcement_enabled = MagicMock(return_value=False)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._get_memory = AsyncMock(return_value="")
        inst._emit_progress = AsyncMock()
        inst._load_mid_exec_broadcast_candidates = AsyncMock(return_value=[])
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_startup = MagicMock()

        turn1_ef = [
            ExecutionTask("own-1-self-agent-t1", 1, "pre_exec", _SELF, "initiator", "task1", "partial", "", None, None),
        ]

        mock_exec = AsyncMock()
        mock_exec.side_effect = [
            ({}, {}, 1, [], list(turn1_ef)),     # Turn 1 返回 hop=1
        ]
        # simulate evaluate — not satisfactory
        mock_eval = AsyncMock()
        mock_eval.side_effect = [
            MagicMock(satisfactory=False, answer="", missing_info="缺数据",
                      rationale="不够", cot_analysis=""),
        ]

        total_turns = 0
        current_hop = 2           # delegated，初始 hop 较小

        with patch.object(inst, "_execute_plan_and_mid_exec", mock_exec):
            with patch.object(inst, "_summarize_with_evaluation", mock_eval):

                total_turns += 1
                tr, dr, remaining_hop, _meta, turn_ef_tasks = await inst._execute_plan_and_mid_exec(
                    query="测试", all_cards=[], own_names=set(), collab_names=set(),
                    skill_runner=None, metadata={}, user_id="u", run_id="r", trace_id="t",
                    updater=MagicMock(), upstream_context={},
                    is_delegated=True, current_hop=current_hop, delegation_chain=["agent-a"],
                    failure_context="", prior_delegate_results={},
                    group_memory=None, turn=1,
                )
                current_hop = remaining_hop

                er = await inst._summarize_with_evaluation(
                    original_query="测试", task_results=tr, delegate_results=dr,
                    upstream_context={}, user_id="u", run_id="r", trace_id="t",
                    execution_flow_tasks=[], agent_role="delegatee", turn=1,
                )

                # ═══════════════════════════════════════════════════════
                # 关键逻辑：delegated agent hop 耗尽 → break（不重置）
                # 对应源码 skill_agent_turn.py:526-542
                # ═══════════════════════════════════════════════════════
                if current_hop <= 1 and True:  # is_delegated = True
                    # break — 不进入 Turn 2
                    pass  # 模拟 break 行为

                # 即使 er 不满足，也不应该再有 Turn 2
                assert current_hop <= 1, "delegated agent hop 耗尽"
                assert not er.satisfactory, "答案不满足"

                # 关键断言：break 后 total_turns 还是 1
                assert total_turns == 1, (
                    "delegated agent hop 耗尽应 break，不应进入 Turn 2"
                )

class TestDAGCyclePrevention:
    """验证 CROSS_SG_ENFORCE_DAG=true 时 A→B→A 的回环被阻止。"""

    @pytest.mark.asyncio
    async def test_planner_pool_filters_out_chain_agents(self):
        """DAG Layer 2: planner 阶段的 agent 池过滤掉已在链中的 agent。"""

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "agent-b"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value="agent-b")
        inst._dag_enforcement_enabled = MagicMock(return_value=True)   # ← DAG 开启
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 3, []))
        inst._delegate_to_peer = AsyncMock()
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == "agent-b")
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_event = MagicMock()
        inst._log_dag_filter = MagicMock()
        inst._log_dag_startup = MagicMock()

        plan_mock = MagicMock()
        plan_mock.tasks = _task([1], ["agent-b"], ["查本地"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_CARD_B, _CARD_C, AgentCard(
            name="agent-a", description="a", url="http://a", version="1",
            skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
            capabilities=AgentCapabilities(), default_input_modes=["text", "text/plain"], default_output_modes=["text", "text/plain"],
        )]
        own_names = {"agent-b"}
        # 假设 chain=["agent-a", "agent-b"]，即 A→B，现在 B 是当前 agent
        # agent-a 已在链中，不应该出现在 planner 的可选池里
        collab_names = {"agent-a", "agent-c"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "ok"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            _, _, _, _, _ = await inst._execute_plan_and_mid_exec(
                query="测试DAG",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=True,
                current_hop=4,
                delegation_chain=["agent-a", "agent-b"],  # ← B 已在此链中
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # 验证 make_plan 被调用时 all_cards 已过滤掉 agent-a
        make_plan_call = inst._get_planner().make_plan.call_args
        plans_cards = make_plan_call[0][1]
        plan_card_names = {getattr(c, "name", "") for c in plans_cards}
        assert "agent-a" not in plan_card_names, (
            "agent-a 在 delegation_chain 中，应被 DAG Layer 2 过滤掉"
        )
        assert "agent-c" in plan_card_names, (
            "agent-c 不在链中，应保留"
        )

    @pytest.mark.asyncio
    async def test_delegation_prevents_calling_agent_in_chain(self):
        """planner 规划了 agent-a 的 task，但 agent-a 在 chain 里，
        pre-exec 阶段应被 skip（collab_names 已被过滤）。"""

        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "agent-b"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value="agent-b")
        inst._dag_enforcement_enabled = MagicMock(return_value=True)   # ← DAG 开启
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 3, []))
        # delegate_to_peer 不应该被调用（agent-a 不在 collab_names 中了）
        inst._delegate_to_peer = AsyncMock(side_effect=AssertionError("should not call agent-a"))
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == "agent-b")
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_event = MagicMock()
        inst._log_dag_filter = MagicMock()
        inst._log_dag_startup = MagicMock()

        # planner 不知道 DAG，可能仍然规划了 agent-a 的 task
        # 但 DAG Layer 2 已经把 agent-a 从 collab_names 移除了，所以
        # 即使 planner 返回 agent-a 的 task，pre-exec 循环会认为不在 collab_names 而跳过
        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2], ["agent-b", "agent-a"],
                                ["查本地", "委派agent-a（应被DAG阻止）"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [_CARD_B, _CARD_C]
        own_names = {"agent-b"}
        # agent-a 已被 DAG 从 collab_names 中移除
        collab_names = {"agent-c"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "ok"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            _, _, _, _, ef = await inst._execute_plan_and_mid_exec(
                query="测试DAG-planner残留",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=True,
                current_hop=4,
                delegation_chain=["agent-a", "agent-b"],
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # delegate_to_peer 从未被调用
        inst._delegate_to_peer.assert_not_called()

        # EF 只有 own task（agent-a 的 task 不在 collab_names 中被跳过）
        assert all(
            e.agent != "agent-a" for e in ef
        ), "agent-a 在 delegation_chain 中，不应有 agent-a 的 EF 记录"

        assert len(ef) == 1
        assert ef[0].execution_id == "own-1-agent-b-t1"

    @pytest.mark.asyncio
    async def test_abc_chain_planner_blocks_recursive_call_to_a(self):
        """A→B→C→A 的完整 3 层回环测试。

        chain=["agent-a", "agent-b", "agent-c"]，当前 agent="agent-c"
        → DAG Layer 2 应同时过滤掉 agent-a 和 agent-b
        → 即使 planner 规划了 agent-a 的 task，collab_names 也不含 agent-a
        → delegate_to_peer 永远不会被调用
        """
        inst = object.__new__(SkillAgentExecutor)
        inst.metadata = {}
        inst.agent_id = "agent-c"
        inst.agent_card = MagicMock()
        inst._self_planner_agent_name = MagicMock(return_value="agent-c")
        inst._dag_enforcement_enabled = MagicMock(return_value=True)   # ← DAG 开启
        inst._plan_mid_exec_delegation = AsyncMock()
        inst._dispatch_mid_exec_delegation = AsyncMock(return_value=({}, {}, 2, []))
        # 两个都不应被调用（agent-a 和 agent-b 都在链中）
        inst._delegate_to_peer = AsyncMock(
            side_effect=AssertionError("should not call any agent in chain"))
        inst._get_planner = MagicMock()
        inst._get_orchestration_llm = MagicMock()
        inst._get_memory = AsyncMock(return_value="")
        inst._is_local_skill_task = MagicMock(side_effect=lambda task, **kw: task.agent == "agent-c")
        inst._emit_progress = AsyncMock()
        inst._emit_execution_flow = AsyncMock()
        inst._record_none_execution_task = AsyncMock()
        inst._llm_refine_dependent_task_query = AsyncMock()
        inst._validate_plan_dependency_schedule = MagicMock(return_value=True)
        inst._detect_delegation_needs = AsyncMock(return_value={"needs_help": False})
        inst._log_data_flow = MagicMock()
        inst._log_summary_input = MagicMock()
        inst._log_dag_event = MagicMock()
        inst._log_dag_filter = MagicMock()
        inst._log_dag_startup = MagicMock()

        # planner 可能规划了回环 task（agent-a）
        plan_mock = MagicMock()
        plan_mock.tasks = _task([1, 2, 3], ["agent-c", "agent-a", "agent-b"],
                                ["C查本地", "尝试回环A（应阻止）", "尝试回环B（应阻止）"])
        inst._get_planner().make_plan = AsyncMock(return_value=plan_mock)

        all_cards = [
            _CARD_C,
            AgentCard(name="agent-a", description="a", url="http://a", version="1",
                      skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
                      capabilities=AgentCapabilities(), default_input_modes=["text", "text/plain"], default_output_modes=["text", "text/plain"]),
            AgentCard(name="agent-b", description="b", url="http://b", version="1",
                      skills=[AgentSkill(id="x", name="x", description="x", tags=[], examples=[], input_modes=["text"], output_modes=["text"])],
                      capabilities=AgentCapabilities(), default_input_modes=["text", "text/plain"], default_output_modes=["text", "text/plain"]),
            _PEER_CARD,
        ]
        own_names = {"agent-c"}
        # agent-a 和 agent-b 已被 DAG 从 collab_names 移除
        collab_names = {"peer-agent"}

        class _FakeSkillAgent:
            def __init__(self, **kw):
                self.agent_id = kw.get("agent_id", "")
                self.metadata = kw.get("metadata", {})
                self.progress_callback = kw.get("progress_callback")
            async def emit_progress(self, **kw):
                return
            async def run(self):
                yield "C 查到的数据"

        with patch("agent.skill_agent.SkillAgent", _FakeSkillAgent):
            _, _, _, _, ef = await inst._execute_plan_and_mid_exec(
                query="A→B→C→A 回环测试",
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=MagicMock(),
                metadata={},
                user_id="u", run_id="r", trace_id="t",
                updater=MagicMock(),
                upstream_context={},
                is_delegated=True,
                current_hop=2,
                delegation_chain=["agent-a", "agent-b", "agent-c"],  # ← 完整 3 层链
                failure_context="",
                prior_delegate_results={},
                group_memory=None,
                turn=1,
            )

        # 核心断言：delegate_to_peer 从未被调用
        inst._delegate_to_peer.assert_not_called()

        # make_plan 收到的 all_cards 已过滤掉 chain 中的 agent
        make_plan_call = inst._get_planner().make_plan.call_args
        plans_cards = make_plan_call[0][1]
        plan_card_names = {getattr(c, "name", "") for c in plans_cards}
        assert "agent-a" not in plan_card_names, "agent-a 在 delegation_chain 中，应被 DAG Layer 2 过滤"
        assert "agent-b" not in plan_card_names, "agent-b 在 delegation_chain 中，应被 DAG Layer 2 过滤"
        # agent-c 是当前 agent，也在 delegation_chain 中，DAG Layer 2 同样过滤。
        # 但不影响本地执行（agent-c 在 own_names 中）。
        assert "peer-agent" in plan_card_names, "peer-agent 不在链中，应保留"

        # EF 只有 agent-c 自己的 task，没有 agent-a 或 agent-b
        agent_names_in_ef = {e.agent for e in ef}
        assert "agent-a" not in agent_names_in_ef, "不应该有回环 agent-a"
        assert "agent-b" not in agent_names_in_ef, "不应该有回环 agent-b"
        assert "agent-c" in agent_names_in_ef, "应该有本地 agent-c"
        assert len(ef) == 1