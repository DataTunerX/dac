package com.fixture;

import java.util.List;

import com.fixture.shop.cart.Cart;
import com.fixture.shop.discount.PercentageDiscount;
import com.fixture.shop.models.Product;
import com.fixture.shop.payment.StripeGateway;
import com.fixture.shop.repository.InMemoryRepository;
import com.fixture.shop.repository.Repository;
import com.fixture.shop.service.OrderService;

/**
 * E-commerce wiring class — exercises the full shop subpackage so Eclipse JDT LS / jdtls
 * indexes all symbols, references, and call chains.
 */
public final class FixtureApp {

    private FixtureApp() {
    }

    /**
     * Wires and runs the e-commerce demo flow.
     */
    public static String demoShopRun() {
        Repository repo = new InMemoryRepository();
        var gateway = new StripeGateway("sk_test_fixture");

        Product laptop = new Product("LAP-001", "Laptop Pro", 1299.99, "electronics", 10);
        Product mouse = new Product("MOU-001", "Wireless Mouse", 29.99, "electronics", 50);

        Cart cart = new Cart("user_fixture_001");
        cart.addProduct(laptop, 1);
        cart.addProduct(mouse, 2);

        var discount = new PercentageDiscount(10);

        OrderService svc = new OrderService(repo, gateway, List.of(discount));
        var order = svc.placeOrder(cart, "ORD-0001");

        return String.format("[done] order=%s total=%.2f status=%s",
                order.getOrderId(), order.rawTotal(), order.getStatus().name());
    }
}
