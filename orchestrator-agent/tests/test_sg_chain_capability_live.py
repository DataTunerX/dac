"""Live LLM tests for SG orchestrator capability-chain scoring.

Tests the ``SG_CHAIN_CAPABILITY_CHECK_PROMPT`` + ``capability_chain.aggregate()``
pipeline against Aliyun DashScope deepseek-v4-flash-0731 with real SG domain
evaluation scenarios.

Requires:
  DASHSCOPE_API_KEY  (Aliyun DashScope API key)
  DASHSCOPE_MODEL    (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=sk-... \\
    python -m pytest tests/test_sg_chain_capability_live.py -q -s -v
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator_agent import capability_chain          # noqa: E402
from orchestrator_agent.orchestrator_agent_semantic_group import (
    SG_CHAIN_CAPABILITY_CHECK_PROMPT,
)  # noqa: E402
from model_sdk.api.model_manager import ModelManager    # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live capability chain tests",
)

TOL = 0.15  # documented tolerance for confidence


# ---------------------------------------------------------------------------
# Test case data — realistic SG domain descriptions with member inventories
# ---------------------------------------------------------------------------

# A typical SG description with attached data inventory block (same format
# produced by build_sg_inventory_description / attach_data_inventory in server.py).
ORDER_SG_DESCRIPTION = """订单域智能体，管理电商订单相关业务数据的查询、统计与分析。
能力范围：订单查询、商品统计、销售额计算、用户购买行为分析。
【data_inventory】
tables=[order_items, order_payments, orders, products, users]
absent=none
source=signature_api; db_type=mysql"""

ORDER_SG_NAME = "EcommerceOrderAgent-sg-ord"

PAYMENT_SG_DESCRIPTION = """支付域智能体，管理支付流水、退款审批、对账结算等支付相关业务。
能力范围：支付流水查询、退款单管理、支付渠道统计、对账差异分析。
【data_inventory】
tables=[payment_records, refund_orders, settlement_logs, payment_channels]
absent=none
source=signature_api; db_type=mysql"""

PAYMENT_SG_NAME = "PaymentAgent-sg-pay"

LOGISTICS_SG_DESCRIPTION = """物流域智能体，管理物流运单、配送状态、仓储库存等物流相关业务。
能力范围：运单跟踪、配送时效统计、仓库库存查询、物流费用计算。
【data_inventory】
tables=[shipments, delivery_logs, warehouses, inventory_items]
absent=none
source=signature_api; db_type=mysql"""

LOGISTICS_SG_NAME = "LogisticsAgent-sg-log"


@dataclass(frozen=True)
class ChainCase:
    """A single capability-chain test case for SG domain evaluation.

    Attributes:
        name: Unique test case identifier.
        query: The user query to evaluate.
        agent_name: The SG orchestrator's agent name.
        agent_description: The SG's domain description with data inventory.
        member_data_inventory: Supplementary member SD data inventory text.
        expect_can_handle: Expected can_handle result after aggregation.
        expect_can_contribute: Expected can_contribute result after aggregation.
        expect_confidence_min: Minimum expected confidence (within TOL).
        expect_confidence_max: Maximum expected confidence (within TOL), for negative cases.
        expect_steps: Expected number-of-steps range (inclusive tuple).
        expect_evidence: Allowed evidence grades.
        expect_contributing_steps: Steps expected in contributing_steps list.
        expect_missing_substrings: Substrings expected in missing_requirements.
    """

    name: str
    query: str
    agent_name: str
    agent_description: str
    member_data_inventory: str = ""
    expect_can_handle: bool = False
    expect_can_contribute: bool = False
    expect_confidence_min: float = 0.0
    expect_confidence_max: float = 1.0
    expect_steps: tuple[int, ...] = (1, 2, 3)
    expect_evidence: tuple[str, ...] = ("A", "B")
    expect_contributing_steps: tuple[int, ...] = ()
    expect_missing_substrings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES = [
    # ── Case 1: 完全匹配 — 查询订单商品，SG 覆盖全部数据实体 ──
    ChainCase(
        "sg_full_match_order_products",
        "查询张三购买的所有商品，列出商品名称和金额",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(2, 3, 4),  # LLM varies between 2-4 steps (user_id→orders→products or +aggregate)
        expect_contributing_steps=(1, 2, 3),
    ),

    # ── Case 2: 完全匹配 — 订单统计 ──
    ChainCase(
        "sg_full_match_order_stats",
        "统计上个月每个商品的销量排名",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(1, 2, 3),  # LLM naturally breaks into: filter→aggregate→sort
        expect_contributing_steps=(1,),
    ),

    # ── Case 3: 完全匹配 — users 表在 inventory 中，SG 可独立覆盖 ──
    ChainCase(
        "sg_full_match_user_profile_and_orders",
        "查询张三的个人资料和他购买的订单记录",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=True,  # users 表在 data_inventory 中
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(2, 3),
        expect_contributing_steps=(1, 2, 3),
    ),

    # ── Case 4: 不匹配 — 物流配送不属于订单域（明确无物流字眼，纯物流业务） ──
    ChainCase(
        "sg_no_match_logistics_shipping",
        "查询运单 SF-2024-001 的配送路线和预计签收时间",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_confidence_max=0.5,
        expect_steps=(1,),
        expect_evidence=("D",),
    ),

    # ── Case 5: 纯工具请求 — 非业务领域 ──
    ChainCase(
        "sg_no_match_tool_request",
        "帮我写一个 Python 脚本，用于将 JSON 文件转为 CSV 格式",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_confidence_max=0.3,
        expect_steps=(1, 2, 3),  # LLM decomposes into: read→(parse)→convert
        expect_evidence=("A", "B", "D"),  # D is correct — no domain relevance
    ),

    # ── Case 6: 完全匹配 — 支付域 ──
    ChainCase(
        "sg_full_match_payment",
        "查询最近三天内所有退款申请的状态和金额",
        PAYMENT_SG_NAME,
        PAYMENT_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(1,),
        expect_contributing_steps=(1,),
    ),

    # ── Case 7: 跨域 — 物流域查询配送状态 ──
    ChainCase(
        "sg_full_match_logistics",
        "查一下运单 SF-2024-001 的当前配送状态和预计送达时间",
        LOGISTICS_SG_NAME,
        LOGISTICS_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(1,),
        expect_contributing_steps=(1,),
    ),

    # ── Case 8: 复杂多步骤 — 支付对账分析 ──
    ChainCase(
        "sg_full_match_payment_reconciliation",
        "统计本月支付成功金额和退款金额，计算退款率",
        PAYMENT_SG_NAME,
        PAYMENT_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(1, 2, 3),
        expect_contributing_steps=(1, 2, 3),
    ),

    # ── Case 9: 不匹配跨域 — 支付域不覆盖物流 ──
    ChainCase(
        "sg_no_match_cross_domain",
        "查询物流运单 SF-001 的详细信息",
        PAYMENT_SG_NAME,
        PAYMENT_SG_DESCRIPTION,
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_confidence_min=0.0,
        expect_steps=(1,),
        expect_evidence=("D",),
    ),

    # ── Case 10: 子领域推断 — SG描述虽侧重订单，但同属电商领域涵盖用户表 ──
    ChainCase(
        "sg_partial_contribute_users_available",
        "列出所有注册用户的手机号和注册时间",
        ORDER_SG_NAME,
        ORDER_SG_DESCRIPTION,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence_min=0.7,
        expect_steps=(1,),
        expect_contributing_steps=(1,),
    ),
]


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------


def _build_llm():
    """Build a non-streaming LLM for capability chain judging."""
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731"),
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


async def _run_chain_judge(case: ChainCase) -> dict[str, any]:
    """Invoke the LLM with SG_CHAIN_CAPABILITY_CHECK_PROMPT and return raw result."""
    prompt = SG_CHAIN_CAPABILITY_CHECK_PROMPT.format(
        agent_name=case.agent_name,
        agent_description=case.agent_description,
        member_data_inventory=case.member_data_inventory or "（无额外成员数据描述）",
        history="（无）",
        query=case.query,
    )
    llm = _build_llm()
    return await llm.ainvoke([HumanMessage(content=prompt)])


def _parse_llm_output(answer: any) -> dict[str, any] | None:
    """Parse the LLM's text output into a dict, with tolerance for common formats."""
    raw = getattr(answer, "content", None)
    if isinstance(raw, list):
        raw = "".join(
            str(p.get("text", "")) if isinstance(p, dict) else (getattr(p, "text", None) or str(p))
            for p in raw
        )
    if not isinstance(raw, str):
        raw = str(answer or "")
    if not raw.strip():
        return None

    # 1. Direct JSON parse
    try:
        parsed = json.loads(raw, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # 3. Single-quote to double-quote (last resort)
    try:
        parsed = json.loads(cleaned.replace("'", '"'), strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_sg_chain_capability(case: ChainCase):
    """End-to-end test: prompt → LLM → parse → aggregate → assert."""
    # ── Step 1: Invoke LLM ──
    answer = await _run_chain_judge(case)
    assert answer is not None, f"[{case.name}] LLM returned no answer"

    # ── Step 2: Parse JSON output ──
    raw_result = _parse_llm_output(answer)
    assert raw_result is not None, (
        f"[{case.name}] Failed to parse LLM output as JSON.\n"
        f"Raw output (first 800 chars):\n{str(answer)[:800]}"
    )

    # ── Step 3: Parse into CapabilityChainResult ──
    try:
        chain = capability_chain.parse_chain_result(raw_result)
    except Exception as exc:
        pytest.fail(
            f"[{case.name}] parse_chain_result failed: {exc}\n"
            f"Raw data: {json.dumps(raw_result, ensure_ascii=False, indent=2)[:1000]}"
        )

    # ── Step 4: Aggregate ──
    agg = capability_chain.aggregate(chain)

    # ── Step 5: Print diagnostics ──
    print(f"\n{'='*80}")
    print(f"[{case.name}]  query={case.query}")
    print(f"  agent={case.agent_name}  handle={agg.can_handle}  contribute={agg.can_contribute}")
    print(f"  confidence={agg.confidence}  handle_score={agg.handle_score}")
    print(f"  evidence={chain.evidence_grade}  threshold={agg.threshold}")
    print(f"  contributing_steps={agg.contributing_steps}")
    print(f"  external_dep={agg.has_external_dependency}")
    print(f"  steps:")
    for s in chain.steps:
        s_score = agg.step_scores.get(s.step_id, 0.0)
        print(f"    step {s.step_id} ({s.operation}, is_final={s.is_final}): "
              f"I={s.input_match.ratio:.2f} D={s.data_coverage.ratio:.2f} "
              f"O={s.operation_capability:.1f} R={s.result_match.ratio:.2f} "
              f"C={s.constraint_satisfaction.ratio:.2f} → score={s_score:.3f}")
        print(f"      inputs={[i.model_dump() for i in s.inputs]}")
        if s.evidence:
            for ev in s.evidence[:3]:
                print(f"      evidence: {ev[:120]}")
    print(f"  contribution={chain.contribution!r}")
    print(f"  missing={chain.missing_requirements}")
    print(f"  risks={chain.risks}")
    print(f"  reason={chain.reason[:300]}")
    print(f"{'='*80}\n")

    # ── Step 6: Structured assertions ──
    # 6a. Every ratio dimension must carry a checklist or be explicitly empty
    for s in chain.steps:
        for dim in (s.input_match, s.data_coverage, s.result_match, s.constraint_satisfaction):
            if dim.required:
                assert 0.0 <= dim.ratio <= 1.0, (
                    f"[{case.name}] step {s.step_id} ratio out of range: {dim.ratio}"
                )
            else:
                assert dim.ratio == pytest.approx(1.0), (
                    f"[{case.name}] step {s.step_id} empty checklist must mean ratio=1.0, "
                    f"got {dim.ratio}"
                )
        assert s.operation_capability in capability_chain.OPERATION_LEVELS, (
            f"[{case.name}] step {s.step_id} invalid operation_capability: "
            f"{s.operation_capability}"
        )

    # 6b. Step count in expected range
    assert len(chain.steps) in case.expect_steps, (
        f"[{case.name}] steps={len(chain.steps)}, expected one of {case.expect_steps}"
    )

    # 6c. can_handle
    assert agg.can_handle is case.expect_can_handle, (
        f"[{case.name}] can_handle={agg.can_handle}, expected={case.expect_can_handle}"
    )

    # 6d. can_contribute
    assert agg.can_contribute is case.expect_can_contribute, (
        f"[{case.name}] can_contribute={agg.can_contribute}, "
        f"expected={case.expect_can_contribute}"
    )

    # 6e. confidence range
    assert agg.confidence >= case.expect_confidence_min - TOL, (
        f"[{case.name}] confidence={agg.confidence}, expected >= {case.expect_confidence_min}"
    )
    assert agg.confidence <= case.expect_confidence_max + TOL, (
        f"[{case.name}] confidence={agg.confidence}, expected <= {case.expect_confidence_max}"
    )

    # 6f. evidence grade
    assert chain.evidence_grade in case.expect_evidence, (
        f"[{case.name}] evidence_grade={chain.evidence_grade}, "
        f"expected one of {case.expect_evidence}"
    )

    # 6g. contributing steps
    for sid in case.expect_contributing_steps:
        assert sid in agg.contributing_steps, (
            f"[{case.name}] step {sid} not in contributing_steps={agg.contributing_steps}"
        )

    # 6h. missing requirements contain expected substrings
    if case.expect_missing_substrings:
        blob = " ".join(chain.missing_requirements or [])
        for sub in case.expect_missing_substrings:
            assert sub in blob, (
                f"[{case.name}] missing_requirements missing '{sub}': "
                f"got {chain.missing_requirements}"
            )


# ---------------------------------------------------------------------------
# Summary report (runs after all parameterized cases)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_sg_chain_capability_summary(case: ChainCase):
    """Summary-only run (no assertions) for aggregate statistics."""
    answer = await _run_chain_judge(case)
    raw_result = _parse_llm_output(answer)
    if raw_result is None:
        print(f"[{case.name}] JSON_PARSE_FAIL")
        return
    try:
        chain = capability_chain.parse_chain_result(raw_result)
    except Exception:
        print(f"[{case.name}] SCHEMA_FAIL")
        return
    agg = capability_chain.aggregate(chain)
    match = "✓" if (
        agg.can_handle == case.expect_can_handle
        and agg.can_contribute == case.expect_can_contribute
        and agg.confidence >= case.expect_confidence_min - 0.15
    ) else "✗"
    print(f"[{match}] {case.name}: handle={agg.can_handle}({case.expect_can_handle}) "
          f"contribute={agg.can_contribute}({case.expect_can_contribute}) "
          f"conf={agg.confidence:.2f}(≥{case.expect_confidence_min}) "
          f"steps={len(chain.steps)} evidence={chain.evidence_grade}")