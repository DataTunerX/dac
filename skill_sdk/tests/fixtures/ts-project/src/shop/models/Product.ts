/**
 * A product available for purchase. Mirrors Product in the Java fixture.
 */
export class Product {
  constructor(
    private readonly sku: string,
    private readonly name: string,
    private readonly price: number,
    private readonly category: string,
    private stock: number
  ) {}

  getSku(): string {
    return this.sku;
  }

  getName(): string {
    return this.name;
  }

  getPrice(): number {
    return this.price;
  }

  getCategory(): string {
    return this.category;
  }

  getStock(): number {
    return this.stock;
  }

  setStock(stock: number): void {
    this.stock = stock;
  }

  isInStock(): boolean {
    return this.stock > 0;
  }
}
