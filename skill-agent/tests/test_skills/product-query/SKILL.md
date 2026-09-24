---
name: product_query
description: 查询商品静态本体：商品ID、名称、价格、分类、库存。数据在 data/products.txt，格式 商品ID|商品名称|价格|商品分类|库存数量。用 shell（cat/grep/awk）读 data/，不依赖外部 API。按商品ID或商品名称查询。不能按用户名、用户ID、订单号查询，不掌握谁买过、销量或订单状态。
---

# 商品查询能力

## 数据来源
商品数据存储在 `data/products.txt` 文件中，每行一条记录，字段以 `|` 分隔：
- 字段1：商品ID（如 PROD-001）
- 字段2：商品名称
- 字段3：价格（单位：元），即官方标价
- 字段4：商品分类
- 字段5：库存数量

## 输入 / 输出
- 输入：商品ID（PROD-xxx）或商品名称
- 输出：商品ID、名称、价格、分类、库存
- 没有：用户、订单、谁买过、销量、成交额

## 数据查询方式
- 读取全部商品：`cat data/products.txt`
- 按商品ID查询：`grep "PROD-001" data/products.txt`
- 按商品名称查询：`grep "iPhone 15 Pro" data/products.txt`
- 按商品分类查询：`grep "笔记本电脑" data/products.txt`
- 按价格区间筛选（价格 >= 5000）：`awk -F'|' '$3>=5000' data/products.txt`
- 按库存数量筛选（库存 <= 50）：`awk -F'|' '$5<=50' data/products.txt`

## 支持的查询场景
1. 根据商品ID查询名称、标价、分类、库存
2. 根据商品名称查询商品信息
3. 按分类、价格、库存筛选
4. 列出所有商品、统计数量

## 跨域规划（强制）
- 必须先有商品ID或明确的商品名称。用户名、用户ID、订单号都不是本技能的过滤键。
- 不要为了「某人买过什么」去读订单；那是 order_query 的职责。
- 一次查询可以带多个商品ID（如 PROD-001、PROD-003、PROD-016），返回各自的名称和标价即可。
