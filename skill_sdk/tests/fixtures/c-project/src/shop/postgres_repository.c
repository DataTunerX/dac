/*
 * postgres_repository.c
 */
#include "postgres_repository.h"

#include <stdio.h>
#include <string.h>

static bool pg_save(const void *ctx, const Order *order) {
    const PostgresRepository *r = (const PostgresRepository *)ctx;
    printf("[PG] saving order %s via %s\n", order->order_id, r->conn_string);
    return true;
}

static Order *pg_find_by_id(const void *ctx, const char *order_id) {
    (void)ctx;
    (void)order_id;
    return NULL;
}

void postgres_repository_init(PostgresRepository *r, const char *conn) {
    strncpy(r->conn_string, conn, sizeof(r->conn_string) - 1);
    r->conn_string[sizeof(r->conn_string) - 1] = '\0';
}

void postgres_repository_fill(Repository *iface, PostgresRepository *r) {
    iface->ctx = r;
    iface->save = pg_save;
    iface->find_by_id = pg_find_by_id;
}
