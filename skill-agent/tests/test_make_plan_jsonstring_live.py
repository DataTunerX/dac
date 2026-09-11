"""Live DashScope tests for PlannerAgent.make_plan_jsonstring.

Requires DASHSCOPE_API_KEY. Model default: deepseek-v4-flash-0731.

Run:
  DASHSCOPE_API_KEY=sk-... python -m pytest tests/test_make_plan_jsonstring_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LANGFUSE_FLUSH_TIMEOUT_SEC", "0")
os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)

from agent.skill_agent import PlannerAgent  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live make_plan_jsonstring tests",
)

DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)


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
    "查询用户信息，包括用户ID、用户名、电话和邮箱。数据在 data/users.txt，格式：用户ID|用户名|电话|邮箱。",
    "user_query",
)
ORDER = _card(
    "order-agent",
    "查询订单与购买商品。数据在 data/orders.txt，格式：订单号|订单状态|商品名称|用户ID。只能按用户ID过滤，不能按姓名过滤。",
    "order_query",
)


def _make_planner() -> PlannerAgent:
    planner = PlannerAgent(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL,
        stream=False,
        temperature=0.01,
        data_services_url="http://127.0.0.1:9",
        metadata={"user_id": "live-test", "run_id": "make-plan-jsonstring-live"},
        agent_id="user-agent",
    )
    planner.get_history = AsyncMock(return_value="")
    return planner


def _dump(label: str, plan) -> None:
    print(f"\n===== {label} =====")
    print(f"thought_process[:240]={plan.thought_process[:240]!r}")
    for t in plan.tasks:
        print(
            f"  #{t.id} agent={t.agent!r} depends_on={t.depends_on} "
            f"desc={t.description[:120]!r}"
        )


@pytest.fixture(scope="module")
def planner():
    return _make_planner()


@pytest.mark.asyncio
async def test_live_jsonstring_cross_domain_zhangsan_orders(planner):
    """姓名买了什么：应先 user-agent 解析 ID，再 order-agent 查订单。"""
    query = "查询用户张三购买的商品"
    plan = await planner.make_plan_jsonstring(query, [USER, ORDER])
    _dump("cross_domain", plan)
    agents = [t.agent for t in plan.tasks]
    assert "NONE" not in agents
    assert "user-agent" in agents
    assert "order-agent" in agents
    user_task = next(t for t in plan.tasks if t.agent == "user-agent")
    order_task = next(t for t in plan.tasks if t.agent == "order-agent")
    assert user_task.depends_on == []
    assert order_task.id != user_task.id
    assert user_task.id in (order_task.depends_on or [])


@pytest.mark.asyncio
async def test_live_jsonstring_single_user_lookup(planner):
    query = '请查询用户"张三"的用户信息，返回其对应的用户ID（以及用户名、电话、邮箱）。'
    plan = await planner.make_plan_jsonstring(query, [USER])
    _dump("single_user", plan)
    assert len(plan.tasks) >= 1
    assert plan.tasks[0].agent == "user-agent"
    assert plan.tasks[0].depends_on == []


@pytest.mark.asyncio
async def test_live_jsonstring_order_by_user_id(planner):
    query = "查询用户ID为 U001 购买的商品"
    plan = await planner.make_plan_jsonstring(query, [USER, ORDER])
    _dump("order_by_uid", plan)
    agents = [t.agent for t in plan.tasks]
    assert "order-agent" in agents
    assert "NONE" not in agents
    order_task = next(t for t in plan.tasks if t.agent == "order-agent")
    assert "U001" in order_task.description or "u001" in order_task.description.lower()


@pytest.mark.asyncio
async def test_live_jsonstring_out_of_domain_none(planner):
    query = "今天北京天气怎么样"
    plan = await planner.make_plan_jsonstring(query, [USER, ORDER])
    _dump("out_of_domain", plan)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent.upper() == "NONE"


@pytest.mark.asyncio
async def test_live_make_plan_falls_back_when_tool_call_errors(planner):
    """tool-call 连续失败后应走 jsonstring，且仍能产出跨域计划。"""
    query = "查询用户张三购买的商品"
    with patch(
        "agent.skill_agent.invoke_llm_with_tool",
        AsyncMock(side_effect=RuntimeError("grammar compile timed out")),
    ) as mocked:
        plan = await planner.make_plan(query, [USER, ORDER])
    _dump("fallback_from_tool_error", plan)
    assert mocked.await_count == planner.make_plan_max_attempts
    agents = [t.agent for t in plan.tasks]
    assert "user-agent" in agents
    assert "order-agent" in agents
    assert "NONE" not in agents
