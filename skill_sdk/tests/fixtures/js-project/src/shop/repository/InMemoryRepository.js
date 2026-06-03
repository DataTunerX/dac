import { Repository } from './Repository.js';

/**
 * In-memory implementation of Repository.
 *
 * @implements {Repository}
 */
export class InMemoryRepository extends Repository {
  constructor() {
    super();
    /** @type {Map<string, import('../models/Order.js').Order>} */
    this._orders = new Map();
    /** @type {Map<string, import('../models/Product.js').Product>} */
    this._products = new Map();
  }

  /** @param {import('../models/Order.js').Order} order */
  saveOrder(order) {
    this._orders.set(order.getOrderId(), order);
  }

  /**
   * @param {string} orderId
   * @returns {import('../models/Order.js').Order | undefined}
   */
  getOrder(orderId) {
    return this._orders.get(orderId);
  }

  /**
   * @param {string} orderId
   * @param {string} status
   */
  updateOrderStatus(orderId, status) {
    const order = this._orders.get(orderId);
    if (order) {
      order.setStatus(status);
    }
  }

  /**
   * @param {string} sku
   * @returns {import('../models/Product.js').Product | undefined}
   */
  getProduct(sku) {
    return this._products.get(sku);
  }

  /**
   * @param {string} userId
   * @returns {import('../models/Order.js').Order[]}
   */
  listOrdersByUser(userId) {
    const result = [];
    for (const order of this._orders.values()) {
      if (order.getUserId() === userId) {
        result.push(order);
      }
    }
    return result;
  }
}
