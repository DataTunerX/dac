/*
 * paypal_gateway.h
 */
#ifndef PAYPAL_GATEWAY_H
#define PAYPAL_GATEWAY_H

#include "payment_gateway.h"

typedef struct PayPalGateway {
    char client_id[64];
} PayPalGateway;

void paypal_gateway_init(PayPalGateway *g, const char *client_id);
void paypal_gateway_fill(PaymentGateway *iface, PayPalGateway *g);

#endif
