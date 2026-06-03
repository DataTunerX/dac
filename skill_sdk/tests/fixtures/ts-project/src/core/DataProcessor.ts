/**
 * Defines the contract for processing data.
 * Analogous to the DataProcessor interface in the Java fixture.
 */
export interface DataProcessor {
  process(data: string): string;
  validate(data: string): boolean;
}
