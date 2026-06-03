#pragma once

#include "PaymentGateway.h"

/**
 * PayPalGateway implements PaymentGateway via PayPal.
 */
class PayPalGateway : public PaymentGateway {
public:
    PayPalGateway(const std::string& clientID, const std::string& clientSecret);

    PaymentResult Charge(double amount, const std::string& currency) override;
    PaymentResult Refund(const std::string& transactionID) override;

private:
    std::string clientID_;
    std::string clientSecret_;
};
