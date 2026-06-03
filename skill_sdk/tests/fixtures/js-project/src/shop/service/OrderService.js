import { DiscountUtils } from '../discount/DiscountUtils.js';
import { OrderStatus } from '../models/OrderStatus.js';

/**
 * Facade over the checkout flow — top-level entry point for incomingCalls.
 */
export class OrderService {
  /**
   * @param {import('../repository/Repository.js').Repository} repo
   * @param {import('../payment/PaymentGateway.js').PaymentGateway} gateway
   * @param {import('../discount/DiscountStrategy.js').DiscountStrategy[]} strategies
   */
  constructor(repo, gateway, strategies) {
    /** @type {import('../repository/Repository.js').Repository} */
    this._repo = repo;
    /** @type {import('../payment/PaymentGateway.js').PaymentGateway} */
    this._gateway = gateway;
    /** @type {import('../discount/DiscountStrategy.js').DiscountStrategy[]} */
    this._strategies = strategies;
  }

  /**
   * Full order flow — outgoingCalls target.
   * Calls: cart.toOrder, DiscountUtils.applyBestDiscount, cart.checkout.
   *
   * @param {import('../cart/Cart.js').Cart} cart
   * @param {string} orderId
   * @returns {import('../models/Order.js').Order}
   */
  placeOrder(cart, orderId) {
    if (this._strategies.length > 0) {
      const order = cart.toOrder(orderId, null);
      DiscountUtils.applyBestDiscount(order, this._strategies);
      return cart.checkout(orderId, this._repo, this._gateway, this._strategies[0]);
    }
    return cart.checkout(orderId, this._repo, this._gateway, null);
  }

  /**
   * Cancel an order and update its status.
   * Calls: repo.getOrder, repo.updateOrderStatus.
   *
   * @param {string} orderId
   */
  cancelOrder(orderId) {
    const order = this._repo.getOrder(orderId);
    if (!order) {
      return;
    }
    order.setStatus(OrderStatus.CANCELLED);
    this._repo.updateOrderStatus(orderId, OrderStatus.CANCELLED);
  }
}
