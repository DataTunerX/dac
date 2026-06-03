#!/bin/bash

# Table Ownership Index API 手测
# table → SG agent name 反向索引，用于跨 SG 数据主权路由。
# 返回格式：{"order_shipping": ["LogisticsSGAgent", ...], ...}

# 1. 获取完整 table-ownership-index

curl -X GET "http://192.168.3.238:22000/table-ownership-index" \
-H "Content-Type: application/json" | jq .

# output example:
# {
#   "status": "success",
#   "data": {
#     "order_shipping": ["LogisticsSGAgent", "LogisticsAgent-sg-xxx"],
#     "orders": ["EcommerceTransactionSGAgent"],
#     "products": ["ProductCatalogSGAgent"],
#     "categories": ["ProductCatalogSGAgent"],
#     "users": ["UserCenterSGAgent"],
#     "user_addresses": ["UserCenterSGAgent"],
#     "user_payment_methods": ["UserCenterSGAgent"],
#     "payment_records": ["EcommerceTransactionSGAgent"],
#     "order_items": ["EcommerceTransactionSGAgent"],
#     "inventory_logs": ["ProductCatalogSGAgent"],
#     "product_images": ["ProductCatalogSGAgent"]
#   },
#   "count": 11
# }