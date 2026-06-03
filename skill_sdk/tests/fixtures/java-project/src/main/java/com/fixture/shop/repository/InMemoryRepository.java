package com.fixture.shop.repository;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.fixture.shop.models.Order;
import com.fixture.shop.models.OrderStatus;
import com.fixture.shop.models.Product;

/**
 * In-memory implementation of Repository.
 */
public class InMemoryRepository implements Repository {

    private final Map<String, Order> orders = new HashMap<>();
    private final Map<String, Product> products = new HashMap<>();

    @Override
    public void saveOrder(Order order) {
        orders.put(order.getOrderId(), order);
    }

    @Override
    public Order getOrder(String orderId) {
        return orders.get(orderId);
    }

    @Override
    public void updateOrderStatus(String orderId, OrderStatus status) {
        Order order = orders.get(orderId);
        if (order != null) {
            order.setStatus(status);
        }
    }

    @Override
    public Product getProduct(String sku) {
        return products.get(sku);
    }

    @Override
    public List<Order> listOrdersByUser(String userId) {
        List<Order> result = new ArrayList<>();
        for (Order order : orders.values()) {
            if (order.getUserId().equals(userId)) {
                result.add(order);
            }
        }
        return result;
    }
}
