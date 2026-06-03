/*
 * mock_gateway.c
 */
#include "mock_gateway.h"

#include <stdio.h>

static PaymentResult mock_charge(const void *ctx, double amount, const char *order_id) {
    const MockGateway *g = (const MockGateway *)ctx;
    PaymentResult r;
    r.success = g->should_succeed;
    snprintf(r.transaction_id, sizeof(r.transaction_id), "MOCK_%s", order_id);
    snprintf(r.message, sizeof(r.message), g->should_succeed ? "mock success" : "mock failure");
    return r;
}

void mock_gateway_init(MockGateway *g, bool succeed) {
    g->should_succeed = succeed;
}

void mock_gateway_fill(PaymentGateway *iface, MockGateway *g) {
    iface->ctx = g;
    iface->charge = mock_charge;
}
