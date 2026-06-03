package com.fixture.shop.payment;

/**
 * Always-succeeds mock gateway for testing.
 */
public class MockGateway implements PaymentGateway {

    private int callCount = 0;

    @Override
    public PaymentResult charge(double amount, String currency) {
        callCount++;
        return new PaymentResult(true, "mock_tx_" + callCount,
                "Mock charge " + amount + " " + currency);
    }

    @Override
    public PaymentResult refund(String transactionId) {
        return new PaymentResult(true, "mock_ref_" + transactionId,
                "Mock refund " + transactionId);
    }

    public int getCallCount() {
        return callCount;
    }
}
