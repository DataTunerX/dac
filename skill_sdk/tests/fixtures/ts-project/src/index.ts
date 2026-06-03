import { DefaultProcessor } from './core/DefaultProcessor';
import { ProcessorConfig } from './core/ProcessorConfig';
import { FixtureApp } from './app';

/**
 * Entry point mirroring the Java and Go fixtures. Kept intentionally minimal
 * so LSP operations on the core data-processing pipeline work consistently
 * across all fixture projects.
 */
function main(): void {
  const config = new ProcessorConfig(30, 3);
  const processor = new DefaultProcessor(config);
  console.log(`processor ready: ${processor.getConfig().getTimeout()}`);

  // Exercise the e-commerce shop wiring
  const result = FixtureApp.demoShopRun();
  console.log(result);

  console.log('done');
}

main();
