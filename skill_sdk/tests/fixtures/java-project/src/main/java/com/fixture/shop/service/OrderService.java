package com.fixture.shop.service;

import java.util.List;

import com.fixture.shop.cart.Cart;
import com.fixture.shop.discount.DiscountStrategy;
import com.fixture.shop.discount.DiscountUtils;
import com.fixture.shop.models.Order;
import com.fixture.shop.models.OrderStatus;
import com.fixture.shop.payment.PaymentGateway;
import com.fixture.shop.repository.Repository;

/**
 * Facade over the checkout flow — top-level entry point for incomingCalls.
 */
public class OrderService {

    private final Repository repo;
    private final PaymentGateway gateway;
    private final List<DiscountStrategy> strategies;

    public OrderService(Repository repo, PaymentGateway gateway, List<DiscountStrategy> strategies) {
        this.repo = repo;
        this.gateway = gateway;
        this.strategies = strategies;
    }

    /**
     * Full order flow — outgoingCalls target.
     * Calls: cart.toOrder, DiscountUtils.applyBestDiscount, cart.checkout.
     */
    public Order placeOrder(Cart cart, String orderId) {
        if (!strategies.isEmpty()) {
            Order order = cart.toOrder(orderId, null);
            DiscountUtils.applyBestDiscount(order, strategies);
            return cart.checkout(orderId, repo, gateway, strategies.get(0));
        }
        return cart.checkout(orderId, repo, gateway, null);
    }

    /**
     * Cancel an order and update its status.
     * Calls: repo.getOrder, repo.updateOrderStatus.
     */
    public void cancelOrder(String orderId) {
        Order order = repo.getOrder(orderId);
        if (order == null) {
            return;
        }
        order.setStatus(OrderStatus.CANCELLED);
        repo.updateOrderStatus(orderId, OrderStatus.CANCELLED);
    }
}
