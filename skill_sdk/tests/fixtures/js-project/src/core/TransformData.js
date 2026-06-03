/**
 * Applies transformation rules to raw data. Mirrors TransformData in the Java fixture.
 */
export class TransformData {
  constructor() {
    throw new Error('Utility class — do not instantiate');
  }

  /**
   * @param {string} data
   * @returns {string}
   */
  static transform(data) {
    return `processed: ${data}`;
  }
}
