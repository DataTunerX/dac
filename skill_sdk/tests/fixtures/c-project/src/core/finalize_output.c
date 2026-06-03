/*
 * finalize_output.c — post-processing utility.
 *
 * hover docs: FinalizeOutput wraps the result with [final] ... [ok] markers.
 */
#include "finalize_output.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

char *finalize_output(const char *data) {
    size_t len = strlen(data) + 20;
    char *result = malloc(len);
    if (result) {
        snprintf(result, len, "[final] %s [ok]", data);
    }
    return result;
}
