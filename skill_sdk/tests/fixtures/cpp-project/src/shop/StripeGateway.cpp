#include "StripeGateway.h"

StripeGateway::StripeGateway(const std::string& apiKey) : apiKey_(apiKey) {}

PaymentResult StripeGateway::Charge(double amount, const std::string& currency) {
    return PaymentResult{
        true,
        "stripe_ch_" + std::to_string(static_cast<int>(amount * 100)),
        "Charged " + std::to_string(amount) + " " + currency
    };
}

PaymentResult StripeGateway::Refund(const std::string& transactionID) {
    return PaymentResult{
        true,
        "stripe_ref_" + transactionID,
        "Refunded transaction " + transactionID
    };
}
