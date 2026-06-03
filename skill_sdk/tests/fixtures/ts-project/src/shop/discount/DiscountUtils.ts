import { DiscountStrategy } from './DiscountStrategy';
import { Order } from '../models/Order';

/**
 * Utility for applying multiple discount strategies.
 */
export class DiscountUtils {
  private constructor() {}

  /**
   * Tries several strategies and returns the lowest price.
   */
  static applyBestDiscount(order: Order, strategies: DiscountStrategy[]): number {
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
