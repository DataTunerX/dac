#include "BogoDiscount.h"

double BogoDiscount::Apply(const Order& order) {
    if (order.Items.size() < 2) {
        return order.RawTotal();
    }
    double cheapest = order.Items[0].Subtotal();
    for (const auto& item : order.Items) {
        double s = item.Subtotal();
        if (s < cheapest) {
            cheapest = s;
        }
    }
    return order.RawTotal() - cheapest;
}
