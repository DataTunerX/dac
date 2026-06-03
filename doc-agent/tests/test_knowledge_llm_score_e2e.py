"""E2E integration: real LLM batch scoring + knowledge block selection for doc-agent.

Requires DASHSCOPE_API_KEY (or OPENAI_API_KEY). Skipped when unset.

Run all 10 live cases:
  cd dac/doc-agent
  DASHSCOPE_API_KEY=sk-... pytest tests/test_knowledge_llm_score_e2e.py -v -s -m integration

Or run directly:
  DASHSCOPE_API_KEY=sk-... python tests/test_knowledge_llm_score_e2e.py
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pytest
from model_sdk import ModelManager

from agent.dataservices_client import MetadataValuesResult
from agent.doc_agent import DocAgent
from agent.tools.knowledge_context_budget import (
    select_blocks_by_score,
    should_score_and_select,
    total_block_chars,
)
from agent.tools.knowledge_llm_score import (
    score_knowledge_blocks_batch_parallel,
    split_blocks_into_batches,
)

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
        pytest.skip("Set DASHSCOPE_API_KEY or OPENAI_API_KEY for live LLM E2E test")


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


@dataclass
class KnowledgeScoreSelectCase:
    id: str
    query: str
    blocks: List[Dict[str, Any]]
    must_select: Set[str] = field(default_factory=set)
    must_exclude: Set[str] = field(default_factory=set)
    top_must_beat: Dict[str, Set[str]] = field(default_factory=dict)
    trigger_chars: int = 100
    max_blocks: int = 10
    min_selected: int = 1
    max_selected: Optional[int] = None
    extra_assert: Optional[Callable[[List[Dict], List[Dict], Dict], None]] = None


def _pad_blocks(blocks: List[Dict[str, Any]], min_chars: int = 200) -> List[Dict[str, Any]]:
    """Ensure total content exceeds default trigger for scoring."""
    out = [dict(b) for b in blocks]
    total = total_block_chars(out)
    if total >= min_chars:
        return out
    pad = min_chars - total + 1
    out[-1]["text"] = (out[-1].get("text") or "") + ("\n补充说明。\n" * pad)
    return out


E2E_CASES: List[KnowledgeScoreSelectCase] = [
    KnowledgeScoreSelectCase(
        id="01_user_login_doc",
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
        must_select={"login-validation"},
        must_exclude={"email-welcome", "deployment-notes"},
        top_must_beat={"login-validation": {"email-welcome", "deployment-notes"}},
    ),
    KnowledgeScoreSelectCase(
        id="02_create_order_doc",
        query="创建订单的完整流程是什么",
        blocks=_pad_blocks([
            _block(
                "order-api",
                "创建订单 API：POST /api/v1/orders，请求体 CreateOrderRequest，"
                "返回 OrderResponse。",
                metadata_value="创建订单 REST 接口",
            ),
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
                "banner-ops",
                "首页 Banner 轮播配置：运营可在后台拖拽排序 Banner。",
                metadata_value="Banner 运营",
            ),
        ]),
        must_select={"order-flow"},
        must_exclude={"banner-ops"},
        top_must_beat={"order-flow": {"banner-ops", "order-api"}},
        trigger_chars=300,
    ),
    KnowledgeScoreSelectCase(
        id="03_refund_flow_doc",
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
        must_select={"refund-process"},
        must_exclude={"log-config"},
        top_must_beat={"refund-process": {"order-list-query", "log-config"}},
    ),
    KnowledgeScoreSelectCase(
        id="04_inventory_deduct_doc",
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
        must_select={"inventory-deduct"},
        top_must_beat={"inventory-deduct": {"shipment-notify", "product-detail"}},
        max_blocks=1,
        max_selected=1,
    ),
    KnowledgeScoreSelectCase(
        id="05_order_api_doc",
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
        must_select={"order-api-spec"},
        top_must_beat={"order-api-spec": {"json-utils"}},
    ),
    KnowledgeScoreSelectCase(
        id="06_order_relation_doc",
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
        must_select={"order-entity", "order-join-query"},
        must_exclude={"glossary"},
        min_selected=2,
        trigger_chars=350,
    ),
    KnowledgeScoreSelectCase(
        id="07_sales_aggregate_doc",
        query="查询每个商品的销售总额",
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
        ]),
        must_select={"sales-report-sql"},
        must_exclude={"product-catalog"},
        top_must_beat={"sales-report-sql": {"product-catalog", "order-total-faq"}},
    ),
    KnowledgeScoreSelectCase(
        id="08_parallel_batch_8_blocks",
        query="支付回调通知如何处理",
        blocks=_pad_blocks([
            _block("pay-overview", "支付模块概述：支持微信、支付宝与银联。"),
            _block(
                "pay-callback-api",
                "支付回调接口 POST /pay/callback：验签后解析 PaymentNotify，更新订单为 PAID。",
            ),
            _block(
                "pay-callback-handler",
                "回调处理逻辑：onPaymentSuccess 调用 orderService.markPaid(orderId)。",
            ),
            _block("audit-log", "审计日志规范：记录 operator、action、timestamp。"),
            _block("metrics", "监控指标：QPS、P99 延迟、错误率看板说明。"),
            _block("health-check", "健康检查：/health 返回 200 与依赖组件状态。"),
            _block("cache-warm", "缓存预热：启动时加载热门商品到 Redis。"),
            _block("changelog", "版本变更记录：v2.1 重构支付模块。"),
        ]),
        must_select={"pay-callback-api", "pay-callback-handler"},
        top_must_beat={
            "pay-callback-api": {"cache-warm", "health-check", "metrics"},
            "pay-callback-handler": {"cache-warm", "health-check"},
        },
        trigger_chars=450,
        max_blocks=3,
        max_selected=3,
        extra_assert=lambda scored, _selected, _report: len(
            split_blocks_into_batches(scored, items_per_batch=3)
        )
        >= 3,
    ),
    KnowledgeScoreSelectCase(
        id="09_max_blocks_limit",
        query="优惠券校验和使用逻辑",
        blocks=_pad_blocks([
            _block(
                "coupon-service",
                "CouponService：validateCoupon 校验券码有效性；applyCoupon 将优惠金额写入订单。",
            ),
            _block(
                "coupon-validator",
                "CouponValidator：检查券码过期时间与适用商品范围。",
            ),
            _block(
                "coupon-repo",
                "CouponRepository：按 code 查询优惠券实体。",
            ),
            _block("coupon-faq", "FAQ：优惠券不可叠加使用。"),
        ]),
        must_select={"coupon-service"},
        max_blocks=2,
        max_selected=2,
    ),
    KnowledgeScoreSelectCase(
        id="10_all_noise_blocks",
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
        must_select=set(),
        must_exclude=set(),
        min_selected=0,
    ),
]


async def _run_score_and_select(
    case: KnowledgeScoreSelectCase,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
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


def _assert_case(
    case: KnowledgeScoreSelectCase,
    scored: List[Dict],
    selected: List[Dict],
    report: Dict,
) -> None:
    scores = {
        s["id"]: float(s["relevance_score"])
        for s in scored
        if s.get("relevance_score") is not None
    }
    selected_ids = {s["id"] for s in selected}

    for s in scored:
        assert s.get("score_description"), f"{case.id}: missing description for {s['id']}"
        assert s.get("relevance_score") is not None
        assert 0 <= float(s["relevance_score"]) <= 10

    for block_id in case.must_select:
        assert block_id in selected_ids, (
            f"{case.id}: expected {block_id} in {selected_ids}, scores={scores}"
        )

    for block_id in case.must_exclude:
        assert block_id not in selected_ids, (
            f"{case.id}: {block_id} should be excluded, scores={scores}"
        )

    for top, losers in case.top_must_beat.items():
        assert top in scores, f"{case.id}: missing score for {top}"
        for loser in losers:
            if loser in scores:
                assert scores[top] >= scores[loser], (
                    f"{case.id}: {top}({scores[top]}) should beat {loser}({scores[loser]})"
                )

    assert report["selected_count"] >= case.min_selected
    if case.max_selected is not None:
        assert report["selected_count"] <= case.max_selected

    if case.extra_assert:
        case.extra_assert(scored, selected, report)

    print(f"\n[{case.id}] query={case.query!r}")
    print(f"  scores={scores}")
    print(f"  selected={selected_ids}")
    print(f"  report={report}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", E2E_CASES, ids=[c.id for c in E2E_CASES])
async def test_live_knowledge_score_select_case(case: KnowledgeScoreSelectCase):
    """Parametrized live LLM: score + select for 10 doc/knowledge scenarios."""
    _skip_without_api_key()
    scored, selected, report = await _run_score_and_select(case)
    _assert_case(case, scored, selected, report)


@pytest.mark.asyncio
async def test_live_get_text_by_ids_e2e_primary_case():
    """E2E via MetadataValuesResult.get_text_by_ids with real LLM (sales SQL case)."""
    _skip_without_api_key()
    case = next(c for c in E2E_CASES if c.id == "07_sales_aggregate_doc")

    os.environ["DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS"] = str(case.trigger_chars)
    os.environ["DOC_KNOWLEDGE_LLM_SCORE_ENABLED"] = "true"
    os.environ["DOC_KNOWLEDGE_MAX_BLOCKS"] = str(case.max_blocks)

    items = [
        {
            "id": b["id"],
            "text": b["text"],
            "metadata_value": b.get("metadata_value", ""),
        }
        for b in case.blocks
    ]
    knowledge_ids = [b["id"] for b in case.blocks]
    result = MetadataValuesResult(status="success", data={"docs": items})

    llm = _make_llm()
    text, meta = await result.get_text_by_ids(
        knowledge_ids,
        query=case.query,
        llm=llm,
        parse_output=_parse_llm_output,
    )

    assert meta["score_select_applied"] is True
    assert "GROUP BY product_id" in text
    assert "product-catalog" not in text or "商品目录" not in text.split("FAQ")[0]
    print(f"\n[E2E get_text_by_ids] len={len(text)} meta={meta}")


async def _main() -> int:
    if _api_key() is None:
        print("Set DASHSCOPE_API_KEY for live E2E")
        return 1

    passed = 0
    failed: List[str] = []
    for case in E2E_CASES:
        try:
            scored, selected, report = await _run_score_and_select(case)
            _assert_case(case, scored, selected, report)
            passed += 1
            print(f"PASS {case.id}")
        except AssertionError as exc:
            failed.append(f"{case.id}: {exc}")
            print(f"FAIL {case.id}: {exc}")

    try:
        await test_live_get_text_by_ids_e2e_primary_case()
        print("PASS get_text_by_ids_e2e")
    except (AssertionError, pytest.skip.Exception) as exc:  # type: ignore[attr-defined]
        if "skip" in str(type(exc)).lower():
            print(f"SKIP get_text_by_ids_e2e: {exc}")
        else:
            failed.append(f"get_text_by_ids_e2e: {exc}")
            print(f"FAIL get_text_by_ids_e2e: {exc}")

    print(f"\nResult: {passed}/{len(E2E_CASES)} score/select cases passed")
    if failed:
        print("Failures:")
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
