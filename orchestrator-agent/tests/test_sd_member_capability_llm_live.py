"""Live LLM tests for SD member capability judgment.

Requires:
  DASHSCOPE_API_KEY
  DASHSCOPE_MODEL (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    python -m pytest tests/test_sd_member_capability_llm_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent import orchestrator_agent_semantic_domain as domain


pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live LLM capability tests",
)


@dataclass(frozen=True)
class LiveCase:
    name: str
    query: str
    descriptor_type: str
    signatures: List[Dict[str, Any]]
    expect_domain_match: bool
    expect_can_handle: bool
    expect_can_contribute: Optional[bool] = None
    must_mention_missing: Optional[str] = None


CASES: List[LiveCase] = [
    LiveCase(
        name="structured_campaign_full_handle",
        query="状态为启用的营销活动有多少个？最早开始的活动编码是什么？",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "营销活动管理，包括活动状态、开始时间和活动编码",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: mkt_campaign(营销活动)，"
                        "table description: 营销活动主表，"
                        "key fields: campaign_code(活动编码)、status(状态)、start_time(开始时间)"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
    ),
    LiveCase(
        name="structured_campaign_partial_refund_missing",
        query="查询状态为启用的营销活动和退款记录",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "营销活动管理",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: mkt_campaign(营销活动)，"
                        "table description: 营销活动主表，"
                        "key fields: campaign_code(活动编码)"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=False,
        expect_can_contribute=True,
        must_mention_missing="退款",
    ),
    LiveCase(
        name="structured_inventory_primary_handle_with_payment_gap",
        query="查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "商品与库存管理，覆盖商品主数据与库存变动日志",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: inventory_logs(库存变动日志)，"
                        "table description: 库存变动历史，"
                        "key fields: change_type(变动类型-采购/销售/退货)、"
                        "product_id(商品ID)、quantity(数量)。\n"
                        "2. table name: products(商品)，table description: 商品信息，"
                        "key fields: product_id、sku、unit_price。"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
        must_mention_missing="支付",
    ),
    LiveCase(
        name="structured_order_contribute_on_inventory_anchor_query",
        query="查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "电商订单与支付流水",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: orders(订单)，table description: 订单主表，"
                        "key fields: order_id、product 相关行项目。\n"
                        "2. table name: payment_records(支付流水)，"
                        "table description: 订单支付状态与交易号，"
                        "key fields: payment_status、order_id。"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=False,
        expect_can_contribute=True,
        must_mention_missing="库存",
    ),
    LiveCase(
        name="structured_order_primary_handle_with_username_gap",
        query="查询订单号为 ORD-2025-00001 的下单用户姓名和收货人联系电话",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "电商订单与履约，覆盖订单主表与收货信息",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: orders(订单)，table description: 订单主表，"
                        "key fields: order_number(订单号)、user_id(下单用户ID)、"
                        "total_amount(订单金额)。\n"
                        "2. table name: order_shipping(物流)，table description: "
                        "收货人联系电话与地址，key fields: receiver_phone(收货电话)。"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
        must_mention_missing="用户",
    ),
    LiveCase(
        name="structured_user_dd_not_primary_on_order_query",
        query="查询订单号为 ORD-2025-00001 的下单用户姓名和收货人联系电话",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "会员与用户主数据",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: users(用户)，table description: 用户姓名与账号，"
                        "key fields: user_id、username(用户姓名)、phone。"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=False,
        expect_can_contribute=True,
        must_mention_missing="订单",
    ),
    LiveCase(
        name="structured_orders_unrelated_reject",
        query="查询火箭发动机推力曲线",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "电商订单与交易",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: orders(订单)，table description: 订单主表，"
                        "key fields: order_id(订单编号)、total_amount(订单金额)"
                    )
                },
            }
        ],
        expect_domain_match=False,
        expect_can_handle=False,
        expect_can_contribute=False,
    ),
    LiveCase(
        name="structured_store_handle",
        query="上海有哪些门店？给出门店编码和名称。",
        descriptor_type="structured-mysql",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "门店主数据管理",
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: ch_store(门店)，table description: 门店主表，"
                        "key fields: store_code(门店编码)、store_name(门店名称)、city(城市)"
                    )
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
    ),
    LiveCase(
        name="code_payment_gateway_handle",
        query="支付网关的超时重试逻辑在哪里实现？",
        descriptor_type="code",
        signatures=[
            {
                "descriptor_type": "code",
                "semantic_domain": "支付网关服务代码，覆盖超时、重试与错误处理",
                "metadata_content": {
                    "summary": "payment-gateway 仓库实现超时重试与幂等保护",
                    "file_summary": "src/retry/TimeoutPolicy.java 定义超时策略",
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
    ),
    LiveCase(
        name="code_payment_partial_inventory_missing",
        query="支付网关超时重试和库存扣减怎么实现？",
        descriptor_type="code",
        signatures=[
            {
                "descriptor_type": "code",
                "semantic_domain": "支付网关超时重试代码",
                "metadata_content": {
                    "summary": "payment-gateway 超时与重试策略",
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=False,
        expect_can_contribute=True,
        must_mention_missing="库存",
    ),
    LiveCase(
        name="document_expense_approval_handle",
        query="员工报销审批流程怎么走？",
        descriptor_type="unstructured",
        signatures=[
            {
                "descriptor_type": "unstructured",
                "semantic_domain": "财务制度与报销审批文档",
                "metadata_content": {
                    "document_summary": "员工报销需部门经理审批后提交财务复核",
                    "topics": ["报销", "审批流程", "财务制度"],
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
    ),
    LiveCase(
        name="document_unrelated_reject",
        query="Kubernetes 集群如何做蓝绿发布？",
        descriptor_type="unstructured",
        signatures=[
            {
                "descriptor_type": "unstructured",
                "semantic_domain": "员工手册与考勤制度",
                "metadata_content": {
                    "document_summary": "考勤打卡、请假销假和年假规则",
                    "topics": ["考勤", "请假", "年假"],
                },
            }
        ],
        expect_domain_match=False,
        expect_can_handle=False,
        expect_can_contribute=False,
    ),
    LiveCase(
        name="bank_risk_domain_handle",
        query="分析银行行业风险趋势",
        descriptor_type="structured-pg",
        signatures=[
            {
                "descriptor_type": "structured-pg",
                "semantic_domain": "银行行业风险数据分析",
                "agent_card": {
                    "description": "覆盖信用风险、市场风险与流动性风险指标分析"
                },
                "metadata_content": {
                    "summary": "银行风险主题宽表与指标口径说明",
                    "topics": ["信用风险", "市场风险", "风险趋势"],
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=True,
        expect_can_contribute=True,
    ),
    LiveCase(
        name="legal_doc_partial_vs_finance",
        query="合同违约责任条款和本月营收汇总分别是什么？",
        descriptor_type="unstructured",
        signatures=[
            {
                "descriptor_type": "unstructured",
                "semantic_domain": "法律合规与合同条款知识库",
                "metadata_content": {
                    "document_summary": "合同模板、违约责任、管辖法院与争议解决条款",
                    "topics": ["合同", "违约责任", "合规"],
                },
            }
        ],
        expect_domain_match=True,
        expect_can_handle=False,
        expect_can_contribute=True,
        must_mention_missing="营收",
    ),
]


def _executor() -> domain.OrchestratorAgentExecutorSemanticDomain:
    return domain.OrchestratorAgentExecutorSemanticDomain(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731"),
        temperature=0.01,
        data_descriptors=["live-dd"],
        dd_namespace="default",
        agent_id="LiveCapabilityAgent",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_live_llm_member_capability_cases(case: LiveCase):
    executor = _executor()
    result = await executor._judge_member_capability_with_llm(
        query=case.query,
        signatures=case.signatures,
        agent_name=f"Live-{case.name}",
        agent_url="http://live-capability:10100",
        descriptor_type=case.descriptor_type,
        request_metadata={
            "run_id": f"live-{case.name}",
            "trace_id": "a" * 32,
            "user_id": "live-capability-tester",
        },
    )

    print(
        f"\n[{case.name}] domain_match={result.get('domain_match')} "
        f"can_handle={result.get('can_handle')} "
        f"can_contribute={result.get('can_contribute')} "
        f"confidence={result.get('confidence')} "
        f"missing={result.get('missing_requirements')} "
        f"evidence={result.get('matched_evidence')} "
        f"reason={result.get('reason')}"
    )

    assert result["evidence_mode"] == "llm"
    assert result["domain_match"] is case.expect_domain_match
    assert result["can_handle"] is case.expect_can_handle
    if case.expect_can_contribute is not None:
        assert result["can_contribute"] is case.expect_can_contribute
    if case.must_mention_missing:
        missing_text = " ".join(result.get("missing_requirements") or [])
        reason_text = str(result.get("reason") or "")
        assert case.must_mention_missing in missing_text or case.must_mention_missing in reason_text
