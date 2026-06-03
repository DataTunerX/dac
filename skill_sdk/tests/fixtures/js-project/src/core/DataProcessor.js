/**
 * Defines the contract for processing data.
 * Analogous to the DataProcessor interface in the Java fixture.
 *
 * @interface DataProcessor
 */
export class DataProcessor {
  /**
   * Process raw data and return the processed result.
   * @param {string} data
   * @returns {string}
   */
  process(data) {
    throw new Error('Not implemented');
  }

  /**
   * Validate whether the given data can be processed.
   * @param {string} data
   * @returns {boolean}
   */
  validate(data) {
    throw new Error('Not implemented');
  }
}
