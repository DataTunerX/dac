package com.fixture.core;

/**
 * Processes incoming API requests. Mirrors Handler in handler.go.
 */
public class Handler {

    private final DataProcessor processor;

    public Handler(DataProcessor processor) {
        this.processor = processor;
    }

    public String processRequest(String payload) {
        System.out.println("Processing request: " + payload);

        Helper helper = new Helper(processor);
        return helper.handleRequest(payload);
    }

    public boolean healthCheck() {
        return processor != null;
    }
}
