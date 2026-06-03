#pragma once

#include "Repository.h"

#include <string>
#include <unordered_map>

/**
 * PostgresRepository is a simulated postgres-backed implementation.
 */
class PostgresRepository : public Repository {
public:
    explicit PostgresRepository(const std::string& connStr);

    bool SaveOrder(const Order& order) override;
    Order GetOrder(const std::string& orderID) override;
    bool UpdateOrderStatus(const std::string& orderID, OrderStatus status) override;
    Product GetProduct(const std::string& sku) override;
    std::vector<Order> ListOrdersByUser(const std::string& userID) override;

private:
    std::string connStr_;
    std::unordered_map<std::string, Order> orders_;
    std::unordered_map<std::string, Product> products_;
};
