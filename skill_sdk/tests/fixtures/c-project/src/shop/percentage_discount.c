/*
 * percentage_discount.c
 */
#include "percentage_discount.h"

static double pct_apply(const void *ctx, double total) {
    const PercentageDiscount *d = (const PercentageDiscount *)ctx;
    return total * (1.0 - d->percentage / 100.0);
}

void percentage_discount_init(PercentageDiscount *d, double pct) {
    d->percentage = pct;
}

void percentage_discount_fill(DiscountStrategy *iface, PercentageDiscount *d) {
    iface->ctx = d;
    iface->apply = pct_apply;
}
