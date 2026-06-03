#include "PercentageDiscount.h"

PercentageDiscount::PercentageDiscount(double percent) : percent_(percent) {}

double PercentageDiscount::Apply(const Order& order) {
    return order.RawTotal() * (1.0 - percent_ / 100.0);
}
