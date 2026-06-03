import { PaymentGateway } from './PaymentGateway';
import { PaymentResult } from './PaymentResult';

/**
 * Always-succeeds mock gateway for testing.
 */
export class MockGateway implements PaymentGateway {
  private callCount = 0;

  charge(amount: number, currency: string): PaymentResult {
    this.callCount++;
    return new PaymentResult(true, `mock_tx_${this.callCount}`, `Mock charge ${amount} ${currency}`);
  }

  refund(transactionId: string): PaymentResult {
    return new PaymentResult(true, `mock_ref_${transactionId}`, `Mock refund ${transactionId}`);
  }

  getCallCount(): number {
    return this.callCount;
  }
}
