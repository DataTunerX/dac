#pragma once

#include "Repository.h"

#include <unordered_map>

/**
 * InMemoryRepository is an in-memory implementation of Repository.
 * goToImplementation should list this class when invoked from Repository.
 */
class InMemoryRepository : public Repository {
public:
    InMemoryRepository();

    bool SaveOrder(const Order& order) override;
    Order GetOrder(const std::string& orderID) override;
    bool UpdateOrderStatus(const std::string& orderID, OrderStatus status) override;
    Product GetProduct(const std::string& sku) override;
    std::vector<Order> ListOrdersByUser(const std::string& userID) override;

private:
    std::unordered_map<std::string, Order> orders_;
    std::unordered_map<std::string, Product> products_;
};
