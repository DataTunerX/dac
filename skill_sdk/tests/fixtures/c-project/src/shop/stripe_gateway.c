/*
 * stripe_gateway.c
 */
#include "stripe_gateway.h"

#include <stdio.h>
#include <string.h>

static PaymentResult stripe_charge(const void *ctx, double amount, const char *order_id) {
    const StripeGateway *g = (const StripeGateway *)ctx;
    PaymentResult r;
    r.success = true;
    snprintf(r.transaction_id, sizeof(r.transaction_id), "ch_stripe_%s_%d", order_id, (int)(amount * 100));
    snprintf(r.message, sizeof(r.message), "charged %.2f via Stripe (key=%s...)", amount, g->api_key);
    return r;
}

void stripe_gateway_init(StripeGateway *g, const char *api_key) {
    strncpy(g->api_key, api_key, sizeof(g->api_key) - 1);
    g->api_key[sizeof(g->api_key) - 1] = '\0';
}

void stripe_gateway_fill(PaymentGateway *iface, StripeGateway *g) {
    iface->ctx = g;
    iface->charge = stripe_charge;
}
