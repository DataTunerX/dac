package com.fixture.shop.models;

/**
 * Possible states for an order. Mirrors OrderStatus in shop/models.go.
 */
public enum OrderStatus {
    PENDING,
    PAID,
    SHIPPED,
    DELIVERED,
    CANCELLED
}
