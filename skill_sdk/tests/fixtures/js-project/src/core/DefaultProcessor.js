import { DataProcessor } from './DataProcessor.js';
import { TransformData } from './TransformData.js';

/**
 * Primary implementation of DataProcessor. Mirrors DefaultProcessor in the Java fixture.
 *
 * @implements {DataProcessor}
 */
export class DefaultProcessor extends DataProcessor {
  /**
   * @param {{ getTimeout(): number; getRetries(): number }} config
   */
  constructor(config) {
    super();
    /** @type {{ getTimeout(): number; getRetries(): number }} */
    this._config = config;
  }

  /**
   * @returns {{ getTimeout(): number; getRetries(): number }}
   */
  getConfig() {
    return this._config;
  }

  /**
   * @param {string} data
   * @returns {string}
   */
  process(data) {
    if (!this.validate(data)) {
      throw new Error(`invalid data: ${data}`);
    }
    return TransformData.transform(data);
  }

  /**
   * @param {string} data
   * @returns {boolean}
   */
  validate(data) {
    return data !== null && data !== undefined && data.length > 0 && data.length < 1024;
  }
}
