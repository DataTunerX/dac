/*
 * handler.h — HTTP-style request handler (cross-file LSP target).
 *
 * Cross-file: ProcessRequest calls NewHelper → HandleRequest.
 * goToDefinition on NewHelper from handler.c resolves to helper.h.
 */
#ifndef HANDLER_H
#define HANDLER_H

#include "data_processor.h"

#include <stdbool.h>

typedef struct Handler {
    DataProcessor *processor;
} Handler;

void handler_init(Handler *h, DataProcessor *processor);
char *handler_process_request(Handler *h, const char *payload);
bool handler_health_check(const Handler *h);

#endif /* HANDLER_H */
