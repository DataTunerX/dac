import { DiscountStrategy } from '../discount/DiscountStrategy';
import { Order } from '../models/Order';
import { OrderItem } from '../models/OrderItem';
import { OrderStatus } from '../models/OrderStatus';
import { Product } from '../models/Product';
import { PaymentGateway } from '../payment/PaymentGateway';
import { Repository } from '../repository/Repository';

/**
 * A transient shopping cart before conversion to an Order.
 * Checkout is the call-hierarchy centrepiece.
 */
export class Cart {
  private readonly items: OrderItem[] = [];

  constructor(private readonly userId: string) {}

  getUserId(): string {
    return this.userId;
  }

  getItems(): OrderItem[] {
    return this.items;
  }

  addProduct(product: Product, quantity: number): void {
    this.items.push(new OrderItem(product, quantity, product.getPrice()));
  }

  removeItem(index: number): void {
    if (index >= 0 && index < this.items.length) {
      this.items.splice(index, 1);
    }
  }

  cartTotal(): number {
    let total = 0;
    for (const item of this.items) {
      total += item.subtotal();
    }
    return total;
  }

  toOrder(orderId: string, discountCode: string | null): Order {
    return new Order(orderId, this.userId, [...this.items], discountCode);
  }

  /**
   * Full checkout pipeline — call-hierarchy centrepiece.
   * OutgoingCalls on checkout should list: toOrder, discount.apply, gateway.charge,
   * repo.saveOrder, repo.updateOrderStatus.
   */
  checkout(
    orderId: string,
    repo: Repository,
    gateway: PaymentGateway,
    discount: DiscountStrategy | null
  ): Order {
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
