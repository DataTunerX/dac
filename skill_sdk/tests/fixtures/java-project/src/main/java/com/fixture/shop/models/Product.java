package com.fixture.shop.models;

import java.util.Objects;

/**
 * A product available for purchase. Mirrors Product in shop/models.go.
 */
public class Product {

    private final String sku;
    private final String name;
    private final double price;
    private final String category;
    private int stock;

    public Product(String sku, String name, double price, String category, int stock) {
        this.sku = Objects.requireNonNull(sku);
        this.name = Objects.requireNonNull(name);
        this.price = price;
        this.category = Objects.requireNonNull(category);
        this.stock = stock;
    }

    public String getSku() { return sku; }

    public String getName() { return name; }

    public double getPrice() { return price; }

    public String getCategory() { return category; }

    public int getStock() { return stock; }

    public void setStock(int stock) { this.stock = stock; }

    public boolean isInStock() {
        return stock > 0;
    }
}
