"""Payment gateway abstraction — ABC + strategies for implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class PaymentResult:
    """Outcome of a payment attempt."""
    success: bool
    transaction_id: str
    message: str


class PaymentGateway(ABC):
    """Abstract payment processor. goToImplementation resolves concrete classes."""

    @abstractmethod
    def charge(self, amount: float, currency: str) -> PaymentResult:
        ...

    @abstractmethod
    def refund(self, transaction_id: str) -> PaymentResult:
        ...


class StripeGateway(PaymentGateway):
    """Stripe-backed payment gateway implementation."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def charge(self, amount: float, currency: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"stripe_ch_{hash(str(amount))}",
            message=f"Charged {amount} {currency}",
        )

    def refund(self, transaction_id: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"stripe_ref_{transaction_id}",
            message=f"Refunded transaction {transaction_id}",
        )


class PayPalGateway(PaymentGateway):
    """PayPal-backed payment gateway implementation."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def charge(self, amount: float, currency: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"pp_ch_{hash(str(amount))}",
            message=f"PayPal charge {amount} {currency}",
        )

    def refund(self, transaction_id: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"pp_ref_{transaction_id}",
            message=f"PayPal refund {transaction_id}",
        )


class MockGateway(PaymentGateway):
    """Always-succeeds mock — useful for testing."""

    def __init__(self) -> None:
        self._call_count = 0

    def charge(self, amount: float, currency: str) -> PaymentResult:
        self._call_count += 1
        return PaymentResult(
            success=True,
            transaction_id=f"mock_tx_{self._call_count}",
            message=f"Mock charge {amount} {currency}",
        )

    def refund(self, transaction_id: str) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"mock_ref_{transaction_id}",
            message=f"Mock refund {transaction_id}",
        )
