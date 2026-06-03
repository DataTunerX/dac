import { Repository } from './Repository';
import { Order } from '../models/Order';
import { OrderStatus } from '../models/OrderStatus';
import { Product } from '../models/Product';

/**
 * In-memory implementation of Repository.
 */
export class InMemoryRepository implements Repository {
  private readonly orders: Map<string, Order> = new Map();
  private readonly products: Map<string, Product> = new Map();

  saveOrder(order: Order): void {
    this.orders.set(order.getOrderId(), order);
  }

  getOrder(orderId: string): Order | undefined {
    return this.orders.get(orderId);
  }

  updateOrderStatus(orderId: string, status: OrderStatus): void {
    const order = this.orders.get(orderId);
    if (order) {
      order.setStatus(status);
    }
  }

  getProduct(sku: string): Product | undefined {
    return this.products.get(sku);
  }

  listOrdersByUser(userId: string): Order[] {
    const result: Order[] = [];
    for (const order of this.orders.values()) {
      if (order.getUserId() === userId) {
        result.push(order);
      }
    }
    return result;
  }
}
