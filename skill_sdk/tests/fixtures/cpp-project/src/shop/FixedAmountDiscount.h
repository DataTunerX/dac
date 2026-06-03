#pragma once

#include "DiscountStrategy.h"

#include <algorithm>

/**
 * FixedAmountDiscount subtracts a fixed amount (floored at zero).
 */
class FixedAmountDiscount : public DiscountStrategy {
public:
    explicit FixedAmountDiscount(double amount);

    double Apply(const Order& order) override;

private:
    double amount_;
};
