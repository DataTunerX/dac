"""E-commerce domain models for LSP fixture testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class OrderStatus(Enum):
    """Possible states for an order."""
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


@dataclass
class Product:
    """A product available for purchase."""
    sku: str
    name: str
    price: float
    category: str
    stock: int = 0

    def is_in_stock(self) -> bool:
        """Check if product has available stock."""
        return self.stock > 0


@dataclass
class OrderItem:
    """A single line item within an order."""
    product: Product
    quantity: int
    unit_price: float

    @property
    def subtotal(self) -> float:
        """Compute line-item total."""
        return self.unit_price * self.quantity


@dataclass
class Order:
    """A customer order."""
    order_id: str
    user_id: str
    items: List[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    discount_code: Optional[str] = None

    @property
    def raw_total(self) -> float:
        """Sum of all item subtotals before discounts."""
        return sum(item.subtotal for item in self.items)

    def apply_discount(self, multiplier: float) -> float:
        """Return discounted total."""
        return self.raw_total * multiplier
