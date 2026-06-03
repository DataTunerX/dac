#pragma once

#include "models.h"

class DiscountStrategy;
class PaymentGateway;
class Repository;

/**
 * Cart is a transient shopping cart before conversion to an Order.
 * Checkout is the call-hierarchy centrepiece for the shop module.
 * outgoingCalls on Checkout should list: ToOrder, discount.Apply,
 * gateway.Charge, repo.SaveOrder, repo.UpdateOrderStatus.
 */
class Cart {
public:
    std::string UserID;
    std::vector<OrderItem> Items;

    /** AddProduct adds a product to the cart. */
    void AddProduct(const Product& product, int quantity);

    /** RemoveItem removes an item by index. */
    void RemoveItem(int index);

    /** CartTotal returns the sum of item subtotals. */
    double CartTotal() const;

    /** ToOrder converts the cart to an Order entity. */
    Order ToOrder(const std::string& orderID, const std::string& discountCode) const;

    /**
     * Checkout runs the full checkout pipeline.
     * outgoingCalls: ToOrder, discount.Apply, gateway.Charge, repo.SaveOrder, repo.UpdateOrderStatus.
     * incomingCalls: PlaceOrder (OrderService).
     */
    Order Checkout(
        const std::string& orderID,
        Repository& repo,
        PaymentGateway& gateway,
        DiscountStrategy* discount
    );
};
