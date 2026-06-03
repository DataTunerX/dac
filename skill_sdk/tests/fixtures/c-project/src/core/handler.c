/*
 * handler.c — request handler implementation.
 */
#include "handler.h"
#include "helper.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void handler_init(Handler *h, DataProcessor *processor) {
    h->processor = processor;
}

char *handler_process_request(Handler *h, const char *payload) {
    printf("Processing request: %s\n", payload);

    Helper *helper = new_helper(h->processor);
    char *result = helper_handle_request(helper, payload);
    helper_free(helper);
    return result;
}

bool handler_health_check(const Handler *h) {
    return h->processor != NULL;
}
