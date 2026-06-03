#include "OrderService.h"

OrderService::OrderService(Repository& repo, PaymentGateway& gateway,
                           std::vector<DiscountStrategy*> strategies)
    : repo_(repo), gateway_(gateway), strategies_(std::move(strategies)) {}

Order OrderService::PlaceOrder(Cart& cart, const std::string& orderID) {
    if (!strategies_.empty()) {
        auto order = cart.ToOrder(orderID, "");
        return cart.Checkout(orderID, repo_, gateway_, strategies_[0]);
    }
    return cart.Checkout(orderID, repo_, gateway_, nullptr);
}

bool OrderService::CancelOrder(const std::string& orderID) {
    auto order = repo_.GetOrder(orderID);
    if (order.OrderID.empty()) return false;

    order.Status = OrderStatus::Cancelled;
    return repo_.UpdateOrderStatus(orderID, OrderStatus::Cancelled);
}
