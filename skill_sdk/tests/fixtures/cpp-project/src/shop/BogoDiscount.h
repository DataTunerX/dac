#pragma once

#include "DiscountStrategy.h"

/**
 * BogoDiscount gives the cheapest item free.
 */
class BogoDiscount : public DiscountStrategy {
public:
    double Apply(const Order& order) override;
};
