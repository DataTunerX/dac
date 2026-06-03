/*
 * fixed_amount_discount.c
 */
#include "fixed_amount_discount.h"

static double famt_apply(const void *ctx, double total) {
    const FixedAmountDiscount *d = (const FixedAmountDiscount *)ctx;
    double result = total - d->amount;
    return result > 0.0 ? result : 0.0;
}

void fixed_amount_discount_init(FixedAmountDiscount *d, double amt) {
    d->amount = amt;
}

void fixed_amount_discount_fill(DiscountStrategy *iface, FixedAmountDiscount *d) {
    iface->ctx = d;
    iface->apply = famt_apply;
}
