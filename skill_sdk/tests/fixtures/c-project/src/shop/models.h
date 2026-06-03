/*
 * models.h — e-commerce domain models.
 *
 * goToDefinition on Product/Order/OrderStatus resolves here.
 */
#ifndef MODELS_H
#define MODELS_H

typedef enum OrderStatus {
    ORDER_PENDING,
    ORDER_CONFIRMED,
    ORDER_SHIPPED,
    ORDER_DELIVERED,
    ORDER_CANCELLED,
} OrderStatus;

typedef struct Product {
    char id[32];
    char name[64];
    double price;
    char category[32];
    int stock;
} Product;

typedef struct OrderItem {
    Product product;
    int quantity;
} OrderItem;

typedef struct Order {
    char order_id[32];
    OrderItem items[10];
    int item_count;
    OrderStatus status;
    double raw_total_value;
} Order;

const char *order_status_string(OrderStatus s);

#endif /* MODELS_H */
