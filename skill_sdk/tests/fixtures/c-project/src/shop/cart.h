/*
 * cart.h — shopping cart abstraction.
 *
 * goToDefinition on Cart (type/struct) resolves here.
 * findReferences on Cart finds usages in main.c and order_service.c.
 */
#ifndef CART_H
#define CART_H

#include "models.h"

typedef struct Cart {
    char user_id[32];
    OrderItem items[10];
    int item_count;
} Cart;

void cart_init(Cart *c, const char *user_id);
void cart_add_product(Cart *c, Product p, int quantity);
double cart_raw_total(const Cart *c);

#endif /* CART_H */
