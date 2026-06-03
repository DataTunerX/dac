import { Order } from '../models/Order';
import { OrderStatus } from '../models/OrderStatus';
import { Product } from '../models/Product';

/**
 * Storage contract. goToImplementation on Repository should resolve to
 * InMemoryRepository and PostgresRepository.
 */
export interface Repository {
  saveOrder(order: Order): void;
  getOrder(orderId: string): Order | undefined;
  updateOrderStatus(orderId: string, status: OrderStatus): void;
  getProduct(sku: string): Product | undefined;
  listOrdersByUser(userId: string): Order[];
}
