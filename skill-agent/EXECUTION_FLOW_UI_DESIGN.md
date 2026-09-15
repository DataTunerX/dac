# Execution Flow UI 展示设计方案

> **版本**: v2.0（讨论稿 · 决策已收敛）
> **日期**: 2026-09-14
> **状态**: 🟡 方案已细化，**待实现**
> **前置文档**: [`EXECUTION_FLOW_DESIGN.md`](./EXECUTION_FLOW_DESIGN.md)（v2.0，EF 协议与 Planner 消费侧设计）
> **本文目标**: 把已有的 EF（Execution Flow）结构化数据接到前端，在 UI 上展示执行状态

---

## 1. 结论速览（TL;DR）

**能做，而且数据早就是现成的结构化数据。** 卡点不在"能不能"，而在于三处代码**有意把 EF 帧丢掉了**，以及前端从未定义过 EF 的渲染方式。UI 形态：**弹出框中上七下三布局**，上半区图+树展示委派层级，下半区表格展示全部任务详情。

| 层 | 现状 | 要做什么 |
|---|---|---|
| skill-agent | ✅ 已发 EF 帧（artifact `execution-flow`） | 无需改动 |
| orchestrator | ⚠️ 收集 EF 但**不转发**给 UI 流 | 转发 expert 的 EF 帧 |
| routing-agent | ❌ 完全不认识 EF，按"内部帧"丢弃 | 识别并转发（2 条路径） |
| dac-apiserver | ✅ 前缀泛化，**零改动即可透传** | 只需按前缀标记事件名 |
| frontend | ️ 能收到但字段名对不上 | 解析 + 弹窗面板（上七下三：图+树 / 表格）+ 入口按钮 |

工作量集中在**后端 2 处转发**和**前端 1 个弹窗面板**。

### 1.1 已拍板决策

| 编号 | 决策 |
|---|---|
| **Q1** | **图 + 树 + 表格结合（上七下三）**：上半区树形节点图展示委派层级与执行流程，父子关系用箭头连接；下半区表格按树的深度优先遍历顺序列出全部任务详情（含 `execution_id` / `turn` / `stage` / `agent` / `role` / `task` / `result` / `parent_execution_id` / `delegated_by` 等列） |
| **Q2** | **独立弹窗面板**，入口按钮放在「已思考」标题行右侧（与思考同级），点击弹出 |
| **Q5** | **只要是 ExecutionTask 都展示**，不做 stage 过滤 |
| **Q7** | **历史回放暂不做**（优先级低，Phase 3+） |

---

## 2. 背景：EF 已经是一条完整协议

`ExecutionTask` 的 14 个字段（见 [`execution_flow.py`](./agent/execution_flow.py)）天然支持 UI 表达：

| UI 需求 | 依赖字段 |
|---|---|
| **执行节点**（第几轮、哪个阶段） | `turn` + `stage` |
| **执行树**（谁委派给谁） | `parent_execution_id` + `delegated_by` + `role` |
| **状态**（成功/失败/未派发） | `result` + `reason` |
| **归属**（哪个 agent） | `agent` |
| **定位**（哪次 run） | `run_id` + `trace_id` + `user_id` |

`stage` 取值域（固定枚举，适合分组）：

```
pre_exec → mid_exec_round_1 → mid_exec_round_2 → ... → turn_summary → final_answer
```

`role` 取值域：`initiator`（本层规划）/ `delegatee`（被委派）。

### 2.1 传输机制已就绪

skill-agent 侧已按 A2A artifact 发出 EF 帧：

```3988:3999:skill-agent/agent/skill_agent.py
    async def _emit_execution_flow(
        self,
        updater: TaskUpdater,
        execution_task: ExecutionTask,
    ) -> None:
        """Emit an Execution Flow frame via A2A artifact.

        Mirrors ``_emit_progress`` but for Execution Flow frames.
        Frame is sent via artifact ``name="execution-flow"``.
        """
        frame = execution_task.to_frame()
        await updater.add_artifact([TextPart(text=frame)], name="execution-flow")
```

帧格式（与 DAC Progress 完全平行）：

```
[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"t1-pre-user-agent-1","turn":1,"stage":"pre_exec","agent":"user-agent","role":"initiator","task":"查询用户","result":"张三","reason":"需要用户信息","parent_execution_id":null,"delegated_by":null,"run_id":"run-abc","trace_id":"trace-xyz","user_id":"user-001"}
```

orchestrator 实现了**同协议**的 `_emit_execution_flow`（artifact name 相同），并且自己也产出 `own_ef_task` / `turn_summary` / `final_answer`：

```6938:6960:orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py
    async def _emit_execution_flow(
        self,
        updater: TaskUpdater,
        task: "ExecutionTask",
    ) -> None:
        """Send an Execution Flow frame via A2A artifact.

        Uses the same artifact name ``"execution-flow"`` as skill-agent so
        upstream/downstream agents can collect and merge the distributed
        execution state map consistently.
        """
        if updater is None:
            return
        frame = task.to_frame()
        await updater.add_artifact(
            [TextPart(text=frame)],
            name="execution-flow",
        )
```

### 2.2 完整链路现状

```
                         ┌──────────────────────────────────────────────┐
                         │              EF 帧流经路径                    │
                         └──────────────────────────────────────────────┘

  skill-agent ──EF──▶ orchestrator ──?──▶ routing-agent ──?──▶ apiserver ─▶ frontend
      ✅ 发              ⚠️ 收但不转发        ❌ 不认识/丢弃         ✅ 可透传      ⚠️ 字段对不上
```

---

## 3. 阻塞点：三处证据

### 3.1 orchestrator 明确丢弃 expert 的 EF 帧

```4056:4065:orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py
            # ── Execution Flow: collect peer's EF frames ──
            # Peer agents emit [[DAC_EXECUTION_FLOW]] frames via A2A artifact.
            # We collect them here so the caller can merge them into the local
            # execution state map.  These frames are NOT forwarded to the
            # progress updater to avoid polluting the UI stream.
            if OrchestratorAgent.is_execution_flow_frame(s):
                ef_task = ExecutionTask.from_frame(s)
                if ef_task is not None:
                    peer_execution_flow_tasks.append(ef_task)
                return
```

注释直白：*"NOT forwarded to the progress updater to avoid polluting the UI stream"*。
EF 只被收进 `peer_execution_flow_tasks`，喂给 Planner 的 `group_memory`，**不往 updater 转发**。

orchestrator 自己产生的节点（`own_ef_task`、`delegate_ef_task`、`turn_summary`、`final_answer`）**是发了的**。发射点：`8421`（own）、`8657`（pre_exec delegate）、`9422`（turn_summary）、`9440`（final_answer）、`11205`（mid_exec delegate）。

### 3.2 routing-agent 对 EF 一无所知，按内部帧丢弃

全文件搜索 `DAC_EXECUTION_FLOW` / `execution_flow` **零命中**。原因是内部帧判定是前缀泛化的：

```2207:2208:routing-agent/routing_agent/server.py
    def is_internal_dac_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_")
```

两处下游消费把这个泛化判定当"丢弃"用：

```4835:4836:routing-agent/routing_agent/server.py
                                if self.agent.is_internal_dac_frame(result):
                                    continue
```

```3732:3733:routing-agent/routing_agent/server.py
                        if self.is_internal_dac_frame(text):
                            continue
```

（前者 single-root 转发路径，后者 multi-root 聚合路径 `execute_multi_root_plan_stream`。）

**结论：即使 orchestrator 转发了，routing 这层也会把 EF 当内部帧吃掉。**

### 3.3 （已确认的 bug）EF 帧会泄漏进给 LLM 的正文

orchestrator 的 `a2a_non_stream`（**非流式路径**）只挡了 `is_progress_frame`，**没有挡 EF 帧**，也没有 `is_internal_dac_frame` 兜底：

```4388:4392:orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result == "" or self.is_progress_frame(result):
                        continue
```

后果：EF 帧字符串会落入 `agent_knowledge`，被 `"\n".join()` 拼进 `_finalize_a2a_collected_text` 的返回值 → **污染下游 LLM 输入**。

> 这是**独立于本 UI 需求就该修的 bug**，不修的话 UI 改动会让它更容易暴露（帧量变大）。
> 注意 `a2a_stream`（流式路径，`4201`）会把 EF 帧透传出去，行为与 `a2a_non_stream` **不一致**。

同类的 `a2a_tasks` 主循环（`5417`）只挡了 `is_progress_frame` + `is_summary_artifact`，**同样没挡 EF**。

### 3.4 前端字段名对不上

前端是**泛化解析**的，EF 帧今天就能流到前端（如果链路打通），但会渲染成半空白卡片：

- `parse-chat-sse.ts`：`event:` 非空即把 `data:` 当 progress payload 解析 —— **能收**
- `shouldShowProgressItem`：EF 没有 `event` 字段 → 返回 `true` → **不会被过滤掉**
- `getProgressRowDisplay`：读 `event` / `message` / `agent` / `layer`，而 EF 用 `stage` / `task` / `result` / `reason` → **只显示 agent + task，result/reason/stage/turn 全丢**

```32:41:frontend/src/lib/chat-progress.ts
export function getProgressRowDisplay(payload: ChatProgressPayload): ProgressRowDisplay {
  return {
    agent: firstOf(payload.agent_id, payload.agent) ?? null,
    layer: firstOf(payload.layer) ?? null,
    event: firstOf(payload.event) ?? null,
    message: firstOf(payload.message, payload.task) ?? null,
  }
}
```

### 3.5 好消息：apiserver 零改动即可透传

apiserver 的帧识别是前缀泛化的，`]]` 之后的内容整体当 payload：

```19:22:dac-apiserver/internal/infrastructure/a2a/client.go
const (
	dacFramePrefix = "[[DAC_"
	dacFrameSuffix = "]]"
)
```

`handleFramePayload` 对非 `DAC_ANSWER` 帧统一塞进 `StreamChunk.Progress`：

```207:236:dac-apiserver/internal/infrastructure/a2a/client.go
// handleFramePayload converts DAC_ANSWER final output into explicit content chunks and keeps
// non-answer DAC frames as progress JSON payloads.
func (c *client) handleFramePayload(payload string, outputCh chan<- entity.StreamChunk, state *answerFrameState) {
	eventName, text, ok := parseAnswerFramePayload(payload)
	if !ok {
		outputCh <- entity.StreamChunk{Progress: payload}
		c.logger.Debug("sent progress chunk")
		return
	}
	...
```

**唯一要改的地方**是 SSE 事件名：`sseEventTypeForChunk` 只从 payload 的 `event` 字段取名，EF 没有该字段 → 会 fallback 成 `"progress"`，与现有进度事件混在一起，前端无法区分。

```386:397:dac-apiserver/internal/handler/chat_handler.go
func sseEventTypeForChunk(chunk entity.StreamChunk) string {
	if chunk.EventType != "" {
		return chunk.EventType
	}
	// Progress JSON is the only source of event name from current A2A pipeline.
	if chunk.Progress != "" {
		if name := eventNameFromProgressJSON(chunk.Progress); name != "" {
			return name
		}
	}
	return "progress"
}
```

---

## 4. 需求决策

### 4.1 已拍板（v2.0）

| 编号 | 问题 | 决策 |
|---|---|---|
| **Q1** | 展示形态 | **上：图 + 执行树（70%），下：表格（30%）**。上半区用节点图 / 树形图展示委派层级与执行流程；下半区用表格（列：`turn` / `stage` / `agent` / `role` / `task` / `result` / `parent_execution_id` / `delegated_by`）列出全部任务，**顺序严格跟随树的遍历顺序**（深度优先先根遍历） |
| **Q2** | 展示位置 | **独立弹窗面板**。入口按钮置于「已思考」标题行右侧（与思考同级），点击弹出 |
| **Q3** | 实时性 | **实时增量**，边跑边看；不做「仅最终态」 |
| **Q5** | 颗粒度 | **所有 ExecutionTask 都展示**，不做 stage 过滤 |
| **Q5-b** | `final_answer` 呈现 | **展示节点**，但其正文**默认折叠**（节点显示终态标记，点开才看全文） |
| **Q6** | 子树默认状态 | **默认折叠**，点击展开 |
| **Q7** | 历史回放 | **暂不做** |
| **Q11** | 委派边 + 内部执行的重复节点 | **保留两个节点**，用缩进表达父子关系（见 §12.3） |
| **Q12** | 执行树层次补全 | **直接读 `parent_execution_id` 建树**（§12.2 实测已确认父子关系成立） |

**Q1 的取舍说明**：EF 数据天然适合两种视角——图的视角看清"谁委派谁"的层级结构，表格的视角看清"何时/何事/结果如何"的完整细节。原本的双栏方案（左树右时间线）虽然兼顾了两者，但信息密度偏高、需要在两栏之间来回切换。改为**上下布局**后：上半区（70%）用树形节点图展示委派关系与执行流程全貌，一眼看清 who delegated what；下半区（30%）用等宽表格严格按树的深度优先遍历顺序逐行列出所有任务的全部字段，方便快速扫描和对比。三七开让用户无需切换视角就能同时获得"全局结构"和"逐行细节"。

### 4.2 仍需确认

| 编号 | 问题 | 决策 |
|---|---|---|
| **Q8** | 多轮 Turn 呈现 | **每 Turn 一个分组标题**（`第 N 轮`），组内按 stage 排序，组尾显示 `turn_summary` 成败徽标 |
| **Q9** | 弹窗滚动行为 | 实时增量下**不因新节点跳动**：仅当用户已在底部时自动跟进 |
| **Q10** | 是否需要耗时 | EF **无时间戳字段**，本期不做；如需精确耗时需扩展 schema（协议变更） |

> Q8–Q10 为低风险默认值，已按推荐方案落定；如需调整可在实现前口头修改，不阻塞开工。

### 4.3 Q5「全都展示」的具体落地

"所有 ExecutionTask 都展示" 直接决定了两件事：

1. **不按 stage 过滤** —— `pre_exec` / `mid_exec_round_N` / `turn_summary` / `final_answer` 全部渲染
2. **`agent=NONE` 的节点也要展示** —— 来自 `_record_none_execution_task`，是"无可用 agent"的真实执行结论，用 ⚠ 样式区分

`final_answer` 的 `result` 与消息正文**完全重复**，因此按 **Q5-b** 处理：**节点仍然展示**（满足"全都展示"），但**正文内容默认折叠**，节点显示为终态标记（如 `最终答案 · 1,234 字`），点开才看全文。既不丢节点、又不重复占屏。

---

## 5. 详细设计

### 5.1 数据通道：新增独立 SSE 事件类型

**不改 EF schema**，通过"帧名前缀 → 事件名"特判让 apiserver 发独立事件：

```
[[DAC_EXECUTION_FLOW]] {json}
        │
        ▼  apiserver: extractDACFramePayload() 已能提取 payload
        │           新增：按帧名前缀判定 → StreamChunk.EventType = "execution-flow"
        ▼
event: execution-flow
data: {"schema_version":"v1","execution_id":"...", ...}
        │
        ▼  frontend: parse-chat-sse.ts 新增 kind
        ▼
{ kind: "execution-flow", payload: ExecutionFlowTaskPayload }
```

**为什么不给 EF payload 加 `event` 字段？** 因为它会污染 EF schema —— EF 是给 Planner 消费的严格协议，为 UI 加字段会破坏前置文档 §1.3 的职责划分。在 Go 侧按前缀特判更干净。

> 实现要点：`extractDACFramePayload` 目前只返回 `]]` 之后的内容，**丢掉了帧名**。需要让它（或新增一个函数）同时返回帧名，才能区分 `DAC_PROGRESS` / `DAC_EXECUTION_FLOW` / `DAC_ANSWER`。

### 5.2 后端改动清单

| # | 文件 | 位置 | 改动 |
|---|---|---|---|
| 1 | `orchestrator-agent/.../orchestrator_agent_semantic_group.py` | `stream_a2a_collect_forward_progress_frames` `~4061` | 收集 EF 的同时转发到 updater |
| 2 | `orchestrator-agent/.../orchestrator_agent_semantic_group.py` | `a2a_non_stream` `~4390` | **修 bug**：识别 EF 并转发，不再落入正文 |
| 3 | `orchestrator-agent/.../orchestrator_agent_semantic_group.py` | `a2a_tasks` 主循环 `~5417` | 同上：识别 EF 转发 |
| 4 | `routing-agent/routing_agent/server.py` | `~4779`（single-root） | 新增 `is_execution_flow_frame` 分支 → 转发 |
| 5 | `routing-agent/routing_agent/server.py` | `~3717`（multi-root） | 同上 |
| 6 | `dac-apiserver/internal/infrastructure/a2a/client.go` | `lineBuffer.feed` / `handleFramePayload` `~105`/`~207` | 帧名透传，EF 帧设 `EventType = "execution-flow"` |
| 7 | `dac-apiserver/internal/handler/chat_handler.go` | `sseEventTypeForChunk` `~386` | 已优先用 `chunk.EventType`，确认生效即可 |

**实现注意点**：

- 改动 #1–#3 需**区分 EF 转发与 progress 转发**，避免 EF 帧被当成 `DAC_PROGRESS` 混入现有 progress 事件。
- routing 侧需**新增** `is_execution_flow_frame`（前缀 `[[DAC_EXECUTION_FLOW]] `），且判定必须放在 `is_internal_dac_frame` **之前**。
- 改动 #2/#3 是**行为变更**，建议与开关一起灰度。

### 5.3 前端状态管理

参照现有 `progressList` 模式（`chat-store.ts` + `ChatMessage` + `AssistantMessageBody`）：

```
streamExecutionFlowBacking   → 流式累积（运行中）
streamExecutionFlowList      → 当前渲染用
ChatMessage.executionFlowList → 冻结到消息（流结束后）
```

新增 `frontend/src/lib/execution-flow.ts`（纯函数 + 单测，与 `chat-progress.ts` 对齐）：

| 函数 | 职责 |
|---|---|
| `interface ExecutionFlowTask` | 14 字段的 TS 映射（`schema_version` 校验 `v1`） |
| `groupByTurnAndStage(tasks)` | 按 `turn` 升序、`stage` 按 `pre_exec → mid_exec_round_N → turn_summary → final_answer` 排序 |
| `buildExecutionTree(tasks)` | 按 `parent_execution_id` 建树（对应 Python `build_tree`）；无 parent 的节点视为 root |
| `flattenTreeForTable(rootNodes)` | 对执行树做**深度优先先根遍历**，展平为表格行数组（每行附加 `indentLevel` 缩进层级）。表格的行顺序严格由树结构决定 |
| `nodeStatusOf(task)` | 派生状态：`done` / `unfinished`（`result` 空） / `unassigned`（`agent === "NONE"`） / `failed`（`turn_summary` + `result === "fail"`） |

**去重策略**：`turn_summary` / `final_answer` 在 orchestrator 与 skill-agent **两层都会产生**，需按 `execution_id` 去重（见 R5）。

### 5.4 渲染组件与交互

#### 入口按钮

放在 `ThinkingProcess` 标题行右侧。**注意**：现有标题行是**单个 `<button>`** 包住了整行：

```711:732:frontend/src/components/chat/ThinkingProcess.tsx
      <button
        type="button"
        className="w-full flex items-center py-2 text-left transition-colors select-none cursor-pointer"
        onClick={() => setUserExpanded((v) => !v)}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? "收起思考过程" : "展开思考过程"}
      >
        ...
      </button>
```

在里面再放按钮会产生 **`<button>` 嵌套 `<button>`**（非法 HTML + React 警告）。因此需要把标题行**重构为 flex 容器**，让"展开/收起思考"按钮与"执行地图"按钮成为**兄弟节点**：

```
┌────────────────────────────────────────────────────────────┐
│  已思考（用时 67 秒）⌄      [ 🗺 执行地图 (12) ]          │
└────────────────────────────────────────────────────────────┘
    ↑ 原 toggle button（占满剩余宽度）    ↑ 新按钮 → 开弹窗
```

按钮可带**节点计数徽标**（如 `执行地图 (12)`），运行中可加 shimmer 提示；无 EF 数据时**不渲染该按钮**（避免空入口）。

#### 弹窗面板

复用 `frontend/src/components/ui/dialog.tsx`（Radix），覆盖宽度/高度类：

```tsx
<DialogContent className="max-w-[min(1400px,95vw)] h-[min(90vh,900px)] flex flex-col gap-0">
```

**尺寸理由**：表格需要至少 14 个字段列宽（`execution_id`、`turn`、`stage`、`agent`、`role`、`task`、`result`、`reason`、`parent_execution_id`、`delegated_by` 等），过窄会导致横向滚动条频繁出现。1400px 在 16:9 2560×1440 屏上占比约 55%，比先前 1100px 更从容。高度 90vh 保证内容不挤。

新增 `frontend/src/components/chat/ExecutionMapPanel.tsx`：

```
┌─ 🗺 执行地图 ───── run-abc-123 ───────────────────────────── ✕ ─┐
│ ┌─ 上：图 + 执行树（70%）─────────────────────────────────────┐ │
│ │                                                             │ │
│ │    ┌─ own-1-user-agent-t1 ──────────────┐                   │ │
│ │    │ initiator · user-agent              │                   │ │
│ │    │ 用户名(张三)→lookup→用户ID          │                   │ │
│ │    │ ✓ 用户ID为 U001                    │                   │ │
│ │    └────────────────────────────────────┘                   │ │
│ │                    │ (委派）                                 │ │
│ │                    ▼                                        │ │
│ │    ┌─ pre-2-order-agent-t1 ─────────────┐                   │ │
│ │    │ delegatee ← user-agent              │                   │ │
│ │    │ 查询用户 U001 购买的商品ID列表       │                   │ │
│ │    │ ✓ PROD-001, PROD-003, PROD-016     │                   │ │
│ │    └─────────────────┬──────────────────┘                   │ │
│ │                      │ (re-parent)                           │ │
│ │                      ▼                                      │ │
│ │    ┌─ own-1-order-agent-t1 ─────────────┐                   │ │
│ │    │ initiator · order-agent             │                   │ │
│ │    │ U001→lookup→商品ID列表              │                   │ │
│ │    │ ✓ PROD-001, PROD-003, PROD-016     │                   │ │
│ │    └────────────────────────────────────┘                   │ │
│ │                                                             │ │
│ │    ┌─ turn-summary-t1 ─┐  ┌─ final-answer-t1 ─┐            │ │
│ │    │ success            │  │ 最终答案（默认折叠）│            │ │
│ │    └───────────────────┘  └───────────────────┘            │ │
│ │                                                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─ 下：表格（30%）───────────────────────────────────────────┐ │
│ │ #  execution_id            turn  stage        agent      ... │ │
│ │───┼────────────────────────────┼─────────────┼─────────────│ │
│ │ 1  own-1-user-agent-t1     1     pre_exec     user-agent  ...│ │
│ │ 2  pre-2-order-agent-t1    1     pre_exec     order-agent ...│ │
│ │ 3  own-1-order-agent-t1    1     pre_exec     order-agent ...│ │
│ │ 4  turn-summary-t1         1     turn_summary user-agent  ...│ │
│ │ 5  final-answer-t1         1     final_answer  user-agent  ...│ │
│ └─────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

**布局规则**：

- 上半区（70%）：用**树形图**展示——每个节点为一个圆角卡片，包含 `agent` / `role` / `task` / `result`。父子关系用箭头连线（非双栏左右分，而是自上而下的树形流式布局）。
- 下半区（30%）：用**等宽表格**展示，列包含 `execution_id` / `turn` / `stage` / `agent` / `role` / `task` / `result` / `parent_execution_id` / `delegated_by`，**行顺序严格按树的深度优先先根遍历**（与上图节点出现顺序一致）。
- 两区之间可拖动分隔条（`splitPanel`），默认 7:3。
- 上半区点击某个节点 → 下半区表格自动滚动到对应行并高亮。

**状态可视化**：

| 状态 | 条件 | 呈现 |
|---|---|---|
| 完成 | `result` 非空 | ✓ 绿色（节点图 + 表格行） |
| 未完成 | `result` 为空 | ○ 灰色 |
| 未派发 | `agent === "NONE"` | ⚠ 橙色（+"无人可执行"） |
| Turn 失败 | `stage === "turn_summary"` 且 `result === "fail"` |  红色徽标 |
| Turn 成功 | `stage === "turn_summary"` 且 `result === "success"` | ✅ 绿色徽标 |

**上下联动**：
- 上半区点击节点 → 下半区表格滚动到对应行并高亮
- 下半区点击表格行 → 上半区对应节点高亮
- 表格行按树的深度优先遍历顺序排列，缩进量由 `indentLevel` 控制

### 5.5 实时增量下的"进行中"表达

已选定 **Q3：实时增量**，弹窗开启时数据持续增长。但 EF 帧**无 `running` 态**（节点完成时才发一次），所以上半区树形图中不会出现"转圈中的节点"。处理方式：

1. **新节点淡入 + 末节点 shimmer** —— 复用 `ThinkingProcess` 已有的 `dacShimmer` 动画，视觉上表达"还在跑"
2. **滚动不跳动（Q9）** —— 新增节点时，仅当用户已在底部才自动跟进；用户手动上滚查看历史时不打扰
3. **（可选，Phase 3）** 用 DAC Progress 的 `event`/`agent_id` 与 EF 节点做**时序近似匹配**，补出进行中的占位行。因两者**没有共享 ID**，匹配只能是近似，故不列入本期

---

## 6. 分阶段实施

| 阶段 | 内容 | 风险 | 可独立验证 |
|---|---|---|---|
| **Phase 0** | 打通链路 + 开关。后端改动 #1–#6；前端仅在现有进度卡片补 `stage`/`result` 显示 | 低 | ✅ 抓 SSE 日志看到 `event: execution-flow` |
| **Phase 1** | 前端：`execution-flow.ts`（含 `flattenTreeForTable`）+ `parse-chat-sse.ts` 新 kind + store + `ExecutionMapPanel`（树上图 + 下表）+ 入口按钮（含标题行重构） | 中 | ✅ 本地跑通全链路渲染 |
| **Phase 2** | 体验打磨：上下联动（点击节点→表格定位）、`final_answer` 正文折叠、动画、分隔条可拖拽、表格缩进样式 | 低 | ✅ |
| **Phase 3** | 历史回放（§7）、running 态融合、耗时字段 | 中 | ✅ |

### Phase 0 开关

```
ENABLE_EXECUTION_FLOW_UI   # 默认关
```

**理由**：改动 #1–#3 触碰的是**所有 SG 编排的公共转发路径**，一旦出错会影响所有对话。必须可灰度、可回滚。开关关闭时行为与现状完全一致。

---

## 7. 历史回放（Phase 3，本期不做）

留档备查，需要时再启动。当前 think 只沉淀 progress 帧：

```4078:4080:routing-agent/routing_agent/server.py
        if not self.agent.is_progress_frame(text):
            return
        self._history_progress_frames.append(self._normalize_progress_frame_text(text))
```

```1:5:frontend/src/lib/history-think.ts
import type { ChatProgressPayload } from "@/lib/api-types"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"

const DAC_PROGRESS_PREFIX = "[[DAC_PROGRESS]] "
```

要做的改动：路由侧 `_append_history_progress_frame` 接纳 EF 帧 → 前端 `history-think.ts` 增 `[[DAC_EXECUTION_FLOW]] ` 分支。
**前置排查**：`think` 的产物是否会被重新喂给 LLM（若是，需先剥离再用）。

---

## 8. 风险与待验证假设

| # | 风险 / 假设 | 影响 | 处理 |
|---|---|---|---|
| R1 | **EF 泄漏进 LLM 正文**（§3.3，已确认存在） | 高：污染下游输入 | Phase 0 一并修（改动 #2/#3） |
| R2 | `execution_id` **跨 agent 可能碰撞** | 中：建树时错挂父子 / 去重误杀 | ✅ **已用真实数据验证：不碰撞**（见 §12.1） |
| R3 | `turn_summary` / `final_answer` **两层重复产生** | 中：重复展示 | 按 `execution_id` 去重（§5.3） |
| R8 | ~~`parent_execution_id` 全为 null、树挂不上~~ | — | ✅ **已撤回**：机制完整，跨 agent 层级链是通的（见 §12.2） |
| R9 | `turn_summary` / `final_answer` **不 emit**，导致跨 agent 看不到对方的 turn 总结 | 中：层级链上少两类元节点 | 见 §12.2.1，评估是否补 emit |
| R4 | 帧量大时**前端重渲染性能**（每帧一次 state 更新 + 全量分组重建） | 低 | 大批量帧压测；必要时按帧批量 flush |
| R5 | `stage` 排序假设 `mid_exec_round_N` 的 `N` 为数字（Python 侧有 `except ValueError` 说明出现过异常值） | 低 | 排序函数对非法值降级处理 |
| R6 | 帧**到达顺序 ≠ 执行顺序**（EF 与 progress 共用同一条流） | 中 | 一律按 `turn`/`stage` 重排，不依赖到达顺序 |
| R7 | 弹窗开启时**流仍在进行**，数据持续增长 | 低 | 弹窗内滚动位置不因新节点跳动（仅在用户已在底部时自动跟进） |

---

## 9. 验收标准（Phase 1）

1. 发起一次会触发**跨 agent 委派 + 多轮 Turn**的对话：
   - 「已思考」旁出现「执行地图」按钮（带节点计数）
   - 点开弹窗，**上半区树形图 + 下半区表格**同时正确呈现
   - 上半区树形图：节点卡片显示 agent / role / task / result，委派关系用箭头连接
   - 下半区表格：行顺序严格按树的深度优先先根遍历，包含 `execution_id` / `turn` / `stage` / `agent` / `role` / `task` / `result` / `parent_execution_id` / `delegated_by` 等列
   - 点击上半区节点 → 下半区表格滚动定位到对应行并高亮（反之亦然）
   - `turn_summary` 成败徽标正确；`agent=NONE` 用  区分
   - 委派子树**默认折叠**（Q6），点击可展开
   - `final_answer` 节点**展示但正文默认折叠**（Q5-b）
2. 运行中**实时增量**出现（Q3），无需刷新；且**用户上滚时新节点不打断**（Q9）。
3. **所有 ExecutionTask 都被展示**，无 stage 过滤。
4. 未开启开关时，UI 与现状**完全一致**（无回归）。
5. 无 EF 数据时**不渲染按钮**。
6. 纯函数单测覆盖：分组、建树、排序、去重、状态派生（用 §12 真实数据作 fixture）。

---

## 10. 附：字段 → UI 映射表

| EF 字段 | UI 用途 | 缺失时 |
|---|---|---|
| `execution_id` | React key / 建树引用 / 去重键 | 帧非法，丢弃 |
| `turn` | 表格列「轮次」 | 归入"未知轮次" |
| `stage` | 子分组标题（首次任务执行 / 补充执行 · 第N轮） | 按 stage 原文展示 |
| `agent` | 节点标题（左）；`NONE` 触发 ⚠ | `?` |
| `role` | 是否显示"被委派者"标签 | 按 initiator 处理 |
| `delegated_by` | 表格列「委派方」 | 不显示委派标签 |
| `task` | 节点标题主文案 | 空 |
| `result` | 状态图标 + 结果正文 | ○ 未完成 |
| `reason` | 折叠区内的"原因" | 隐藏该行 |
| `parent_execution_id` | 树上图建树 + 表格缩进 | 视为 root |
| `run_id` / `trace_id` / `user_id` | 弹窗头部 / 悬浮 / 复制 | 不显示 |
| `schema_version` | 版本校验 | 非 `v1` 则丢弃 |

---

## 12. 真实数据验证（2026-09-14）

抓取了一次真实 run 的 EF 快照（`max_loops>1` Turn 模式，由 `skill_agent_turn.py:896` 的 `render_execution_flow_table` 在**单个 skill-agent 进程内**打印）。

场景：查询「张三」购买的商品名称。7 个 ExecutionTask：

| # | execution_id | turn | stage | agent | role |
|---|---|---|---|---|---|
| 1 | `own-1-user-agent-t1` | 1 | pre_exec | user-agent | initiator |
| 2 | `pre-2-order-agent-t1` | 1 | pre_exec | order-agent | delegatee |
| 3 | `own-1-order-agent-t1` | 1 | pre_exec | order-agent | initiator |
| 4 | `mid-del-1-product-agent-t1-r1` | 1 | mid_exec_round_1 | product-agent | delegatee |
| 5 | `own-1-product-agent-t1` | 1 | pre_exec | product-agent | initiator |
| 6 | `turn-summary-t1` | 1 | turn_summary | user-agent | initiator |
| 7 | `final-answer-t1` | 1 | final_answer | user-agent | initiator |

### 12.1 ✅ R2 解除：`execution_id` 跨 agent 不碰撞

ID 的**每个前缀都内含 `{agent}`**，天然避免碰撞：

| 来源 | 格式 | 实例 |
|---|---|---|
| skill own | `own-{task_id}-{agent}-t{turn}` | `own-1-user-agent-t1` |
| skill pre 委派 | `pre-{task_id}-{agent}-t{turn}` | `pre-2-order-agent-t1` |
| skill mid 委派 | `mid-del-{task_id}-{agent}-t{turn}-r{round}` | `mid-del-1-product-agent-t1-r1` |
| turn_summary | `turn-summary-t{turn}` | `turn-summary-t1` |
| final_answer | `final-answer-t{turn}` | `final-answer-t1` |

对照 orchestrator 侧同样带 agent：`t1-pre-{agent}-{id}`、`t1-summary-{sg_label}`、`final-answer-{sg_label}`。
**结论：执行树的 ID 唯一性与去重键都成立。**

### 12.2 ✅ R8 撤回：`parent_execution_id` 机制完整，树能建起来（实测确认）

> ⚠️ **本节为修正内容。** 先前版本曾断言"`parent_execution_id` 实际全为 `null`、执行树挂不上"，**该结论错误**，已撤回。错误来源：用户提供的表格是**裁剪过的快照**（`_COL_KEYS` 只有 8 列，不含 `parent_execution_id`），我据此做出错误推断。回代码求证后确认机制完整；随后用户提供了**完整快照**（15 列，含全字段）直接证实。

#### 1. 实测验证（完整 15 列快照，2026-09-14）

| execution_id | role | agent | parent_execution_id | delegated_by |
|---|---|---|---|---|
| `own-1-user-agent-t1` | initiator | user-agent | — | — |
| `pre-2-order-agent-t1` | delegatee | order-agent | — | user-agent |
| `own-1-order-agent-t1` | initiator | order-agent | **`pre-2-order-agent-t1`** ✅ | user-agent |
| `turn-summary-t1` | initiator | user-agent | — | — |
| `final-answer-t1` | initiator | user-agent | — | — |

**树形结构**：

```
root: own-1-user-agent-t1          (initiator, root)
root: pre-2-order-agent-t1         (delegatee, delegated_by=user-agent)
  └── own-1-order-agent-t1         (initiator, parent=pre-2-order-agent-t1)  ← 父子成立 ✅
root: turn-summary-t1              (initiator, root)
root: final-answer-t1              (initiator, root)
```

**结论**：`buildExecutionTree` 会得到 4 个 root（含一条有子节点的委派边），而非 5 个平级节点。直接按 `parent_execution_id` 建树即可。

#### 2. 机制确认：跨 agent 委派的 re-parenting（已实现且被测试覆盖）

skill-agent 的委派路径**确实会设置 parent**，两条路径都有：

```7392:7398:dac/skill-agent/agent/skill_agent.py
                # Merge peer's Execution Flow — only set parent_execution_id
                # on the peer's root tasks (those without a parent already).
                pre_ef_id = f"pre-{task_item.id}-{agent_name}-t{turn}"
                for pt in peer_ef_tasks:
                    if pt.parent_execution_id is None:
                        pt.parent_execution_id = pre_ef_id
                        pt.delegated_by = self._self_planner_agent_name()
```

```5263:5267:dac/skill-agent/agent/skill_agent.py
            # Point G: mid-exec delegate task Execution Flow emit
            mg_ef_id = f"mid-del-{task.id}-{agent_name}-t{turn}-r{mid_exec_round}"
            for pt in peer_ef_tasks:
                if pt.parent_execution_id is None:
                    pt.parent_execution_id = mg_ef_id
                    pt.delegated_by = self._self_planner_agent_name()
```

**规则**：委派方 A 收到被委派方 B 返回的 EF 后，把 **B 的根任务**（`parent_execution_id is None` 的）挂到 A 自己创建的**委派边**（`pre-*` / `mid-del-*`）之下，并记录 `delegated_by=A`。

**测试已覆盖**（`tests/test_execution_flow.py`，权威语义）：

```510:531:dac/skill-agent/tests/test_execution_flow.py
        # 模拟 C 返回的 peer EF
        peer_ef_tasks = [
            ExecutionTask("peer-own-1", 1, "pre_exec", "agent-c", "initiator", "C task", "C result", "", None, None),
            ExecutionTask("peer-mid-1", 1, "mid_exec_round_1", "agent-c", "initiator", "C mid", "ok", "", None, None),
        ]

        wrapper_id = "mid-del-2-agent-c-t1-r1"
        for pt in peer_ef_tasks:
            if pt.parent_execution_id is None:
                pt.parent_execution_id = wrapper_id
                pt.delegated_by = _SELF
...
        assert full_ef[2].parent_execution_id == wrapper_id
        assert full_ef[3].parent_execution_id == wrapper_id
```

#### 机制二：turn-loop 通过 `upstream_context` 让下游 agent 追加自己的 EF

`skill_agent_turn.py` 里 `parent_execution_id` 确实只有 `=None`（屈指可数的几处），但**这并不影响建树**：

- turn-loop **自己不设置 parent**，它只负责：
  1. 把上游 EF 通过 `upstream_context["execution_flow"]` 读进来
  2. 追加本层的 own / turn_summary / final_answer 节点
  3. **把上游 EF 原样透传给下游**，供下游委派方去 re-parent
- 真正设置 parent 的是**下游 agent**（机制一），用的是 `peer_ef_tasks` 数组

链路是这样的：

```
A 委派 B
  └─ A 侧：_delegate_to_peer 收集 B 返回的 EF → peer_ef_tasks
           → A 把 B 的根节点 parent 设为 A 的委派边 pre-X-b-t1   ← 机制一
```

#### 机制的已知缺口（真实存在，需处理）

**若 B 的 own 节点从未被 emit，A 就收不到、也就无法 re-parent。** 而 turn-loop 的 `own_*` 节点确实**不 emit**：

| 节点 | 是否 emit | 位置 |
|---|---|---|
| `own_*` | ✅ emit | `skill_agent.py:7231`（base 版 `_execute_plan_and_mid_exec`） |
| `pre_*` 委派边 | ✅ emit | `skill_agent.py:7382` |
| `mid-del-*` 委派边 | ✅ emit | `skill_agent.py:5264` |
| `turn_summary` / `final_answer` | ❌ **不 emit** | `skill_agent_turn.py` 仅 `append` 不 `add_artifact` |

> 注意：**turn-loop 模式下 `_execute_plan_and_mid_exec` 与 base 版是同一个方法**（`SkillAgentExecutorWithTurns` 继承且未覆写），所以 `own_*` / `pre_*` / `mid-del-*` **仍然会 emit**。真正不 emit 的是 `turn_summary` / `final_answer`。

因此**跨 agent 的层级链是通的**，缺口只在 `turn_summary` / `final_answer` 这两类**元节点**上。

#### 对 §12 快照的正确解读

`pre-2-order-agent-t1` 在快照里看似叶子节点，**但它的子节点不在这份快照里**：
- 子节点是 **order-agent 进程内**产生的 own/parent 链
- 该 skill-agent 的 turn-loop 打印的 `_COL_KEYS` **原先只有 8 列**（层级信息被裁掉）；
  ✅ 已于 2026-09-14 扩展为 **15 列全字段**（见 §12.6），此后快照不再丢字段
- 生产链路上，order-agent 返回的 EF 会被上游 A 收集 → re-parent → **层级就建立起来了**

**结论：执行树直接由 `parent_execution_id` 建立，无需任何推断逻辑。**

### 12.2.1 修正后的待办

| # | 事项 | 优先级 | 状态 |
|---|---|---|---|
| 1 | 给 `_COL_KEYS` 加 `parent_execution_id` / `delegated_by` 两列，**重跑实测**确认层级 | 高（把推断变实测） | ✅ **已确认**（2026-09-14，用户提供完整 15 列快照，`pre-2-order-agent-t1` → `own-1-order-agent-t1` 父子成立） |
| 2 | 评估 `turn_summary` / `final_answer` 不 emit 是否要补（影响"跨 agent 看到对方的 turn 总结"） | 中 | 待办（不影响本 UI 需求） |
| 3 | 前端建树：**直接按 `parent_execution_id` 建树**，无 parent 的节点视为 root | 高 | 待办 |

### 12.3 语义重复节点：委派边 + 内部执行（与上一份快照互补）

order-agent 出现**两次**，这与此前理论分析完全一致：

| | execution_id | role | result |
|---|---|---|---|
| 委派边 | `pre-2-order-agent-t1` | delegatee | 3 条订单 + 商品ID列表 |
| 内部执行 | `own-1-order-agent-t1` | initiator | **同一内容**（父子挂载成功） |

**与上一份快照的互补关系**：
- 上一份：含 product-agent + mid-exec 委派（`mid-del-1-product-agent-t1-r1`），覆盖了 **mid-exec 委派模式**
- 本份：只含 order-agent + pre-exec 委派（`pre-2-order-agent-t1`），覆盖了 **pre-exec 委派模式**
- 两份数据合起来，完整覆盖了两种委派路径

UI 上会像"跑了两次"。**已决策：保留两个节点，用缩进表达父子**（见 §4.1 Q11）。

| | execution_id | role | result |
|---|---|---|---|
| 委派边 | `pre-2-order-agent-t1` | delegatee | 3 条订单 + 商品ID列表 |
| 内部执行 | `own-1-order-agent-t1` | initiator | **同一内容** |

UI 上会像"跑了两次"。**已决策：保留两个节点，用缩进表达父子**（见 §4.1 Q11）。

### 12.4 其他发现

- **`final-answer-t1` 的 `agent` 是 `user-agent`**，不是 orchestrator。说明最终答案由**被委派者**签发。建议 UI 标注"谁给出的最终答复"。
- **`turn-summary-t1` 的 `agent` 也是 `user-agent`**，且 `result=success`、`reason` 为空（数据里未显示原因）。
- **本次快照不含 orchestrator 层**。因为 `render_execution_flow_table` 是在 skill-agent 的 `SkillAgentExecutorWithTurns` 里调用、经 logger 打印，只包含**这个 skill-agent 自己累积的** EF（`turn_records` 的 `execution_flow_tasks`）。生产链路上 orchestrator / routing 会加入更多节点，最终 UI 数据是**上游合并后的结果**。

### 12.5 （已删除）

### 12.6 ✅ 快照表格已扩展为**全部 15 列**（2026-09-14 实施）

`render_execution_flow_table`（`skill-agent` 与 `orchestrator-agent` 两份同源副本）原先只打印 8 列
（`# | execution_id | turn | stage | agent | role | task | result`），**裁掉了 7 个字段**，
这正是 §12.2 误判"`parent_execution_id` 全为 null"的根因。

现已改为：

| 变更点 | 内容 |
|---|---|
| **列集合** | `_COL_KEYS = ["#"] + [f.name for f in fields(ExecutionTask)] + ["schema_version"]` —— **由 dataclass 定义派生**，新增字段自动进入日志，不会再被漏掉 |
| **列数** | 8 → **15**：新增 `reason`、`parent_execution_id`、`delegated_by`、`run_id`、`trace_id`、`user_id`、`schema_version` |
| **列宽** | 为每个新列补 `_COL_WIDTHS`；`_col_width()` 对未知列回退 `_DEFAULT_COL_WIDTH = 20`，渲染永不抛 KeyError |
| **空值处理** | `None` → 空串；`schema_version` 是帧级元字段（非 `ExecutionTask` 成员），行内缺失时回退为当前版本 `v1` |
| **表头** | 标题行标注 `(15 cols, all ExecutionTask fields)` |

> 说明：`schema_version` 并非 `ExecutionTask` 的成员（它在 `to_frame()` 的 payload 里），
> 但属于同一份帧快照的字段，因此也纳入表格，以保证"快照里不丢任何字段"。

---

## 13. 下一步

**§4 的 Q1–Q12 已全部拍板**。§12 的真实数据验证解除了 R2；**R8 已撤回**（§12.2，EF 层级机制经实测确认，执行树直接由 `parent_execution_id` 建立）。

实施顺序建议：

1. **Phase 0**（低风险、可独立验证）：打通链路 + `ENABLE_EXECUTION_FLOW_UI` 开关（默认关），后端改动 #1–#6，顺带修掉 §3.3 的正文泄漏 bug。
   **附带**：给 `render_execution_flow_table` 的 `_COL_KEYS` 加列 —— ✅ **已完成**（2026-09-14）：不止加 `parent_execution_id` / `delegated_by` 两列，而是**一次性扩到全部 15 列**，见 §12.6
2. **Phase 1**：前端解析 + 状态管理 + 树上图 + 下表格（含 `flattenTreeForTable`）+ `ExecutionMapPanel` + 入口按钮（含标题行重构）
3. **Phase 2**：体验打磨（上下联动定位、`final_answer` 折叠、动画、分隔条可拖拽、表格缩进样式）
4. **Phase 3**：历史回放

**单测建议**：把 §12 的 7 行真实数据作为 fixture（覆盖 own / pre 委派 / mid 委派 / turn_summary / final_answer 全部 5 种节点类型），并**补充带 `parent_execution_id` 的用例**（可参照 `tests/test_execution_flow.py` 的 `TestCrossAgentEFFullChain`）来锁定建树行为。