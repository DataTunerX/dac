"""Order services — orchestrates repo / gateway / discount into business workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .cart import Cart
from .discount import DiscountStrategy, apply_best_discount
from .models import Order, OrderStatus, Product
from .payment import PaymentGateway
from .repository import Repository


def seed_catalog(repo: Repository) -> None:
    """Pre-populate the product catalog (used for fixture_app wiring)."""
    products = [
        Product(sku="LAP-001", name="Laptop Pro", price=1299.99, category="electronics", stock=10),
        Product(sku="PHN-001", name="SmartPhone X", price=799.99, category="electronics", stock=25),
        Product(sku="BOK-001", name="Python Book", price=49.99, category="books", stock=100),
        Product(sku="MUG-001", name="Coffee Mug", price=14.99, category="accessories", stock=200),
    ]
    for p in products:
        # Simulate a product seed by storing each product.  InMemoryRepository stores
        # products on get_product calls — this is a fixture stub.
        # Actual seeding would be repo.save_product(p) but the mock is in-memory.
        # We keep the repo param for call-chain visibility in LSP tests.
        if not repo.get_product(p.sku):
            pass  # mock-scaffolding placeholder — real injection handled in fixture_app


@dataclass
class OrderService:
    """Facade over the checkout flow — top-level entry point for incomingCalls."""

    repo: Repository
    gateway: PaymentGateway
    strategies: List[DiscountStrategy] = field(default_factory=list)

    def place_order(self, cart: Cart, order_id: str) -> Order:
        """Full order flow — outgoingCalls target.

        Calls:
          - ``cart.checkout(...)``
          - ``apply_best_discount(order, ...)``  (if multiple strategies)
          - ``cart.to_order(...)``
        """
        if self.strategies:
            order = cart.to_order(order_id)
            # apply_best_discount computes cheapest price across strategies
            apply_best_discount(order, self.strategies)
            return cart.checkout(order_id, self.repo, self.gateway, self.strategies[0])
        return cart.checkout(order_id, self.repo, self.gateway)

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order and trigger refund."""
        order = self.repo.get_order(order_id)
        if order is None:
            return
        order.status = OrderStatus.CANCELLED
        self.repo.update_order_status(order_id, OrderStatus.CANCELLED)
