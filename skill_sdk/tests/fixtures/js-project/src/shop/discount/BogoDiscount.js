import { DiscountStrategy } from './DiscountStrategy.js';

/**
 * Buy-one-get-one — cheapest item is free.
 *
 * @implements {DiscountStrategy}
 */
export class BogoDiscount extends DiscountStrategy {
  /**
   * @param {import('../models/Order.js').Order} order
   * @returns {number}
   */
  apply(order) {
    if (order.getItems().length < 2) {
      return order.rawTotal();
    }
    let cheapest = Number.MAX_VALUE;
    for (const item of order.getItems()) {
      if (item.subtotal() < cheapest) {
        cheapest = item.subtotal();
      }
    }
    return order.rawTotal() - cheapest;
  }
}
