---
name: product_query
description: 查询商品数据。支持按商品ID、商品名称、商品分类、价格区间进行查询和筛选。商品数据存储在 data/products.txt 文件中，格式为：商品ID|商品名称|价格|商品分类|库存数量。请使用 shell 命令（如 cat、grep、awk）从 data/ 目录读取数据，不依赖外部 API。如需获取某商品的订单销售情况，请使用 order_query 技能按商品ID查询。
---

# 商品查询能力

## 数据来源
商品数据存储在 `data/products.txt` 文件中，每行一条记录，字段以 `|` 分隔：
- 字段1：商品ID（如 PROD-001）
- 字段2：商品名称
- 字段3：价格（单位：元）
- 字段4：商品分类
- 字段5：库存数量

## 数据查询方式
- 读取全部商品：`cat data/products.txt`
- 按商品ID查询：`grep "PROD-001" data/products.txt`
- 按商品名称查询：`grep "iPhone 15 Pro" data/products.txt`
- 按商品分类查询：`grep "笔记本电脑" data/products.txt`
- 按价格区间筛选（价格 >= 5000）：`awk -F'|' '$3>=5000' data/products.txt`
- 按价格区间筛选（价格 <= 1000）：`awk -F'|' '$3<=1000' data/products.txt`
- 按库存数量筛选（库存 <= 50）：`awk -F'|' '$5<=50' data/products.txt`
- 提取商品名称列表：`awk -F'|' '{print $2}' data/products.txt`
- 统计商品总数：`cat data/products.txt | wc -l`
- 计算某分类商品的平均价格：`grep "笔记本电脑" data/products.txt | awk -F'|' '{sum+=$3; count++} END {if(count>0) print sum/count}'`

## 支持的查询场景
1. 根据商品ID查询商品详细信息
2. 根据商品名称查询商品信息
3. 按商品分类筛选商品列表
4. 按价格区间筛选商品
5. 按库存数量筛选商品（低库存预警）
6. 列出所有商品
7. 统计各分类商品数量
8. 查询某分类下最贵的商品

## 跨技能关联
- 商品数据中不包含订单信息，只包含商品本身的信息
- **如需获取某商品的订单销售情况**，请使用 `order_query` 技能，传入商品ID（如 PROD-001）进行查询
- 商品ID 与 order_query 中订单数据里的商品ID 完全一致，可作为关联字段

## 注意事项
- 所有查询结果应直接返回给用户