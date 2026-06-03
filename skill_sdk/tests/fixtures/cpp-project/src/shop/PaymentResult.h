#pragma once

#include <string>

/**
 * PaymentResult represents the outcome of a payment attempt.
 */
struct PaymentResult {
    bool Success = false;
    std::string TransactionID;
    std::string Message;
};
