"""Shopping cart — call-hierarchy target for outgoingCalls / incomingCalls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .discount import DiscountStrategy
from .models import Order, OrderItem, OrderStatus, Product
from .payment import PaymentGateway, PaymentResult
from .repository import Repository


@dataclass
class Cart:
    """A transient shopping cart before conversion to an Order."""

    user_id: str
    items: List[OrderItem] = field(default_factory=list)

    def add_product(self, product: Product, quantity: int = 1) -> None:
        """Add a product to the cart (call site for findReferences on OrderItem)."""
        self.items.append(OrderItem(product=product, quantity=quantity, unit_price=product.price))

    def remove_item(self, index: int) -> None:
        """Remove an item by index."""
        if 0 <= index < len(self.items):
            del self.items[index]

    def cart_total(self) -> float:
        """Sum of item subtotals."""
        return sum(item.subtotal for item in self.items)

    def to_order(self, order_id: str, discount_code: Optional[str] = None) -> Order:
        """Convert cart to an Order entity."""
        return Order(order_id=order_id, user_id=self.user_id, items=list(self.items), discount_code=discount_code)

    def checkout(
        self,
        order_id: str,
        repo: Repository,
        gateway: PaymentGateway,
        discount: Optional[DiscountStrategy] = None,
    ) -> Order:
        """Full checkout pipeline — call-hierarchy centrepiece.

        This method calls:
          - ``to_order()``
          - ``discount.apply(order)``       (if discount is given)
          - ``gateway.charge(amount, ...)``
          - ``repo.save_order(order)``
          - ``repo.update_order_status(...)``

        outgoingCalls on ``checkout`` should list these as callees.
        incomingCalls on any of those should list ``checkout`` as a caller.
        """
        order = self.to_order(order_id)

        final_amount = order.raw_total
        if discount is not None:
            final_amount = discount.apply(order)

        result: PaymentResult = gateway.charge(final_amount, "USD")
        if result.success:
            order.status = OrderStatus.PAID

        repo.save_order(order)
        repo.update_order_status(order.order_id, order.status)
        return order
