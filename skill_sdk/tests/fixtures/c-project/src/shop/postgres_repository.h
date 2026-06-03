/*
 * postgres_repository.h
 */
#ifndef POSTGRES_REPOSITORY_H
#define POSTGRES_REPOSITORY_H

#include "repository.h"

typedef struct PostgresRepository {
    char conn_string[128];
} PostgresRepository;

void postgres_repository_init(PostgresRepository *r, const char *conn);
void postgres_repository_fill(Repository *iface, PostgresRepository *r);

#endif
