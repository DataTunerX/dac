"""End-to-end wiring for fixture-py-project (cross-module graph for Pyright / LSP).

Pulls ``core``, ``bridge``, ``protocols``, ``utils``, ``workers``, and the e-commerce
``shop`` subpackage into one import surface so indexes see cross-file definitions and
references across the full fixture tree.
"""

from __future__ import annotations

from bridge import bridge_batch, bridge_finalize
from core import (
    AdvancedProcessor,
    DataProcessor,
    RequestHandler,
    ServiceConfig,
    build_pipeline,
    finalize_result,
)
from shop import (
    Cart,
    InMemoryRepository,
    Order,
    OrderItem,
    OrderStatus,
    PayPalGateway,
    PaymentGateway,
    Product,
    Repository,
    StripeGateway,
)
from shop.discount import DiscountStrategy, PercentageDiscount, apply_best_discount
from shop.payment import PaymentResult
from shop.services import OrderService, seed_catalog
from utils import batch_process, format_output, sanitize_input
from workers import finalize_chunked


def demo_fixture_run() -> str:
    """One path touching every subsystem (symbol + reference scaffolding)."""
    # --- boilerplate core/pipeline path (keeps backward compat) ---
    cfg = ServiceConfig(timeout=60, retries=1, endpoint="http://fixture.local")
    processor = AdvancedProcessor(cfg)
    raw = sanitize_input("  Hello LSP Fixture  ")
    stage1 = format_output(processor.process(raw), prefix="stage")
    chained = finalize_result(stage1)

    finalized_rows = finalize_chunked([chained])
    routed = bridge_finalize(finalized_rows[0])
    pooled = bridge_batch([routed, routed])
    capped = batch_process(list(pooled), batch_size=1)[0]

    handler = make_handler(processor)
    build_pipeline(cfg, handlers=[handler])
    handled = handler.handle(capped)

    # --- e-commerce shopping demo ---
    repo: Repository = InMemoryRepository()
    gateway: PaymentGateway = StripeGateway(api_key="sk_test_fixture")

    laptop = Product(sku="LAP-001", name="Laptop Pro", price=1299.99, category="electronics", stock=10)
    mouse = Product(sku="MOU-001", name="Wireless Mouse", price=29.99, category="electronics", stock=50)

    cart = Cart(user_id="user_fixture_001")
    cart.add_product(laptop, quantity=1)
    cart.add_product(mouse, quantity=2)

    discount: DiscountStrategy = PercentageDiscount(percent=10)
    svc = OrderService(repo=repo, gateway=gateway, strategies=[discount])
    order = svc.place_order(cart, order_id="ORD-0001")

    nf = NotificationService()
    nf.send_order_confirmation(order)

    return f"[done] order={order.order_id} total={order.raw_total} status={order.status.value} legacy={handled}"


# ---------------------------------------------------------------------------
# Helper — kept alongside the e-commerce modules as a distinct call target
# ---------------------------------------------------------------------------


def make_handler(processor: DataProcessor) -> RequestHandler:
    """Return a handler bound to ``processor`` (definition / hover sites)."""
    return RequestHandler(processor)


class NotificationService:
    """Sends order notifications — target for incomingCalls from checkout flow."""

    def send_order_confirmation(self, order: Order) -> str:
        """Send confirmation for a newly-placed order."""
        msg = f"Order {order.order_id} confirmed for user {order.user_id}"
        return self._dispatch(msg)

    def send_shipping_update(self, order: Order) -> str:
        """Send shipping notification."""
        msg = f"Order {order.order_id} shipped"
        return self._dispatch(msg)

    def _dispatch(self, message: str) -> str:
        """Internal dispatch helper — goToDefinition target."""
        return f"[NOTIFY] {message}"
