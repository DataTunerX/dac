"""E2E integration: real LLM batch scoring + snippet selection.

Requires DASHSCOPE_API_KEY (or OPENAI_API_KEY). Skipped in CI when unset.

Run all 12 live cases:
  cd dac/code-agent
  DASHSCOPE_API_KEY=sk-... pytest tests/test_snippet_llm_score_e2e.py -v -s -m integration
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pytest
from model_sdk import ModelManager

from agent.code_agent import CodeAgent
from agent.tools.snippet_context_budget import (
    select_snippets_by_score,
    should_score_and_select,
    total_snippet_chars,
)
from agent.tools.snippet_llm_score import (
    score_snippets_batch_parallel,
    split_snippets_into_batches,
)

pytestmark = pytest.mark.integration

MODEL = os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def _api_key() -> Optional[str]:
    key = (os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
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
    agent = CodeAgent(
        api_key=_api_key(),
        base_url=BASE_URL,
        model=MODEL,
        data_services_url="http://127.0.0.1:1",
        query="",
    )
    return agent.format_llm_output(answer) or {}


def _block(
    name: str,
    code: str,
    *,
    file_path: str = "",
    line_no: str = "1-50",
    source: str = "skill_read_code",
) -> Dict[str, Any]:
    return {
        "file_path": file_path or f"src/{name}.java",
        "name": name,
        "line_no": line_no,
        "segment_type": "skill_read",
        "source": source,
        "relevance_reason": "read-code skill 定位",
        "code_content": code,
    }


@dataclass
class ScoreSelectCase:
    id: str
    query: str
    snippets: List[Dict[str, Any]]
    must_select: Set[str] = field(default_factory=set)
    must_exclude: Set[str] = field(default_factory=set)
    top_must_beat: Dict[str, Set[str]] = field(default_factory=dict)
    trigger_chars: int = 100
    max_snippets: int = 10
    min_selected: int = 1
    max_selected: Optional[int] = None
    extra_assert: Optional[Callable[[List[Dict], List[Dict], Dict], None]] = None


def _pad_snippets(snippets: List[Dict[str, Any]], min_chars: int = 200) -> List[Dict[str, Any]]:
    """Ensure total content exceeds default trigger for scoring."""
    out = [dict(s) for s in snippets]
    total = total_snippet_chars(out)
    if total >= min_chars:
        return out
    pad = min_chars - total + 1
    out[-1]["code_content"] = (out[-1].get("code_content") or "") + ("\n// pad\n" * pad)
    return out


# ---------------------------------------------------------------------------
# 10 curated E2E cases (+ 2 legacy tests below use sales_by_product set)
# ---------------------------------------------------------------------------

E2E_CASES: List[ScoreSelectCase] = [
    ScoreSelectCase(
        id="01_user_login",
        query="用户登录时如何验证用户名和密码",
        snippets=_pad_snippets([
            _block("imports", "import org.springframework.security.crypto.bcrypt.BCrypt;\n"),
            _block(
                "AuthService",
                "public class AuthService {\n"
                "  public boolean validateLogin(String username, String password) {\n"
                "    User u = userRepo.findByName(username);\n"
                "    return u != null && bcrypt.matches(password, u.getPasswordHash());\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "EmailService",
                "public class EmailService {\n"
                "  public void sendWelcomeEmail(String email) { ... }\n"
                "}\n",
            ),
            _block("main", "public static void main(String[] args) { SpringApplication.run(App.class); }\n"),
        ]),
        must_select={"AuthService"},
        must_exclude={"main", "EmailService"},
        top_must_beat={"AuthService": {"imports", "main", "EmailService"}},
    ),
    ScoreSelectCase(
        id="02_create_order",
        query="创建订单的完整流程在哪里实现",
        snippets=_pad_snippets([
            _block(
                "OrderController",
                "@RestController\npublic class OrderController {\n"
                "  @PostMapping(\"/orders\")\n"
                "  public Order createOrder(@RequestBody CreateOrderRequest req) {\n"
                "    return orderService.createOrder(req);\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "OrderService",
                "public class OrderService {\n"
                "  public Order createOrder(CreateOrderRequest req) {\n"
                "    validate(req); reserveInventory(req); return persist(req);\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "BannerRotator",
                "public class BannerRotator { public List<Banner> rotate() { ... } }\n",
            ),
            _block("imports", "import java.util.List;\nimport org.springframework.web.bind.annotation.*;\n"),
        ]),
        must_select={"OrderService", "OrderController"},
        must_exclude={"BannerRotator", "imports"},
        top_must_beat={"OrderService": {"BannerRotator", "imports"}},
    ),
    ScoreSelectCase(
        id="03_refund_flow",
        query="用户申请退款后系统如何处理",
        snippets=_pad_snippets([
            _block(
                "RefundService",
                "public class RefundService {\n"
                "  public RefundResult processRefund(String orderId, BigDecimal amount) {\n"
                "    verifyEligible(orderId); paymentGateway.refund(orderId, amount);\n"
                "    return RefundResult.success(orderId);\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "OrderQueryService",
                "public class OrderQueryService {\n"
                "  public List<Order> listOrdersByUser(int userId) { ... }\n"
                "}\n",
            ),
            _block("LoggerConfig", "@Configuration\npublic class LoggerConfig { ... }\n"),
        ]),
        must_select={"RefundService"},
        must_exclude={"LoggerConfig"},
        top_must_beat={"RefundService": {"OrderQueryService", "LoggerConfig"}},
    ),
    ScoreSelectCase(
        id="04_inventory_deduct",
        query="下单时如何扣减商品库存",
        snippets=_pad_snippets([
            _block(
                "InventoryService",
                "public class InventoryService {\n"
                "  public void deductStock(int productId, int qty) {\n"
                "    int current = repo.getStock(productId);\n"
                "    if (current < qty) throw new OutOfStockException();\n"
                "    repo.updateStock(productId, current - qty);\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "NotificationService",
                "public class NotificationService {\n"
                "  public void notifyShipped(int orderId) { ... }\n"
                "}\n",
            ),
            _block(
                "ProductService",
                "public class ProductService {\n"
                "  public Product getProduct(int id) { return repo.find(id); }\n"
                "}\n",
            ),
        ]),
        must_select={"InventoryService"},
        must_exclude={"NotificationService"},
        top_must_beat={"InventoryService": {"NotificationService"}},
    ),
    ScoreSelectCase(
        id="05_order_api_endpoint",
        query="创建订单的 REST API 接口定义在哪",
        snippets=_pad_snippets([
            _block(
                "OrderController",
                "@RestController\n@RequestMapping(\"/api/v1\")\n"
                "public class OrderController {\n"
                "  @PostMapping(\"/orders\")\n"
                "  public ResponseEntity<Order> create(@RequestBody CreateOrderRequest body) {\n"
                "    return ResponseEntity.ok(orderService.createOrder(body));\n"
                "  }\n"
                "}\n",
                line_no="10-40",
            ),
            _block(
                "OrderService",
                "public class OrderService {\n"
                "  public Order createOrder(CreateOrderRequest req) { ... internal ... }\n"
                "}\n",
            ),
            _block("JsonUtils", "public class JsonUtils { public static String toJson(Object o) { ... } }\n"),
        ]),
        must_select={"OrderController"},
        top_must_beat={"OrderController": {"JsonUtils"}},
    ),
    ScoreSelectCase(
        id="06_order_and_order_item_relation",
        query="订单和订单项之间是什么关系，如何关联查询",
        snippets=_pad_snippets([
            _block(
                "Order",
                "public class Order {\n"
                "  private int id;\n"
                "  private List<OrderItem> items;\n"
                "  public List<OrderItem> getItems() { return items; }\n"
                "}\n",
            ),
            _block(
                "OrderItem",
                "public class OrderItem {\n"
                "  private int orderId;\n"
                "  private int productId;\n"
                "  private double amount;\n"
                "}\n",
            ),
            _block(
                "OrderRepository",
                "public interface OrderRepository {\n"
                "  Order findWithItems(int orderId);\n"
                "}\n",
            ),
            _block("imports", "import java.util.List;\n"),
        ]),
        must_select={"Order", "OrderItem"},
        must_exclude={"imports"},
        min_selected=2,
    ),
    ScoreSelectCase(
        id="07_sales_by_product_aggregate",
        query="查询每个商品的销售总额",
        snippets=_pad_snippets([
            _block("imports", "import java.util.*;\nimport java.sql.*;\n"),
            _block(
                "OrderItemService",
                "public class OrderItemService {\n"
                "  public Map<Integer, Double> getSalesTotalByProduct() {\n"
                "    String sql = \"SELECT product_id, SUM(amount) FROM order_items GROUP BY product_id\";\n"
                "    return fetchProductSalesTotals(sql);\n"
                "  }\n"
                "}\n",
                line_no="327-365",
            ),
            _block(
                "ProductService",
                "public class ProductService {\n"
                "  public Product findById(int id) { ... }\n"
                "}\n",
            ),
            _block("main", "public static void main(String[] args) { SpringApplication.run(App.class); }\n"),
            _block(
                "OrderService",
                "public class OrderService {\n"
                "  public double getOrderTotalAmount(int orderId) { ... }\n"
                "}\n",
            ),
        ]),
        must_select={"OrderItemService"},
        must_exclude={"imports", "main"},
        top_must_beat={"OrderItemService": {"imports", "main", "ProductService"}},
    ),
    ScoreSelectCase(
        id="08_parallel_batch_8_blocks",
        query="支付回调通知如何处理",
        snippets=_pad_snippets([
            _block("imports", "import java.util.Map;\n"),
            _block(
                "PaymentCallbackController",
                "public class PaymentCallbackController {\n"
                "  @PostMapping(\"/pay/callback\")\n"
                "  public void handleCallback(PaymentNotify notify) {\n"
                "    paymentService.onPaymentSuccess(notify);\n"
                "  }\n"
                "}\n",
            ),
            _block(
                "PaymentService",
                "public class PaymentService {\n"
                "  public void onPaymentSuccess(PaymentNotify notify) {\n"
                "    orderService.markPaid(notify.getOrderId());\n"
                "  }\n"
                "}\n",
            ),
            _block("AuditLog", "public class AuditLog { public void info(String msg) { ... } }\n"),
            _block("MetricsConfig", "@Configuration public class MetricsConfig { ... }\n"),
            _block("HealthCheck", "public class HealthCheck { public boolean ok() { return true; } }\n"),
            _block("CacheWarmer", "public class CacheWarmer { public void warm() { ... } }\n"),
            _block("main", "public static void main(String[] args) { ... }\n"),
        ]),
        must_select={"PaymentCallbackController", "PaymentService"},
        must_exclude={"main", "MetricsConfig"},
        extra_assert=lambda scored, _selected, _report: len(
            split_snippets_into_batches(scored, items_per_batch=3)
        )
        >= 3,
    ),
    ScoreSelectCase(
        id="09_max_snippets_limit",
        query="优惠券校验和使用逻辑",
        snippets=_pad_snippets([
            _block(
                "CouponService",
                "public class CouponService {\n"
                "  public boolean validateCoupon(String code, Order order) {\n"
                "    Coupon c = repo.find(code); return c != null && c.isValid(order);\n"
                "  }\n"
                "  public void applyCoupon(String code, Order order) { ... }\n"
                "}\n",
            ),
            _block(
                "CouponValidator",
                "public class CouponValidator {\n"
                "  public ValidationResult checkExpiry(Coupon c) { ... }\n"
                "}\n",
            ),
            _block(
                "CouponRepository",
                "public interface CouponRepository { Coupon find(String code); }\n",
            ),
            _block("imports", "import java.time.LocalDate;\n"),
        ]),
        must_select={"CouponService"},
        max_snippets=2,
        max_selected=2,
    ),
    ScoreSelectCase(
        id="10_all_noise_blocks",
        query="每个商品的销售总额统计 SQL 在哪",
        snippets=_pad_snippets([
            _block("imports", "import java.util.*;\nimport org.slf4j.Logger;\n"),
            _block(
                "ApplicationConfig",
                "@Configuration\npublic class ApplicationConfig {\n"
                "  @Bean DataSource dataSource() { return new HikariDataSource(); }\n"
                "}\n",
            ),
            _block(
                "LogFormatter",
                "public class LogFormatter { public String fmt(String s) { return s; } }\n",
            ),
        ]),
        must_select=set(),
        must_exclude=set(),
        min_selected=0,
    ),
]


@dataclass
class AccuracyCase:
    """Stricter ground-truth checks for LLM scoring accuracy."""

    id: str
    query: str
    snippets: List[Dict[str, Any]]
    primary: str
    primary_min_score: float = 7.0
    noise_blocks: Set[str] = field(default_factory=set)
    noise_max_score: float = 4.0
    min_gap_vs_noise: float = 4.0
    misleading: Optional[str] = None
    misleading_max_score: Optional[float] = None
    min_gap_vs_misleading: float = 2.0
    trigger_chars: int = 100


# 2 accuracy-focused E2E cases with explicit ground truth
ACCURACY_CASES: List[AccuracyCase] = [
    AccuracyCase(
        id="accuracy_A_direct_product_sales_sql",
        query="按商品维度统计每个商品的销售总额，GROUP BY 聚合 SQL 在哪",
        snippets=_pad_snippets([
            _block("imports", "import logging\nimport mysql.connector\n"),
            _block(
                "SalesAggregator",
                "class SalesAggregator:\n"
                "    def get_sales_total_by_product(self):\n"
                '        sql = """\n'
                "            SELECT oi.product_id, p.product_name,\n"
                "                   SUM(oi.quantity * oi.unit_price) AS sales_total\n"
                "            FROM order_items oi\n"
                "            JOIN products p ON oi.product_id = p.product_id\n"
                "            GROUP BY oi.product_id, p.product_name\n"
                '        """\n'
                "        return self.db.fetch_all(sql)\n",
                line_no="120-145",
            ),
            _block(
                "UserAvatarService",
                "class UserAvatarService:\n"
                "    def upload_avatar(self, user_id: int, image_bytes: bytes):\n"
                "        return self.storage.save(user_id, image_bytes)\n",
                line_no="300-310",
            ),
            _block(
                "main",
                "def main():\n    app = create_app()\n    app.run()\n",
                line_no="500-505",
            ),
        ]),
        primary="SalesAggregator",
        primary_min_score=8.0,
        noise_blocks={"imports", "UserAvatarService", "main"},
        noise_max_score=3.0,
        min_gap_vs_noise=5.0,
    ),
    AccuracyCase(
        id="accuracy_B_login_not_password_reset",
        query="用户登录时如何验证用户名和密码",
        snippets=_pad_snippets([
            _block("imports", "import bcrypt\nfrom flask import session\n"),
            _block(
                "LoginService",
                "class LoginService:\n"
                "    def authenticate(self, username: str, password: str) -> bool:\n"
                "        user = self.user_repo.find_by_username(username)\n"
                "        if user is None:\n"
                "            return False\n"
                "        return bcrypt.checkpw(password.encode(), user.password_hash)\n",
                line_no="40-55",
            ),
            _block(
                "PasswordResetService",
                "class PasswordResetService:\n"
                "    def send_reset_email(self, email: str) -> None:\n"
                "        token = self.token_store.issue(email)\n"
                "        self.mailer.send(email, f'reset link: {token}')\n",
                line_no="200-215",
            ),
            _block(
                "EmailTemplateRenderer",
                "class EmailTemplateRenderer:\n"
                "    def render_welcome(self, name: str) -> str:\n"
                "        return f'Hello {name}'\n",
                line_no="400-410",
            ),
        ]),
        primary="LoginService",
        primary_min_score=8.0,
        noise_blocks={"imports", "EmailTemplateRenderer"},
        noise_max_score=3.0,
        min_gap_vs_noise=5.0,
        misleading="PasswordResetService",
        misleading_max_score=6.0,
        min_gap_vs_misleading=2.0,
    ),
]


async def _run_accuracy_score(case: AccuracyCase) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    os.environ["CODE_SEARCH_SCORE_TRIGGER_CHARS"] = str(case.trigger_chars)
    os.environ["SNIPPET_LLM_SCORE_ENABLED"] = "true"
    os.environ["CODE_SEARCH_MAX_SNIPPETS"] = "10"

    snippets = [dict(s) for s in case.snippets]
    llm = _make_llm()
    scored = await score_snippets_batch_parallel(
        snippets,
        query=case.query,
        llm=llm,
        parse_output=_parse_llm_output,
    )
    selected, _report = select_snippets_by_score(scored)
    return scored, selected


def _assert_accuracy(case: AccuracyCase, scored: List[Dict], selected: List[Dict]) -> None:
    scores = {s["name"]: float(s["relevance_score"]) for s in scored}
    selected_names = {s["name"] for s in selected}

    assert case.primary in scores, f"{case.id}: missing primary {case.primary}"
    primary_score = scores[case.primary]
    assert primary_score >= case.primary_min_score, (
        f"{case.id}: {case.primary} score {primary_score} < min {case.primary_min_score}"
    )
    assert case.primary in selected_names, (
        f"{case.id}: primary {case.primary} not selected, scores={scores}"
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
        assert noise not in selected_names, (
            f"{case.id}: noise {noise} should not be selected"
        )

    if case.misleading:
        assert case.misleading in scores
        mis_score = scores[case.misleading]
        if case.misleading_max_score is not None:
            assert mis_score <= case.misleading_max_score, (
                f"{case.id}: misleading {case.misleading} score {mis_score} too high"
            )
        assert primary_score - mis_score >= case.min_gap_vs_misleading, (
            f"{case.id}: {case.primary}({primary_score}) should beat misleading "
            f"{case.misleading}({mis_score}) by >= {case.min_gap_vs_misleading}"
        )

    for s in scored:
        assert s.get("score_description"), f"{case.id}: missing description for {s['name']}"

    print(f"\n[ACCURACY {case.id}] query={case.query!r}")
    print(f"  scores={scores}")
    print(f"  selected={selected_names}")
    print(f"  primary={case.primary} score={primary_score}")


async def _run_score_and_select(
    case: ScoreSelectCase,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    os.environ["CODE_SEARCH_SCORE_TRIGGER_CHARS"] = str(case.trigger_chars)
    os.environ["SNIPPET_LLM_SCORE_ENABLED"] = "true"
    os.environ["CODE_SEARCH_MAX_SNIPPETS"] = str(case.max_snippets)

    snippets = [dict(s) for s in case.snippets]
    assert should_score_and_select(snippets), f"{case.id}: total chars must exceed trigger"

    llm = _make_llm()
    scored = await score_snippets_batch_parallel(
        snippets,
        query=case.query,
        llm=llm,
        parse_output=_parse_llm_output,
    )
    selected, report = select_snippets_by_score(scored)
    return scored, selected, report


def _assert_case(case: ScoreSelectCase, scored: List[Dict], selected: List[Dict], report: Dict) -> None:
    scores = {s["name"]: float(s["relevance_score"]) for s in scored if s.get("relevance_score") is not None}
    selected_names = {s["name"] for s in selected}

    for s in scored:
        assert s.get("score_description"), f"{case.id}: missing description for {s['name']}"
        assert s.get("relevance_score") is not None
        assert 0 <= float(s["relevance_score"]) <= 10

    for name in case.must_select:
        assert name in selected_names, f"{case.id}: expected {name} in {selected_names}, scores={scores}"

    for name in case.must_exclude:
        assert name not in selected_names, f"{case.id}: {name} should be excluded, scores={scores}"

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
    print(f"  selected={selected_names}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ACCURACY_CASES, ids=[c.id for c in ACCURACY_CASES])
async def test_live_llm_score_accuracy(case: AccuracyCase):
    """Accuracy E2E: real LLM must rank primary block well above noise/misleading blocks."""
    _skip_without_api_key()
    scored, selected = await _run_accuracy_score(case)
    _assert_accuracy(case, scored, selected)


@pytest.mark.asyncio
async def test_live_hybrid_search_accuracy_case_a(monkeypatch):
    """Full hybrid_search path + real LLM: direct SQL aggregate block must win."""
    _skip_without_api_key()
    case = ACCURACY_CASES[0]
    key = _api_key()

    agent = CodeAgent(
        api_key=key,
        base_url=BASE_URL,
        model=MODEL,
        data_services_url="http://127.0.1:1",
        query=case.query,
    )

    async def _fake_semantic(filepaths=None):
        return {"code_snippets": []}

    async def _fake_grep(**kwargs):
        return {
            "code_snippets": [dict(s) for s in case.snippets],
            "keywords": [],
            "files_matched": [],
            "filtered_count": 0,
        }

    monkeypatch.setattr(agent, "search_and_extract_code_enhanced", _fake_semantic)
    monkeypatch.setattr(agent, "grep_recall_code_segments", _fake_grep)
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "100")
    monkeypatch.setenv("SNIPPET_LLM_SCORE_ENABLED", "true")

    result = await agent.hybrid_search()
    out = result["code_snippets"]
    scores = {s["name"]: float(s["relevance_score"]) for s in out}

    assert "SalesAggregator" in scores
    assert scores["SalesAggregator"] >= 8.0
    assert "UserAvatarService" not in {s["name"] for s in out}
    print(f"\n[ACCURACY HYBRID A] selected={[s['name'] for s in out]} scores={scores}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", E2E_CASES, ids=[c.id for c in E2E_CASES])
async def test_live_llm_score_select_case(case: ScoreSelectCase):
    """Parametrized live LLM: score + select for 10 business scenarios."""
    _skip_without_api_key()
    scored, selected, report = await _run_score_and_select(case)
    _assert_case(case, scored, selected, report)


@pytest.mark.asyncio
async def test_live_hybrid_search_score_and_select(monkeypatch):
    """E2E via CodeAgent.hybrid_search with mocked search, real LLM score+select."""
    _skip_without_api_key()

    case = next(c for c in E2E_CASES if c.id == "07_sales_by_product_aggregate")
    key = _api_key()

    agent = CodeAgent(
        api_key=key,
        base_url=BASE_URL,
        model=MODEL,
        data_services_url="http://127.0.0.1:1",
        query=case.query,
    )

    async def _fake_semantic(filepaths=None):
        return {"code_snippets": []}

    async def _fake_grep(**kwargs):
        return {
            "code_snippets": [dict(s) for s in case.snippets],
            "keywords": [],
            "files_matched": [],
            "filtered_count": 0,
        }

    monkeypatch.setattr(agent, "search_and_extract_code_enhanced", _fake_semantic)
    monkeypatch.setattr(agent, "grep_recall_code_segments", _fake_grep)
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "100")
    monkeypatch.setenv("SNIPPET_LLM_SCORE_ENABLED", "true")

    result = await agent.hybrid_search()
    out = result["code_snippets"]
    names = {s["name"] for s in out}

    assert "OrderItemService" in names
    assert "imports" not in names
    print("\n[E2E HYBRID] selected:", names)


async def _main() -> int:
    if _api_key() is None:
        print("Set DASHSCOPE_API_KEY for live E2E")
        return 1
    for case in ACCURACY_CASES:
        scored, selected = await _run_accuracy_score(case)
        _assert_accuracy(case, scored, selected)
        print(f"PASS accuracy {case.id}")
    passed = 0
    for case in E2E_CASES:
        scored, selected, report = await _run_score_and_select(case)
        _assert_case(case, scored, selected, report)
        passed += 1
        print(f"PASS {case.id}")
    print(f"\nAll accuracy + {passed} scenario cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
