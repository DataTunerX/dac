/**
 * A single line item within an order. Mirrors OrderItem in the Java fixture.
 */
export class OrderItem {
  /**
   * @param {import('./Product.js').Product} product
   * @param {number} quantity
   * @param {number} unitPrice
   */
  constructor(product, quantity, unitPrice) {
    /** @type {import('./Product.js').Product} */
    this._product = product;
    /** @type {number} */
    this._quantity = quantity;
    /** @type {number} */
    this._unitPrice = unitPrice;
  }

  /** @returns {import('./Product.js').Product} */
  getProduct() { return this._product; }

  /** @returns {number} */
  getQuantity() { return this._quantity; }

  /** @returns {number} */
  getUnitPrice() { return this._unitPrice; }

  /** @returns {number} */
  subtotal() {
    return this._unitPrice * this._quantity;
  }
}
