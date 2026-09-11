"""Live tests: make_plan_jsonstring must 100% hydrate a real TaskList.

These 10 cases stress long prompts / history / replan JSON. Assertions only
check that the LLM text was parsed into a valid TaskList object — not routing
accuracy. A parse-failure fallback NONE plan is treated as failure.

Run:
  DASHSCOPE_API_KEY=sk-... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    python -m pytest tests/test_make_plan_jsonstring_complex_live.py -q -s
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

from agent.skill_agent import PlannerAgent, PlannerTask, TaskList  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live make_plan_jsonstring tests",
)

DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

STABILITY_RUNS = 2
PARSE_FAIL_MARKER = "jsonstring attempts"


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
    "查询退货/退款流水：退货单号、退货商品、退款状态、用户ID。"
    "只能按用户ID或订单号过滤，不能按姓名过滤。不掌握用户画像和商品标价。",
    "aftersale_query",
)
PAYMENT = _card(
    "payment-agent",
    "查询支付流水：支付单号、支付状态、金额、关联订单号、用户ID。"
    "只能按用户ID或订单号过滤。不掌握商品库存和用户电话。",
    "payment_query",
)

POOL = [USER, ORDER, PRODUCT, AFTERSALE, PAYMENT]


def _dump(label: str, plan: TaskList) -> None:
    print(f"\n===== {label} =====")
    print(f"type={type(plan).__name__} tasks={len(plan.tasks)}")
    print(f"thought_process[:200]={plan.thought_process[:200]!r}")
    for t in plan.tasks:
        print(
            f"  #{t.id} agent={t.agent!r} depends_on={list(t.depends_on)} "
            f"desc={t.description[:120]!r}"
        )


def assert_llm_produced_tasklist(plan, cards) -> None:
    """Fail unless *plan* is a hydrated TaskList from LLM JSON, not the parse fallback.

    Every field except ``tasks[].depends_on`` must be non-empty. ``depends_on``
    may be ``[]``.
    """
    assert isinstance(plan, TaskList), f"expected TaskList, got {type(plan)}"
    assert PARSE_FAIL_MARKER not in (plan.thought_process or ""), (
        "make_plan_jsonstring fell back after JSON parse/hydrate failures"
    )
    assert str(plan.thought_process).strip(), "thought_process must not be empty"
    assert str(plan.original_query).strip(), "original_query must not be empty"
    assert plan.tasks, "tasks must not be empty"
    assert all(isinstance(t, PlannerTask) for t in plan.tasks)

    valid = {str(getattr(c, "name", "") or "").strip() for c in cards}
    valid.discard("")
    valid.add("NONE")
    ids = {t.id for t in plan.tasks}
    assert len(ids) == len(plan.tasks), f"duplicate task ids: {ids}"

    for t in plan.tasks:
        assert t.id is not None, "task.id must not be empty"
        assert isinstance(t.id, int), f"task.id must be int, got {t.id!r}"
        assert str(t.description).strip(), f"task {t.id} description must not be empty"
        agent = str(t.agent).strip()
        assert agent, f"task {t.id} agent must not be empty"
        assert agent in valid or agent.upper() == "NONE", (
            f"task {t.id} agent={agent!r} not in {sorted(valid)}"
        )
        assert t.depends_on is not None, f"task {t.id} depends_on missing"
        assert isinstance(t.depends_on, list), f"task {t.id} depends_on not a list"
        for dep in t.depends_on:
            assert isinstance(dep, int), f"task {t.id} depends_on item {dep!r}"
            assert dep in ids, f"task {t.id} depends_on {dep} missing"
            assert dep != t.id, f"task {t.id} self-depends"

    rebuilt = TaskList.model_validate(plan.model_dump())
    assert isinstance(rebuilt, TaskList)
    assert len(rebuilt.tasks) == len(plan.tasks)
    assert rebuilt.thought_process.strip()
    assert rebuilt.original_query.strip()
    for t in rebuilt.tasks:
        assert t.description.strip()
        assert t.agent.strip()


@dataclass
class ComplexCase:
    name: str
    query: str
    cards: list
    history: str = ""
    group_memory: str = ""
    replan_context: dict | None = None
    replan_guidance: str = ""


CASES = [
    ComplexCase(
        "c1_noun_trap_product_sales",
        "iPhone 15 Pro 的销量是多少",
        [USER, ORDER, PRODUCT],
    ),
    ComplexCase(
        "c2_three_hop_name_order_stock",
        "张三买的那款手机现在库存还剩多少",
        [USER, ORDER, PRODUCT, AFTERSALE],
    ),
    ComplexCase(
        "c3_reuse_resolved_user_id",
        "查询用户张三购买的商品",
        [USER, ORDER, PRODUCT],
        group_memory=(
            "[执行上下文] 任务#1 user-agent 已完成：用户张三对应的用户ID是 U003，"
            "电话 13800000003，邮箱 zhangsan@example.com。"
        ),
        replan_context={
            "executed_tasks": [
                {
                    "task_id": 1,
                    "agent": "user-agent",
                    "status": "completed",
                    "result": "张三 -> 用户ID=U003",
                }
            ]
        },
    ),
    ComplexCase(
        "c4_replan_after_order_name_failure",
        "查询用户张三购买的商品",
        [USER, ORDER, PRODUCT],
        replan_guidance=(
            "上次 order-agent 按姓名“张三”查订单失败：orders.txt 只有用户ID。"
            "必须改变策略，先解析姓名到用户ID。"
        ),
        replan_context={
            "executed_tasks": [
                {
                    "task_id": 1,
                    "agent": "order-agent",
                    "status": "failed",
                    "result": "无法按姓名过滤订单，缺少姓名到用户ID映射",
                }
            ]
        },
    ),
    ComplexCase(
        "c5_pronoun_from_history",
        "那他的电话和邮箱呢",
        [USER, ORDER, PRODUCT],
        history=(
            "用户: 查一下李四的用户ID\n"
            "助手: 李四对应的用户ID是 U007。\n"
        ),
    ),
    ComplexCase(
        "c6_parallel_email_and_list_price",
        "查一下张三的邮箱，另外把 iPhone 15 Pro 的标价也告诉我",
        [USER, ORDER, PRODUCT],
    ),
    ComplexCase(
        "c7_refund_behavior_not_product",
        "张三退了哪些货",
        POOL,
    ),
    ComplexCase(
        "c8_mixed_order_and_weather",
        "张三买了什么，另外今天北京天气如何",
        [USER, ORDER, PRODUCT],
    ),
    ComplexCase(
        "c9_compare_two_users_purchases",
        "对比张三和李四分别买了哪些商品",
        [USER, ORDER, PRODUCT],
    ),
    ComplexCase(
        "c10_uid_orders_then_product_attrs",
        "用户ID U002 买过哪些手机，并把这些手机的类目和标价列出来",
        [USER, ORDER, PRODUCT],
    ),
]


def _make_planner() -> PlannerAgent:
    return PlannerAgent(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL,
        stream=False,
        temperature=0.01,
        data_services_url="http://127.0.0.1:9",
        metadata={"user_id": "live-test", "run_id": "make-plan-jsonstring-complex"},
        agent_id="planner-test",
    )


@pytest.fixture(scope="module")
def planner():
    return _make_planner()


async def _run_case(planner: PlannerAgent, case: ComplexCase) -> TaskList:
    object.__setattr__(planner, "get_history", AsyncMock(return_value=case.history))
    return await planner.make_plan_jsonstring(
        case.query,
        case.cards,
        group_memory=case.group_memory,
        replan_context=case.replan_context,
        replan_guidance=case.replan_guidance,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_complex_jsonstring_always_returns_tasklist(planner, case: ComplexCase):
    for run in range(1, STABILITY_RUNS + 1):
        plan = await _run_case(planner, case)
        _dump(f"{case.name} run{run}", plan)
        assert_llm_produced_tasklist(plan, case.cards)
