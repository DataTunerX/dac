/*
 * default_processor.h — primary DataProcessor implementation.
 *
 * goToImplementation on DataProcessor should resolve to default_processor_fill.
 */
#ifndef DEFAULT_PROCESSOR_H
#define DEFAULT_PROCESSOR_H

#include "data_processor.h"
#include "processor_config.h"

typedef struct DefaultProcessor {
    ProcessorConfig config;
} DefaultProcessor;

void default_processor_init(DefaultProcessor *p);
void default_processor_init_config(DefaultProcessor *p, ProcessorConfig cfg);

void default_processor_fill(DataProcessor *iface, DefaultProcessor *p);

void default_processor_set_retries(DefaultProcessor *p, int retries);

#endif /* DEFAULT_PROCESSOR_H */
