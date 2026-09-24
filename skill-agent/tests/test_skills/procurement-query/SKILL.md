---
name: procurement_query
description: 查询采购订单：采购单号、供应商、物料/商品ID、采购数量、单价、交货日期、采购状态、目标仓库ID。数据在 data/purchase_orders.txt，格式 采购单号|供应商|物料ID|采购数量|单价|交货日期|采购状态|仓库ID。用 shell（cat/grep/awk）读 data/。按采购单号、供应商、物料ID、状态、仓库ID过滤。不含零售标价、当前库存量、销售订单、合同条款全文。只读，不能下单、收货或改交期。
---

# 采购订单查询能力

## 数据来源
采购单存储在 `data/purchase_orders.txt` 文件中，每日凌晨同步，每行一条记录，字段以 `|` 分隔：
- 字段1：采购单号（如 PO-001）
- 字段2：供应商名称
- 字段3：物料/商品ID（如 PROD-001 或 MAT-201）
- 字段4：采购数量
- 字段5：采购单价（元，进货价，不是零售标价）
- 字段6：计划交货日期（YYYY-MM-DD）
- 字段7：采购状态（草稿 / 已下单 / 在途 / 部分入库 / 已入库 / 已取消）
- 字段8：目标仓库ID（如 WH-001）

## 输入 / 输出
- 输入：采购单号、供应商、物料/商品ID、采购状态、仓库ID、交货日期范围
- 输出：采购单号、供应商、物料ID、数量、进货单价、交货日期、状态、仓库ID
- 没有：零售标价、商品名称、当前库存量、安全阈值；销售订单号、用户；运单轨迹；合同正文条款；发票认证状态

## 数据查询方式
- 读取全部采购单：`cat data/purchase_orders.txt`
- 按采购单号：`grep "PO-001" data/purchase_orders.txt`
- 按供应商：`grep "华储电子" data/purchase_orders.txt`
- 按物料ID：`grep "PROD-001" data/purchase_orders.txt`
- 在途采购：`grep "在途" data/purchase_orders.txt`
- 按仓库汇总在途数量：`awk -F'|' '$7=="在途" {sum[$8]+=$4} END {for (w in sum) print w, sum[w]}' data/purchase_orders.txt`
- 允许工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 按采购单号查详情
2. 按供应商列出采购单
3. 按物料ID查未到货数量
4. 按仓库查在途采购
5. 汇总采购金额或数量

## 跨域规划（强制）
- 当前仓库存量属于 **inventory_query**，本技能只有采购数量与在途状态，不是现存量。
- 商务合同金额/到期日属于 **contract_query**；物流派送轨迹属于 **logistics_query**。
- 只读。不能创建采购单、确认收货、变更交期或取消采购。
