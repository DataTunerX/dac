/*
 * cart.c — shopping cart implementation.
 */
#include "cart.h"

#include <string.h>

void cart_init(Cart *c, const char *user_id) {
    strncpy(c->user_id, user_id, sizeof(c->user_id) - 1);
    c->user_id[sizeof(c->user_id) - 1] = '\0';
    c->item_count = 0;
}

void cart_add_product(Cart *c, Product p, int quantity) {
    if (c->item_count >= 10) return;
    c->items[c->item_count].product = p;
    c->items[c->item_count].quantity = quantity;
    c->item_count++;
}

double cart_raw_total(const Cart *c) {
    double total = 0.0;
    for (int i = 0; i < c->item_count; i++) {
        total += c->items[i].product.price * c->items[i].quantity;
    }
    return total;
}
