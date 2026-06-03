package com.fixture.shop.payment;

/**
 * Stripe-backed payment gateway.
 */
public class StripeGateway implements PaymentGateway {

    private final String apiKey;

    public StripeGateway(String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    public PaymentResult charge(double amount, String currency) {
        String txId = "stripe_ch_" + hashFloat(amount);
        return new PaymentResult(true, txId, "Charged " + amount + " " + currency);
    }

    @Override
    public PaymentResult refund(String transactionId) {
        return new PaymentResult(true, "stripe_ref_" + transactionId,
                "Refunded transaction " + transactionId);
    }

    public String getApiKey() {
        return apiKey;
    }

    private static int hashFloat(double f) {
        return (int) (f * 100);
    }
}
