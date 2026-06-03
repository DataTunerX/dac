import { DiscountStrategy } from './DiscountStrategy.js';

/**
 * Subtracts a fixed amount from the total (floored at zero).
 *
 * @implements {DiscountStrategy}
 */
export class FixedAmountDiscount extends DiscountStrategy {
  /**
   * @param {number} amount
   */
  constructor(amount) {
    super();
    /** @type {number} */
    this._amount = amount;
  }

  /**
   * @param {import('../models/Order.js').Order} order
   * @returns {number}
   */
  apply(order) {
    return Math.max(0, order.rawTotal() - this._amount);
  }

  /** @returns {number} */
  getAmount() {
    return this._amount;
  }
}
