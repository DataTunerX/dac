/*
 * bogo_discount.c
 */
#include "bogo_discount.h"

static double bogo_apply(const void *ctx, double total) {
    const BogoDiscount *d = (const BogoDiscount *)ctx;
    if (d->apply_count % 2 == 0) {
        return total / 2.0;
    }
    return total;
}

void bogo_discount_init(BogoDiscount *d) {
    d->apply_count = 0;
}

void bogo_discount_fill(DiscountStrategy *iface, BogoDiscount *d) {
    iface->ctx = d;
    iface->apply = bogo_apply;
}
