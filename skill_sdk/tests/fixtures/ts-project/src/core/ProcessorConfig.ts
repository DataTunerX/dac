/**
 * Configuration for processors. Mirrors ProcessorConfig in the Java fixture.
 */
export class ProcessorConfig {
  constructor(
    private readonly timeout: number,
    private readonly retries: number
  ) {}

  getTimeout(): number {
    return this.timeout;
  }

  getRetries(): number {
    return this.retries;
  }
}
