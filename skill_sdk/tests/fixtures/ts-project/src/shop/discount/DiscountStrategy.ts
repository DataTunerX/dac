import { Order } from '../models/Order';

/**
 * Contract for pluggable discount calculation.
 * findReferences on DiscountStrategy should locate all implementors.
 */
export interface DiscountStrategy {
  apply(order: Order): number;
}
