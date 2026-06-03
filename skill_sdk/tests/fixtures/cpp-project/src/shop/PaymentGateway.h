#pragma once

#include "PaymentResult.h"

#include <string>

/**
 * PaymentGateway defines the payment processing contract.
 * goToImplementation on PaymentGateway should resolve to:
 *   StripeGateway, PayPalGateway, MockGateway.
 */
class PaymentGateway {
public:
    virtual ~PaymentGateway() = default;

    virtual PaymentResult Charge(double amount, const std::string& currency) = 0;
    virtual PaymentResult Refund(const std::string& transactionID) = 0;
};
