/*
 * fixed_amount_discount.h
 */
#ifndef FIXED_AMOUNT_DISCOUNT_H
#define FIXED_AMOUNT_DISCOUNT_H

#include "discount_strategy.h"

typedef struct FixedAmountDiscount {
    double amount;
} FixedAmountDiscount;

void fixed_amount_discount_init(FixedAmountDiscount *d, double amt);
void fixed_amount_discount_fill(DiscountStrategy *iface, FixedAmountDiscount *d);

#endif
