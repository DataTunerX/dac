/*
 * processor_config.h — configuration struct for data processors.
 */
#ifndef PROCESSOR_CONFIG_H
#define PROCESSOR_CONFIG_H

typedef struct ProcessorConfig {
    int timeout;
    int retries;
} ProcessorConfig;

#endif /* PROCESSOR_CONFIG_H */
