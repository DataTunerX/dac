"""Repository layer — ABC + implementations for goToImplementation testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from .models import Order, OrderStatus, Product


class Repository(ABC):
    """Abstract storage backend. pyright should resolve goToImplementation on this."""

    @abstractmethod
    def save_order(self, order: Order) -> None:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        ...

    @abstractmethod
    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        ...

    @abstractmethod
    def get_product(self, sku: str) -> Optional[Product]:
        ...

    @abstractmethod
    def list_orders_by_user(self, user_id: str) -> List[Order]:
        ...


class InMemoryRepository(Repository):
    """In-memory implementation — target for goToImplementation."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._products: dict[str, Product] = {}

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        order = self._orders.get(order_id)
        if order is not None:
            order.status = status

    def get_product(self, sku: str) -> Optional[Product]:
        return self._products.get(sku)

    def list_orders_by_user(self, user_id: str) -> List[Order]:
        return [o for o in self._orders.values() if o.user_id == user_id]


class PostgresRepository(Repository):
    """Postgres-backed implementation — another goToImplementation target."""

    def __init__(self, connection_string: str) -> None:
        self._conn = connection_string
        self._orders: dict[str, Order] = {}
        self._products: dict[str, Product] = {}

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        order = self._orders.get(order_id)
        if order is not None:
            order.status = status

    def get_product(self, sku: str) -> Optional[Product]:
        return self._products.get(sku)

    def list_orders_by_user(self, user_id: str) -> List[Order]:
        return [o for o in self._orders.values() if o.user_id == user_id]
