package com.fixture.core;

/**
 * Defines the contract for processing data.
 * Analogous to the DataProcessor interface in main.go.
 */
public interface DataProcessor {

    String process(String data);

    boolean validate(String data);
}
