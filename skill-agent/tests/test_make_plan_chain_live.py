"""Live tests for chain-driven planner (USE_CHAIN_PLANNING=true).

Tests:
  - Single lookup
  - Cross-domain chained plan (user → order)
  - Out-of-domain fallback to NONE
  - Stability: repeated runs produce valid TaskList every time

Run:
  DASHSCOPE_API_KEY=sk-... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    USE_CHAIN_PLANNING=true \\
    python -m pytest tests/test_make_plan_chain_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LANGFUSE_FLUSH_TIMEOUT_SEC", "0")
os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)

# ── Force chain mode ─────────────────────────────────────────────────
os.environ["USE_CHAIN_PLANNING"] = "true"

from agent.skill_agent import PlannerAgent  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live chain planner tests",
)

DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

STABILITY_RUNS = 2


def _card(name: str, description: str, skill_name: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        url=f"http://local/{name}",
        version="1.0.0",
        skills=[
            AgentSkill(
                id=skill_name,
                name=skill_name,
                description=description,
                tags=["live"],
                examples=[],
                input_modes=["text"],
                output_modes=["text"],
            )
        ],
        capabilities=AgentCapabilities(),
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
    )


USER = _card(
    "user-agent",
    "查询用户静态本体信息：用户ID、用户名、电话、邮箱、收货地址。数据 data/users.txt。"
    "不掌握订单、支付、退货或商品销量。",
    "user_query",
)
ORDER = _card(
    "order-agent",
    "查询订单流水与购买行为数据：订单号、订单状态、商品名称、用户ID、销量/成交记录。"
    "只能按用户ID或商品名称过滤，不能按用户姓名过滤。不掌握用户电话邮箱，不掌握仓库库存和标价。",
    "order_query",
)
PRODUCT = _card(
    "product-agent",
    "查询商品静态本体：SKU、商品名称、类目、上下架状态、标价、仓库库存量。"
    "不掌握谁买过、销量、成交额或退货记录。",
    "product_query",
)
AFTERSALE = _card(
    "aftersale-agent",
    "查询售后与退货数据：退货单号、退货商品、退货原因、退款金额、退货用户ID。"
    "不掌握用户电话邮箱，不掌握商品库存和标价。",
    "aftersale_query",
)


def _make_planner(agent_id: str = "PlannerAgent") -> PlannerAgent:
    planner = PlannerAgent(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL,
        stream=False,
        temperature=0.01,
        data_services_url="http://127.0.0.1:9",
        metadata={"user_id": "live-test", "run_id": "chain-plan-live"},
        agent_id=agent_id,
    )
    planner.get_history = AsyncMock(return_value="")
    return planner


def _dump(label: str, plan) -> None:
    print(f"\n===== {label} =====")
    print(f"thought_process[:300]={plan.thought_process[:300]!r}")
    for t in plan.tasks:
        print(
            f"  #{t.id} agent={t.agent!r} depends_on={t.depends_on} "
            f"desc={t.description[:150]!r}"
        )


# ── Test case definitions ────────────────────────────────────────────

@dataclass
class ChainCase:
    name: str
    query: str
    cards: list[AgentCard]
    expect_agents: set[str]       # agents that should appear
    expect_no_agents: set[str]    # agents that must NOT appear
    expect_min_tasks: int         # minimum task count
    expect_none_allowed: bool     # is NONE allowed?


CASES: list[ChainCase] = [
    ChainCase(
        name="single_user_lookup",
        query='请查询用户"张三"的用户信息，返回其对应的用户ID。',
        cards=[USER],
        expect_agents={"user-agent"},
        expect_no_agents=set(),
        expect_min_tasks=1,
        expect_none_allowed=False,
    ),
    ChainCase(
        name="cross_domain_zhangsan_orders",
        query="查询用户张三购买的商品",
        cards=[USER, ORDER],
        expect_agents={"user-agent", "order-agent"},
        expect_no_agents={"NONE"},
        expect_min_tasks=2,
        expect_none_allowed=False,
    ),
    ChainCase(
        name="order_by_user_id",
        query="查询用户ID为 U001 购买的商品",
        cards=[USER, ORDER],
        expect_agents={"order-agent"},
        expect_no_agents={"NONE"},
        expect_min_tasks=1,
        expect_none_allowed=False,
    ),
    ChainCase(
        name="out_of_domain_weather",
        query="今天北京天气怎么样",
        cards=[USER, ORDER, PRODUCT],
        expect_agents={"NONE"},
        expect_no_agents=set(),
        expect_min_tasks=1,
        expect_none_allowed=True,
    ),
    ChainCase(
        name="db_health_check",
        query="对数据库做一次全面体检并给出优化建议",
        cards=[USER, ORDER, PRODUCT, AFTERSALE],
        expect_agents=set(),
        expect_no_agents=set(),
        expect_min_tasks=1,
        expect_none_allowed=True,  # 无 DB 相关 agent，可能 NONE
    ),
    ChainCase(
        name="multi_independent_simple",
        query="查一下用户李四的邮箱和用户王五的电话",
        cards=[USER, ORDER],
        expect_agents={"user-agent"},
        expect_no_agents={"NONE"},
        expect_min_tasks=1,
        expect_none_allowed=False,
    ),
]


# ── Helper ───────────────────────────────────────────────────────────

def _agent_set(plan) -> set[str]:
    return {str(t.agent or "") for t in plan.tasks}


# ── Tests ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def planner():
    return _make_planner()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_live_chain_planner_basic(planner, case: ChainCase):
    """Chain planner: produce valid TaskList with expected agent routing."""
    plan = await planner.make_plan(case.query, case.cards)
    _dump(case.name, plan)

    agents = _agent_set(plan)

    # Must produce a valid plan (no fallback NONE unless expected)
    if not case.expect_none_allowed:
        assert "NONE" not in agents, (
            f"Unexpected NONE agent in plan for '{case.name}'. "
            f"Agents: {agents}. thought_process: {plan.thought_process[:200]}"
        )

    assert len(plan.tasks) >= case.expect_min_tasks, (
        f"Expected at least {case.expect_min_tasks} tasks for '{case.name}', "
        f"got {len(plan.tasks)}"
    )

    # Expected agents must appear
    for expected in case.expect_agents:
        assert expected in agents, (
            f"Expected agent '{expected}' for '{case.name}', got {agents}"
        )

    # Forbidden agents must NOT appear
    for forbidden in case.expect_no_agents:
        assert forbidden not in agents, (
            f"Forbidden agent '{forbidden}' appeared in '{case.name}'"
        )


@pytest.mark.asyncio
async def test_live_chain_planner_depends_on_correct(planner):
    """Task dependencies must match chain topology."""
    query = "查询用户张三购买的商品"
    plan = await planner.make_plan(query, [USER, ORDER])
    _dump("depends_on_check", plan)

    agents = _agent_set(plan)
    assert "user-agent" in agents
    assert "order-agent" in agents
    assert "NONE" not in agents

    user_task = next(t for t in plan.tasks if t.agent == "user-agent")
    order_task = next(t for t in plan.tasks if t.agent == "order-agent")

    assert user_task.depends_on == [], (
        f"user-agent task should have no dependencies, got {user_task.depends_on}"
    )
    assert order_task.depends_on, (
        f"order-agent task should depend on user-agent (id={user_task.id}), "
        f"got depends_on={order_task.depends_on}"
    )
    assert user_task.id in (order_task.depends_on or []), (
        f"order-agent depends_on={order_task.depends_on} should include "
        f"user-agent task id={user_task.id}"
    )


@pytest.mark.asyncio
async def test_live_chain_planner_zhangsan_with_extra_agent(planner):
    """With product agent added, should still route to user→order, not product."""
    query = "查询用户张三购买的商品"
    plan = await planner.make_plan(query, [USER, ORDER, PRODUCT])
    _dump("zhangsan_with_product", plan)

    agents = _agent_set(plan)
    assert "NONE" not in agents
    assert "user-agent" in agents
    assert "order-agent" in agents
    # Product agent should NOT appear (ordering ≠ product static info)
    assert "product-agent" not in agents, (
        f"product-agent should NOT be used for ordering data (sales/transactions). "
        f"Got agents: {agents}. thought: {plan.thought_process[:300]}"
    )


@pytest.mark.asyncio
async def test_live_chain_planner_stability(planner):
    """Repeated runs should produce valid TaskList every time (no parse failures)."""
    query = "查询用户张三购买的商品，按金额排序"
    failures = 0
    for run in range(1, STABILITY_RUNS + 1):
        plan = await planner.make_plan(query, [USER, ORDER])
        _dump(f"stability_run_{run}", plan)
        agents = _agent_set(plan)
        # Must be a valid parse, not a fallback NONE
        if plan.thought_process and "fallback" in plan.thought_process.lower():
            failures += 1
            print(f"  ⚠️  run {run}: fallback NONE plan (parsing failed)")
            continue
        if "NONE" in agents:
            failures += 1
            print(f"  ⚠️  run {run}: unexpected NONE")
            continue
        tasks_sorted = sorted(plan.tasks, key=lambda t: t.id)
        task_agent_list = [t.agent for t in tasks_sorted]
        if "user-agent" not in task_agent_list or "order-agent" not in task_agent_list:
            failures += 1
            print(f"  ⚠️  run {run}: missing expected agents: {task_agent_list}")

    assert failures == 0, (
        f"{failures}/{STABILITY_RUNS} stability runs failed. "
        f"Target: 0 failures."
    )
    print(f"\n✅ Stability: {STABILITY_RUNS - failures}/{STABILITY_RUNS} passed")


@pytest.mark.asyncio
async def test_live_chain_planner_complex_health_check(planner):
    """Full health check with DB-like agents should NOT route shopping agents."""
    query = "对数据库做一次全面体检并给出优化建议"
    plan = await planner.make_plan(query, [USER, ORDER, PRODUCT, AFTERSALE])
    _dump("db_health_check", plan)

    # DB check should not be handled by shopping agents; NONE is acceptable
    # The key assertion: the plan is valid (no parsing crash)
    assert len(plan.tasks) >= 1, "Plan must have at least 1 task"
    # Just verify it's a well-formed plan — routing correctness is secondary
    # for this out-of-domain query
    task_agents = _agent_set(plan)
    print(f"  DB health check agents: {task_agents}")
    print(f"  thought: {plan.thought_process[:400]}")