"""Route-plan decision tests for capability-chain scored broadcast results.

Imports ``routing_agent.server`` with the same heavy-dep mocks used elsewhere
in dac, then drives ``get_plan_by_broadcast`` / ``_pick_dominant_single_root``
with canned CapabilityCheckResponse objects — no live LLM, no network.
"""

from __future__ import annotations

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
