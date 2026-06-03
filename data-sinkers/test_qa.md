基于你提供的三个数据库模块（用户、商品、订单），我为你生成了以下多模块关联查询问题。这些问题都至少覆盖2个模块，难度从易到难排列。

---

### 📦 模块覆盖说明
- **用户 + 订单**：查询用户及其订单信息
- **用户 + 商品**：查询用户与商品的关系（通常通过订单关联）
- **商品 + 订单**：查询商品与订单的关系
- **用户 + 订单 + 商品**：三模块联合查询

---

### 问题列表

#### 🟢 简单级别

**1. 查询每个用户的订单总数和消费总额**
- 覆盖模块：用户 + 订单
- 涉及表：`user_management.users`、`order_management.orders`
- 业务场景：统计所有用户的订单数量和总消费金额

**2. 查询ORD-2025-00001订单编号的购买用户的全部详细信息和支付记录**
- 覆盖模块：用户 + 订单
- 涉及表：`user_management.users`、`order_management.orders`、`order_management.payment_records`
- 业务场景：查看订单"ORD-2025-00001"的购买者的详细信息和支付情况

**3. 查询每个商品的总销售数量和销售总额，要包含商品的一些具体信息**
- 覆盖模块：商品 + 订单
- 涉及表：`product_management.products`、`order_management.order_items`
- 业务场景：统计商品的销售情况

**4. 查询使用了"ALIPAY"支付的用户及对应订单，要包含用户的具体信息**
- 覆盖模块：用户 + 订单
- 涉及表：`user_management.users`、`order_management.orders`、`order_management.payment_records`
- 业务场景：找出所有使用支付宝支付的用户和订单，要包含用户的详细信息

---

#### 🟡 中等级别

**5. 查询张三这个用户的默认收货地址及该地址的订单发货情况**
- 覆盖模块：用户 + 订单
- 涉及表：`user_management.users`、`user_management.user_addresses`、`order_management.orders`、`order_management.order_shipping`
- 业务场景：分析用户默认地址与订单发货状态的关系

**6. 查询购买了Apple品牌商品的用户详细信息及订单详情**
- 覆盖模块：用户 + 商品 + 订单
- 涉及表：`user_management.users`、`product_management.products`、`order_management.orders`、`order_management.order_items`
- 业务场景：找出所有购买Apple产品的用户及其订单信息

**7. 查询库存变化记录中涉及销售的商品及对应订单的支付状态**
- 覆盖模块：商品 + 订单
- 涉及表：`product_management.products`、`product_management.inventory_logs`、`order_management.order_items`、`order_management.orders`、`order_management.payment_records`
- 业务场景：关联库存销售变动与订单支付状态

**8. 查询北京用户购买的商品分布（分组统计）**
- 覆盖模块：用户 + 商品 + 订单
- 涉及表：`user_management.user_addresses`、`order_management.orders`、`order_management.order_items`、`product_management.products`
- 业务场景：分析不同城市用户的品牌偏好

---

#### 🔴 高级别

**9. 查询超期未发货订单的购买用户及其支付方式信息，超期范围是最近3天以内创建的**
- 覆盖模块：用户 + 订单
- 涉及表：`user_management.users`、`user_management.user_payment_methods`、`order_management.orders`、`order_management.order_shipping`
- 业务场景：找出预计送达日期已过但仍未发货的订单，并获取用户默认支付方式


**10. 统计各省份用户在不同商品品类的消费金额排名**
- 覆盖模块：用户 + 商品 + 订单（三模块联合）
- 涉及表：`user_management.user_addresses`、`order_management.orders`、`order_management.order_items`、`product_management.products`、`product_management.categories`
- 业务场景：按省份统计各品类的销售情况，支持地域化营销分析

