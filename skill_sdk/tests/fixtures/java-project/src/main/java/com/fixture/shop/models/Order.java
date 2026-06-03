package com.fixture.shop.models;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * A customer order. Mirrors Order in shop/models.go.
 */
public class Order {

    private final String orderId;
    private final String userId;
    private final List<OrderItem> items;
    private OrderStatus status;
    private final LocalDateTime createdAt;
    private String discountCode;

    public Order(String orderId, String userId, List<OrderItem> items, String discountCode) {
        this.orderId = orderId;
        this.userId = userId;
        this.items = new ArrayList<>(items);
        this.status = OrderStatus.PENDING;
        this.createdAt = LocalDateTime.now();
        this.discountCode = discountCode;
    }

    public String getOrderId() { return orderId; }

    public String getUserId() { return userId; }

    public List<OrderItem> getItems() { return items; }

    public OrderStatus getStatus() { return status; }

    public void setStatus(OrderStatus status) { this.status = status; }

    public LocalDateTime getCreatedAt() { return createdAt; }

    public String getDiscountCode() { return discountCode; }

    public void setDiscountCode(String discountCode) { this.discountCode = discountCode; }

    public double rawTotal() {
        double total = 0;
        for (OrderItem item : items) {
            total += item.subtotal();
        }
        return total;
    }

    public double applyDiscount(double multiplier) {
        return rawTotal() * multiplier;
    }
}
