package com.fixture.shop.discount;

import java.util.List;

import com.fixture.shop.models.Order;

/**
 * Utility for applying multiple discount strategies.
 */
public final class DiscountUtils {

    private DiscountUtils() {
    }

    /**
     * Tries several strategies and returns the lowest price.
     */
    public static double applyBestDiscount(Order order, List<DiscountStrategy> strategies) {
        double best = order.rawTotal();
        for (DiscountStrategy s : strategies) {
            double value = s.apply(order);
            if (value < best) {
                best = value;
            }
        }
        return best;
    }
}
