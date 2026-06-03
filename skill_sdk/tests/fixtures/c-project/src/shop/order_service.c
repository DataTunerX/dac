/*
 * order_service.c — order placement implementation.
 */
#include "order_service.h"

#include <stdio.h>
#include <string.h>

void order_service_init(OrderService *svc, Repository *repo, PaymentGateway *gw,
                        DiscountStrategy **discounts, int discount_count) {
    svc->repo = repo;
    svc->gateway = gw;
    svc->discounts = discounts;
    svc->discount_count = discount_count;
}

Order order_service_place_order(OrderService *svc, Cart cart, const char *order_id) {
    Order order;
    strncpy(order.order_id, order_id, sizeof(order.order_id) - 1);
    order.order_id[sizeof(order.order_id) - 1] = '\0';
    order.item_count = cart.item_count;
    for (int i = 0; i < cart.item_count && i < 10; i++) {
        order.items[i] = cart.items[i];
    }
    order.status = ORDER_PENDING;

    /* compute raw total */
    double total = cart_raw_total(&cart);

    /* apply discounts sequentially */
    for (int i = 0; i < svc->discount_count; i++) {
        total = svc->discounts[i]->apply(svc->discounts[i]->ctx, total);
    }
    order.raw_total_value = total;

    /* charge via payment gateway */
    PaymentResult payment = svc->gateway->charge(svc->gateway->ctx, total, order_id);
    if (payment.success) {
        order.status = ORDER_CONFIRMED;
        printf("Payment OK: %s\n", payment.transaction_id);
    } else {
        order.status = ORDER_CANCELLED;
        printf("Payment FAILED: %s\n", payment.message);
    }

    /* persist */
    if (!svc->repo->save(svc->repo->ctx, &order)) {
        order.status = ORDER_CANCELLED;
    }

    return order;
}
