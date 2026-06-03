/*
 * helper.h — bridges processor with external systems.
 *
 * goToDefinition from handler.c NewHelper call resolves here.
 */
#ifndef HELPER_H
#define HELPER_H

#include "data_processor.h"

typedef struct Helper {
    DataProcessor *processor;
} Helper;

Helper *new_helper(DataProcessor *proc);
void helper_free(Helper *h);

char *helper_handle_request(Helper *h, const char *input);

#endif /* HELPER_H */
