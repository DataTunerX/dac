/*
 * discount_strategy.h — discount strategy interface (vtable pattern).
 *
 * goToImplementation on DiscountStrategy finds all implementations.
 */
#ifndef DISCOUNT_STRATEGY_H
#define DISCOUNT_STRATEGY_H

typedef struct DiscountStrategy {
    void *ctx;
    double (*apply)(const void *ctx, double total);
} DiscountStrategy;

#endif /* DISCOUNT_STRATEGY_H */
