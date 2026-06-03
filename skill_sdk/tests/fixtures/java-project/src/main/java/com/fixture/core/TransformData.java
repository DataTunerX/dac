package com.fixture.core;

/**
 * Applies transformation rules to raw data. Mirrors TransformData function in main.go.
 */
public final class TransformData {

    private TransformData() {
    }

    public static String transform(String data) {
        return "processed: " + data;
    }
}
