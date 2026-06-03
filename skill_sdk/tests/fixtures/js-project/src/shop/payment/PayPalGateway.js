import { PaymentGateway } from './PaymentGateway.js';
import { PaymentResult } from './PaymentResult.js';

/**
 * PayPal-backed payment gateway.
 *
 * @implements {PaymentGateway}
 */
export class PayPalGateway extends PaymentGateway {
  /**
   * @param {string} clientId
   * @param {string} clientSecret
   */
  constructor(clientId, clientSecret) {
    super();
    /** @type {string} */
    this._clientId = clientId;
    /** @type {string} */
    this._clientSecret = clientSecret;
  }

  /**
   * @param {number} amount
   * @param {string} currency
   * @returns {PaymentResult}
   */
  charge(amount, currency) {
    const txId = `pp_ch_${this._hashFloat(amount)}`;
    return new PaymentResult(true, txId, `PayPal charge ${amount} ${currency}`);
  }

  /**
   * @param {string} transactionId
   * @returns {PaymentResult}
   */
  refund(transactionId) {
    return new PaymentResult(
      true,
      `pp_ref_${transactionId}`,
      `PayPal refund ${transactionId}`
    );
  }

  /**
   * @param {number} f
   * @returns {number}
   */
  _hashFloat(f) {
    return Math.floor(f * 100);
  }
}
