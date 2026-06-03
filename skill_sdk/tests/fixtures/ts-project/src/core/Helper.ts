import { DataProcessor } from './DataProcessor';
import { FinalizeOutput } from './FinalizeOutput';

/**
 * Bridges the processor with external systems. Mirrors Helper in the Java fixture.
 */
export class Helper {
  constructor(private readonly processor: DataProcessor) {}

  handleRequest(input: string): string {
    const validated = this.processor.validate(input);
    if (!validated) {
      throw new Error('validation failed');
    }
    const result = this.processor.process(input);
    return FinalizeOutput.finalize(result);
  }
}
