import { OrderItem } from './OrderItem';
import { OrderStatus } from './OrderStatus';

/**
 * A customer order. Mirrors Order in the Java fixture.
 */
export class Order {
  private readonly createdAt: Date;
  private status: OrderStatus;
  private discountCode: string | null;

  constructor(
    private readonly orderId: string,
    private readonly userId: string,
    private readonly items: OrderItem[],
    discountCode: string | null
  ) {
    this.status = OrderStatus.PENDING;
    this.createdAt = new Date();
    this.discountCode = discountCode;
  }

  getOrderId(): string {
    return this.orderId;
  }

  getUserId(): string {
    return this.userId;
  }

  getItems(): OrderItem[] {
    return this.items;
  }

  getStatus(): OrderStatus {
    return this.status;
  }

  setStatus(status: OrderStatus): void {
    this.status = status;
  }

  getCreatedAt(): Date {
    return this.createdAt;
  }

  getDiscountCode(): string | null {
    return this.discountCode;
  }

  setDiscountCode(discountCode: string): void {
    this.discountCode = discountCode;
  }

  rawTotal(): number {
    let total = 0;
    for (const item of this.items) {
      total += item.subtotal();
    }
    return total;
  }

  applyDiscount(multiplier: number): number {
    return this.rawTotal() * multiplier;
  }
}
