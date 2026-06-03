#include "models.h"

bool Product::IsInStock() const {
    return Stock > 0;
}

double OrderItem::Subtotal() const {
    return UnitPrice * Quantity;
}

double Order::RawTotal() const {
    double total = 0.0;
    for (const auto& item : Items) {
        total += item.Subtotal();
    }
    return total;
}

double Order::ApplyDiscount(double multiplier) const {
    return RawTotal() * multiplier;
}
