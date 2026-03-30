# DAC 完整流程：单层 SG 模型

本文档描述在“只有一层 SG，且每个 SG 同时是 root 和 leaf”前提下，从用户 query 到实际查询数据表的完整链路。

---

## 一、架构总览

```text
用户 Query
    │
    ▼
Routing Agent
    - 广播 capability_check 到所有 SG Orchestrator
    - 选择单个 SG，或执行 multi_root 跨 SG 拆分
    │
    ▼
SG Orchestrator
    - 不再递归下钻 child_groups
    - 不再按多跳 route_path 转发
    - 本地调用 own sg expert (+ 可选 utility agents)
    │
    ▼
SG Expert
    - 基于 members 做组内 phase 规划
    - A2A 调用多个 sd agent
    │
    ▼
SD Orchestrator
    - 通常退化为单 agent fast path
    - 转给本地 sd expert
    │
    ▼
SD Expert
    - 检索知识、生成 SQL、执行数据库查询
```

---

## 二、各角色职责

### 1. Routing Agent

| 属性 | 说明 |
|------|------|
| **注册来源** | `orchestrator_agent_cards`，所有 SG 都视为 root |
| **能力检查** | `broadcast_capability_check` 并行探测所有 SG |
| **规划结果** | 单 root 直接转发，或执行 `multi_root` 跨 SG 拆分 |
| **不做什么** | 不再依赖 SG 树内路径，不再把 `multi_child` 传给下游 |

**代码位置**: `dac/routing-agent/routing_agent/server.py`

### 2. SG Orchestrator

| 属性 | 说明 |
|------|------|
| **角色** | 每个 SG 的统一入口，同时也是最终业务组执行节点 |
| **capability_check** | 只评估当前 SG 是否能处理当前 query |
| **执行** | 始终走本地 planner + own expert，不再递归子 SG |
| **不做什么** | 不再使用 `child_groups`、`_forward_by_route_path`、`multi_child` |

**代码位置**: `dac/orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py`

### 3. SG Expert

| 属性 | 说明 |
|------|------|
| **数据来源** | `semantic_groups/{id}/with_members` 返回 `members`，`child_groups` 恒为空 |
| **规划** | 保留现有 `_plan_execution_order` phase 规划 |
| **执行** | A2A 调用多个 `sd` agent，汇总组内知识 |

**代码位置**: `dac/expert-agent/agent/expert_agent_semantic_group.py`

### 4. SD Orchestrator

| 属性 | 说明 |
|------|------|
| **角色** | `sd` 层薄编排器 |
| **执行** | 典型情况下只有本地 own expert，直接分发 |

**代码位置**: `dac/orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_domain.py`

### 5. SD Expert

| 属性 | 说明 |
|------|------|
| **角色** | 真正的数据执行与知识检索单元 |
| **能力** | `get_knowledge`、`invoke_structured`、`execute_db_query` |

**代码位置**: `dac/expert-agent/agent/expert_agent_semantic_domain.py`

---

## 三、端到端数据流

示例 query：

```text
查一下各支行 2024 年零售贷款余额和同比增长
```

| 步骤 | 组件 | 动作 |
|------|------|------|
| 1 | Routing Agent | 广播 `capability_check` 到所有 SG Orchestrator |
| 2 | Routing Agent | 选中最匹配的 SG，或执行 `multi_root` 拆分 |
| 3 | SG Orchestrator | 本地执行，不再向子 SG 转发 |
| 4 | SG Orchestrator | `get_plan -> a2a_tasks`，调用本组 `sg expert` |
| 5 | SG Expert | 基于 `members` 做 phase 规划，调用 `sd` agent |
| 6 | SD Orchestrator | 转给本地 `sd expert` |
| 7 | SD Expert | 检索 schema/样本数据，生成 SQL，并执行数据库查询 |
| 8 | SG Orchestrator | 汇总下游结果，流式返回用户答案 |
| 9 | Routing Agent | 如果是 `multi_root`，再做跨 SG 聚合；否则直接透传 |

---

## 四、数据契约变化

### SemanticGroup

- `parent_id` 保留为兼容字段，但单层 SG 模式下恒为 `null`
- `child_groups` 保留为兼容字段，但 `with_members` 返回中恒为 `[]`
- `/semantic_groups_roots` 语义退化为“所有 SG”
- `/semantic_groups/{id}/children` 语义退化为恒空列表

### Capability Check

- `route_path` / `route_paths` 仅表示当前 SG 的兼容路径信息
- `execution_strategy` 在 SG 侧只返回 `single`
- `multi_root` 仅存在于 `routing-agent` 的跨 SG 规划中
- `multi_child` 已删除，不再作为运行时策略

---

## 五、能力边界总结

| 角色 | 规划 | 转发 | 调用 Expert | 执行 SQL |
|------|------|------|-------------|----------|
| Routing Agent | 选 SG / `multi_root` | 发 SG | ❌ | ❌ |
| SG Orchestrator | 组入口规划 | ❌ | `sg expert` | ❌ |
| SG Expert | `sd` phase 规划 | A2A 到 `sd` | ✓ | ❌ |
| SD Orchestrator | 轻量转发 | 发 `sd expert` | ✓ | ❌ |
| SD Expert | SQL/知识规划 | ❌ | ❌ | ✓ |

“查询数据表”能力只在 `SD Expert` 中落地，通过 `execute_db_query` 调用数据库执行器完成。
