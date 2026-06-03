import { Order } from '../models/Order.js';
import { OrderItem } from '../models/OrderItem.js';
import { OrderStatus } from '../models/OrderStatus.js';

/**
 * A transient shopping cart before conversion to an Order.
 * Checkout is the call-hierarchy centrepiece.
 */
export class Cart {
  /**
   * @param {string} userId
   */
  constructor(userId) {
    /** @type {string} */
    this._userId = userId;
    /** @type {import('../models/OrderItem.js').OrderItem[]} */
    this._items = [];
  }

  /** @returns {string} */
  getUserId() { return this._userId; }

  /** @returns {import('../models/OrderItem.js').OrderItem[]} */
  getItems() { return this._items; }

  /**
   * @param {import('../models/Product.js').Product} product
   * @param {number} quantity
   */
  addProduct(product, quantity) {
    this._items.push(new OrderItem(product, quantity, product.getPrice()));
  }

  /** @param {number} index */
  removeItem(index) {
    if (index >= 0 && index < this._items.length) {
      this._items.splice(index, 1);
    }
  }

  /** @returns {number} */
  cartTotal() {
    let total = 0;
    for (const item of this._items) {
      total += item.subtotal();
    }
    return total;
  }

  /**
   * @param {string} orderId
   * @param {string | null} discountCode
   * @returns {Order}
   */
  toOrder(orderId, discountCode) {
    return new Order(orderId, this._userId, [...this._items], discountCode);
  }

  /**
   * Full checkout pipeline — call-hierarchy centrepiece.
   * OutgoingCalls on checkout should list: toOrder, discount.apply, gateway.charge,
   * repo.saveOrder, repo.updateOrderStatus.
   *
   * @param {string} orderId
   * @param {import('../repository/Repository.js').Repository} repo
   * @param {import('../payment/PaymentGateway.js').PaymentGateway} gateway
   * @param {import('../discount/DiscountStrategy.js').DiscountStrategy | null} discount
   * @returns {Order}
   */
  checkout(orderId, repo, gateway, discount) {
    const order = this.toOrder(orderId, null);

    let finalAmount = order.rawTotal();
    if (discount) {
      finalAmount = discount.apply(order);
    }

    const result = gateway.charge(finalAmount, 'USD');
    if (result.isSuccess()) {
      order.setStatus(OrderStatus.PAID);
    }

    repo.saveOrder(order);
    repo.updateOrderStatus(order.getOrderId(), order.getStatus());
    return order;
  }
}
