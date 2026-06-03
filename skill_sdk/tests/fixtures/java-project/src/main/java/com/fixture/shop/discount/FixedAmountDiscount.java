package com.fixture.shop.discount;

import com.fixture.shop.models.Order;

/**
 * Subtracts a fixed amount from the total (floored at zero).
 */
public class FixedAmountDiscount implements DiscountStrategy {

    private final double amount;

    public FixedAmountDiscount(double amount) {
        this.amount = amount;
    }

    @Override
    public double apply(Order order) {
        return Math.max(0, order.rawTotal() - amount);
    }

    public double getAmount() {
        return amount;
    }
}
