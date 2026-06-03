import { DiscountStrategy } from './DiscountStrategy';
import { Order } from '../models/Order';
import { OrderItem } from '../models/OrderItem';

/**
 * Buy-one-get-one — cheapest item is free.
 */
export class BogoDiscount implements DiscountStrategy {
  apply(order: Order): number {
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
