package com.fixture.shop.cart;

import java.util.ArrayList;
import java.util.List;

import com.fixture.shop.discount.DiscountStrategy;
import com.fixture.shop.models.Order;
import com.fixture.shop.models.OrderItem;
import com.fixture.shop.models.OrderStatus;
import com.fixture.shop.models.Product;
import com.fixture.shop.payment.PaymentGateway;
import com.fixture.shop.repository.Repository;

/**
 * A transient shopping cart before conversion to an Order.
 * Checkout is the call-hierarchy centrepiece.
 */
public class Cart {

    private final String userId;
    private final List<OrderItem> items = new ArrayList<>();

    public Cart(String userId) {
        this.userId = userId;
    }

    public String getUserId() {
        return userId;
    }

    public List<OrderItem> getItems() {
        return items;
    }

    public void addProduct(Product product, int quantity) {
        items.add(new OrderItem(product, quantity, product.getPrice()));
    }

    public void removeItem(int index) {
        if (index >= 0 && index < items.size()) {
            items.remove(index);
        }
    }

    public double cartTotal() {
        double total = 0;
        for (OrderItem item : items) {
            total += item.subtotal();
        }
        return total;
    }

    public Order toOrder(String orderId, String discountCode) {
        return new Order(orderId, userId, new ArrayList<>(items), discountCode);
    }

    /**
     * Full checkout pipeline — call-hierarchy centrepiece.
     * OutgoingCalls on checkout should list: toOrder, discount.apply, gateway.charge,
     * repo.saveOrder, repo.updateOrderStatus.
     */
    public Order checkout(
            String orderId,
            Repository repo,
            PaymentGateway gateway,
            DiscountStrategy discount) {
        Order order = toOrder(orderId, null);

        double finalAmount = order.rawTotal();
        if (discount != null) {
            finalAmount = discount.apply(order);
        }

        var result = gateway.charge(finalAmount, "USD");
        if (result.isSuccess()) {
            order.setStatus(OrderStatus.PAID);
        }

        repo.saveOrder(order);
        repo.updateOrderStatus(order.getOrderId(), order.getStatus());
        return order;
    }
}
