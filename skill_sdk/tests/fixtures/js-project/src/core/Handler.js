import { Helper } from './Helper.js';

/**
 * Processes incoming API requests. Mirrors Handler in the Java fixture.
 */
export class Handler {
  /**
   * @param {import('./DataProcessor.js').DataProcessor} processor
   */
  constructor(processor) {
    /** @type {import('./DataProcessor.js').DataProcessor} */
    this._processor = processor;
  }

  /**
   * @param {string} payload
   * @returns {string}
   */
  processRequest(payload) {
    console.log(`Processing request: ${payload}`);

    const helper = new Helper(this._processor);
    return helper.handleRequest(payload);
  }

  /**
   * @returns {boolean}
   */
  healthCheck() {
    return this._processor !== null;
  }
}
