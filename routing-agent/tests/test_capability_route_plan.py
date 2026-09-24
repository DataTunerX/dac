"""Route-plan decision tests for capability-chain scored broadcast results.

Imports ``routing_agent.server`` with the same heavy-dep mocks used elsewhere
in dac, then drives ``get_plan_by_broadcast`` / ``_pick_dominant_single_root``
with canned CapabilityCheckResponse objects — no live LLM, no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod in (
    "model_sdk",
    "langfuse",
    "langfuse.langchain",
    "mcp",
    "mcp.client.sse",
    "mcp.client.stdio",
    "mcp.types",
    "a2a.server.apps",
    "a2a.server.request_handlers",
    "a2a.server.agent_execution",
    "a2a.server.events",
    "a2a.server.tasks",
    "a2a.utils",
    "a2a.client",
    "langchain_mcp_adapters",
    "routing_agent.agentregistry_client",
    "routing_agent.dataservices_client",
    "routing_agent.tool_call_utils",
):
    sys.modules.setdefault(_mod, MagicMock())

# a2a.types is needed for AgentCard-shaped objects; a SimpleNamespace is enough
# for these tests, so a MagicMock module is fine if the real one is missing.
sys.modules.setdefault("a2a", MagicMock())
sys.modules.setdefault("a2a.types", MagicMock())

from routing_agent.server import (  # noqa: E402
    CapabilityCheckResponse,
    MultiRootTask,
    MultiRootTaskPlan,
    ROUTING_AGENT_POOL_KEY,
    RoutingAgent,
    _capability_response_from_payload,
    _format_capable_agent_line,
    _pre_make_plan_select_max_attempts,
    _pre_make_plan_select_timeout,
    _render_broadcast_capability_progress_md,
    _render_capability_progress_md,
    _render_broadcast_pre_make_plan_progress_md,
    _render_pre_make_plan_md,
    _render_pre_make_plan_selection_md,
)


def _card(name: str, url: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=name, url=url or f"http://{name}", description=f"{name} desc")


def _chain(**kwargs) -> CapabilityCheckResponse:
    data = dict(
        can_handle=False,
        can_contribute=True,
        confidence=1.0,
        reason="test",
        agent_name=kwargs.get("agent_name", "agent"),
        contribution=kwargs.get("contribution", "输入 x，输出 y，供下一步使用"),
        score_version="capability-chain-v1",
        evidence_grade="A",
        threshold=0.7,
        handle_score=0.0,
        contributing_steps=[1],
        missing_requirements=[],
    )
    data.update(kwargs)
    return CapabilityCheckResponse(**data)


class _FakeRouting:
    """Plain object that reuses RoutingAgent methods without pydantic init."""

    get_plan_by_broadcast = RoutingAgent.get_plan_by_broadcast
    get_best_agent_by_broadcast = RoutingAgent.get_best_agent_by_broadcast
    _pick_dominant_single_root = RoutingAgent._pick_dominant_single_root
    _normalize_capability_check_response = RoutingAgent._normalize_capability_check_response

    def __init__(self) -> None:
        self.agent_name = "routing-agent"
        self.agent_cards = []
        planner = MagicMock()
        planner.get_history_payload = AsyncMock(return_value={})
        self.planner_agent = planner
        self._select_by_pre_make_plan = AsyncMock(return_value=None)


def _agent() -> _FakeRouting:
    return _FakeRouting()


@pytest.mark.asyncio
async def test_zhangsan_two_contributors_compose_into_multi_root():
    """Design 12.1 + 12.2: neither agent can_handle; routing must stitch them."""
    user_card, order_card = _card("user-agent"), _card("order-agent")
    user_resp = _chain(
        agent_name="user-agent",
        contribution="输入 username=张三，输出 user_id，供步骤 2 查询订单使用",
        missing_requirements=["订单/购买记录数据（步骤 2）"],
        contributing_steps=[1],
    )
    order_resp = _chain(
        agent_name="order-agent",
        contribution="需补齐 user_id，输出该用户的商品列表，对应最终结果",
        missing_requirements=["user_id"],
        contributing_steps=[2],
    )
    plan = MultiRootTaskPlan(
        reasoning="步骤链：用户名→user_id→商品",
        requirements=["用户标识", "购买商品"],
        needs_split=True,
        tasks=[
            MultiRootTask(
                id=1,
                description="把张三换成 user_id",
                agent="user-agent",
                covers=["用户标识"],
            ),
            MultiRootTask(
                id=2,
                description="按 user_id 查张三买过的商品",
                agent="order-agent",
                depends_on=[1],
                covers=["购买商品"],
            ),
        ],
    )
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(
        return_value=[(user_card, user_resp), (order_card, order_resp)]
    )
    agent._plan_cross_root_tasks = AsyncMock(return_value=plan)

    step, multi, cards, _rps, meta = await agent.get_plan_by_broadcast(
        "张三买了哪些东西", "u", "r", "t"
    )
    assert step is None
    assert multi is plan
    assert [c.name for c in cards] == ["user-agent", "order-agent"]
    assert meta["execution_strategy"] == "multi_root"
    agent._plan_cross_root_tasks.assert_awaited()


@pytest.mark.asyncio
async def test_contributor_only_llm_collapse_is_rejected():
    user_card, order_card = _card("user-agent"), _card("order-agent")
    pair = [
        (user_card, _chain(agent_name="user-agent")),
        (order_card, _chain(agent_name="order-agent")),
    ]
    collapsed = MultiRootTaskPlan(
        needs_split=False,
        requirements=["购买"],
        tasks=[MultiRootTask(id=1, description="张三买了哪些东西", agent="user-agent", covers=["购买"])],
    )
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=pair)
    agent._plan_cross_root_tasks = AsyncMock(return_value=collapsed)

    step, multi, cards, _rps, meta = await agent.get_plan_by_broadcast(
        "张三买了哪些东西", "u", "r", "t"
    )
    assert step is None
    assert multi is None
    assert cards == []
    assert meta == {}


@pytest.mark.asyncio
async def test_contributor_only_planning_failure_does_not_pick_a_fake_owner():
    pair = [
        (_card("user-agent"), _chain(agent_name="user-agent")),
        (_card("order-agent"), _chain(agent_name="order-agent")),
    ]
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=pair)
    agent._plan_cross_root_tasks = AsyncMock(return_value=None)

    step, multi, cards, _rps, meta = await agent.get_plan_by_broadcast("张三买了哪些东西", "u", "r", "t")
    assert (step, multi, cards, meta) == (None, None, [], {})


@pytest.mark.asyncio
async def test_single_chain_handler_stays_single_root():
    card = _card("order-agent")
    resp = _chain(
        agent_name="order-agent",
        can_handle=True,
        can_contribute=True,
        confidence=0.7,
        handle_score=0.7,
        contributing_steps=[1],
    )
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(card, resp)])
    agent._plan_cross_root_tasks = AsyncMock(side_effect=AssertionError("should not plan"))

    step, multi, cards, _rps, meta = await agent.get_plan_by_broadcast(
        "统计上个月每个商品的销量排名", "u", "r", "t"
    )
    assert multi is None
    assert step is not None and step.agent == "order-agent"
    assert cards == [card]
    assert meta.get("execution_strategy") == "single"


def test_dominant_fast_path_rejects_untrusted_evidence():
    agent = _agent()
    card = _card("db-agent")
    resp = _chain(
        agent_name="db-agent",
        can_handle=True,
        can_contribute=True,
        confidence=0.9,
        evidence_grade="C",
        handle_score=0.9,
    )
    assert agent._pick_dominant_single_root([(card, resp)], []) is None


def test_dominant_fast_path_accepts_trusted_single_handle():
    agent = _agent()
    card = _card("db-agent")
    resp = _chain(
        agent_name="db-agent",
        can_handle=True,
        can_contribute=True,
        confidence=0.9,
        evidence_grade="A",
        handle_score=0.9,
    )
    picked = agent._pick_dominant_single_root([(card, resp)], [])
    assert picked is not None
    assert picked[0] is card
    assert picked[2] == "only_high_confidence_handle"


def test_payload_roundtrip_keeps_chain_fields():
    raw = {
        "can_handle": False,
        "can_contribute": True,
        "confidence": 1.0,
        "reason": "步骤1 满分；步骤2 D=0",
        "agent_name": "user-agent",
        "agent_url": "http://u",
        "contribution": "输入 username=张三，输出 user_id，供步骤 2 查询订单使用",
        "score_version": "capability-chain-v1",
        "evidence_grade": "A",
        "threshold": 0.7,
        "handle_score": 0.0,
        "steps": [{"step_id": 1, "description": "用户名→user_id", "step_score": 1.0, "is_final": False}],
        "contributing_steps": [1],
        "missing_requirements": ["订单/购买记录数据（步骤 2）"],
        "risks": ["张三可能对应多个用户"],
        "latency_ms": 12,
    }
    resp = _capability_response_from_payload(
        raw,
        default_name="fallback",
        default_url="http://x",
        route_path=["user-agent"],
        route_paths=[{"path": ["user-agent"], "confidence": 1.0}],
        latency_ms=12,
    )
    assert resp.is_chain_scored
    assert resp.evidence_grade == "A"
    assert resp.contributing_steps == [1]
    assert resp.missing_requirements == ["订单/购买记录数据（步骤 2）"]
    line = _format_capable_agent_line(_card("user-agent"), resp)
    assert "evidence_grade: A" in line
    assert "missing_requirements" in line
    assert "contributing_steps" in line


def test_sg_expert_payload_roundtrip_keeps_chain_protocol():
    """SG Orchestrator dumps Expert aggregate JSON; routing must keep chain fields."""
    raw = {
        "can_handle": True,
        "can_contribute": False,
        "confidence": 0.91,
        "reason": "Member sd-a can handle the query",
        "agent_name": "sales-group",
        "contribution": "输入订单号，输出订单明细",
        "score_version": "capability-chain-v1",
        "evidence_grade": "solid",
        "threshold": 0.6,
        "handle_score": 0.91,
        "steps": [{"step_id": 1, "name": "I", "score": 0.9, "evidence_strength": "solid"}],
        "contributing_steps": [1],
        "domain_verdict": "has",
        "has_external_dependency": False,
        "member_results": [
            {
                "agent_name": "sd-a",
                "can_handle": True,
                "score_version": "capability-chain-v1",
                "domain_verdict": "has",
            }
        ],
    }
    resp = _capability_response_from_payload(
        raw,
        default_name="sales-group",
        default_url="http://sg",
        route_path=["sales-group"],
        route_paths=[{"path": ["sales-group"], "confidence": 0.91}],
        latency_ms=40,
    )
    assert resp.is_chain_scored is True
    assert resp.domain_verdict == "has"
    assert resp.steps[0]["name"] == "I"
    assert resp.contributing_steps == [1]
    assert resp.has_external_dependency is False
    assert resp.member_results[0]["agent_name"] == "sd-a"


def test_normalize_skips_regex_for_chain_scored_complete_contribution():
    agent = _agent()
    resp = _chain(
        agent_name="user-agent",
        contribution="输入 username=张三，输出 user_id，供步骤 2 查询订单使用",
    )
    out = RoutingAgent._normalize_capability_check_response(agent, resp)
    assert out.can_contribute is True


def test_normalize_drops_chain_contributor_with_empty_contribution():
    agent = _agent()
    resp = _chain(agent_name="user-agent", contribution="")
    out = RoutingAgent._normalize_capability_check_response(agent, resp)
    assert out.can_contribute is False


# ── Simple-mode: top 3 sorted candidates (handlers first, contributors follow) ─────


@pytest.mark.asyncio
async def test_simple_handler_ranks_before_contributor():
    """Sort key puts handler ahead of contributor.  db-agent wins."""
    db = _card("db-agent")
    user = _card("user-agent")
    db_resp = _chain(agent_name="db-agent", can_handle=True, confidence=0.65)
    user_resp = _chain(agent_name="user-agent", can_contribute=True, confidence=1.0)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(db, db_resp), (user, user_resp)])
    step, rps, meta = await agent.get_best_agent_by_broadcast("张三买了哪些东西", "u", "r", "t")
    assert step is not None and step.agent == "db-agent"
    # contributor still in pool for delegation
    pool_names = [e["agent_name"] for e in meta[ROUTING_AGENT_POOL_KEY]]
    assert "user-agent" in pool_names


@pytest.mark.asyncio
async def test_simple_single_handler_direct_pick():
    """1 candidate → direct pick, no LLM round-trip."""
    db = _card("db-agent")
    db_resp = _chain(agent_name="db-agent", can_handle=True, confidence=0.9, handle_score=0.9)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(db, db_resp)])
    step, rps, meta = await agent.get_best_agent_by_broadcast("统计上个月商品销量排名", "u", "r", "t")
    assert step is not None and step.agent == "db-agent"


@pytest.mark.asyncio
async def test_simple_single_contributor_direct_pick():
    """No handler → single contributor wins (sort picks it, 1 candidate → direct)."""
    user = _card("user-agent")
    user_resp = _chain(agent_name="user-agent", can_contribute=True, confidence=0.85)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(user, user_resp)])
    step, rps, meta = await agent.get_best_agent_by_broadcast("张三买了哪些东西", "u", "r", "t")
    assert step is not None and step.agent == "user-agent"


@pytest.mark.asyncio
async def test_simple_two_contributors_pre_make_plan():
    """No handler + 2 contributors → Pre-Make-Plan picks one."""
    user = _card("user-agent")
    gateway = _card("gateway-agent")
    user_resp = _chain(agent_name="user-agent", can_contribute=True, confidence=0.85)
    gw_resp = _chain(agent_name="gateway-agent", can_contribute=True, confidence=0.72)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(user, user_resp), (gateway, gw_resp)])
    agent._select_by_pre_make_plan = AsyncMock(return_value=(user, user_resp))
    step, rps, meta = await agent.get_best_agent_by_broadcast("张三买了哪些东西", "u", "r", "t")
    assert step is not None and step.agent == "user-agent"


@pytest.mark.asyncio
async def test_simple_two_handlers_pre_make_plan():
    """2 handlers → Pre-Make-Plan selection."""
    db = _card("db-agent")
    report = _card("report-agent")
    db_resp = _chain(agent_name="db-agent", can_handle=True, confidence=0.8)
    report_resp = _chain(agent_name="report-agent", can_handle=True, confidence=0.95)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=[(report, report_resp), (db, db_resp)])
    agent._select_by_pre_make_plan = AsyncMock(return_value=(report, report_resp))
    step, rps, meta = await agent.get_best_agent_by_broadcast("生成上月销售周报", "u", "r", "t")
    assert step is not None and step.agent == "report-agent"


@pytest.mark.asyncio
async def test_simple_candidates_capped_at_three():
    """6 agents → only top 3 (by sort_key) enter Pre-Make-Plan."""
    cards = [_card(f"agent-{i}") for i in range(6)]
    resps = [_chain(agent_name=f"agent-{i}", can_handle=True, confidence=0.9 - i * 0.08)
             for i in range(6)]
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(return_value=list(zip(cards, resps)))
    agent._select_by_pre_make_plan = AsyncMock(return_value=(cards[0], resps[0]))
    step, rps, meta = await agent.get_best_agent_by_broadcast("query", "u", "r", "t")
    assert step is not None and step.agent == "agent-0"
    call_args = agent._select_by_pre_make_plan.call_args[0][1]
    assert len(call_args) == 3


@pytest.mark.asyncio
async def test_simple_mixed_handlers_and_contributors():
    """1 handler + 2 contributors → 3 candidates enter Pre-Make-Plan.
    Handler ranks first by sort_key."""
    db = _card("db-agent")
    user = _card("user-agent")
    order = _card("order-agent")
    db_resp = _chain(agent_name="db-agent", can_handle=True, confidence=0.65)
    user_resp = _chain(agent_name="user-agent", can_contribute=True, confidence=1.0)
    order_resp = _chain(agent_name="order-agent", can_contribute=True, confidence=0.8)
    agent = _agent()
    agent.broadcast_capability_check = AsyncMock(
        return_value=[(user, user_resp), (order, order_resp), (db, db_resp)]
    )
    agent._select_by_pre_make_plan = AsyncMock(return_value=(db, db_resp))
    step, rps, meta = await agent.get_best_agent_by_broadcast("张三买了哪些东西", "u", "r", "t")
    assert step is not None and step.agent == "db-agent"
    # All 3 should be in routing_agent_pool
    assert len(meta[ROUTING_AGENT_POOL_KEY]) == 3


def test_capability_progress_md_matches_friendly_format():
    query = "用户ID U001 → 查询支付流水 → 最近几笔支付记录及状态"
    resp = CapabilityCheckResponse(
        can_handle=True,
        can_contribute=True,
        confidence=1.0,
        reason="领域交集：明确有 — 问题领域：L1 订单查询；可独立完成。",
        agent_name="order-agent",
        contribution="输入用户ID=U001，输出订单号及订单状态列表，满足用户对支付记录及状态的查询需求",
        score_version="capability-chain-v1",
        evidence_grade="A",
        threshold=0.7,
        handle_score=1.0,
        contributing_steps=[1],
        domain_verdict="has",
        has_external_dependency=False,
        latency_ms=7320,
        risks=["订单状态中'待支付'、'已完成'等可视为支付相关，但'已取消'可能不属于支付流水，需用户确认筛选范围"],
        steps=[
            {
                "step_id": 1,
                "description": "按用户ID U001 查询订单流水，筛选出支付相关记录（待支付、已完成等状态）",
                "operation": "lookup",
                "is_final": True,
                "inputs": [{"name": "用户ID", "source": "query"}],
                "outputs": ["订单号列表", "订单状态列表"],
                "constraints": ["只读"],
                "scores": {"I": 1.0, "D": 1.0, "O": 1.0, "R": 1.0, "C": 1.0},
                "step_score": 1.0,
                "checklists": {
                    "I": {"required": ["用户ID"], "matched": ["用户ID"], "evidence_strength": "solid"},
                    "D": {
                        "required": ["订单流水数据（含订单号、状态、用户ID）"],
                        "matched": ["订单流水数据（含订单号、状态、用户ID）"],
                        "evidence_strength": "solid",
                    },
                    "R": {
                        "required": ["订单号列表", "订单状态列表"],
                        "matched": ["订单号列表", "订单状态列表"],
                        "evidence_strength": "solid",
                    },
                    "C": {"required": ["只读"], "matched": ["只读"], "evidence_strength": "solid"},
                },
                "evidence": [
                    '技能正文：按用户ID查询：grep "U001" data/orders.txt',
                    "技能正文：输出：订单号、订单状态、商品ID、用户ID",
                ],
            }
        ],
    )
    md = _render_capability_progress_md("order-agent", resp, query=query)
    assert "## Capability Check — agent=`order-agent`" in md
    assert "独立处理" in md and "can_handle=True" in md
    assert "贡献步骤" in md and "can_contribute=True" in md
    assert "**handle_score**: `1.000`" in md
    assert "**domain_verdict**: `has`" in md
    assert "**has_external_dependency**: `False`" in md
    assert "**contributing_steps**: `[1]`" in md
    assert "**latency_ms**: `7320`" in md
    assert "### §〇 前置检查：领域交集判定" in md
    assert "| **I** | 输入匹配 |" in md
    assert "| **O** | 操作能力 | — | — |" in md
    assert "### LLM 结构化理由（reason）" in md

    combined = _render_broadcast_capability_progress_md(
        query,
        [(_card("order-agent"), resp), (_card("logistics-query"), _chain(agent_name="logistics-query", can_handle=True))],
    )
    assert combined.startswith("# 广播能力检查结果")
    assert "order-agent [handle]" in combined
    assert "logistics-query [handle]" in combined


def test_capability_payload_parses_domain_verdict():
    resp = _capability_response_from_payload(
        {
            "can_handle": True,
            "can_contribute": True,
            "confidence": 1.0,
            "domain_verdict": "has",
            "has_external_dependency": True,
            "score_version": "capability-chain-v1",
        },
        default_name="order-agent",
        default_url="http://x",
        route_path=["order-agent"],
        route_paths=[],
        latency_ms=10,
    )
    assert resp.domain_verdict == "has"
    assert resp.has_external_dependency is True


def test_pre_make_plan_progress_md_lists_tasks_and_thought():
    query = "用户ID U001 的最近支付记录"
    resp = _chain(agent_name="order-agent", can_handle=True, can_contribute=True)
    plan = {
        "original_query": query,
        "thought_process": "Step1 订单流水属于 order-agent；Step6 单任务即可。",
        "tasks": [
            {
                "id": 1,
                "description": "按用户ID U001 查询最近支付记录及状态",
                "agent": "order-agent",
                "depends_on": [],
            }
        ],
    }
    md = _render_pre_make_plan_md("order-agent", plan, query=query, resp=resp)
    assert "## Pre-Make-Plan — agent=`order-agent`" in md
    assert "**任务数**: `1`" in md
    assert "`can_handle=True`" in md
    assert "**agent**: `order-agent`" in md
    assert "**depends_on**: `[]`" in md
    assert "按用户ID U001 查询最近支付记录及状态" in md
    assert "### 思考过程（thought_process）" in md

    failed = _render_pre_make_plan_md("logistics-query", None, query=query)
    assert "未返回有效规划" in failed

    combined = _render_broadcast_pre_make_plan_progress_md(
        query,
        [
            (_card("order-agent"), resp, plan),
            (_card("logistics-query"), _chain(agent_name="logistics-query"), None),
        ],
    )
    assert combined.startswith("# Pre-Make-Plan 结果")
    assert "order-agent [handle]" in combined
    assert "logistics-query [contribute]" in combined
    assert "收到 **1/2** 个 Agent 的规划" in combined


def test_pre_make_plan_selection_md_includes_reason_and_thought():
    md = _render_pre_make_plan_selection_md(
        "logistics-query",
        candidate_count=2,
        reason="物流查询技能覆盖运单号与轨迹，规划完整且能力实证为实据。",
        thought="Step1 用户要查物流轨迹。",
        source="llm",
    )
    lines = md.splitlines()
    assert lines[0] == "选定 logistics-query 作为最佳路由目标"
    assert lines[1] == "物流查询技能覆盖运单号与轨迹，规划完整且能力实证为实据。"
    assert "Step1 用户要查物流轨迹。" in md


class _SelectRouting(_FakeRouting):
    _llm_select_best_plan = RoutingAgent._llm_select_best_plan


def _select_candidates():
    plan = {
        "tasks": [{"task_name": "t1", "agent": "a", "description": "d"}],
        "thought_process": "plan",
    }
    return [
        (_card("logistics-query"), _chain(agent_name="logistics-query"), plan),
        (_card("ticket-query"), _chain(agent_name="ticket-query"), plan),
    ]


def test_pre_make_plan_select_env_defaults(monkeypatch):
    monkeypatch.delenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", raising=False)
    monkeypatch.delenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", raising=False)
    assert _pre_make_plan_select_timeout() == 60.0
    assert _pre_make_plan_select_max_attempts() == 3
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", "0")
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", "nope")
    assert _pre_make_plan_select_timeout() == 60.0
    assert _pre_make_plan_select_max_attempts() == 3
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", "45.5")
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", "2")
    assert _pre_make_plan_select_timeout() == 45.5
    assert _pre_make_plan_select_max_attempts() == 2


@pytest.mark.asyncio
async def test_llm_select_best_plan_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", "5")
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", "3")
    calls = {"n": 0}

    async def _flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {
            "selected_agent_index": 2,
            "thought": "ok",
            "reason": "ticket-query better",
        }

    monkeypatch.setattr("routing_agent.server.invoke_llm_with_tool", _flaky)
    agent = _SelectRouting()
    card, resp, meta = await agent._llm_select_best_plan(
        query="张三的包裹现在到哪了？",
        candidates_with_plans=_select_candidates(),
        user_id="u",
        run_id="r",
        trace_id="t",
    )
    assert calls["n"] == 3
    assert card.name == "ticket-query"
    assert meta["source"] == "llm"
    assert meta["reason"] == "ticket-query better"
    assert resp.agent_name == "ticket-query"


@pytest.mark.asyncio
async def test_llm_select_best_plan_timeout_retries_then_fallback(monkeypatch):
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", "0.05")
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", "3")
    calls = {"n": 0}

    async def _hang(*_args, **_kwargs):
        calls["n"] += 1
        await asyncio.sleep(10)
        return {"selected_agent_index": 2, "thought": "", "reason": "late"}

    monkeypatch.setattr("routing_agent.server.invoke_llm_with_tool", _hang)
    agent = _SelectRouting()
    card, _resp, meta = await agent._llm_select_best_plan(
        query="张三的包裹现在到哪了？",
        candidates_with_plans=_select_candidates(),
        user_id="u",
        run_id="r",
        trace_id="t",
    )
    assert calls["n"] == 3
    assert card.name == "logistics-query"
    assert meta["source"] == "fallback_first"
    assert "timeout" in meta["reason"]
    assert "3 次" in meta["reason"]


@pytest.mark.asyncio
async def test_llm_select_best_plan_none_then_success(monkeypatch):
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_TIMEOUT", "5")
    monkeypatch.setenv("PRE_MAKE_PLAN_SELECT_MAX_ATTEMPTS", "3")
    calls = {"n": 0}

    async def _none_then_ok(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {
            "selected_agent_index": 1,
            "thought": "first",
            "reason": "logistics",
        }

    monkeypatch.setattr("routing_agent.server.invoke_llm_with_tool", _none_then_ok)
    agent = _SelectRouting()
    card, _resp, meta = await agent._llm_select_best_plan(
        query="张三的包裹现在到哪了？",
        candidates_with_plans=_select_candidates(),
        user_id="u",
        run_id="r",
        trace_id="t",
    )
    assert calls["n"] == 2
    assert card.name == "logistics-query"
    assert meta["source"] == "llm"
    assert meta["reason"] == "logistics"
