/*
 * helper.c — bridges processor with external systems.
 */
#include "helper.h"
#include "finalize_output.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

Helper *new_helper(DataProcessor *proc) {
    Helper *h = malloc(sizeof(Helper));
    if (h) {
        h->processor = proc;
    }
    return h;
}

void helper_free(Helper *h) {
    free(h);
}

char *helper_handle_request(Helper *h, const char *input) {
    if (!h->processor->validate(h->processor->ctx, input)) {
        char *err = malloc(64);
        if (err) {
            snprintf(err, 64, "validation failed for: %s", input);
        }
        return err;
    }

    char *raw = h->processor->process(h->processor->ctx, input);
    if (!raw) {
        return NULL;
    }

    char *final = finalize_output(raw);
    free(raw);
    return final;
}
