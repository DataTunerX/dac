"""Accuracy E2E: 10 strict ground-truth cases with real LLM scoring for doc-agent.

Each case asserts:
- primary block score >= primary_min_score (default 8.0)
- primary block MUST be selected
- noise blocks score <= noise_max_score (default 3.0)
- primary beats noise by >= min_gap_vs_noise (default 5.0)
- misleading blocks (if any) scored below primary with explicit gap
- noise blocks MUST NOT be selected (max_blocks=1 for single-primary cases)

Requires DASHSCOPE_API_KEY. Run:
  cd dac/doc-agent
  DASHSCOPE_API_KEY=sk-... python tests/test_knowledge_llm_score_accuracy_e2e.py
  DASHSCOPE_API_KEY=sk-... pytest tests/test_knowledge_llm_score_accuracy_e2e.py -v -s -m integration
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from model_sdk import ModelManager

from agent.dataservices_client import MetadataValuesResult
from agent.doc_agent import DocAgent
from agent.tools.knowledge_context_budget import (
    select_blocks_by_score,
    should_score_and_select,
    total_block_chars,
)
from agent.tools.knowledge_llm_score import score_knowledge_blocks_batch_parallel

pytestmark = pytest.mark.integration

MODEL = os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def _api_key() -> Optional[str]:
    key = (
        os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if not key or key == "sk-xxx":
        return None
    return key


def _skip_without_api_key() -> None:
    if _api_key() is None:
        pytest.skip("Set DASHSCOPE_API_KEY or OPENAI_API_KEY for live LLM accuracy E2E")


def _make_llm():
    key = _api_key()
    assert key
    manager = ModelManager()
    return manager.get_llm(
        provider="openai_compatible",
        api_key=key,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


def _parse_llm_output(answer: Any) -> dict:
    agent = DocAgent(
        api_key=_api_key(),
        base_url=BASE_URL,
        model=MODEL,
        data_services_url="http://127.0.0.1:1",
        query="",
    )
    return agent.format_llm_output(answer) or {}


def _block(
    block_id: str,
    text: str,
    *,
    metadata_value: str = "",
) -> Dict[str, Any]:
    return {
        "id": block_id,
        "text": text,
        "metadata_value": metadata_value or f"摘要：{block_id}",
    }


def _pad_blocks(blocks: List[Dict[str, Any]], min_chars: int = 200) -> List[Dict[str, Any]]:
    out = [dict(b) for b in blocks]
    total = total_block_chars(out)
    if total >= min_chars:
        return out
    pad = min_chars - total + 1
    out[-1]["text"] = (out[-1].get("text") or "") + ("\n补充说明。\n" * pad)
    return out


@dataclass
class AccuracyCase:
    """Strict ground-truth checks for knowledge block LLM scoring accuracy."""

    id: str
    query: str
    blocks: List[Dict[str, Any]]
    primary: Optional[str]
    primary_alternatives: Set[str] = field(default_factory=set)
    primary_min_score: float = 8.0
    noise_blocks: Set[str] = field(default_factory=set)
    noise_max_score: float = 3.0
    min_gap_vs_noise: float = 5.0
    misleading: Optional[str] = None
    misleading_max_score: Optional[float] = 6.0
    min_gap_vs_misleading: float = 2.0
    trigger_chars: int = 100
    max_blocks: int = 1
    all_noise_max_score: float = 3.0
    all_noise_ceiling: float = 7.0


ACCURACY_CASES: List[AccuracyCase] = [
    AccuracyCase(
        id="accuracy_01_login_not_welcome_email",
        query="用户登录时如何验证用户名和密码",
        blocks=_pad_blocks([
            _block(
                "auth-overview",
                "认证模块概述：系统采用 JWT 与会话双模式，支持 OAuth2 第三方登录。",
                metadata_value="认证模块总览",
            ),
            _block(
                "login-validation",
                "用户登录验证流程：\n"
                "1. 接收 username 与 password；\n"
                "2. 根据 username 查询用户记录；\n"
                "3. 使用 bcrypt 比对 password 与 password_hash；\n"
                "4. 验证通过后签发 access_token。",
                metadata_value="登录用户名密码校验步骤",
            ),
            _block(
                "email-welcome",
                "欢迎邮件模板说明：新用户注册后发送 HTML 欢迎信，包含产品引导链接。",
                metadata_value="欢迎邮件",
            ),
            _block(
                "deployment-notes",
                "部署说明：生产环境需配置 HTTPS 与 Redis 会话存储。",
                metadata_value="部署文档",
            ),
        ]),
        primary="login-validation",
        noise_blocks={"email-welcome", "deployment-notes"},
        misleading="auth-overview",
        misleading_max_score=6.0,
    ),
    AccuracyCase(
        id="accuracy_02_sales_sql_not_catalog",
        query="按商品维度统计每个商品的销售总额，GROUP BY 聚合 SQL 在哪",
        blocks=_pad_blocks([
            _block(
                "sales-report-sql",
                "销售统计 SQL：\n"
                "SELECT product_id, SUM(quantity * unit_price) AS sales_total\n"
                "FROM order_items GROUP BY product_id;",
                metadata_value="按商品聚合销售总额 SQL",
            ),
            _block(
                "product-catalog",
                "商品目录管理：支持批量导入 CSV 与上下架操作。",
                metadata_value="商品目录",
            ),
            _block(
                "order-total-faq",
                "FAQ：单笔订单总金额 = 各 order_item 金额之和 + 运费 - 优惠。",
                metadata_value="订单总金额 FAQ",
            ),
            _block(
                "style-guide",
                "文档风格指南：标题使用二级标题，术语保持一致。",
                metadata_value="文档规范",
            ),
        ]),
        primary="sales-report-sql",
        noise_blocks={"product-catalog", "order-total-faq", "style-guide"},
    ),
    AccuracyCase(
        id="accuracy_03_refund_not_order_list",
        query="用户申请退款后系统如何处理",
        blocks=_pad_blocks([
            _block(
                "refund-process",
                "退款处理流程：\n"
                "1. 校验订单状态是否可退款；\n"
                "2. 调用支付网关发起原路退款；\n"
                "3. 更新订单状态为 REFUNDED；\n"
                "4. 通知用户退款结果。",
                metadata_value="退款处理 SOP",
            ),
            _block(
                "order-list-query",
                "订单列表查询：支持按用户 ID、时间范围分页查询历史订单。",
                metadata_value="订单列表",
            ),
            _block(
                "log-config",
                "日志配置：生产环境 log level 设为 INFO，敏感字段脱敏。",
                metadata_value="日志配置",
            ),
        ]),
        primary="refund-process",
        noise_blocks={"order-list-query", "log-config"},
    ),
    AccuracyCase(
        id="accuracy_04_inventory_not_shipment",
        query="下单时如何扣减商品库存",
        blocks=_pad_blocks([
            _block(
                "inventory-deduct",
                "库存扣减规则：下单成功后立即扣减可用库存；若库存不足则拒绝下单并返回错误码 OUT_OF_STOCK。",
                metadata_value="下单库存扣减",
            ),
            _block(
                "shipment-notify",
                "发货通知：仓库出库后向用户推送物流单号。",
                metadata_value="发货通知",
            ),
            _block(
                "product-detail",
                "商品详情页展示 SKU 规格、价格与库存余量。",
                metadata_value="商品详情",
            ),
        ]),
        primary="inventory-deduct",
        noise_blocks={"shipment-notify", "product-detail"},
    ),
    AccuracyCase(
        id="accuracy_05_order_api_not_internal",
        query="创建订单的 REST API 接口定义在哪",
        blocks=_pad_blocks([
            _block(
                "order-api-spec",
                "接口文档 - 创建订单：\n"
                "POST /api/v1/orders\n"
                "Request: CreateOrderRequest\n"
                "Response: 201 Created + Order JSON",
                metadata_value="创建订单 API 规范",
            ),
            _block(
                "order-service-internal",
                "OrderService 内部实现：封装持久化与领域校验，不对外暴露 HTTP。",
                metadata_value="OrderService 内部说明",
            ),
            _block(
                "json-utils",
                "JSON 工具类：提供 toJson/fromJson 辅助方法。",
                metadata_value="JSON 工具",
            ),
        ]),
        primary="order-api-spec",
        noise_blocks={"json-utils", "order-service-internal"},
        misleading="order-service-internal",
        misleading_max_score=5.0,
    ),
    AccuracyCase(
        id="accuracy_06_join_query_not_glossary",
        query="订单和订单项之间是什么关系，如何关联查询",
        blocks=_pad_blocks([
            _block(
                "order-entity",
                "订单实体 Order：一对多关联 OrderItem，通过 order_id 外键关联。",
                metadata_value="Order 实体关系",
            ),
            _block(
                "order-item-entity",
                "订单项 OrderItem：包含 product_id、quantity、unit_price 等字段。",
                metadata_value="OrderItem 实体",
            ),
            _block(
                "order-join-query",
                "关联查询示例：SELECT * FROM orders o JOIN order_items oi ON o.id = oi.order_id WHERE o.id = ?",
                metadata_value="订单与订单项 JOIN 查询",
            ),
            _block(
                "glossary",
                "术语表：SKU、SPU、履约、对账等电商常用术语解释。",
                metadata_value="术语表",
            ),
        ]),
        primary="order-join-query",
        noise_blocks={"glossary"},
        misleading="order-item-entity",
        misleading_max_score=6.0,
        min_gap_vs_misleading=2.0,
    ),
    AccuracyCase(
        id="accuracy_07_payment_callback_not_health",
        query="支付回调通知如何处理",
        blocks=_pad_blocks([
            _block(
                "pay-callback-handler",
                "回调处理逻辑：onPaymentSuccess 调用 orderService.markPaid(orderId)。",
                metadata_value="支付回调处理逻辑",
            ),
            _block(
                "pay-callback-api",
                "支付回调接口 POST /pay/callback：验签后解析 PaymentNotify，更新订单为 PAID。",
                metadata_value="支付回调 API",
            ),
            _block(
                "health-check",
                "健康检查：/health 返回 200 与依赖组件状态。",
                metadata_value="健康检查",
            ),
            _block(
                "cache-warm",
                "缓存预热：启动时加载热门商品到 Redis。",
                metadata_value="缓存预热",
            ),
        ]),
        primary="pay-callback-handler",
        primary_alternatives={"pay-callback-api"},
        noise_blocks={"health-check", "cache-warm"},
    ),
    AccuracyCase(
        id="accuracy_08_coupon_not_faq",
        query="优惠券校验和使用逻辑",
        blocks=_pad_blocks([
            _block(
                "coupon-service",
                "CouponService：validateCoupon 校验券码有效性；applyCoupon 将优惠金额写入订单。",
                metadata_value="优惠券校验与使用",
            ),
            _block(
                "coupon-validator",
                "CouponValidator：检查券码过期时间与适用商品范围。",
                metadata_value="优惠券校验器",
            ),
            _block(
                "coupon-faq",
                "FAQ：优惠券不可叠加使用。",
                metadata_value="优惠券 FAQ",
            ),
            _block(
                "banner-ops",
                "首页 Banner 轮播配置：运营可在后台拖拽排序 Banner。",
                metadata_value="Banner 运营",
            ),
        ]),
        primary="coupon-service",
        noise_blocks={"banner-ops"},
        misleading="coupon-faq",
        misleading_max_score=6.0,
        min_gap_vs_misleading=2.0,
    ),
    AccuracyCase(
        id="accuracy_09_order_flow_not_banner",
        query="创建订单的完整业务流程是什么",
        blocks=_pad_blocks([
            _block(
                "order-flow",
                "创建订单业务流程：\n"
                "1. 校验商品与库存；\n"
                "2. 计算价格与优惠；\n"
                "3. 写入 orders 与 order_items；\n"
                "4. 发送订单创建事件。",
                metadata_value="创建订单完整流程",
            ),
            _block(
                "order-api",
                "创建订单 API：POST /api/v1/orders，请求体 CreateOrderRequest。",
                metadata_value="创建订单 REST 接口",
            ),
            _block(
                "banner-ops",
                "首页 Banner 轮播配置：运营可在后台拖拽排序 Banner。",
                metadata_value="Banner 运营",
            ),
        ]),
        primary="order-flow",
        noise_blocks={"banner-ops"},
        misleading="order-api",
        misleading_max_score=7.0,
    ),
    AccuracyCase(
        id="accuracy_10_all_noise_no_answer",
        query="每个商品的销售总额统计 SQL 在哪",
        blocks=_pad_blocks([
            _block("imports-guide", "文档编写规范：标题层级与术语一致性要求。"),
            _block(
                "application-config",
                "应用配置说明：Datasource、Redis、消息队列连接参数。",
            ),
            _block(
                "log-formatter",
                "日志格式化工具：统一 trace_id 与 timestamp 格式。",
            ),
        ]),
        primary=None,
        noise_blocks={"imports-guide", "application-config", "log-formatter"},
        all_noise_max_score=3.0,
        all_noise_ceiling=7.0,
    ),
]


async def _run_accuracy(case: AccuracyCase) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    os.environ["DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS"] = str(case.trigger_chars)
    os.environ["DOC_KNOWLEDGE_LLM_SCORE_ENABLED"] = "true"
    os.environ["DOC_KNOWLEDGE_MAX_BLOCKS"] = str(case.max_blocks)

    blocks = _pad_blocks([dict(b) for b in case.blocks], min_chars=case.trigger_chars + 50)
    assert should_score_and_select(blocks), (
        f"{case.id}: total chars must exceed trigger "
        f"({total_block_chars(blocks)} <= {case.trigger_chars})"
    )

    llm = _make_llm()
    scored = await score_knowledge_blocks_batch_parallel(
        blocks,
        query=case.query,
        llm=llm,
        parse_output=_parse_llm_output,
    )
    selected, report = select_blocks_by_score(scored)
    return scored, selected, report


def _assert_accuracy(
    case: AccuracyCase,
    scored: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    report: Dict[str, Any],
) -> None:
    scores = {s["id"]: float(s["relevance_score"]) for s in scored}
    selected_ids = {s["id"] for s in selected}

    for s in scored:
        assert s.get("score_description"), f"{case.id}: missing description for {s['id']}"
        assert s.get("relevance_score") is not None
        assert 0.0 <= float(s["relevance_score"]) <= 10.0

    if case.primary is None:
        for noise in case.noise_blocks:
            assert noise in scores, f"{case.id}: missing noise block {noise}"
            assert scores[noise] <= case.all_noise_max_score, (
                f"{case.id}: noise {noise} score {scores[noise]} > max {case.all_noise_max_score}"
            )
            assert scores[noise] < case.all_noise_ceiling, (
                f"{case.id}: noise {noise} score {scores[noise]} must stay below {case.all_noise_ceiling}"
            )
        print(f"\n[{case.id}] query={case.query!r} (all-noise case)")
        print(f"  scores={scores}")
        print(f"  selected={selected_ids}")
        return

    assert case.primary in scores, f"{case.id}: missing primary {case.primary}"
    acceptable = {case.primary} | case.primary_alternatives
    primary_score = scores[case.primary]
    assert primary_score >= case.primary_min_score, (
        f"{case.id}: {case.primary} score {primary_score} < min {case.primary_min_score}"
    )
    for alt in case.primary_alternatives:
        assert alt in scores, f"{case.id}: missing alternative primary {alt}"
        assert scores[alt] >= case.primary_min_score, (
            f"{case.id}: {alt} score {scores[alt]} < min {case.primary_min_score}"
        )
    assert selected_ids & acceptable, (
        f"{case.id}: none of {acceptable} selected, scores={scores}, selected={selected_ids}"
    )

    for noise in case.noise_blocks:
        assert noise in scores, f"{case.id}: missing noise block {noise}"
        assert scores[noise] <= case.noise_max_score, (
            f"{case.id}: noise {noise} score {scores[noise]} > max {case.noise_max_score}"
        )
        assert primary_score - scores[noise] >= case.min_gap_vs_noise, (
            f"{case.id}: gap {case.primary}({primary_score}) vs {noise}({scores[noise]}) "
            f"< {case.min_gap_vs_noise}"
        )
        assert noise not in selected_ids, (
            f"{case.id}: noise {noise} must not be selected, scores={scores}"
        )

    if case.misleading:
        assert case.misleading in scores, f"{case.id}: missing misleading {case.misleading}"
        mis_score = scores[case.misleading]
        if case.misleading_max_score is not None:
            assert mis_score <= case.misleading_max_score, (
                f"{case.id}: misleading {case.misleading} score {mis_score} too high"
            )
        if case.min_gap_vs_misleading > 0:
            assert primary_score - mis_score >= case.min_gap_vs_misleading, (
                f"{case.id}: {case.primary}({primary_score}) should beat misleading "
                f"{case.misleading}({mis_score}) by >= {case.min_gap_vs_misleading}"
            )

    assert report["selected_count"] <= case.max_blocks, (
        f"{case.id}: selected_count {report['selected_count']} > max_blocks {case.max_blocks}"
    )

    print(f"\n[{case.id}] query={case.query!r}")
    print(f"  scores={scores}")
    print(f"  selected={selected_ids}")
    print(f"  primary={case.primary} score={primary_score}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ACCURACY_CASES, ids=[c.id for c in ACCURACY_CASES])
async def test_live_knowledge_score_accuracy(case: AccuracyCase):
    """Strict accuracy: real LLM must rank primary well above noise/misleading blocks."""
    _skip_without_api_key()
    scored, selected, report = await _run_accuracy(case)
    _assert_accuracy(case, scored, selected, report)


@pytest.mark.asyncio
async def test_live_get_text_by_ids_accuracy_sales_sql():
    """Full get_text_by_ids path: only primary SQL block in output."""
    _skip_without_api_key()
    case = next(c for c in ACCURACY_CASES if c.id == "accuracy_02_sales_sql_not_catalog")

    os.environ["DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS"] = str(case.trigger_chars)
    os.environ["DOC_KNOWLEDGE_LLM_SCORE_ENABLED"] = "true"
    os.environ["DOC_KNOWLEDGE_MAX_BLOCKS"] = str(case.max_blocks)

    items = [
        {"id": b["id"], "text": b["text"], "metadata_value": b.get("metadata_value", "")}
        for b in _pad_blocks(case.blocks, min_chars=case.trigger_chars + 50)
    ]
    result = MetadataValuesResult(status="success", data={"docs": items})
    llm = _make_llm()
    text, meta = await result.get_text_by_ids(
        [b["id"] for b in items],
        query=case.query,
        llm=llm,
        parse_output=_parse_llm_output,
    )

    assert meta["score_select_applied"] is True
    assert "GROUP BY product_id" in text
    assert "商品目录" not in text
    assert "文档风格" not in text
    assert case.primary in {s["id"] for s in result.get_blocks_by_ids([case.primary])}
    print(f"\n[get_text_by_ids accuracy] len={len(text)} meta={meta}")


async def _main() -> int:
    if _api_key() is None:
        print("Set DASHSCOPE_API_KEY for live accuracy E2E")
        return 1

    passed = 0
    failed: List[str] = []
    for case in ACCURACY_CASES:
        try:
            scored, selected, report = await _run_accuracy(case)
            _assert_accuracy(case, scored, selected, report)
            passed += 1
            print(f"PASS {case.id}")
        except AssertionError as exc:
            failed.append(f"{case.id}: {exc}")
            print(f"FAIL {case.id}: {exc}")

    try:
        await test_live_get_text_by_ids_accuracy_sales_sql()
        print("PASS get_text_by_ids_accuracy")
    except AssertionError as exc:
        failed.append(f"get_text_by_ids_accuracy: {exc}")
        print(f"FAIL get_text_by_ids_accuracy: {exc}")

    print(f"\nAccuracy result: {passed}/{len(ACCURACY_CASES)} cases passed")
    if failed:
        print("Failures:")
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
