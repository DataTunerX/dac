"""E-commerce fixture subpackage for Python LSP skill testing.

Exposes the full e-commerce domain for cross-module navigation:
  - ``models``         – domain entities (Product, Order, OrderItem, OrderStatus)
  - ``repository``     – ABC + implementations (goToImplementation target)
  - ``payment``        – ABC + implementations (goToImplementation target)
  - ``discount``       – Protocol-based strategies + helper
  - ``cart``           – Cart with checkout call chain (call hierarchy target)
  - ``services``       – OrderService orchestration
"""

from .cart import Cart
from .discount import DiscountStrategy, apply_best_discount
from .models import Order, OrderItem, OrderStatus, Product
from .payment import PaymentGateway, PaymentResult, PayPalGateway, StripeGateway
from .repository import InMemoryRepository, PostgresRepository, Repository

__all__ = [
    "apply_best_discount",
    "Cart",
    "DiscountStrategy",
    "InMemoryRepository",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PayPalGateway",
    "PaymentGateway",
    "PaymentResult",
    "PostgresRepository",
    "Product",
    "Repository",
    "StripeGateway",
]
