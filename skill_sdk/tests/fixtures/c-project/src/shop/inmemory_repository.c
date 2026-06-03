/*
 * inmemory_repository.c
 */
#include "inmemory_repository.h"

#include <string.h>

static bool im_save(const void *ctx, const Order *order) {
    InMemoryRepository *r = (InMemoryRepository *)ctx;
    if (r->count >= INMEMORY_MAX_ORDERS) return false;
    r->orders[r->count++] = *order;
    return true;
}

static Order *im_find_by_id(const void *ctx, const char *order_id) {
    InMemoryRepository *r = (InMemoryRepository *)ctx;
    for (int i = 0; i < r->count; i++) {
        if (strcmp(r->orders[i].order_id, order_id) == 0) {
            return &r->orders[i];
        }
    }
    return NULL;
}

void inmemory_repository_init(InMemoryRepository *r) {
    r->count = 0;
}

void inmemory_repository_fill(Repository *iface, InMemoryRepository *r) {
    iface->ctx = r;
    iface->save = im_save;
    iface->find_by_id = im_find_by_id;
}
