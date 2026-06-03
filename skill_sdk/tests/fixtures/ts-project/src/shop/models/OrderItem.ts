import { Product } from './Product';

/**
 * A single line item within an order. Mirrors OrderItem in the Java fixture.
 */
export class OrderItem {
  constructor(
    private readonly product: Product,
    private readonly quantity: number,
    private readonly unitPrice: number
  ) {}

  getProduct(): Product {
    return this.product;
  }

  getQuantity(): number {
    return this.quantity;
  }

  getUnitPrice(): number {
    return this.unitPrice;
  }

  subtotal(): number {
    return this.unitPrice * this.quantity;
  }
}
