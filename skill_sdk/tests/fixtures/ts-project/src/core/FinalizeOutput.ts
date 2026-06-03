/**
 * Applies post-processing to the result. Mirrors FinalizeOutput in the Java fixture.
 */
export class FinalizeOutput {
  private constructor() {}

  static finalize(data: string): string {
    return `[final] ${data} [ok]`;
  }
}
