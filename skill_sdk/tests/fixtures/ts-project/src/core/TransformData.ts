/**
 * Applies transformation rules to raw data. Mirrors TransformData in the Java fixture.
 */
export class TransformData {
  private constructor() {}

  static transform(data: string): string {
    return `processed: ${data}`;
  }
}
