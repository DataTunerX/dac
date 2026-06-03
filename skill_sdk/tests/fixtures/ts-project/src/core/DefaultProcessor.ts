import { DataProcessor } from './DataProcessor';
import { TransformData } from './TransformData';

/**
 * Primary implementation of DataProcessor. Mirrors DefaultProcessor in the Java fixture.
 */
export class DefaultProcessor implements DataProcessor {
  constructor(private readonly config: { getTimeout(): number; getRetries(): number }) {}

  getConfig(): { getTimeout(): number; getRetries(): number } {
    return this.config;
  }

  process(data: string): string {
    if (!this.validate(data)) {
      throw new Error(`invalid data: ${data}`);
    }
    return TransformData.transform(data);
  }

  validate(data: string): boolean {
    return data !== null && data !== undefined && data.length > 0 && data.length < 1024;
  }
}
