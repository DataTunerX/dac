/*
 * paypal_gateway.c
 */
#include "paypal_gateway.h"

#include <stdio.h>

static PaymentResult paypal_charge(const void *ctx, double amount, const char *order_id) {
    (void)ctx;
    PaymentResult r;
    r.success = true;
    snprintf(r.transaction_id, sizeof(r.transaction_id), "PP_%s_%.0f", order_id, amount * 100);
    snprintf(r.message, sizeof(r.message), "charged %.2f via PayPal", amount);
    return r;
}

void paypal_gateway_init(PayPalGateway *g, const char *client_id) {
    snprintf(g->client_id, sizeof(g->client_id), "%s", client_id);
}

void paypal_gateway_fill(PaymentGateway *iface, PayPalGateway *g) {
    iface->ctx = g;
    iface->charge = paypal_charge;
}
