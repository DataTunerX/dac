#pragma once

#include "PaymentGateway.h"

/**
 * MockGateway implements PaymentGateway for testing.
 */
class MockGateway : public PaymentGateway {
public:
    MockGateway();

    PaymentResult Charge(double amount, const std::string& currency) override;
    PaymentResult Refund(const std::string& transactionID) override;

private:
    int callCount_ = 0;
};
