#pragma once

#include "models.h"

#include <string>
#include <vector>

/**
 * Repository defines the storage contract.
 * goToImplementation on Repository should resolve to InMemoryRepository, PostgresRepository.
 */
class Repository {
public:
    virtual ~Repository() = default;

    virtual bool SaveOrder(const Order& order) = 0;
    virtual Order GetOrder(const std::string& orderID) = 0;
    virtual bool UpdateOrderStatus(const std::string& orderID, OrderStatus status) = 0;
    virtual Product GetProduct(const std::string& sku) = 0;
    virtual std::vector<Order> ListOrdersByUser(const std::string& userID) = 0;
};
