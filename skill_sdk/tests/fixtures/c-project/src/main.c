/*
 * main.c — entry point that exercises all symbols across core/ and shop/.
 *
 * This ensures clangd indexes every type, function, and cross-file reference
 * for end-to-end LSP testing.
 */
#include "core/default_processor.h"
#include "core/handler.h"
#include "core/helper.h"

#include "shop/cart.h"
#include "shop/percentage_discount.h"
#include "shop/stripe_gateway.h"
#include "shop/inmemory_repository.h"
#include "shop/order_service.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *demo_core_run(void) {
    DefaultProcessor dp;
    default_processor_init(&dp);

    DataProcessor iface;
    default_processor_fill(&iface, &dp);

    Handler handler;
    handler_init(&handler, &iface);

    char *result = handler_process_request(&handler, "hello");
    printf("Core demo: %s\n", result);
    return result;
}

static void demo_shop_run(void) {
    InMemoryRepository repo;
    inmemory_repository_init(&repo);
    Repository repo_iface;
    inmemory_repository_fill(&repo_iface, &repo);

    StripeGateway stripe;
    stripe_gateway_init(&stripe, "sk_test_fixture");
    PaymentGateway gw_iface;
    stripe_gateway_fill(&gw_iface, &stripe);

    Product laptop = {"LAP-001", "Laptop Pro", 1299.99, "electronics", 10};
    Product mouse  = {"MOU-001", "Wireless Mouse", 29.99, "electronics", 50};

    Cart cart;
    cart_init(&cart, "user_fixture_001");
    cart_add_product(&cart, laptop, 1);
    cart_add_product(&cart, mouse, 2);

    PercentageDiscount pct_disc;
    percentage_discount_init(&pct_disc, 10.0);
    DiscountStrategy ds_pct;
    percentage_discount_fill(&ds_pct, &pct_disc);

    DiscountStrategy *discounts[] = {&ds_pct};

    OrderService svc;
    order_service_init(&svc, &repo_iface, &gw_iface, discounts, 1);

    Order order = order_service_place_order(&svc, cart, "ORD-0001");

    printf("[done] order=%s total=%.2f status=%s\n",
           order.order_id,
           order.raw_total_value,
           order_status_string(order.status));
}

int main(void) {
    char *core_result = demo_core_run();
    free(core_result);
    demo_shop_run();
    return 0;
}
