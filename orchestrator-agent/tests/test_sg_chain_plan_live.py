"""Live chain-driven planner tests for SG orchestrator (use_chain=True).

20 business-meaningful test cases + 8 targeted assertion tests.
Validates: chain decomposition, noun-trap avoidance, depends_on topology,
out-of-domain rejection, large-agent-pool precision, stability.

Run:
  DASHSCOPE_API_KEY=sk-... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
  python -m pytest tests/test_sg_chain_plan_live.py -q -s -v
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

# Force chain mode
os.environ["USE_CHAIN_PLANNING"] = "true"

from orchestrator_agent.orchestrator_agent_semantic_group import PlannerAgent  # noqa: E402

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


def _card(name: str, description: str, skill_name: str = "") -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        url=f"http://local/{name}",
        version="1.0.0",
        skills=[
            AgentSkill(
                id=skill_name or name,
                name=skill_name or name,
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


# ── Agent Cards ───────────────────────────────────────────────────────
USER = _card(
    "user-agent",
    "查询用户静态本体信息：用户ID、用户名、电话、邮箱、收货地址、注册时间。"
    "数据 data/users.txt，格式 用户ID|用户名|电话|邮箱|地址|注册时间。"
    "不掌握订单、支付、退货、商品、库存或销量。",
)
ORDER = _card(
    "order-agent",
    "查询订单流水与购买行为数据：订单号、订单状态、商品名称、用户ID、购买数量、成交金额、下单时间。"
    "只能按用户ID或商品名称过滤，不能按用户姓名过滤。"
    "不掌握用户电话邮箱、商品库存和标价、退货数据。",
)
PRODUCT = _card(
    "product-agent",
    "查询商品静态本体：SKU、商品名称、类目、上下架状态、标价、仓库库存量、规格参数。"
    "不掌握谁买过、销量、成交额、退货记录。",
)
AFTERSALE = _card(
    "aftersale-agent",
    "查询售后与退货数据：退货单号、退货商品名称、退货原因、退款金额、退货用户ID、退货时间。"
    "只能按退货用户ID过滤，不能按用户姓名过滤。",
)
PAYMENT = _card(
    "payment-agent",
    "查询支付流水数据：支付单号、支付金额、支付方式、支付时间、关联订单号。"
    "只能按关联订单号过滤。不掌握用户信息、商品信息、退款信息。",
)
LOGISTICS = _card(
    "logistics-agent",
    "查询物流追踪数据：物流单号、承运商、当前状态、各节点时间。"
    "只能按关联订单号过滤。不掌握商品名称、用户电话。",
)
INVENTORY = _card(
    "inventory-agent",
    "查询仓库库存与出入库记录：SKU、仓库名称、当前库存量、安全库存、最近入库/出库时间与数量。"
    "不掌握商品类目、标价、销量、订单数据。",
)
REVIEW = _card(
    "review-agent",
    "查询商品评论数据：评论ID、商品SKU、用户ID、评分(1-5)、评论文本、评论时间。"
    "只能按商品SKU过滤。不掌握商品名称和类目、用户电话和邮箱。",
)
NOTIFY = _card(
    "notify-agent",
    "消息通知服务：支持通过短信、邮件、App推送向指定用户发送通知消息。"
    "需要用户手机号或邮箱，需要通知内容。不掌握用户信息本身，不掌握订单和物流。",
)

ALL_CARDS = [USER, ORDER, PRODUCT, AFTERSALE, PAYMENT, LOGISTICS, INVENTORY, REVIEW, NOTIFY]


# ── Planner ───────────────────────────────────────────────────────────

def _make_planner() -> PlannerAgent:
    planner = PlannerAgent(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL,
        stream=False,
        temperature=0.01,
        data_services_url="http://127.0.0.1:9",
        metadata={"user_id": "live-test-sg", "run_id": "sg-chain-plan-live"},
        enable_history="disable",
    )
    planner.get_history = AsyncMock(return_value="")
    return planner


def _dump(label: str, plan) -> None:
    print(f"\n===== {label} =====")
    print(f"thought[:300]={plan.thought_process[:300]!r}")
    for t in plan.tasks:
        print(
            f"  #{t.id} agent={t.agent!r} depends_on={t.depends_on} "
            f"desc={t.description[:150]!r}"
        )


def _agents(plan) -> set[str]:
    return {str(t.agent or "") for t in plan.tasks}


# ── Test Case Definitions (20 cases) ──────────────────────────────────

@dataclass
class ExtCase:
    name: str
    query: str
    cards: list[AgentCard]
    expect_agents: set[str]
    expect_no_agents: set[str]
    expect_min_tasks: int
    expect_max_tasks: int  # 0 = no upper bound
    expect_none_allowed: bool
    expect_chained: bool


CASES: list[ExtCase] = [
    ExtCase(
        name="01_商品库存查询",
        query="查询SKU为 PRD-001 的商品当前库存量",
        cards=[PRODUCT, USER, ORDER],
        expect_agents={"product-agent"}, expect_no_agents={"NONE", "user-agent", "order-agent"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="02_用户电话查询",
        query="帮我查一下用户李四的电话号码",
        cards=[USER, ORDER, PRODUCT],
        expect_agents={"user-agent"}, expect_no_agents={"NONE", "order-agent", "product-agent"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="03_退货原因查询",
        query="退货单号 R20240001 的退货原因是什么，退款了多少钱",
        cards=[AFTERSALE, USER, ORDER],
        expect_agents={"aftersale-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="04_张三退货记录",
        query="查询用户张三的所有退货记录",
        cards=[USER, AFTERSALE, ORDER, PRODUCT],
        expect_agents={"user-agent", "aftersale-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=2, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=True,
    ),
    ExtCase(
        name="05_订单物流追踪",
        query="查询订单 ORD-001 的物流状态",
        cards=[ORDER, LOGISTICS, USER],
        expect_agents={"logistics-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="06_支付流水查询",
        query="订单 ORD-001 的支付记录是什么",
        cards=[ORDER, PAYMENT, USER],
        expect_agents={"payment-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="07_谁买过某商品_动态数据陷阱",
        query="查询商品'无线耳机'被哪些用户购买过",
        cards=[ORDER, PRODUCT, USER],
        expect_agents=set(), expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="08_某商品上季度销量",
        query="商品'无线耳机'上个季度卖了多少件",
        cards=[ORDER, PRODUCT, USER],
        expect_agents=set(), expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="09_退货最多商品统计",
        query="最近一个月退货最多的商品是哪个",
        cards=[AFTERSALE, PRODUCT, USER, ORDER],
        expect_agents={"aftersale-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="10_三独立查询",
        query="帮我同时查三件事：张三的电话、SKU为PRD-001的库存、订单ORD-001的支付记录",
        cards=[USER, PRODUCT, PAYMENT, ORDER],
        expect_agents={"user-agent", "product-agent", "payment-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=3, expect_max_tasks=3,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="11_商品信息加评论",
        query="查询SKU为PRD-001的商品信息（类目、标价、库存），以及它的所有用户评论",
        cards=[PRODUCT, REVIEW, USER],
        expect_agents={"product-agent", "review-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=2, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="12_张三退货商品原始订单",
        query="张三退货的那个商品，原始订单是什么时候下的",
        cards=[USER, AFTERSALE, ORDER, PRODUCT],
        expect_agents=set(), expect_no_agents={"NONE"},
        expect_min_tasks=2, expect_max_tasks=4,
        expect_none_allowed=False, expect_chained=True,
    ),
    ExtCase(
        name="13_上月销售额统计",
        query="统计上个月所有订单的总销售额",
        cards=[ORDER, PAYMENT, USER],
        expect_agents={"order-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="14_评分最高商品",
        query="评价最高的前3个商品是什么",
        cards=[REVIEW, PRODUCT, USER],
        expect_agents=set(), expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="15_知识问答_MySQL索引",
        query="什么是MySQL的聚簇索引",
        cards=[USER, ORDER, PRODUCT, AFTERSALE],
        expect_agents={"NONE"}, expect_no_agents=set(),
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=True, expect_chained=False,
    ),
    ExtCase(
        name="16_超出能力_财务报表",
        query="生成一份上季度的财务报表，包含收入、成本、利润",
        cards=[ORDER, PAYMENT, USER, PRODUCT],
        expect_agents=set(), expect_no_agents=set(),
        expect_min_tasks=1, expect_max_tasks=0,
        expect_none_allowed=True, expect_chained=False,
    ),
    ExtCase(
        name="17_意图过于模糊",
        query="帮我查一下",
        cards=[USER, ORDER, PRODUCT],
        expect_agents=set(), expect_no_agents=set(),
        expect_min_tasks=1, expect_max_tasks=0,
        expect_none_allowed=True, expect_chained=False,
    ),
    ExtCase(
        name="18_退过洗衣机的用户",
        query="最近退过洗衣机的用户都有谁，列出他们的联系电话",
        cards=[AFTERSALE, USER, ORDER, PRODUCT],
        expect_agents={"aftersale-agent", "user-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=2, expect_max_tasks=2,
        expect_none_allowed=False, expect_chained=True,
    ),
    ExtCase(
        name="19_高价值订单过滤",
        query="查询用户ID为U001的所有订单中金额超过500元的订单",
        cards=[ORDER, USER],
        expect_agents={"order-agent"}, expect_no_agents={"NONE"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
    ExtCase(
        name="20_商品规格参数",
        query="SKU为PRD-001的商品，它的规格参数（尺寸、重量、材质）是什么",
        cards=[PRODUCT, USER, ORDER, INVENTORY],
        expect_agents={"product-agent"}, expect_no_agents={"NONE", "order-agent"},
        expect_min_tasks=1, expect_max_tasks=1,
        expect_none_allowed=False, expect_chained=False,
    ),
]


# ── Parametric test ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def planner():
    return _make_planner()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_sg_chain_plan(planner, case: ExtCase):
    """Validate chain planner output for 20 business scenarios."""
    plan = await planner.make_plan(case.query, case.cards)
    _dump(case.name, plan)

    agents = _agents(plan)

    if not case.expect_none_allowed:
        assert "NONE" not in agents, (
            f"[{case.name}] Unexpected NONE. Agents: {agents}. "
            f"thought: {plan.thought_process[:200]}"
        )

    assert len(plan.tasks) >= case.expect_min_tasks, (
        f"[{case.name}] Expected ≥{case.expect_min_tasks} tasks, got {len(plan.tasks)}"
    )
    if case.expect_max_tasks > 0:
        assert len(plan.tasks) <= case.expect_max_tasks, (
            f"[{case.name}] Expected ≤{case.expect_max_tasks} tasks, got {len(plan.tasks)}"
        )

    for expected in case.expect_agents:
        assert expected in agents, (
            f"[{case.name}] Missing '{expected}'. Got: {agents}"
        )

    for forbidden in case.expect_no_agents:
        assert forbidden not in agents, (
            f"[{case.name}] Forbidden '{forbidden}' appeared. Got: {agents}"
        )

    if case.expect_chained and len(plan.tasks) > 1:
        has_dep = any(t.depends_on for t in plan.tasks)
        assert has_dep, (
            f"[{case.name}] Expected chained deps, got "
            f"{[(t.id, t.depends_on) for t in plan.tasks]}"
        )


# ── Targeted tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sg_noun_trap_sales(planner):
    """销量是订单动态数据，product-agent 不应被路由。"""
    query = "统计商品'无线耳机'的历史总销量"
    plan = await planner.make_plan(query, [PRODUCT, ORDER, USER])
    _dump("noun_trap_sales", plan)
    agents = _agents(plan)
    assert "order-agent" in agents, f"order-agent should handle sales, got {agents}"
    assert "product-agent" not in agents, (
        f"Noun trap: product-agent routed for sales. Sales=transaction behavior."
    )


@pytest.mark.asyncio
async def test_sg_three_step_chain(planner):
    """张三退货商品库存：三步骤链。"""
    query = "张三最近退货的那个商品，现在库存还有多少"
    plan = await planner.make_plan(query, [USER, AFTERSALE, PRODUCT, ORDER])
    _dump("three_step", plan)
    agents = _agents(plan)
    assert "NONE" not in agents
    assert len(plan.tasks) >= 2, f"Expected ≥2 tasks, got {len(plan.tasks)}"
    deps = [(t.id, t.agent, t.depends_on) for t in plan.tasks]
    print(f"  deps: {deps}")
    # At least one task should depend on another
    assert any(t.depends_on for t in plan.tasks), f"No chain dependency found: {deps}"


@pytest.mark.asyncio
async def test_sg_ambiguous_no_false_positive(planner):
    """高度模糊查询不应路由到多个agent。"""
    query = "帮我看看这个"
    plan = await planner.make_plan(query, [USER, ORDER, PRODUCT, AFTERSALE])
    _dump("ambiguous", plan)
    agents = _agents(plan)
    if "NONE" in agents:
        print("  ✅ NONE for ambiguous query")
    else:
        assert len(agents) <= 1, f"Ambiguous query routed to {agents}"
        print(f"  ℹ️  routed to single agent: {agents}")


@pytest.mark.asyncio
async def test_sg_inventory_not_sales(planner):
    """库存agent不应处理销量排名。"""
    query = "上个月哪个商品卖得最好"
    plan = await planner.make_plan(query, [INVENTORY, ORDER, PRODUCT, USER])
    _dump("inventory_not_sales", plan)
    agents = _agents(plan)
    assert "inventory-agent" not in agents, "inventory-agent should NOT handle sales ranking"
    assert "order-agent" in agents, "order-agent should handle sales ranking"


@pytest.mark.asyncio
async def test_sg_notify_not_data_query(planner):
    """notify-agent 是通知服务，不应被路由到数据查询。"""
    query = "查询用户张三的邮箱"
    plan = await planner.make_plan(query, [USER, NOTIFY, ORDER])
    _dump("notify_filter", plan)
    agents = _agents(plan)
    assert "notify-agent" not in agents, "notify-agent routed for data query"
    assert "user-agent" in agents, "user-agent should handle data query"


@pytest.mark.asyncio
async def test_sg_review_not_product(planner):
    """评论评分统计是review-agent职责。"""
    query = "统计SKU为PRD-001的商品的平均评分"
    plan = await planner.make_plan(query, [REVIEW, PRODUCT, USER])
    _dump("review_avg", plan)
    agents = _agents(plan)
    assert "review-agent" in agents, f"review-agent should handle rating stats, got {agents}"
    assert "product-agent" not in agents, "product-agent routed for review ratings"


@pytest.mark.asyncio
async def test_sg_large_pool_precision(planner):
    """9 agent大池中只路由到正确的agent。"""
    query = "查询用户ID为U001的电话号码"
    plan = await planner.make_plan(query, ALL_CARDS)
    _dump("large_pool", plan)
    agents = _agents(plan)
    assert "user-agent" in agents
    assert "NONE" not in agents
    non_user = agents - {"user-agent"}
    assert not non_user, f"Large pool noise: extra agents {non_user}"


@pytest.mark.asyncio
async def test_sg_stability(planner):
    """连续3个复杂查询均产出有效plan。"""
    queries = [
        ("张三买了什么", [USER, ORDER]),
        ("退货单R001的信息及该用户电话", [AFTERSALE, USER, ORDER]),
        ("SKU为PRD-001的库存和最近评论", [PRODUCT, INVENTORY, REVIEW]),
    ]
    for qi, (q, cards) in enumerate(queries):
        plan = await planner.make_plan(q, cards)
        agents = _agents(plan)
        assert "NONE" not in agents, (
            f"Stability #{qi}: unexpected NONE for '{q}'. thought: {plan.thought_process[:200]}"
        )
        assert len(plan.tasks) >= 1
        print(f"  ✅ Stability #{qi}: '{q}' → {agents} tasks={len(plan.tasks)}")
    print("\n✅ Stability: 3/3 complex queries passed")