"""Live LLM E2E for Stage 1.5 observe_locate_files (OBSERVE_LOCATE_FILES prompt).

Requires DASHSCOPE_API_KEY (or OPENAI_API_KEY). Skipped in CI when unset.

Run:
  cd dac/code-agent
  DASHSCOPE_API_KEY=sk-... pytest tests/test_observe_locate_files_e2e.py -v -s -m integration

Or direct:
  DASHSCOPE_API_KEY=sk-... python tests/test_observe_locate_files_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set

import pytest
from model_sdk import ModelManager

from agent.code_agent import CodeAgent, FileLocationResult, KnowledgeFiles

pytestmark = pytest.mark.integration

MODEL = os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

KID_ECOMMERCE = "2c85f591-470a-47b8-84a7-367637183f42"

DIANSHANG_KNOWLEDGE = """
[Knowledge ID: 2c85f591-470a-47b8-84a7-367637183f42]
模块名称: 电商核心业务模块
模块业务描述: 实现电商系统的核心业务闭环，涵盖用户管理、商品分类与展示、订单生成及历史查询等完整事务流程。

=== 文件: code.py ===
文件摘要: 本文件负责电商系统的核心数据访问与业务流程处理，包括用户、分类、商品、订单及订单项的CRUD操作，以及下单和查询订单历史的完整事务流程。

关键功能:
- DatabaseManager: 数据库连接与 fetch_all / fetch_one / execute_query
- ProductService: 商品 CRUD，get_all_products
- OrderService: 订单 CRUD，get_all_orders，create_order
- OrderItemService: add_order_item，get_order_items（含 product_id, quantity, unit_price），get_order_total_amount（单订单 SUM(subtotal)）
- ECommerceService: place_order 下单编排，get_user_order_history
- main: 示例入口
"""

LOGGER_KNOWLEDGE = """
=== 文件: config/logging.yaml ===
文件摘要: 应用日志级别与 handler 配置，与业务逻辑无关。

=== 文件: utils/logger_setup.py ===
文件摘要: logging.basicConfig 封装，通用基础设施，无订单/商品领域逻辑。
"""

ORDER_PRODUCT_KNOWLEDGE = """
=== 文件: services/order_service.py ===
文件摘要: 订单创建、状态更新（update_order_status）、按用户查询订单列表、get_all_orders。

=== 文件: services/product_service.py ===
文件摘要: 商品 CRUD、search_products 关键字搜索、按分类查询、update_stock 库存更新。

=== 文件: services/order_item_service.py ===
文件摘要: 订单项增删改查，字段含 product_id、quantity、unit_price、subtotal；get_order_total_amount 按 order_id SUM(subtotal)。
"""

DIANSHANG_EXTENDED_KNOWLEDGE = """
[Knowledge ID: 2c85f591-470a-47b8-84a7-367637183f42]
模块名称: 电商核心业务模块

=== 文件: code.py ===
文件摘要: 电商核心 monolith：DatabaseManager、UserService、CategoryService、ProductService、OrderService、OrderItemService、ECommerceService。

关键功能:
- UserService: create_user, get_all_users, get_user_by_id
- CategoryService: create_category, get_all_categories
- ProductService: create_product, search_products(keyword), update_stock, get_products_by_category
- OrderService: create_order, update_order_status, get_orders_by_user, get_all_orders
- OrderItemService: add_order_item, get_order_items, get_order_total_amount（SELECT SUM(subtotal) WHERE order_id=?）
- ECommerceService: place_order 事务编排, get_user_order_history
- DatabaseManager: connect/disconnect MySQL, fetch_all, fetch_one, execute_query
"""

FRONTEND_KNOWLEDGE = """
=== 文件: frontend/src/App.tsx ===
文件摘要: React 根组件与路由，纯前端 UI，不含订单/商品后端逻辑或 SQL。

=== 文件: frontend/src/pages/ProductList.tsx ===
文件摘要: 商品列表页面组件，调用后端 API 展示，无数据库访问代码。
"""

INFRA_ONLY_KNOWLEDGE = """
=== 文件: deploy/helm/values.yaml ===
文件摘要: Helm chart 默认 values，replicaCount、image.repository 等部署参数。

=== 文件: docker/Dockerfile ===
文件摘要: 多阶段构建镜像，与业务 CRUD 无关。
"""


def _api_key() -> Optional[str]:
    key = (os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key or key == "sk-xxx":
        return None
    return key


def _skip_without_api_key() -> None:
    if _api_key() is None:
        pytest.skip("Set DASHSCOPE_API_KEY or OPENAI_API_KEY for live LLM E2E test")


def _make_agent(query: str) -> CodeAgent:
    key = _api_key()
    assert key
    manager = ModelManager()
    llm = manager.get_llm(
        provider="openai_compatible",
        api_key=key,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )
    agent = CodeAgent(
        api_key=key,
        base_url=BASE_URL,
        model=MODEL,
        data_services_url="http://127.0.0.1:1",
        query=query,
        metadata={
            "user_id": "e2e-user",
            "run_id": "e2e-run",
            "trace_id": uuid.uuid4().hex,
        },
    )
    agent.llm = llm
    return agent


def _locate(
    files: List[str],
    *,
    knowledge_id: str = KID_ECOMMERCE,
    intent: str = "定位相关业务文件",
    reasoning: str = "Stage-1 mock",
) -> FileLocationResult:
    return FileLocationResult(
        knowledge_files=[KnowledgeFiles(knowledge_id=knowledge_id, files=list(files))],
        intent_analysis=intent,
        reasoning_path=reasoning,
    )


@dataclass
class ObserveLocateCase:
    id: str
    query: str
    locate: FileLocationResult
    knowledge: str
    must_keep: Set[str] = field(default_factory=set)
    must_discard: Set[str] = field(default_factory=set)
    min_kept: int = 1
    max_kept: Optional[int] = None
    min_keep_score: Optional[dict] = None  # file -> min logic_score for KEEP
    max_discard_score: Optional[dict] = None  # file -> max logic_score when DISCARD
    stability_runs: int = 0  # if >0, included in multi-run stability suite
    extra_assert: Optional[Callable] = None
    note: str = ""


OBSERVE_CASES: List[ObserveLocateCase] = [
    ObserveLocateCase(
        id="01_regression_sales_aggregate_no_api",
        query="查询每个商品的销售总额，按商品维度统计",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 6},
        note="回归：无 GROUP BY 现成接口，但含 order_items 字段，必须 KEEP",
    ),
    ObserveLocateCase(
        id="02_sales_total_simple_query",
        query="查询每个商品的销售总额",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 6},
    ),
    ObserveLocateCase(
        id="03_how_to_implement_aggregate",
        query="如何实现按商品ID分组统计销售总额",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
        note="实现类问题：缺现成方法仍应保留数据载体",
    ),
    ObserveLocateCase(
        id="04_place_order_process",
        query="用户下单的完整流程是怎么实现的",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
    ),
    ObserveLocateCase(
        id="05_multi_file_prune_logger",
        query="查询每个商品的销售总额，按商品维度统计",
        locate=FileLocationResult(
            knowledge_files=[
                KnowledgeFiles(knowledge_id=KID_ECOMMERCE, files=["code.py"]),
                KnowledgeFiles(knowledge_id="log-cfg-001", files=["config/logging.yaml", "utils/logger_setup.py"]),
            ],
            intent_analysis="电商销售统计 + 误召回日志配置",
            reasoning_path="Stage-1 多文件",
        ),
        knowledge=DIANSHANG_KNOWLEDGE + "\n" + LOGGER_KNOWLEDGE,
        must_keep={"code.py"},
        must_discard={"config/logging.yaml", "utils/logger_setup.py"},
        min_keep_score={"code.py": 6},
        note="多文件降噪：剔除明显无关日志配置",
    ),
    ObserveLocateCase(
        id="06_order_history_multi_service",
        query="如何查询用户的订单历史及订单明细",
        locate=FileLocationResult(
            knowledge_files=[
                KnowledgeFiles(
                    knowledge_id="svc-order",
                    files=["services/order_service.py", "services/order_item_service.py"],
                ),
                KnowledgeFiles(knowledge_id="svc-product", files=["services/product_service.py"]),
            ],
            intent_analysis="订单历史与明细",
            reasoning_path="OrderService + OrderItemService 链路",
        ),
        knowledge=ORDER_PRODUCT_KNOWLEDGE,
        must_keep={"services/order_service.py", "services/order_item_service.py"},
        must_discard={"services/product_service.py"},
        min_keep_score={
            "services/order_service.py": 6,
            "services/order_item_service.py": 6,
        },
    ),
    ObserveLocateCase(
        id="07_product_crud_partial_relevance",
        query="如何更新商品库存",
        locate=FileLocationResult(
            knowledge_files=[
                KnowledgeFiles(knowledge_id="svc-product", files=["services/product_service.py"]),
                KnowledgeFiles(knowledge_id="svc-order", files=["services/order_service.py"]),
            ],
            intent_analysis="商品库存更新",
            reasoning_path="ProductService 为主",
        ),
        knowledge=ORDER_PRODUCT_KNOWLEDGE,
        must_keep={"services/product_service.py"},
        must_discard={"services/order_service.py"},
        min_keep_score={"services/product_service.py": 7},
    ),
    ObserveLocateCase(
        id="08_wrong_domain_k8s_query",
        query="如何配置 Kubernetes Deployment 的 readinessProbe",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_discard={"code.py"},
        min_kept=0,
        max_kept=0,
        note="业务域完全无关，应 DISCARD",
    ),
    ObserveLocateCase(
        id="09_auth_query_on_ecommerce_only",
        query="JWT refresh token 的校验逻辑在哪里",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_discard={"code.py"},
        min_kept=0,
        max_kept=0,
        note="电商模块摘要不包含认证逻辑",
    ),
    ObserveLocateCase(
        id="10_order_item_fields_for_revenue",
        query="订单项里有哪些字段可以用来计算商品销售额",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 8},
        note="字段/模型探索类，OrderItemService 强相关",
    ),
]

# Batch 2: 10 additional scenarios (ids 11–20), each tagged for 5-run stability.
OBSERVE_CASES_BATCH2: List[ObserveLocateCase] = [
    ObserveLocateCase(
        id="11_update_order_status",
        query="如何把订单状态更新为已发货",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
        stability_runs=5,
        note="OrderService.update_order_status 相关",
    ),
    ObserveLocateCase(
        id="12_search_products_keyword",
        query="按关键字搜索商品的逻辑在哪里",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="13_list_all_categories",
        query="如何获取系统中所有商品分类",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="14_get_all_users",
        query="查询所有注册用户的代码在哪",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 7},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="15_single_order_total_amount",
        query="计算某一个订单总金额的 SQL 或方法在哪",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 8},
        stability_runs=5,
        note="get_order_total_amount / SUM(subtotal)",
    ),
    ObserveLocateCase(
        id="16_multi_prune_react_frontend",
        query="查询每个商品的销售总额，按商品维度统计",
        locate=FileLocationResult(
            knowledge_files=[
                KnowledgeFiles(knowledge_id=KID_ECOMMERCE, files=["code.py"]),
                KnowledgeFiles(
                    knowledge_id="fe-001",
                    files=["frontend/src/App.tsx", "frontend/src/pages/ProductList.tsx"],
                ),
            ],
            intent_analysis="后端销售统计 + 误召回前端",
            reasoning_path="Stage-1 混合",
        ),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE + "\n" + FRONTEND_KNOWLEDGE,
        must_keep={"code.py"},
        must_discard={"frontend/src/App.tsx", "frontend/src/pages/ProductList.tsx"},
        min_keep_score={"code.py": 6},
        max_discard_score={"frontend/src/App.tsx": 2, "frontend/src/pages/ProductList.tsx": 2},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="17_create_order_with_items",
        query="创建订单并写入多个订单项的实现在哪",
        locate=FileLocationResult(
            knowledge_files=[
                KnowledgeFiles(
                    knowledge_id="svc-order",
                    files=["services/order_service.py", "services/order_item_service.py"],
                ),
                KnowledgeFiles(knowledge_id="svc-product", files=["services/product_service.py"]),
            ],
            intent_analysis="下单 + 订单项写入",
            reasoning_path="OrderService + OrderItemService",
        ),
        knowledge=ORDER_PRODUCT_KNOWLEDGE,
        must_keep={"services/order_service.py", "services/order_item_service.py"},
        must_discard={"services/product_service.py"},
        min_keep_score={
            "services/order_service.py": 7,
            "services/order_item_service.py": 7,
        },
        max_discard_score={"services/product_service.py": 4},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="18_stripe_webhook_unrelated",
        query="Stripe 支付 webhook 签名校验怎么做",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_discard={"code.py"},
        min_kept=0,
        max_kept=0,
        max_discard_score={"code.py": 2},
        stability_runs=5,
        note="摘要不含支付模块",
    ),
    ObserveLocateCase(
        id="19_elasticsearch_unrelated",
        query="Elasticsearch 商品索引 mapping 怎么配置",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_discard={"code.py"},
        min_kept=0,
        max_kept=0,
        max_discard_score={"code.py": 2},
        stability_runs=5,
    ),
    ObserveLocateCase(
        id="20_database_manager_connect",
        query="DatabaseManager 是如何连接 MySQL 的",
        locate=_locate(["code.py"]),
        knowledge=DIANSHANG_EXTENDED_KNOWLEDGE,
        must_keep={"code.py"},
        min_keep_score={"code.py": 8},
        stability_runs=5,
        note="基础设施代码仍在业务 monolith 内，应 KEEP",
    ),
]

ALL_OBSERVE_CASES = OBSERVE_CASES + OBSERVE_CASES_BATCH2
BATCH2_STABILITY_RUNS = 5


async def _run_observe(case: ObserveLocateCase):
    agent = _make_agent(case.query)
    result = await agent.observe_locate_files(
        locate_files=case.locate,
        knowledge=case.knowledge,
    )
    kept = set(result.get_kept_files())
    discarded = set(result.get_discarded_files())
    scores = {ar.file_path: ar.logic_score for ar in result.audit_results}
    actions = {ar.file_path: ar.action for ar in result.audit_results}
    return result, kept, discarded, scores, actions


def _assert_case(case: ObserveLocateCase, kept, discarded, scores, actions) -> None:
    missing_keep = case.must_keep - kept
    assert not missing_keep, (
        f"[{case.id}] expected KEEP {case.must_keep}, got kept={kept}, "
        f"discarded={discarded}, actions={actions}, scores={scores}, note={case.note}"
    )

    wrong_keep = case.must_discard & kept
    assert not wrong_keep, (
        f"[{case.id}] must DISCARD {case.must_discard} but kept {wrong_keep}, "
        f"actions={actions}, scores={scores}"
    )

    if case.min_kept is not None:
        assert len(kept) >= case.min_kept, (
            f"[{case.id}] min_kept={case.min_kept}, got {len(kept)}: {kept}"
        )
    if case.max_kept is not None:
        assert len(kept) <= case.max_kept, (
            f"[{case.id}] max_kept={case.max_kept}, got {len(kept)}: {kept}"
        )

    if case.min_keep_score:
        for fp, min_score in case.min_keep_score.items():
            if fp in kept:
                assert scores.get(fp, 0) >= min_score, (
                    f"[{case.id}] {fp} logic_score {scores.get(fp)} < {min_score}"
                )

    if case.max_discard_score:
        for fp, max_score in case.max_discard_score.items():
            if fp in discarded and fp in scores:
                assert scores[fp] <= max_score, (
                    f"[{case.id}] {fp} DISCARD but logic_score {scores[fp]} > {max_score}"
                )

    if case.extra_assert:
        case.extra_assert(kept, discarded, scores, actions)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", OBSERVE_CASES, ids=[c.id for c in OBSERVE_CASES])
async def test_live_observe_locate_files(case: ObserveLocateCase):
    _skip_without_api_key()
    result, kept, discarded, scores, actions = await _run_observe(case)
    _assert_case(case, kept, discarded, scores, actions)
    print(
        f"\n[{case.id}] query={case.query!r}\n"
        f"  kept={sorted(kept)} discarded={sorted(discarded)}\n"
        f"  scores={scores}\n"
        f"  summary={result.final_context_summary[:120]}..."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", OBSERVE_CASES_BATCH2, ids=[c.id for c in OBSERVE_CASES_BATCH2])
async def test_live_observe_locate_files_batch2(case: ObserveLocateCase):
    _skip_without_api_key()
    result, kept, discarded, scores, actions = await _run_observe(case)
    _assert_case(case, kept, discarded, scores, actions)
    print(
        f"\n[{case.id}] query={case.query!r}\n"
        f"  kept={sorted(kept)} discarded={sorted(discarded)}\n"
        f"  scores={scores}\n"
        f"  summary={result.final_context_summary[:120]}..."
    )


@pytest.mark.asyncio
async def test_live_regression_stability_three_runs():
    """Run the original bug scenario 3 times — all must KEEP code.py."""
    _skip_without_api_key()
    case = next(c for c in OBSERVE_CASES if c.id == "01_regression_sales_aggregate_no_api")
    for run in range(1, 4):
        _, kept, _, scores, _ = await _run_observe(case)
        assert "code.py" in kept, f"run {run}: expected KEEP code.py, got kept={kept}, scores={scores}"
        print(f"\n[stability run {run}] KEEP code.py score={scores.get('code.py')}")


@pytest.mark.asyncio
async def test_live_batch2_stability_five_runs_each():
    """Each batch-2 case runs 5 times; all runs must pass assertions."""
    _skip_without_api_key()
    failures: List[str] = []
    for case in OBSERVE_CASES_BATCH2:
        runs = case.stability_runs or BATCH2_STABILITY_RUNS
        for run in range(1, runs + 1):
            try:
                _, kept, discarded, scores, actions = await _run_observe(case)
                _assert_case(case, kept, discarded, scores, actions)
                print(
                    f"\n[{case.id} run {run}/{runs}] "
                    f"kept={sorted(kept)} discard={sorted(discarded)} scores={scores}"
                )
            except AssertionError as exc:
                failures.append(f"{case.id} run {run}: {exc}")
    assert not failures, "Stability failures:\n" + "\n".join(failures)


async def _main() -> int:
    if _api_key() is None:
        print("Set DASHSCOPE_API_KEY for live E2E")
        return 1
    passed = 0
    for case in ALL_OBSERVE_CASES:
        _, kept, discarded, scores, actions = await _run_observe(case)
        _assert_case(case, kept, discarded, scores, actions)
        passed += 1
        print(
            f"PASS {case.id}: kept={sorted(kept)} discard={sorted(discarded)} scores={scores}"
        )
    failures: List[str] = []
    for case in OBSERVE_CASES_BATCH2:
        for run in range(1, BATCH2_STABILITY_RUNS + 1):
            try:
                _, kept, discarded, scores, actions = await _run_observe(case)
                _assert_case(case, kept, discarded, scores, actions)
            except AssertionError as exc:
                failures.append(f"{case.id} run {run}: {exc}")
    if failures:
        print("STABILITY FAILURES:")
        for f in failures:
            print(f)
        return 1
    print(f"\nAll {passed} scenario cases + batch2 {BATCH2_STABILITY_RUNS}x stability passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
