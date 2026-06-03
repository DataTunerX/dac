import { PaymentResult } from './PaymentResult';

/**
 * Payment processing contract. goToImplementation should resolve to
 * StripeGateway, PayPalGateway, MockGateway.
 */
export interface PaymentGateway {
  charge(amount: number, currency: string): PaymentResult;
  refund(transactionId: string): PaymentResult;
}
