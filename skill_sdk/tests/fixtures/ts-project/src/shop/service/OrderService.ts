import { Cart } from '../cart/Cart';
import { DiscountStrategy } from '../discount/DiscountStrategy';
import { DiscountUtils } from '../discount/DiscountUtils';
import { Order } from '../models/Order';
import { OrderStatus } from '../models/OrderStatus';
import { PaymentGateway } from '../payment/PaymentGateway';
import { Repository } from '../repository/Repository';

/**
 * Facade over the checkout flow — top-level entry point for incomingCalls.
 */
export class OrderService {
  constructor(
    private readonly repo: Repository,
    private readonly gateway: PaymentGateway,
    private readonly strategies: DiscountStrategy[]
  ) {}

  /**
   * Full order flow — outgoingCalls target.
   * Calls: cart.toOrder, DiscountUtils.applyBestDiscount, cart.checkout.
   */
  placeOrder(cart: Cart, orderId: string): Order {
    if (this.strategies.length > 0) {
      const order = cart.toOrder(orderId, null);
      DiscountUtils.applyBestDiscount(order, this.strategies);
      return cart.checkout(orderId, this.repo, this.gateway, this.strategies[0]);
    }
    return cart.checkout(orderId, this.repo, this.gateway, null);
  }

  /**
   * Cancel an order and update its status.
   * Calls: repo.getOrder, repo.updateOrderStatus.
   */
  cancelOrder(orderId: string): void {
    const order = this.repo.getOrder(orderId);
    if (!order) {
      return;
    }
    order.setStatus(OrderStatus.CANCELLED);
    this.repo.updateOrderStatus(orderId, OrderStatus.CANCELLED);
  }
}
