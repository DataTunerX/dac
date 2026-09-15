# Execution Flow 设计方案

> **版本**: v2.0  
> **日期**: 2026-09-06  
> **状态**: 设计阶段，待评审

---

## 1. 概述

### 1.1 背景

当前 DAC 系统中，多智能体协作的执行过程追踪依赖两个机制：

1. **DAC Progress**（`[[DAC_PROGRESS]]`）：面向 UI 展示，松散自由，message 字段随意，extra 无 schema。
2. **turn_records**：Turn 级别的粗粒度记录，用于 Turn 间策略传递。

两者都**无法提供结构化的跨 Agent 执行流水账**，导致 Planner 在 mid-exec 和下一轮 Turn 中缺少「谁做了什么、结果是什么、为什么」的完整上下文。

### 1.2 目标

设计并实现 **Execution Flow** 机制：

- 以 **Turn 和 Task** 为关键节点，记录完整的结果和原因
- 支持 **跨 Agent 层级追踪**（A 委派 B，B 内部执行过程可见）
- 支持 **跨 Turn 全貌图**（Turn 1 → Turn 2 → ... 直到最终结果）
- 支持 **A→B→A 有来有回** 的复杂协作模式
- 基于 **A2A 协议** 传输，与 DAC Progress 并行共存
- 为 Planner 和调试提供结构化、可读的 MD 上下文
- 携带 `run_id`、`trace_id`、`user_id` 方便查询和维护

### 1.3 与 DAC Progress 的职责划分

| 维度 | DAC Progress | Execution Flow |
|------|-------------|----------------|
| 帧前缀 | `[[DAC_PROGRESS]]` | `[[DAC_EXECUTION_FLOW]]` |
| A2A artifact name | `"progress"` | `"execution-flow"` |
| 用途 | UI 展示，给用户看进度 | 结构化执行追踪，给 Planner/LLM/调试 |
| schema | 松散（message 自由，extra 任意） | 严格 |
| 层级关系 | 平面，无父子关系 | 树形（`parent_execution_id`） |
| 发送时机 | 每个事件点（开始、进行中、完成） | 每个关键节点完成后发送一次 |
| 消费方 | 前端 UI | Planner LLM、日志分析、调试 |
| 前端展示 | ✅ 展示 | ❌ 暂不展示 |

---

## 2. 核心执行流程

### 2.1 关键节点模型

Execution Flow 只记录**关键结果节点**，不记录过程：

```
Turn 1
├── pre_exec
│   ├── own task 完成      ← 记录
│   └── delegate task 完成  ← 记录
├── mid_exec_round_1
│   └── delegate task 完成  ← 记录
│       └── peer 内部 sub-tasks  ← 记录（通过 A2A 帧转发）
├── mid_exec_round_2
│   └── delegate task 完成  ← 记录
└── Turn 1 总结            ← 记录：本轮是否满足？失败原因是什么？

Turn 2
├── pre_exec
│   ├── own task 完成      ← 记录
│   └── delegate task 完成  ← 记录
├── mid_exec_round_1
│   └── delegate task 完成  ← 记录
└── Turn 2 总结            ← 记录：成功

最终答案                   ← 记录
```

**不记录的过程节点**（跳过）：
- hop 耗尽（还没执行就失败了）
- 依赖未满足（还没执行就跳过了）
- 上游数据无效（还没执行就跳过了）
- 中间态进度（如 "task_started", "planning_started"）

### 2.2 节点类型

| stage | 说明 | 示例 |
|-------|------|------|
| `"pre_exec"` | 本层预执行的 task | own task 或 delegate task |
| `"mid_exec_round_1"` | 第 N 轮 mid-exec 委派的 task | `"mid_exec_round_1"`, `"mid_exec_round_2"` |
| `"turn_summary"` | Turn 级别总结 | 本轮是否满足需求，失败原因 |
| `"final_answer"` | 整个 run 的最终答案 | 最终汇总结果 |

### 2.3 pre_exec 中的两种 Task

| 类型 | 判断条件 | role |
|------|---------|------|
| **own task** | `agent_name in own_names` | `"initiator"` |
| **delegate task** | `agent_name in collab_names` | `"delegatee"` |

### 2.4 A→B→A 有来有回

```
order-agent (root)
  └── user-agent (被 order 委派)
       └── order-agent (被 user 反委派，回查订单数据)
```

通过 `parent_execution_id` 引用，扁平列表可以表达任意深度的调用链，包括循环调用。

---

## 3. 数据结构

### 3.1 ExecutionTask

```python
@dataclass
class ExecutionTask:
    """一个 task 或 turn 的一次执行记录。

    只记录关键结果节点：谁、在哪个阶段、做了什么、结果是什么、为什么。
    通过 parent_execution_id 形成层级关系，表达跨 Agent 的委派链。
    """
    # ── 唯一标识 ──
    execution_id: str               # 全局唯一 ID

    # ── 时间线定位 ──
    turn: int                       # 第几轮 Turn
    stage: str                      # "pre_exec" | "mid_exec_round_N" | "turn_summary" | "final_answer"

    # ── 身份 ──
    agent: str                      # 执行此 task 的 agent 名称
    role: str                       # "initiator" | "delegatee"

    # ── 任务与结果 ──
    task: str                       # 此 task 的问题/描述
    result: str                     # 此 task 的结果（为空表示未完成/失败）

    # ── 原因 ──
    reason: str                     # 为什么规划了这个 task；如果失败，为什么失败

    # ── 层级关系 ──
    parent_execution_id: str | None # 父 ExecutionTask 的 execution_id（None = 根）
    delegated_by: str | None        # 如果 role=delegatee，被哪个 agent 委派

    # ── 追踪标识 ──
    run_id: str = ""                # 当前 run 的 ID
    trace_id: str = ""              # 分布式追踪 trace ID
    user_id: str = ""               # 用户 ID
```

### 3.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `execution_id` | `str` | ✅ | 全局唯一。格式：`t{turn}-{stage-short}-{agent}-{seq}`，如 `t1-pre-user-agent-1`、`t1-summary`、`final-answer` |
| `turn` | `int` | ✅ | Turn 编号，从 1 开始 |
| `stage` | `str` | ✅ | `"pre_exec"` / `"mid_exec_round_N"` / `"turn_summary"` / `"final_answer"` |
| `agent` | `str` | ✅ | 执行此 task 的 agent 名称 |
| `role` | `str` | ✅ | `"initiator"`：本层 Planner 规划；`"delegatee"`：被委派 |
| `task` | `str` | ✅ | 任务描述。turn_summary 时如 `"Turn 1 执行结果"`；final_answer 时如 `"最终答案"` |
| `result` | `str` | ✅ | 执行结果。turn_summary 时如 `"fail"` / `"success"` |
| `reason` | `str` | ✅ | 规划原因或失败原因 |
| `parent_execution_id` | `str \| None` | ✅ | 父 task 的 execution_id |
| `delegated_by` | `str \| None` | ✅ | 委派方 agent 名称 |
| `run_id` | `str` | | 当前 run 的 ID，方便查询和维护 |
| `trace_id` | `str` | | 分布式追踪 trace ID |
| `user_id` | `str` | | 用户 ID |

### 3.3 存储模型：扁平列表 + 引用

**不使用嵌套 `children`**，全部用 `parent_execution_id` 引用，理由：

1. 避免 JSON 序列化时的循环引用（A→B→A）
2. 跨 Agent 合并时只需 append 到列表，无需递归合并嵌套结构
3. 与 OpenTelemetry span 模型一致，兼容分布式追踪

渲染时通过 `parent_execution_id` 动态重建树：

```python
def build_tree(tasks: list[dict]) -> list[dict]:
    """按 parent_execution_id 重建树，返回根节点列表。"""
    by_id = {t["execution_id"]: t for t in tasks}
    roots = []
    for t in tasks:
        pid = t.get("parent_execution_id")
        if pid and pid in by_id:
            by_id[pid].setdefault("children", []).append(t)
        else:
            roots.append(t)
    return roots
```

### 3.4 帧格式

与 DAC Progress 并行，通过 A2A artifact 传输：

```
[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"t1-pre-user-agent-1","turn":1,"stage":"pre_exec","agent":"user-agent","role":"initiator","task":"查询用户","result":"张三","reason":"需要用户信息","parent_execution_id":null,"delegated_by":null,"run_id":"run-abc","trace_id":"trace-xyz","user_id":"user-001"}
```

传输方式：

```python
await updater.add_artifact([TextPart(text=frame)], name="execution-flow")
```

常量定义：

```python
EXECUTION_FLOW_FRAME_PREFIX = "[[DAC_EXECUTION_FLOW]] "
EXECUTION_FLOW_SCHEMA_VERSION = "v1"
```

---

## 4. 样本数据

### 4.1 场景：跨 Turn 跨 Agent 全貌

**用户问题**：查询用户张三的订单详情、支付记录和物流状态

**参与者**：
- `orchestrator`：发起者
- `user-agent`：用户信息查询
- `order-agent`：订单查询
- `payment-agent`：支付查询（被委派）
- `logistics-agent`：物流查询（被委派）

**执行过程**：
1. Turn 1 pre_exec：orchestrator 规划 user-agent + order-agent 各执行一个 task
2. Turn 1 mid_exec_round_1：检测到缺少支付，委派 payment-agent
3. Turn 1 mid_exec_round_2：检测到缺少物流，委派 logistics-agent
4. Turn 1 总结：fail，缺少物流信息
5. Turn 2 pre_exec：看到 Turn 1 的流水后，补充查询物流详情和用户地址
6. Turn 2 mid_exec_round_1：检测到缺少物流详情，委派 logistics-agent
7. Turn 2 总结：success
8. 最终答案

### 4.2 扁平列表数据

```json
{
  "flow_id": "run-abc-123",
  "agent": "orchestrator",
  "role": "initiator",
  "tasks": [
    {
      "execution_id": "t1-pre-user-agent-1",
      "turn": 1,
      "stage": "pre_exec",
      "agent": "user-agent",
      "role": "initiator",
      "task": "查询用户信息",
      "result": "用户：张三，age: 30，city: 北京",
      "reason": "用户问题涉及订单，需要先获取用户基础信息作为关联键",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t1-pre-order-agent-1",
      "turn": 1,
      "stage": "pre_exec",
      "agent": "order-agent",
      "role": "initiator",
      "task": "查询用户订单",
      "result": "订单#123：金额500元，status: paid",
      "reason": "用户问题涉及订单详情",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t1-mid1-payment-agent-1",
      "turn": 1,
      "stage": "mid_exec_round_1",
      "agent": "payment-agent",
      "role": "delegatee",
      "task": "补充查询张三的支付记录",
      "result": "支付记录：微信支付456元，时间2026-09-01",
      "reason": "检测到订单#123已支付但缺少支付记录，委派给payment-agent补充",
      "parent_execution_id": null,
      "delegated_by": "orchestrator",
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t1-mid1-payment-agent-1-internal",
      "turn": 1,
      "stage": "pre_exec",
      "agent": "payment-api",
      "role": "initiator",
      "task": "查询支付记录",
      "result": "微信支付456元",
      "reason": "被orchestrator委派，调用payment-api获取数据",
      "parent_execution_id": "t1-mid1-payment-agent-1",
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t1-mid2-logistics-agent-1",
      "turn": 1,
      "stage": "mid_exec_round_2",
      "agent": "logistics-agent",
      "role": "delegatee",
      "task": "补充查询订单#123的物流状态",
      "result": "物流：顺丰快递，已发货",
      "reason": "检测到订单已支付但缺少物流状态，委派给logistics-agent补充",
      "parent_execution_id": null,
      "delegated_by": "orchestrator",
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t1-summary",
      "turn": 1,
      "stage": "turn_summary",
      "agent": "orchestrator",
      "role": "initiator",
      "task": "Turn 1 执行结果",
      "result": "fail",
      "reason": "缺少物流信息，需要补充查询",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t2-pre-order-agent-1",
      "turn": 2,
      "stage": "pre_exec",
      "agent": "order-agent",
      "role": "initiator",
      "task": "补充查询订单#123的物流状态",
      "result": "物流：顺丰快递，已发货",
      "reason": "Turn 1 发现缺少物流信息，Turn 2 补充查询",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t2-pre-user-agent-1",
      "turn": 2,
      "stage": "pre_exec",
      "agent": "user-agent",
      "role": "initiator",
      "task": "补充查询用户地址",
      "result": "地址：北京朝阳区",
      "reason": "物流查询需要用户地址作为关联键",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t2-mid1-logistics-agent-1",
      "turn": 2,
      "stage": "mid_exec_round_1",
      "agent": "logistics-agent",
      "role": "delegatee",
      "task": "补充查询物流详情",
      "result": "物流详情：顺丰，预计9月3日送达",
      "reason": "检测到物流状态存在但缺少详细物流信息",
      "parent_execution_id": null,
      "delegated_by": "orchestrator",
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "t2-summary",
      "turn": 2,
      "stage": "turn_summary",
      "agent": "orchestrator",
      "role": "initiator",
      "task": "Turn 2 执行结果",
      "result": "success",
      "reason": "所有信息已齐全",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    },
    {
      "execution_id": "final-answer",
      "turn": 2,
      "stage": "final_answer",
      "agent": "orchestrator",
      "role": "initiator",
      "task": "最终答案",
      "result": "用户张三，订单#123金额500元，支付微信456元，物流顺丰预计9月3日送达",
      "reason": "",
      "parent_execution_id": null,
      "delegated_by": null,
      "run_id": "run-abc-123",
      "trace_id": "trace-xyz",
      "user_id": "user-001"
    }
  ]
}
```

### 4.3 A→B→A 有来有回

```
order-agent (root)
  └── user-agent (被 order 委派查用户)
       └── order-agent (被 user 反委派回查订单关联号)
```

```json
{
  "flow_id": "run-abc-456",
  "agent": "order-agent",
  "role": "initiator",
  "tasks": [
    {
      "execution_id": "t1-pre-order-agent-1",
      "turn": 1, "stage": "pre_exec",
      "agent": "order-agent", "role": "initiator",
      "task": "查询订单详情",
      "result": "订单#123：金额500元",
      "reason": "用户问题涉及订单",
      "parent_execution_id": null, "delegated_by": null,
      "run_id": "run-abc-456", "trace_id": "trace-xyz", "user_id": "user-001"
    },
    {
      "execution_id": "t1-mid1-user-agent-1",
      "turn": 1, "stage": "mid_exec_round_1",
      "agent": "user-agent", "role": "delegatee",
      "task": "补充查询订单#123对应的用户信息",
      "result": "用户：张三，age: 30",
      "reason": "检测到缺少用户信息，委派给user-agent",
      "parent_execution_id": null, "delegated_by": "order-agent",
      "run_id": "run-abc-456", "trace_id": "trace-xyz", "user_id": "user-001"
    },
    {
      "execution_id": "t1-mid1-user-agent-1-callback",
      "turn": 1, "stage": "mid_exec_round_1",
      "agent": "order-agent", "role": "delegatee",
      "task": "回查订单#123的用户关联订单号列表",
      "result": "关联订单：[#123, #456, #789]",
      "reason": "user-agent需要用户关联的所有订单号来定位用户身份",
      "parent_execution_id": "t1-mid1-user-agent-1",
      "delegated_by": "user-agent",
      "run_id": "run-abc-456", "trace_id": "trace-xyz", "user_id": "user-001"
    },
    {
      "execution_id": "t1-summary",
      "turn": 1, "stage": "turn_summary",
      "agent": "order-agent", "role": "initiator",
      "task": "Turn 1 执行结果",
      "result": "success",
      "reason": "用户信息和关联订单号已获取",
      "parent_execution_id": null, "delegated_by": null,
      "run_id": "run-abc-456", "trace_id": "trace-xyz", "user_id": "user-001"
    },
    {
      "execution_id": "final-answer",
      "turn": 1, "stage": "final_answer",
      "agent": "order-agent", "role": "initiator",
      "task": "最终答案",
      "result": "订单#123，用户张三，关联订单[#123, #456, #789]",
      "reason": "",
      "parent_execution_id": null, "delegated_by": null,
      "run_id": "run-abc-456", "trace_id": "trace-xyz", "user_id": "user-001"
    }
  ]
}
```

### 4.4 Markdown 渲染输出

```
## 执行流水账

**Agent**: orchestrator（发起者）
**Run ID**: run-abc-123
**Trace ID**: trace-xyz

---

### Turn 1

#### pre_exec（本层预执行）

1. **user-agent** → 查询用户信息
   - **结果**: 用户：张三，age: 30，city: 北京
   - **原因**: 用户问题涉及订单，需要先获取用户基础信息作为关联键

2. **order-agent** → 查询用户订单
   - **结果**: 订单#123：金额500元，status: paid
   - **原因**: 用户问题涉及订单详情

#### mid_exec_round_1

1. **payment-agent**（被委派者 ← orchestrator）→ 补充查询张三的支付记录
   - **结果**: 支付记录：微信支付456元，时间2026-09-01
   - **原因**: 检测到订单#123已支付但缺少支付记录，委派给payment-agent补充

   ⤷ **payment-agent 内部执行**:

   1. **payment-api** → 查询支付记录
      - **结果**: 微信支付456元
      - **原因**: 被orchestrator委派，调用payment-api获取数据

#### mid_exec_round_2

1. **logistics-agent**（被委派者 ← orchestrator）→ 补充查询订单#123的物流状态
   - **结果**: 物流：顺丰快递，已发货
   - **原因**: 检测到订单已支付但缺少物流状态，委派给logistics-agent补充

#### Turn 1 总结

- **结果**: fail
- **原因**: 缺少物流信息，需要补充查询

---

### Turn 2

#### pre_exec（本层预执行）

1. **order-agent** → 补充查询订单#123的物流状态
   - **结果**: 物流：顺丰快递，已发货
   - **原因**: Turn 1 发现缺少物流信息，Turn 2 补充查询

2. **user-agent** → 补充查询用户地址
   - **结果**: 地址：北京朝阳区
   - **原因**: 物流查询需要用户地址作为关联键

#### mid_exec_round_1

1. **logistics-agent**（被委派者 ← orchestrator）→ 补充查询物流详情
   - **结果**: 物流详情：顺丰，预计9月3日送达
   - **原因**: 检测到物流状态存在但缺少详细物流信息

#### Turn 2 总结

- **结果**: success
- **原因**: 所有信息已齐全

---

### 最终答案

用户张三，订单#123金额500元，支付微信456元，物流顺丰预计9月3日送达
```

---

## 5. 代码集成点

### 5.1 文件结构

```
dac/skill-agent/agent/
├── execution_flow.py          # ExecutionTask 数据类 + 帧构建/解析 + MD 渲染
├── skill_agent.py             # 在 task 完成节点发送 ExecutionTask 帧（Point A/B/F/G/I）
└── skill_agent_turn.py        # Turn 总结 + 最终答案 + 跨 Turn 积累 + 注入 group_memory（Point J）
```

### 5.2 插入点明细

| 点 | 文件 | 位置 | 场景 | stage |
|----|------|------|------|-------|
| **A** | `skill_agent.py` | own task 执行完成后（~5415 行） | pre_exec 本地执行 | `"pre_exec"` |
| **B** | `skill_agent.py` | delegate task 委派完成后（~5490 行） | pre_exec A2A 委派 | `"pre_exec"` |
| **F** | `skill_agent.py` | `_dispatch_mid_exec_delegation` self task 完成后（~3682 行） | mid-exec 本地执行 | `"mid_exec_round_N"` |
| **G** | `skill_agent.py` | `_dispatch_mid_exec_delegation` delegate task 完成后（~3742 行） | mid-exec A2A 委派 | `"mid_exec_round_N"` |
| **I** | `skill_agent.py` | `_delegate_to_peer` 的 `_handle_line` 中（~3840 行） | 转发 peer 的 `[[DAC_EXECUTION_FLOW]]` 帧 | peer 自己的 stage |
| **J** | `skill_agent_turn.py` | Turn 循环中（~476 行后） | Turn 总结 + 最终答案 + 注入 group_memory | `"turn_summary"` / `"final_answer"` |

### 5.3 各插入点的数据来源

#### Point A: pre_exec own task 完成

| 字段 | 来源 |
|------|------|
| `execution_id` | `f"t{turn}-pre-{agent_name}-{task_item.id}"` |
| `turn` | 函数参数 `turn` |
| `stage` | `"pre_exec"` |
| `agent` | `agent_name` |
| `role` | `"initiator"` |
| `task` | `task_query` |
| `result` | `result` |
| `reason` | `"本层 Planner 规划"`（成功）/ `"执行失败"`（失败） |
| `parent_execution_id` | `None` |
| `delegated_by` | `None` |
| `run_id` / `trace_id` / `user_id` | 从 `metadata` 或 `self._progress_context` 获取 |

#### Point B: pre_exec delegate task 完成

| 字段 | 来源 |
|------|------|
| `execution_id` | `f"t{turn}-pre-{agent_name}-{task_item.id}"` |
| `turn` | 函数参数 `turn` |
| `stage` | `"pre_exec"` |
| `agent` | `agent_name` |
| `role` | `"delegatee"` |
| `task` | `task_query` |
| `result` | `result` |
| `reason` | `"本层 Planner 规划，委派给外部 Agent 执行"` |
| `parent_execution_id` | `None` |
| `delegated_by` | `self._self_planner_agent_name()` |

#### Point F/G: mid_exec task 完成

| 字段 | 来源 |
|------|------|
| `execution_id` | `f"t{turn}-mid{mid_exec_round}-{agent_name}-{task.id}"` |
| `turn` | 新增参数 `turn` |
| `stage` | `f"mid_exec_round_{mid_exec_round}"` |
| `agent` | `agent_name` |
| `role` | `"initiator"`（self）/ `"delegatee"`（delegate） |
| `task` | `task.description` |
| `result` | `result` |
| `reason` | 新增参数 `detection_reason` |
| `delegated_by` | `self._self_planner_agent_name()`（delegate 时） |

#### Point I: 转发 peer 的 Execution Flow 帧

在 `_delegate_to_peer` 的 `_handle_line` 中新增：

```python
if self._is_execution_flow_frame(s):
    if updater is not None:
        await updater.add_artifact(
            [TextPart(text=s + "\n")],
            name="execution-flow",
        )
    return
```

#### Point J: Turn 总结 + 最终答案 + 注入 group_memory

在 `skill_agent_turn.py` 的 Turn 循环中：

```python
# 初始化
all_execution_flow_tasks: list[dict] = []

while total_turns < self.max_loops:
    # ... 执行一轮 ...
    task_results, delegate_results, remaining_hop, plan_task_meta, exec_flow = (
        await self._execute_plan_and_mid_exec(...)
    )
    all_execution_flow_tasks.extend(exec_flow)

    # Turn 总结
    turn_summary = ExecutionTask(
        execution_id=f"t{total_turns}-summary",
        turn=total_turns,
        stage="turn_summary",
        agent=self._self_planner_agent_name(),
        role="initiator",
        task=f"Turn {total_turns} 执行结果",
        result="success" if not failure_context else "fail",
        reason=failure_context or "本轮任务已满足用户需求",
        run_id=run_id, trace_id=trace_id, user_id=user_id,
    )
    all_execution_flow_tasks.append(turn_summary.to_dict())

    # 注入到下一轮 group_memory
    execution_flow_md = render_execution_flow_md(
        all_execution_flow_tasks,
        agent=self._self_planner_agent_name(),
        role="initiator" if not is_delegated else "delegatee",
    )
    if execution_flow_md:
        turn_context_md = _build_turn_context_md(...)
        group_memory = f"{base_group_memory}\n\n{turn_context_md}\n\n{execution_flow_md}"

# 循环结束后，记录最终答案
final_answer_task = ExecutionTask(
    execution_id="final-answer",
    turn=total_turns,
    stage="final_answer",
    agent=self._self_planner_agent_name(),
    role="initiator",
    task="最终答案",
    result=final_answer,
    reason="",
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
all_execution_flow_tasks.append(final_answer_task.to_dict())
```

### 5.4 `_execute_plan_and_mid_exec` 返回值变更

```python
# 旧签名
async def _execute_plan_and_mid_exec(
    self, ..., failure_context="", ...,
) -> tuple[dict[int, str], dict[str, str], int, list[dict]]:

# 新签名
async def _execute_plan_and_mid_exec(
    self, ..., failure_context="", ..., turn: int = 1,
) -> tuple[dict[int, str], dict[str, str], int, list[dict], list[ExecutionTask]]:
```

### 5.5 `_dispatch_mid_exec_delegation` 参数变更

```python
# 旧签名
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    hints_by_sg=None, updater=None, skill_runner=None, metadata=None,
)

# 新签名
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    hints_by_sg=None, updater=None, skill_runner=None, metadata=None,
    turn: int = 1, detection_reason: str = "",
)
```

### 5.6 跨 Agent 合并

当 orchestrator 委派 task 给 payment-agent 时，payment-agent 的 Execution Flow 帧通过 A2A 返回。收集方需要：

1. `_delegate_to_peer` 中转发 peer 的 `[[DAC_EXECUTION_FLOW]]` 帧到 updater（Point I）
2. 在 `_dispatch_mid_exec_delegation` 中，通过 `_delegate_to_peer` 的返回值拿到 peer 的 ExecutionTask 列表
3. 将 peer 的根 task 的 `parent_execution_id` 设置为当前 delegate task 的 `execution_id`
4. 追加到 `execution_flow_tasks` 列表

---

## 6. Execution Flow 与现有机制的关系

### 6.1 与 turn_records 的关系

| 维度 | turn_records | Execution Flow |
|------|-------------|----------------|
| 粒度 | Turn 级别（粗） | Turn + Task 级别（细） |
| 用途 | Turn 间传递策略信息 | 完整执行流水 + 结果 |
| 包含 | plan 元信息 + 聚合结果 + delegate_results | 每个 task 的完整结果 + Turn 总结 + 最终答案 |
| 层级 | 平面列表 | 树形结构（parent_execution_id） |
| 注入时机 | 每轮 Turn 开始时 | 每轮 Turn 开始时注入 group_memory |
| 数据来源 | `_execute_plan_and_mid_exec` 返回值 | `_execute_plan_and_mid_exec` 返回值 + A2A 帧转发 |

### 6.2 与 DAC Progress 的关系

| 维度 | DAC Progress | Execution Flow |
|------|-------------|----------------|
| 帧前缀 | `[[DAC_PROGRESS]]` | `[[DAC_EXECUTION_FLOW]]` |
| A2A artifact name | `"progress"` | `"execution-flow"` |
| 发送时机 | 每个事件点 | 每个关键结果节点 |
| 前端展示 | ✅ | ❌ 暂不展示 |
| 内容 | 过程事件（开始、进行中、完成） | 结果节点（结果 + 原因） |

---

## 7. 实现计划

### 7.1 Phase 1：execution_flow.py 模块 ✅ 已完成

- [x] `ExecutionTask` 数据类（12 个字段，含 run_id/trace_id/user_id）
- [x] `to_frame()` / `from_frame()` 帧序列化
- [x] `is_execution_flow_frame()` 帧检测
- [x] `parse_frames()` / `strip_execution_flow_lines()` 帧解析
- [x] `build_tree()` 树形结构重建
- [x] `render_execution_flow_md()` Markdown 渲染（含 turn_summary / final_answer）
- [x] 35 个测试全部通过

### 7.2 Phase 2：更新 execution_flow.py 适配新字段

- [ ] 更新 `ExecutionTask` 增加 `run_id` / `trace_id` / `user_id`
- [ ] 更新 `render_execution_flow_md()` 渲染 `turn_summary` 和 `final_answer` 节点
- [ ] 更新测试用例

### 7.3 Phase 3：集成到 skill_agent.py

- [ ] 添加 import + `_is_execution_flow_frame` + `_emit_execution_flow`
- [ ] `_execute_plan_and_mid_exec` 新增 `turn` 参数 + `execution_flow_tasks` 列表 + 返回值
- [ ] Point A: own task 完成后 emit ExecutionTask
- [ ] Point B: delegate task 完成后 emit ExecutionTask
- [ ] `_dispatch_mid_exec_delegation` 新增 `turn` + `detection_reason` 参数
- [ ] Point F: self task 完成后 emit ExecutionTask
- [ ] Point G: delegate task 完成后 emit ExecutionTask
- [ ] Point I: `_delegate_to_peer` 转发 `[[DAC_EXECUTION_FLOW]]` 帧
- [ ] `execute()` 单 Turn 路径适配新返回值（turn 默认为 1，同样记录 Turn 总结和最终答案）

### 7.4 Phase 4：集成到 skill_agent_turn.py

- [ ] Turn 循环中积累 `execution_flow_tasks`
- [ ] Turn 总结（`turn_summary`）记录
- [ ] 最终答案（`final_answer`）记录
- [ ] `render_execution_flow_md()` 注入到 `group_memory`

### 7.5 Phase 5：替换现有 mid-exec 上下文构建

- [ ] 用 `render_execution_flow_md()` 替换 `_build_mid_exec_planner_context()` 的调用
- [ ] 逐步废弃 `_enrich_group_memory_with_upstream` 中的 JSON dump 逻辑
- [ ] 清理 300 字符截断（`res[:300]`）等遗留问题

---

## 8. 设计决策（已确定）

### 8.1 `_delegate_to_peer` 返回值

**决策**：改为返回 `(result_text, peer_execution_flow_tasks)` 元组。

**理由**：updater 是单向的（只写不读），caller 无法从 updater 回读 peer 的 ExecutionTask 帧。只能通过返回值传递。

**实现**：

```python
# _delegate_to_peer 内部
peer_exec_flow_tasks: list[ExecutionTask] = []

async def _handle_line(raw_line: str) -> None:
    s = raw_line.strip()
    if not s:
        return
    if self._is_progress_frame(s):
        if updater is not None:
            await updater.add_artifact([TextPart(text=s + "\n")], name="progress")
        return
    if self._is_answer_frame(s):
        if updater is not None:
            await updater.add_artifact([TextPart(text=s + "\n")], name="progress")
        return
    if self._is_execution_flow_frame(s):
        # Point I: 转发到 updater
        if updater is not None:
            await updater.add_artifact([TextPart(text=s + "\n")], name="execution-flow")
        # 收集到列表（供 caller 设置 parent_execution_id）
        task = ExecutionTask.from_frame(s + "\n")
        if task is not None:
            peer_exec_flow_tasks.append(task)
        return
    result_segments.append(s)

# ... streaming loop ...
return full_response, peer_exec_flow_tasks
```

**调用方适配**：

```python
result, peer_tasks = await self._delegate_to_peer(...)
delegate_results[agent_name] = result

# 给 peer 的根 task 设置 parent_execution_id，然后合并
for pt in peer_tasks:
    if pt.parent_execution_id is None:
        pt.parent_execution_id = execution_id
    execution_flow_tasks.append(pt)
```

### 8.2 Turn 路径统一

**决策**：不存在"Non-turn 路径"，所有执行都是 Turn。Turn 1 就是 Turn 1，不管有没有 Turn 2。

**理由**：单次执行只是 Turn 数量为 1 的特例，不应特殊对待。`_execute_plan_and_mid_exec` 的 `turn` 参数默认值 `1`，所有调用方走同一套 Execution Flow 记录逻辑：收集 execution_flow_tasks → 记录 Turn 总结 → 记录最终答案。

### 8.3 `_dispatch_mid_exec_delegation` 参数

**决策**：显式参数 `turn: int = 1, detection_reason: str = ""`，新增返回值 `list[ExecutionTask]`。

**理由**：显式参数比隐式传递（塞进 `upstream_context`）更清晰，参数来源明确可追溯。

**最终签名**：

```python
async def _dispatch_mid_exec_delegation(
    self, plan, target_cards, user_id, run_id, trace_id,
    current_hop, delegation_chain, upstream_context,
    hints_by_sg=None, updater=None, skill_runner=None, metadata=None,
    turn: int = 1,
    detection_reason: str = "",
) -> tuple[dict[str, str], dict[str, str], int, list[ExecutionTask]]:
```

### 8.4 跨 Agent 合并 `parent_execution_id`

**决策**：统一的三步模式，在 pre_exec 和 mid_exec 两处各实现一次。

**三步模式**：

```python
# Step 1: 委派，拿到 peer 的 ExecutionTask 列表
result, peer_tasks = await self._delegate_to_peer(...)
delegate_results[agent_name] = result

# Step 2: 创建本层的 delegate task ExecutionTask
execution_id = f"t{turn}-{stage_short}-{agent_name}-{task_id}"
exec_task = ExecutionTask(
    execution_id=execution_id,
    turn=turn, stage=stage,
    agent=agent_name, role="delegatee",
    task=task_desc, result=result,
    reason=reason,
    delegated_by=self._self_planner_agent_name(),
    run_id=run_id, trace_id=trace_id, user_id=user_id,
)
execution_flow_tasks.append(exec_task)

# Step 3: 给 peer 的根 task 设置 parent_execution_id，然后合并
for pt in peer_tasks:
    if pt.parent_execution_id is None:
        pt.parent_execution_id = execution_id
    execution_flow_tasks.append(pt)
```

### 8.5 最终签名总览

```python
# _execute_plan_and_mid_exec
async def _execute_plan_and_mid_exec(
    self, ..., turn: int = 1,
) -> tuple[dict[int, str], dict[str, str], int, list[dict], list[ExecutionTask]]:

# _dispatch_mid_exec_delegation
async def _dispatch_mid_exec_delegation(
    self, ..., turn: int = 1, detection_reason: str = "",
) -> tuple[dict[str, str], dict[str, str], int, list[ExecutionTask]]:

# _delegate_to_peer
async def _delegate_to_peer(
    self, ...
) -> tuple[str, list[ExecutionTask]]:
```