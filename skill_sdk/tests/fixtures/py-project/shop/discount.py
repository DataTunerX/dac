"""Discount strategies — Protocol-based pluggable strategies for findReferences + Protocol."""

from __future__ import annotations

from typing import Protocol

from .models import Order


class DiscountStrategy(Protocol):
    """Protocol for pluggable discount strategies.  Protocol dispatch in Python 3.12."""

    def apply(self, order: Order) -> float:
        """Return the discounted total for the given order."""
        ...


class PercentageDiscount:
    """Apply a percentage off the raw total."""

    def __init__(self, percent: float) -> None:
        self._percent = percent

    def apply(self, order: Order) -> float:
        return order.raw_total * (1.0 - self._percent / 100.0)


class FixedAmountDiscount:
    """Subtract a fixed amount from the raw total (floor at zero)."""

    def __init__(self, amount: float) -> None:
        self._amount = amount

    def apply(self, order: Order) -> float:
        return max(0.0, order.raw_total - self._amount)


class BogoDiscount:
    """Buy-one-get-one — cheapest item is free."""

    def apply(self, order: Order) -> float:
        if len(order.items) < 2:
            return order.raw_total
        cheapest = min(item.subtotal for item in order.items)
        return order.raw_total - cheapest


def apply_best_discount(order: Order, strategies: list[DiscountStrategy]) -> float:
    """Try several strategies and return the lowest price (reference target)."""
    candidates = [s.apply(order) for s in strategies]
    return min(candidates)
