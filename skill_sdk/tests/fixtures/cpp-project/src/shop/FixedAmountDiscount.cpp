#include "FixedAmountDiscount.h"

FixedAmountDiscount::FixedAmountDiscount(double amount) : amount_(amount) {}

double FixedAmountDiscount::Apply(const Order& order) {
    return std::max(0.0, order.RawTotal() - amount_);
}
