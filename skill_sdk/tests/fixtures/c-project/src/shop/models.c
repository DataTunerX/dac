/*
 * models.c — e-commerce domain models implementation.
 */
#include "models.h"

const char *order_status_string(OrderStatus s) {
    switch (s) {
        case ORDER_PENDING:    return "pending";
        case ORDER_CONFIRMED:  return "confirmed";
        case ORDER_SHIPPED:    return "shipped";
        case ORDER_DELIVERED:  return "delivered";
        case ORDER_CANCELLED:  return "cancelled";
        default:               return "unknown";
    }
}
