/*
 * repository.h — repository interface (vtable pattern).
 */
#ifndef REPOSITORY_H
#define REPOSITORY_H

#include "models.h"

#include <stdbool.h>

typedef struct Repository {
    void *ctx;
    bool (*save)(const void *ctx, const Order *order);
    Order *(*find_by_id)(const void *ctx, const char *order_id);
} Repository;

#endif
