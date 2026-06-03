package com.fixture.shop.models;

/**
 * A single line item within an order. Mirrors OrderItem in shop/models.go.
 */
public class OrderItem {

    private final Product product;
    private final int quantity;
    private final double unitPrice;

    public OrderItem(Product product, int quantity, double unitPrice) {
        this.product = product;
        this.quantity = quantity;
        this.unitPrice = unitPrice;
    }

    public Product getProduct() { return product; }

    public int getQuantity() { return quantity; }

    public double getUnitPrice() { return unitPrice; }

    public double subtotal() {
        return unitPrice * quantity;
    }
}
