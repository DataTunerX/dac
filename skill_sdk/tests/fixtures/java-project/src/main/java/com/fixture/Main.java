package com.fixture;

import com.fixture.core.DefaultProcessor;
import com.fixture.core.ProcessorConfig;

/**
 * Entry point mirroring main.go. Kept intentionally minimal so LSP operations on
 * the core data-processing pipeline work identically to the Go fixture.
 */
public class Main {

    public static void main(String[] args) {
        ProcessorConfig config = new ProcessorConfig(30, 3);
        DefaultProcessor processor = new DefaultProcessor(config);
        System.out.println("processor ready: " + processor.getConfig().getTimeout());

        // Exercise the e-commerce shop wiring
        FixtureApp.demoShopRun();

        System.out.println("done");
    }
}
