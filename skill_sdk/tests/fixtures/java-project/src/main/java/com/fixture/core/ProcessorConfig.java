package com.fixture.core;

/**
 * Configuration for processors. Mirrors ProcessorConfig struct in main.go.
 */
public class ProcessorConfig {

    private final int timeout;
    private final int retries;

    public ProcessorConfig(int timeout, int retries) {
        this.timeout = timeout;
        this.retries = retries;
    }

    public int getTimeout() {
        return timeout;
    }

    public int getRetries() {
        return retries;
    }
}
