/**
 * Utility for applying multiple discount strategies.
 */
export class DiscountUtils {
  constructor() {
    throw new Error('Utility class — do not instantiate');
  }

  /**
   * Tries several strategies and returns the lowest price.
   *
   * @param {import('../models/Order.js').Order} order
   * @param {import('./DiscountStrategy.js').DiscountStrategy[]} strategies
   * @returns {number}
   */
  static applyBestDiscount(order, strategies) {
    let best = order.rawTotal();
    for (const s of strategies) {
      const value = s.apply(order);
      if (value < best) {
        best = value;
      }
    }
    return best;
  }
}
