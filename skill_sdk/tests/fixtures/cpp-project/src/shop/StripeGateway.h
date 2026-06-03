#pragma once

#include "PaymentGateway.h"

/**
 * StripeGateway implements PaymentGateway via Stripe.
 */
class StripeGateway : public PaymentGateway {
public:
    explicit StripeGateway(const std::string& apiKey);

    PaymentResult Charge(double amount, const std::string& currency) override;
    PaymentResult Refund(const std::string& transactionID) override;

private:
    std::string apiKey_;
};
