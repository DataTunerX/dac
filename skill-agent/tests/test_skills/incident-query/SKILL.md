---
name: incident_query
description: 查询 IT 运维告警与服务指标：告警ID、服务名、级别、状态、指标名、指标值、发生时间、处理人；以及 CPU/内存/错误率/QPS 时序。数据在 data/incidents.txt 与 data/metrics.txt。用 shell（cat/grep/awk）读 data/。按告警ID、服务名、级别、状态过滤。不覆盖业务订单/GMV、用户账号、应用代码性能剖析、安全入侵检测、数据库慢 SQL 原文。只读，不能静默告警或变更配置。
---

# IT 告警与指标查询能力

## 数据来源
1. 告警列表 `data/incidents.txt`，每行一条，字段以 `|` 分隔：
   - 字段1：告警ID（如 INC-001）
   - 字段2：服务名（如 order-svc）
   - 字段3：级别（P1 / P2 / P3 / P4）
   - 字段4：状态（触发中 / 处理中 / 已恢复 / 已关闭）
   - 字段5：指标名（错误率 / 延迟P99 / CPU / 内存 / 连接数 / 慢查询数）
   - 字段6：指标值（带单位的文本，如 `12.4%`、`95`）
   - 字段7：发生时间（YYYY-MM-DD HH:MM:SS）
   - 字段8：处理人
2. 服务指标快照 `data/metrics.txt`，每行一条，字段以 `|` 分隔：
   - 字段1：时间戳
   - 字段2：服务名
   - 字段3：CPU%
   - 字段4：内存%
   - 字段5：错误率%
   - 字段6：QPS

指标与告警来自监控系统，约 1 分钟粒度，非应用日志原文。

## 输入 / 输出
- 输入：告警ID、服务名、级别、状态、时间范围
- 输出：告警记录（含级别/状态/指标/处理人）；服务在某时刻的 CPU/内存/错误率/QPS
- 没有：业务订单量、GMV、转化率；用户账号与订单；应用代码/火焰图；安全 WAF/入侵事件；MySQL 慢查询 SQL 原文；变更单与发布记录

## 数据查询方式
- 读取全部告警：`cat data/incidents.txt`
- 按告警ID：`grep "INC-001" data/incidents.txt`
- 按服务名：`grep "order-svc" data/incidents.txt`
- 按级别：`grep "P1" data/incidents.txt`
- 未恢复告警：`awk -F'|' '$4=="触发中" || $4=="处理中"' data/incidents.txt`
- 某服务指标：`grep "order-svc" data/metrics.txt`
- 错误率高于阈值：`awk -F'|' '$5>5' data/metrics.txt`
- 允许工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 查询某条告警详情
2. 列出某服务最近告警
3. 筛选 P1/P2 或未恢复告警
4. 查看某服务 CPU/内存/错误率/QPS 趋势
5. 统计各服务告警数量

## 跨域规划（强制）
- 「order-svc 告警」是本域；「订单金额 / 谁买了什么」不是本域，交给 **order_query**。
- 不覆盖安全攻击研判、慢 SQL 文本、发布回滚。
- 只读。不能静默/关闭告警、改阈值、重启服务或提交变更。
