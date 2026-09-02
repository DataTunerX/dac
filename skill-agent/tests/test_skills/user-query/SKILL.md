---
name: user_query
description: 查询用户信息，包括用户ID、用户名、电话和邮箱。用户数据存储在 data/users.txt 文件中，格式为：用户ID|用户名|电话|邮箱。请使用 shell 命令（如 cat、grep、awk）从 data/ 目录读取数据，不依赖外部 API。
---

# 用户查询能力

## 数据来源
用户数据存储在 `data/users.txt` 文件中，每行一条记录，字段以 `|` 分隔：
- 字段1：用户ID（如 U001）
- 字段2：用户名
- 字段3：电话
- 字段4：邮箱

## 数据查询方式
- 读取全部用户：`cat data/users.txt`
- 按用户ID查询：`grep "U001" data/users.txt`
- 按用户名查询：`grep "张三" data/users.txt`
- 按邮箱查询：`grep "zhangsan@example.com" data/users.txt`
- 提取用户名列表：`awk -F'|' '{print $2}' data/users.txt`

## 支持的查询场景
1. 根据用户ID查询用户详细信息
2. 根据用户名查询用户信息
3. 根据邮箱查找用户
4. 列出所有用户
5. 统计用户总数

## 注意事项
- 用户数据中不包含订单信息
- 如需获取用户的订单数据，请使用 order_query 技能，传入用户ID即可
- 所有查询结果应直接返回给用户