import { OrderStatus } from './OrderStatus.js';

/**
 * A customer order. Mirrors Order in the Java fixture.
 */
export class Order {
  /**
   * @param {string} orderId
   * @param {string} userId
   * @param {import('./OrderItem.js').OrderItem[]} items
   * @param {string | null} discountCode
   */
  constructor(orderId, userId, items, discountCode) {
    /** @type {string} */
    this._orderId = orderId;
    /** @type {string} */
    this._userId = userId;
    /** @type {import('./OrderItem.js').OrderItem[]} */
    this._items = items;
    /** @type {string} */
    this._status = OrderStatus.PENDING;
    /** @type {Date} */
    this._createdAt = new Date();
    /** @type {string | null} */
    this._discountCode = discountCode;
  }

  /** @returns {string} */
  getOrderId() { return this._orderId; }

  /** @returns {string} */
  getUserId() { return this._userId; }

  /** @returns {import('./OrderItem.js').OrderItem[]} */
  getItems() { return this._items; }

  /** @returns {string} */
  getStatus() { return this._status; }

  /** @param {string} status */
  setStatus(status) { this._status = status; }

  /** @returns {Date} */
  getCreatedAt() { return this._createdAt; }

  /** @returns {string | null} */
  getDiscountCode() { return this._discountCode; }

  /** @param {string} discountCode */
  setDiscountCode(discountCode) { this._discountCode = discountCode; }

  /** @returns {number} */
  rawTotal() {
    let total = 0;
    for (const item of this._items) {
      total += item.subtotal();
    }
    return total;
  }

  /**
   * @param {number} multiplier
   * @returns {number}
   */
  applyDiscount(multiplier) {
    return this.rawTotal() * multiplier;
  }
}
