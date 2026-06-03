/**
 * Contract for pluggable discount calculation.
 * findReferences on DiscountStrategy should locate all implementors.
 *
 * @interface DiscountStrategy
 */
export class DiscountStrategy {
  /**
   * Apply the discount strategy to an order.
   * @param {import('../models/Order.js').Order} order
   * @returns {number}
   */
  apply(order) {
    throw new Error('Not implemented');
  }
}
