# SG Orchestrator Execution Flow 集成方案

> **版本**: v4.0  
> **日期**: 2026-09-07  
> **状态**: 设计阶段，待评审  
> **核心理念**: Execution Flow 是分布式多智能体协作的**执行状态地图**  
> **参考**: skill-agent 已有方案 → `EXECUTION_FLOW_DESIGN.md`  
> **本次更新**: 所有插入点标注精确行号 + 可用变量 + 代码上下文

---

## 1. 问题定义

### 1.1 分布式协作中的核心痛点

在多智能体分布式协作中，每个智能体独立执行自己的任务，但**彼此之间不知道对方做了什么**：

```
用户请求 → SG Orchestrator (order 域)
              │
              ├─ 自己执行 order_query → 失败（缺少用户ID）
              │
              └─ 委派给 user-agent（可能是 skill-agent 或另一个 SG Orchestrator）
                    │
                    └─ user-agent 执行 user_query → 成功，返回 U003

问题：user-agent 不知道 order-agent 已经尝试过查询、为什么失败、需要什么关联键。
      order-agent 的 Planner 在 mid-exec 规划时，也不知道之前的执行细节。
```

### 1.2 Execution Flow 的解决方案

**Execution Flow 是一张随执行流动的分布式状态地图**：

- 每个 agent 执行后，将自己的执行记录追加到地图上
- 委派时，将**完整的地图**传递给下游 agent
- 下游 agent 的 Planner 看到地图后，知道"已经做了什么、结果是什么、还缺什么"
- 上游 agent 收回委派结果时，合并下游 agent 的地图更新

```
用户请求 → SG Orchestrator (order)  [地图: {order_query: 失败}]
              │
              │ 委派时传递完整地图
              ↓
         user-agent (SG Orchestrator)  [地图: {order_query: 失败} + {user_query: 成功}]
              │
              │ 返回结果 + 更新后的地图
              ↓
         SG Orchestrator (order)  [地图: {order_query: 失败, user_query: 成功}]
              │
              │ Planner 看到地图后，知道"order_query 失败、user_query 返回 U003"
              │ → 规划补充查询：用 U003 重新查询订单
              └─ 自己执行 order_query(U003) → 成功

              [地图: {order_query: 失败, user_query: 成功, order_query(U003): 成功}]
```

### 1.3 SG Orchestrator 与 skill-agent 的协作关系

SG Orchestrator 和 skill-agent 是**同一注册中心中的对等智能体**，处于同一水平层级：

- **SG Orchestrator**：侧重处理内部数据（数据库查询、API 调用、内部业务逻辑）
- **skill-agent**：侧重处理外部 skill（文件操作、shell 命令、外部工具调用）

两者在同一个注册中心中，**可以互相发现、互相委派**。协作关系是**双向对等**的：

```
┌─────────────────────────────────────────────────────────────────┐
│                    同一注册中心 (Agent Registry)                 │
│                                                                 │
│  ┌─────────────────────┐          ┌─────────────────────┐       │
│  │   SG Orchestrator   │ ←─A2A──→ │    skill-agent      │       │
│  │   (内部数据智能体)   │  双向委派  │   (外部skill智能体)  │       │
│  └─────────────────────┘          └─────────────────────┘       │
│           ↕ A2A                          ↕ A2A                  │
│  ┌─────────────────────┐          ┌─────────────────────┐       │
│  │   SG Orchestrator   │          │    skill-agent      │       │
│  │   (另一个 SG)        │          │    (另一个 skill)   │       │
│  └─────────────────────┘          └─────────────────────┘       │
│                                                                 │
│  Execution Flow 状态地图在所有这些智能体之间双向流动               │
└─────────────────────────────────────────────────────────────────┘
```

**关键特性**：
- SG Orchestrator 可以委派给 skill-agent（如"请帮我执行这个 shell 命令"）
- skill-agent 也可以委派给 SG Orchestrator（如"请帮我查一下这个用户的数据"）
- 两者之间的委派都通过 A2A 协议，Execution Flow 帧在两者之间统一传输
- 两者的 Planner 都需要看到 Execution Flow 状态地图来做决策

---

## 2. 设计原则

### 2.1 核心原则

1. **EF 是状态地图，不是日志**：首要用途是注入 Planner 的 `group_memory`，次要用途是日志输出
2. **EF 随委派流动**：每次委派（无论是给 skill-agent 还是 peer SG），都传递完整地图
3. **EF 统一协议**：SG Orchestrator 和 skill-agent 使用相同的 EF 协议（`[[DAC_EXECUTION_FLOW]]` 帧 + A2A artifact）
4. **EF 增量更新**：每个 agent 在地图上追加自己的执行记录，不修改上游记录
5. **复用 `execution_flow.py`**：不做任何修改，只通过 import 使用

### 2.2 与 skill-agent 的对比

| 维度 | skill-agent | SG Orchestrator |
|------|-------------|-----------------|
| **角色** | 外部 skill 智能体（文件操作、shell、工具调用） | 内部数据智能体（数据库查询、API 调用、业务逻辑） |
| **关系** | 与 SG Orchestrator 对等，同一注册中心，双向协作 | 与 skill-agent 对等，同一注册中心，双向协作 |
| **执行模型** | Turn Loop（plan → execute → evaluate → repeat） | 单次执行（plan → execute sequentially → mid-exec → summarize） |
| **Turn 概念** | 多 Turn（Turn 1/2/3...） | 单 Turn（Turn 1），但 Legacy 路径有重试 |
| **委派对象** | 对等 skill-agent + 对等 SG Orchestrator | 对等 SG Orchestrator + 对等 skill-agent（作为 expert） |
| **EF 已集成** | ✅ 完整集成 | ❌ 零集成 |
| **EF 注入点** | `_build_turn_context_md` → `group_memory` | `_enrich_group_memory_with_upstream` → `group_memory` |

---

## 3. 执行状态地图模型

### 3.1 地图结构

Execution Flow 状态地图由一系列 `ExecutionTask` 节点组成，按时间线组织：

```
Turn 1
├── pre_exec
│   ├── own task 完成      ← 记录：谁、做了什么、结果、为什么
│   └── delegate task 完成  ← 记录：委派给谁、结果、为什么
│       └── peer 内部执行   ← 记录：被委派方的内部执行过程
├── mid_exec_round_1
│   ├── own task 完成      ← 记录：检测到缺口后自己补充执行
│   └── delegate task 完成  ← 记录：检测到缺口后委派给谁
│       └── peer 内部执行
├── mid_exec_round_2
│   └── ...
└── Turn 1 总结            ← 记录：本轮是否满足需求

最终答案                   ← 记录：最终汇总
```

### 3.2 地图的流动

```
┌─────────────────────────────────────────────────────────────────┐
│  Execution Flow 状态地图的流动路径                                │
│                                                                 │
│  1. 初始化：入口 agent 创建空地图                                │
│                                                                 │
│  2. 本地执行后：追加自己的执行记录到地图                          │
│                                                                 │
│  3. 委派时：将完整地图序列化，放入 upstream_context["execution_flow"]│
│     → 传递给下游 agent                                          │
│                                                                 │
│  4. 接收端：从 upstream_context["execution_flow"] 反序列化地图    │
│     → prepend 到本地地图（上游记录在前，本地记录在后）            │
│                                                                 │
│  5. 下游执行后：追加自己的记录到地图                              │
│                                                                 │
│  6. 返回时：下游 agent 的地图随 A2A 响应返回（通过 EF 帧）       │
│     → 上游 agent 合并下游的更新（只合并新记录，不重复）           │
│                                                                 │
│  7. Planner 上下文：渲染地图为 Markdown，注入 group_memory       │
│                                                                 │
│  8. 最终输出：渲染地图为 Markdown，输出到日志                    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 地图的关键特性

- **完整性**：任一节点看到的地图，包含从根到当前节点的完整执行历史
- **增量性**：每个 agent 只追加自己的记录，不修改上游记录
- **层级性**：通过 `parent_execution_id` 表达委派关系（A 委派 B，B 的任务是 A 的任务的子节点）
- **可追溯**：通过 `run_id`、`trace_id`、`user_id` 关联到具体请求和用户

---

## 4. 插入点设计（精确行号 + 可用变量）

### 4.1 总览

SG Orchestrator 需要在以下位置插入 Execution Flow 逻辑。**每个插入点都标注了精确的代码行号和可用变量**。

```
execute_collaborative() [Cross-SG 路径，约 6554 行]
│
├─ 【Entry】入口：接收上游 EF 地图（第 6571 行之后）
│   可用：upstream_context, sg_label, is_delegated, run_id, trace_id, user_id
│
├─ Phase 2: Plan（第 6752 行 + 第 7586 行）
│   └─ 【Inject】注入 EF 地图到 group_memory（_enrich_group_memory_with_upstream 第 6392 行）
│
├─ Phase 3: 执行 plan tasks（第 6860 行开始）
│   ├─ Own task（第 6938 行）
│   │   └─ 【Point A】own task 完成后追加 EF 记录（第 6940 行之后）
│   │       可用：t (PlannerTask), agent_name, result, run_id, trace_id, user_id
│   │   └─ 【Point A-expert】_execute_own_task_via_expert 内部收集 expert EF（第 7880 行）
│   │       可用：task, agent_card, updater, send_payload (metadata 含 upstream_context)
│   │
│   └─ Delegate task（第 7125 行）
│       └─ 【Point B】delegate 完成后追加 EF 记录（第 7138 行之后）
│           可用：t (PlannerTask), agent_name, _target_card, _task_desc_for_delegate, result
│       └─ 【Point B-peer】delegate_to_collaborator_sg 内部收集 peer EF（第 2977 行）
│           可用：target_card, stream_a2a_collect_forward_progress_frames 返回
│
├─ Phase 4: Mid-exec loop（第 7276 行开始）
│   ├─ Step 2: Plan（第 7620 行）
│   │   └─ 【Inject】注入更新后的 EF 地图到 mid_group_memory（第 7586 行）
│   │
│   └─ Step 3: Dispatch → _dispatch_mid_exec_delegation（第 9252 行）
│       └─ 【Point D】delegate task 完成后追加 EF 记录（第 9383 行之后）
│           可用：task (PlannerTask), agent_name, target_card, task_desc_for_delegate, result
│           可用：mid_exec_round (从 upstream_context 解码), current_hop, run_id, trace_id, user_id
│
└─ Phase 5: Summarize（第 7791 行开始）
    ├─ 【Point E】Turn Summary 记录（第 7870 行 updater.complete() 之前）
    │   可用：summary, own_results, delegated_results, sg_label, run_id, trace_id, user_id
    └─ 【Point F】Final Answer 记录（第 7870 行 updater.complete() 之前）
        可用：summary, sg_label, run_id, trace_id, user_id

execute() → Legacy 路径（第 6331 行开始）
│
├─ Phase 2: Plan（第 6354 行）
│   └─ 【Inject】注入 EF 地图到 group_memory
│
└─ a2a_tasks()（第 4494 行）
    ├─ 【Point G】每个 task 完成后追加 EF 记录（第 4570 行之后）
    │   可用：task (PlannerTask), current_agents_knowledge, execution_rounds, retry_count
    └─ 【Point H】每轮重试后 Turn Summary 记录（retry evaluation 之后）
        可用：retry_count, execution_rounds, tasks_status
```

> **注意**：SG Orchestrator 的 mid-exec 路径中**不存在 Point C（own task）**。`_dispatch_mid_exec_delegation` 只做委托，不做本地自执行。这是与 skill-agent 的关键区别。

---

### 4.2 【Entry】入口：接收上游 EF 地图

**精确位置**：`execute_collaborative()` 方法，第 6571 行之后

**代码上下文**：

```python
# 第 6571 行：upstream_context 解析
upstream_context = dict(metadata.get("upstream_context", {}))
user_id = str(metadata.get("user_id", ""))
run_id = str(metadata.get("run_id", ""))
trace_id = str(metadata.get("trace_id", ""))
# ↓ 第 6575 行之后，在此插入 EF 接收逻辑 ↓
```

**可用变量**：
| 变量 | 类型 | 说明 |
|------|------|------|
| `upstream_context` | `dict` | 上游所有上下文，可能包含 `"execution_flow"` 键 |
| `sg_label` | `str` | 当前 SG 的标识（第 6618 行定义，需提前） |
| `is_delegated` | `bool` | 是否是被委派的 agent |
| `run_id` | `str` | 当前 run 的 ID |
| `trace_id` | `str` | 分布式追踪 trace ID |
| `user_id` | `str` | 用户 ID |

**插入代码**：

```python
# ── 接收上游 Execution Flow 状态地图 ──
execution_flow_tasks: list[ExecutionTask] = []

upstream_ef = upstream_context.get("execution_flow")
if upstream_ef and isinstance(upstream_ef, list):
    for ef_dict in upstream_ef:
        if isinstance(ef_dict, dict):
            try:
                execution_flow_tasks.append(ExecutionTask.from_dict(ef_dict))
            except Exception:
                logger.warning(
                    "[ExecutionFlow] failed to parse upstream EF task: %s",
                    ef_dict.get("execution_id", "?"),
                )
    if execution_flow_tasks:
        logger.info(
            "[ExecutionFlow] received upstream state map | agent=%s count=%d",
            sg_label, len(execution_flow_tasks),
        )
```

---

### 4.3 【Inject】注入 EF 地图到 Group Memory（核心用途）

**精确位置**：`_enrich_group_memory_with_upstream()` 方法，第 6392 行

**三个调用方**：

| 调用方 | 行号 | 场景 |
|--------|------|------|
| `execute()` 中的 group_memory 构建 | 第 6354 行 | Legacy 路径的初始规划 |
| `execute_collaborative()` 中的 group_memory 构建 | 第 6752 行 | Cross-SG 路径的初始规划 |
| `execute_collaborative()` 中的 mid_group_memory 构建 | 第 7586 行 | Mid-exec 轮次的规划 |

**新增参数**：`execution_flow_tasks`, `agent_name`, `is_delegated`

```python
def _enrich_group_memory_with_upstream(
    upstream_context: dict,
    base_group_memory: str = "",
    extra_context: dict | None = None,
    execution_flow_tasks: list[ExecutionTask] | None = None,  # 【新增】
    agent_name: str = "",                                       # 【新增】
    is_delegated: bool = False,                                 # 【新增】
) -> str:
    parts: list[str] = []
    if base_group_memory:
        parts.append(base_group_memory)

    # ... 现有 JSON dump 逻辑（第 6408-6448 行）...

    # ── 【新增】注入 Execution Flow 状态地图 ──
    if execution_flow_tasks:
        ef_md = render_execution_flow_md(
            execution_flow_tasks,
            agent=agent_name,
            role="delegatee" if is_delegated else "initiator",
        )
        if ef_md:
            parts.append(ef_md)
            logger.info(
                "[ExecutionFlow] injected state map into group_memory | "
                "agent=%s tasks=%d chars=%d",
                agent_name, len(execution_flow_tasks), len(ef_md),
            )

    return "\n\n".join(parts)
```

**三个调用方适配**：

```python
# 第 6354 行（execute() Legacy 路径）
group_memory = self._enrich_group_memory_with_upstream(
    upstream_context=upstream_context,
    base_group_memory=base_group_memory,
    execution_flow_tasks=execution_flow_tasks,     # 【新增】
    agent_name=agent_name,                          # 【新增】
    is_delegated=is_delegated,                      # 【新增】
)

# 第 6752 行（execute_collaborative 初始规划）
group_memory = self._enrich_group_memory_with_upstream(
    upstream_context=upstream_context,
    base_group_memory=base_group_memory,
    execution_flow_tasks=execution_flow_tasks,     # 【新增】
    agent_name=sg_label,                            # 【新增】
    is_delegated=is_delegated,                      # 【新增】
)

# 第 7586 行（execute_collaborative mid-exec 规划）
mid_group_memory = self._enrich_group_memory_with_upstream(
    upstream_context=mid_upstream,
    base_group_memory=group_memory,
    extra_context={...},
    execution_flow_tasks=execution_flow_tasks,     # 【新增】
    agent_name=sg_label,                            # 【新增】
    is_delegated=is_delegated,                      # 【新增】
)
```

---

### 4.4 【Point A】Own Task 完成后追加 EF 记录

**精确位置**：`execute_collaborative()` Phase 3，第 6938-6940 行之后

**代码上下文**：

```python
# 第 6938 行：执行 own task
result = await self._execute_own_task_via_expert(
    t, user_id, run_id, trace_id, updater, agent,
    prior_task_results=_all_task_results,
    collaboration_original_query=query,
)
# 第 6939-6940 行：存储结果
own_results.setdefault(t.id, "")
own_results[t.id] = result
_all_task_results.setdefault(t.id, "")
_all_task_results[t.id] = result
# ↓ 第 6941 行之后，在此插入 Point A EF 记录 ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `t` | `PlannerTask` | 当前 plan task，含 `t.id`, `t.description`, `t.agent` |
| `agent_name` | `str` | task 的 agent 名称（如 `"order-agent"`） |
| `result` | `str` | 执行结果文本 |
| `plan_idx` | `int` | 当前 plan 的索引（从 0 开始） |
| `_all_task_results` | `dict[int, str]` | 所有 task 的累积结果 |
| `run_id / trace_id / user_id` | `str` | 追踪标识 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `f"t1-pre-{agent_name}-{t.id}"` |
| `turn` | `1` |
| `stage` | `"pre_exec"` |
| `agent` | `agent_name` |
| `role` | `"initiator"` |
| `task` | `t.description` 或 `""` |
| `result` | `result` |
| `reason` | `"本层 Planner 规划"` |

**插入代码**：

```python
# ── Point A: own task EF 记录 ──
exec_id = f"t1-pre-{agent_name}-{t.id}"
own_ef_task = ExecutionTask(
    execution_id=exec_id, turn=1, stage="pre_exec",
    agent=agent_name, role="initiator",
    task=t.description or "", result=result,
    reason="本层 Planner 规划",
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(own_ef_task)
await self._emit_execution_flow(updater, own_ef_task)
logger.info(
    "[ExecutionFlow] recorded | agent=%s turn=1 stage=pre_exec role=initiator task_preview=%s",
    agent_name, (t.description or "")[:80],
)
```

---

### 4.5 【Point A-expert】收集 Expert 的 EF 更新

**精确位置**：`_execute_own_task_via_expert()` 方法，第 7880 行

**代码上下文**：

```python
# 第 8111 行：调用 A2A streaming
return await OrchestratorAgent.stream_a2a_collect_forward_progress_frames(
    stream,
    self.get_response_text,
    updater,
    task_progress_name,
)
```

**修改**：`_execute_own_task_via_expert()` 返回值改为 `tuple[str, list[ExecutionTask]]`

**内部逻辑**：在 `stream_a2a_collect_forward_progress_frames` 中增加 `[[DAC_EXECUTION_FLOW]]` 帧收集（详见 §6.2）

**调用方合并（第 6938 行的调用方）**：

```python
# 旧代码
result = await self._execute_own_task_via_expert(...)

# 新代码
result, expert_ef_tasks = await self._execute_own_task_via_expert(...)

# 将 expert 的根任务链接到当前 own task
for et in expert_ef_tasks:
    if et.parent_execution_id is None:
        et.parent_execution_id = exec_id   # exec_id 来自 Point A
        et.delegated_by = agent_name
    execution_flow_tasks.append(et)
```

---

### 4.6 【Point B】Delegate Task 完成后追加 EF 记录

**精确位置**：`execute_collaborative()` Phase 3，第 7125-7138 行之后

**代码上下文**：

```python
# 第 7125 行：委派
result = await agent.delegate_to_collaborator_sg(
    target_card=_target_card,
    task_description=_task_desc_for_delegate,
    user_id=user_id, run_id=run_id, trace_id=trace_id,
    hop_remaining=_next_hop, delegation_chain=_new_chain,
    upstream_context=_ctx,
    progress_updater=updater,
    progress_artifact_name="collaboration-progress",
)
# 第 7138 行：存储结果
delegated_results[agent_name] = result
_all_task_results.setdefault(t.id, "")
_all_task_results[t.id] = result
# ↓ 第 7141 行之后，在此插入 Point B EF 记录 ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `t` | `PlannerTask` | 当前 plan task，含 `t.id`, `t.description`, `t.agent` |
| `agent_name` | `str` | 目标 SG 名称（如 `"user-agent"`） |
| `_target_card` | `AgentCard` | 目标 SG 的 AgentCard |
| `_task_desc_for_delegate` | `str` | 委派时的 task description（可能经 LLM refine） |
| `result` | `str` | 委派返回结果 |
| `_new_chain` | `list[str]` | 委派链 |
| `_next_hop` | `int` | 剩余 hop |
| `run_id / trace_id / user_id` | `str` | 追踪标识 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `f"t1-pre-{agent_name}-{t.id}"` |
| `turn` | `1` |
| `stage` | `"pre_exec"` |
| `agent` | `agent_name`（目标 SG） |
| `role` | `"delegatee"` |
| `task` | `_task_desc_for_delegate` 或 `t.description` |
| `result` | `result` |
| `reason` | `"Pre-exec delegation"` |
| `parent_execution_id` | `None` |
| `delegated_by` | `agent.agent_name`（当前 SG 的 orchestrator 名称） |

**插入代码（含三步模式）**：

```python
# ── Point B: delegate task EF 记录 + merge peer EF ──
# Step 1: 委派并拿到 peer 的 EF 更新（delegate_to_collaborator_sg 返回值改为元组）
result, peer_ef_tasks = await agent.delegate_to_collaborator_sg(...)

# Step 2: 创建本层的 delegate task EF 记录
exec_id = f"t1-pre-{agent_name}-{t.id}"
delegate_ef_task = ExecutionTask(
    execution_id=exec_id, turn=1, stage="pre_exec",
    agent=agent_name, role="delegatee",
    task=_task_desc_for_delegate or t.description or "",
    result=result,
    reason="Pre-exec delegation",
    delegated_by=agent.agent_name,
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(delegate_ef_task)
await self._emit_execution_flow(updater, delegate_ef_task)

# Step 3: 给 peer 的根任务设置 parent_execution_id，然后合并
for pt in peer_ef_tasks:
    if pt.parent_execution_id is None:
        pt.parent_execution_id = exec_id
        pt.delegated_by = agent.agent_name
    execution_flow_tasks.append(pt)

logger.info(
    "[ExecutionFlow] recorded | agent=%s turn=1 stage=pre_exec role=delegatee "
    "task_preview=%s peer_ef_tasks=%d",
    agent_name, (_task_desc_for_delegate or "")[:80], len(peer_ef_tasks),
)
```

---

### 4.7 【Point B-peer】`delegate_to_collaborator_sg` 内部收集 Peer EF

**精确位置**：`delegate_to_collaborator_sg()` 方法，第 2977 行

**代码上下文**：

```python
# 第 2977 行：方法签名
async def delegate_to_collaborator_sg(
    self, target_card, task_description, user_id="", run_id="", trace_id="",
    hop_remaining=0, delegation_chain=None, upstream_context=None,
    progress_updater=None, progress_artifact_name="collaboration-progress",
    execution_hint=None,
) -> str:
    # ...
    # 第 3039 行：A2A streaming 调用
    result = await self.stream_a2a_collect_forward_progress_frames(
        stream,
        self.get_response_text,
        progress_updater,
        progress_artifact_name,
    )
    # 第 3049 行：只返回 result
    return result
```

**修改**：返回值改为 `tuple[str, list[ExecutionTask]]`

**内部逻辑**：`stream_a2a_collect_forward_progress_frames` 中增加 EF 帧收集（详见 §6.2）

```python
# 新代码
result, peer_ef_tasks = await self.stream_a2a_collect_forward_progress_frames(...)
return result, peer_ef_tasks
```

---

### 4.8 【Point D】Mid-Exec Delegate Task 完成后追加 EF 记录

**精确位置**：`_dispatch_mid_exec_delegation()` 方法内，第 9370-9383 行之后

**代码上下文**：

```python
# 第 9370 行：mid-exec 委派
result = await agent.delegate_to_collaborator_sg(
    target_card=target_card,
    task_description=task_desc_for_delegate,
    user_id=user_id, run_id=run_id, trace_id=trace_id,
    hop_remaining=next_hop, delegation_chain=new_chain,
    upstream_context=ctx,
    progress_updater=progress_updater,
    progress_artifact_name="collaboration-progress",
    execution_hint=peer_hint or None,
)
# 第 9383 行：存储结果
results[agent_name] = result
# ↓ 第 9384 行之后，在此插入 Point D EF 记录 ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `task` | `PlannerTask` | 当前 plan task（循环变量） |
| `agent_name` | `str` | 目标 SG 名称 |
| `target_card` | `AgentCard` | 目标 SG 的 AgentCard |
| `task_desc_for_delegate` | `str` | 委派时的 task description |
| `result` | `str` | 委派返回结果 |
| `mid_exec_round` | `int` | 当前 mid-exec 轮次（从 `upstream_context` 解码，第 9279 行） |
| `current_hop` | `int` | 剩余 hop |
| `new_chain` | `list[str]` | 委派链 |
| `run_id / trace_id / user_id` | `str` | 追踪标识 |
| `detection_reason` | `str` | 检测原因（需从 `upstream_context` 获取，第 7693 行） |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `f"t1-mid{mid_exec_round}-{agent_name}-{task.id}"` |
| `turn` | `1` |
| `stage` | `f"mid_exec_round_{mid_exec_round}"` |
| `agent` | `agent_name`（目标 SG） |
| `role` | `"delegatee"` |
| `task` | `task_desc_for_delegate` |
| `result` | `result` |
| `reason` | `detection_reason` |
| `parent_execution_id` | `None` |
| `delegated_by` | `agent.agent_name` |

**插入代码**（含三步模式，与 Point B 完全一致）：

```python
# ── Point D: mid-exec delegate task EF 记录 + merge peer EF ──
# Step 1: 委派并拿到 peer 的 EF 更新（delegate_to_collaborator_sg 返回值改为元组）
result, peer_ef_tasks = await agent.delegate_to_collaborator_sg(...)

# Step 2: 创建本层的 delegate task EF 记录
exec_id = f"t1-mid{mid_exec_round}-{agent_name}-{task.id}"
delegate_ef_task = ExecutionTask(
    execution_id=exec_id, turn=1, stage=f"mid_exec_round_{mid_exec_round}",
    agent=agent_name, role="delegatee",
    task=task_desc_for_delegate or "", result=result,
    reason=detection_reason,
    delegated_by=agent.agent_name,
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(delegate_ef_task)
await self._emit_execution_flow(progress_updater, delegate_ef_task)

# Step 3: 给 peer 的根任务设置 parent_execution_id，然后合并
for pt in peer_ef_tasks:
    if pt.parent_execution_id is None:
        pt.parent_execution_id = exec_id
        pt.delegated_by = agent.agent_name
    execution_flow_tasks.append(pt)
```

**方法签名变更**：

```python
# 旧签名
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    is_delegated, agent, progress_updater=None,
    collaboration_original_query="", execution_hints_by_sg=None,
) -> tuple[dict[str, str], int]:

# 新签名
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    is_delegated, agent, progress_updater=None,
    collaboration_original_query="", execution_hints_by_sg=None,
    execution_flow_tasks: list[ExecutionTask] | None = None,  # 【新增】
) -> tuple[dict[str, str], int, list[ExecutionTask]]:
    """Returns (delegate_results, remaining_hop, execution_flow_tasks_delta).
    
    execution_flow_tasks_delta 是本方法内部新增的 EF 记录增量。
    调用方需将其 merge 到主 execution_flow_tasks 列表中。
    """
```

> **注意**：SG Orchestrator 的 `_dispatch_mid_exec_delegation` 只做委托，**不存在 Point C（own task）**。这与 skill-agent 不同——skill-agent 的 mid-exec 中既有 self task 也有 delegate task。

---

### 4.9 【Point E】Turn Summary 记录

**精确位置**：`execute_collaborative()` Phase 5，第 7839-7870 行之间

**代码上下文**：

```python
# 第 7839 行：生成 summary
summary = await self._summarize_delegated_result(
    query=query,
    own_results=own_results,
    delegated_results=delegated_results,
    upstream_context=upstream_context,
    user_id=user_id, run_id=run_id, trace_id=trace_id,
)
# ...
# 第 7870 行：updater.complete()
await updater.add_artifact(
    [TextPart(text=summary)],
    name="collaborative-result",
)
await updater.complete(
    message=new_agent_text_message("", context_id=task.context_id),
)
# ↓ 在 updater.complete() 之前插入 Point E + Point F ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `summary` | `str` | 总结后的最终文本 |
| `own_results` | `dict[int, str]` | 本层 own task 的执行结果 |
| `delegated_results` | `dict[str, str]` | 委派结果 |
| `sg_label` | `str` | 当前 SG 标识 |
| `run_id / trace_id / user_id` | `str` | 追踪标识 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `"t1-summary"` |
| `turn` | `1` |
| `stage` | `"turn_summary"` |
| `agent` | `sg_label` |
| `role` | `"initiator"` |
| `task` | `"Turn 1 执行结果"` |
| `result` | `"success"`（SG Orchestrator 单 Turn 无失败判定，始终 success） |
| `reason` | `"单轮执行完成"` |

**插入代码**：

```python
# ── Point E: Turn Summary ──
turn_summary_task = ExecutionTask(
    execution_id="t1-summary", turn=1, stage="turn_summary",
    agent=sg_label, role="initiator",
    task="Turn 1 执行结果", result="success",
    reason="单轮执行完成",
    parent_execution_id=None, delegated_by=None,
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(turn_summary_task)
await self._emit_execution_flow(updater, turn_summary_task)
```

---

### 4.10 【Point F】Final Answer 记录

**精确位置**：同 Point E，第 7870 行 `updater.complete()` 之前

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `summary` | `str` | 总结后的最终文本 |
| `sg_label` | `str` | 当前 SG 标识 |
| `run_id / trace_id / user_id` | `str` | 追踪标识 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `"final-answer"` |
| `turn` | `1` |
| `stage` | `"final_answer"` |
| `agent` | `sg_label` |
| `role` | `"initiator"` |
| `task` | `"最终答案"` |
| `result` | `summary`（完整总结文本） |
| `reason` | `""` |

**插入代码**：

```python
# ── Point F: Final Answer ──
final_answer_task = ExecutionTask(
    execution_id="final-answer", turn=1, stage="final_answer",
    agent=sg_label, role="initiator",
    task="最终答案", result=summary or "",
    reason="",
    parent_execution_id=None, delegated_by=None,
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(final_answer_task)
await self._emit_execution_flow(updater, final_answer_task)
```

---

### 4.11 【Point G】Legacy 路径任务记录

**精确位置**：`a2a_tasks()` 方法内，第 4535-4575 行的 task 执行循环中，第 4570 行之后

**代码上下文**：

```python
# 第 4535 行：开始遍历 task
for task in current_tasks.tasks:
    self._update_task_status(task.id, "start", "")
    # ... 各种执行路径 ...
    # 第 4570 行：agent=NONE 的 task 完成
    self._update_task_status(task.id, "complete", none_description)
    current_agents_knowledge.append(
        self._format_task_knowledge(task.id, task.description, "", none_description, "complete")
    )
# ↓ 第 4573 行之后，在每个 task 完成时插入 Point G EF 记录 ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `task` | `PlannerTask` | 当前 task（含 `task.id`, `task.description`, `task.agent`） |
| `execution_rounds` | `int` | 当前执行轮次（从 1 开始） |
| `retry_count` | `int` | 重试次数 |
| `current_agents_knowledge` | `list[str]` | 当前轮次的 agent 知识 |
| `self.tasks_status` | `list[TaskStatus]` | 当前所有 task 的状态 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `f"t{execution_rounds}-{task.agent}-{task.id}"` |
| `turn` | `execution_rounds` |
| `stage` | `"pre_exec"` |
| `agent` | `task.agent` 或 `"NONE"` |
| `role` | `"initiator"` |
| `task` | `task.description` 或 `""` |
| `result` | task 执行结果 |
| `reason` | `"本层 Planner 规划"` |

**插入代码**：

```python
# ── Point G: legacy task EF 记录 ──
exec_id = f"t{execution_rounds}-{task.agent or 'NONE'}-{task.id}"
task_result = current_agents_knowledge[-1] if current_agents_knowledge else ""
legacy_ef_task = ExecutionTask(
    execution_id=exec_id, turn=execution_rounds, stage="pre_exec",
    agent=task.agent or "NONE", role="initiator",
    task=task.description or "", result=task_result,
    reason="本层 Planner 规划",
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(legacy_ef_task)
```

---

### 4.12 【Point H】Legacy 路径 Turn Summary

**精确位置**：`a2a_tasks()` 方法内，每轮 retry evaluation 之后

**代码上下文**：

```python
# 第 4510 行：while 循环
while retry_count <= self.max_loop_count:
    execution_rounds += 1
    # ... 执行所有 task ...
    # retry evaluation 后
    # ↓ 在每轮末尾插入 Point H Turn Summary ↓
```

**可用变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `execution_rounds` | `int` | 当前执行轮次 |
| `retry_count` | `int` | 重试次数 |
| `self.tasks_status` | `list[TaskStatus]` | 当前所有 task 的状态 |
| `self._task_eval_results` | `dict` | task 评估结果 |

**EF 数据字段**：

| 字段 | 值 |
|------|-----|
| `execution_id` | `f"t{execution_rounds}-summary"` |
| `turn` | `execution_rounds` |
| `stage` | `"turn_summary"` |
| `agent` | `agent_name` |
| `role` | `"initiator"` |
| `task` | `f"Turn {execution_rounds} 执行结果"` |
| `result` | `"success"` 或 `"fail"` |
| `reason` | 失败原因（如有） |

**插入代码**：

```python
# ── Point H: legacy Turn Summary ──
all_success = all(
    ts.status == "complete" for ts in self.tasks_status
)
turn_summary_task = ExecutionTask(
    execution_id=f"t{execution_rounds}-summary",
    turn=execution_rounds, stage="turn_summary",
    agent=agent_name, role="initiator",
    task=f"Turn {execution_rounds} 执行结果",
    result="success" if all_success else "fail",
    reason="" if all_success else "部分任务未完成",
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(turn_summary_task)
```

---

## 5. 上游 EF 地图的传递

### 5.1 传递时机（精确行号）

| 委派场景 | 位置 | 行号 | 传递方式 |
|---------|------|------|---------|
| pre-exec 委派给对等智能体（skill-agent 或 peer SG） | `execute_collaborative()` Phase 3 | 第 7067 行 | `upstream_context["execution_flow"]` |
| mid-exec 委派给对等智能体（skill-agent 或 peer SG） | `_dispatch_mid_exec_delegation()` | 第 9309 行 | `upstream_context["execution_flow"]`（嵌套在 `ctx` 中） |
| own task 执行（委派给本地 expert，可能是 skill-agent） | `_execute_own_task_via_expert()` | 第 8037-8040 行 | A2A metadata `upstream_context["execution_flow"]` |

**注意**：SG Orchestrator 和 skill-agent 是对等智能体，使用相同的 A2A 协议和 EF 协议。上表中的"peer SG"和"skill-agent"在协议层面无区别——都是通过同一注册中心发现、通过同一 A2A 协议委派、通过同一 EF 帧传递状态地图。

### 5.2 传递逻辑

#### 5.2.1 pre-exec 委派（第 7067 行）

**代码上下文**：

```python
# 第 7050-7067 行：构建 upstream_context
_ctx: dict[str, Any] = {
    "delegator_plan": [pt.model_dump() for pt in plan.tasks],
    "executed_tasks": _completed_tasks_context,
    "key_findings_so_far": "\n".join(
        f"[Task#{tid}] {res[:300]}"
        for tid, res in _all_task_results.items() if res
    ),
    "remaining_tasks": [dt.model_dump() for dt in delegation_tasks],
    "upstream_context": upstream_context,
    # ↓ 在此插入 execution_flow 字段 ↓
}
```

**插入代码**：

```python
# ── 传递 Execution Flow 状态地图 ──
_ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
               for t in execution_flow_tasks]
_ctx["execution_flow"] = _ef_for_ctx

logger.info(
    "[ExecutionFlow] passing state map to downstream | agent=%s "
    "target=%s ef_tasks=%d",
    agent.agent_name, agent_name, len(_ef_for_ctx),
)
```

#### 5.2.2 mid-exec 委派（第 9309 行）

**代码上下文**：

```python
# 第 9309 行：_dispatch_mid_exec_delegation 中构建 ctx
ctx = dict(upstream_context or {})
tid_map = self._task_results_from_upstream_ctx(ctx)
# ↓ 在此插入 execution_flow 字段 ↓
```

**插入代码**：

```python
# ── 传递 Execution Flow 状态地图 ──
_ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
               for t in (execution_flow_tasks or [])]
ctx["execution_flow"] = _ef_for_ctx

logger.info(
    "[ExecutionFlow] passing state map to downstream (mid-exec) | agent=%s "
    "target=%s ef_tasks=%d",
    agent.agent_name, agent_name, len(_ef_for_ctx),
)
```

#### 5.2.3 own task 执行（第 8037-8040 行）

**代码上下文**：

```python
# 第 8037-8040 行：_execute_own_task_via_expert 中构建 A2A metadata
_a2a_upstream_context: dict = {}
if _upstream_executed_tasks:
    _a2a_upstream_context = {"executed_tasks": _upstream_executed_tasks}
# ↓ 在此插入 execution_flow 字段 ↓
```

**插入代码**：

```python
# ── 传递 Execution Flow 状态地图（给 expert agent）──
_ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
               for t in (execution_flow_tasks or [])]
if _ef_for_ctx:
    _a2a_upstream_context["execution_flow"] = _ef_for_ctx
    logger.info(
        "[ExecutionFlow] passing state map to expert | agent=%s "
        "target=%s ef_tasks=%d",
        agent.agent_name, task.agent, len(_ef_for_ctx),
    )
```

> **注意**：`_execute_own_task_via_expert` 自身没有 `execution_flow_tasks` 变量。需要从调用方（`execute_collaborative`）传入，或通过方法签名增加参数。

### 5.3 接收端入口

已在 §4.2 中详细说明。三处 A2A 接收点都需要在 metadata 解析后立即反序列化 `execution_flow`：

1. **Cross-SG 入口**：`execute_collaborative()` 第 6571 行（§4.2）
2. **Legacy 入口**：`execute()` 第 6354 行附近（`metadata.get("upstream_context", {})` 解析后）
3. **Expert 入口**：`_execute_own_task_via_expert()` 第 7880 行（A2A metadata 解析后）

---

## 6. 需要修改的方法（精确行号 + 签名变更）

### 6.1 `stream_a2a_collect_forward_progress_frames()` — 增加 EF 帧解析

**文件**：`orchestrator_agent_semantic_group.py`  
**类**：`OrchestratorAgent`  
**行号**：第 3249 行

**当前逻辑**：在 `handle_line` 中只处理 `[[DAC_PROGRESS]]`、`[[DAC_ANSWER]]`、`[[DAC_SUMMARY]]` 帧。需要增加 `[[DAC_EXECUTION_FLOW]]` 帧的识别和收集。

**代码上下文**：

```python
# 第 3249 行：方法签名
async def stream_a2a_collect_forward_progress_frames(
    stream_chunks: AsyncIterable[Any],
    get_text_fn: Callable[[Any], str],
    updater: Optional[Any],
    progress_artifact_name: str,
) -> str:
    # ...
    line_buf = ""
    result_segments: list[str] = []
    # ↓ 在此增加 peer_execution_flow_tasks 列表 ↓

    async def handle_line(raw_line: str) -> None:
        s = raw_line.strip()
        # 第 3269 行：处理 [[DAC_PROGRESS]]
        if OrchestratorAgent.is_progress_frame(s):
            # ...
        # 第 3276 行：处理 [[DAC_SUMMARY]]
        if OrchestratorAgent.is_summary_artifact(s):
            # ...
        # 第 3282 行：处理 [[DAC_ANSWER]]
        if OrchestratorAgent.is_answer_frame(s):
            # ...
        # ↓ 在此插入 [[DAC_EXECUTION_FLOW]] 处理 ↓
        result_segments.append(s)
```

**插入代码**：

```python
from skill_agent.agent.execution_flow import is_execution_flow_frame, ExecutionTask

# 在 line_buf 初始化后增加
peer_execution_flow_tasks: list[ExecutionTask] = []

# 在 handle_line 中，is_answer_frame 处理后增加
if is_execution_flow_frame(s):
    ef_task = ExecutionTask.from_frame(s)
    if ef_task is not None:
        peer_execution_flow_tasks.append(ef_task)
    # 不转发到 progress updater，只收集到列表
    # （EF 帧由下游 agent 自己 emit，不需要上游转发）
    return

# 在方法末尾，返回值改为元组
return body, peer_execution_flow_tasks
```

**返回值变更**：

```python
# 旧签名
async def stream_a2a_collect_forward_progress_frames(...) -> str:

# 新签名
async def stream_a2a_collect_forward_progress_frames(
    self, stream_chunks, get_text_fn, updater, progress_artifact_name,
) -> tuple[str, list[ExecutionTask]]:
    """Returns (body_text, peer_execution_flow_tasks)."""
```

### 6.2 `delegate_to_collaborator_sg()` — 返回值改为元组

**文件**：`orchestrator_agent_semantic_group.py`  
**类**：`OrchestratorAgent`  
**行号**：第 2977 行

**当前代码**：

```python
# 第 3039 行
result = await self.stream_a2a_collect_forward_progress_frames(
    stream, self.get_response_text, progress_updater, progress_artifact_name,
)
# 第 3049 行
return result
```

**新代码**：

```python
# 第 3039 行
result, peer_ef_tasks = await self.stream_a2a_collect_forward_progress_frames(
    stream, self.get_response_text, progress_updater, progress_artifact_name,
)
# 第 3049 行
return result, peer_ef_tasks
```

**签名变更**：

```python
# 旧签名
async def delegate_to_collaborator_sg(
    self, target_card, task_description, user_id="", run_id="", trace_id="",
    hop_remaining=0, delegation_chain=None, upstream_context=None,
    progress_updater=None, progress_artifact_name="collaboration-progress",
    execution_hint=None,
) -> str:

# 新签名
async def delegate_to_collaborator_sg(
    self, target_card, task_description, user_id="", run_id="", trace_id="",
    hop_remaining=0, delegation_chain=None, upstream_context=None,
    progress_updater=None, progress_artifact_name="collaboration-progress",
    execution_hint=None,
) -> tuple[str, list[ExecutionTask]]:
    """Returns (result_text, peer_execution_flow_tasks).

    peer_execution_flow_tasks 是下游 agent 的完整 EF 地图更新。
    调用方需要将其 merge 到本地 EF 地图中。
    """
```

### 6.3 `_execute_own_task_via_expert()` — 收集 Expert 的 EF 帧

**文件**：`orchestrator_agent_semantic_group.py`  
**类**：`OrchestratorAgentExecutorSemanticGroup`  
**行号**：第 7880 行

**当前代码**：

```python
# 第 7880 行：方法签名
async def _execute_own_task_via_expert(
    self, task, user_id, run_id, trace_id, updater, agent,
    prior_task_results=None, collaboration_original_query="",
) -> str:
    # ...
    # 第 8111 行：返回
    return await OrchestratorAgent.stream_a2a_collect_forward_progress_frames(
        stream, self.get_response_text, updater, task_progress_name,
    )
```

**新增参数**：`execution_flow_tasks: list[ExecutionTask] | None = None`（用于传递给下游 expert）

**新代码**：

```python
# 第 7880 行：方法签名
async def _execute_own_task_via_expert(
    self, task, user_id, run_id, trace_id, updater, agent,
    prior_task_results=None, collaboration_original_query="",
    execution_flow_tasks: list[ExecutionTask] | None = None,  # 【新增】
) -> tuple[str, list[ExecutionTask]]:                          # 【返回值变更】
    """Returns (result_text, expert_execution_flow_tasks)."""
    # ...
    # 在 _a2a_upstream_context 构建时（第 8037-8040 行），注入 execution_flow
    _a2a_upstream_context: dict = {}
    if _upstream_executed_tasks:
        _a2a_upstream_context = {"executed_tasks": _upstream_executed_tasks}
    # ── 【新增】传递 EF 地图 ──
    if execution_flow_tasks:
        _ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
                       for t in execution_flow_tasks]
        _a2a_upstream_context["execution_flow"] = _ef_for_ctx
    # ...
    # 第 8111 行：返回
    result, expert_ef_tasks = await OrchestratorAgent.stream_a2a_collect_forward_progress_frames(
        stream, self.get_response_text, updater, task_progress_name,
    )
    return result, expert_ef_tasks
```

**调用方适配（第 6938 行）**：

```python
# 旧代码
result = await self._execute_own_task_via_expert(
    t, user_id, run_id, trace_id, updater, agent,
    prior_task_results=_all_task_results,
    collaboration_original_query=query,
)

# 新代码
result, expert_ef_tasks = await self._execute_own_task_via_expert(
    t, user_id, run_id, trace_id, updater, agent,
    prior_task_results=_all_task_results,
    collaboration_original_query=query,
    execution_flow_tasks=execution_flow_tasks,  # 【新增】
)
```

### 6.4 `_dispatch_mid_exec_delegation()` — 签名变更

**文件**：`orchestrator_agent_semantic_group.py`  
**类**：`OrchestratorAgentExecutorSemanticGroup`  
**行号**：第 9252 行

**当前签名**：

```python
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    is_delegated, agent, progress_updater=None,
    collaboration_original_query="", execution_hints_by_sg=None,
) -> tuple[dict[str, str], int]:
```

**新签名**：

```python
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    is_delegated, agent, progress_updater=None,
    collaboration_original_query="", execution_hints_by_sg=None,
    execution_flow_tasks: list[ExecutionTask] | None = None,  # 【新增】
) -> tuple[dict[str, str], int, list[ExecutionTask]]:
    """Returns (delegate_results, remaining_hop, execution_flow_tasks_delta).

    execution_flow_tasks_delta 是本方法内部新增的 EF 记录增量。
    调用方需将其 merge 到主 execution_flow_tasks 列表中。
    """
```

**方法内部**：在 for 循环中每个 task 委派完成后（第 9383 行之后），追加 Point D 的 EF 逻辑（详见 §4.8）。

**方法内部新增变量**：

```python
# 第 9279 行之后：初始化
_delta_ef_tasks: list[ExecutionTask] = []

# 第 9309 行：在 ctx 中注入 execution_flow
ctx = dict(upstream_context or {})
if execution_flow_tasks:
    _ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
                   for t in execution_flow_tasks]
    ctx["execution_flow"] = _ef_for_ctx

# 在每个 task 委派后（第 9383 行之后）追加 Point D 逻辑
# ... 见 §4.8 插入代码 ...

# 方法末尾返回
return results, current_hop, _delta_ef_tasks
```

**调用方适配（第 7697 行）**：

```python
# 旧代码
mid_results, current_hop = await self._dispatch_mid_exec_delegation(...)

# 新代码
mid_results, current_hop, mid_ef_tasks = await self._dispatch_mid_exec_delegation(
    ..., execution_flow_tasks=execution_flow_tasks,
)
execution_flow_tasks.extend(mid_ef_tasks)
```

### 6.5 `_enrich_group_memory_with_upstream()` — 注入 EF 地图

**文件**：`orchestrator_agent_semantic_group.py`  
**行号**：第 6392 行

**签名变更**：

```python
# 旧签名
def _enrich_group_memory_with_upstream(
    upstream_context, base_group_memory="", extra_context=None,
) -> str:

# 新签名
def _enrich_group_memory_with_upstream(
    upstream_context, base_group_memory="", extra_context=None,
    execution_flow_tasks=None,  # 【新增】
    agent_name="",               # 【新增】
    is_delegated=False,          # 【新增】
) -> str:
```

**三个调用方适配**（详见 §4.3）：

| 调用方 | 行号 | 新增参数 |
|--------|------|---------|
| `execute()` Legacy 路径 | 第 6354 行 | `execution_flow_tasks`, `agent_name`, `is_delegated` |
| `execute_collaborative()` 初始规划 | 第 6752 行 | `execution_flow_tasks`, `agent_name=sg_label`, `is_delegated` |
| `execute_collaborative()` mid-exec 规划 | 第 7586 行 | `execution_flow_tasks`, `agent_name=sg_label`, `is_delegated` |

### 6.6 新增辅助方法

**文件**：`orchestrator_agent_semantic_group.py`  
**类**：`OrchestratorAgentExecutorSemanticGroup`

```python
from skill_agent.agent.execution_flow import (
    ExecutionTask, is_execution_flow_frame, render_execution_flow_md,
)

@staticmethod
def _is_execution_flow_frame(text: str) -> bool:
    """检查文本行是否为 Execution Flow 帧。"""
    return is_execution_flow_frame(text)

async def _emit_execution_flow(self, updater, task: ExecutionTask) -> None:
    """通过 A2A artifact 发送 Execution Flow 帧。"""
    if updater is None:
        return
    frame = task.to_frame()
    await updater.add_artifact([TextPart(text=frame)], name="execution-flow")
```

### 6.7 调用方适配汇总

| 方法 | 旧返回值 | 新返回值 | 行号 |
|------|---------|---------|------|
| `stream_a2a_collect_forward_progress_frames()` | `str` | `tuple[str, list[ExecutionTask]]` | 3249 |
| `delegate_to_collaborator_sg()` | `str` | `tuple[str, list[ExecutionTask]]` | 2977 |
| `_execute_own_task_via_expert()` | `str` | `tuple[str, list[ExecutionTask]]` | 7880 |
| `_dispatch_mid_exec_delegation()` | `tuple[dict, int]` | `tuple[dict, int, list[ExecutionTask]]` | 9252 |
| `_enrich_group_memory_with_upstream()` | `str` | `str`（新增参数，返回值不变） | 6392 |

---

## 7. 日志输出

### 7.1 最终 EF 地图日志

```python
if execution_flow_tasks:
    role = "delegatee" if is_delegated else "initiator"
    ef_md = render_execution_flow_md(execution_flow_tasks, agent=sg_label, role=role)
    logger.info("[ExecutionFlow] state map | run_id=%s trace_id=%s\n%s", run_id, trace_id, ef_md)
else:
    logger.info("[ExecutionFlow] empty state map (run_id=%s)", run_id)
```

### 7.2 关键节点日志

```python
logger.info(
    "[ExecutionFlow] recorded | agent=%s turn=%d stage=%s role=%s task_preview=%s",
    agent_name, turn, stage, role, (task or "")[:80],
)
```

---

## 8. 实现顺序

### Phase 1：基础设施
- [ ] 新增 `_is_execution_flow_frame` 和 `_emit_execution_flow` 辅助方法

### Phase 2：EF 帧解析（底层）
- [ ] 修改 `stream_a2a_collect_forward_progress_frames()`：返回值改为 `tuple[str, list[ExecutionTask]]`
- [ ] 修改 `delegate_to_collaborator_sg()`：返回值改为 `tuple[str, list[ExecutionTask]]`

### Phase 3：Expert 路径
- [ ] 修改 `_execute_own_task_via_expert()`：返回值改为 `tuple[str, list[ExecutionTask]]`

### Phase 4：Cross-SG 路径 EF 记录
- [ ] 入口：接收上游 EF 地图
- [ ] Point A/B：pre-exec 任务完成后追加 EF 记录 + merge
- [ ] Point E/F：Turn Summary + Final Answer 记录

### Phase 5：Mid-exec 路径 EF 记录
- [ ] 修改 `_dispatch_mid_exec_delegation()`：新增参数 + 返回值
- [ ] Point C/D：mid-exec 任务完成后追加 EF 记录 + merge

### Phase 6：注入 Group Memory
- [ ] 修改 `_enrich_group_memory_with_upstream()`：新增 `execution_flow_tasks` 参数
- [ ] 适配所有调用方

### Phase 7：上游 EF 传递
- [ ] pre-exec 委托 / mid-exec 委托 / own task 执行：增加 `execution_flow` 字段

### Phase 8：Legacy 路径
- [ ] Point G/H：`a2a_tasks()` 中追加 EF 记录 + Turn Summary

### Phase 9：日志输出
- [ ] `execute_collaborative()` 和 `a2a_tasks()` 末尾输出 EF 地图

### Phase 10：编译验证 + 测试
- [ ] 编译检查 + 运行现有测试 + 补充 EF 测试用例

---

## 9. 完整数据流：收 → 处理 → 合并 → 传

SG Orchestrator 的 Execution Flow 不是孤立存在的，它与 skill-agent 之间通过 A2A 协议双向传播 EF 帧。本章完整描述从"接收上游 EF"到"注入 Planner 上下文"再到"传递给下游"的完整闭环，与 skill-agent 保持一致。

### 9.1 五步闭环总览

```
                    ┌─────────────────────────────────┐
   ① 收             │  upstream_context 中反序列化     │
      │             │  execution_flow_tasks 列表       │
      ▼             └─────────────────────────────────┘
   ② 注入           ┌─────────────────────────────────┐
      │             │  render_execution_flow_md()     │
      │             │  → _enrich_group_memory_with_   │
      │             │    upstream()                   │
      │             │  → Planner 的 group_memory      │
      ▼             └─────────────────────────────────┘
   ③ 本地执行记录   ┌─────────────────────────────────┐
      │             │  Point A/B/D: 创建 ExecutionTask│
      │             │  → execution_flow_tasks.append()│
      │             │  → _emit_execution_flow()       │
      ▼             └─────────────────────────────────┘
   ④ 接收 peer 回传 ┌─────────────────────────────────┐
      │             │  stream_a2a_collect_forward_    │
      │             │  progress_frames() 内部：        │
      │             │  [[DAC_EXECUTION_FLOW]] 帧解析  │
      │             │  → peer_execution_flow_tasks    │
      ▼             └─────────────────────────────────┘
   ⑤ 合并 + 传      ┌─────────────────────────────────┐
                    │  三步模式：                      │
                    │  1. parent_execution_id 关联    │
                    │  2. execution_flow_tasks.extend │
                    │  3. upstream_context 中注入      │
                    │     execution_flow 字段          │
                    └─────────────────────────────────┘
```

### 9.2 Step ①：接收上游 EF（入口反序列化）

**触发时机**：每次 A2A 请求进入时，metadata 中携带 `upstream_context.execution_flow`

**skill-agent 中的实现**（`skill_agent.py` 第 5306-5327 行）：

```python
execution_flow_tasks: list[ExecutionTask] = []

upstream_ef = upstream_context.get("execution_flow")
if upstream_ef and isinstance(upstream_ef, list):
    for ef_dict in upstream_ef:
        if isinstance(ef_dict, dict):
            try:
                execution_flow_tasks.append(ExecutionTask.from_dict(ef_dict))
            except Exception:
                logger.warning(
                    "[ExecutionFlow] failed to parse upstream EF task: %s",
                    ef_dict.get("execution_id", "?"),
                )
    if execution_flow_tasks:
        logger.info(
            "[ExecutionFlow] received upstream EF | agent=%s turn=%d count=%d",
            self._self_planner_agent_name(), turn, len(execution_flow_tasks),
        )
```

**SG Orchestrator 中对应的位置**：

| 入口 | 方法 | 行号 | 说明 |
|------|------|------|------|
| Cross-SG 入口 | `execute_collaborative()` | 第 6571 行 | 从 `metadata.upstream_context.execution_flow` 反序列化 |
| Legacy 入口 | `execute()` | 第 6354 行附近 | 同上 |
| Expert 入口 | `_execute_own_task_via_expert()` | 第 7880 行 | 从 A2A metadata 反序列化 |

**实现细节**：与 skill-agent 完全一致，直接复用 `ExecutionTask.from_dict()`。

### 9.3 Step ②：注入 Planner 上下文（核心用途）

**skill-agent 中的实现**：在 `skill_agent_turn.py` 中，`_build_turn_context_md` 方法内调用 `render_execution_flow_md()`，将渲染后的 Markdown 注入到 `group_memory`。

**SG Orchestrator 中的实现**：在 `_enrich_group_memory_with_upstream()` 中注入（详见 §4.3）。

两者对比：

| 维度 | skill-agent | SG Orchestrator |
|------|------------|-----------------|
| 注入方法 | `_build_turn_context_md` | `_enrich_group_memory_with_upstream` |
| 注入时机 | 每轮 Turn 开始时 | 初始规划 + mid-exec 每轮规划 |
| 渲染函数 | `render_execution_flow_md()` | `render_execution_flow_md()`（复用） |
| 注入位置 | `group_memory` 中 | `group_memory` 中 |
| role 参数 | `"delegatee" if is_delegated else "initiator"` | 同 skill-agent |

### 9.4 Step ③：本地执行记录（Point A/B/D）

**skill-agent 中的实现**（`skill_agent.py` 第 5600-5607 行）：

```python
own_ef_task = ExecutionTask(
    execution_id=exec_id, turn=turn, stage="pre_exec",
    agent=agent_name, role="initiator",
    task=task_query, result=result, reason="本层 Planner 规划",
    ...
)
execution_flow_tasks.append(own_ef_task)
await self._emit_execution_flow(updater, own_ef_task)
```

**SG Orchestrator 中对应**：Point A（§4.4）、Point B（§4.6）、Point D（§4.8），模式完全一致。

### 9.5 Step ④：接收 peer 回传（A2A streaming 帧解析）

**这是最关键的一步，确保 peer agent 的 EF 不会丢失。**

**skill-agent 中的实现**（`skill_agent.py` 第 3978-4009 行，`_delegate_to_peer` 内部的 `_handle_line`）：

```python
peer_execution_flow_tasks: list[ExecutionTask] = []

async def _handle_line(raw_line: str) -> None:
    s = raw_line.strip()
    # ... 处理 [[DAC_PROGRESS]] ...
    # ... 处理 [[DAC_ANSWER]] ...
    # Collect peer's Execution Flow frames
    if self._is_execution_flow_frame(s):
        ef_task = ExecutionTask.from_frame(s)
        if ef_task is not None:
            peer_execution_flow_tasks.append(ef_task)
        # Also forward to updater under "execution-flow" artifact
        if updater is not None:
            await updater.add_artifact(
                [TextPart(text=s + "\n")],
                name="execution-flow",
            )
        return
    result_segments.append(s)

# ... streaming loop ...
return full_response, peer_execution_flow_tasks
```

**SG Orchestrator 中对应的位置**：`stream_a2a_collect_forward_progress_frames()` 方法（第 3249 行），需要增加完全相同的 EF 帧收集逻辑。

**关键设计决策对比**：

| 维度 | skill-agent | SG Orchestrator |
|------|------------|-----------------|
| 收集位置 | `_delegate_to_peer` 的 `_handle_line` | `stream_a2a_collect_forward_progress_frames` 的 `handle_line` |
| 帧检测 | `self._is_execution_flow_frame(s)` | `is_execution_flow_frame(s)` |
| 帧解析 | `ExecutionTask.from_frame(s)` | 同 skill-agent |
| 是否转发到 updater | ✅ 转发到 `"execution-flow"` artifact | ✅ 同样转发 |
| 返回值 | `tuple[str, list[ExecutionTask]]` | `tuple[str, list[ExecutionTask]]` |
| 触达的方法 | `_delegate_to_peer` | `delegate_to_collaborator_sg` + `_execute_own_task_via_expert` |

### 9.6 Step ⑤：合并 + 传递（三步模式 + 上游注入）

**skill-agent 和 SG Orchestrator 使用完全相同的三步模式**：

```python
# Step 1: 委派并拿到 peer 的 EF 更新
result, peer_ef_tasks = await self.delegate_to_collaborator_sg(...)

# Step 2: 创建本层的 delegate task EF 记录
exec_id = f"t1-pre-{agent_name}-{task.id}"
delegate_ef_task = ExecutionTask(
    execution_id=exec_id, turn=1, stage="pre_exec",
    agent=agent_name, role="delegatee",
    task=task_description, result=result,
    reason="Pre-exec delegation",
    delegated_by=self_agent_name,
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(delegate_ef_task)
await self._emit_execution_flow(updater, delegate_ef_task)

# Step 3: 给 peer 的根任务设置 parent_execution_id，然后合并
for pt in peer_ef_tasks:
    if pt.parent_execution_id is None:
        pt.parent_execution_id = exec_id
        pt.delegated_by = self_agent_name
    execution_flow_tasks.append(pt)
```

**SG Orchestrator 中三步模式的应用位置**：

| 位置 | 行号 | 委派方法 | 说明 |
|------|------|---------|------|
| Point B | 第 7138 行 | `delegate_to_collaborator_sg()` | pre-exec 委派 |
| Point D | 第 9383 行 | `delegate_to_collaborator_sg()` | mid-exec 委派 |
| Point A-expert | 第 6938 行 | `_execute_own_task_via_expert()` | own task 内的 expert 调用 |

**传递到下游**（发生在上游注入时，详见 §5）：

```python
# 在构建 upstream_context 时，将完整的 EF 地图序列化传递给下游
_ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
               for t in execution_flow_tasks]
_ctx["execution_flow"] = _ef_for_ctx
```

**传递位置**：

| 传递场景 | 行号 | 目标 |
|---------|------|------|
| pre-exec 委派 | 第 7067 行 | 对等 SG / skill-agent |
| mid-exec 委派 | 第 9309 行 | 对等 SG / skill-agent |
| own task 执行 | 第 8037 行 | 本地 expert agent |

### 9.7 与 skill-agent 的一致性清单

| 步骤 | skill-agent 文件/方法 | SG Orchestrator 文件/方法 | 行号 | 一致性 |
|------|----------------------|--------------------------|------|--------|
| ① 收 | `skill_agent.py` / `_execute_plan_and_mid_exec` | `orchestrator_agent_semantic_group.py` / `execute_collaborative` | 6571 | ✅ 完全一致 |
| ② 注入 | `skill_agent_turn.py` / `_build_turn_context_md` | `orchestrator_agent_semantic_group.py` / `_enrich_group_memory_with_upstream` | 6392 | ✅ 同函数 + 同参数 |
| ③ 本地记录 | `skill_agent.py` / Point A/B/F/G | `orchestrator_agent_semantic_group.py` / Point A/B/D | 6940/7138/9383 | ✅ 完全一致 |
| ④ peer 回传 | `skill_agent.py` / `_delegate_to_peer._handle_line` | `orchestrator_agent_semantic_group.py` / `stream_a2a_collect_forward_progress_frames.handle_line` | 3249 | ✅ 同逻辑 |
| ⑤ 合并传 | `skill_agent.py` / 三步模式 | `orchestrator_agent_semantic_group.py` / 三步模式 | 多处 | ✅ 完全一致 |

---

## 10. 风险与注意事项

1. **返回值变更影响面大**：`delegate_to_collaborator_sg()`、`_execute_own_task_via_expert()` 等方法的返回值变更需要适配所有调用方。建议分阶段迁移。

2. **导入依赖**：SG Orchestrator 需要 `from skill_agent.agent.execution_flow import ...`，需确认 Python 包路径可达。

3. **与 DAC Progress 的共存**：EF 帧与 DAC Progress 帧通过 `[[DAC_EXECUTION_FLOW]]` 前缀独立标识，互不干扰。

4. **`OrchestratorAgent` vs `OrchestratorAgentExecutorSemanticGroup`**：
   - `_emit_execution_flow` 放在 `OrchestratorAgentExecutorSemanticGroup`（需要 `TaskUpdater`）
   - EF 帧解析放在 `OrchestratorAgent`（`stream_a2a_collect_forward_progress_frames` 所在类）

5. **`handle_capability_check()` 和 `handle_pre_make_plan()`**：轻量级路径不需要 EF 记录，但需确保响应中不会意外携带 EF 帧。

6. **Legacy 路径的 Turn 映射**：建议与 skill-agent 保持一致，将 `turn` 固定为 `1`，用 `retry_count` 在 `reason` 字段中体现。

7. **Expert EF 兼容性**：本地 expert 可能是 skill-agent（已集成 EF）或其他类型 agent（未集成 EF）。需要兼容两种场景。

8. **`_enrich_group_memory_with_upstream` 的 JSON dump 废弃**：先并行注入（JSON + EF MD），确认 Planner 能正确理解后再移除 JSON dump。

9. **EF 地图大小**：随着委派链增长，EF 地图会越来越大。建议先不限制，观察实际大小后再决定是否优化。