#pragma once

#include "cart.h"
#include "DiscountStrategy.h"
#include "PaymentGateway.h"
#include "Repository.h"

#include <vector>

/**
 * OrderService orchestrates the checkout flow.
 * This is the top-level entry point for incomingCalls.
 * outgoingCalls on PlaceOrder should list: cart.ToOrder, cart.Checkout.
 * incomingCalls on PlaceOrder should list: demoShopRun (main.cpp).
 *
 * CancelOrder — outgoingCalls: repo.GetOrder, repo.UpdateOrderStatus.
 */
class OrderService {
public:
    OrderService(Repository& repo, PaymentGateway& gateway,
                 std::vector<DiscountStrategy*> strategies);

    /**
     * PlaceOrder runs the full order flow.
     * outgoingCalls: cart.ToOrder, cart.Checkout
     */
    Order PlaceOrder(Cart& cart, const std::string& orderID);

    /**
     * CancelOrder cancels an order and updates its status.
     * outgoingCalls: repo.GetOrder, repo.UpdateOrderStatus
     */
    bool CancelOrder(const std::string& orderID);

private:
    Repository& repo_;
    PaymentGateway& gateway_;
    std::vector<DiscountStrategy*> strategies_;
};
