/*
 * bogo_discount.h
 */
#ifndef BOGO_DISCOUNT_H
#define BOGO_DISCOUNT_H

#include "discount_strategy.h"

typedef struct BogoDiscount {
    int apply_count;
} BogoDiscount;

void bogo_discount_init(BogoDiscount *d);
void bogo_discount_fill(DiscountStrategy *iface, BogoDiscount *d);

#endif
