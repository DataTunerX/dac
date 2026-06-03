import { FinalizeOutput } from './FinalizeOutput.js';

/**
 * Bridges the processor with external systems. Mirrors Helper in the Java fixture.
 */
export class Helper {
  /**
   * @param {import('./DataProcessor.js').DataProcessor} processor
   */
  constructor(processor) {
    /** @type {import('./DataProcessor.js').DataProcessor} */
    this._processor = processor;
  }

  /**
   * @param {string} input
   * @returns {string}
   */
  handleRequest(input) {
    const validated = this._processor.validate(input);
    if (!validated) {
      throw new Error('validation failed');
    }
    const result = this._processor.process(input);
    return FinalizeOutput.finalize(result);
  }
}
