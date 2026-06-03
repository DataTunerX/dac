/*
 * stripe_gateway.h
 */
#ifndef STRIPE_GATEWAY_H
#define STRIPE_GATEWAY_H

#include "payment_gateway.h"

typedef struct StripeGateway {
    char api_key[64];
} StripeGateway;

void stripe_gateway_init(StripeGateway *g, const char *api_key);
void stripe_gateway_fill(PaymentGateway *iface, StripeGateway *g);

#endif
