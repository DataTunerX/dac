#pragma once

#include "models.h"

#include <string>

/**
 * DiscountStrategy — contract for pluggable discount calculation.
 * findReferences on DiscountStrategy should locate all implementors + usages.
 * goToImplementation on DiscountStrategy should resolve to:
 *   PercentageDiscount, FixedAmountDiscount, BogoDiscount.
 */
class DiscountStrategy {
public:
    virtual ~DiscountStrategy() = default;

    /**
     * Apply calculates the discounted total for an order.
     */
    virtual double Apply(const Order& order) = 0;
};
