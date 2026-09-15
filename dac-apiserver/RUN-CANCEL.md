# 对话 Run 取消方案（UI Stop → 全链路停止大模型执行）

> 状态：设计稿（未实现）
> 范围：`frontend` 对话停止按钮、`dac-apiserver` Redis 协同 API、全部 A2A agent 的协作式退出
> 关联现状：前端已有 Stop 按钮，但只 `AbortController.abort()` 了 SSE，后端 routing / orchestrator / skill / code 等仍继续跑大模型。

---

## 1. 问题与目标

### 1.1 现状

一次对话的执行链是：

```
UI 点击发送
  → 前端生成 optimistic run_id（UUID）
  → POST /v1/chat/completions { stream:true, run_id }
  → dac-apiserver GetOrCreateRun(user_id, run_id, agent_id="routing-agent")
  → A2A StreamMessage(metadata={user_id, run_id}) → routing-agent
  → routing-agent 广播 / 转发，metadata 原样下传
  → orchestrator-agent / skill-agent / expert-agent / code-agent / chart-agent / doc-agent
  → skill_sdk ReAct 循环、sandbox、工具调用、再次 A2A 委派
```

`run_id` 已经是全链路主键：

| 层 | 现状 |
|---|---|
| 前端 | URL `/?run_id=`，`chat-store` 按 run_id 分 session；Stop 只 abort 本 session 的 fetch |
| apiserver | `runs` 表（ent `Run`：`id` / `user_id` / `agent_id`）；A2A metadata 只传 `user_id` + `run_id` |
| routing-agent | `execute()` 从 `context.metadata['run_id']` 取值，转发给下游 |
| 下游 agent | 全部从 metadata 读 `run_id`，写入 history / Langfuse / progress frame |
| Redis | **apiserver 未使用 Redis**。集群 Redis 只给 agent registry / heartbeat（db 0、2 等） |
| A2A `cancel()` | 所有 agent 均为 `raise Exception("cancel not supported")` |

因此用户点「停止」后：

1. UI 立刻停流、输入框恢复（体验已有）。
2. Hertz 侧 SSE 连接断开，最多打断 apiserver → routing-agent 的 **A2A 读流**。
3. routing-agent 及全部下游 **不会收到取消**，LLM / 工具 / sandbox 继续烧配额。

### 1.2 目标

1. UI 点停止后，**已经在跑的那次发送**上，turn / step / round / retry 在发起**下一发大模型**之前退出；当前这次 LLM HTTP 跑完即可。
2. 取消信号落在 Redis，带 **TTL**：用户点完停止就关页面 / 不管了，信号在过期后自行消失，不进 MySQL。
3. 点停止后立刻开 **新对话**（新 `run_id`）互不影响。
4. 同一会话里停止后再发下一条消息，也不得误杀新的 `chat_id`。
5. apiserver 提供 **写入停止** 与 **按 run_id + chat_id 查询是否该停** 的 API；agent 在执行循环里按需查询，命中则 `return`。

非目标（本期不做）：

- 打断已经发出去、正在等响应的单次 LLM HTTP（需在 `model_sdk` / httpx 里挂 cancel，作为后续增强）。
- 实现 A2A 协议的 `tasks/cancel`（所有 agent 的 `cancel()` 仍可先保持 not supported）。
- 把取消状态持久化到 `runs` 表。

---

## 2. 核心模型：`run_id` + `chat_id`

用户设想「一个对话有 run_id 和 agent_id，Redis 里记停止信号量」是对的。需要再补一层 **一次用户发送** 的 ID，否则同一会话连发会互相踩。这一层 **不叫 `turn_id`**：

| 已有概念 | 含义 | 为何不能复用名字 |
|---|---|---|
| agent **turn** | skill-agent / orchestrator 内部的 plan→execute 重试圈（`SkillAgentExecutorWithTurns`、`max_loops`、`turn_records`） | 一次用户发送里可以有多轮内部 turn |
| HTTP `request_id` | Hertz 中间件给 **单次 HTTP** 打的日志 ID（`X-Request-ID`） | 停止是另一次 POST，和开流 SSE 不是同一个 HTTP 请求 |
| `run_id` | 整段会话 | 停的是这一次发送，不是整段对话 |

因此引入 **`chat_id`**：一次用户点发送 / 重新生成所对应的整棵 A2A 执行树。仓库里目前没有这个字段。一次 `chat_id` 覆盖 routing → orchestrator → skill 里的 **多轮内部 turn**；用户点停止，这些内部 turn 全部该停。

`chat_id` 不是会话 ID。会话仍然是 `run_id`（URL `/?run_id=`、会话列表、`runs` 表）。

| 场景 | 只按 `run_id` 记停止 | 按 `(run_id, chat_id)` |
|---|---|---|
| 停止后开**新对话** | 新 UUID，本来就隔离 | 隔离 |
| 停止后**同一会话再发一句** | 新请求看到旧停止 key，会立刻退出 | 新 chat_id，旧停止不影响 |
| 停止 POST 与新 completions **乱序到达** | 可能误杀新发送 | cancel 只针对旧 chat_id |

### 2.1 标识

| 字段 | 谁生成 | 生命周期 | 作用 |
|---|---|---|---|
| `run_id` | 前端 `safeUUID()`，apiserver `GetOrCreateRun` 确认 | 整个会话 | 会话主键，已有 |
| `agent_id` | apiserver 创建 run 时写入（当前固定 `"routing-agent"`）；下游 agent 另有自己的 `Agent_Name` | 会话入口 agent | **不作为停止 key**。一次 run 会扇出到多个 agent，取消必须是 run + chat 级 |
| `chat_id` | **前端在每次 `send` / `startNew` / `regenerate` 时生成 UUID** | 一次用户发送对应的整条执行树（可含多轮 agent 内部 turn） | 停止信号的精确目标 |
| `user_id` | JWT | 用户 | 鉴权：只能停自己的 run |

`chat_id` 随 A2A metadata 与 `run_id` 一起下传：

```json
{
  "user_id": "...",
  "run_id": "...",
  "chat_id": "...",
  "agent_id": "routing-agent"
}
```

下游转发 metadata 时必须原样带上 `chat_id`（与今天转发 `run_id` 的方式相同）。capability_check / pre_make_plan 等短路径也带上，便于它们在循环里同样可查。

### 2.2 为什么不用「开新 chat 时 DEL 停止 key」

若 key 只有 `run_id`，新消息一开始就 `DEL dac:run:stop:{run_id}`，则：

- 旧 `chat_id` 还在跑的 agent 会发现 key 没了，**继续跑**（停止失效）。
- 若先 SET 再被新 chat DEL，一样救不了旧执行树。

所以：**停止 key 永不表示「整个 run 永久停」**，只表示「这个 `chat_id` 被用户叫停」。TTL 只负责垃圾回收。agent 内部的 turn 循环不另建停止 key，它们查的是外层同一个 `chat_id`。

---

## 3. Redis 设计

### 3.1 归属

- **只由 dac-apiserver 读写 Redis**。agent 不直连这块 key，统一走查询 API。
- 集群里已有 Redis（installer `redis-server`，agent registry 用 db 0 / 2）。apiserver 新增独立 db，避免和 `expert_agents` / `agent_heartbeats` 冲突。
- 建议：**db 1**，key 前缀 `dac:run:stop:`。可通过配置改。

apiserver 目前 `go.mod` 无 Redis 依赖，实现时引入 `github.com/redis/go-redis/v9`。

### 3.2 Key

```
dac:run:stop:{run_id}:{chat_id}
```

- Value（JSON，便于排障；查询侧也可只 `EXISTS`）：

```json
{
  "run_id": "…",
  "chat_id": "…",
  "user_id": "…",
  "agent_id": "routing-agent",
  "reason": "user_stop",
  "stopped_at": "2026-09-09T01:56:00Z"
}
```

- TTL：**默认 15 分钟**，配置项 `run_cancel.ttl`（建议 5m～30m，对齐 `routing_agent.session_timeout=30m` 的量级）。
- 重复点击停止：对同一 key `SET` + 刷新 TTL，幂等。
- 过期后 key 消失 ≡ 停止信号失效。仍在跑的极少数超长任务会恢复执行——这是 TTL 的明确取舍，用足够长的 TTL 覆盖「点完停止到 agent 看到」的窗口即可。

不使用「单 key 覆盖整个 run_id」：见 §2.2。

可选索引（非必须，排障用）：

```
dac:run:stop:index:{run_id}  → SET of chat_id，TTL 与成员相同或略长
```

查询 API 的热路径只需要 `EXISTS dac:run:stop:{run_id}:{chat_id}`。

### 3.3 配置

`configs/config.yaml` 新增：

```yaml
redis:
  host: "127.0.0.1"
  port: 6379
  password: ""
  db: 1                 # 与 registry db 错开
  tls: false

run_cancel:
  ttl: 15m
  # agent 查询接口使用的集群内共享令牌；空则仅允许集群内网访问（见 §4.3）
  internal_token: ""
```

环境变量前缀已有 `DAC_`：`DAC_REDIS_HOST`、`DAC_RUN_CANCEL_TTL` 等。集群侧可复用 `dac-configuration` ConfigMap 里现成的 `redis-host` / `redis-port` / `redis-password`。

---

## 4. dac-apiserver API

### 4.1 用户侧：登记停止（JWT）

```
POST /api/v1/chat/runs/:run_id/stop
Authorization: Bearer …
Content-Type: application/json

{ "chat_id": "<uuid>" }
```

行为：

1. 从 JWT 取 `user_id`。
2. `GetRun(run_id)`：不存在 → 404；`run.user_id != 当前用户` → 按现有惯例当 invalid（不泄露他人 run）。
3. `SET dac:run:stop:{run_id}:{chat_id}` + TTL。
4. 返回 `204`。重复调用仍 204。

`chat_id` 为空：拒绝（400）。不要提供「停掉该 run 上所有 chat」的默认行为，避免误杀紧接着发出的新消息。

权限：复用 `chat:use`（与发起对话同一能力）。在 `pkg/rbac/seeder.go` 把该权限码的路径用 `|` 扩成：

```
POST /v1/chat/completions | POST /api/v1/chat/runs/*/stop
```

不新增独立权限点，避免角色配置扩散。

### 4.2 用户侧：查询（可选，给 UI/排障）

```
GET /api/v1/chat/runs/:run_id/stop?chat_id=<uuid>
```

```json
{ "stopped": true, "expires_in_sec": 842 }
```

权限同 `chat:use` 或 `chat:history:read` 均可；建议跟 stop 写接口同一码。

### 4.3 Agent 侧：查询是否该停（高频、无用户 JWT）

Agent 进程没有用户 Token，不能走上面的 JWT 组。单独开内部接口：

```
GET /internal/v1/runs/:run_id/stop?chat_id=<uuid>
Header: X-DAC-Internal-Token: <run_cancel.internal_token>
```

```json
{ "stopped": false }
```

约束：

- **不**放进现有 `authorized` + RBAC 组。
- 必须带 `chat_id`；缺了视为未停止（`stopped: false`），避免「只传 run_id 就全停」。
- Redis / 网络失败时返回 `stopped: false`（**fail-open**）：取消是尽力而为，控制面挂了不应把所有对话打挂。打 warn 日志。
- `internal_token` 配在 apiserver 与各 agent 的同一套配置（或 env `DAC_RUN_CANCEL_INTERNAL_TOKEN`）。空 token 时：接口仍可用，但部署上应只暴露给集群内网。

实现要极轻：`EXISTS`，无 DB。这是 agent 热路径。

### 4.4 发起对话时带上 `chat_id`

现有：

```json
POST /v1/chat/completions
{ "messages": [...], "stream": true, "run_id": "…" }
```

扩展 `ChatCompletionRequest`：

```go
ChatID string `json:"chat_id"`
```

`ChatRequest` / A2A `SendMessageStreaming` metadata 增加 `chat_id`。空 `chat_id` 时 apiserver 自己生成一个 UUID（兼容旧客户端），并在响应头回传：

```
X-Run-Id: <run_id>
X-Chat-Id: <chat_id>
```

前端以自己生成的为准；header 用于对账。

### 4.5 SSE 断开时的兜底写入

`handleStreaming` 里客户端 abort 后 Hertz `ctx` 会取消。除前端主动 POST stop 外，apiserver 在 `ctx.Done()` 且该次请求已有 `(run_id, chat_id)` 时，**同样 SET 停止 key**。

这样即使用户杀进程、关标签、只 abort 没发出 POST，下游 agent 仍能查到停止。POST 与兜底 SET 完全幂等。

注意：不要在「正常 `[DONE]`」时写停止 key。

---

## 5. 前端改动

文件：`frontend/src/lib/chat-store.ts`、`page.tsx`（Stop 按钮已接 `onStop`）。

### 5.1 每次开流生成 `chat_id`

在 `processChatRequest` 里与 `AbortController` 一起：

```ts
const chatId = safeUUID()
int.chatId = chatId
body: { messages, stream: true, run_id: activeRunId, chat_id: chatId }
```

`stop(runId)`：

```ts
function stop(runId: string) {
  const int = internals.get(runId)
  const chatId = int?.chatId
  int?.abortController?.abort()   // 现有：立刻停 UI 流
  if (chatId) {
    void authFetch(`/api/v1/chat/runs/${runId}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId }),
      skipAuthRedirect: true,
    }).catch(() => { /* 停止是尽力而为 */ })
  }
  // 其余：isStreaming=false，冻结 thinkingElapsedSec（保持现有）
}
```

要点：

- **先 abort SSE，再 fire-and-forget POST**。UI 不能等 Redis。
- POST 失败只打日志，不 toast（用户已经看到停了）。
- `remove(runId)` 若该 session 仍在流，同样带当前 `chatId` 发一次 stop。

### 5.2 场景：点停止后立刻开新对话

前端今天已经是：

- 无 `run_id` 的首页发送 → `safeUUID()` 新 run → `startNew`。
- 侧栏「开启新对话」只是 `href="/"`，**不会** abort 旧 session 的 SSE。旧对话若仍在流，侧栏会继续转圈（`selectStreamingRunIds`）。

因此 key 隔离没问题：

```
run_A / chat_1  ──stop──►  SET dac:run:stop:{A}:{chat_1}  TTL 15m
run_B / chat_1' 立即发送 ──►  新 key，查 A 的停止信号不会命中
```

旧 routing-agent 树仍在查 `(A, chat_1)`，会陆续 return；新对话完全独立。不需要等 TTL，也不需要主动 DEL 旧 key。

**产品补丁（建议一并做）：** 点「开启新对话」或在首页发出新消息时，对 *当前仍在 streaming 的其它 run* 自动走一遍 `stop(oldRunId)`。理由：用户语义是「丢掉上一轮、开新的」，不是「后台挂着旧 LLM」。`chat_id` 隔离保证这次自动 stop 杀不到新 run。若不做这步，只点侧栏 `+`、不点停止，旧树会一直跑到自然结束。

### 5.3 场景：同一会话停止后再发一句

```
run_A / chat_1  ──stop──►  SET …:{A}:{chat_1}
run_A / chat_2  立刻 send──►  新 chat_id，EXISTS …:{A}:{chat_2} = 0
```

即使 stop 的 POST 比新的 completions 晚到，也只 SET `chat_1`，杀不到 `chat_2`。

`send()` 现有守卫 `if (session.isLoading || session.isStreaming) return`：点停止后 `isStreaming=false`，可以马上发下一条。无需额外排队。

### 5.4 多 session

`chat-store` 已按 run_id 隔离 abort。停止只停当前 `runId`，侧栏里另一个正在流的会话不受影响。

---

## 6. Agent 协作退出（LLM 路径检查点）

停止的对象不是「还没进 `execute()`」，而是 **已经在跑、但逻辑里还有很多 turn / step / round / retry**。检查点因此打在 **下一发大模型之前**，不是 `execute()` 入口，也不在 SSE token 流中间掐断。

当前这次 `ainvoke` / `astream` 跑完；循环头或 `invoke_llm_with_tool` 的下一 attempt 看到停止则 `return`，不再开下一轮 LLM、不再 replan、不再 mid-exec。

查失败（超时、5xx）= 未停止（与 §4.3 fail-open 一致）。不杀已在跑的 sandbox 子进程；停止后不再起新的 `plan_cmd`。

### 6.1 共享调用闸（五个 agent 共用的最内层）

下列文件是拷贝关系，结构化 tool-call 几乎都走这里。在 **每一次 attempt 的 `ainvoke` 之前** 查停止，能盖住该 agent 里大部分 LLM，而不用改每个业务函数：

| 组件 | 文件 | 循环 | 下一发 LLM |
|---|---|---|---|
| code-agent | `agent/tool_call_utils.py` `invoke_llm_with_tool` | `for attempt in range(1, max_attempts+1)`（默认含 `retry=2`） | `_invoke_single_attempt` → `llm_with_tool.ainvoke` |
| doc-agent | 同上（独立拷贝） | 同上 | 同上 |
| expert-agent | `agent/tool_call_utils.py`（无 attempt 循环，单次 ainvoke） | 无外层 retry；SD 侧业务自己 retry | `llm_with_tool.ainvoke` |
| orchestrator-agent | `orchestrator_agent/tool_call_utils.py` | 单次 ainvoke | 同上 |
| skill-agent | `agent/tool_call_utils.py` | 单次 ainvoke | 同上 |

**不走这个函数、必须在外层循环另标的直接调用：** `self.llm.ainvoke` / `astream`、`chain.ainvoke`、ReAct `_ainvoke_ai_message`、skill_sdk `_ainvoke`。下面按组件列出。

命中后：打 `[RunCancel] run_id chat_id`；循环 `return`；不要当 failure 触发 orchestrator replan（`suggested_retry_action=abort`）。

### 6.2 共享查询客户端

检查点只调用同一客户端，短 GET，进程内缓存约 300ms：

```python
async def should_stop(run_id: str, chat_id: str) -> bool: ...
```

`run_id` / `chat_id` 从该次请求的 `metadata` 读（与现有 LLM span 一样）。空则视为不停止。

### 6.3 code-agent

文件：`code-agent/agent/code_agent.py`。外层是 **step 循环**（默认 `max_steps=5`），observe 不通过则 requery 进入下一 step。

| 层级 | 位置 | 循环 | 检查点（下一发 LLM 前） |
|---|---|---|---|
| step 外圈 | `CodeAgent.run` ~5339 | `while current_step < max_steps and state != FINISHED` | 每圈 `step()` **之前**。停则不再 requery / 下一 step |
| step 内 | `CodeAgent.step` ~4941 | 单次 step 内串行多段 LLM | 每一段 LLM 前（或依赖 6.1 的 `invoke_llm_with_tool`） |
| skill 先行 | `_try_skill_answer` → `_run_skill_plan_and_run` | 见 §6.8 skill_sdk | 进入 `plan_and_run` 前；sdk 内部另有 step |
| 定位文件 | `locate_files` ~2241 | 一次 tool-call（utils 内可 retry） | `invoke_llm_with_tool`（locate_files） |
| 审查文件 | `observe_locate_files` ~2319 | 同上 | `invoke_llm_with_tool` |
| 关键词 | `extract_keywords` ~4102 | 同上 | `invoke_llm_with_tool` |
| 片段筛选 | `search_relevant_code_segments` 等 | 同上 | `invoke_llm_with_tool` |
| 片段打分 | `tools/snippet_llm_score.py` | `for` 分批 | 每批 `invoke_llm_with_tool` 前 |
| 生成回答 | `answer_with_code` ~4926 | **不走** tool_call_utils | `chain.ainvoke` 前（直接 LLM） |
| 验证回答 | `observe_common` ~2477 | tool-call | `invoke_llm_with_tool` |
| grep skill | hybrid_search 方案 A | skill_sdk ReAct | §6.8 |

`answer_model=original` 时跳过回答/observe LLM，step 内主要剩检索侧 LLM；step 外圈仍要查，避免空转 max_steps。

### 6.4 doc-agent

文件：`doc-agent/agent/doc_agent.py`。同样是 **step 循环**（默认 `max_steps=5`）。

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| step 外圈 | `DocAgent.run` ~1586 | `while current_step < max_steps` | 每圈 `step()` 前 |
| 知识粗筛 | `get_knowledge` ~1174 | 按 batch `asyncio.gather`；空结果可再筛 | 每批评分 LLM 前（`knowledge_llm_score` → `invoke_llm_with_tool`） |
| 生成回答 | `invoke_unstructured` ~754 | 一次 | `invoke_llm_with_tool` 或 `self.llm.astream` 前 |
| 验证 | `observe_unstructured` ~911 | 一次 | `invoke_llm_with_tool` 前 |

`answer_model=original` 时跳过 unstructured/observe，仍可能跑 `get_knowledge` 的评分 LLM。

### 6.5 expert-agent

#### Semantic Domain（SQL 专家）

文件：`expert-agent/agent/expert_agent_semantic_domain.py`。注释写明约 **13 处** `invoke_llm_with_tool`。外圈仍是 step。

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| step 外圈 | `ExpertAgent.run` ~3963 | `while current_step < max_steps` | 每圈 `step()` 前（observe 失败会 requery 进下一 step） |
| 任务分流 | `invoke_structured_task_analyze`（`step` ~3228） | 一次 | tool-call：是否走 SQL |
| 选表 / 生成 SQL / 改写 SQL 等 | `select_tables`、`generate_sql`、`generate_sql_simple` 及 dictionary 模式其它 tool（约 #1–#8） | 单步内串行 | 各 `invoke_llm_with_tool` 前（6.1 一处即可） |
| SQL 空结果重试 | `get_knowledge` ~2913 | `for retry_idx in range(1, max_empty_retries+1)`（最多 3） | 每轮重试的 batch 评分 LLM 前 |
| observe SQL | `observe_sql` ~2536 | 一次（step 内可能调用两次） | `invoke_llm_with_tool`（observe_sql_result） |
| observe 通用 | `observe_common` ~2671 | 一次 | `invoke_llm_with_tool`（observe_answer） |
| 流式回答 | ~1690 `self.llm.astream` | 一次 | **不走** utils：`astream` 前 |

#### Semantic Group（组内 ReAct）

文件：`expert_agent_semantic_group.py` + `react.py`。

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| step 外圈 | SG `run` ~2575 | `while current_step < max_steps` | 每圈 `step()` 前 |
| 能力/选路 | SG 内 `invoke_llm_with_tool` ~2035 | 视路径 | tool-call 前 |
| ReAct 主循环 | `ReActRunner.run` ~1492 | `for step_idx in range(react_max_steps)` 默认 20 | **每步决策 LLM 前**（`_ainvoke_ai_message`） |
| ReAct 同步重试 | `_ainvoke_ai_message` ~442；`run` 内 `while True` ~1517（compaction overflow） | attempt / compact-retry | 每一次 `llm.ainvoke` 前 |
| 步内分析 | `analyze_step` ~1341 | 每步可选 | bind_tools + `_ainvoke_ai_message` 前 |
| 逼近上限强制 finish | ~2036 `react_max_steps_force_finish` | 一次 | finish LLM 前 |
| compaction 摘要 | `compaction/prepare.py` `_ainvoke_plain` | overflow 时 | 摘要 LLM 前 |

ReAct 步内还会 A2A 调 code/doc 等；**下一发 LLM** 在子 agent 自己的检查点。本组只拦 ReAct 决策 LLM 和本进程其它 LLM。

### 6.6 orchestrator-agent

两个 executor 结构平行：先 **make_plan（attempt 循环）**，再 **execution round / retry 循环**（`retry_count <= max_loop_count`），SG 另有 **mid-exec round**。

#### Semantic Domain

文件：`orchestrator_agent_semantic_domain.py`

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| 规划 | `make_plan` ~1346 | `for attempt in range(1, make_plan_max_attempts+1)` | 每次 **`self.llm.ainvoke`** 前（不走 utils） |
| 执行/重试圈 | 执行计划 ~3139 | `while retry_count <= max_loop_count` | **每一 execution round 开头**（下一轮 replan/再跑 task 前） |
| 依赖预检 | `_preflight_dependency_check` ~1857 | 每个 task | `invoke_llm_with_tool` 前 |
| 能力探测 | capability 路径 | 广播后的 LLM 判定 | `invoke_llm_with_tool` 前 |
| LocalSkill | `_run_local_skill` → skill_sdk | 见 §6.8 | `plan_and_run` 内 |
| 结果评估 / replan | retry 决策、outcome eval | 每 round 末 | 评估 LLM / 再 `make_plan` 前 |

#### Semantic Group

文件：`orchestrator_agent_semantic_group.py`

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| 规划 | `make_plan` ~1792 | `for attempt ... make_plan_max_attempts` | 每次 `self.llm.ainvoke` 前 |
| 执行/重试圈 | ~4567 | `while retry_count <= max_loop_count` | 每 round 开头（progress：`group_execution_round_started`） |
| mid-exec | collab mid-exec ~7686 | `while mid_exec_round < max_mid_exec_rounds` | **每 round 的 detect / select / plan LLM 前**（注释写明否则会浪费 LLM） |
| 能力/评估 | 多处 `invoke_llm_with_tool`（~2618、4014、6204、8815、9619） | 按路径 | 各 tool-call 前 |
| 总结 | ~10033 | 一次 | `self.llm.ainvoke` 前 |
| LocalSkill | 同 SD | §6.8 | |

A2A 委派下游（code/doc/expert/skill）本身不是本进程 LLM；停本 orchestrator 的意义是：**不要再 replan、不要再开下一 mid-exec round、不要再 make_plan attempt**。下游靠它们自己的检查点停。

### 6.7 skill-agent

文件：`skill_agent.py`、`skill_agent_turn.py`。`max_loops>1` 时是 **Turn 循环**；每 turn 内部仍是 make_plan + 执行 + **mid-exec round**。

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| Turn 外圈 | `SkillAgentExecutorWithTurns.execute` ~444 | `while total_turns < max_loops` | **下一 turn 的 make_plan / 执行前** |
| 规划 tool-call | `make_plan` cmd 路径 ~1900 | `for attempt in range(1, make_plan_max_attempts+1)` | 每次 `invoke_llm_with_tool`（make_plan_cmd）前 |
| 规划纯文本 | `_ainvoke_plain_plan` ~1771、~1975 | `for attempt` + 失败再 `self.llm.ainvoke` | 每次 **直接 ainvoke** 前 |
| mid-exec | `_execute_plan_and_mid_exec` ~6587 | `while mid_exec_round < max_mid_exec_rounds` | 每 round 的 detect/plan LLM 前 |
| 能力 / 总结 / 评估 | ~3782、4894、5070、5328、5531 等 | 按路径 | `invoke_llm_with_tool` 或 `llm.ainvoke` 前 |
| 本地 skill | LocalSkill → skill_sdk | §6.8 | |

`max_loops=1` 时没有 turn 外圈，仍有 make_plan attempt 与 mid-exec round。

### 6.8 被上述 agent 调用的 skill_sdk（innermost ReAct）

skill-agent LocalSkill、orchestrator LocalSkill、code-agent skill-first / grep read-code 都会进 `skill_sdk/skill/runner.py`。

| 层级 | 位置 | 循环 | 检查点 |
|---|---|---|---|
| 换 skill 重试 | `_plan_and_run_with_planner` ~2612 | `for attempt in range(1, plan_and_run_max_attempts+1)` | 下一次 `make_plan` LLM 前 |
| 规划 | `make_plan` | 内部 tool-call / ainvoke | 该次 LLM 前 |
| ReAct step | `run()` ~1606 一带 | `for step` 至 `max_steps`；步内 `while True` compaction | **每 step 的 `_ainvoke(llm_with_tools, ...)` 前**；compact 后再 invoke 也要查 |
| 工具 | `_execute_prepared_tool` / `_dispatch` | 每 tool | 非 LLM；可选：下一 tool 前停，避免空转。`plan_cmd` 子进程：当前这次跑完，不再起新的 |

### 6.9 覆盖范围（本期五个组件）

需要按上表接检查点：

- `code-agent`
- `doc-agent`
- `expert-agent`（SD step + SG ReAct）
- `orchestrator-agent`（SD + SG：make_plan attempt、retry round、mid-exec round）
- `skill-agent`（turn、make_plan attempt、mid-exec）
- 以及它们共用的 `skill_sdk` runner

本期清单不含 routing-agent / chart-agent（未列入本次排查）。`execute()` **不作为**停止检查点。

### 6.10 A2A `cancel()`

本期不依赖。Redis 查询仍是真相源。下游 fan-out 靠各叶子自己的 LLM 循环检查点，不靠父 `execute` 返回。

---

## 7. 时序

### 7.1 停止

```
用户点击 Stop
  ├─ abort() SSE                         # UI 立即停
  └─ POST /api/v1/chat/runs/{run}/stop {chat_id}
        └─ Redis SET …:{run}:{chat} EX 900

并行：Hertz ctx cancel
  └─ apiserver 兜底 SET 同一 key

routing / orchestrator / skill / code … 在 **下一发 LLM 检查点** GET /internal/…/stop?chat_id=
  └─ stopped=true → 结束当前 turn/step/round，不再调用大模型
```

### 7.2 停止后立刻新对话

```
Stop(run_A, chat_1)  → SET stop A/chat_1
New chat → run_B, chat_1'
  POST /v1/chat/completions { run_id:B, chat_id:chat_1' }
  agent 查询 B/chat_1' → false → 正常执行
  旧树查询 A/chat_1 → true → 陆续退出
```

### 7.3 同会话停止后再发送

```
Stop(run_A, chat_1)  → SET stop A/chat_1
Send(run_A, chat_2)  → completions 带 chat_2
  查询 A/chat_2 → false
  迟到的 stop POST 仍只写 A/chat_1
```

---

## 8. 失败与边界

| 情况 | 行为 |
|---|---|
| Redis 宕机 | 写 stop 返回 503；agent 查询 fail-open。UI 仍 abort SSE（体验与今天相同，只是后端停不掉） |
| 停止 POST 丢失 | 依赖 SSE `ctx.Done()` 兜底 SET |
| `chat_id` 未传到某下游 | 该下游查不到停止，会跑完。所以 metadata 转发是验收项 |
| TTL 过了任务还在跑 | 会继续。TTL 配 ≥ 典型剩余执行时间 |
| 用户停别人的 run | GetRun 校验 user_id，拒绝 |
| capability_check 广播 | 可查 stop；命中则不要再打下游。这些调用短，漏检一次可接受 |
| 非流式 `/v1/chat/completions` | 同样接受 `chat_id`，同样在 ctx cancel / 客户端断开时 SET |

---

## 9. 实现切片（建议顺序）

1. **apiserver**：Redis 客户端、config、`RunCancelStore`（SET/EXISTS）、用户 POST/GET、internal GET、RBAC 路径、SSE 断开兜底、A2A metadata 增加 `chat_id`。实现放进已有空目录 `internal/infrastructure/cancel/`。单测用 miniredis 或接口假对象。
2. **frontend**：`chat_id` 生成、completions body、`stop()` POST；新对话时自动 stop 仍在流的旧 run。手工验：停、立刻新对话、同会话再发、只点「开启新对话」不点停止。
3. **共享 `should_stop` 客户端** + 五个 agent 的 `invoke_llm_with_tool` 闸（每次 attempt 的 ainvoke 前）+ skill_sdk ReAct step。
4. **外圈循环头**：code/doc/expert SD 的 `run()` step while；orchestrator / skill 的 make_plan attempt、retry round、turn、mid-exec round；expert SG 的 ReAct `for step_idx`。
5. **直接 ainvoke 点**：orchestrator/skill `make_plan` 的 `self.llm.ainvoke`、code `answer_with_code` 的 `chain.ainvoke`、ReAct `_ainvoke_ai_message`。
6. 部署：apiserver Redis db、internal token、agent env。

每一步可独立上线。agent 未接检查点时行为与今天相同；接上后停止延迟约为「当前这发 LLM 结束 + 下一循环头」。

---

## 10. 验收

1. 流式对话中点停止：UI 立即停；当前这发 LLM 结束后，五个 agent 的 turn/step/round/retry **不再发起下一发**，日志有 `[RunCancel]`。
2. 点停止后立刻新对话：新 `run_id` 正常回答；旧 run 的 LLM 停。
3. 不点停止、直接「开启新对话」再发送：旧 run 仍被自动 stop，新 run 正常。
4. 同一 `run_id` 停止后再发：新回答正常，不被旧停止 key 误杀。
5. 点停止后关页面：不依赖 POST 成功（SSE 断开兜底），agent 仍退出；TTL 到期后 Redis key 消失。
6. 未点停止：对话完整结束，Redis 无 stop key。
7. 内部查询不带用户 JWT，带错 token 拒绝；带对 token + 未停止的 chat 返回 `{stopped:false}`。

---

## 11. 与现有代码的锚点

| 点 | 位置 |
|---|---|
| 前端 Stop | `frontend/src/components/chat/ChatInput.tsx` → `page.tsx` `handleStop` → `chat-store.stop`（仅 abort） |
| 开流 | `chat-store.processChatRequest` → `POST /v1/chat/completions` |
| 创建 run | `internal/infrastructure/database/chat_repository.go` `GetOrCreateRun` |
| A2A 下发 | `internal/infrastructure/a2a/client.go` metadata `user_id`/`run_id` |
| Chat 路由 | `internal/router/router.go`：`/api/v1/chat/*`、`/v1/chat/completions` |
| 取消包占位 | `internal/infrastructure/cancel/`（空目录，无引用；实现落这里） |
| 权限 | `pkg/rbac/seeder.go` `chat:use` |
| routing 入口 | `routing-agent/routing_agent/server.py` `execute()` |
| agent cancel 空实现 | 各 agent `async def cancel` → `cancel not supported` |
| innermost LLM 循环 | 见 §6：各 agent step/turn/round + `tool_call_utils` + `skill_sdk` runner |
| 集群 Redis | installer `dac-configuration`：`redis-host` / `redis-port` / `redis-password`；registry 占用 db 0、2 |

---

## 12. 决策摘要

1. 停止信号只进 Redis，带 TTL，不进 MySQL。
2. Key = `(run_id, chat_id)`，不是光 `run_id`；`agent_id` 只作审计字段。
3. apiserver 负责 SET / EXISTS；agent 只调内部查询 API，不直连这组 key。
4. 前端每次发送生成 `chat_id`；停止 = abort SSE + POST stop；SSE 断开再兜底写一次。
5. 新对话靠新 `run_id` 隔离；同会话连发靠新 `chat_id` 隔离。侧栏开新对话应对仍在流的旧 run 自动 stop。
6. 停止检查点在 **下一发大模型之前**（turn / step / round / retry / tool-call attempt），**不在** `execute()` 入口，也不中断当前这次 API。
7. 查询失败 fail-open；停止接口鉴权必须校验 run 归属。
