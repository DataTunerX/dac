# Routing Agent 过滤与选择逻辑（Simple 模式）

本文档描述 Routing Agent 在 Simple（单根）模式下，如何从广播返回的候选 Agent 中选出最终执行 Agent。

**入口函数**：`get_best_agent_by_broadcast()`

---

## 1. 整体流程概览

```
用户查询
  ↓
从注册中心获取所有 Agent
  ↓
广播 capability_check 给所有 Agent
  每个返回: can_handle, can_contribute, confidence, evidence_grade, score_version
  ↓（广播过程中完成第 1 层过滤 + 排序）
存活 agents 按 sort_key 降序排列
  ↓
截取 top 3 作为候选（MAX_SIMPLE_CANDIDATES = 3）
  ↓
候选数 == 1  →  直接委派（不做任何 LLM 调用）
候选数 >= 2  →  pre_make_plan：并发让每个候选独立生成 TaskList → 由 LLM 比较各 TaskList 选择最优
```

Simple 模式的设计目标：**永远返回一个单根 agent，从不拆多根**。选择机制聚焦于"哪个候选能产出最好的执行规划"。

---

## 2. 广播中的第 1 层过滤：0.5 门檻

**执行位置**：`broadcast_capability_check()` 方法内部，对每个 Agent 返回的 `capability_check` 响应执行。

**门檻**：`MIN_BROADCAST_CONFIDENCE`（默认 0.5）

### 过滤规则

| can_handle | can_contribute | chain-scored（score_version 非空） | 结果 |
|------------|---------------|-----------------------------------|------|
| ✅ | — | — | confidence ≥ 0.5 则保留 |
| ❌ | ✅ | ✅ | **无条件保留** |
| ❌ | ✅ | ❌ | confidence ≥ 0.5 则保留 |
| ❌ | ❌ | — | 丢弃 |

### 设计意图

- **handler 必须过 0.5**：确保"声称能做"不是低置信度瞎说的
- **chain-scored contributor 无条件保留**：其 confidence 是步骤分而非全链分，agent 侧已用自身 0.7 门檻 gate 过 can_contribute，routing 侧不应重复过滤
- **legacy contributor 也必须过 0.5**：legacy 没有步骤级拆解，confidence 仍是全链分

过滤后的 agent 按 `sort_key` 降序排列。

---

## 3. 排序规则 `sort_key`

三元组降序排列：

| 优先级 | 维度 | 规则 |
|--------|------|------|
| 第 1 | `can_handle` | 1 > 0，能独立完成的永远排前面 |
| 第 2 | `evidence_grade` | A=3 > B=2 > C=1 > D=0；legacy（无 evidence）映射为 B=2 |
| 第 3 | `confidence` | 浮点数直接比较 |

---

## 4. chain-scored 与 legacy 的区分

**判断依据**：skill-agent 响应中 `score_version` 字段是否非空。`"capability-chain-v1"` → chain-scored；空 → legacy。

对过滤的影响：

| 位置 | chain-scored | legacy |
|------|-------------|--------|
| 第 1 层 0.5 | contributor 跳过门槛 | contributor 必须过 0.5 |
| 排序 evidence | 按真实 A/B/C/D | 固定 B 级 |

---

## 5. 候选截取：top 3

排序后截取 `capable_agents[:3]` 作为候选（`MAX_SIMPLE_CANDIDATES = 3`）。sort_key 保证了 handlers 在 contributors 之前，也就是优先保证能独立完成的 agent 进入候选池。

---

## 6. 最终选择

### 候选数 == 1：直接委派

无需任何 LLM 调用，直接选中唯一的候选。无论它是 handler 还是 contributor。

### 候选数 ≥ 2：pre_make_plan

**这是 Simple 模式的核心选择机制。**

流程：
1. 并发给每个候选发送 `pre_make_plan` 请求——各 agent 独立执行自己的 planning，返回一个 `TaskList`（子任务列表、thought_process 等）
2. 收集所有候选的 TaskList
3. LLM 横向比较所有候选的计划质量，从覆盖度、合理性、自洽性、整体印象四个维度评估，选出最优

**优势**：不是只看 capability_check 返回的分数和标签，而是让各 agent 实际执行一次拆解规划（pre-make-plan），用真实产出的 TaskList 质量来决策。分数只是排队的依据，最终选择靠"实战"比较。

**LLM 比较的维度**：
- 覆盖度：计划是否覆盖了问题的核心需求
- 合理性：任务划分粒度是否合适
- 自洽性：子任务与 agent 的 description 是否匹配
- 整体印象：该计划是否高效准确

**失败保障**：如果 pre_make_plan 全部失败或 LLM 比较异常，回退到按排序取 `candidates[0]`。

---

## 7. evidence 的使用位置

`evidence_grade`（A/B/C/D）在 Simple 模式中有以下使用点：

| # | 位置 | 作用 |
|---|------|------|
| 1 | 排序 `sort_key` | 第二优先级：同等 can_handle 下 A > B > C > D |
| 2 | 候选截取 | 排序靠前的优先进入 top 3 候选池 |
| 3 | pre_make_plan 比较 | 候选的 evidence 信息随 description 注入 LLM 上下文，辅助评估 |

---

## 8. 四个核心条件在 Simple 模式中的角色

| 条件 | 在 Simple 模式中的角色 |
|------|----------------------|
| `can_handle` | 排序第一优先级，确保 handlers 优先入候选池；但不强制要求（contributor 也可进候选） |
| `can_contribute` | contributor 仍可进入候选池（经 0.5 门檻），有被 pre_make_plan 比较后选中的可能 |
| `confidence` | 排序第三优先级 + 0.5 门檻 |
| `evidence_grade` | 排序第二优先级，参与候选排序 |

---

## 9. Broadcast 模式对比

Broadcast 模式（`get_plan_by_broadcast`）独有的、Simple 模式**没有**的过滤层：

| Broadcast 独有过滤层 | Simple 替代 |
|---------------------|------------|
| 第 2 层分区 0.6（handlers/contributors 分流） | 不分区，统一进 top 3 |
| 第 3 层纯贡献者组合判断 | 无 |
| 第 4 层单根快速路径 0.78 | 候选 == 1 直接委派 |
| `_pick_dominant_single_root`（0.78 + evidence A/B + gap 0.15） | 不调用 |
| `_pick_best_root_for_fallback`（LLM 排名选择） | pre_make_plan（LLM 比较 TaskList） |
| `_plan_cross_root_tasks`（多根 LLM 规划） | 不调用，永远单根 |

---

## 10. 代码路径速查

| 文件 | 函数 | 职责 |
|------|------|------|
| `server.py` | `get_best_agent_by_broadcast` | Simple 模式入口，主流程 |
| `server.py` | `broadcast_capability_check` | 广播 + 第 1 层 0.5 过滤 + 排序 |
| `server.py` | `_select_by_pre_make_plan` | 并发 pre_make_plan + LLM 比较 TaskList 选最优 |
| `server.py` | `send_pre_make_plan` | 给单个 agent 发 pre_make_plan 请求 |
| `server.py` | `_llm_select_best_plan` | LLM 横向比较多个 agent 的 TaskList |
| `capability_select.py` | `keep_after_broadcast_threshold` | 第 1 层 0.5 判断 |
| `capability_select.py` | `sort_key` | 三元组排序规则 |
| `capability_select.py` | `is_chain_scored` | 判断 chain/legacy 模式 |
| `capability_select.py` | `evidence_rank` | A/B/C/D 映射 3/2/1/0 |