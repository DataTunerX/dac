import { Cart } from './shop/cart/Cart';
import { PercentageDiscount } from './shop/discount/PercentageDiscount';
import { Product } from './shop/models/Product';
import { StripeGateway } from './shop/payment/StripeGateway';
import { InMemoryRepository } from './shop/repository/InMemoryRepository';
import { Repository } from './shop/repository/Repository';
import { OrderService } from './shop/service/OrderService';

/**
 * E-commerce wiring class — exercises the full shop subpackage so the TypeScript
 * LSP indexes all symbols, references, and call chains.
 */
export class FixtureApp {
  private constructor() {}

  /**
   * Wires and runs the e-commerce demo flow.
   */
  static demoShopRun(): string {
    const repo: Repository = new InMemoryRepository();
    const gateway = new StripeGateway('sk_test_fixture');

    const laptop = new Product('LAP-001', 'Laptop Pro', 1299.99, 'electronics', 10);
    const mouse = new Product('MOU-001', 'Wireless Mouse', 29.99, 'electronics', 50);

    const cart = new Cart('user_fixture_001');
    cart.addProduct(laptop, 1);
    cart.addProduct(mouse, 2);

    const discount = new PercentageDiscount(10);

    const svc = new OrderService(repo, gateway, [discount]);
    const order = svc.placeOrder(cart, 'ORD-0001');

    return `[done] order=${order.getOrderId()} total=${order.rawTotal().toFixed(2)} status=${order.getStatus()}`;
  }
}
