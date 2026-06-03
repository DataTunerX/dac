import { PaymentResult } from './PaymentResult.js';

/**
 * Payment processing contract. goToImplementation should resolve to
 * StripeGateway, PayPalGateway, MockGateway.
 *
 * @interface PaymentGateway
 */
export class PaymentGateway {
  /**
   * @param {number} amount
   * @param {string} currency
   * @returns {PaymentResult}
   */
  charge(amount, currency) {
    throw new Error('Not implemented');
  }

  /**
   * @param {string} transactionId
   * @returns {PaymentResult}
   */
  refund(transactionId) {
    throw new Error('Not implemented');
  }
}
