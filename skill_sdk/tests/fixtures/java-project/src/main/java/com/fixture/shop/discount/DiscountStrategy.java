package com.fixture.shop.discount;

import com.fixture.shop.models.Order;

/**
 * Contract for pluggable discount calculation.
 * findReferences on DiscountStrategy should locate all implementors.
 */
public interface DiscountStrategy {

    double apply(Order order);
}
