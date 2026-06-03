---
name: cross-sg-collaboration
overview: 在 SG Orchestrator 中新增纯路由/规划层的跨 SG 递归协作模式。SG 本身不处理数据（不生成 SQL、不查 DB），只做规划调度和结果汇总。真实工作由 SG Expert Agent 完成。支持 pre-execution 和 mid-execution 两种委托机制。
todos:
  - id: add-collab-branch
    content: 在 execute() 入口处新增 ENABLE_CROSS_SG_COLLABORATION 分支，跳转 execute_collaborative()
    status: completed
  - id: add-discover
    content: 在 OrchestratorAgent 类中新增 discover_collaborator_sgs()，复用现有 AgentRegistry 发现其他 SG
    status: pending
  - id: add-delegate
    content: 在 OrchestratorAgent 类中新增 delegate_to_collaborator_sg()，封装 A2A 委托调用
    status: pending
  - id: add-execute-collab
    content: 新增 execute_collaborative() 主入口 (pre-execution 三段 + mid-execution 四段循环)
    status: completed
  - id: add-execute-own
    content: 新增 _execute_own_task_via_expert()，纯 A2A 转发给 own Expert
    status: pending
  - id: add-mid-exec-pipeline
    content: 新增 _detect_delegation_needs() + _plan_mid_exec_delegation() + _dispatch_mid_exec_delegation() + _summarize_delegated_result()
    status: pending
  - id: verify-no-touch-existing
    content: 最终确认：0 行删除、0 行修改已有方法签名及实现
    status: pending
isProject: false
---

## 约束说明

1. **SG Orchestrator 不处理数据** — 不生成 SQL、不查数据库、不做知识检索。这些是 SG Expert Agent 的职责。SG Orchestrator 只做三件事：规划（Planner）、调度（Dispatch）、汇总（Summarize）。
2. **零修改已有代码** — 不删除任何一行、不改任何方法签名、不改任何方法内部实现。只在已有方法之后追加新方法。
3. **标准递归委托** — 不需要特殊的 tradeoff 分支。SG 能处理的自己找 Expert 处理，不能处理的委托给其他 SG。被委托的 SG 同理。每层汇总自己的结果 + 下游返回的结果，往上返回。
4. **Expert 归属严格隔离** — 每个 SG 只用自己的 sidecar Expert Agent（`_build_own_expert_card()`, localhost:10101）加 utility agents 来执行自有 task。绝不拿到其他 SG 的 Expert 去执行。SG1 如果委托给 SG2，SG2 会启动 SG2 自己的 Expert 来处理，SG1 完全不知道 SG2 内部的 Expert 是谁。

## 核心架构

```
                    SG1 (入口, hop_remaining=N)
                    │
                    ├── discover_collaborator_sgs() → [SG2_card, SG3_card]
                    │    每个 card 只有 name/description/skills，仅用于 Planner 路由
                    │
                    ├── Planner: 看到 [SG1_own_expert + utility_agents + SG2_card + SG3_card]
                    │    planner 把 SG2/SG3 当作"业务领域入口"来分配任务，
                    │    不是把它们当作 Expert Agent 来执行。
                    │
                    │   产出 tasks:
                    │     Task#1: "查华东库存" → agent=SG1_own_expert   (自己的 Expert 处理)
                    │     Task#2: "查竞品活动" → agent=SG2              (委托给 SG2)
                    │
                    ├── Task#1 → A2A → SG1 的 Expert Agent (sidecar, localhost:10101)
                    │                 └─ 返回结果
                    │
                    ├── Task#2 → delegate_to_collaborator(SG2, hop=N-1, chain=[SG1])
                    │             │
                    │             │  upstream_context:
                    │             │    delegator_plan: [所有 task 定义]
                    │             │    executed_tasks: [{id:1, status:"completed", result:"(完整结果)"}]
                    │             │    key_findings_so_far: "库存下降40%, 受影响SKU 50个..."
                    │             │    remaining_tasks: [Task#2 的定义]
                    │             │
                    │             ▼
                    │  SG2 (被委托, hop=N-1, chain=[SG1])
                    │    │
                    │    ├── 收到 upstream_context → 理解 "SG1 已经查了库存，现在需要竞品数据"
                    │    │                                  "并且库存下降40%，这些 SKU 需要重点对照"
                    │    │
                    │    ├── discover_collaborator_sgs() → [SG3_card]  (SG1 已被排除)
                    │    │
                    │    ├── Planner: 看到 [SG2_own_expert + SG3_card]
                    │    │   同时参考上游上下文中的 executed_tasks + key_findings
                    │    │   产出 tasks:
                    │    │     Task#1: "查竞品品牌数据(重点关注SKU-001~050)" → agent=SG2_own_expert
                    │    │     Task#2: "查广告投放效果(同期对照)" → agent=SG3
                    │    │
                    │    ├── Task#1 → A2A → SG2 的 Expert Agent (SG2 的 sidecar)
                    │    │
                    │    ├── Task#2 → 若 hop_remaining-1 > 0:
                    │    │              delegate_to_collaborator(SG3, hop=N-2, chain=[SG1,SG2])
                    │    │            否则: NONE 协议
                    │    │
                    │    └── 汇总: SG2_own + SG3返回 → 返回给 SG1
                    │
                    ├── Mid-execution: _detect_delegation_needs():
                    │       分析已有结果 → 发现还缺数据 → 构造新 task → 委托 SG4
                    │
                    └── 最终汇总: SG1_own + SG2 返回(含 SG3) + mid 委托 → 返回用户
```

## 两阶段委托

### 阶段一：pre-execution delegation（规划时就委托）

SG1 的 Planner 在规划时看到了所有协作 SG 的 agent card（name/description/skills）。
这些 SG card 被 Planner 当作**业务领域入口**——如果某个子任务的领域明显属于 SG2，
Planner 直接把 `task.agent` 设为 `"营销SG"`。但**执行时，SG1 不会去调用 SG2 的 Expert**，
而是把整个 task 委托给 SG2（A2A 流式调用），SG2 自己再启动它自己的 Expert 来处理。

```
SG1 Planner 的增强输入:
  - SG1 自己的 Expert Agent card (sidecar, localhost:10101)
  - utility agents (全局, 非树内)
  - SG2_card: { name: "供应链SG", description: "负责供应链、仓储、库存", skills: [...] }
  - SG3_card: { name: "营销SG", description: "负责营销、活动、广告", skills: [...] }

SG1 Planner 输出 TaskList:
  tasks: [
    {id:1, description:"查华东库存缺口", agent:"SG1_own_expert_name", depends_on:[]},
    {id:2, description:"查竞品近30天促销活动", agent:"营销SG", depends_on:[1]},
  ]
```

SG1 执行时拆分逻辑:
- `agent in own_names` → 走 `_execute_own_task_via_expert` → 发给 SG1 自己的 Expert
- `agent in collaborator_names` → 走 `delegate_to_collaborator_sg` → 把整个 task 发给对应 SG

### 阶段二：mid-execution delegation（执行中发现）

与 pre-execution 完全对等的三段式流程：检测 → 规划 → 派发 → 总结。
区别在于 planner 的输入 query 是基于已有结果合成的子问题，而非原始用户 query。

```
SG1 已完成 pre-execution:
  own_results:     {1: "华东库存下降40%，受影响的SKU 50个..."}
  delegated_results: {"SG2": "竞品同时期促销活动共12起，折扣力度最大达30%..."}

───────────────────────────────────
  Step 1: _detect_delegation_needs()
───────────────────────────────────

输入:
  - 原始 query: "分析华东销量下降原因"
  - 已有所有结果 (own + delegated)
  - 协作 SG 列表: [供应链SG, 营销SG, 财务SG, ...]

LLM 分析:
  "库存数据有了，竞品数据有了。但库存下降的根因需要查供应商排产情况，
   这是供应链SG的领地。另外财务SG可能没有直接关联。"

输出 (DetectionResult):
  needs_help: true
  synthesized_query: "查华东地区供应商排产异常数据，重点关注：
    1. 最近30天内产线故障或停机的供应商
    2. 对应的SKU补货时间线
    3. 预计排产恢复日期"
  target_sgs: ["供应链SG"]
  reason: "库存下降可能需要排产数据作为根因佐证"

───────────────────────────────────
  Step 2: 规划 (_plan_mid_exec_delegation)
───────────────────────────────────

SG1 调用 Planner.make_plan():
  query = synthesized_query
  agent_cards = [供应链SG_card]  (只包含检测出的目标 SG 的 card)
  group_memory = 增量（包含前序分析结论）

Planner 输出:
  tasks: [
    {id:1, description:"查华东供应商排产异常...", agent:"供应链SG"}
  ]

───────────────────────────────────
  Step 3: 派发 (_dispatch_mid_exec_delegation)
───────────────────────────────────

对每个 task:
  delegate_to_collaborator_sg(
    target_card = 供应链SG_card,
    task_description = task.description,
    hop_remaining = current_hop - 1,
    delegation_chain = [...] + ["SG1"],
    upstream_context = {
      own_results: {...},
      delegated_results: {...},
      mid_exec_round: 1,
      detection_reason: "..."
    }
  )

供应链 SG 收到后:
  → execute_collaborative() (is_delegated=true, mid_exec_round=1)
  → 如果供应链 SG 处理过程中也发现还需要其他 SG 帮忙:
      → 供应链 SG 自己的 _detect_delegation_needs() 触发 (递归)
      → 规划 → 派发 → 汇总 → 返回给 SG1

───────────────────────────────────
  Step 4: 总结 (_summarize_delegated_result)
───────────────────────────────────

SG1 收到 mid-exec 结果后:
  _summarize_delegated_result(
    query = 原始 query,
    own_results = {...},                    # 第一批的 own
    delegated_results = {                    # pre + mid 的全部
      "SG2": "...",                          # pre-exec 结果
      "供应链SG": "...",                    # mid-exec 结果
    },
    upstream_context = {...}
  )
  → 如果 allow_recursive=true 且 hop_remaining > 0:
      → 可以再次 _detect_delegation_needs → 进入下一个 mid_exec 轮次
  → 否则: 返回最终综合答案
```

## 具体实现

修改文件: `[dac/orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py](dac/orchestrator-agent/orchestrator_agent/orchestrator_agent_semantic_group.py)`

### 插入点一：execute() 入口分支（第 4752 行之前）

在 `if metadata and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:` 之前插入:

```python
        # ---- Cross-SG Collaborative Mode ----
        if os.getenv("ENABLE_CROSS_SG_COLLABORATION", "false").strip().lower() in ("true", "1", "yes"):
            await self.execute_collaborative(context, event_queue)
            return
```

### 插入点二：OrchestratorAgent 类新增方法

在 `_list_agent_cards_semantic_group` 之后、`list_agent_cards` 之前（第 2171 行附近）插入:

```python
    async def discover_collaborator_sgs(self) -> list[AgentCard]:
        """发现所有可协作的 SG Orchestrator agent（排除自己）。

        从 Agent Registry 全量拉取后过滤。每个 card 的 name/description/skills
        可以被 Planner 消费用于跨 SG 任务分配。
        """
        agent_registry_client = AgentRegistryClient()
        coll_collection = os.getenv(
            "SG_COLLABORATION_COLLECTION",
            "orchestrator_agent_cards",
        )
        try:
            raw = await agent_registry_client.alist_all_agents(
                collection_name=coll_collection,
            )
            all_cards = self._parse_agent_cards_from_response(raw)
        except Exception as e:
            logger.warning("Failed to discover collaborator SGs: %s", e)
            return []
        all_cards = self._filter_stale_semantic_group_agents(all_cards)
        my_name = (self.agent_card.name if self.agent_card else self.agent_name)
        cards = [c for c in all_cards if c.name != my_name]
        logger.info("Cross-SG: discovered %d collaborator SGs", len(cards))
        return cards


    async def delegate_to_collaborator_sg(
        self,
        target_card: AgentCard,
        task_description: str,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        hop_remaining: int = 0,
        delegation_chain: Optional[list[str]] = None,
        upstream_context: Optional[dict] = None,
    ) -> str:
        """向另一个 SG Orchestrator 发送结构化委托请求。

        使用 A2A SendStreamingMessage + metadata 传递上下文。
        下游 SG 收到后通过 collaboration_delegation=true 识别这是一个委托。
        """
        chain = list(delegation_chain or [])
        ctx = dict(upstream_context or {})

        send_payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task_description}],
                "messageId": uuid4().hex,
            },
            "metadata": {
                "collaboration_delegation": True,
                "hop_remaining": hop_remaining,
                "delegation_chain": chain,
                "upstream_context": ctx,
                "user_id": user_id,
                "run_id": run_id,
                "trace_id": trace_id,
                "delegator_name": self.agent_name,
                "skip_history_write": True,
            },
        }

        timeout = float(os.getenv("COLLABORATION_TIMEOUT", "3600"))
        response_parts: list[str] = []
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=target_card)
            streaming_req = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_payload),
            )
            async for chunk in client.send_message_streaming(streaming_req):
                text = self.get_response_text(chunk)
                if text:
                    response_parts.append(text)
        result = "".join(response_parts).strip()
        logger.info(
            "Cross-SG: delegation to %s done, result_chars=%d",
            target_card.name,
            len(result),
        )
        return result
```

### 插入点三：OrchestratorAgentExecutorSemanticGroup 类新增方法（第 4756 行之后，在 handle_capability_check return 之后）

```python
    async def execute_collaborative(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """跨 SG 协作执行入口。

        如果 metadata 中有 collaboration_delegation=true 标记，
        表示这是另一个 SG 委托过来的请求。否则是用户直接发起的原始请求。
        """

        # ---- 基础准备 ----
        query = context.get_user_input()
        metadata = dict(context.metadata or {})
        self.metadata = metadata

        is_delegated = metadata.get("collaboration_delegation") is True
        hop_remaining = int(metadata.get("hop_remaining", 0))
        delegation_chain = list(metadata.get("delegation_chain", []))
        upstream_context = dict(metadata.get("upstream_context", {}))
        user_id = str(metadata.get("user_id", ""))
        run_id = str(metadata.get("run_id", ""))
        trace_id = str(metadata.get("trace_id", ""))

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

        # ---- 发现协作 SG ----
        collaborator_cards = await self.agent.discover_collaborator_sgs()
        collaborator_names = {c.name for c in collaborator_cards}

        # ---- 规划：扩增 agent 池 ----
        own_cards = self.agent.agent_cards or []
        own_names = {c.name for c in own_cards}
        augmented_pool = own_cards + collaborator_cards

        group_memory = await self.agent.get_memory(query)
        plan = await self.agent.planner_agent.make_plan(
            query,
            augmented_pool,
            group_memory=group_memory,
        )

        own_tasks = [t for t in plan.tasks if t.agent in own_names or t.agent.upper() == "NONE"]
        delegation_tasks = [t for t in plan.tasks if t.agent in collaborator_names]

        # ---- 执行自有 task（委托给 Expert Agent 处理） ----
        own_results: dict[int, str] = {}
        for t in own_tasks:
            result = await self._execute_own_task_via_expert(
                t, query, user_id, run_id, trace_id, updater,
            )
            own_results.setdefault(t.id, "")
            own_results[t.id] = result

        # ---- pre-execution 委托 ----
        # 构建完整的上游上下文，包含：
        #  - 已执行的 task 定义（id/description/agent/status）+ 执行结果
        #  - 本层 Planner 产出的全部 task 清单（帮助被委派者理解问题全貌）
        own_task_context = [
            {
                "task_id": t.id,
                "description": t.description,
                "agent": t.agent,
                "status": "completed" if t.id in own_results else "delegated",
                "result": own_results.get(t.id, "") or "",
            }
            for t in plan.tasks
        ]

        delegated_results: dict[str, str] = {}
        for dt in delegation_tasks:
            _target_card = next(c for c in collaborator_cards if c.name == dt.agent)
            _can_delegate = (not is_delegated) or (current_hop > 0)
            if _can_delegate:
                _next_hop = (current_hop - 1) if is_delegated else (current_hop - 1)
                _new_chain = delegation_chain + [self.agent.agent_name]
                _ctx = {
                    "delegator_plan": [t.model_dump() for t in plan.tasks],
                    "executed_tasks": own_task_context,
                    "key_findings_so_far": "\n".join(
                        f"[Task#{tid}] {res[:300]}"
                        for tid, res in own_results.items() if res
                    ),
                    "remaining_tasks": [t.model_dump() for t in delegation_tasks],
                    "upstream_context": upstream_context,
                }
                result = await self.agent.delegate_to_collaborator_sg(
                    target_card=_target_card,
                    task_description=dt.description,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    hop_remaining=_next_hop,
                    delegation_chain=_new_chain,
                    upstream_context=_ctx,
                )
                delegated_results[dt.agent] = result
            else:
                delegated_results[dt.agent] = NONE_TASK_DESCRIPTION

        # ---- mid-execution: 递归检测 + 规划 + 派发 ----
        mid_exec_round = 0
        max_mid_exec_rounds = int(os.getenv("CROSS_SG_MID_EXEC_ROUNDS", "3"))
        while mid_exec_round < max_mid_exec_rounds:
            if not collaborator_cards:
                break

            # Step 1: detect
            detection = await self._detect_delegation_needs(
                query=query,
                own_results=own_results,
                delegated_results=delegated_results,
                collaborator_cards=collaborator_cards,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
            if detection is None:
                break

            synthesized_query = detection.get("synthesized_query", "")
            target_sg_names = detection.get("target_sgs", [])
            reason = detection.get("reason", "")
            if not target_sg_names or not synthesized_query:
                logger.info("Cross-SG: mid-exec detection returned empty targets or query")
                break

            # Step 2: plan
            target_cards = [c for c in collaborator_cards if c.name in target_sg_names]
            if not target_cards:
                logger.warning(
                    "Cross-SG: mid-exec detected targets not found: %s",
                    target_sg_names,
                )
                break

            mid_plan = await self._plan_mid_exec_delegation(
                synthesized_query=synthesized_query,
                target_cards=target_cards,
                group_memory=group_memory,
            )
            if mid_plan is None:
                logger.warning("Cross-SG: mid-exec plan returned None")
                break

            # Step 3: dispatch
            # 构建 upstream_context，包含本层的全部执行进展
            own_task_context = [
                {
                    "task_id": t.id,
                    "description": t.description,
                    "agent": t.agent,
                    "status": "completed" if t.id in own_results else "delegated",
                    "result": own_results.get(t.id, "") or "",
                }
                for t in plan.tasks
            ]

            upstream_ctx = {
                "delegator_plan": [t.model_dump() for t in plan.tasks],
                "executed_tasks": own_task_context,
                "key_findings_so_far": "\n".join(
                    f"[Task#{tid}] {res[:300]}"
                    for tid, res in own_results.items() if res
                ),
                "already_delegated": [
                    {"target_sg": name, "result": result or ""}
                    for name, result in delegated_results.items() if result
                ],
                "mid_exec_round": mid_exec_round + 1,
                "synthesized_query": synthesized_query,
                "detection_reason": reason,
                "upstream_context": upstream_context,
            }
            mid_results = await self._dispatch_mid_exec_delegation(
                plan=mid_plan,
                target_cards=target_cards,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                current_hop=current_hop,
                delegation_chain=delegation_chain,
                upstream_context=upstream_ctx,
                is_delegated=is_delegated,
            )
            for sg_name, result in mid_results.items():
                delegated_results.setdefault(sg_name, "")
                delegated_results[sg_name] = result

            mid_exec_round += 1

        # ---- Step 4: summary ----
        summary = await self._summarize_delegated_result(
            query=query,
            own_results=own_results,
            delegated_results=delegated_results,
            upstream_context=upstream_context,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
        )

        await updater.add_artifact(
            [TextPart(text=summary)],
            name="collaborative-result",
        )
        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id),
        )


    async def _execute_own_task_via_expert(
        self,
        task: PlannerTask,
        original_query: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        updater: TaskUpdater,
    ) -> str:
        """执行单个自有 task：找到对应的 Expert Agent，A2A 流式调用并收集结果。

        不生成 SQL、不查 DB —— 纯调度。
        """
        # NONE 协议
        if (task.agent or "").strip().upper() == "NONE":
            return NONE_TASK_DESCRIPTION

        # 从 agent_cards 中找匹配的 Expert
        agent_card = next(
            (c for c in (self.agent.agent_cards or []) if c.name == task.agent),
            None,
        )
        if agent_card is None:
            return ""

        send_payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task.description}],
                "messageId": uuid4().hex,
            },
            "metadata": {
                "user_id": user_id,
                "run_id": run_id,
                "trace_id": trace_id,
                "skip_history_write": True,
            },
        }

        result_parts: list[str] = []
        async with httpx.AsyncClient() as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            req = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_payload),
            )
            async for chunk in client.send_message_streaming(req):
                text = self.agent.get_response_text(chunk)
                if text:
                    result_parts.append(text)

        return "".join(result_parts).strip()


    async def _detect_delegation_needs(
        self,
        query: str,
        own_results: dict[int, str],
        delegated_results: dict[str, str],
        collaborator_cards: list[AgentCard],
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> Optional[dict]:
        """mid-execution Step 1: 检测是否需要其他 SG 的帮助。

        基于已有执行结果，用 LLM 判断还缺什么领域的数据，
        并合成一个给下游 SG 的子问题（synthesized_query）。

        Returns:
            None 如果不需要委托。
            dict 包含 synthesized_query、target_sgs、reason 如果需要委托。
        """
        if not collaborator_cards:
            return None

        own_text = "\n".join(
            f"[Task#{tid}]: {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}]: {res}" for name, res in delegated_results.items() if res
        )
        sg_options = "\n".join(
            f"- {c.name}: {c.description or ''}"
            for c in collaborator_cards
        )

        prompt = (
            "你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，"
            "判断是否还需要其他领域的补充数据。\n\n"
            "注意: 如果已有结果已经能完整回答原始问题，应返回 needs_help=false。"
            "只有当确实存在具体的数据缺口，且某个 SG 可以填补时，才返回需要帮助。\n\n"
            f"原始问题：{query}\n\n"
            f"本层自身执行结果：\n{own_text}\n\n"
            f"已完成委托结果：\n{del_text}\n\n"
            f"可委托的 SG 领域列表：\n{sg_options}\n\n"
            "请输出 JSON:\n"
            '{"needs_help": bool, "synthesized_query": "给下游 SG 的完整、具体子问题（含必要上下文）", '
            '"target_sgs": ["SG名称"], "reason": "为什么需要这些 SG 的数据"}\n'
            "只输出 JSON，不要 Markdown："
        )

        try:
            response = await self.agent.llm.ainvoke(
                [HumanMessage(content=prompt)],
                config={"callbacks": [langfuse_handler]},
            )
            content = response.content.strip()
            if "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            if not data.get("needs_help", False):
                return None
            return {
                "synthesized_query": data.get("synthesized_query", ""),
                "target_sgs": data.get("target_sgs", []),
                "reason": data.get("reason", ""),
            }
        except Exception as e:
            logger.warning("Cross-SG: mid-exec delegation detection failed: %s", e)
            return None


    async def _plan_mid_exec_delegation(
        self,
        synthesized_query: str,
        target_cards: list[AgentCard],
        group_memory: str = "",
    ) -> Optional[TaskList]:
        """mid-execution Step 2: 基于检测结果，调用 Planner 做任务规划。

        传入的是合成后的子问题 + 目标 SG 的 card 列表。
        Planner 可能产出单 task 或多 task（如果目标 SG 内部还需要再拆）。
        """
        if not target_cards or not synthesized_query:
            return None
        try:
            plan = await self.agent.planner_agent.make_plan(
                synthesized_query,
                target_cards,
                group_memory=group_memory,
            )
            return plan
        except Exception as e:
            logger.warning("Cross-SG: mid-exec plan failed: %s", e)
            return None


    async def _dispatch_mid_exec_delegation(
        self,
        plan: TaskList,
        target_cards: list[AgentCard],
        user_id: str,
        run_id: str,
        trace_id: str,
        current_hop: int,
        delegation_chain: list[str],
        upstream_context: dict,
        is_delegated: bool,
    ) -> dict[str, str]:
        """mid-execution Step 3: 派发 planning results 到目标 SG。

        对 plan 中的每个 task，找对应的 target_card，发起 delegate_to_collaborator_sg。
        返回 {sg_name: result} 字典。
        """
        results: dict[str, str] = {}
        name_to_card = {c.name: c for c in target_cards}

        for task in plan.tasks:
            agent_name = (task.agent or "").strip()
            target_card = name_to_card.get(agent_name)
            if target_card is None:
                logger.warning(
                    "Cross-SG: mid-exec dispatch, no card for agent=%s", agent_name,
                )
                continue

            can_delegate = (not is_delegated) or (current_hop > 0)
            if not can_delegate:
                results[agent_name] = NONE_TASK_DESCRIPTION
                continue

            next_hop = current_hop - 1
            new_chain = delegation_chain + [self.agent.agent_name]
            ctx = dict(upstream_context or {})

            result = await self.agent.delegate_to_collaborator_sg(
                target_card=target_card,
                task_description=task.description,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                hop_remaining=next_hop,
                delegation_chain=new_chain,
                upstream_context=ctx,
            )
            results[agent_name] = result

        return results


    async def _summarize_delegated_result(
        self,
        query: str,
        own_results: dict[int, str],
        delegated_results: dict[str, str],
        upstream_context: dict,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> str:
        """汇总自身结果 + 下游委托结果 + 上游上下文 → 返回上层。

        这是纯 LLM 汇总，不涉及数据处理。
        """
        own_text = "\n".join(
            f"[Task#{tid}] {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}] {res}" for name, res in delegated_results.items() if res
        )
        upstream_text = json.dumps(upstream_context, ensure_ascii=False) if upstream_context else "无"

        prompt = (
            "你是一个多层多 agent 协作的结果汇总器。请基于以下各层结果，"
            "给出完整、综合的回答。\n\n"
            f"原始问题：{query}\n\n"
            f"上游传入上下文：{upstream_text}\n\n"
            f"本层自身执行结果：\n{own_text}\n\n"
            f"委托给下游 SG 的返回结果（可能已包含多级汇总）：\n{del_text}\n\n"
            "请直接输出综合答案："
        )

        response = await self.agent.llm.ainvoke(
            [HumanMessage(content=prompt)],
            config={"callbacks": [langfuse_handler]},
        )
        return response.content.strip()
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENABLE_CROSS_SG_COLLABORATION` | `false` | 启用跨 SG 协作模式 |
| `CROSS_SG_MAX_HOP` | `5` | 最大递归跳数（入口 SG 设为 N，每层递减） |
| `COLLABORATION_TIMEOUT` | `3600` | 单次委托超时秒数 |
| `SG_COLLABORATION_COLLECTION` | `orchestrator_agent_cards` | Agent Registry 中查找协作 SG 的 collection |
| `CROSS_SG_MID_EXEC_ROUNDS` | `3` | mid-execution 最大轮次（R1=Track 1 命中委托，R2=Track 1 让位 → Track 2 兜底/收敛，R3=唯一一次纠错余量） |
| `ENABLE_ROUTING_AGENT_POOL` | `true` | 使用 Routing 传来的 `routing_agent_pool`；关闭则回退 legacy discover |
| `ENABLE_SG_CAPABILITY_REBROADCAST` | `true` | root 首次 make_plan 之后、replan/mid-exec/委派 SG 在 make_plan 前 SG 侧再广播 |
| `AgentRegistryCollection` | `orchestrator_agent_cards` | SG 侧 `broadcast_capability_check` 与 Routing 相同的 registry 集合 |
| `BROADCAST_TIMEOUT` | `30` | 单次 capability A2A 超时（秒） |

## Routing Agent Pool（simple 模式）

1. Routing `broadcast_capability_check` 构建 `routing_agent_pool`，转发 root SG 时附带 `routing_skip_broadcast_eligible=true`。
2. **仅 root SG 第一次** `make_plan` 复用该池，**不再** SG 广播。
3. 之后任意 `make_plan`（replan、mid-exec、委派下游 SG）由 [`broadcast_capability_check.py`](orchestrator_agent/broadcast_capability_check.py) 再广播刷新池。
4. **委派** `delegate_to_collaborator_sg` **不**传递 `routing_agent_pool` / `routing_skip_broadcast_eligible`。

## 关键设计原则

1. **SG 不处理数据** — `_execute_own_task_via_expert` 只做 A2A 转发给 Expert Agent，`_summarize_delegated_result` 只做 LLM 文本汇总。没有任何 SQL 生成、知识检索、数据库操作。
2. **递归一致性** — SG1→SG2→SG3 的每一层都使用完全相同的逻辑（同一个 `execute_collaborative`），只是 hop_remaining 递减。不存在特殊的底层逻辑。
3. **已有代码零触碰** — `execute()` 只在入口加一个 if 分支跳转；`a2a_stream()` / `a2a_non_stream()` / `make_plan()` / `get_plan()` / `a2a_tasks()` 等所有已有方法签名和内部实现原封不动。
4. **结果流向** — SG2 返回给 SG1 的结果是 SG2 自己汇总好的（含 SG2 own + SG3 返回的）。SG1 不需要知道 SG2 的委托细节。

