/*
 * percentage_discount.h — percentage-off discount strategy.
 *
 * hover on PercentageDiscount shows doc: applies a percentage reduction.
 */
#ifndef PERCENTAGE_DISCOUNT_H
#define PERCENTAGE_DISCOUNT_H

#include "discount_strategy.h"

typedef struct PercentageDiscount {
    double percentage;
} PercentageDiscount;

void percentage_discount_init(PercentageDiscount *d, double pct);
void percentage_discount_fill(DiscountStrategy *iface, PercentageDiscount *d);

#endif /* PERCENTAGE_DISCOUNT_H */
