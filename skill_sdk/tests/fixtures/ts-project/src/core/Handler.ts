import { DataProcessor } from './DataProcessor';
import { Helper } from './Helper';

/**
 * Processes incoming API requests. Mirrors Handler in the Java fixture.
 */
export class Handler {
  constructor(private readonly processor: DataProcessor) {}

  processRequest(payload: string): string {
    console.log(`Processing request: ${payload}`);

    const helper = new Helper(this.processor);
    return helper.handleRequest(payload);
  }

  healthCheck(): boolean {
    return this.processor !== null;
  }
}
