/*
 * mock_gateway.h
 */
#ifndef MOCK_GATEWAY_H
#define MOCK_GATEWAY_H

#include "payment_gateway.h"

typedef struct MockGateway {
    bool should_succeed;
} MockGateway;

void mock_gateway_init(MockGateway *g, bool succeed);
void mock_gateway_fill(PaymentGateway *iface, MockGateway *g);

#endif
