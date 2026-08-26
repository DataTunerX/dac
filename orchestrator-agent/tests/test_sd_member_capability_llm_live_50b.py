"""Live LLM suite B: another 50 SD member-capability cases (accuracy + stability).

Distinct from ``test_sd_member_capability_llm_live_50.py``. Cases are worded to
minimize peer-primary / related-attribute ambiguity.

  export DASHSCOPE_API_KEY=...
  export DASHSCOPE_MODEL=deepseek-v4-flash-0731
  export SD_CAP_LIVE_STABILITY_RUNS=3

  python -m pytest tests/test_sd_member_capability_llm_live_50b.py -q -s
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


def _mysql(domain_text: str, tables: str) -> Dict[str, Any]:
    return {
        "descriptor_type": "structured-mysql",
        "semantic_domain": domain_text,
        "metadata_content": {"tables_detail": tables},
    }


def _pg(domain_text: str, tables: str) -> Dict[str, Any]:
    return {
        "descriptor_type": "structured-pg",
        "semantic_domain": domain_text,
        "metadata_content": {"tables_detail": tables},
    }


def _code(domain_text: str, **meta: Any) -> Dict[str, Any]:
    return {
        "descriptor_type": "code",
        "semantic_domain": domain_text,
        "metadata_content": meta,
    }


def _docs(domain_text: str, **meta: Any) -> Dict[str, Any]:
    return {
        "descriptor_type": "unstructured",
        "semantic_domain": domain_text,
        "metadata_content": meta,
    }


# ---- inventories (suite B; different wording from suite A) ----
INVOICE = (
    "1. table name: invoices(发票)，key fields: invoice_id, invoice_no, buyer_name, "
    "amount, tax_rate, issue_date, status。"
)
AP_BILL = (
    "1. table name: ap_bills(应付账单)，key fields: bill_id, vendor_id, due_date, "
    "amount_due, pay_status。"
)
VENDOR = (
    "1. table name: vendors(供应商)，key fields: vendor_id, vendor_name, contact_phone, "
    "bank_account, tax_id。"
)
WAREHOUSE = (
    "1. table name: warehouses(仓库)，key fields: warehouse_id, warehouse_name, city, "
    "capacity。"
)
STOCK_SNAP = (
    "1. table name: stock_snapshots(库存快照)，key fields: warehouse_id, sku_id, "
    "on_hand_qty, snapshot_date。"
)
SKU = (
    "1. table name: sku_master(SKU主数据)，key fields: sku_id, sku_code, title, brand, "
    "category_name。"
)
TICKET = (
    "1. table name: support_tickets(客服工单)，key fields: ticket_id, customer_id, "
    "subject, priority, status, created_at。"
)
CUSTOMER = (
    "1. table name: customers(客户)，key fields: customer_id, customer_name, email, "
    "phone, tier。"
)
COUPON = (
    "1. table name: coupons(优惠券)，key fields: coupon_id, coupon_code, discount_type, "
    "discount_value, valid_to, status。"
)
REDEEM = (
    "1. table name: coupon_redemptions(券核销)，key fields: redemption_id, coupon_id, "
    "order_id, redeemed_at。"
)
DEVICE = (
    "1. table name: iot_devices(设备)，key fields: device_id, device_sn, model, "
    "firmware_version, online_status。"
)
ALERT = (
    "1. table name: device_alerts(设备告警)，key fields: alert_id, device_id, "
    "alert_type, severity, raised_at。"
)
EMPLOYEE = (
    "1. table name: employees(员工)，key fields: emp_id, emp_name, dept_id, title, "
    "hire_date。"
)
ATTEND = (
    "1. table name: attendance_logs(考勤打卡)，key fields: emp_id, punch_time, "
    "punch_type, location。"
)
FLIGHT = (
    "1. table name: flights(航班)，key fields: flight_no, origin, destination, "
    "depart_at, arrive_at, status。"
)
BOOKING = (
    "1. table name: flight_bookings(机票订单)，key fields: booking_id, flight_no, "
    "passenger_name, seat_no, pay_status。"
)


CASES: List[CapCase] = [
    # ===== H. Clear handle (10) =====
    CapCase(
        "H01_invoice_by_no",
        "handle_clear",
        "查询发票号 INV-9001 的金额、税率和开票日期",
        "structured-mysql",
        [_mysql("发票管理", INVOICE)],
        True,
        True,
        True,
    ),
    CapCase(
        "H02_vendor_profile",
        "handle_clear",
        "查询供应商 V-88 的名称、联系电话和税号",
        "structured-mysql",
        [_mysql("供应商主数据", VENDOR)],
        True,
        True,
        True,
    ),
    CapCase(
        "H03_warehouse_list_beijing",
        "handle_clear",
        "北京有哪些仓库？给出仓库编码和名称",
        "structured-mysql",
        [_mysql("仓储主数据", WAREHOUSE)],
        True,
        True,
        True,
    ),
    CapCase(
        "H04_sku_by_brand",
        "handle_clear",
        "列出品牌为 Acme 的 SKU 编码和标题",
        "structured-mysql",
        [_mysql("SKU主数据", SKU)],
        True,
        True,
        True,
    ),
    CapCase(
        "H05_ticket_open_high",
        "handle_clear",
        "有哪些优先级为高且状态为打开的客服工单？",
        "structured-mysql",
        [_mysql("客服工单", TICKET)],
        True,
        True,
        True,
    ),
    CapCase(
        "H06_coupon_active",
        "handle_clear",
        "状态为启用的优惠券有哪些？给出券码和面额",
        "structured-mysql",
        [_mysql("营销优惠券", COUPON)],
        True,
        True,
        True,
    ),
    CapCase(
        "H07_device_offline",
        "handle_clear",
        "哪些设备当前 offline？给出 device_sn 和型号",
        "structured-mysql",
        [_mysql("物联网设备", DEVICE)],
        True,
        True,
        True,
    ),
    CapCase(
        "H08_employee_by_dept",
        "handle_clear",
        "部门 D10 有哪些员工？给出姓名和职位",
        "structured-mysql",
        [_mysql("人事主数据", EMPLOYEE)],
        True,
        True,
        True,
    ),
    CapCase(
        "H09_flight_status",
        "handle_clear",
        "航班 MU5101 今天的起飞到达时间和状态是什么？",
        "structured-mysql",
        [_mysql("航班运行", FLIGHT)],
        True,
        True,
        True,
    ),
    CapCase(
        "H10_ap_bill_due",
        "handle_clear",
        "查询应付账单 B-331 的到期日和应付金额",
        "structured-pg",
        [_pg("应付账款", AP_BILL)],
        True,
        True,
        True,
    ),
    # ===== I. Anchor handle + related-attr gap (10) =====
    CapCase(
        "I01_invoice_anchor_vendor_bank_gap",
        "handle_plus_gap",
        "查询发票 INV-9001 的金额，以及开票对应供应商的银行账号",
        "structured-mysql",
        [_mysql("发票", INVOICE)],
        True,
        True,
        True,
        "供应商",
    ),
    CapCase(
        "I02_ticket_anchor_customer_email_gap",
        "handle_plus_gap",
        "查询工单 T-100 的主题和优先级，并补充该客户的邮箱",
        "structured-mysql",
        [_mysql("客服工单", TICKET)],
        True,
        True,
        True,
        "客户",
    ),
    CapCase(
        "I03_stock_anchor_sku_title_gap",
        "handle_plus_gap",
        "查询仓库 WH-1 今日库存快照数量，并附上对应 SKU 标题",
        "structured-mysql",
        [_mysql("库存快照", STOCK_SNAP)],
        True,
        True,
        True,
        "SKU",
    ),
    CapCase(
        "I04_coupon_anchor_redeem_count_gap",
        "handle_plus_gap",
        "查询优惠券 C-VIP 的面额，以及它被核销了多少次",
        "structured-mysql",
        [_mysql("优惠券", COUPON)],
        True,
        True,
        True,
        "核销",
    ),
    CapCase(
        "I05_device_anchor_alert_gap",
        "handle_plus_gap",
        "查询设备 SN-900 的固件版本，以及它最近产生的告警类型",
        "structured-mysql",
        [_mysql("设备资产", DEVICE)],
        True,
        True,
        True,
        "告警",
    ),
    CapCase(
        "I06_employee_anchor_attendance_gap",
        "handle_plus_gap",
        "查询员工 E-17 的姓名和入职日期，以及他今天的打卡记录",
        "structured-mysql",
        [_mysql("员工", EMPLOYEE)],
        True,
        True,
        True,
        "打卡",
    ),
    CapCase(
        "I07_flight_anchor_booking_pay_gap",
        "handle_plus_gap",
        "查询航班 CZ3101 的起飞时间，以及该航班机票订单的支付状态",
        "structured-mysql",
        [_mysql("航班", FLIGHT)],
        True,
        True,
        True,
        "支付",
    ),
    CapCase(
        "I08_ap_anchor_vendor_phone_gap",
        "handle_plus_gap",
        "查询应付账单 B-331 的应付金额，并补充供应商联系电话",
        "structured-pg",
        [_pg("应付", AP_BILL)],
        True,
        True,
        True,
        "供应商",
    ),
    CapCase(
        "I09_customer_anchor_ticket_count_gap",
        "handle_plus_gap",
        "查询客户 CUST-9 的等级和手机号，以及他有多少张开着的工单",
        "structured-mysql",
        [_mysql("客户主数据", CUSTOMER)],
        True,
        True,
        True,
        "工单",
    ),
    CapCase(
        "I10_sku_anchor_onhand_gap",
        "handle_plus_gap",
        "查询 SKU S-200 的品牌和类目，以及它在各仓库的在库数量",
        "structured-mysql",
        [_mysql("SKU", SKU)],
        True,
        True,
        True,
        "库存",
    ),
    # ===== J. Contribute-only / not primary (8) =====
    CapCase(
        "J01_vendor_on_invoice_anchor",
        "contribute_only",
        "查询发票 INV-9001 的金额，以及开票对应供应商的银行账号",
        "structured-mysql",
        [_mysql("供应商", VENDOR)],
        True,
        False,
        True,
        "发票",
    ),
    CapCase(
        "J02_customer_on_ticket_anchor",
        "contribute_only",
        "查询工单 T-100 的主题和优先级，并补充该客户的邮箱",
        "structured-mysql",
        [_mysql("客户", CUSTOMER)],
        True,
        False,
        True,
        "工单",
    ),
    CapCase(
        "J03_sku_on_stock_anchor",
        "contribute_only",
        "查询仓库 WH-1 今日库存快照数量，并附上对应 SKU 标题",
        "structured-mysql",
        [_mysql("SKU主数据", SKU)],
        True,
        False,
        True,
        "库存",
    ),
    CapCase(
        "J04_redeem_on_coupon_anchor",
        "contribute_only",
        "查询优惠券 C-VIP 的面额，以及它被核销了多少次",
        "structured-mysql",
        [_mysql("券核销", REDEEM)],
        True,
        False,
        True,
        "优惠券",
    ),
    CapCase(
        "J05_alert_on_device_anchor",
        "contribute_only",
        "查询设备 SN-900 的固件版本，以及它最近产生的告警类型",
        "structured-mysql",
        [_mysql("设备告警", ALERT)],
        True,
        False,
        True,
        "设备",
    ),
    CapCase(
        "J06_attend_on_employee_anchor",
        "contribute_only",
        "查询员工 E-17 的姓名和入职日期，以及他今天的打卡记录",
        "structured-mysql",
        [_mysql("考勤", ATTEND)],
        True,
        False,
        True,
        "员工",
    ),
    CapCase(
        "J07_booking_on_flight_anchor",
        "contribute_only",
        "查询航班 CZ3101 的起飞时间，以及该航班机票订单的支付状态",
        "structured-mysql",
        [_mysql("机票订单", BOOKING)],
        True,
        False,
        True,
        "航班",
    ),
    CapCase(
        "J08_warehouse_on_sku_query",
        "contribute_only",
        "列出品牌为 Acme 的 SKU 编码和标题",
        "structured-mysql",
        [_mysql("仓库", WAREHOUSE)],
        False,
        False,
        False,
    ),
    # ===== K. Hard reject unrelated (8) =====
    CapCase(
        "K01_invoice_vs_weather",
        "reject",
        "上海明天会下雪吗？",
        "structured-mysql",
        [_mysql("发票", INVOICE)],
        False,
        False,
        False,
    ),
    CapCase(
        "K02_ticket_vs_k8s",
        "reject",
        "如何给 Kubernetes Deployment 做滚动更新？",
        "structured-mysql",
        [_mysql("客服工单", TICKET)],
        False,
        False,
        False,
    ),
    CapCase(
        "K03_coupon_vs_rocket",
        "reject",
        "火箭二级发动机比冲怎么计算？",
        "structured-mysql",
        [_mysql("优惠券", COUPON)],
        False,
        False,
        False,
    ),
    CapCase(
        "K04_device_vs_legal",
        "reject",
        "劳动合同解除补偿金的法定标准是什么？",
        "structured-mysql",
        [_mysql("物联网设备", DEVICE)],
        False,
        False,
        False,
    ),
    CapCase(
        "K05_flight_vs_hr_leave",
        "reject",
        "员工年假余额如何核算？",
        "structured-mysql",
        [_mysql("航班", FLIGHT)],
        False,
        False,
        False,
    ),
    CapCase(
        "K06_employee_vs_payment_gateway",
        "reject",
        "支付网关幂等键冲突怎么排查？",
        "structured-mysql",
        [_mysql("员工", EMPLOYEE)],
        False,
        False,
        False,
    ),
    CapCase(
        "K07_docs_hr_vs_flight",
        "reject",
        "航班 MU5101 是否延误？",
        "unstructured",
        [
            _docs(
                "员工手册",
                document_summary="入职须知、着装规范与行为准则",
                topics=["入职", "着装", "行为准则"],
            )
        ],
        False,
        False,
        False,
    ),
    CapCase(
        "K08_code_billing_vs_firmware",
        "reject",
        "设备固件 OTA 升级协议怎么实现？",
        "code",
        [
            _code(
                "计费对账代码",
                summary="billing-reconcile 仅处理账单差额核对",
                file_summary="ReconcileJob.java",
            )
        ],
        False,
        False,
        False,
    ),
    # ===== L. Explicit peer primaries (6) =====
    CapCase(
        "L01_invoice_and_ticket_peer",
        "peer_primary",
        "请分别独立查询以下两项（对等主题）：(1) 发票 INV-9001 金额 (2) 打开状态的高优先级工单列表",
        "structured-mysql",
        [_mysql("发票", INVOICE)],
        True,
        False,
        True,
        "工单",
    ),
    CapCase(
        "L02_coupon_and_device_peer",
        "peer_primary",
        "请分别独立统计以下两项（对等主题）：(1) 启用中优惠券数量 (2) offline 设备数量",
        "structured-mysql",
        [_mysql("优惠券", COUPON)],
        True,
        False,
        True,
        "设备",
    ),
    CapCase(
        "L03_employee_and_flight_peer",
        "peer_primary",
        "请分别独立查询以下两项（对等主题）：(1) 部门 D10 员工名单 (2) 航班 MU5101 状态",
        "structured-mysql",
        [_mysql("员工", EMPLOYEE)],
        True,
        False,
        True,
        "航班",
    ),
    CapCase(
        "L04_vendor_and_warehouse_peer",
        "peer_primary",
        "请分别独立查询以下两项（对等主题）：(1) 供应商 V-88 税号 (2) 北京仓库列表",
        "structured-mysql",
        [_mysql("供应商", VENDOR)],
        True,
        False,
        True,
        "仓库",
    ),
    CapCase(
        "L05_code_ota_and_billing_peer",
        "peer_primary",
        "请分别独立说明以下两项实现（对等主题）：(1) 设备固件 OTA 升级 (2) 账单差额核对任务",
        "code",
        [
            _code(
                "OTA 升级服务代码",
                summary="firmware-ota 负责分片下载与版本校验",
                file_summary="OtaCoordinator.java",
            )
        ],
        True,
        False,
        True,
        "账单",
    ),
    CapCase(
        "L06_docs_policy_and_revenue_peer",
        "peer_primary",
        "请分别独立查询以下两项（对等主题）：(1) 差旅报销审批节点说明 (2) 本季度营收汇总口径",
        "unstructured",
        [
            _docs(
                "差旅报销制度",
                document_summary="差旅申请、审批节点与票据提交要求",
                topics=["差旅", "报销", "审批"],
            )
        ],
        True,
        False,
        True,
        "营收",
    ),
    # ===== M. Code / docs specifics (8) =====
    CapCase(
        "M01_code_ota_handle",
        "code_docs",
        "设备固件 OTA 的断点续传在哪个类实现？",
        "code",
        [
            _code(
                "固件 OTA 服务",
                summary="支持分片下载与断点续传",
                file_summary="ResumeDownloadHandler.java, OtaCoordinator.java",
            )
        ],
        True,
        True,
        True,
    ),
    CapCase(
        "M02_code_live_invoice_not_handle",
        "code_docs",
        "发票号 INV-9001 的开票金额是多少？",
        "code",
        [
            _code(
                "发票领域服务代码",
                summary="InvoiceService 与 DTO 映射",
                file_summary="InvoiceController.java",
            )
        ],
        True,
        False,
        False,
    ),
    CapCase(
        "M03_docs_travel_policy_handle",
        "code_docs",
        "差旅报销需要哪些审批节点？",
        "unstructured",
        [
            _docs(
                "差旅报销制度",
                document_summary="差旅申请、审批节点与票据提交要求",
                topics=["差旅", "报销", "审批"],
            )
        ],
        True,
        True,
        True,
    ),
    CapCase(
        "M04_docs_sample_not_live_device",
        "code_docs",
        "设备 SN-900 现在是否在线？",
        "unstructured",
        [
            _docs(
                "设备 API 文档",
                document_summary="Swagger 示例含 online_status 字段说明",
                topics=["设备 API", "字段说明"],
            )
        ],
        True,
        False,
        False,
    ),
    CapCase(
        "M05_code_attend_service_handle",
        "code_docs",
        "考勤异常申诉的状态机在哪里定义？",
        "code",
        [
            _code(
                "考勤服务代码",
                summary="attendance 服务定义异常申诉状态机",
                file_summary="AppealStateMachine.java",
            )
        ],
        True,
        True,
        True,
    ),
    CapCase(
        "M06_docs_unrelated_devops",
        "code_docs",
        "GitOps 里如何做多集群同步？",
        "unstructured",
        [
            _docs(
                "差旅报销制度",
                document_summary="差旅申请与报销票据规范",
                topics=["差旅", "报销"],
            )
        ],
        False,
        False,
        False,
    ),
    CapCase(
        "M07_code_partial_peer_missing",
        "code_docs",
        "请分别独立说明以下两项实现（对等主题）：(1) 考勤异常申诉状态机 (2) 固件 OTA 断点续传",
        "code",
        [
            _code(
                "考勤服务代码",
                summary="AppealStateMachine 定义申诉流转",
                file_summary="AppealStateMachine.java",
            )
        ],
        True,
        False,
        True,
        "OTA",
    ),
    CapCase(
        "M08_docs_live_booking_not_handle",
        "code_docs",
        "机票订单 BK-55 的支付状态是什么？",
        "unstructured",
        [
            _docs(
                "机票 API 文档",
                document_summary="样例 JSON 展示 pay_status 枚举含义",
                topics=["机票 API", "支付字段"],
            )
        ],
        True,
        False,
        False,
    ),
]


assert len(CASES) == 50, f"expected 50 cases, got {len(CASES)}"


def _stability_runs() -> int:
    try:
        return max(1, int(os.getenv("SD_CAP_LIVE_STABILITY_RUNS", "3") or 3))
    except ValueError:
        return 3


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
        data_descriptors=["live-dd-b"],
        dd_namespace="default",
        agent_id="LiveCapabilityAgent50B",
    )


def _flags(result: Dict[str, Any]) -> tuple:
    return (
        bool(result.get("domain_match")),
        bool(result.get("can_handle")),
        bool(result.get("can_contribute")),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_live_sd_capability_50b(case: CapCase):
    executor = _executor()
    runs = _stability_runs()
    outcomes = []
    last: Dict[str, Any] = {}

    for i in range(runs):
        last = await executor._judge_member_capability_with_llm(
            query=case.query,
            signatures=case.signatures,
            agent_name=f"LiveB-{case.name}",
            agent_url="http://live-capability-b:10100",
            descriptor_type=case.descriptor_type,
            request_metadata={
                "run_id": f"live50b-{case.name}-r{i}",
                "trace_id": "c" * 32,
                "user_id": "live-capability-50b",
            },
        )
        outcomes.append(_flags(last))

    print(
        f"\n[{case.category}/{case.name}] runs={outcomes} "
        f"missing={last.get('missing_requirements')} "
        f"reason={(last.get('reason') or '')[:200]}"
    )

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
