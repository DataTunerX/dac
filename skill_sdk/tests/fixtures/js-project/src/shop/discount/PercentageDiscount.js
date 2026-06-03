import { DiscountStrategy } from './DiscountStrategy.js';

/**
 * Applies a percentage off the raw total.
 *
 * @implements {DiscountStrategy}
 */
export class PercentageDiscount extends DiscountStrategy {
  /**
   * @param {number} percent
   */
  constructor(percent) {
    super();
    /** @type {number} */
    this._percent = percent;
  }

  /**
   * @param {import('../models/Order.js').Order} order
   * @returns {number}
   */
  apply(order) {
    return order.rawTotal() * (1.0 - this._percent / 100.0);
  }

  /** @returns {number} */
  getPercent() {
    return this._percent;
  }
}
