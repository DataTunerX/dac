import { PaymentGateway } from './PaymentGateway.js';
import { PaymentResult } from './PaymentResult.js';

/**
 * Stripe-backed payment gateway.
 *
 * @implements {PaymentGateway}
 */
export class StripeGateway extends PaymentGateway {
  /**
   * @param {string} apiKey
   */
  constructor(apiKey) {
    super();
    /** @type {string} */
    this._apiKey = apiKey;
  }

  /**
   * @param {number} amount
   * @param {string} currency
   * @returns {PaymentResult}
   */
  charge(amount, currency) {
    const txId = `stripe_ch_${this._hashFloat(amount)}`;
    return new PaymentResult(true, txId, `Charged ${amount} ${currency}`);
  }

  /**
   * @param {string} transactionId
   * @returns {PaymentResult}
   */
  refund(transactionId) {
    return new PaymentResult(
      true,
      `stripe_ref_${transactionId}`,
      `Refunded transaction ${transactionId}`
    );
  }

  /** @returns {string} */
  getApiKey() { return this._apiKey; }

  /**
   * @param {number} f
   * @returns {number}
   */
  _hashFloat(f) {
    return Math.floor(f * 100);
  }
}
