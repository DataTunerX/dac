package com.fixture.shop.repository;

import java.util.List;

import com.fixture.shop.models.Order;
import com.fixture.shop.models.OrderStatus;
import com.fixture.shop.models.Product;

/**
 * Storage contract. goToImplementation on Repository should resolve to
 * InMemoryRepository and PostgresRepository.
 */
public interface Repository {

    void saveOrder(Order order);

    Order getOrder(String orderId);

    void updateOrderStatus(String orderId, OrderStatus status);

    Product getProduct(String sku);

    List<Order> listOrdersByUser(String userId);
}
