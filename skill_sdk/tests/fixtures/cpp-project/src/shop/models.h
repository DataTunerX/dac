#pragma once

#include <string>
#include <vector>
#include <functional>
#include <ctime>

/**
 * OrderStatus represents possible states for an order.
 */
enum class OrderStatus {
    Pending,
    Paid,
    Shipped,
    Delivered,
    Cancelled
};

/**
 * Product represents an item available for purchase.
 */
struct Product {
    std::string SKU;
    std::string Name;
    double Price = 0.0;
    std::string Category;
    int Stock = 0;

    /** IsInStock checks whether the product has available inventory. */
    bool IsInStock() const;
};

/**
 * OrderItem is a single line item within an order.
 */
struct OrderItem {
    Product Product;
    int Quantity = 1;
    double UnitPrice = 0.0;

    /** Subtotal returns the line-item total. */
    double Subtotal() const;
};

/**
 * Order is a customer order.
 * ApplyDiscount method depends on cart::Cart, PaymentGateway — cross-file.
 */
struct Order {
    std::string OrderID;
    std::string UserID;
    std::vector<OrderItem> Items;
    OrderStatus Status = OrderStatus::Pending;
    std::time_t CreatedAt = 0;
    std::string DiscountCode;

    /** RawTotal sums all item subtotals before discounts. */
    double RawTotal() const;

    /** ApplyDiscount returns the discounted total. */
    double ApplyDiscount(double multiplier) const;
};
