/*
 * order_service.h — order placement service (cross-file call chain target).
 *
 * PlaceOrder is the main entry point for order creation.
 * outgoingCalls on PlaceOrder reveals: save → charge → discount.apply
 */
#ifndef ORDER_SERVICE_H
#define ORDER_SERVICE_H

#include "cart.h"
#include "discount_strategy.h"
#include "models.h"
#include "payment_gateway.h"
#include "repository.h"

typedef struct OrderService {
    Repository *repo;
    PaymentGateway *gateway;
    DiscountStrategy **discounts;
    int discount_count;
} OrderService;

void order_service_init(OrderService *svc, Repository *repo, PaymentGateway *gw,
                        DiscountStrategy **discounts, int discount_count);
Order order_service_place_order(OrderService *svc, Cart cart, const char *order_id);

#endif
