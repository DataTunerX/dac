/**
 * Outcome of a payment attempt.
 */
export class PaymentResult {
  /**
   * @param {boolean} success
   * @param {string} transactionId
   * @param {string} message
   */
  constructor(success, transactionId, message) {
    /** @type {boolean} */
    this._success = success;
    /** @type {string} */
    this._transactionId = transactionId;
    /** @type {string} */
    this._message = message;
  }

  /** @returns {boolean} */
  isSuccess() { return this._success; }

  /** @returns {string} */
  getTransactionId() { return this._transactionId; }

  /** @returns {string} */
  getMessage() { return this._message; }
}
