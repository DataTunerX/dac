/**
 * Configuration for processors. Mirrors ProcessorConfig in the Java fixture.
 */
export class ProcessorConfig {
  /**
   * @param {number} timeout
   * @param {number} retries
   */
  constructor(timeout, retries) {
    /** @type {number} */
    this._timeout = timeout;
    /** @type {number} */
    this._retries = retries;
  }

  /**
   * @returns {number}
   */
  getTimeout() {
    return this._timeout;
  }

  /**
   * @returns {number}
   */
  getRetries() {
    return this._retries;
  }
}
