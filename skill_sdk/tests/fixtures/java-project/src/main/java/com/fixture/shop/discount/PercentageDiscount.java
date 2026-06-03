package com.fixture.shop.discount;

import com.fixture.shop.models.Order;

/**
 * Applies a percentage off the raw total.
 */
public class PercentageDiscount implements DiscountStrategy {

    private final double percent;

    public PercentageDiscount(double percent) {
        this.percent = percent;
    }

    @Override
    public double apply(Order order) {
        return order.rawTotal() * (1.0 - percent / 100.0);
    }

    public double getPercent() {
        return percent;
    }
}
