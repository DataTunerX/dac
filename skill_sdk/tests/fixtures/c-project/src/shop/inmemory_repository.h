/*
 * inmemory_repository.h
 */
#ifndef INMEMORY_REPOSITORY_H
#define INMEMORY_REPOSITORY_H

#include "repository.h"

#define INMEMORY_MAX_ORDERS 100

typedef struct InMemoryRepository {
    Order orders[INMEMORY_MAX_ORDERS];
    int count;
} InMemoryRepository;

void inmemory_repository_init(InMemoryRepository *r);
void inmemory_repository_fill(Repository *iface, InMemoryRepository *r);

#endif
