---
name: order_query
description: 查询订单数据。支持按订单号、订单状态、商品ID、用户ID进行查询和筛选。订单数据存储在 data/orders.txt 文件中，格式为：订单号|订单状态|商品ID|用户ID。请使用 shell 命令（如 cat、grep、awk）从 data/ 目录读取数据，不依赖外部 API。如需获取商品名称、价格、分类等详细信息，请使用 product_query 技能按商品ID查询。
---

# 订单查询能力

## 数据来源
订单数据存储在 `data/orders.txt` 文件中，每行一条记录，字段以 `|` 分隔：
- 字段1：订单号（如 ORD-001）
- 字段2：订单状态（待支付、待发货、已发货、已完成、已取消）
- 字段3：商品ID（如 PROD-001）
- 字段4：用户ID（如 U001）

## 数据查询方式
- 读取全部订单：`cat data/orders.txt`
- 按订单号查询：`grep "ORD-001" data/orders.txt`
- 按用户ID查询：`grep "U001" data/orders.txt`
- 按商品ID查询：`grep "PROD-001" data/orders.txt`
- 按订单状态查询：`grep "已发货" data/orders.txt`
- 统计某用户的订单数量：`grep "U001" data/orders.txt | wc -l`
- 统计某商品的订单数量：`grep "PROD-001" data/orders.txt | wc -l`

## 支持的查询场景
1. 查询某个用户的全部订单
2. 查询某个订单的详细信息
3. 按订单状态筛选订单
4. 按商品ID查询订单
5. 统计用户的订单数量
6. 列出所有订单状态

## 跨技能关联
- 订单数据中只包含商品ID，不包含商品名称、价格、分类等详细信息
- **如需获取商品详细信息（名称、价格、分类、库存）**，请使用 `product_query` 技能，传入商品ID进行查询
- 订单数据中只包含用户ID，不包含用户姓名、电话等个人信息
- **如需获取用户详细信息**，请使用 `user_query` 技能，传入用户ID进行查询

## 注意事项
- 所有查询结果应直接返回给用户，不要做额外的数据脱敏