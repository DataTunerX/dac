/**
 * Storage contract. goToImplementation on Repository should resolve to
 * InMemoryRepository and PostgresRepository.
 *
 * @interface Repository
 */
export class Repository {
  /**
   * @param {import('../models/Order.js').Order} order
   */
  saveOrder(order) {
    throw new Error('Not implemented');
  }

  /**
   * @param {string} orderId
   * @returns {import('../models/Order.js').Order | undefined}
   */
  getOrder(orderId) {
    throw new Error('Not implemented');
  }

  /**
   * @param {string} orderId
   * @param {string} status
   */
  updateOrderStatus(orderId, status) {
    throw new Error('Not implemented');
  }

  /**
   * @param {string} sku
   * @returns {import('../models/Product.js').Product | undefined}
   */
  getProduct(sku) {
    throw new Error('Not implemented');
  }

  /**
   * @param {string} userId
   * @returns {import('../models/Order.js').Order[]}
   */
  listOrdersByUser(userId) {
    throw new Error('Not implemented');
  }
}
