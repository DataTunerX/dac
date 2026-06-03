package com.fixture.shop.discount;

import com.fixture.shop.models.Order;
import com.fixture.shop.models.OrderItem;

/**
 * Buy-one-get-one — cheapest item is free.
 */
public class BogoDiscount implements DiscountStrategy {

    @Override
    public double apply(Order order) {
        if (order.getItems().size() < 2) {
            return order.rawTotal();
        }
        double cheapest = Double.MAX_VALUE;
        for (OrderItem item : order.getItems()) {
            if (item.subtotal() < cheapest) {
                cheapest = item.subtotal();
            }
        }
        return order.rawTotal() - cheapest;
    }
}
