/*
 * payment_gateway.h — payment gateway interface (vtable pattern).
 *
 * goToImplementation on PaymentGateway finds Stripe/PayPal/Mock.
 */
#ifndef PAYMENT_GATEWAY_H
#define PAYMENT_GATEWAY_H

#include <stdbool.h>

typedef struct PaymentResult {
    bool success;
    char transaction_id[64];
    char message[128];
} PaymentResult;

typedef struct PaymentGateway {
    void *ctx;
    PaymentResult (*charge)(const void *ctx, double amount, const char *order_id);
} PaymentGateway;

#endif
