export class TdbError extends Error {
  public readonly code: string;
  public readonly statusCode: number;
  public readonly details?: unknown;

  constructor(code: string, statusCode: number, message: string, details?: unknown) {
    super(message);
    this.name = 'TdbError';
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

export type ErrorResponse = {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
};
