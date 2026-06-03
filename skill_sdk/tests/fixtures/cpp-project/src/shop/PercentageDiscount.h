#pragma once

#include "DiscountStrategy.h"

/**
 * PercentageDiscount applies a percentage off the raw total.
 */
class PercentageDiscount : public DiscountStrategy {
public:
    explicit PercentageDiscount(double percent);

    double Apply(const Order& order) override;

private:
    double percent_;
};
