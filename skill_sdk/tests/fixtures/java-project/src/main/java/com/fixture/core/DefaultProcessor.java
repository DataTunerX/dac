package com.fixture.core;

/**
 * Primary implementation of DataProcessor. Mirrors DefaultProcessor in main.go.
 */
public class DefaultProcessor implements DataProcessor {

    private final ProcessorConfig config;

    public DefaultProcessor(ProcessorConfig config) {
        this.config = config;
    }

    public ProcessorConfig getConfig() {
        return config;
    }

    @Override
    public String process(String data) {
        if (!validate(data)) {
            throw new IllegalArgumentException("invalid data: " + data);
        }
        return TransformData.transform(data);
    }

    @Override
    public boolean validate(String data) {
        return data != null && data.length() > 0 && data.length() < 1024;
    }
}
