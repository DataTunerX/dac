import { PaymentGateway } from './PaymentGateway';
import { PaymentResult } from './PaymentResult';

/**
 * Stripe-backed payment gateway.
 */
export class StripeGateway implements PaymentGateway {
  constructor(private readonly apiKey: string) {}

  charge(amount: number, currency: string): PaymentResult {
    const txId = `stripe_ch_${this.hashFloat(amount)}`;
    return new PaymentResult(true, txId, `Charged ${amount} ${currency}`);
  }

  refund(transactionId: string): PaymentResult {
    return new PaymentResult(
      true,
      `stripe_ref_${transactionId}`,
      `Refunded transaction ${transactionId}`
    );
  }

  getApiKey(): string {
    return this.apiKey;
  }

  private hashFloat(f: number): number {
    return Math.floor(f * 100);
  }
}
