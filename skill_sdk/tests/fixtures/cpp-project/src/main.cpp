#include "core/DefaultProcessor.h"
#include "core/Handler.h"
#include "core/Helper.h"

#include "shop/cart.h"
#include "shop/PercentageDiscount.h"
#include "shop/StripeGateway.h"
#include "shop/InMemoryRepository.h"
#include "shop/OrderService.h"

#include <iostream>
#include <memory>

/**
 * demoCoreRun exercises core module symbols.
 * This ensures clangd indexes all core symbols, references, and call chains.
 */
static std::string demoCoreRun() {
    auto proc = std::make_shared<DefaultProcessor>();

    auto handler = std::make_unique<Handler>(proc);
    auto result = handler->ProcessRequest("hello");

    std::cout << "Core demo: " << result << std::endl;
    return result;
}

/**
 * demoShopRun wires and exercises the e-commerce subpackage so clangd indexes
 * all symbols, references, and call chains across the shop/ tree.
 * This is the entry-point that triggers all cross-file LSP lookups.
 */
static std::string demoShopRun() {
    InMemoryRepository repo;
    StripeGateway gateway("sk_test_fixture");

    Product laptop{"LAP-001", "Laptop Pro", 1299.99, "electronics", 10};
    Product mouse{"MOU-001", "Wireless Mouse", 29.99, "electronics", 50};

    Cart cart{"user_fixture_001"};
    cart.AddProduct(laptop, 1);
    cart.AddProduct(mouse, 2);

    PercentageDiscount discount(10);

    OrderService svc(repo, gateway, {&discount});
    auto order = svc.PlaceOrder(cart, "ORD-0001");

    return "[done] order=" + order.OrderID
         + " total=" + std::to_string(order.RawTotal())
         + " status=" + std::to_string(static_cast<int>(order.Status));
}

int main() {
    demoCoreRun();
    demoShopRun();
    return 0;
}
