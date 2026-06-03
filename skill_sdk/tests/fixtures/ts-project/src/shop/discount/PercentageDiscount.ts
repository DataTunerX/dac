import { DiscountStrategy } from './DiscountStrategy';
import { Order } from '../models/Order';

/**
 * Applies a percentage off the raw total.
 */
export class PercentageDiscount implements DiscountStrategy {
  constructor(private readonly percent: number) {}

  apply(order: Order): number {
    return order.rawTotal() * (1.0 - this.percent / 100.0);
  }

  getPercent(): number {
    return this.percent;
  }
}
