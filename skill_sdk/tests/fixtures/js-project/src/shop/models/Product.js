/**
 * A product available for purchase. Mirrors Product in the Java fixture.
 */
export class Product {
  /**
   * @param {string} sku
   * @param {string} name
   * @param {number} price
   * @param {string} category
   * @param {number} stock
   */
  constructor(sku, name, price, category, stock) {
    /** @type {string} */
    this._sku = sku;
    /** @type {string} */
    this._name = name;
    /** @type {number} */
    this._price = price;
    /** @type {string} */
    this._category = category;
    /** @type {number} */
    this._stock = stock;
  }

  /** @returns {string} */
  getSku() { return this._sku; }

  /** @returns {string} */
  getName() { return this._name; }

  /** @returns {number} */
  getPrice() { return this._price; }

  /** @returns {string} */
  getCategory() { return this._category; }

  /** @returns {number} */
  getStock() { return this._stock; }

  /** @param {number} stock */
  setStock(stock) { this._stock = stock; }

  /** @returns {boolean} */
  isInStock() {
    return this._stock > 0;
  }
}
