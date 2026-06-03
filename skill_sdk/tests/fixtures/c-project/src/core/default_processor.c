/*
 * default_processor.c — primary DataProcessor implementation.
 */
#include "default_processor.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool default_validate(const void *ctx, const char *data) {
    (void)ctx;
    return data != NULL && strlen(data) > 0 && strlen(data) < 1024;
}

static char *transform_data(const char *data) {
    size_t len = strlen(data) + 20;
    char *result = malloc(len);
    if (result) {
        snprintf(result, len, "processed: %s", data);
    }
    return result;
}

static char *default_process(const void *ctx, const char *data) {
    const DefaultProcessor *self = (const DefaultProcessor *)ctx;
    if (!self->config.timeout) {
        return NULL;
    }
    if (!default_validate(ctx, data)) {
        return NULL;
    }
    return transform_data(data);
}

void default_processor_init(DefaultProcessor *p) {
    p->config.timeout = 30;
    p->config.retries = 3;
}

void default_processor_init_config(DefaultProcessor *p, ProcessorConfig cfg) {
    p->config = cfg;
}

void default_processor_fill(DataProcessor *iface, DefaultProcessor *p) {
    iface->ctx = p;
    iface->validate = default_validate;
    iface->process = default_process;
}

void default_processor_set_retries(DefaultProcessor *p, int retries) {
    p->config.retries = retries;
}
