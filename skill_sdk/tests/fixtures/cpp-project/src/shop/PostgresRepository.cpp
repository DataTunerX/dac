#include "PostgresRepository.h"

PostgresRepository::PostgresRepository(const std::string& connStr) : connStr_(connStr) {}

bool PostgresRepository::SaveOrder(const Order& order) {
    orders_[order.OrderID] = order;
    return true;
}

Order PostgresRepository::GetOrder(const std::string& orderID) {
    auto it = orders_.find(orderID);
    return it != orders_.end() ? it->second : Order{};
}

bool PostgresRepository::UpdateOrderStatus(const std::string& orderID, OrderStatus status) {
    auto it = orders_.find(orderID);
    if (it == orders_.end()) return false;
    it->second.Status = status;
    return true;
}

Product PostgresRepository::GetProduct(const std::string& sku) {
    auto it = products_.find(sku);
    return it != products_.end() ? it->second : Product{};
}

std::vector<Order> PostgresRepository::ListOrdersByUser(const std::string& userID) {
    std::vector<Order> result;
    for (const auto& [_, order] : orders_) {
        if (order.UserID == userID)
            result.push_back(order);
    }
    return result;
}
