#include "cart.h"
#include "DiscountStrategy.h"
#include "PaymentGateway.h"
#include "Repository.h"

#include <ctime>
#include <algorithm>

void Cart::AddProduct(const Product& product, int quantity) {
    Items.push_back({product, quantity, product.Price});
}

void Cart::RemoveItem(int index) {
    if (index >= 0 && static_cast<size_t>(index) < Items.size()) {
        Items.erase(Items.begin() + index);
    }
}

double Cart::CartTotal() const {
    double total = 0.0;
    for (const auto& item : Items) {
        total += item.Subtotal();
    }
    return total;
}

Order Cart::ToOrder(const std::string& orderID, const std::string& discountCode) const {
    return Order{
        orderID,
        UserID,
        Items,
        OrderStatus::Pending,
        std::time(nullptr),
        discountCode
    };
}

Order Cart::Checkout(
    const std::string& orderID,
    Repository& repo,
    PaymentGateway& gateway,
    DiscountStrategy* discount
) {
    auto order = ToOrder(orderID, "");

    double finalAmount = order.RawTotal();
    if (discount) {
        finalAmount = discount->Apply(order);
    }

    auto result = gateway.Charge(finalAmount, "USD");
    if (result.Success) {
        order.Status = OrderStatus::Paid;
    }

    repo.SaveOrder(order);
    repo.UpdateOrderStatus(order.OrderID, order.Status);
    return order;
}
