#include "PayPalGateway.h"

PayPalGateway::PayPalGateway(const std::string& clientID, const std::string& clientSecret)
    : clientID_(clientID), clientSecret_(clientSecret) {}

PaymentResult PayPalGateway::Charge(double amount, const std::string& currency) {
    return PaymentResult{
        true,
        "pp_ch_" + std::to_string(static_cast<int>(amount * 100)),
        "PayPal charge " + std::to_string(amount) + " " + currency
    };
}

PaymentResult PayPalGateway::Refund(const std::string& transactionID) {
    return PaymentResult{
        true,
        "pp_ref_" + transactionID,
        "PayPal refund " + transactionID
    };
}
