package com.fixture.shop.payment;

/**
 * Payment processing contract. goToImplementation should resolve to
 * StripeGateway, PayPalGateway, MockGateway.
 */
public interface PaymentGateway {

    PaymentResult charge(double amount, String currency);

    PaymentResult refund(String transactionId);
}
