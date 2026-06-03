package com.fixture.core;

/**
 * Bridges the processor with external systems. Mirrors Helper in main.go.
 */
public class Helper {

    private final DataProcessor processor;

    public Helper(DataProcessor processor) {
        this.processor = processor;
    }

    public String handleRequest(String input) {
        boolean validated = processor.validate(input);
        if (!validated) {
            throw new IllegalArgumentException("validation failed");
        }
        String result = processor.process(input);
        return FinalizeOutput.finalize(result);
    }
}
