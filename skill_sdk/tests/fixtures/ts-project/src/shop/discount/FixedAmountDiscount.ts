import { DiscountStrategy } from './DiscountStrategy';
import { Order } from '../models/Order';

/**
 * Subtracts a fixed amount from the total (floored at zero).
 */
export class FixedAmountDiscount implements DiscountStrategy {
  constructor(private readonly amount: number) {}

  apply(order: Order): number {
    return Math.max(0, order.rawTotal() - this.amount);
  }

  getAmount(): number {
    return this.amount;
  }
}
