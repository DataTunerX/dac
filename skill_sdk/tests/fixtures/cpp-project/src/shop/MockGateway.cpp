#include "MockGateway.h"

MockGateway::MockGateway() {}

PaymentResult MockGateway::Charge(double amount, const std::string& currency) {
    callCount_++;
    return PaymentResult{
        true,
        "mock_tx_" + std::to_string(callCount_),
        "Mock charge " + std::to_string(amount) + " " + currency
    };
}

PaymentResult MockGateway::Refund(const std::string& transactionID) {
    return PaymentResult{
        true,
        "mock_ref_" + transactionID,
        "Mock refund " + transactionID
    };
}
