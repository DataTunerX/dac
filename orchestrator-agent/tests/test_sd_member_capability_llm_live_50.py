"""Live LLM suite: 50 SD member-capability cases (accuracy + stability).

Uses DashScope OpenAI-compatible API. API key MUST come from the environment
(never commit secrets):

  export DASHSCOPE_API_KEY=...
  export DASHSCOPE_MODEL=deepseek-v4-flash-0731
  export DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  export SD_CAP_LIVE_STABILITY_RUNS=2   # optional, default 2

  python -m pytest tests/test_sd_member_capability_llm_live_50.py -q -s
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
class CapCase:
    name: str
    category: str
    query: str
    descriptor_type: str
    signatures: List[Dict[str, Any]]
    expect_domain_match: bool
    expect_can_handle: bool
    expect_can_contribute: bool
    must_mention_missing: Optional[str] = None


def _sig_mysql(domain_text: str, tables_detail: str) -> Dict[str, Any]:
    return {
        "descriptor_type": "structured-mysql",
        "semantic_domain": domain_text,
        "metadata_content": {"tables_detail": tables_detail},
    }


def _sig_code(domain_text: str, **meta: Any) -> Dict[str, Any]:
    return {
        "descriptor_type": "code",
        "semantic_domain": domain_text,
        "metadata_content": meta,
    }


def _sig_docs(domain_text: str, **meta: Any) -> Dict[str, Any]:
    return {
        "descriptor_type": "unstructured",
        "semantic_domain": domain_text,
        "metadata_content": meta,
    }


ORDERS_TABLES = (
    "1. table name: orders(订单)，key fields: order_id, order_number, user_id, total_amount, status。\n"
    "2. table name: order_items(订单明细)，key fields: order_id, product_id, quantity, price。\n"
    "3. table name: payment_records(支付流水)，key fields: order_id, payment_status, amount, trade_no。"
)
USERS_TABLES = (
    "1. table name: users(用户)，key fields: user_id, username, full_name, email, phone_number, registration_date。\n"
    "2. table name: user_addresses(收货地址)，key fields: user_id, recipient_name, phone。\n"
    "3. table name: user_payment_methods(用户支付方式)，key fields: user_id, method_type, masked_account。"
)
INVENTORY_TABLES = (
    "1. table name: inventory_logs(库存变动日志)，key fields: change_type(采购/销售/退货), product_id, quantity, ref_no。\n"
    "2. table name: products(商品)，key fields: product_id, sku, product_name, unit_price。"
)
PRODUCT_ONLY = (
    "1. table name: products(商品)，key fields: product_id, sku, product_name, category_id, unit_price。"
)
STORE_TABLES = (
    "1. table name: ch_store(门店)，key fields: store_code, store_name, city, status。"
)
CAMPAIGN_TABLES = (
    "1. table name: mkt_campaign(营销活动)，key fields: campaign_code, status, start_time, end_time。"
)
REFUND_TABLES = (
    "1. table name: refunds(退款单)，key fields: refund_id, order_id, refund_amount, refund_status。"
)
SHIPPING_TABLES = (
    "1. table name: order_shipping(物流)，key fields: order_id, carrier, tracking_no, receiver_phone, status。"
)

CASES: List[CapCase] = [
    # ----- A. Clear structured handle (8) -----
    CapCase(
        "A01_orders_by_number",
        "handle_clear",
        "查询订单号 ORD-2025-00001 的金额和状态",
        "structured-mysql",
        [_sig_mysql("电商订单", ORDERS_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A02_user_profile",
        "handle_clear",
        "查询用户 user_id=1 的姓名、邮箱和注册日期",
        "structured-mysql",
        [_sig_mysql("用户账户", USERS_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A03_inventory_sales_logs",
        "handle_clear",
        "列出 change_type 为销售的库存变动记录",
        "structured-mysql",
        [_sig_mysql("商品库存", INVENTORY_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A04_product_catalog",
        "handle_clear",
        "查询 sku 以 PHONE 开头的商品名称和单价",
        "structured-mysql",
        [_sig_mysql("商品主数据", PRODUCT_ONLY)],
        True,
        True,
        True,
    ),
    CapCase(
        "A05_store_list_shanghai",
        "handle_clear",
        "上海有哪些门店？给出门店编码和名称",
        "structured-mysql",
        [_sig_mysql("门店主数据", STORE_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A06_active_campaigns",
        "handle_clear",
        "状态为启用的营销活动有多少个？最早开始的活动编码是什么？",
        "structured-mysql",
        [_sig_mysql("营销活动", CAMPAIGN_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A07_refund_status",
        "handle_clear",
        "查询退款单 RF-1001 的退款金额和退款状态",
        "structured-mysql",
        [_sig_mysql("退款管理", REFUND_TABLES)],
        True,
        True,
        True,
    ),
    CapCase(
        "A08_shipping_track",
        "handle_clear",
        "查询订单 ORD-2025-00001 的物流单号和承运商",
        "structured-mysql",
        [_sig_mysql("订单物流", SHIPPING_TABLES)],
        True,
        True,
        True,
    ),
    # ----- B. Primary handle + cross-domain gap (10) -----
    CapCase(
        "B01_order_primary_user_name_gap",
        "handle_plus_gap",
        "查询订单号 ORD-2025-00001 的下单用户姓名和收货人联系电话",
        "structured-mysql",
        [_sig_mysql("订单与履约", ORDERS_TABLES + "\n" + SHIPPING_TABLES)],
        True,
        True,
        True,
        "用户",
    ),
    CapCase(
        "B02_inventory_primary_payment_gap",
        "handle_plus_gap",
        "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        "structured-mysql",
        [_sig_mysql("商品与库存", INVENTORY_TABLES)],
        True,
        True,
        True,
        "支付",
    ),
    CapCase(
        "B03_order_primary_user_email_gap",
        "handle_plus_gap",
        "统计各订单对应下单用户的邮箱",
        "structured-mysql",
        [_sig_mysql("订单", ORDERS_TABLES)],
        True,
        True,
        True,
        "用户",
    ),
    CapCase(
        "B04_product_primary_order_qty_gap",
        "handle_plus_gap",
        "查询商品 P-001 的名称以及它在订单中的销售件数",
        "structured-mysql",
        [_sig_mysql("商品主数据", PRODUCT_ONLY)],
        True,
        True,
        True,
        "订单",
    ),
    CapCase(
        "B05_user_primary_order_count_gap",
        "handle_plus_gap",
        "查询用户张三的手机号，以及他有多少笔订单",
        "structured-mysql",
        [_sig_mysql("用户账户", USERS_TABLES)],
        True,
        True,
        True,
        "订单",
    ),
    CapCase(
        "B06_campaign_primary_store_gap",
        "handle_plus_gap",
        "启用中的营销活动有哪些，各自覆盖哪些上海门店？",
        "structured-mysql",
        [_sig_mysql("营销活动", CAMPAIGN_TABLES)],
        True,
        True,
        True,
        "门店",
    ),
    CapCase(
        "B07_refund_primary_user_gap",
        "handle_plus_gap",
        "查询退款单 RF-1001 的金额，以及申请退款用户的姓名",
        "structured-mysql",
        [_sig_mysql("退款", REFUND_TABLES)],
        True,
        True,
        True,
        "用户",
    ),
    CapCase(
        "B08_shipping_primary_payment_gap",
        "handle_plus_gap",
        "查询已发货订单的物流状态，并给出对应支付状态",
        "structured-mysql",
        [_sig_mysql("物流", SHIPPING_TABLES)],
        True,
        True,
        True,
        "支付",
    ),
    CapCase(
        "B09_inventory_primary_product_ok_order_gap",
        "handle_plus_gap",
        "从库存销售变动中找出商品，并给出这些商品对应订单是否已支付",
        "structured-mysql",
        [_sig_mysql("库存商品", INVENTORY_TABLES)],
        True,
        True,
        True,
        "订单",
    ),
    CapCase(
        "B10_order_amount_plus_category_gap",
        "handle_plus_gap",
        "列出订单金额，并附上所购商品的类目名称",
        "structured-mysql",
        [_sig_mysql("订单", ORDERS_TABLES)],
        True,
        True,
        True,
        "商品",
    ),
    # ----- C. Contribute only, not primary (10) -----
    CapCase(
        "C01_order_on_inventory_anchor",
        "contribute_only",
        "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        "structured-mysql",
        [_sig_mysql("订单支付", ORDERS_TABLES)],
        True,
        False,
        True,
        "库存",
    ),
    CapCase(
        "C02_user_on_order_anchor",
        "contribute_only",
        "查询订单号 ORD-2025-00001 的下单用户姓名和收货人联系电话",
        "structured-mysql",
        [_sig_mysql("用户", USERS_TABLES)],
        True,
        False,
        True,
        "订单",
    ),
    CapCase(
        "C03_product_on_order_payment_report",
        "contribute_only",
        "统计每个订单的支付状态，并带上商品名称",
        "structured-mysql",
        [_sig_mysql("商品", PRODUCT_ONLY)],
        True,
        False,
        True,
        "订单",
    ),
    CapCase(
        "C04_product_sku_for_order_lines",
        "contribute_only",
        "查询订单 ORD-2025-00001 各明细行对应的商品 SKU 名称",
        "structured-mysql",
        [_sig_mysql("商品主数据", PRODUCT_ONLY)],
        True,
        False,
        True,
        "订单",
    ),
    CapCase(
        "C05_shipping_unrelated_to_payment_status",
        "contribute_only",
        "订单 ORD-2025-00001 是否已支付？支付流水号是什么？",
        "structured-mysql",
        [_sig_mysql("物流", SHIPPING_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "C06_refund_unrelated_to_payment_status",
        "contribute_only",
        "订单 ORD-2025-00001 当前支付状态是什么？",
        "structured-mysql",
        [_sig_mysql("退款", REFUND_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "C07_inventory_unrelated_to_paid_orders",
        "contribute_only",
        "列出已支付成功订单中的商品及支付状态",
        "structured-mysql",
        [_sig_mysql("库存", INVENTORY_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "C08_user_payment_methods_not_order_payment",
        "contribute_only",
        "查询订单 ORD-2025-00001 的支付状态",
        "structured-mysql",
        [_sig_mysql("用户支付方式", USERS_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "C09_campaign_for_order_gmv",
        "contribute_only",
        "统计本月订单支付成功总额",
        "structured-mysql",
        [_sig_mysql("营销", CAMPAIGN_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "C10_store_for_user_profile",
        "contribute_only",
        "查询用户李四的邮箱和注册日期",
        "structured-mysql",
        [_sig_mysql("门店", STORE_TABLES)],
        False,
        False,
        False,
    ),
    # ----- D. Unrelated reject (6) -----
    CapCase(
        "D01_orders_vs_rocket",
        "reject",
        "查询火箭发动机推力曲线",
        "structured-mysql",
        [_sig_mysql("电商订单", ORDERS_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "D02_users_vs_k8s",
        "reject",
        "Kubernetes 集群如何做蓝绿发布？",
        "structured-mysql",
        [_sig_mysql("用户账户", USERS_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "D03_inventory_vs_hr",
        "reject",
        "员工年假剩余天数怎么查？",
        "structured-mysql",
        [_sig_mysql("库存", INVENTORY_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "D04_campaign_vs_weather",
        "reject",
        "北京明天会下雨吗？",
        "structured-mysql",
        [_sig_mysql("营销活动", CAMPAIGN_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "D05_store_vs_legal",
        "reject",
        "合同违约责任条款有哪些？",
        "structured-mysql",
        [_sig_mysql("门店", STORE_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "D06_refund_vs_devops",
        "reject",
        "CI 流水线缓存命中率怎么优化？",
        "structured-mysql",
        [_sig_mysql("退款", REFUND_TABLES)],
        False,
        False,
        False,
    ),
    # ----- E. True peer primaries (4) -----
    CapCase(
        "E01_campaign_and_refund_peer",
        "peer_primary",
        "请分别独立查询以下两项（对等主题）：(1) 启用中的营销活动列表 (2) 退款记录列表",
        "structured-mysql",
        [_sig_mysql("营销活动", CAMPAIGN_TABLES)],
        True,
        False,
        True,
        "退款",
    ),
    CapCase(
        "E02_order_and_inventory_peer",
        "peer_primary",
        "请分别独立统计以下两项（对等主题）：(1) 订单总数 (2) 库存销售变动次数",
        "structured-mysql",
        [_sig_mysql("订单", ORDERS_TABLES)],
        True,
        False,
        True,
        "库存",
    ),
    CapCase(
        "E03_user_and_store_peer",
        "peer_primary",
        "请分别独立统计以下两项（对等主题）：(1) 用户注册量 (2) 上海门店数量",
        "structured-mysql",
        [_sig_mysql("用户", USERS_TABLES)],
        True,
        False,
        True,
        "门店",
    ),
    CapCase(
        "E04_code_retry_and_inventory_peer",
        "peer_primary",
        "请分别独立说明以下两项实现（对等主题）：(1) 支付网关超时重试 (2) 库存扣减",
        "code",
        [
            _sig_code(
                "支付网关超时重试代码",
                summary="payment-gateway 超时与重试策略",
                file_summary="src/retry/TimeoutPolicy.java",
            )
        ],
        True,
        False,
        True,
        "库存",
    ),
    # ----- F. Code / docs (8) -----
    CapCase(
        "F01_code_payment_retry_handle",
        "code_docs",
        "支付网关的超时重试逻辑在哪里实现？",
        "code",
        [
            _sig_code(
                "支付网关服务代码",
                summary="payment-gateway 仓库实现超时重试与幂等保护",
                file_summary="src/retry/TimeoutPolicy.java 定义超时策略",
            )
        ],
        True,
        True,
        True,
    ),
    CapCase(
        "F02_code_unrelated_reject",
        "code_docs",
        "门店主数据表有哪些字段？",
        "code",
        [
            _sig_code(
                "支付网关重试代码",
                summary="仅包含超时重试实现",
            )
        ],
        False,
        False,
        False,
    ),
    CapCase(
        "F03_code_live_order_not_handle",
        "code_docs",
        "订单号 ORD-2025-00001 的下单用户姓名是什么？",
        "code",
        [
            _sig_code(
                "电商订单服务代码",
                summary="订单领域服务与 DTO 映射",
                file_summary="OrderController.java, UserMapper docs",
            )
        ],
        True,
        False,
        False,
    ),
    CapCase(
        "F04_docs_expense_handle",
        "code_docs",
        "员工报销审批流程怎么走？",
        "unstructured",
        [
            _sig_docs(
                "财务制度与报销审批文档",
                document_summary="员工报销需部门经理审批后提交财务复核",
                topics=["报销", "审批流程", "财务制度"],
            )
        ],
        True,
        True,
        True,
    ),
    CapCase(
        "F05_docs_unrelated_reject",
        "code_docs",
        "Kubernetes 集群如何做蓝绿发布？",
        "unstructured",
        [
            _sig_docs(
                "员工手册与考勤制度",
                document_summary="考勤打卡、请假销假和年假规则",
                topics=["考勤", "请假", "年假"],
            )
        ],
        False,
        False,
        False,
    ),
    CapCase(
        "F06_docs_peer_legal_and_revenue",
        "code_docs",
        "分别说明合同违约责任条款和本月营收汇总",
        "unstructured",
        [
            _sig_docs(
                "法律合规与合同条款知识库",
                document_summary="合同模板、违约责任、管辖法院与争议解决条款",
                topics=["合同", "违约责任", "合规"],
            )
        ],
        True,
        False,
        True,
        "营收",
    ),
    CapCase(
        "F07_docs_sample_json_not_live",
        "code_docs",
        "订单号 ORD-2025-00001 的支付状态是什么？",
        "unstructured",
        [
            _sig_docs(
                "支付 API 文档",
                document_summary="Swagger 示例含 payment_status 字段说明与样例 JSON",
                topics=["支付 API", "字段说明"],
            )
        ],
        True,
        False,
        False,
    ),
    CapCase(
        "F08_code_inventory_service_handle",
        "code_docs",
        "库存扣减的幂等键是在哪个类里生成的？",
        "code",
        [
            _sig_code(
                "库存扣减服务代码",
                summary="inventory-deduction 服务生成幂等键并扣减库存",
                file_summary="IdempotencyKeyFactory.java, StockDeductor.java",
            )
        ],
        True,
        True,
        True,
    ),
    # ----- G. Hard negatives / name traps (4) -----
    CapCase(
        "G01_user_payment_methods_vs_order_payment_status",
        "traps",
        "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        "structured-mysql",
        [_sig_mysql("用户账户与支付方式", USERS_TABLES)],
        False,
        False,
        False,
    ),
    CapCase(
        "G02_card_says_user_mgmt_no_users_table",
        "traps",
        "查询用户 user_id=9 的姓名",
        "structured-mysql",
        [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "用户管理平台",
                "agent_card": {"description": "用户管理与会员运营"},
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: orders(订单)，key fields: order_id, user_id, amount。"
                    )
                },
            }
        ],
        True,
        False,
        False,
        "用户",
    ),
    CapCase(
        "G03_weather_like_business_reject",
        "traps",
        "查询订单支付状态",
        "structured-mysql",
        [
            _sig_mysql(
                "天气技能域",
                "1. table name: weather_cache(天气缓存)，key fields: city, forecast, temp。",
            )
        ],
        False,
        False,
        False,
    ),
    CapCase(
        "G04_partial_same_domain_slice_only",
        "traps",
        "请分别独立查询以下两项（对等主题）：(1) 全部商品名称列表 (2) 库存销售变动数量",
        "structured-mysql",
        [_sig_mysql("仅商品主数据", PRODUCT_ONLY)],
        True,
        False,
        True,
        "库存",
    ),
]


assert len(CASES) == 50, f"expected 50 cases, got {len(CASES)}"


def _stability_runs() -> int:
    try:
        return max(1, int(os.getenv("SD_CAP_LIVE_STABILITY_RUNS", "2") or 2))
    except ValueError:
        return 2


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
        agent_id="LiveCapabilityAgent50",
    )


def _flags(result: Dict[str, Any]) -> tuple:
    return (
        bool(result.get("domain_match")),
        bool(result.get("can_handle")),
        bool(result.get("can_contribute")),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_live_sd_capability_50(case: CapCase):
    executor = _executor()
    runs = _stability_runs()
    outcomes = []
    last: Dict[str, Any] = {}

    for i in range(runs):
        last = await executor._judge_member_capability_with_llm(
            query=case.query,
            signatures=case.signatures,
            agent_name=f"Live-{case.name}",
            agent_url="http://live-capability:10100",
            descriptor_type=case.descriptor_type,
            request_metadata={
                "run_id": f"live50-{case.name}-r{i}",
                "trace_id": "b" * 32,
                "user_id": "live-capability-50",
            },
        )
        outcomes.append(_flags(last))

    print(
        f"\n[{case.category}/{case.name}] runs={outcomes} "
        f"missing={last.get('missing_requirements')} "
        f"reason={(last.get('reason') or '')[:180]}"
    )

    # Stability: all runs must agree on the three flags.
    assert len(set(outcomes)) == 1, f"unstable across {runs} runs: {outcomes}"

    domain_match, can_handle, can_contribute = outcomes[0]
    assert last.get("evidence_mode") == "llm"
    assert domain_match is case.expect_domain_match
    assert can_handle is case.expect_can_handle
    assert can_contribute is case.expect_can_contribute

    if case.must_mention_missing:
        blob = " ".join(
            [
                " ".join(last.get("missing_requirements") or []),
                str(last.get("reason") or ""),
            ]
        )
        assert case.must_mention_missing in blob
