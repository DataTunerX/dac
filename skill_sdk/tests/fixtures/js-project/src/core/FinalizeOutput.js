/**
 * Applies post-processing to the result. Mirrors FinalizeOutput in the Java fixture.
 */
export class FinalizeOutput {
  constructor() {
    throw new Error('Utility class — do not instantiate');
  }

  /**
   * @param {string} data
   * @returns {string}
   */
  static finalize(data) {
    return `[final] ${data} [ok]`;
  }
}
