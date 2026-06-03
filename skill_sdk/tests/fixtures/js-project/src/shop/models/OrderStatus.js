/**
 * Possible states for an order. Mirrors OrderStatus in the Java fixture.
 *
 * @readonly
 * @enum {string}
 */
export const OrderStatus = Object.freeze({
  PENDING: 'PENDING',
  PAID: 'PAID',
  SHIPPED: 'SHIPPED',
  DELIVERED: 'DELIVERED',
  CANCELLED: 'CANCELLED',
});
