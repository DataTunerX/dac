import { PaymentGateway } from './PaymentGateway.js';
import { PaymentResult } from './PaymentResult.js';

/**
 * Always-succeeds mock gateway for testing.
 *
 * @implements {PaymentGateway}
 */
export class MockGateway extends PaymentGateway {
  constructor() {
    super();
    /** @type {number} */
    this._callCount = 0;
  }

  /**
   * @param {number} amount
   * @param {string} currency
   * @returns {PaymentResult}
   */
  charge(amount, currency) {
    this._callCount++;
    return new PaymentResult(true, `mock_tx_${this._callCount}`, `Mock charge ${amount} ${currency}`);
  }

  /**
   * @param {string} transactionId
   * @returns {PaymentResult}
   */
  refund(transactionId) {
    return new PaymentResult(true, `mock_ref_${transactionId}`, `Mock refund ${transactionId}`);
  }

  /** @returns {number} */
  getCallCount() { return this._callCount; }
}
