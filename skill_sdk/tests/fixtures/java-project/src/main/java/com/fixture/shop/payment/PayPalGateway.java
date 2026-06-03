package com.fixture.shop.payment;

/**
 * PayPal-backed payment gateway.
 */
public class PayPalGateway implements PaymentGateway {

    private final String clientId;
    private final String clientSecret;

    public PayPalGateway(String clientId, String clientSecret) {
        this.clientId = clientId;
        this.clientSecret = clientSecret;
    }

    @Override
    public PaymentResult charge(double amount, String currency) {
        String txId = "pp_ch_" + hashFloat(amount);
        return new PaymentResult(true, txId, "PayPal charge " + amount + " " + currency);
    }

    @Override
    public PaymentResult refund(String transactionId) {
        return new PaymentResult(true, "pp_ref_" + transactionId,
                "PayPal refund " + transactionId);
    }

    private static int hashFloat(double f) {
        return (int) (f * 100);
    }
}
