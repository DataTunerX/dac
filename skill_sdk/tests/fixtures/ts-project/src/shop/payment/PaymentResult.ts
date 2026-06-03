/**
 * Outcome of a payment attempt.
 */
export class PaymentResult {
  constructor(
    private readonly success: boolean,
    private readonly transactionId: string,
    private readonly message: string
  ) {}

  isSuccess(): boolean {
    return this.success;
  }

  getTransactionId(): string {
    return this.transactionId;
  }

  getMessage(): string {
    return this.message;
  }
}
