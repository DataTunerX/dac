package com.fixture.core;

/**
 * Applies post-processing to the result. Mirrors FinalizeOutput in main.go.
 */
public final class FinalizeOutput {

    private FinalizeOutput() {
    }

    public static String finalize(String data) {
        return "[final] " + data + " [ok]";
    }
}
