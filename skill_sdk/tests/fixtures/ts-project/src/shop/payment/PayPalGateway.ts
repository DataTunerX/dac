import { PaymentGateway } from './PaymentGateway';
import { PaymentResult } from './PaymentResult';

/**
 * PayPal-backed payment gateway.
 */
export class PayPalGateway implements PaymentGateway {
  constructor(
    private readonly clientId: string,
    private readonly clientSecret: string
  ) {}

  charge(amount: number, currency: string): PaymentResult {
    const txId = `pp_ch_${this.hashFloat(amount)}`;
    return new PaymentResult(true, txId, `PayPal charge ${amount} ${currency}`);
  }

  refund(transactionId: string): PaymentResult {
    return new PaymentResult(
      true,
      `pp_ref_${transactionId}`,
      `PayPal refund ${transactionId}`
    );
  }

  private hashFloat(f: number): number {
    return Math.floor(f * 100);
  }
}
