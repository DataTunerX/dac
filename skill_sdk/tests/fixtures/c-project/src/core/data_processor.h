/*
 * data_processor.h — interface contract for data processing.
 *
 * goToDefinition on DataProcessor should resolve to this header.
 * findReferences on DataProcessor should find all usages across core/ and shop/.
 * goToImplementation on DataProcessor_vtable via Process should locate default_processor.c.
 */
#ifndef DATA_PROCESSOR_H
#define DATA_PROCESSOR_H

#include <stdbool.h>

/**
 * DataProcessor defines the contract for processing data via a vtable.
 * Each implementor fills in validate and process callbacks.
 */
typedef struct DataProcessor {
    void *ctx;
    bool (*validate)(const void *ctx, const char *data);
    char *(*process)(const void *ctx, const char *data);
} DataProcessor;

#endif /* DATA_PROCESSOR_H */
