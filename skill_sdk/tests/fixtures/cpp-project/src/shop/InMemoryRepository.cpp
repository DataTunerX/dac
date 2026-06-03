#include "InMemoryRepository.h"

InMemoryRepository::InMemoryRepository() {}

bool InMemoryRepository::SaveOrder(const Order& order) {
    orders_[order.OrderID] = order;
    return true;
}

Order InMemoryRepository::GetOrder(const std::string& orderID) {
    auto it = orders_.find(orderID);
    return it != orders_.end() ? it->second : Order{};
}

bool InMemoryRepository::UpdateOrderStatus(const std::string& orderID, OrderStatus status) {
    auto it = orders_.find(orderID);
    if (it == orders_.end()) return false;
    it->second.Status = status;
    return true;
}

Product InMemoryRepository::GetProduct(const std::string& sku) {
    auto it = products_.find(sku);
    return it != products_.end() ? it->second : Product{};
}

std::vector<Order> InMemoryRepository::ListOrdersByUser(const std::string& userID) {
    std::vector<Order> result;
    for (const auto& [_, order] : orders_) {
        if (order.UserID == userID)
            result.push_back(order);
    }
    return result;
}
