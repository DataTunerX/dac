import json
import logging
import sys
from pathlib import Path
import click
import httpx
import uvicorn
import os
import asyncio
import re
import hashlib
import time as _time
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Any, AsyncIterable, Awaitable, Callable, ClassVar, Dict, Literal, List, Optional, Union
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field, ValidationError
from abc import ABC
from langchain_core.prompts.chat import(
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
    )
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    MessageSendParams,
    SendStreamingMessageRequest,
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    TaskState,
    TaskStatus,
    TextPart,
)
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from a2a.client import A2AClient
from .redis_registry import RedisRegistry, HeartbeatService
import atexit
import signal
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from .dataservices_client import DataServicesClient, CreateHistoryRequest, HistoryMessage, SearchHistoryRequest
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .agentregistry_client import AgentRegistryClient
from .agent_card_resolve import resolve_agent_card_by_planner_name
from . import broadcast_capability_check as sg_broadcast
from .orchestrator_agent_semantic_domain import SUMMARY_FRAME_PREFIX
from langchain_core.tools import tool, StructuredTool
from .tool_call_utils import invoke_llm_with_tool

try:
    from skill_sdk.skill.runner import SkillRunner  # noqa: F401  (used when local skills enabled)
except ImportError:  # pragma: no cover - skill_sdk is an optional runtime dep
    SkillRunner = None  # type: ignore[assignment]

try:
    from skill_sdk.tool.code_execution import CodeExecution
except ImportError:  # pragma: no cover
    CodeExecution = None  # type: ignore[assignment,misc]

try:
    # json_repair is a tolerant JSON parser designed specifically for LLM output.
    # It handles common failure modes such as unescaped inner double quotes,
    # trailing commas, missing quotes, python-style single quotes, etc.
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]


# Fields in the planner output that carry free-form natural language and are
# the most frequent victims of "LLM forgot to escape inner quotes" — typical
# failure mode is a user query containing a JSON/code fragment inlined as the
# value without escaping the inner ``"`` characters. The helper below surgically
# escapes unescaped inner double quotes *only* for these specific fields.
_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "reason",
    "rationale",
    "final_answer",
)


def _escape_known_string_field_inner_quotes(text: str) -> str:
    """Best-effort escape of unescaped inner ``"`` inside known single-line
    string fields of a planner-style JSON payload.

    We deliberately restrict the pre-pass to a whitelist of known fields where
    the value is a single JSON string on one line so we can recognize the end
    of the value by the structural pattern ``"`` followed by an optional
    comma/whitespace and a newline. Multi-line values and nested structures
    are left untouched (json_repair handles those as a later fallback).
    """
    if not text or '"' not in text:
        return text

    pattern_fields = "|".join(re.escape(f) for f in _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
    # Match:  "field": "<body possibly containing unescaped ">"<optional , >\n
    #
    # The closing ``"`` must sit at end-of-line (optionally followed by a
    # trailing comma and whitespace). This anchor is strong enough to
    # disambiguate against unescaped inner quotes that happen to be followed
    # by ``,`` mid-line, e.g. ``"手机",`` inside ``{"category":"手机",...}``.
    #
    # We keep ``.*?`` without DOTALL so the body cannot accidentally span
    # lines — the failure mode we care about always puts the offending field
    # value on a single pretty-printed line.
    pattern = re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'   # group 1: "field": "
        r'(.*?)'                                # group 2: value body (lazy, single line)
        r'((?<!\\)"[ \t]*,?[ \t]*$)',          # group 3: closing " at end of line
        re.MULTILINE,
    )

    def _repl(m: "re.Match[str]") -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        # Escape any ``"`` in the body that is not already escaped. We walk
        # character-by-character so we don't mis-handle ``\"`` (already
        # escaped) or ``\\`` (escaped backslash that does NOT escape a
        # following quote).
        fixed_chars: List[str] = []
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                # Preserve any escape sequence untouched.
                fixed_chars.append(body[i : i + 2])
                i += 2
                continue
            if ch == '"':
                fixed_chars.append('\\"')
                i += 1
                continue
            fixed_chars.append(ch)
            i += 1
        return head + "".join(fixed_chars) + tail

    return pattern.sub(_repl, text)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

PROGRESS_SCHEMA_VERSION = "v1"
ANSWER_SCHEMA_VERSION = "v1"
ANSWER_FRAME_PREFIX = "[[DAC_ANSWER]] "
PROGRESS_BASE_FIELDS = (
    "schema_version",
    "layer",
    "event",
    "run_id",
    "user_id",
    "agent_id",
    "task_id",
    "message",
    "status",
)
PROGRESS_EXTRA_ALLOWLIST: Dict[str, set[str]] = {
    "group_plan_ready": {
        "strategy",
        "task_count",
        "retry_count",
        "query_preview",
        "plan_tasks_summary",
        "plan_tasks_agents",
        "planner_thought",
        "original_query",
    },
    "group_execution_round_started": {"round", "retry_count", "max_retries"},
    "task_answer": {"task_agent"},
    "task_finished": {
        "task_agent",
        "task_status",
        # LocalSkill (route B) extras — see _run_local_skill_task / _try_local_skill_fallback_for_none.
        "execution_mode",
        "local_skill_name",
        "local_skill_attempts",
        "local_skill_status",
        "reason_code",
    },
    "task_error": set(),
    "group_retry_same_plan": {"retry_count", "reason_code"},
    "group_replan_failed": {"retry_count"},
    "group_tasks_completed": {"task_count"},
    "group_final_answer_ready": {"answer_chars"},
    # Planner assigned NONE: no downstream agent can handle this task
    "task_no_agent_available": {"reason_code", "task_description", "task_agent"},
    # ---- Cross-SG collaborative execution progress ----
    "collab_started": {
        "sg_id",
        "is_delegated",
        "hop",
        "chain_depth",
    },
    "collab_discovered_sgs": {
        "own_expert_count",
        "collab_sg_count",
        "collab_sg_names",
    },
    "collab_plan_ready": {
        "total_tasks",
        "own_task_count",
        "delegation_count",
        "own_agents",
        "delegation_targets",
    },
    "collab_executing_own": {
        "task_index",
        "total_own_tasks",
        "agent",
        "task_id",
        "plan_index",
        "desc_preview",
    },
    "collab_own_task_done": {
        "task_id",
        "agent",
        "plan_index",
        "desc_preview",
        "result_chars",
    },
    "collab_own_all_done": {
        "completed_count",
    },
    "collab_pre_delegating": {
        "target_sg",
        "task_id",
        "plan_index",
        "remaining_hop",
        "desc_preview",
        "planned_task_desc_preview",
    },
    "collab_pre_delegation_done": {
        "target_sg",
        "task_id",
        "plan_index",
        "desc_preview",
        "result_chars",
    },
    "collab_pre_delegation_skipped": {
        "target_sg",
        "task_id",
        "plan_index",
        "desc_preview",
        "reason",
    },
    "collab_pre_delegations_all_done": {
        "total_count",
        "result_count",
    },
    "collab_mid_exec_loop_started": {
        "max_rounds",
    },
    "collab_mid_exec_round": {
        "round",
        "max_rounds",
    },
    "collab_mid_detect_result": {
        "needs_help",
        "target_sgs",
        "reason_preview",
    },
    "collab_mid_detect_none": {},
    "collab_mid_plan_ready": {
        "task_count",
        "agents",
        "mid_exec_round",
    },
    "collab_mid_delegating": {
        "target_sg",
        "task_id",
        "mid_exec_round",
        "remaining_hop",
        "desc_preview",
    },
    "collab_mid_dispatched": {
        "target_sg",
        "task_id",
        "mid_exec_round",
        "desc_preview",
        "result_chars",
    },
    "collab_mid_round_done": {
        "round",
        "total_delegated",
    },
    "collab_mid_loop_done": {
        "total_rounds",
        "total_delegated",
    },
    "collab_mid_exec_loop_done": {
        "total_rounds",
        "total_delegated",
    },
    "collab_summarizing": {
        "own_result_count",
        "delegated_result_count",
    },
    "collab_done": {
        "result_chars",
    },
}

# Do not overwrite DASHSCOPE_API_KEY - use env or explicit api_key for real LLM

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_ZH = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
按 **数据归属（Data Sovereignty）** 将用户查询分解为可执行任务。你必须通过 **[执行上下文]** 建立反馈闭环，确保规划路径既能解决指代关系，又能避免重复失败。

## 核心方法论：数据归属语义判断（不要靠关键词，要靠业务本质思考）

⚠ **严禁名词驱动**：不要因为问题里出现 "X" 就路由到主管 "X" 的 Agent。
⚠ **不要退化成关键词字面比对**：判断标准不是 "Agent 描述里有没有这个词"，而是"这份数据从**业务本质**上是不是该 Agent 能力的**自然产物**"。
✅ **必须做业务语义归属**：先问"这份数据是什么**业务性质**的数据"，再问"哪个 Agent 的业务能力**天然覆盖 / 自然沉淀**这种性质的数据"。

### 关键认知（数据本体二分法 — 整个推理的根基）

任何业务数据，从本质上都属于以下两类之一：

1. **静态本体数据（实体的内在属性 / 自身状态）**
   - 含义：是某个业务实体"自带的"、"自身就有的"属性或状态。
   - 归属：**持有该实体生命周期的 Agent**。
   - 直觉判断："这个数据，就算从来没人买过、没人用过，它也客观存在。"
   - 例：
     - 商品的名称 / SKU / 类目 / 上下架状态 / 库存量 / 标价 → 商品 Agent
     - 用户的昵称 / 等级 / 注册时间 / 收货地址 → 用户 Agent

2. **动态行为数据（行为/事件/交互产生的流水或统计）**
   - 含义：必须有"某种动作发生过"才会存在的数据，是行为本身的副产物或聚合统计。
   - 归属：**记录该行为本身的 Agent**（**不是**被作用对象那一方的 Agent）。
   - 直觉判断："如果没人触发过这个动作，这数据就不存在。"
   - 例：
     - 商品的销量 / 销售情况 / 成交额 / 售出记录 / 退款情况 → **由购买/退款行为产生** → 订单 / 交易 Agent
     - 用户的登录次数 / 浏览路径 / 收藏行为 → **由用户操作产生** → 行为日志 / 用户行为 Agent

### 关键洞察（消除"X 的 Y"歧义）
- "X 的 Y"形式中，**Y 的业务性质决定归属，X 只是过滤维度**。
- 当 Y 是 **动作/行为/统计/流水**（销售、购买、成交、登录、支付、退款……）时：
  - 这份数据是**动态行为数据**，归属于**记录该行为的领域**，**不在** X 自身的领域。
  - 哪怕 Y 听起来"是关于 X 的"，也不改变这一点。
- 反例提醒：商品 Agent 管的是"商品本体"，**不**管"消费者购买商品产生的销售流水"——后者是交易行为的产物。

## 战略思考过程（思维链 — 必须按顺序执行，不可跳过）

### Step 1：数据需求识别（这一步是"思考要什么"，不是"提取名词"）
对用户查询，思考并写出：
- **核心数据需求**：要回答这个问题，必须获得**什么业务性质的数据**？用一句话描述（如"按商品维度聚合的销售流水统计"、"商品的库存数量"、"用户的注册档案"）。
- **过滤维度**（可空）：这份数据要按什么条件过滤（如"按商品维度"、"按时间段"、"按某用户"）。

> **示范（重在示范"如何思考数据本质"，不是枚举答案）**：
> - "统计商品的销售情况" → 思考："销售情况"是消费者**购买行为**的统计聚合，不是商品本身的固有属性 → 核心数据需求：【按商品维度聚合的销售/交易统计】，过滤维度：商品。
> - "查某商品的库存" → 思考："库存"是商品本身的状态量，是商品本体属性 → 核心数据需求：【商品的库存数据】，过滤维度：该商品。
> - "用户的活跃度" → 思考："活跃度"是用户**登录/操作行为**的统计，不是用户档案里固有的字段 → 核心数据需求：【用户行为日志聚合】，过滤维度：该用户。

### Step 2：数据本体性质判定（核心二分）
对 Step 1 写出的"核心数据需求"，必须明确判定它是：
- **(A) 静态本体数据** — "X 的内在属性 / 自身状态"，那么归属于持有 X 实体生命周期的 Agent；或
- **(B) 动态行为数据** — "由某种动作/事件产生的流水或统计"，那么归属于记录该动作的 Agent，**不**归属于被作用对象那一方。

判定方法（直觉法，不是关键词法）：
- 自问："如果从来没有发生过任何相关动作（没人买过 / 没人登录过 / 没人评价过……），这份数据还会存在吗？"
- 会存在 → (A) 静态本体；
- 不会存在 → (B) 动态行为。

### Step 3：业务能力语义匹配（基于 Agent 能力的语义理解，不是关键词字面匹配）
逐个审视 [可用智能体]，对每个候选 Agent：
- **读懂它的业务能力范围**（它在业务上承担什么职责、管理什么生命周期、产生什么行为流水），而不是死扣它的描述里出现了哪些字。
- 自问：**Step 1 那份数据，是不是这个 Agent 业务能力的"自然产物 / 直接职责覆盖"？**
  - "自然产物"：履行其核心职能时**必然产生 / 必须维护**的数据（如订单 Agent 在处理交易时必然产生销售流水与统计）。
  - "直接职责覆盖"：数据是它显式管理的实体的内在属性（如商品 Agent 直接管商品 SKU、库存、上下架）。
- 只有满足"自然产物"或"直接职责覆盖"的 Agent，才算合法候选。
- ❌ "Agent 描述里碰巧出现了某个词"——不构成路由理由（关键词巧合不等于业务归属）。
- ❌ "听起来像那个领域 / 主体名词同名"——更不构成路由理由。

### Step 4：路由前自检（强制 — 防名词陷阱与"语义虚假相关"）
在最终落定 Agent 前，必须在 `thought_process` 中显式回答下面四问：
1. **本体性质**：Step 1 这份数据，是 (A) 静态本体属性 还是 (B) 动态行为产物？
2. **业务覆盖**：选定 Agent 的业务能力，是不是**天然产生 / 直接覆盖**这份数据（业务必然性，不是字面巧合）？
3. **名词陷阱**：我是否仅因为"用户问题里的名词" 与 "Agent 主体名词" 同名就做了路由？（若是，重选）
4. **更优候选**：是否存在另一个 Agent，其业务本质比当前选择**更直接地**对应这份数据的产出？（如果数据是"X 的某动作统计"，是否记录该动作的 Agent 才是更本质的归属？）

### Step 5：[执行上下文] 闭环分析
- **结果复用**：若 **[执行上下文]** 中已有相关任务的成功结果（ID / Token / 数据），直接继承，严禁创建重复查询任务。
- **路径纠偏（避坑）**：若上下文显示先前尝试已失败（报错 / 权限不足 / 超时），本次规划必须改变策略（更换 Agent、调整参数或在描述中注入修正指令）。

### Step 6：跨域编排判定
- 当 **数据归属方 ≠ 过滤维度持有方** 时：
  - **首选方案**：让"数据归属方"独立完成查询（它直接按过滤维度搜索即可），不要画蛇添足拆任务。
  - **仅当**过滤条件需要先由另一个 Agent 解析为 ID / 枚举 / 名单后才能传给主查询 Agent 时，才安排上游任务。
- 编排顺序：**数据持有方**（产出关联键）→ **数据消费方**（消费关联键），消费方必须在 `depends_on` 中声明依赖。
- 严禁循环依赖（A↔B）。

### Step 7：依赖与描述注入（自洽校验规则）
若当前任务需要先前任务的产出，必须在 `description` 中明确注入（如"根据上一步任务返回的 user_id 查询..."）。

**描述与依赖的自洽规则（强制）**：
- 若某任务的 `description` 中明确或隐含地依赖了另一个任务的结果（例如描述中出现了"根据上一步"、"需要从上游获取"、"基于任务 X 的结果"、或引用了尚未产出的数据），则该任务的 `depends_on` 字段**必须**包含对应任务的 ID。**禁止出现**描述中声明依赖、但 `depends_on` 为空的自相矛盾情况。
- 同时，若 `depends_on` 非空，则 `description` 中**必须**说明需要从上游获取哪些具体数据或字段，而不是仅笼统写一句"需要从上游获取"。

## 智能体选择规则（必须严格遵守）
1. **数据本体归属优先**：分配给"业务能力天然产出该数据"的 Agent，**不是**"主体名词同名"或"描述里碰巧有相关字眼"的 Agent。
2. **领域内隐含能力**：领域专家拥有**该领域内**的全量知识（如订单 / 交易 Agent 天然能"按各种维度（商品、用户、时段）切分销售统计"，因为这都是其业务的自然产出）。
3. **⚠ 不可跨域扩张（重点）**：不要假设"X Agent 是 X 全能专家就能处理 X 的 Y"，当 Y 是**动态行为数据**且行为本身归属于另一领域时（如"商品的销量"中"销量"是消费购买行为的产物，归属于交易领域，**不在**商品领域）。"全能"只在该 Agent 业务能力本身的范围内有效。
4. **任务分解节制**：仅当查询确实涉及**多个不同领域**或存在**明确先后依赖**时才拆分；不要把一个简单问题过度拆分。
5. **"无对应"协议（NONE）**：
   - **仅当**用户问题的**全部**可执行议题都超出当前可用 Agent 的领域范围时，才使用 `agent="NONE"`。
   - **禁止**因为还夹带了本 Agent 无法覆盖的关联属性 / 外域切片，就把**整题**标成 NONE。
   - 若可用 Agent 已覆盖问题中的**主锚定议题 / 本域可答部分**，必须派给对应 Agent；外域缺口留给执行结果或上层编排，不得因“答不完整题”拒绝派活。
6. **名称准确性**：`agent` 字段必须与智能体列表中的"名称"完全一致。

## ⚠ 反模式（已知路由失败案例 — 必须避免）
1. **名词陷阱（最高频错误）**：把"X 的 Y"中的动态行为数据 Y 当成 X 领域的事。
   - ❌ "统计商品的销售情况" → 商品管理 Agent（错：销量是消费购买**行为**的统计产物，本质属于交易领域；商品管理 Agent 管的是商品本体属性如 SKU / 库存 / 上下架，不天然产出销售流水）
   - ✅ "统计商品的销售情况" → 订单 / 交易 Agent，过滤维度="商品"
2. **关键词字面匹配陷阱**：仅因为 Agent 描述里出现了某个相关词就路由，而不思考业务本质。"沾边"不是"归属"。
3. **跨域隐含能力误判**：以为"X 领域专家"能处理"X 的 Y"，而 Y 实际是另一领域的行为产物。
4. **静态/动态判定错误**：把动态行为数据当成静态本体数据（或反之）从而错配 Agent。

## ⚠ 跨域串联规则（强制）
当用户查询需要跨 SG 串联两个领域的数据时（如"查某个订单的购买者信息"、"查某个商品的所属类目信息"），必须遵守：
1. 拥有关联键的 SG（**数据持有方**）的任务排在前面。
2. 需要关联键的 SG（**数据消费方**）在其 `depends_on` 中声明对持有方任务的依赖。
3. 消费方任务的 `description` 中需明确说明需要从上游获得的关键字段。


## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化或改写问题。**

1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[执行上下文]** 中的关键结果（如已获 ID、特定报错原因）。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户"查订单" → `description`："查询订单情况" ✅
   - **错误示例**：用户"查订单" → `description`："查询2024年Q4电子产品订单及同比增长" ❌（捏造了时间、类别、指标）
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。
4. **保留过滤维度**：当 **谓词数据 ≠ 过滤维度** 时，description 必须保留过滤维度，让数据持有方知道该按什么条件过滤。
   - 例：路由到订单 Agent 处理"统计商品的销售情况"，description 应为"按商品维度统计销售情况"，不能丢掉"商品"这个过滤维度。

---

**[可用智能体] (Agents):**
{agents}

**[执行上下文] (Information):**
{information}
*注：包含之前已执行的任务 ID、任务描述、执行 Agent 以及执行结果（成功/失败/具体数据）。*

**[组级记忆] (Group Memory):**
{group_memory}
*注：包含长期策略沉淀及 Agent 间协作的特殊规则。*

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本，也不要返回 JSON Schema 的 `properties` 包装。

工具参数结构：
   - `thought_process`：必须按以下结构化模板输出（**不可省略任何一行，便于审计与稳定性**）：
     ```
     [Step1 数据需求] 核心数据需求=...; 过滤维度=...
     [Step2 本体性质] (A) 静态本体 / (B) 动态行为产物 二选一, 并给出业务直觉理由（"如果没人触发过相关动作, 这数据是否仍存在"）
     [Step3 业务能力匹配] 逐个候选 Agent: 是否"业务能力天然产出 / 直接职责覆盖"该数据? 选定=<AgentName>, 选它的业务必然性理由=...
     [Step4 自检] (1) 本体性质判定与所选 Agent 业务能力是否相容? 是; (2) 是否仅因名词同名/字面相关而路由? 否; (3) 是否存在业务本质更直接对应的另一 Agent? 已确认无
     [Step5 上下文] 是否复用先前结果 / 是否需要纠偏（简述）
     [Step6 跨域] 是否拆分及理由
     ```
   - `original_query`：逐字复制原始用户输入，必须保留全部字符、空格、引号和标点，不得改写、规范化或删减。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务（忠实于用户原始表述，禁止添加额外条件；保留过滤维度；对比性追问需继承完整上下文；指代性追问需补充上下文使其自包含）。
     - `agent`：确切的智能体名称或"NONE"。
     - `depends_on`：整数列表，标明此任务依赖哪些 task id 必须先完成（无依赖则为空列表 `[]`）。

## `make_plan_cmd` 工具参数示例
{instructions}

或当未找到智能体时：
{none_instructions}

问题：

"""

PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
按 **数据归属（Data Sovereignty）** 将用户查询分解为可执行任务。你必须通过 **[执行上下文]** 建立反馈闭环，并结合 **[对话历史]** 的语境，确保规划路径既能解决指代关系，又能避免重复失败。

## 核心方法论：数据归属语义判断（不要靠关键词，要靠业务本质思考）

⚠ **严禁名词驱动**：不要因为问题里出现 "X" 就路由到主管 "X" 的 Agent。
⚠ **不要退化成关键词字面比对**：判断标准不是 "Agent 描述里有没有这个词"，而是"这份数据从**业务本质**上是不是该 Agent 能力的**自然产物**"。
✅ **必须做业务语义归属**：先问"这份数据是什么**业务性质**的数据"，再问"哪个 Agent 的业务能力**天然覆盖 / 自然沉淀**这种性质的数据"。

### 关键认知（数据本体二分法 — 整个推理的根基）

任何业务数据，从本质上都属于以下两类之一：

1. **静态本体数据（实体的内在属性 / 自身状态）**
   - 含义：是某个业务实体"自带的"、"自身就有的"属性或状态。
   - 归属：**持有该实体生命周期的 Agent**。
   - 直觉判断："这个数据，就算从来没人买过、没人用过，它也客观存在。"
   - 例：
     - 商品的名称 / SKU / 类目 / 上下架状态 / 库存量 / 标价 → 商品 Agent
     - 用户的昵称 / 等级 / 注册时间 / 收货地址 → 用户 Agent

2. **动态行为数据（行为/事件/交互产生的流水或统计）**
   - 含义：必须有"某种动作发生过"才会存在的数据，是行为本身的副产物或聚合统计。
   - 归属：**记录该行为本身的 Agent**（**不是**被作用对象那一方的 Agent）。
   - 直觉判断："如果没人触发过这个动作，这数据就不存在。"
   - 例：
     - 商品的销量 / 销售情况 / 成交额 / 售出记录 / 退款情况 → **由购买/退款行为产生** → 订单 / 交易 Agent
     - 用户的登录次数 / 浏览路径 / 收藏行为 → **由用户操作产生** → 行为日志 / 用户行为 Agent

### 关键洞察（消除"X 的 Y"歧义）
- "X 的 Y"形式中，**Y 的业务性质决定归属，X 只是过滤维度**。
- 当 Y 是 **动作/行为/统计/流水**（销售、购买、成交、登录、支付、退款……）时：
  - 这份数据是**动态行为数据**，归属于**记录该行为的领域**，**不在** X 自身的领域。
  - 哪怕 Y 听起来"是关于 X 的"，也不改变这一点。
- 反例提醒：商品 Agent 管的是"商品本体"，**不**管"消费者购买商品产生的销售流水"——后者是交易行为的产物。

## 战略思考过程（思维链 — 必须按顺序执行，不可跳过）

### Step 1：数据需求识别（这一步是"思考要什么"，不是"提取名词"）
对用户查询，思考并写出：
- **核心数据需求**：要回答这个问题，必须获得**什么业务性质的数据**？用一句话描述（如"按商品维度聚合的销售流水统计"、"商品的库存数量"、"用户的注册档案"）。
- **过滤维度**（可空）：这份数据要按什么条件过滤（如"按商品维度"、"按时间段"、"按某用户"）。

> **示范（重在示范"如何思考数据本质"，不是枚举答案）**：
> - "统计商品的销售情况" → 思考："销售情况"是消费者**购买行为**的统计聚合，不是商品本身的固有属性 → 核心数据需求：【按商品维度聚合的销售/交易统计】，过滤维度：商品。
> - "查某商品的库存" → 思考："库存"是商品本身的状态量，是商品本体属性 → 核心数据需求：【商品的库存数据】，过滤维度：该商品。
> - "用户的活跃度" → 思考："活跃度"是用户**登录/操作行为**的统计，不是用户档案里固有的字段 → 核心数据需求：【用户行为日志聚合】，过滤维度：该用户。

### Step 2：数据本体性质判定（核心二分）
对 Step 1 写出的"核心数据需求"，必须明确判定它是：
- **(A) 静态本体数据** — "X 的内在属性 / 自身状态"，那么归属于持有 X 实体生命周期的 Agent；或
- **(B) 动态行为数据** — "由某种动作/事件产生的流水或统计"，那么归属于记录该动作的 Agent，**不**归属于被作用对象那一方。

判定方法（直觉法，不是关键词法）：
- 自问："如果从来没有发生过任何相关动作（没人买过 / 没人登录过 / 没人评价过……），这份数据还会存在吗？"
- 会存在 → (A) 静态本体；
- 不会存在 → (B) 动态行为。

### Step 3：业务能力语义匹配（基于 Agent 能力的语义理解，不是关键词字面匹配）
逐个审视 [可用智能体]，对每个候选 Agent：
- **读懂它的业务能力范围**（它在业务上承担什么职责、管理什么生命周期、产生什么行为流水），而不是死扣它的描述里出现了哪些字。
- 自问：**Step 1 那份数据，是不是这个 Agent 业务能力的"自然产物 / 直接职责覆盖"？**
  - "自然产物"：履行其核心职能时**必然产生 / 必须维护**的数据（如订单 Agent 在处理交易时必然产生销售流水与统计）。
  - "直接职责覆盖"：数据是它显式管理的实体的内在属性（如商品 Agent 直接管商品 SKU、库存、上下架）。
- 只有满足"自然产物"或"直接职责覆盖"的 Agent，才算合法候选。
- ❌ "Agent 描述里碰巧出现了某个词"——不构成路由理由（关键词巧合不等于业务归属）。
- ❌ "听起来像那个领域 / 主体名词同名"——更不构成路由理由。

### Step 4：路由前自检（强制 — 防名词陷阱与"语义虚假相关"）
在最终落定 Agent 前，必须在 `thought_process` 中显式回答下面四问：
1. **本体性质**：Step 1 这份数据，是 (A) 静态本体属性 还是 (B) 动态行为产物？
2. **业务覆盖**：选定 Agent 的业务能力，是不是**天然产生 / 直接覆盖**这份数据（业务必然性，不是字面巧合）？
3. **名词陷阱**：我是否仅因为"用户问题里的名词" 与 "Agent 主体名词" 同名就做了路由？（若是，重选）
4. **更优候选**：是否存在另一个 Agent，其业务本质比当前选择**更直接地**对应这份数据的产出？（如果数据是"X 的某动作统计"，是否记录该动作的 Agent 才是更本质的归属？）

### Step 5：[执行上下文] + [对话历史] 闭环分析
- **结果复用**：若 **[执行上下文]** 中已有相关任务的成功结果（ID / Token / 数据），直接继承，严禁创建重复查询任务。
- **路径纠偏（避坑）**：若上下文显示先前尝试已失败（报错 / 权限不足 / 超时），本次规划必须改变策略（更换 Agent、调整参数或在描述中注入修正指令）。
- **历史指代解析**：用 [对话历史] 仅解析"它 / 那个 / 继续 / 更详细一点"等指代，不要把历史中与当前追问无关的过滤条件机械搬运过来。

### Step 6：跨域编排判定
- 当 **数据归属方 ≠ 过滤维度持有方** 时：
  - **首选方案**：让"数据归属方"独立完成查询（它直接按过滤维度搜索即可），不要画蛇添足拆任务。
  - **仅当**过滤条件需要先由另一个 Agent 解析为 ID / 枚举 / 名单后才能传给主查询 Agent 时，才安排上游任务。
- 编排顺序：**数据持有方**（产出关联键）→ **数据消费方**（消费关联键），消费方必须在 `depends_on` 中声明依赖。
- 严禁循环依赖（A↔B）。

### Step 7：依赖与描述注入（自洽校验规则）
若当前任务需要先前任务（或历史结论）的产出，必须在 `description` 中明确注入（如"根据上一步任务返回的 user_id 查询..."）。

**描述与依赖的自洽规则（强制）**：
- 若某任务的 `description` 中明确或隐含地依赖了另一个任务的结果（例如描述中出现了"根据上一步"、"需要从上游获取"、"基于任务 X 的结果"、或引用了尚未产出的数据），则该任务的 `depends_on` 字段**必须**包含对应任务的 ID。**禁止出现**描述中声明依赖、但 `depends_on` 为空的自相矛盾情况。
- 同时，若 `depends_on` 非空，则 `description` 中**必须**说明需要从上游获取哪些具体数据或字段，而不是仅笼统写一句"需要从上游获取"。

## 智能体选择规则（必须严格遵守）
1. **数据本体归属优先**：分配给"业务能力天然产出该数据"的 Agent，**不是**"主体名词同名"或"描述里碰巧有相关字眼"的 Agent。
2. **领域内隐含能力**：领域专家拥有**该领域内**的全量知识（如订单 / 交易 Agent 天然能"按各种维度（商品、用户、时段）切分销售统计"，因为这都是其业务的自然产出）。
3. **⚠ 不可跨域扩张（重点）**：不要假设"X Agent 是 X 全能专家就能处理 X 的 Y"，当 Y 是**动态行为数据**且行为本身归属于另一领域时（如"商品的销量"中"销量"是消费购买行为的产物，归属于交易领域，**不在**商品领域）。"全能"只在该 Agent 业务能力本身的范围内有效。
4. **任务分解节制**：仅当查询确实涉及**多个不同领域**或存在**明确先后依赖**时才拆分；不要把一个简单问题过度拆分。
5. **"无对应"协议（NONE）**：
   - **仅当**用户问题的**全部**可执行议题都超出当前可用 Agent 的领域范围时，才使用 `agent="NONE"`。
   - **禁止**因为还夹带了本 Agent 无法覆盖的关联属性 / 外域切片，就把**整题**标成 NONE。
   - 若可用 Agent 已覆盖问题中的**主锚定议题 / 本域可答部分**，必须派给对应 Agent；外域缺口留给执行结果或上层编排，不得因“答不完整题”拒绝派活。
6. **名称准确性**：`agent` 字段必须与智能体列表中的"名称"完全一致。

## ⚠ 反模式（已知路由失败案例 — 必须避免）
1. **名词陷阱（最高频错误）**：把"X 的 Y"中的动态行为数据 Y 当成 X 领域的事。
   - ❌ "统计商品的销售情况" → 商品管理 Agent（错：销量是消费购买**行为**的统计产物，本质属于交易领域；商品管理 Agent 管的是商品本体属性如 SKU / 库存 / 上下架，不天然产出销售流水）
   - ✅ "统计商品的销售情况" → 订单 / 交易 Agent，过滤维度="商品"
2. **关键词字面匹配陷阱**：仅因为 Agent 描述里出现了某个相关词就路由，而不思考业务本质。"沾边"不是"归属"。
3. **跨域隐含能力误判**：以为"X 领域专家"能处理"X 的 Y"，而 Y 实际是另一领域的行为产物。
4. **静态/动态判定错误**：把动态行为数据当成静态本体数据（或反之）从而错配 Agent。

## ⚠ 跨域串联规则（强制）
当用户查询需要跨 SG 串联两个领域的数据时（如"查某个订单的购买者信息"、"查某个商品的所属类目信息"），必须遵守：
1. 拥有关联键的 SG（**数据持有方**）的任务排在前面。
2. 需要关联键的 SG（**数据消费方**）在其 `depends_on` 中声明对持有方任务的依赖。
3. 消费方任务的 `description` 中需明确说明需要从上游获得的关键字段。

## ⚠ 对话历史使用规则（指代与继承）
1. **仅用于理解指代**：解析"它"、"那个"、"继续"等含义。
2. **禁止无关条件搬运**：不要将历史对话中与当前追问无关的过滤条件搬运到当前任务中。
3. **对比性追问须继承完整上下文**：用户进行对比追问（如"那2024年呢"），必须从历史中完整继承未变化的维度（年份、机构、指标等），确保 `description` 语义自包含。
4. **指代追问必须自包含**：对于"更详细一点"这类指代，描述必须补充历史主题，使其对 Agent 而言是完整的。

## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化或改写问题。**

1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[执行上下文]** 中的关键结果（如已获 ID、特定报错原因）。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户"查订单" → `description`："查询订单情况" ✅
   - **错误示例**：用户"查订单" → `description`："查询2024年Q4电子产品订单及同比增长" ❌（捏造了时间、类别、指标）
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。
4. **保留过滤维度**：当 **谓词数据 ≠ 过滤维度** 时，description 必须保留过滤维度，让数据持有方知道该按什么条件过滤。
   - 例：路由到订单 Agent 处理"统计商品的销售情况"，description 应为"按商品维度统计销售情况"，不能丢掉"商品"这个过滤维度。

---

**[对话历史] (History):**
{history}
*注：包含用户与系统的自然语言对话，用于理解语境和指代。*

**[可用智能体] (Agents):**
{agents}

**[执行上下文] (Information):**
{information}
*注：包含之前已执行的任务 ID、任务描述、执行 Agent 以及执行结果（成功/失败/具体数据）。*

**[组级记忆] (Group Memory):**
{group_memory}
*注：包含长期策略沉淀及 Agent 间协作的特殊规则。*

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本，也不要返回 JSON Schema 的 `properties` 包装。

工具参数结构：
   - `thought_process`：必须按以下结构化模板输出（**不可省略任何一行，便于审计与稳定性**）：
     ```
     [Step1 数据需求] 核心数据需求=...; 过滤维度=...
     [Step2 本体性质] (A) 静态本体 / (B) 动态行为产物 二选一, 并给出业务直觉理由（"如果没人触发过相关动作, 这数据是否仍存在"）
     [Step3 业务能力匹配] 逐个候选 Agent: 是否"业务能力天然产出 / 直接职责覆盖"该数据? 选定=<AgentName>, 选它的业务必然性理由=...
     [Step4 自检] (1) 本体性质判定与所选 Agent 业务能力是否相容? 是; (2) 是否仅因名词同名/字面相关而路由? 否; (3) 是否存在业务本质更直接对应的另一 Agent? 已确认无
     [Step5 上下文/历史] 是否复用先前结果 / 是否需要纠偏 / 历史指代解析（简述）
     [Step6 跨域] 是否拆分及理由
     ```
   - `original_query`：逐字复制原始用户输入，必须保留全部字符、空格、引号和标点，不得改写、规范化或删减。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务（忠实于用户原始表述，禁止添加额外条件；保留过滤维度；对比性追问需继承完整上下文；指代性追问需补充上下文使其自包含）。
     - `agent`：确切的智能体名称或"NONE"。
     - `depends_on`：整数列表，标明此任务依赖哪些 task id 必须先完成（无依赖则为空列表 `[]`）。

## `make_plan_cmd` 工具参数示例
{instructions}

或当未找到智能体时：
{none_instructions}

问题：

"""

Orchestrator_INSTRUCTIONS_ZH = """
你是一位知识分析与总结专家。你的任务是基于提供的子问题答案（`knowledge`）和对话上下文（`history`），通过逻辑严密的分析，回答用户的原始问题。

**核心原则与回答规则**

1. **答案来源的唯一性**
   * 你的所有事实性结论必须源于 `knowledge`。`history` 仅用于理解当前问题的指代（如“他”指代谁）或语境。
   * **严禁幻觉**：禁止编造 `knowledge` 中不存在的数字、日期或具体事实。
   * **不确定不猜测**：凡是上下文证据不足、字段缺失、口径冲突或无法确认的内容，不要自行补全或猜测，不要把推测当成事实输出。

2. **信息处理与灵活匹配（核心优化）**
   * **精确匹配**：若 `knowledge` 包含原始问题所需的全部精确信息，请直接进行整合归纳，给出直接答案。
   * **退守匹配（重要）**：若 `knowledge` 中缺乏原始问题要求的“精确时间点”或“精确维度”的数据，但包含**高度相关**的信息（例如：没有11月数据但有三季度数据；没有公司客户数但有总客户数），你应当：
     1. 告知用户当前缺乏精确到 [具体维度] 的数据。
     2. 主动提供 `knowledge` 中现有的、最接近的参考数据作为替代。
     3. 严禁直接回答“没有数据”，除非 `knowledge` 与问题完全无关。

3. **回答表现形式**
   * **逻辑性**：使用分点、表格或对比等方式让答案易于阅读。
   * **默认结构**：先用 1-2 句给出结论；当答案里包含多个数字、属性、对象信息或对比关系时，优先补一个简短的“关键依据”或“补充信息”小节，不要只输出一整段纯文本。
   * **轻量格式优先**：默认使用短标题、项目符号或简短表格提升可读性；保持结构轻量，不要堆砌大段背景说明。
   * **标题自然**：不要机械使用“直接答案”“补充说明”这类模板化标题；若需要标题，优先使用更自然的标题，如“结论”“核心结论”“关键信息”“关键依据”，并允许根据内容自适应命名。
   * **图表建议**：若用户要求“画图”且 `knowledge` 中包含chart包装的多维度或趋势性数据，你应该原封不动的保留chart包装好的结构化的数据，浏览器的ui自己会负责渲染的。

4. **判定“无法回答”的标准**
   * 只有当 `knowledge` 内容与问题**毫无关联**，或信息量极度匮乏（如仅有零碎词汇）无法构成逻辑链条时，才触发该规则。
   * **此时回复**：「抱歉，目前的知识库中暂无与 [原始问题关键点] 直接或间接相关的信息，无法为您提供有效的分析。」

5. **多轮对话处理**
   * 始终以最新的 `knowledge` 为最高准则。若 `history` 中之前的结论与当前 `knowledge` 不符，请以 `knowledge` 为准，并可在回答中顺带说明数据已更新。

6. **证据约束（强制）**
   * 只输出可被 `knowledge` 直接支持的结论。
   * 默认不输出推测性内容。

7. **收敛输出（强制）**
   * 必须先给结论，首段 1-2 句内明确回答用户问题核心结论（不要先讲过程）。
   * 默认使用轻量结构化表达提升可读性，例如短标题、项目符号或简短表格；不要输出成没有层次的一大段纯文本。
   * 不要机械使用“直接答案”“补充说明”这类模板化标题；若需要标题，优先使用更自然的标题，并允许根据内容自适应命名。
   * 若用户未明确要求“方法对比/扩展建议/治理建议/补充分析”，默认不要主动展开这些内容。
   * 补充内容只保留与用户问题直接相关的 2-4 个要点；保持表达简洁，但不要为了简短牺牲可读性（图表原始结构化数据透传场景除外）。
"""

# Initialize Langfuse client
langfuse = get_client()

langfuse_auth_check = os.getenv('LANGFUSE_AUTH_CHECK',"disable")
if langfuse_auth_check == "enable":
    # Verify connection
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Authentication failed. Please check your credentials and host.")

# Initialize Langfuse CallbackHandler for Langchain (tracing)
langfuse_handler = CallbackHandler()

CONVERSATION_HISTORY_LIMIT_DEFAULT = 6
CONVERSATION_HISTORY_LIMIT_MAX = 10
PROPAGATED_HISTORY_KEY = "propagated_history"


def get_conversation_history_limit() -> int:
    raw = (
        os.getenv("ConversationHistoryLimit")
        or os.getenv("History_Limit")
        or str(CONVERSATION_HISTORY_LIMIT_DEFAULT)
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = CONVERSATION_HISTORY_LIMIT_DEFAULT
    if value <= 0:
        value = CONVERSATION_HISTORY_LIMIT_DEFAULT
    return min(value, CONVERSATION_HISTORY_LIMIT_MAX)


def parse_propagated_history(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_history_turns(turns: Any) -> list[dict]:
    normalized: list[dict] = []
    if not isinstance(turns, list):
        return normalized
    for item in turns:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def history_payload_from_search_items(search_items: Any, *, source: str) -> dict:
    turns: list[dict] = []
    for item in search_items or []:
        messages = getattr(item, "messages", None) or (item.get("messages") if isinstance(item, dict) else None) or []
        for msg in messages:
            role = getattr(msg, "role", None) if not isinstance(msg, dict) else msg.get("role")
            content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
            role_text = str(role or "").strip().lower()
            content_text = str(content or "").strip()
            if role_text not in ("user", "assistant") or not content_text:
                continue
            turns.append({"role": role_text, "content": content_text})
    return {
        "turns": turns,
        "turn_count": len(turns),
        "source": source,
    }


def history_text_from_payload(payload: Any) -> str:
    parsed = parse_propagated_history(payload)
    turns = normalize_history_turns(parsed.get("turns"))
    lines: list[str] = []
    for item in turns:
        prefix = "human" if item["role"] == "user" else "assistant"
        lines.append(f"{prefix}：{item['content']}")
    return "\n".join(lines)


def history_messages_from_payload(payload: Any) -> list[Union[HumanMessage, AIMessage]]:
    parsed = parse_propagated_history(payload)
    turns = normalize_history_turns(parsed.get("turns"))
    messages: list[Union[HumanMessage, AIMessage]] = []
    for item in turns:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        else:
            messages.append(AIMessage(content=item["content"]))
    return messages

class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        'arbitrary_types_allowed': True,
        'extra': 'allow',
    }

    agent_name: str = Field(
        description='The name of the agent.',
    )

    description: str = Field(
        description="A brief description of the agent's purpose.",
    )

    content_types: list[str] = Field(description='Supported content types.')


class PlannerTask(BaseModel):
    """Represents a single task generated by the Planner."""

    id: int = Field(description='Sequential ID for the task.')

    description: str = Field(
        description='description of subtask'
    )

    agent: str = Field(
        description='agent name of the task to be executed.'
    )

    depends_on: list[int] = Field(
        default_factory=list,
        description='List of task IDs that this task depends on (must complete before this one runs).',
    )


class TaskList(BaseModel):
    """Output schema for the Planner Agent."""

    thought_process: Optional[str] = Field(
        default=None, 
        description='The internal reasoning steps of the planner.'
    )
    
    original_query: Optional[str] = Field(
        description=(
            "Verbatim original user query. Preserve every character, space, "
            "quote, and punctuation mark without normalization."
        )
    )

    tasks: List[PlannerTask] = Field(
        description='A list of tasks to be executed sequentially.'
    )

class TaskStatus(BaseModel):
    """Represents a single task generated by the Planner."""

    id: int = Field(description='Sequential ID for the task.')

    description: str = Field(
        description='description of subtask'
    )

    agent: str = Field(
        description='agent name of the task to be executed.'
    )

    answer: str = Field(
        description='answer of the task.'
    )

    answer_final: str = Field(
        default="",
        description='sanitized business answer used for upstream planning/display.'
    )

    diagnostics_excerpt: str = Field(
        default="",
        description='diagnostic/process excerpt separated from business answer.'
    )

    marker_present: bool = Field(
        default=False,
        description='whether NON_RETRYABLE marker is present in raw answer.'
    )

    failure_reason_code: str = Field(
        default="",
        description='normalized failure reason code for planning.'
    )

    failure_explanation: str = Field(
        default="",
        description='failure explanation from outcome evaluation.'
    )

    missing_requirements: List[str] = Field(
        default_factory=list,
        description='missing requirements from outcome evaluation.'
    )

    status: str = Field(
        description='the status of the task to be executed.'
    )

# ==================== Capability Check Protocol ====================
# Message type flag used in A2A metadata to indicate a capability check request
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"
PRE_MAKE_PLAN_MESSAGE_TYPE = "pre_make_plan"
SG_EXECUTION_HINT_KEY = "sg_execution_hint"
TOP_K_PATHS_PER_TREE = int(os.getenv("TOP_K_PATHS_PER_TREE", "5"))
MAX_PATH_FAILURES_BEFORE_STOP = int(os.getenv("MAX_PATH_FAILURES_BEFORE_STOP", "3"))
MIN_CONTRIBUTION_CONFIDENCE = float(os.getenv("MIN_CONTRIBUTION_CONFIDENCE", "0.6"))
MIN_MULTI_HANDLE_CONFIDENCE = float(os.getenv("MIN_MULTI_HANDLE_CONFIDENCE", "0.6"))
MULTI_HANDLE_GAP_THRESHOLD = float(os.getenv("MULTI_HANDLE_GAP_THRESHOLD", "0.30"))
MAX_MULTI_HANDLE_COLLAB_AGENTS = int(os.getenv("MAX_MULTI_HANDLE_COLLAB_AGENTS", "3"))
ENABLE_REASON_AWARE_RETRY = os.getenv("ENABLE_REASON_AWARE_RETRY", "true").strip().lower() in ("true", "1", "yes")
MAX_SAME_PLAN_RETRY = int(os.getenv("MAX_SAME_PLAN_RETRY", "1"))
NON_RETRYABLE_MARKER = "NON_RETRYABLE::OUT_OF_SCOPE"
# Repeated-failure marker emitted by SD Expert when ``is_stuck`` fires
# (e.g. SQL_WHITELIST validator rejecting the same table twice).  Unlike
# OUT_OF_SCOPE, repeated_failure carries ``unfulfilled_needs`` in its
# structured_control payload, which the SG Orchestrator uses together with
# :class:`SovereigntyIndex` to redirect the gap to the peer SG that actually
# owns the missing table.  Surfacing this marker here closes the
# classification gap noted in R5.
NON_RETRYABLE_REPEAT_MARKER = "NON_RETRYABLE::REPEATED_FAILURE"


def _path_to_alias(path: List[str]) -> str:
    """Generate a readable alias from path (uses leaf node name, cleaned)."""
    if not path:
        return "unknown"
    leaf = path[-1]
    base = leaf.split("-sg-")[0] if "-sg-" in leaf else leaf
    base = base.replace("Group", "").replace("_", "-").strip("-")
    if not base:
        base = leaf.split("-sg-")[0][:20] if "-sg-" in leaf else leaf[:20]
    alias = base.lower()
    for c in (" ", "_", ".", "/"):
        alias = alias.replace(c, "-")
    while "--" in alias:
        alias = alias.replace("--", "-")
    return alias.strip("-") or "path"


class CapabilityCheckResponse(BaseModel):
    """Standard response model for capability check A2A requests.

    When routing broadcasts a 'can you handle this?' request to all orchestrators,
    each orchestrator responds with this structured JSON so the router can easily
    parse and compare answers.

    route_path: best path (backward compat, same as route_paths[0] if route_paths).
    route_paths: top-K paths within this tree, each (path, confidence), for fallback retry.
    """
    can_handle: bool = Field(
        description="Whether this agent can handle the given query."
    )
    confidence: float = Field(
        default=0.0,
        description="Confidence level from 0.0 to 1.0."
    )
    reason: str = Field(
        default="",
        description="Brief explanation for the capability assessment."
    )
    agent_name: str = Field(
        default="",
        description="Name of the responding agent."
    )
    agent_url: str = Field(
        default="",
        description="URL of the responding agent."
    )
    route_path: List[str] = Field(
        default_factory=list,
        description="Best path (first in route_paths). Kept for backward compat."
    )
    route_paths: List[dict] = Field(
        default_factory=list,
        description="Top-K paths: [{\"path\": [...], \"confidence\": 0.9}, ...] for fallback retry."
    )
    can_contribute: bool = Field(
        default=False,
        description="Whether this agent can partially contribute (e.g. provide user names) even if cannot handle fully."
    )
    contribution: str = Field(
        default="",
        description="Brief description of what this agent can contribute."
    )
    execution_strategy: str = Field(
        default="single",
        description="Capability response strategy; SG layer uses 'single' for local handling (route_path is per-group)."
    )
    collaboration_agents: List[str] = Field(
        default_factory=list,
        description="Optional list of peer agents for same-group collaboration hints (usually empty for broadcast capability checks)."
    )
    collaboration_roles: Dict[str, str] = Field(
        default_factory=dict,
        description="Role map for collaboration agents, e.g. {'agentA': 'handle', 'agentB': 'contribute'}."
    )
    collaboration_paths: List[dict] = Field(
        default_factory=list,
        description="Optional per-agent route hints for collaboration (usually empty); shape e.g. [{\"agent\":\"A\",\"path\":[...],\"confidence\":0.9}]."
    )
    member_results: List[dict] = Field(
        default_factory=list,
        description="Compact member capability evidence for execution-plan reuse."
    )
    degraded: bool = Field(
        default=False,
        description="Whether member capability evaluation was degraded."
    )
    unavailable_count: int = Field(
        default=0,
        description="Number of member capability probes that were unavailable."
    )
    missing_requirements: List[str] = Field(
        default_factory=list,
        description="Requirements not covered by the selected group members."
    )
    execution_hint: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque SG-issued execution evidence for request-scoped handoff."
    )
    latency_ms: int = Field(
        default=0,
        description="Capability check end-to-end latency in milliseconds, measured by the responding agent."
        # 由 handle_capability_check 用 _time.monotonic() 计时填充，随响应 JSON 上报给 routing-agent 用于链路耗时观测。
    )


# LLM prompt for the responder side: analyze whether this agent can handle the query
# Use CoT (Chain-of-Thought) to reason step by step and avoid rigid rule-based errors.
CAPABILITY_CHECK_PROMPT = """# Role：业务领域匹配判定器

请按以下步骤**逐步思考**，每步写出你的推理，最后给出结论。

## 思考步骤

**步骤 1 - 提取数据实体**：从用户问题中剥离动作词（查询、统计、分析、画图、导出等）和输出形式（图表、报表等），只保留**核心数据/实体**。问：用户问的是哪些行业、哪些业务的数据？

**步骤 2 - 识别领域归属**：这些数据实体属于哪个大业务领域？（领域由数据所属行业决定，不由操作方式决定）

**步骤 3 - 匹配智能体**：本智能体名称与描述已指明其所在**行业**。判定标准是**数据所属行业**，而非行业内的子领域划分。只要数据属于该行业，无论涉及何种业务环节，均属可处理范围。
补充约束：skills 仅作参考，不作为是否接单的准入条件。不要因为 skills 文案未覆盖某个动作词就判定不能处理。

**步骤 4 - 反思（关键）**：① 若步骤 1 提取不到任何业务数据实体（纯工具类请求：编程、脚本、翻译、计算器等无行业数据），则不属于任何业务领域，应判定为不能处理。② **领域归属由数据所属行业决定，不由操作类型（分析/统计/可视化/导出）决定**——操作类型不是领域。③ **不按行业内的子领域细分**：智能体覆盖整个行业，不因描述侧重某环节而排斥同行业其他环节的数据。④ 同一名词可能对应不同行业。需从**用户问题的核心诉求**推断：用户真正关心的是哪个行业的数据？

**步骤 5 - 结论**：综合以上做出判定。不确定时，结构化业务查询不要仅凭 AgentCard 文案就 can_handle=true。can_handle 表示本智能体覆盖问题的**主实体/主职责**（如订单号 → 订单域），即使关联字段（如下单用户姓名）需其他域补全也可为 true，并在 missing_requirements 中列出缺口。若问题有多个对等主实体且本智能体缺其一，则 can_handle=false。

**步骤 6 - 可贡献性（仅当 can_handle=false 时）**：只有当本智能体能提供**当前问题直接需要、且可明确说清楚的具体补充内容**时，才能设 can_contribute=true，并在 contribution 中写明具体补充什么；否则必须为 false。
补充约束：
- 若已有单一专家可端到端回答当前问题，则其它专家应倾向于 can_contribute=false。
- contribution 必须是可执行、可验证的具体内容，禁止输出“补充相关信息/互补信息/完善信息/辅助信息”这类空泛表述。
- 不要因为“也许以后有用”或“同属一个行业”就判定 can_contribute=true。
- 若本智能体只有本地技能（如 weather）而问题是订单/用户/商品等业务库查询，必须 can_contribute=false。
- 若 reason/contribution 表明自己没有所需数据源或无法访问业务库，必须 can_contribute=false。

---
**本智能体信息：**
- 名称：{agent_name}
- 描述：{agent_description}
- 技能参考（仅供参考，不限定能力边界）：
{agent_skills}

**历史对话：**
{history}

**用户问题：**
{query}

---
## 输出格式
请调用 evaluate_capability 工具来输出判定结果。将步骤 1～6 的推理过程写入 reason 字段。
"""


class TaskOutcomeEval(BaseModel):
    status: Literal["complete", "fail"] = Field(default="fail", description="Task execution outcome")
    confidence: float = Field(default=0.0, description="Evaluation confidence from 0.0 to 1.0")
    failure_reason_code: str = Field(default="", description="Failure reason code when status=fail")
    failure_explanation: str = Field(default="", description="Natural language failure explanation")
    missing_requirements: List[str] = Field(default_factory=list, description="Missing requirement units")
    suggested_retry_action: str = Field(
        default="replan_standard",
        description="retry_same_plan | replan_standard | replan_with_decomposition | abort",
    )


# ---------------------------------------------------------------------------
# Pydantic models for tool-call based LLM invocations (replacing prompt-based JSON)
# ---------------------------------------------------------------------------

class AgentEvalItem(BaseModel):
    """Single agent evaluation result for _batch_llm_evaluate."""
    model_config = {"extra": "ignore"}
    agent: str = Field(default="", description="Agent name")
    can_handle: bool = Field(default=False, description="Whether the agent can handle the query")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0")
    reason: str = Field(default="", description="Brief reason for the evaluation")


class AgentSelectionEvalResult(BaseModel):
    """Batch agent selection evaluation result."""
    model_config = {"extra": "ignore"}
    result: List[AgentEvalItem] = Field(default_factory=list, description="List of agent evaluation results")


class TaskOutcomeEvalToolResult(BaseModel):
    """Mirrors TaskOutcomeEval for use as tool-call args_schema."""
    model_config = {"extra": "ignore"}
    status: Literal["complete", "fail"] = Field(default="fail", description="Task execution outcome")
    confidence: float = Field(default=0.0, description="Evaluation confidence from 0.0 to 1.0")
    coverage_scope: str = Field(default="unknown", description="full | partial | unknown")
    coverage_score: float = Field(default=0.0, description="0.0 to 1.0")
    consistency_score: float = Field(default=0.0, description="0.0 to 1.0")
    merge_readiness_score: float = Field(default=0.0, description="0.0 to 1.0")
    evidence_quality_score: float = Field(default=0.0, description="0.0 to 1.0")
    failure_reason_code: str = Field(default="", description="Failure reason code when status=fail")
    failure_explanation: str = Field(default="", description="Natural language failure explanation")
    missing_requirements: List[str] = Field(default_factory=list, description="Missing requirement units")
    suggested_retry_action: str = Field(
        default="replan_standard",
        description="retry_same_plan | replan_standard | replan_with_decomposition | abort",
    )


class CapabilityCheckToolResult(BaseModel):
    """Capability check result for handle_capability_check."""
    model_config = {"extra": "ignore"}
    can_handle: bool = Field(default=False, description="Whether this SG can handle the query")
    can_contribute: bool = Field(default=False, description="Whether this SG can contribute")
    contribution: str = Field(default="", description="What this SG can contribute")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0")
    reason: str = Field(default="", description="Detailed reasoning")


class DependentQueryRefineResult(BaseModel):
    """Dependent query refinement result for _llm_refine_dependent_task_query."""
    model_config = {"extra": "ignore"}
    delegation_query: str = Field(default="", description="Synthesized delegation query body")
    skip: bool = Field(default=False, description="Whether to skip delegation")
    reason: str = Field(default="", description="Reason for skip (only when skip=True)")


class DelegationDetectionResult(BaseModel):
    """Mid-execution gap detection result for _detect_delegation_needs.

    Target SG selection is performed separately via concurrent standard
    ``capability_check`` against peer SGs. ``target_sgs`` here is optional and
    treated only as a soft inventory hint when present.
    """
    model_config = {"extra": "ignore"}
    needs_help: bool = Field(default=False, description="Whether another SG's help is needed")
    synthesized_query: str = Field(
        default="",
        description=(
            "Scoped sub-query for the downstream SG only: join keys + fields that "
            "SG must return. Do NOT restate the full original question or ask the "
            "peer to also compute other domains' metrics."
        ),
    )
    target_sgs: List[str] = Field(
        default_factory=list,
        description="Optional soft hint of SG names; final selection uses capability_check. Names must be selected from the provided SG list, do NOT invent non-existent SG names.",
    )
    reason: str = Field(default="", description="Why additional data is needed")


ALLOWED_FAILURE_REASON_CODES = {
    "",
    "non_retryable_misrouted_task",
    "execution_error_no_data",
    "transient_network",
    "auth_or_permission",
    "invalid_request",
    "cross_source_join_unavailable",
    "missing_relation_in_context",
    # Repeated SD Expert failure where structured ``unfulfilled_needs`` lets the
    # outer loop route the gap to a peer SG that owns the missing tables.
    "data_sovereignty_gap",
    "unknown_failure",
    "outcome_eval_error",
}

ALLOWED_RETRY_ACTIONS = {
    "retry_same_plan",
    "replan_standard",
    "replan_with_decomposition",
    "abort",
}


TASK_OUTCOME_EVAL_PROMPT = """你是任务完成判定器。

请判断该任务是否“真正完成”。要求：
1) 只能基于输入内容进行评估，不要臆测。
2) 判定基准是“当前 task_description”，不是整个 original_query 的全部要求。
3) original_query 仅用于理解上下文，不得要求当前子任务覆盖其它子任务职责。
4) 采用“综合判断”而不是单点一票否决：请同时评估覆盖度、结果一致性、可合并性、证据质量。
5) 若回答覆盖当前任务核心要求，且可被直接使用或可被后续步骤稳定消费，应倾向判定为 complete。
6) 若存在缺失，但不影响当前子任务主要目标达成、且可在后续步骤补齐，可判 complete，并在 missing_requirements 标注风险。
7) 仅当存在核心目标未达成、明显冲突、不可用结果、或无法被后续步骤消费时，判定 fail。
   - 通用硬规则：若 task_description 明确要求“补充/显示/合并”某类信息，而回答完全未包含该类信息或无可用字段映射，必须判 fail。
8) 对“各/每个/all/全部”语义，优先做证据化判断（full/partial/unknown），避免机械性判 fail。
   - partial/unknown 并不必然 fail，需结合任务目标与下游可消费性综合判断。
9) 对“合并输出”要求，若当前回答已提供可稳定 join 的结构化结果（如包含join_key和核心字段），可判 complete 并标注待合并风险。
10) 请调用 evaluate_task_outcome 工具来输出评估结果。

输入：
- original_query: {original_query}
- task_id: {task_id}
- task_description: {task_description}
- assigned_agent: {assigned_agent}
- agent_answer_raw: {agent_answer_raw}
- plan_context: {plan_context}
- prior_task_results: {prior_task_results}

failure_reason_code 只能从以下白名单中选择（严格二选一风格，不要自造新码）：
- non_retryable_misrouted_task
- execution_error_no_data
- transient_network
- auth_or_permission
- invalid_request
- cross_source_join_unavailable
- missing_relation_in_context
- unknown_failure
- outcome_eval_error
- （当 status=complete 时可为空字符串）

强约束：
- 若 agent_answer_raw 含有 "NON_RETRYABLE::OUT_OF_SCOPE"，你必须输出：
  - status="fail"
  - failure_reason_code="non_retryable_misrouted_task"
  - suggested_retry_action="abort"
- 不允许输出任何未在白名单中的 failure_reason_code。
"""

# Fixed description when no agent is relevant (agent=NONE)
NONE_TASK_DESCRIPTION = "No available agent can do this task. "
DEPENDENT_TASK_SKIP_MARKER = "__SG_SKIP_UPSTREAM_NO_DATA__"
DEPENDENT_TASK_SKIP_DESCRIPTION = (
    DEPENDENT_TASK_SKIP_MARKER + "上游依赖任务未返回有效数据，当前子任务无输入来源，已自动跳过。"
)

# Agent selection evaluation prompt (batch_llm mode)
AGENT_SELECTION_EVALUATION_PROMPT = """你是一个智能体选择专家。给定用户问题和一组候选智能体，请调用 evaluate_agent_batch 工具评估每个智能体能否处理该问题，并给出 0-1 的可信度（confidence）。

用户问题：
{query}

候选智能体：
{agents}"""

# 无可用 agent 且未配置 expert agent 时的提示（HAS_EXPERTAGENT=false），展示给用户
NO_SIDECAR_FALLBACK_DESCRIPTION = "暂时没有找到可以处理此问题的智能体，请稍后再试或换个方式描述您的问题。"

# ---------------------------------------------------------------------------
# Local skill (route B) configuration — mirrors orchestrator_agent_semantic_domain.py.
# ---------------------------------------------------------------------------
# When enabled, the SemanticGroup orchestrator carries a process-wide SkillRunner
# and exposes it to the planner as a synthetic AgentCard named
# ``LOCAL_SKILL_AGENT_NAME``. Tasks the planner routes to this agent are executed
# in-process via ``SkillRunner.plan_and_run`` instead of being dispatched over A2A.
#
# Environment variables (all optional, defaults matched with SemanticDomain):
#   ENABLE_LOCAL_SKILLS            : "true" to turn the feature on (default: true)
#   LOCAL_SKILLS_DIR               : directory containing skill zip packs (default: /app/skills/)
#   LOCAL_SKILL_AGENT_NAME         : display name of the synthetic card (default: LocalSkill)
#   LOCAL_SKILL_MAX_STEPS          : per-call ReAct step budget passed to SkillRunner
#   LOCAL_SKILL_CMD_TIMEOUT_SEC    : subprocess timeout passed to SkillRunner
#   LOCAL_SKILL_MAX_CONCURRENCY    : max concurrent plan_cmd executions, 0 = unlimited
#   LOCAL_SKILL_FALLBACK_ON_NONE   : when planner emits agent=NONE, try LocalSkill first
#   LOCAL_SKILL_INJECT_CARD        : auto|always|never (default: auto)
LOCAL_SKILL_AGENT_NAME = os.getenv("LOCAL_SKILL_AGENT_NAME", "LocalSkill").strip() or "LocalSkill"
LOCAL_SKILLS_ENABLED = os.getenv("ENABLE_LOCAL_SKILLS", "true").strip().lower() in ("1", "true", "yes")
LOCAL_SKILLS_DIR = os.getenv("LOCAL_SKILLS_DIR", "/app/skills/").strip()
LOCAL_SKILL_FALLBACK_ON_NONE = os.getenv("LOCAL_SKILL_FALLBACK_ON_NONE", "true").strip().lower() in ("1", "true", "yes")
LOCAL_SKILL_INJECT_MODE = os.getenv("LOCAL_SKILL_INJECT_CARD", "auto").strip().lower()
try:
    LOCAL_SKILL_MAX_STEPS = int(os.getenv("LOCAL_SKILL_MAX_STEPS", "20"))
except (TypeError, ValueError):
    LOCAL_SKILL_MAX_STEPS = 20
try:
    LOCAL_SKILL_CMD_TIMEOUT_SEC = int(os.getenv("LOCAL_SKILL_CMD_TIMEOUT_SEC", "30"))
except (TypeError, ValueError):
    LOCAL_SKILL_CMD_TIMEOUT_SEC = 30
try:
    LOCAL_SKILL_MAX_CONCURRENCY = int(os.getenv("LOCAL_SKILL_MAX_CONCURRENCY", "8"))
except (TypeError, ValueError):
    LOCAL_SKILL_MAX_CONCURRENCY = 8

# CodeExecution — inject ``code_exec`` tool into SkillRunner ReAct loop.
ENABLE_CODE_EXEC = os.getenv("ENABLE_CODE_EXEC", "true").strip().lower() in ("1", "true", "yes")
try:
    CODE_EXEC_MAX_RETRIES = int(os.getenv("CODE_EXEC_MAX_RETRIES", "3"))
except (TypeError, ValueError):
    CODE_EXEC_MAX_RETRIES = 3

# Failure reason codes emitted when LocalSkill cannot complete a task.
# Listed in the priority order used by ``_select_retry_reason_code``.
LOCAL_SKILL_FAIL_REASONS: tuple[str, ...] = (
    "local_skill_declined",
    "local_skill_max_steps",
    "local_skill_no_finish",
    "local_skill_no_selection",
    "local_skill_not_found",
    "local_skill_error",
)

def tasklist_to_string(task_list: TaskList, participant_chain: Optional[List[str]] = None) -> str:
    """Format task list for UI. participant_chain: full path [root -> ... -> leaf] for display when forwarded."""
    lines = []
    agent_display_base = " -> ".join(participant_chain) if participant_chain else None
    for task in task_list.tasks:
        if (task.agent or "").strip().upper() == "NONE":
            line = f"[{task.id}]: {NONE_TASK_DESCRIPTION} - [NONE]"
        else:
            agent_display = agent_display_base if agent_display_base else task.agent
            line = f"[{task.id}]: {task.description} - [{agent_display}]"
        lines.append(line)
    return "\nAll Tasks:\n" + "\n".join(lines) + "\n\n"

class PlannerAgent(BaseAgent):
    """Planner Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        semantic_group_id: str = None
    ):
        logger.info('Initializing PlannerAgent')
        logger.info(f"PlannerAgent received semantic_group_id: {semantic_group_id}")

        super().__init__(
            agent_name='PlannerAgent',
            description='Breakdown the user request into executable tasks',
            content_types=['text', 'text/plain'],
        )
        self.manager = ModelManager()
        _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        # Force the planner onto the structured tool-call path so it cannot
        # regress to returning prompt-shaped JSON text. The fallback below is
        # only for providers whose bind_tools implementation lacks tool_choice.
        try:
            self.llm = self.llm.bind_tools(
                [self.make_plan_tool],
                tool_choice="make_plan_cmd",
            )
        except TypeError:
            # Some OpenAI-compatible providers do not accept tool_choice.
            # Keep tool binding plus the existing nudge loop as a fallback.
            self.llm = self.llm.bind_tools([self.make_plan_tool])
        self.make_plan_max_attempts = int(os.getenv("MAKE_PLAN_MAX_ATTEMPTS", "3"))
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.semantic_group_id = semantic_group_id

    make_plan_tool: ClassVar[Any]

    @tool("make_plan_cmd", args_schema=TaskList)
    def make_plan_tool(
        thought_process: Optional[str] = None,
        original_query: Optional[str] = None,
        tasks: List[PlannerTask] = None
    ) -> str:
        """Create a structured plan with tasks to be executed sequentially.

        Supply the plan through this tool's structured arguments. The planner
        consumes the tool-call arguments directly instead of parsing JSON text.
        
        Args:
            thought_process: The internal reasoning steps of the planner
            original_query: The original user query for context
            tasks: A list of PlannerTask objects to be executed sequentially
        
        Returns:
            Serialized plan when the tool is executed directly.
        """
        plan_data = {
            "thought_process": thought_process,
            "original_query": original_query,
            "tasks": [task.dict() if isinstance(task, PlannerTask) else task for task in (tasks or [])]
        }
        return json.dumps(plan_data, ensure_ascii=False)

    # generate agent skills string
    def format_agent_skills(self, skills_list):
        result_lines = []
        
        for i, skill in enumerate(skills_list, 1):
            lines = [
                f"Skill {i}:",
                f"  ID: {skill.id}",
                f"  Name: {skill.name}",
                f"  Description: {skill.description}",
            ]

            if skill.tags:
                lines.append(f"  Tags: {', '.join(skill.tags)}")
            
            if skill.examples:
                lines.append(f"  Examples: {', '.join(skill.examples)}")
            
            result_lines.extend(lines)
            result_lines.append("")

        if result_lines and result_lines[-1] == "":
            result_lines.pop()
        
        return "\n".join(result_lines)

    # Create a prompt for the large language model to generate relevant information about all agents in order to determine which agents to use
    def generate_system_prompt_agents(self, agent_cards) -> str:
        if not agent_cards:
            return ""
        lines = []
        for index, agent_card in enumerate(agent_cards, start=1):
            skills = self.format_agent_skills(agent_card.skills) if getattr(agent_card, "skills", None) else "（无）"
            block = [
                f"--- 智能体 {index} ---",
                f"name: {agent_card.name}",
                f"description: {agent_card.description or ''}",
                f"skills:\n{skills}" if skills and skills.strip() else "skills: （无）",
            ]
            lines.append("\n".join(block))
        return "\n\n".join(lines)

    async def get_history(self) -> list:
        """
        human: Hello  
        assistant: Hello! How can I help you?  
        human: What's the weather like today?  
        assistant: Please provide your location information.
        """

        logger.info(f"PlannerAgent get_history metadata: user_id: {self.metadata.get('user_id', '')}, agent_id:{self.metadata.get('agent_id', '')}, run_id:{self.metadata.get('run_id', '')}")
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        if normalize_history_turns(propagated.get("turns")):
            return history_text_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
                user_id=self.metadata.get('user_id', ''),
                run_id=self.metadata.get('run_id', ''),
                limit=get_conversation_history_limit()
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"PlannerAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"PlannerAgent get_history response : {search_items}")
        return history_text_from_payload(
            history_payload_from_search_items(search_items, source="sg_orchestrator_fallback")
        )

    # Legacy text-output parser retained for compatibility with its standalone
    # recovery test. make_plan() now consumes make_plan_cmd arguments directly.
    def format_llm_output(self, answer) -> dict:
        """Parse the planner LLM output into a dict with heavy tolerance.

        LLMs frequently emit malformed JSON — the most common failure in our
        logs is a user query containing a JSON/code fragment being inlined into
        a string value without escaping the inner double quotes, e.g.::

            "original_query": "请将 JSON {"category":"手机"} 格式化..."

        The recovery chain below handles this progressively:

        1. Strict ``json.loads`` on the raw content.
        2. Strict ``json.loads`` after stripping ``` code fences.
        3. Targeted inner-quote escaping for known long-string fields
           (``original_query`` / ``description`` / ``thought_process`` /
           ``reason``) — the fields where this failure pattern overwhelmingly
           occurs.
        4. ``json_repair`` — a tolerant LLM-oriented parser (external dep,
           fails soft if not installed).
        5. ``ast.literal_eval`` for python-style dict literals.
        6. Naive single-quote -> double-quote substitution as a last resort.

        Returns the parsed dict, or ``None`` if every strategy failed.
        """
        raw = getattr(answer, "content", "") or ""

        try:
            return json.loads(raw, strict=False)
        except json.JSONDecodeError:
            pass

        cleaned_content = raw.strip()
        if cleaned_content.startswith('```json'):
            cleaned_content = cleaned_content[7:]
        elif cleaned_content.startswith('```'):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            return json.loads(cleaned_content, strict=False)
        except json.JSONDecodeError as e2:
            logger.error(f" === format_llm_output, Parsing failed after cleanup.: {e2}")

        escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                parsed = json.loads(escaped_content, strict=False)
                logger.info(" === format_llm_output, recovered via inner-quote field escaping")
                return parsed
            except json.JSONDecodeError as e_esc:
                logger.warning(f" === format_llm_output, field-escape pre-pass still invalid: {e_esc}")

        if _json_repair is not None:
            try:
                repaired = _json_repair(escaped_content, return_objects=True)
                if isinstance(repaired, dict):
                    logger.info(" === format_llm_output, recovered via json_repair")
                    return repaired
                if isinstance(repaired, str):
                    parsed = json.loads(repaired, strict=False)
                    if isinstance(parsed, dict):
                        logger.info(" === format_llm_output, recovered via json_repair (string)")
                        return parsed
            except Exception as e_rep:  # noqa: BLE001
                logger.error(f" === format_llm_output, json_repair failed: {e_rep}")
        else:
            logger.warning(
                " === format_llm_output, json_repair not installed; "
                "add 'json-repair' to dependencies to improve LLM JSON tolerance"
            )

        try:
            import ast
            parsed = ast.literal_eval(cleaned_content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError) as e3:
            logger.error(f" === format_llm_output, ast parsing fail: {e3}")
        except Exception as e5:  # noqa: BLE001
            logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        try:
            parsed = json.loads(cleaned_content.replace("'", '"'), strict=False)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e4:
            logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")

        return None

    async def make_plan(
        self,
        query,
        agent_cards,
        group_memory: str = "",
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
    ) -> TaskList:

        information = ""
        if replan_context or replan_guidance:
            info_parts: List[str] = []
            if replan_context:
                info_parts.append(
                    "REPLAN_CONTEXT(JSON):\n"
                    + json.dumps(replan_context, ensure_ascii=False)
                )
            if replan_guidance:
                info_parts.append(f"REPLAN_GUIDANCE:\n{replan_guidance}")
            information = "\n\n".join(info_parts)

        system_template = ""
        if self.enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_ZH

        human_template = "{query}"

        # Few-shot values below illustrate make_plan_cmd arguments. They are
        # injected as semantic examples, not as instructions to emit JSON text.
        json_prompt_instructions_zh: dict = {
            "thought_process": "[Step1 数据需求] 子问1: 核心数据需求=北京当下的实时气象观测数据, 过滤维度=城市(北京)+当下时刻; 子问2: 核心数据需求=与给定天气相匹配的穿衣搭配建议(知识/咨询型), 过滤维度=该天气条件。 [Step2 本体性质] 子问1=(A)静态本体(气象站持续观测产出的'天气状态量', 即使无人查询也客观存在); 子问2=(B)动态产出(由穿衣推理这一动作生成的建议)。 [Step3 业务能力匹配] 天气查询员的核心业务是'获取并提供气象观测/天气状态'→子问1是它的直接职责覆盖→选定承接子问1; 时尚顾问的核心业务是'根据情境产出穿搭建议'→子问2是它的自然产物→选定承接子问2。 [Step4 自检] (1) 本体性质与所选 Agent 业务能力相容: 是; (2) 是否仅因名词同名/字面相关而路由: 否(基于业务本质); (3) 是否存在业务本质更直接对应的另一 Agent: 无。 [Step5 上下文] 无可复用结果, 无需纠偏。 [Step6 跨域] 涉及气象与生活方式两个领域, 且穿衣建议依赖天气结果, 故拆分为两个任务并建立依赖。description 忠实转述用户原话, 不添加额外条件。",
            "original_query": "帮我查询北京的天气并推荐合适的穿衣建议",
            "tasks": [
                {
                    "id": 1,
                    "description": "查询北京的天气", 
                    "agent": "天气查询员",
                    "depends_on": []
                },
                {
                    "id": 2,
                    "description": "推荐合适的穿衣建议",
                    "agent": "时尚顾问",
                    "depends_on": [1]
                }
            ]
        }

        json_prompt_instructions_en: dict = {
            "thought_process": "[Step1 Data Need] Subq1: core-need=current real-time meteorological observation for Beijing, filter=city(Beijing)+now; Subq2: core-need=outfit/styling advice matching the given weather, filter=that weather condition. [Step2 Ontology] Subq1=(A) Static-State (weather observations exist objectively regardless of any query); Subq2=(B) Dynamic-Output (advice produced by a styling inference action). [Step3 Capability Semantics] Weather-Checker's business is to fetch and serve meteorological state → Subq1 is its direct duty → owns Subq1; Fashion-Consultant's business is to produce outfit advice from a context → Subq2 is its natural output → owns Subq2. [Step4 Self-Check] (1) Ontology vs chosen agent's capability are aligned: yes; (2) Routed solely by noun/keyword coincidence: no, based on business essence; (3) Any agent more essentially aligned: none. [Step5 Context] No reusable prior result, no correction needed. [Step6 Cross-Domain] Two distinct domains (meteorology vs lifestyle) with sequential dependency, so split into two tasks with dependency. Note: description faithfully relays user's words without adding extra conditions.",
            "original_query": "Help me check the weather in Beijing and recommend suitable clothing advice",
            "tasks": [
                {
                    "id": 1,
                    "description": "Check the weather in Beijing", 
                    "agent": "Weather-Checker",
                    "depends_on": []
                },
                {
                    "id": 2,
                    "description": "Recommend suitable clothing advice",
                    "agent": "Fashion-Consultant",
                    "depends_on": [1]
                }
            ]
        }

        # When no agent is relevant, return a single task with agent "NONE" and fixed description
        json_prompt_no_agent_en: dict = {
            "thought_process": "[Step1 Data Need] core-need=knowledge/explanation about the Starlink project (aerospace + satellite-communication domain), filter=Starlink. [Step2 Ontology] (B) Dynamic-Output (an explanation produced by a knowledge-bearing agent). [Step3 Capability Semantics] Reviewed every available agent's business essence — none of them naturally produces aerospace/satellite knowledge as a core duty. [Step4 Self-Check] (1) No agent's business naturally covers this need: confirmed; (2) Not routed by noun coincidence: yes; (3) Any agent more essentially aligned: none. [Step5 Context] N/A. [Step6 Cross-Domain] N/A. Conclusion: subject lies outside every available agent's business sovereignty, fall back to NONE.",
            "original_query": "What is the Starlink project?",
            "tasks": [
                {
                    "id": 1,
                    "description": NONE_TASK_DESCRIPTION,
                    "agent": "NONE"
                }
            ]
        }

        system_prompt = None

        if self.enable_history == "enable":
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["history", "agents", "information", "group_memory"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents", "information", "group_memory"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        user_id = self.metadata.get('user_id', '')
        run_id = self.metadata.get('run_id', '')
        trace_id = self.metadata.get('trace_id', '')
        replan_marker_count = str(query or "").count("REPLAN_CONTEXT(JSON):")
        history = ""
        planner_prompt_chars = (
            len(str(system_template or ""))
            + len(str(query or ""))
            + len(str(system_prompt_agents or ""))
            + len(str(information or ""))
            + len(str(group_memory or ""))
        )

        if self.enable_history == "enable":
            history = await self.get_history()
            planner_prompt_chars += len(str(history or ""))

        logger.info(
            "[RetryAware][PlannerInput] query_chars=%d replan_context_chars=%d group_memory_chars=%d replan_marker_count=%d planner_prompt_chars=%d agent_count=%d agents=%s",
            len(str(query or "")),
            len(str(information or "")),
            len(str(group_memory or "")),
            replan_marker_count,
            planner_prompt_chars,
            len(agent_cards or []),
            ", ".join(getattr(c, "name", "") or "(unnamed)" for c in (agent_cards or [])),
        )

        # Build initial messages (system + human) for tool-calling loop
        format_kwargs = {
            "query": query,
            "agents": system_prompt_agents,
            "information": information,
            "group_memory": group_memory,
        }
        if self.enable_history == "enable":
            format_kwargs["history"] = history
        messages = chat_prompt.format_messages(**format_kwargs)

        tasks = None

        with langfuse.start_as_current_span(
            name="biz-orchestrator-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            for attempt in range(1, self.make_plan_max_attempts + 1):
                logger.info(
                    "make_plan llm_invoke attempt=%d/%d messages=%d",
                    attempt,
                    self.make_plan_max_attempts,
                    len(messages),
                )
                answer = await self.llm.ainvoke(
                    messages,
                    config={"callbacks": [langfuse_handler]},
                )
                messages.append(answer)
                tool_calls = getattr(answer, "tool_calls", None) or []
                logger.info(
                    "make_plan llm_reply attempt=%d tool_calls=%s content=%r",
                    attempt,
                    [c.get("name") for c in tool_calls],
                    str(getattr(answer, "content", ""))[:200],
                )

                if not tool_calls:
                    logger.warning(
                        "make_plan attempt %s/%s: no tool call, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你上一次没有调用工具。请**必须**调用 `make_plan_cmd` 工具来输出规划结果。"
                                "不要直接输出文本或 JSON。"
                            )
                        )
                    )
                    continue

                call = next(
                    (c for c in tool_calls if c.get("name") == "make_plan_cmd"),
                    None,
                )
                if call is None:
                    logger.warning(
                        "make_plan attempt %s/%s: unknown tool=%r, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                        [c.get("name") for c in tool_calls],
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你调用了未知工具。请只使用 `make_plan_cmd` 工具来输出规划结果。"
                            )
                        )
                    )
                    continue

                args = call.get("args", {}) or {}
                logger.info(
                    "make_plan attempt=%d args keys=%s",
                    attempt,
                    list(args.keys()),
                )

                try:
                    tasks = TaskList(
                        thought_process=args.get("thought_process"),
                        # This value is already known by the caller. Do not trust
                        # the model to reproduce punctuation and quoting exactly.
                        original_query=str(query),
                        tasks=args.get("tasks") or [],
                    )
                except Exception as e:
                    logger.warning(
                        "make_plan attempt %s/%s: failed to parse TaskList from args: %s, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                        e,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                f"工具调用参数解析失败: {e}。"
                                "请检查 `tasks` 字段格式是否正确（需要 id, description, agent 三个字段），"
                                "并重新调用 `make_plan_cmd`。"
                            )
                        )
                    )
                    continue

                if not tasks.tasks:
                    logger.warning(
                        "make_plan attempt %s/%s: empty tasks list, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你返回的 `tasks` 列表为空。必须至少包含一个任务。"
                                "如果确实没有合适的智能体，请使用 agent='NONE' 和 "
                                f"description='{NONE_TASK_DESCRIPTION}'。"
                            )
                        )
                    )
                    continue

                logger.info(
                    "make_plan SELECTED attempt=%d tasks_count=%d",
                    attempt,
                    len(tasks.tasks),
                )
                for t in tasks.tasks:
                    logger.info(
                        "  task id=%s agent=%s depends_on=%s description=%s",
                        t.id,
                        t.agent,
                        t.depends_on,
                        str(t.description)[:120],
                    )
                break

            span.update_trace(
                output={
                    "tasks": tasks.model_dump() if tasks else None,
                }
            )

        langfuse.flush()

        if tasks is None:
            logger.warning(
                "make_plan EXIT no_valid_selection after %s attempts.",
                self.make_plan_max_attempts,
            )
            tasks = TaskList(
                thought_process=(
                    f"Planner failed to produce a valid plan "
                    f"after {self.make_plan_max_attempts} attempts."
                ),
                original_query=str(query),
                tasks=[
                    PlannerTask(
                        id=1,
                        description=NONE_TASK_DESCRIPTION,
                        agent="NONE",
                    )
                ],
            )

        logger.info(f" === PlannerAgent.make_plan , tasks = {tasks}")

        return tasks


class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        semantic_group_id:str = None,
        debug: int = 0,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        max_loops: int = None,
        agent_card: AgentCard = None,
        skill_runner: "SkillRunner | None" = None,
    ):
        logger.info('Initializing OrchestratorAgent')
        logger.info(f"OrchestratorAgent received semantic_group_id: {semantic_group_id}")

        super().__init__(
            agent_name=((agent_id or semantic_group_id or "OrchestratorAgent").strip()),
            description='call related agent than answer user question using agents answers.',
            content_types=['text', 'text/plain'],
        )
        self.planner_agent = PlannerAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=False,
            temperature=temperature,
            data_services_url=data_services_url,
            metadata=metadata,
            enable_history=enable_history,
            agent_id=agent_id,
            semantic_group_id=semantic_group_id
        )
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.data_services_url = data_services_url
        self.manager = ModelManager()
        _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        # Non-streaming LLM instance for tool-call based invocations.
        # When stream=True, ChatOpenAI returns AsyncStream instead of AIMessage,
        # breaking .tool_calls extraction.  This instance is used exclusively by
        # invoke_llm_with_tool() from tool_call_utils.
        self.llm_non_stream = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=False,
            extra_body=_extra_body,
        )
        self.semantic_group_id = semantic_group_id
        self.debug = debug
        self.tasks_status = []
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.enable_history = enable_history
        self.agent_id = (agent_id or self.agent_name).strip()
        self.max_loop_count = max_loops if max_loops is not None else 2
        self.loop_retry_delay = 1
        self.agent_cards = []
        self.agent_card = agent_card
        self._no_sidecar_fallback = False
        self._last_retry_reason_code = ""
        self._last_retry_action = ""
        self._task_eval_results: Dict[int, TaskOutcomeEval] = {}
        self._last_split_decision_trace: Dict[str, Any] = {}
        # LocalSkill (route B) binding. When non-None, the orchestrator exposes
        # a synthetic AgentCard named ``LOCAL_SKILL_AGENT_NAME`` to the planner
        # and intercepts tasks routed to it in ``a2a_tasks``.
        self.skill_runner = skill_runner
        self._routing_agent_pool: list[dict] | None = None
        self._routing_skip_broadcast_used = False
        self.local_skill_agent_name = LOCAL_SKILL_AGENT_NAME
        if self.skill_runner is not None:
            try:
                _loaded = len(getattr(self.skill_runner.lister, "skills", []) or [])
            except Exception:  # noqa: BLE001
                _loaded = -1
            logger.info(
                "[LocalSkill][Bind] SemanticGroup OrchestratorAgent bound SkillRunner: agent_name=%s "
                "skills_loaded=%s max_concurrency=%s",
                self.local_skill_agent_name,
                _loaded,
                getattr(self.skill_runner, "max_concurrency", None),
            )

    # ------------------------------------------------------------------
    # LocalSkill (route B) helpers
    # ------------------------------------------------------------------
    def _has_local_skill(self) -> bool:
        return self.skill_runner is not None and SkillRunner is not None

    def _is_local_skill_task(self, task: "PlannerTask") -> bool:
        if not self._has_local_skill():
            return False
        return (getattr(task, "agent", "") or "").strip() == self.local_skill_agent_name

    def _should_inject_local_skill_card(self) -> bool:
        """Decide whether to add the synthetic LocalSkill card to agent_cards."""
        if not self._has_local_skill():
            logger.info(
                "[LocalSkill][InjectDecision] skip: skill_runner not available "
                "(ENABLE_LOCAL_SKILLS=%s, skill_sdk_importable=%s)",
                LOCAL_SKILLS_ENABLED,
                SkillRunner is not None,
            )
            return False
        mode = LOCAL_SKILL_INJECT_MODE
        if mode == "never":
            logger.info("[LocalSkill][InjectDecision] skip: LOCAL_SKILL_INJECT_CARD=never")
            return False
        if mode == "always":
            logger.info("[LocalSkill][InjectDecision] inject: LOCAL_SKILL_INJECT_CARD=always")
            return True
        # auto: inject when we have loaded zip skills.
        try:
            skills_loaded = len(getattr(self.skill_runner.lister, "skills", []) or [])
        except Exception:  # noqa: BLE001
            logger.exception("[LocalSkill][InjectDecision] failed to read skills list")
            return False
        if skills_loaded > 0:
            logger.info(
                "[LocalSkill][InjectDecision] inject (mode=auto): skills_loaded=%d",
                skills_loaded,
            )
            return True
        logger.info(
            "[LocalSkill][InjectDecision] skip (mode=auto): no skills loaded "
            "(LOCAL_SKILLS_DIR=%s)",
            LOCAL_SKILLS_DIR or "(empty)",
        )
        return False

    def _build_local_skill_card(self) -> AgentCard:
        """Render currently-loaded skills into an AgentCard description.

        The URL is a sentinel — ``find_agent`` will resolve it but A2A dispatch
        never actually contacts it; ``a2a_tasks`` intercepts the task earlier.
        """
        lines: list[str] = []
        try:
            for s in (self.skill_runner.lister.skills or []):
                name = str(getattr(s, "name", "") or "").strip()
                desc = str(getattr(s, "description", "") or "").strip().replace("\n", " ")
                if len(desc) > 140:
                    desc = desc[:140] + "..."
                if name:
                    lines.append(f"- {name}: {desc}")
        except Exception:  # noqa: BLE001
            logger.exception("[LocalSkill][CardBuild] failed to render skill list for AgentCard")
        if not lines:
            description = (
                "本地技能执行器。当前未加载任何技能；若被选中，将回退为不可用。"
            )
            logger.warning(
                "[LocalSkill][CardBuild] rendering empty LocalSkill card (no skills loaded); "
                "planner will see a no-op capability"
            )
        else:
            preview = lines[:30]
            description = "本地技能执行器，可在本进程内直接运行以下技能：\n" + "\n".join(preview)
            if len(lines) > 30:
                description += f"\n（另有 {len(lines) - 30} 个技能未列出）"
            logger.info(
                "[LocalSkill][CardBuild] rendered AgentCard: skills_count=%d (shown=%d, hidden=%d)",
                len(lines),
                min(len(lines), 30),
                max(0, len(lines) - 30),
            )
        return AgentCard(
            name=self.local_skill_agent_name,
            description=description,
            url="local://skill-runner",
            version="1.0.0",
            skills=[],
            capabilities=AgentCapabilities(),
            default_input_modes=["text", "text/plain"],
            default_output_modes=["text", "text/plain"],
        )

    @staticmethod
    def _map_skill_runner_status(raw_status: Any) -> tuple[str, str]:
        """Map ``SkillRunner.plan_and_run`` status -> (task_status, failure_reason_code)."""
        s = str(raw_status or "").strip().lower()
        if s == "completed":
            return "complete", ""
        if s == "no_suitable_skill":
            return "fail", "local_skill_declined"
        if s == "no_skill_selected":
            return "fail", "local_skill_no_selection"
        if s == "skill_not_found":
            return "fail", "local_skill_not_found"
        if s == "max_steps_exceeded":
            return "fail", "local_skill_max_steps"
        if s == "completed_without_finish":
            return "fail", "local_skill_no_finish"
        return "fail", "local_skill_error"

    def _apply_local_skill_reason_code(self, task_id: int, reason_code: str) -> None:
        """Overwrite the failure_reason_code on a task_status entry.

        ``_update_task_status`` only assigns ``failure_reason_code`` when an
        ``eval_result`` is provided. For LocalSkill runs there is no
        TaskOutcomeEval, so we set the code directly (same contract as
        SemanticDomain).
        """
        if not reason_code:
            return
        for t in self.tasks_status:
            if t.id == task_id:
                t.failure_reason_code = reason_code
                break

    def _maybe_append_local_skill_card(self, cards: list[AgentCard]) -> list[AgentCard]:
        """Append the synthetic LocalSkill card when route B is enabled + allowed."""
        if not self._should_inject_local_skill_card():
            return cards
        try:
            card = self._build_local_skill_card()
        except Exception:  # noqa: BLE001
            logger.exception(
                "[LocalSkill][Inject] failed to build local skill AgentCard; skipping injection"
            )
            return cards
        try:
            skills_count = len(getattr(self.skill_runner.lister, "skills", []) or [])
        except Exception:  # noqa: BLE001
            skills_count = -1
        logger.info(
            "[LocalSkill][Inject] appended synthetic AgentCard name=%s skills_count=%d "
            "(total cards: %d → %d)",
            card.name,
            skills_count,
            len(cards),
            len(cards) + 1,
        )
        return list(cards) + [card]

    async def _run_local_skill_task(
        self,
        task: "PlannerTask",
        *,
        updater,
        task_name: str,
        think: list,
        current_agents_knowledge: list,
        retry_count: int,
        task_desc_preview: str,
    ) -> None:
        """Execute a task routed to the local skill executor.

        Never raises; every failure lands in ``TaskStatus`` with a
        ``local_skill_*`` reason code so the existing replan logic can pick it
        up. The caller is expected to ``continue`` the outer loop immediately
        after this returns.
        """
        metadata = self.metadata or {}
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
        run_id = metadata.get("run_id") if isinstance(metadata, dict) else None

        desc_preview = (task.description or "").replace("\n", " ")
        if len(desc_preview) > 180:
            desc_preview = desc_preview[:180] + "..."
        logger.info(
            "[LocalSkill][RunStart] task_id=%s retry=%d query=%r (user_id=%s run_id=%s)",
            task.id,
            retry_count,
            desc_preview,
            user_id,
            run_id,
        )
        t0 = _time.perf_counter()

        try:
            result = await self.skill_runner.plan_and_run(
                query=task.description,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        except asyncio.CancelledError:
            logger.warning("[LocalSkill][RunCancel] task_id=%s cancelled", task.id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LocalSkill][RunError] plan_and_run raised for task_id=%s", task.id)
            result = {
                "status": "local_skill_error",
                "skill": "",
                "final_answer": f"LocalSkill execution error: {exc}",
                "attempts": [],
            }

        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        status_code, reason_code = self._map_skill_runner_status(result.get("status"))
        final_answer = str(result.get("final_answer") or "").strip()
        skill_name_used = str(result.get("skill") or "")
        attempts = result.get("attempts") or []

        try:
            _result_dump = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception:  # noqa: BLE001
            _result_dump = repr(result)
        logger.info(
            "[LocalSkill][RunResult] task_id=%s skill=%s status=%s elapsed_ms=%d result:\n%s",
            task.id,
            skill_name_used or "(unknown)",
            result.get("status"),
            elapsed_ms,
            _result_dump,
        )

        answer_preview = final_answer.replace("\n", " ")
        if len(answer_preview) > 200:
            answer_preview = answer_preview[:200] + "..."

        if status_code == "complete":
            logger.info(
                "[LocalSkill][RunOK] task_id=%s skill=%s attempts=%d elapsed_ms=%d answer=%r",
                task.id,
                skill_name_used or "(unknown)",
                len(attempts),
                elapsed_ms,
                answer_preview,
            )
        else:
            logger.warning(
                "[LocalSkill][RunFail] task_id=%s skill=%s status=%s reason=%s attempts=%d "
                "elapsed_ms=%d answer=%r",
                task.id,
                skill_name_used or "(none)",
                result.get("status"),
                reason_code,
                len(attempts),
                elapsed_ms,
                answer_preview or "(empty)",
            )

        display_answer = final_answer or (
            f"LocalSkill did not produce a final answer (status={result.get('status')})."
        )
        # No TaskOutcomeEval is produced for LocalSkill runs; status is set directly.
        self._update_task_status(task.id, status_code, display_answer)
        if status_code == "fail" and reason_code:
            self._apply_local_skill_reason_code(task.id, reason_code)

        current_agents_knowledge.append(
            self._format_task_knowledge(
                task.id,
                task.description,
                self.local_skill_agent_name,
                display_answer,
                status_code,
            )
        )

        if self.debug == 1:
            dbg_text = (
                f"Task [{task.id}] via LocalSkill"
                f"{f' (skill={skill_name_used})' if skill_name_used else ''}:\n"
                f"{display_answer}\n"
            )
            think.append(dbg_text)

        extra: Dict[str, Any] = {
            "task_agent": self.local_skill_agent_name,
            "task_status": status_code,
            "execution_mode": "local_skill",
            "local_skill_name": skill_name_used,
            "local_skill_attempts": len(attempts),
            "local_skill_status": str(result.get("status") or ""),
        }
        if reason_code:
            extra["reason_code"] = reason_code
        await self.emit_progress(
            updater,
            task_name,
            event="task_finished",
            message=(
                f"completed task {task.id} via LocalSkill"
                if status_code == "complete"
                else f"failed task {task.id} via LocalSkill ({reason_code or 'error'})"
            ),
            status="done" if status_code == "complete" else "fail",
            task_id=task.id,
            extra=extra,
        )

    async def _try_local_skill_fallback_for_none(
        self,
        task: "PlannerTask",
        *,
        updater,
        task_name: str,
        think: list,
        current_agents_knowledge: list,
        retry_count: int,
        task_desc_preview: str,
    ) -> bool:
        """Attempt LocalSkill as a fallback when planner returned ``agent=NONE``.

        Returns ``True`` iff LocalSkill completed successfully; the caller
        should skip the default NONE handling in that case. Failures (including
        explicit skill declines) return ``False`` so the caller can fall back
        to the original ``NONE_TASK_DESCRIPTION`` behaviour.
        """
        desc_preview = (task.description or "").replace("\n", " ")
        if len(desc_preview) > 180:
            desc_preview = desc_preview[:180] + "..."
        logger.info(
            "[LocalSkill][NoneFallback] task_id=%s retry=%d — planner returned NONE, trying LocalSkill; query=%r",
            task.id,
            retry_count,
            desc_preview,
        )
        metadata = self.metadata or {}
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
        run_id = metadata.get("run_id") if isinstance(metadata, dict) else None
        t0 = _time.perf_counter()
        try:
            result = await self.skill_runner.plan_and_run(
                query=task.description,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        except asyncio.CancelledError:
            logger.warning("[LocalSkill][NoneFallback] task_id=%s cancelled during fallback", task.id)
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "[LocalSkill][NoneFallback] plan_and_run raised for task_id=%s — falling back to NONE",
                task.id,
            )
            return False

        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        try:
            _result_dump = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception:  # noqa: BLE001
            _result_dump = repr(result)
        logger.info(
            "[LocalSkill][NoneFallback][RunResult] task_id=%s skill=%s status=%s elapsed_ms=%d result:\n%s",
            task.id,
            result.get("skill") or "(unknown)",
            result.get("status"),
            elapsed_ms,
            _result_dump,
        )
        if str(result.get("status") or "").strip().lower() != "completed":
            logger.info(
                "[LocalSkill][NoneFallback] task_id=%s declined (status=%s skill=%s elapsed_ms=%d) "
                "— falling back to NONE",
                task.id,
                result.get("status"),
                result.get("skill") or "(none)",
                elapsed_ms,
            )
            return False

        final_answer = str(result.get("final_answer") or "").strip() or NONE_TASK_DESCRIPTION
        skill_name_used = str(result.get("skill") or "")
        answer_preview = final_answer.replace("\n", " ")
        if len(answer_preview) > 200:
            answer_preview = answer_preview[:200] + "..."
        logger.info(
            "[LocalSkill][NoneFallback] task_id=%s rescued by skill=%s elapsed_ms=%d answer=%r",
            task.id,
            skill_name_used or "(unknown)",
            elapsed_ms,
            answer_preview,
        )

        self._update_task_status(task.id, "complete", final_answer)
        current_agents_knowledge.append(
            self._format_task_knowledge(
                task.id, task.description, self.local_skill_agent_name, final_answer, "complete"
            )
        )
        if self.debug == 1:
            dbg_text = (
                f"Task [{task.id}] via LocalSkill (NONE fallback"
                f"{f', skill={skill_name_used}' if skill_name_used else ''}):\n"
                f"{final_answer}\n"
            )
            think.append(dbg_text)

        await self.emit_progress(
            updater,
            task_name,
            event="task_finished",
            message=f"completed task {task.id} via LocalSkill (NONE fallback)",
            status="done",
            task_id=task.id,
            extra={
                "task_agent": self.local_skill_agent_name,
                "task_status": "complete",
                "execution_mode": "local_skill_fallback",
                "local_skill_name": skill_name_used,
                "reason_code": "local_skill_fallback_ok",
            },
        )
        return True

    def _count_replan_context_markers(self, text: str) -> int:
        raw = str(text or "")
        return raw.count("REPLAN_CONTEXT(JSON):")

    def _strip_replan_context_block(self, text: str) -> str:
        raw = str(text or "")
        marker = "REPLAN_CONTEXT(JSON):"
        idx = raw.find(marker)
        if idx < 0:
            return raw.strip()
        return raw[:idx].strip()

    def _count_retry_banner_hits(self, text: str) -> int:
        raw = str(text or "")
        return (
            raw.count("=== 计划执行遇到问题，正在进行第 ")
            + raw.count("=== Plan execution encountered issues, performing retry attempt ")
        )

    def _count_failure_analysis_hits(self, text: str) -> int:
        raw = str(text or "")
        return raw.count("失败分析:") + raw.count("Failure analysis:")

    def _strip_retry_diagnostics_block(self, text: str) -> str:
        """Display/planning cleanup: remove nested retry/failure-analysis narratives."""
        raw = str(text or "")
        cut_markers = [
            "=== 计划执行遇到问题，正在进行第 ",
            "=== Plan execution encountered issues, performing retry attempt ",
            "失败分析:",
            "Failure analysis:",
        ]
        cut_indexes = [raw.find(marker) for marker in cut_markers if raw.find(marker) >= 0]
        if not cut_indexes:
            return raw.strip()
        cut_at = min(cut_indexes)
        tail = raw[cut_at:]
        # Strict mode: keep full text only when the explicit success marker exists.
        success_marker = "reason:The current answer addresses the question very well."
        if success_marker.lower() in tail.lower():
            return raw.strip()
        return raw[:cut_at].strip()

    def _sanitize_display_text(self, text: str) -> str:
        """Generate clean business text while preserving NON_RETRYABLE marker semantics."""
        raw = str(text or "")
        cleaned = self._strip_retry_diagnostics_block(self._strip_replan_context_block(raw))
        if NON_RETRYABLE_MARKER in raw and NON_RETRYABLE_MARKER not in cleaned:
            return f"{NON_RETRYABLE_MARKER}\n{cleaned}" if cleaned else NON_RETRYABLE_MARKER
        if NON_RETRYABLE_REPEAT_MARKER in raw and NON_RETRYABLE_REPEAT_MARKER not in cleaned:
            # Preserve REPEATED_FAILURE marker upward so an outer-layer SG / SG
            # Orchestrator can still see the structured signal and either route
            # via the sovereignty index or abort with full attribution.
            return (
                f"{NON_RETRYABLE_REPEAT_MARKER}\n{cleaned}"
                if cleaned else NON_RETRYABLE_REPEAT_MARKER
            )
        return cleaned

    def _get_sg_memory_owner(self) -> str:
        group_id = (self.semantic_group_id or "").strip()
        return f"sg:{group_id}" if group_id else "sg:unknown"

    # get all plans (agent names) for user question to execute
    async def get_plan(
        self,
        query,
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
    ) -> Optional[TaskList]:
        base_query = self._strip_replan_context_block(query)
        if self._routing_pool_flow_enabled():
            self._init_routing_pool_from_metadata()
            augmented_pool, _, _ = await self._resolve_planner_agent_pool(base_query)
            self.agent_cards = augmented_pool
        else:
            self.agent_cards = await self.list_agent_cards(base_query)
        if len(self.agent_cards) == 0:
            return None
        if len(self.agent_cards) == 1:
            agent_name = self.agent_cards[0].name
            logger.info("get_plan: only 1 agent (%s), skip LLM make_plan", agent_name)
            return TaskList(
                thought_process="Single agent available, direct assignment.",
                original_query=base_query,
                tasks=[PlannerTask(id=1, description=base_query, agent=agent_name)],
            )
        group_memory = await self.get_memory(base_query)
        logger.info(
            "[MemoryUse][SG][PlannerInput] owner=%s query_chars=%d memory_chars=%d memory_non_empty=%s",
            self._get_sg_memory_owner(),
            len(str(base_query or "")),
            len(str(group_memory or "")),
            bool(str(group_memory or "").strip()),
        )
        # 打印查询出的 memory 内容（超过 500 字符时截断，避免日志过长）
        _mem_preview = (group_memory or "").strip()
        if _mem_preview:
            _mem_display = _mem_preview if len(_mem_preview) <= 500 else _mem_preview[:500] + "...[truncated]"
            logger.info("[MemoryUse][SG][PlannerInput] memory_content=%s", repr(_mem_display))
        try:
            return await self.planner_agent.make_plan(
                base_query,
                self.agent_cards,
                group_memory=group_memory,
                replan_context=replan_context,
                replan_guidance=replan_guidance,
            )
        except ValueError as e:
            logger.warning("get_plan: make_plan failed (unparseable LLM output): %s", e)
            return None


    async def _batch_llm_evaluate(self, query: str, all_agent_cards: list[AgentCard]) -> list[AgentCard]:
        """全量 agent 分批并发 LLM 评估，取 top-k 可信度最高的 agent。"""
        if not all_agent_cards:
            return []
        batch_size = int(os.getenv("BATCH_LLM_BATCH_SIZE", "10"))
        top_k = int(os.getenv("BATCH_LLM_TOP_K", "10"))
        name_to_card = {getattr(c, "name", ""): c for c in all_agent_cards if getattr(c, "name", None)}

        def format_agents_for_eval(cards: list) -> str:
            lines = []
            for i, c in enumerate(cards, 1):
                skills = self.planner_agent.format_agent_skills(c.skills) if getattr(c, "skills", None) else "（无）"
                lines.append(f"--- 智能体 {i} ---\nname: {c.name}\ndescription: {c.description or ''}\nskills: {skills}")
            return "\n\n".join(lines)

        async def eval_one_batch(batch_cards: list[AgentCard]) -> list[dict]:
            agents_str = format_agents_for_eval(batch_cards)
            prompt = AGENT_SELECTION_EVALUATION_PROMPT.format(query=query, agents=agents_str)
            try:
                eval_tool = StructuredTool(
                    name="evaluate_agent_batch",
                    description="评估每个候选智能体能否处理用户问题，给出可信度评分。",
                    args_schema=AgentSelectionEvalResult,
                    func=None,
                    coroutine=None,
                )
                result = await invoke_llm_with_tool(
                    llm=self.llm_non_stream,
                    tool=eval_tool,
                    messages=[HumanMessage(content=prompt)],
                    metadata=self.metadata,
                    tool_choice="evaluate_agent_batch",
                    span_name="group-batch-agent-eval",
                    span_input={"query": query, "batch_size": len(batch_cards)},
                )
                items = result.get("result", []) if result else []
                return items
            except Exception as e:
                logger.warning(f"batch_llm_evaluate error: {e}, using full batch as fallback")
                return [{"agent": c.name, "can_handle": True, "confidence": 0.5, "reason": "parse_fallback"} for c in batch_cards]

        batches = [all_agent_cards[i:i + batch_size] for i in range(0, len(all_agent_cards), batch_size)]
        batch_results = await asyncio.gather(*[eval_one_batch(b) for b in batches])
        merged = []
        for result_list in batch_results:
            for item in result_list:
                if isinstance(item, dict) and item.get("agent"):
                    merged.append(item)
        scored = [(r.get("confidence", 0), r.get("agent", "")) for r in merged if r.get("can_handle", False)]
        scored.sort(key=lambda x: (-x[0], x[1]))
        selected_names = [name for _, name in scored[:top_k]]
        selected = [name_to_card[n] for n in selected_names if n in name_to_card]
        if not selected and all_agent_cards:
            selected = all_agent_cards[:top_k]
        logger.info(f"batch_llm_evaluate: selected {len(selected)} agents from {len(all_agent_cards)}, top: {selected_names[:5]}")
        return selected

    def _build_own_expert_card(self) -> Optional[AgentCard]:
        """Build an AgentCard for this orchestrator's own sidecar expert agent (localhost:10101)."""
        has_expert_agent = os.getenv("HAS_EXPERTAGENT", "true").strip().lower() in ("true", "1", "yes")
        if not has_expert_agent or self.agent_card is None:
            return None
        _dump = getattr(self.agent_card, "model_dump", None) or getattr(self.agent_card, "dict", None)
        card_dict = dict(_dump()) if _dump else {}
        card_dict["url"] = "http://localhost:10101"
        return AgentCard(**card_dict)

    def _fallback_to_own_expert(self, agent_cards: list) -> list[AgentCard]:
        """无可用 agent 时，若部署了 expert agent（HAS_EXPERTAGENT=true 默认），回退到自身的 expert agent（10101 端口）。"""
        if len(agent_cards) > 0:
            self._no_sidecar_fallback = False
            return agent_cards
        own = self._build_own_expert_card()
        if own is not None:
            logger.info("No agent from registry; fallback to own expert agent (localhost:10101)")
            self._no_sidecar_fallback = False
            return [own]
        logger.warning("No agent from registry and HAS_EXPERTAGENT=false (or agent_card unset); cannot fallback")
        self._no_sidecar_fallback = True
        return []

    def _filter_tree_internal_agents(self, agent_cards: list[AgentCard]) -> list[AgentCard]:
        """Filter out tree-internal agents (-sg- and -dd- patterns) from the candidate pool.
        These should only be reached through their own group's Expert Agent tree routing.
        Utility agents (Chart, Translation, etc.) without these patterns are preserved."""
        filtered = []
        removed = 0
        for c in agent_cards:
            name = getattr(c, "name", "") or ""
            if "-sg-" in name or "-dd-" in name:
                removed += 1
                continue
            filtered.append(c)
        if removed > 0:
            logger.info("Filtered out %d tree-internal agent(s) (-sg-/-dd-), keeping %d utility agent(s)", removed, len(filtered))
        return filtered

    def _filter_internal_agents_for_collaboration_pool(self, agent_cards: list[AgentCard]) -> list[AgentCard]:
        """Remove only -dd- tree-internal agents; keep -sg- orchestrators for cross-SG collaboration.

        The global registry pool may list other Semantic Group orchestrators (``*-sg-*``).
        Plain ``_filter_tree_internal_agents`` would drop them as "tree-internal"; the
        collaboration planner needs those cards reachable from the augmented pool."""
        filtered = []
        removed = 0
        for c in agent_cards:
            name = getattr(c, "name", "") or ""
            if "-dd-" in name:
                removed += 1
                continue
            filtered.append(c)
        if removed > 0:
            logger.info(
                "Collaboration pool: filtered out %d -dd-only tree-internal agent(s), keeping %d agent(s)",
                removed,
                len(filtered),
            )
        return filtered

    def _looks_like_sg_orchestrator_identity(self, card: AgentCard) -> bool:
        """Collaboration delegation targets are SG orchestrators (``…-sg-<id>``), not Chart/Skill utilities."""
        name = getattr(card, "name", "") or ""
        return "-sg-" in name

    def _dedupe_agent_cards_by_name_preserve_order(self, cards: list[AgentCard]) -> tuple[list[AgentCard], int]:
        """First occurrence wins. Returns (deduped_list, removed_duplicate_row_count)."""
        seen: set[str] = set()
        out: list[AgentCard] = []
        for c in cards:
            n = getattr(c, "name", "") or ""
            if n in seen:
                continue
            seen.add(n)
            out.append(c)
        return out, len(cards) - len(out)

    def _routing_pool_flow_enabled(self) -> bool:
        return os.getenv("ENABLE_ROUTING_AGENT_POOL", "true").strip().lower() in ("true", "1", "yes")

    def _sg_capability_rebroadcast_enabled(self) -> bool:
        return os.getenv("ENABLE_SG_CAPABILITY_REBROADCAST", "true").strip().lower() in ("true", "1", "yes")

    def _self_planner_agent_name(self) -> str:
        if self.agent_card and getattr(self.agent_card, "name", None):
            return str(self.agent_card.name)
        return (self.agent_id or self.agent_name or "").strip()

    def _init_routing_pool_from_metadata(self, metadata: Optional[dict] = None) -> None:
        md = metadata if isinstance(metadata, dict) else (self.metadata if isinstance(self.metadata, dict) else {})
        parsed = sg_broadcast.parse_routing_agent_pool(md)
        if parsed:
            self._routing_agent_pool = parsed

    def _may_skip_routing_broadcast(self) -> bool:
        if not self._routing_pool_flow_enabled():
            return False
        md = self.metadata if isinstance(self.metadata, dict) else {}
        if md.get("collaboration_delegation") is True:
            return False
        hint = md.get(sg_broadcast.SG_EXECUTION_HINT_KEY)
        if isinstance(hint, dict) and hint.get("missing_requirements"):
            logger.info(
                "[RoutingPool] skip broadcast blocked | missing_requirements=%s",
                list(hint.get("missing_requirements") or [])[:8],
            )
            return False
        if not md.get(sg_broadcast.ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY):
            return False
        if self._routing_skip_broadcast_used:
            return False
        pool = self._routing_agent_pool or sg_broadcast.parse_routing_agent_pool(md)
        return bool(pool)

    def _build_local_execution_pool(self) -> list[AgentCard]:
        own = self._build_own_expert_card()
        cards = [own] if own else []
        return self._maybe_append_local_skill_card(cards)

    async def _legacy_collab_planner_pools(
        self,
        query: str,
    ) -> tuple[list[AgentCard], set[str], set[str]]:
        own_cards = await self.list_agent_cards(query, for_collaboration=True)
        collaborator_cards = await self.discover_collaborator_sgs()
        raw_augmented = (own_cards or []) + (collaborator_cards or [])
        augmented_pool, _ = self._dedupe_agent_cards_by_name_preserve_order(raw_augmented)
        own_names = {c.name for c in (own_cards or [])}
        collab_names = {c.name for c in (collaborator_cards or [])}
        return augmented_pool, own_names, collab_names

    async def _resolve_planner_agent_pool(
        self,
        query: str,
    ) -> tuple[list[AgentCard], set[str], set[str]]:
        """Build planner agent_cards: local execution pool + peer SGs from routing pool or broadcast."""
        if not self._routing_pool_flow_enabled():
            return await self._legacy_collab_planner_pools(query)

        md = self.metadata if isinstance(self.metadata, dict) else {}
        pool: list[dict]

        if self._may_skip_routing_broadcast():
            pool = self._routing_agent_pool or sg_broadcast.parse_routing_agent_pool(md)
            self._routing_agent_pool = pool
            self._routing_skip_broadcast_used = True
            logger.info(
                "[RoutingPool] skip SG broadcast (root first plan) pool_size=%d",
                len(pool),
            )
        elif self._sg_capability_rebroadcast_enabled():
            capable = await sg_broadcast.broadcast_capability_check(
                query,
                str(md.get("user_id", "")),
                str(md.get("run_id", "")),
                str(md.get("trace_id", "")),
                propagated_history=parse_propagated_history(md.get(PROPAGATED_HISTORY_KEY)),
                get_response_text=self.get_response_text,
            )
            pool = sg_broadcast.build_routing_agent_pool(capable)
            self._routing_agent_pool = pool
            logger.info(
                "[RoutingPool] SG rebroadcast refreshed pool_size=%d query_chars=%d",
                len(pool),
                len(str(query or "")),
            )
        elif self._routing_agent_pool:
            pool = self._routing_agent_pool
        else:
            return await self._legacy_collab_planner_pools(query)

        peer_cards = sg_broadcast.pool_to_peer_agent_cards(pool, self._self_planner_agent_name())
        local_cards = self._build_local_execution_pool()
        augmented_pool, dup_drop = self._dedupe_agent_cards_by_name_preserve_order(local_cards + peer_cards)
        own_names = {getattr(c, "name", "") for c in local_cards if getattr(c, "name", "")}
        collab_names = {getattr(c, "name", "") for c in peer_cards if getattr(c, "name", "")}
        logger.info(
            "[RoutingPool] planner_pool local=%d peer=%d total=%d dup_dropped=%d",
            len(local_cards),
            len(peer_cards),
            len(augmented_pool),
            dup_drop,
        )
        return augmented_pool, own_names, collab_names

    def _parse_agent_cards_from_response(self, raw_list: list) -> list[AgentCard]:
        """Parse raw agent data (from asearch or list_all) into AgentCard list."""
        cards = []
        for item in raw_list:
            agent_data = item.get("agent", item) if isinstance(item, dict) else item
            if isinstance(agent_data, dict):
                cards.append(AgentCard(**agent_data))
            elif hasattr(agent_data, "__dict__"):
                cards.append(AgentCard(**agent_data.__dict__))
        return cards

    def _filter_stale_semantic_group_agents(self, agent_cards: list[AgentCard]) -> list[AgentCard]:
        """Filter out stale semantic group agents (same prefix, different instance)."""
        my_agent_id = self.agent_id or ""
        if not my_agent_id or "-sg-" not in my_agent_id:
            return agent_cards
        sg_prefix = my_agent_id.rsplit("-sg-", 1)[0] + "-sg-"
        before = len(agent_cards)
        filtered = [
            c for c in agent_cards
            if not (getattr(c, "name", "").startswith(sg_prefix) and getattr(c, "name", "") != my_agent_id)
        ]
        if before - len(filtered) > 0:
            logger.info(f"Filtered out {before - len(filtered)} stale semantic group agent(s)")
        return filtered

    async def _list_agent_cards_semantic_group(self, query, *, for_collaboration: bool = False) -> list[AgentCard]:
        """SemanticGroup mode: candidate pool = own Expert Agent + global utility agents.

        Default: tree-internal agents (-sg-/-dd-) are filtered out (cross-tree routing off).
        When ``for_collaboration``: keep -sg- orchestrators so other SGs stay in the pool;
        still drop -dd- subtree-internal agents."""
        own_expert = self._build_own_expert_card()
        if own_expert is None:
            logger.warning("SemanticGroup mode: cannot build own expert card, no agents available")
            self._no_sidecar_fallback = True
            return []
        self._no_sidecar_fallback = False

        agent_registry_client = AgentRegistryClient()
        try:
            raw = await agent_registry_client.alist_all_agents()
            all_cards = self._parse_agent_cards_from_response(raw)
        except Exception as e:
            logger.warning("Failed to fetch global agents: %s, using own expert only", e)
            return [own_expert]

        utility_cards = (
            self._filter_internal_agents_for_collaboration_pool(all_cards)
            if for_collaboration
            else self._filter_tree_internal_agents(all_cards)
        )

        expert_name = getattr(own_expert, "name", "") or ""
        if for_collaboration and expert_name:
            _n = len(utility_cards)
            utility_cards = [c for c in utility_cards if (getattr(c, "name", "") or "") != expert_name]
            if _n > len(utility_cards):
                logger.info(
                    "SemanticGroup [collaboration]: removed %d registry row(s) duplicate of this_SG_expert=%s",
                    _n - len(utility_cards),
                    expert_name,
                )

        # ── Strip other SG orchestrators (*-sg-*) from the OWN pool ──
        # In collaboration mode, peer SG cards must only enter through
        # discover_collaborator_sgs() → collaborator_names.  If we keep
        # them in own_names they collide with delegation routing and defeat
        # hop/chaining.
        if for_collaboration:
            _n_before = len(utility_cards)
            utility_cards = [c for c in utility_cards if "-sg-" not in (getattr(c, "name", "") or "")]
            _dropped = _n_before - len(utility_cards)
            if _dropped:
                logger.info(
                    "SemanticGroup [collaboration]: removed %d other-SG card(s) from own pool "
                    "(SG routing must go through delegate_to_collaborator_sg)",
                    _dropped,
                )

        if not utility_cards:
            logger.info("SemanticGroup mode: no utility agents found, fast path with own expert only")
            return [own_expert]

        candidates = [own_expert] + utility_cards
        expert_name = getattr(own_expert, "name", "") or "(unnamed)"
        registry_names = sorted(getattr(c, "name", "") or "(unnamed)" for c in utility_cards)
        reg_other_sg = sorted(n for n in registry_names if "-sg-" in n)
        reg_tools = sorted(n for n in registry_names if "-sg-" not in n)

        return candidates

    async def discover_collaborator_sgs(self) -> list[AgentCard]:
        """Return **peer SG orchestrator** cards (name contains ``-sg-``), excluding self.

        The collaboration collection often also lists ChartAgent / SkillAgent / etc.; those are
        not valid cross-SG delegation endpoints and are skipped (see skip log line).

        Re-delegation to previously visited SGs is now allowed (A→B→A is permitted).
        Hop-based depth limiting (CROSS_SG_MAX_HOP) prevents infinite delegation loops.
        """
        agent_registry_client = AgentRegistryClient()
        coll_collection = os.getenv(
            "SG_COLLABORATION_COLLECTION",
            "biz_orchestrator_agent_cards",
        )
        try:
            raw = await agent_registry_client.alist_all_agents(
                collection=coll_collection,
            )
            all_cards = self._parse_agent_cards_from_response(raw)
        except Exception as e:
            logger.warning("Failed to discover collaborator SGs: %s", e)
            return []
        all_cards = self._filter_stale_semantic_group_agents(all_cards)
        my_name = (self.agent_card.name if self.agent_card else self.agent_name)

        # ── allow re-delegation to SGs already in the chain; only exclude self ──
        # Previously SGs in the delegation_chain were removed from the candidate pool
        # to enforce a DAG. Removing the DAG constraint allows A→B→A patterns (e.g.
        # Order delegates to User, and User needs to go back to Order for a follow-up).
        # Hop-based depth limiting prevents infinite loops.
        chain = list((self.metadata or {}).get("delegation_chain", []))
        not_myself = [c for c in all_cards if c.name != my_name]

        skipped_non_sg = sorted({c.name for c in not_myself if not self._looks_like_sg_orchestrator_identity(c)})
        cards = [c for c in not_myself if self._looks_like_sg_orchestrator_identity(c)]
        coll_names = sorted(c.name for c in cards if getattr(c, "name", ""))
        if chain:
            logger.info(
                "Cross-SG [collaborator discovery from %s]: re-delegation allowed; prior chain: %s",
                coll_collection,
                ", ".join(chain),
            )
        if skipped_non_sg:
            logger.info(
                "Cross-SG [collaborator discovery from %s]: skipped %d row(s) that are not SG orchestrators "
                "(name must contain '-sg-'): %s",
                coll_collection,
                len(skipped_non_sg),
                ", ".join(skipped_non_sg),
            )
        logger.info(
            "Cross-SG [delegation targets — SG orchestrators only from %s]: %d peer SG card row(s), "
            "excluding self=%s: %s",
            coll_collection,
            len(cards),
            my_name or "?",
            ", ".join(coll_names) if coll_names else "(none)",
        )
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
        progress_updater: Optional[Any] = None,
        progress_artifact_name: str = "collaboration-progress",
        execution_hint: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a structured delegation request to another SG Orchestrator.

        Uses A2A SendStreamingMessage with metadata so the downstream SG
        can recognise the request as a collaboration delegation.
        When ``execution_hint`` is present (from that peer's capability_check),
        it is transported opaquely so the peer can reuse member evidence.
        """
        chain = list(delegation_chain or [])
        ctx = dict(upstream_context or {})

        metadata: Dict[str, Any] = {
            "collaboration_delegation": True,
            "hop_remaining": hop_remaining,
            "delegation_chain": chain,
            "upstream_context": ctx,
            "user_id": user_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "delegator_name": self.agent_name,
            "skip_history_write": True,
        }
        if isinstance(execution_hint, dict) and execution_hint:
            metadata[SG_EXECUTION_HINT_KEY] = execution_hint
            logger.info(
                "[Cross-SG][Delegate] transporting peer execution_hint | target=%s "
                "selected_members=%s can_handle=%s",
                getattr(target_card, "name", ""),
                (execution_hint.get("selected_members") or [])[:10],
                execution_hint.get("can_handle"),
            )

        send_payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task_description}],
                "messageId": uuid4().hex,
            },
            "metadata": metadata,
        }

        timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=target_card)
            streaming_req = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_payload),
            )
            stream = client.send_message_streaming(streaming_req)
            result = await self.stream_a2a_collect_forward_progress_frames(
                stream,
                self.get_response_text,
                progress_updater,
                progress_artifact_name,
            )
        logger.info(
            "Cross-SG: delegation to %s done, result_chars=%d",
            target_card.name,
            len(result),
        )
        return result

    async def list_agent_cards(self, query, *, for_collaboration: bool = False) -> list[AgentCard]:
        """Reads agent cards from registry.
        - SemanticGroup mode: scoped pool (own expert + utility agents, no cross-tree)
        - SemanticDomain mode: controlled by AGENT_SELECTION_MODE (batch_llm / vector)
        - ``for_collaboration=True`` (SG mode only): same fetch but retention of ``-sg-`` cards

        The synthetic LocalSkill card (route B) is appended at the end when
        ``_should_inject_local_skill_card`` allows it, so every selection path
        uniformly exposes it to the planner.
        """
        if self.semantic_group_id:
            cards = await self._list_agent_cards_semantic_group(query, for_collaboration=for_collaboration)
            return self._maybe_append_local_skill_card(cards)

        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("CollectionName", "biz_expert_agent_cards")
        mode = os.getenv("AGENT_SELECTION_MODE", "batch_llm").strip().lower()

        try:
            if mode == "vector":
                cards = await self._list_agent_cards_vector(query, agent_registry_client, collection_name)
            else:
                cards = await self._list_agent_cards_batch_llm(query, agent_registry_client, collection_name)
            return self._maybe_append_local_skill_card(cards)
        except Exception as e:
            logger.error(f"An error occurred during list_agent_cards: {e}")
            raise ValueError(f"An error occurred during list_agent_cards: {e}")

    async def _list_agent_cards_vector(self, query, agent_registry_client, collection_name) -> list[AgentCard]:
        """Vector search mode: asearch -> parse -> filter -> fallback."""
        response = await agent_registry_client.asearch(query, collection_name=collection_name)
        if response.status != "success":
            logger.warning(f"Search returned non-success status: {response.status}")
            return self._fallback_to_own_expert([])
        agent_cards_dict = []
        for item in response.result:
            metadata = item.metadata
            agent_data = metadata.get("agent", {})
            if isinstance(agent_data, dict):
                agent_cards_dict.append(agent_data)
            elif hasattr(agent_data, "__dict__"):
                agent_cards_dict.append(agent_data.__dict__.copy())
        agent_cards = [AgentCard(**d) for d in agent_cards_dict]
        agent_cards = self._filter_stale_semantic_group_agents(agent_cards)
        logger.info(f"vector mode: retrieved {len(agent_cards)} agent cards")
        return self._fallback_to_own_expert(agent_cards)

    async def _list_agent_cards_batch_llm(self, query, agent_registry_client, collection_name) -> list[AgentCard]:
        """Batch LLM mode: list_all -> batch_llm_evaluate -> filter -> fallback."""
        raw = await agent_registry_client.alist_all_agents()
        all_cards = self._parse_agent_cards_from_response(raw)
        all_cards = self._filter_stale_semantic_group_agents(all_cards)
        if not all_cards:
            logger.warning("list_all_agents returned empty")
            return self._fallback_to_own_expert([])
        selected = await self._batch_llm_evaluate(query, all_cards)
        logger.info(f"batch_llm mode: selected {len(selected)} from {len(all_cards)} agents")
        return self._fallback_to_own_expert(selected)


    # handle response artifact-update event to get knowledge string from a2a server
    def get_response_text(self, chunk) -> str:
        data = chunk.model_dump(mode='json', exclude_none=True)
        if (result := data.get('result')) is not None:
            kind = result.get('kind')
            if kind == 'artifact-update':
                artifact = result.get('artifact')
                parts = artifact.get('parts') or []
                if isinstance(parts, list):
                    texts = [str(p.get('text') or "") for p in parts if isinstance(p, dict) and p.get('text') is not None]
                    return "".join(texts)

            return ""

    @staticmethod
    def build_progress_frame(
        event: str,
        *,
        message: str = "",
        status: str = "running",
        run_id: str = "",
        user_id: str = "",
        agent_id: str = "",
        task_id: Optional[int] = None,
        layer: str = "sg_orchestrator",
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        allowed = PROGRESS_EXTRA_ALLOWLIST.get(event, set())
        filtered_extra: Dict[str, Any] = {}
        if extra and allowed:
            filtered_extra = {k: v for k, v in extra.items() if k in allowed}
        payload: Dict[str, Any] = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "layer": layer,
            "event": event,
            "run_id": run_id or "",
            "user_id": user_id or "",
            "agent_id": agent_id or "",
            "task_id": task_id,
            "message": message or "",
            "status": status or "",
        }
        if filtered_extra:
            payload.update(filtered_extra)
        return f"[[DAC_PROGRESS]] {json.dumps(payload, ensure_ascii=False)}\n"

    @staticmethod
    def is_progress_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_PROGRESS]] ")

    @staticmethod
    def build_answer_frame(
        event: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        status: str = "done",
        run_id: str = "",
        user_id: str = "",
        agent_id: str = "",
        task_id: Optional[int] = None,
        layer: str = "sg_orchestrator",
    ) -> str:
        body: Dict[str, Any] = {
            "schema_version": ANSWER_SCHEMA_VERSION,
            "frame_type": "answer",
            "layer": layer,
            "event": event,
            "run_id": run_id or "",
            "user_id": user_id or "",
            "agent_id": agent_id or "",
            "task_id": task_id,
            "status": status or "",
            "payload": payload or {},
        }
        return f"{ANSWER_FRAME_PREFIX}{json.dumps(body, ensure_ascii=False)}\n"

    @staticmethod
    def is_answer_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith(ANSWER_FRAME_PREFIX)

    @classmethod
    def parse_answer_frame(cls, text: str) -> Optional[Dict[str, Any]]:
        if not cls.is_answer_frame(text):
            return None
        raw = text.lstrip()
        payload = raw[len(ANSWER_FRAME_PREFIX):].strip()
        try:
            data = json.loads(payload)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def is_summary_artifact(text: str) -> bool:
        """Detect DAC_SUMMARY frame (SD Orchestrator → SG Orchestrator / SG Expert)."""
        return isinstance(text, str) and text.lstrip().startswith(SUMMARY_FRAME_PREFIX)

    @staticmethod
    def parse_summary_artifact(text: str) -> Optional[str]:
        """Parse DAC_SUMMARY frame; return summary text or None if not a summary frame."""
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        if not stripped.startswith(SUMMARY_FRAME_PREFIX):
            return None
        json_str = stripped[len(SUMMARY_FRAME_PREFIX):]
        try:
            payload = json.loads(json_str)
            return payload.get("summary", "")
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _downstream_answer_model_for_a2a(agent_name: str, agent_card: Any = None) -> str:
        """SD domain orchestrators (-dd-) emit DAC_SUMMARY via summarized; others stay original."""
        name = (agent_name or "").strip().lower()
        if not name and agent_card is not None:
            name = (getattr(agent_card, "name", "") or "").strip().lower()
        if "-dd-" in name:
            return "summarized"
        return "original"

    @staticmethod
    def _finalize_a2a_collected_text(raw_parts: List[str], summary_text: Optional[str]) -> str:
        """Prefer DAC_SUMMARY over raw step chunks when SD orchestrator summarized downstream."""
        if summary_text is not None:
            return (summary_text or "").strip()
        return "\n".join(raw_parts).strip() if raw_parts else ""

    @classmethod
    def strip_progress_lines(cls, text: str) -> str:
        if not text:
            return ""
        lines = [line for line in text.splitlines() if not cls.is_progress_frame(line)]
        return "\n".join(lines).strip()

    @staticmethod
    async def stream_a2a_collect_forward_progress_frames(
        stream_chunks: AsyncIterable[Any],
        get_text_fn: Callable[[Any], str],
        updater: Optional[Any],
        progress_artifact_name: str,
    ) -> str:
        """Consume A2A streaming chunks: relay DAC progress/answer frames to ``updater`` (same artifact name as ``a2a_tasks`` path) and return body text for summaries.

        Collaborative mode previously concatenated Expert streams verbatim, hiding
        ``[[DAC_PROGRESS]]`` from RoutingAgent and poisoning downstream LLM prompts.
        """
        line_buf = ""
        result_segments: list[str] = []
        summary_text: Optional[str] = None

        async def handle_line(raw_line: str) -> None:
            nonlocal summary_text
            s = raw_line.strip()
            if not s:
                return
            if OrchestratorAgent.is_progress_frame(s):
                if updater is not None:
                    await updater.add_artifact(
                        [TextPart(text=s + "\n")],
                        name=progress_artifact_name,
                    )
                return
            if OrchestratorAgent.is_summary_artifact(s):
                parsed = OrchestratorAgent.parse_summary_artifact(s)
                if parsed is not None:
                    summary_text = parsed
                return
            if OrchestratorAgent.is_answer_frame(s):
                if updater is not None:
                    await updater.add_artifact(
                        [TextPart(text=s + "\n")],
                        name=progress_artifact_name,
                    )
                data = OrchestratorAgent.parse_answer_frame(s) or {}
                if str(data.get("event") or "").strip() == "final_answer":
                    payload = data.get("payload") or {}
                    ft = str(payload.get("text") or "").strip()
                    if ft:
                        result_segments.append(ft)
                return
            result_segments.append(s)

        async for chunk in stream_chunks:
            text = get_text_fn(chunk)
            if not text:
                continue
            stripped = text.strip()
            if OrchestratorAgent.is_summary_artifact(stripped):
                parsed = OrchestratorAgent.parse_summary_artifact(stripped)
                if parsed is not None:
                    summary_text = parsed
                continue
            line_buf += text
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                await handle_line(line)
        if line_buf:
            await handle_line(line_buf)

        body = OrchestratorAgent._finalize_a2a_collected_text(result_segments, summary_text)
        return OrchestratorAgent.strip_progress_lines(body)

    def current_agent_label(self) -> str:
        return (self.agent_id or self.semantic_group_id or self.agent_name or "sg_orchestrator").strip()

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 320) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit - 3] + "..."

    @classmethod
    def build_group_plan_ready_progress(
        cls,
        *,
        task_list: TaskList,
        user_query: str = "",
        replan: bool = False,
        retry_count: Optional[int] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Build concise message + extra fields for group_plan_ready (orchestrator identity is in agent_id/event)."""
        tasks = list(getattr(task_list, "tasks", None) or [])
        n = len(tasks)
        thought_raw = (getattr(task_list, "thought_process", None) or "").strip()
        planner_thought = cls._truncate_progress_message(thought_raw, 480) if thought_raw else ""
        orig_from_plan = (getattr(task_list, "original_query", None) or "").strip()
        query_source = (user_query or "").strip() or orig_from_plan
        query_preview = cls._truncate_progress_message(query_source, 220)

        task_lines: List[str] = []
        for t in tasks[:20]:
            tid = getattr(t, "id", 0)
            desc = cls._truncate_progress_message(getattr(t, "description", "") or "", 150)
            task_lines.append(f"#{tid} {desc}")
        if len(tasks) > 20:
            task_lines.append(f"... +{len(tasks) - 20} more task(s)")
        plan_tasks_summary = " ; ".join(task_lines) if task_lines else "(no tasks)"
        plan_tasks_summary = cls._truncate_progress_message(plan_tasks_summary, 950)

        # message: keep payload minimal; agent_id / event / layer already identify orchestrator & plan type.
        segments: List[str] = [f"{n} task(s)", f"query: {query_preview}"]
        if planner_thought:
            segments.append(f"planner thought: {planner_thought}")
        segments.append(f"tasks: {plan_tasks_summary}")

        message = cls._truncate_progress_message(" | ".join(segments), 720)

        extra: Dict[str, Any] = {
            "task_count": n,
            "query_preview": query_preview,
            "plan_tasks_summary": plan_tasks_summary,
            "plan_tasks_agents": [
                (getattr(t, "id", 0), (getattr(t, "agent", "") or "").strip())
                for t in tasks[:40]
            ],
        }
        if planner_thought:
            extra["planner_thought"] = planner_thought
        if orig_from_plan:
            extra["original_query"] = cls._truncate_progress_message(orig_from_plan, 240)
        if replan and retry_count is not None:
            extra["retry_count"] = retry_count

        return message, extra

    async def emit_progress(
        self,
        updater: TaskUpdater,
        task_name: str,
        *,
        event: str,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        layer: str = "sg_orchestrator",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if os.getenv("ENABLE_SG_PROGRESS_STREAM", "true").strip().lower() in ("false", "0", "no"):
            return
        await updater.add_artifact(
            [TextPart(text=self.build_progress_frame(
                event,
                message=message,
                status=status,
                run_id=(self.metadata or {}).get("run_id", ""),
                user_id=(self.metadata or {}).get("user_id", ""),
                agent_id=self.agent_id or self.current_agent_label(),
                task_id=task_id,
                layer=layer,
                extra=extra,
            ))],
            name=task_name,
        )


    # find one AgentCard with agent name which is from plan task
    async def find_agent(self, agent_name) -> AgentCard:
        return resolve_agent_card_by_planner_name(self.agent_cards, agent_name)


    # call agent with a2a according to agent name which is from plan task (stream mode)
    async def a2a_stream(
        self,
        task_id,
        query,
        agent_name,
        current_tasks_status,
        prior_task_results: Optional[List[dict]] = None,
    ) -> AsyncIterable[str]:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            logger.error(
                "[A2A][stream] target agent not found: agent_name=%s, task_id=%s, run_id=%s, trace_id=%s, available_agents=%s",
                agent_name,
                task_id,
                self.metadata.get('run_id', ''),
                self.metadata.get('trace_id', ''),
                [getattr(a, "name", "") for a in self.agent_cards],
            )
            yield "Not found agent"
            return

        # memory = await self.get_memory(self._strip_replan_context_block(query))
        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata.get('user_id', ''),
            'run_id': self.metadata.get('run_id', ''),
            'trace_id': self.metadata.get('trace_id', ''),
            PROPAGATED_HISTORY_KEY: parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY)),
            'current_tasks_status': current_tasks_status,
            'current_task': f"current task id: [{task_id}], task description: {query} ",
            'current_task_id': f"{task_id}",
            # SD orchestrators (-dd-) use summarized + DAC_SUMMARY; SG experts stay original.
            'answer_model': self._downstream_answer_model_for_a2a(agent_name, agent_card),
            # 下游执行仅返回知识片段，完整对话历史由入口编排器统一落库。
            'skip_history_write': True,
        }
        if prior_task_results:
            a2a_metadata['prior_task_results'] = prior_task_results
            prior_doc, _ = self._prior_merged_items_to_document(prior_task_results)
            if prior_doc:
                a2a_metadata['upstream_prior_knowledge'] = prior_doc
                logger.info(
                    "[A2A][stream] upstream_prior_knowledge for downstream execution | chars=%d task_id=%s",
                    len(prior_doc),
                    task_id,
                )
        logger.info(
            ">>>>>> [answer_model=%s] OrchestratorAgent(SemanticGroup).a2a_stream() agent=%s <<<<<<",
            a2a_metadata['answer_model'],
            agent_name,
        )

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': a2a_metadata,
        }

        logger.info(
            "[A2A][stream] request target=%s url=%s task_id=%s run_id=%s trace_id=%s query=%s",
            agent_name,
            getattr(agent_card, "url", ""),
            task_id,
            self.metadata.get('run_id', ''),
            self.metadata.get('trace_id', ''),
            (query or "")[:120],
        )

        # build a2a client with agent_card
        _a2a_timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(_a2a_timeout, connect=10.0)) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            try:
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result != "":
                        if self.is_answer_frame(result):
                            answer_data = self.parse_answer_frame(result) or {}
                            if str(answer_data.get("event") or "").strip() == "final_answer":
                                payload = answer_data.get("payload") or {}
                                final_text = str(payload.get("text") or "").strip()
                                if final_text:
                                    yield final_text
                            continue
                        yield result

            except Exception as e:
                logger.error(
                    "[A2A][stream] request failed target=%s url=%s task_id=%s run_id=%s trace_id=%s error_type=%s error=%s",
                    agent_name,
                    getattr(agent_card, "url", ""),
                    task_id,
                    self.metadata.get('run_id', ''),
                    self.metadata.get('trace_id', ''),
                    type(e).__name__,
                    str(e),
                )
                yield "Error occurred"

    # call agent with a2a according to agent name which is from plan task (non-stream mode)
    async def a2a_non_stream(
        self,
        query,
        agent_name,
        prior_task_results: Optional[List[dict]] = None,
    ) -> str:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            logger.error(
                "[A2A][non_stream] target agent not found: agent_name=%s, run_id=%s, trace_id=%s, available_agents=%s",
                agent_name,
                self.metadata.get('run_id', ''),
                self.metadata.get('trace_id', ''),
                [getattr(a, "name", "") for a in self.agent_cards],
            )
            return "Not found agent"

        # memory = await self.get_memory(self._strip_replan_context_block(query))
        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata.get('user_id', ''),
            'run_id': self.metadata.get('run_id', ''),
            'trace_id': self.metadata.get('trace_id', ''),
            PROPAGATED_HISTORY_KEY: parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY)),
            # SD orchestrators (-dd-) use summarized + DAC_SUMMARY; SG experts stay original.
            'answer_model': self._downstream_answer_model_for_a2a(agent_name, agent_card),
            # 下游执行仅返回知识片段，完整对话历史由入口编排器统一落库。
            'skip_history_write': True,
        }
        if prior_task_results:
            a2a_metadata['prior_task_results'] = prior_task_results
            prior_doc, _ = self._prior_merged_items_to_document(prior_task_results)
            if prior_doc:
                a2a_metadata['upstream_prior_knowledge'] = prior_doc
                logger.info(
                    "[A2A][non_stream] upstream_prior_knowledge for downstream execution | chars=%d",
                    len(prior_doc),
                )
        logger.info(
            ">>>>>> [answer_model=%s] OrchestratorAgent(SemanticGroup).a2a_non_stream() agent=%s <<<<<<",
            a2a_metadata['answer_model'],
            agent_name,
        )

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': a2a_metadata,
        }

        logger.info(
            "[A2A][non_stream] request target=%s url=%s run_id=%s trace_id=%s query=%s",
            agent_name,
            getattr(agent_card, "url", ""),
            self.metadata.get('run_id', ''),
            self.metadata.get('trace_id', ''),
            (query or "")[:120],
        )

        # build a2a client with agent_card
        _a2a_timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(_a2a_timeout, connect=10.0)) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            try:
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                agent_knowledge: List[str] = []
                summary_text: Optional[str] = None
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result == "" or self.is_progress_frame(result):
                        continue
                    if self.is_summary_artifact(result):
                        parsed = self.parse_summary_artifact(result)
                        if parsed is not None:
                            summary_text = parsed
                            logger.info(
                                "[DACSummary][SG-Orch][non_stream] received summary from agent=%s (%d chars)",
                                agent_name,
                                len(parsed),
                            )
                        continue
                    if self.is_answer_frame(result):
                        answer_data = self.parse_answer_frame(result) or {}
                        if str(answer_data.get("event") or "").strip() != "final_answer":
                            continue
                        payload = answer_data.get("payload") or {}
                        final_text = str(payload.get("text") or "").strip()
                        if final_text:
                            agent_knowledge.append(final_text)
                        continue
                    agent_knowledge.append(result)
                finalized = self._finalize_a2a_collected_text(agent_knowledge, summary_text)
                if summary_text is not None:
                    logger.info(
                        "[DACSummary][SG-Orch][non_stream] using summary from agent=%s, discarded %d raw chunks",
                        agent_name,
                        len(agent_knowledge),
                    )
                return finalized

            except Exception as e:
                logger.error(
                    "[A2A][non_stream] request failed target=%s url=%s run_id=%s trace_id=%s error_type=%s error=%s",
                    agent_name,
                    getattr(agent_card, "url", ""),
                    self.metadata.get('run_id', ''),
                    self.metadata.get('trace_id', ''),
                    type(e).__name__,
                    str(e),
                )
                return "Error occurred"

    def _format_task_knowledge(self, task_id: int, description: str, agent: str, result: str, status: str = "") -> str:
        """将单条任务结果格式化为大模型易读的块，便于总结时区分任务与结果。"""
        agent_label = (agent or "").strip() or "（未分配）"
        status_line = f"\n【任务状态】\n{status}\n" if status else ""
        if status == "fail":
            # When a task has failed, any raw data in its result (e.g. partial
            # SQL query output) is unverified and misleading.  Replace the full
            # result with a clean failure signal so the summary LLM cannot
            # accidentally treat speculative data as confirmed facts.
            result = (
                "【此任务执行失败，以下内容为多步尝试过程摘要，其中的具体数据不可作为事实引用】\n"
                + (result or "").strip()
            )
        return f"【任务 {task_id}】\n{description}\n\n【执行 Agent】\n{agent_label}{status_line}\n【结果】\n{(result or '').strip()}"

    def _update_task_status(
        self,
        task_id: int,
        status: str,
        answer: str,
        eval_result: Optional[TaskOutcomeEval] = None,
    ):
        for task_status in self.tasks_status:
            if task_status.id == task_id:
                raw_answer = str(answer or "")
                answer_final = self._sanitize_display_text(raw_answer)
                success_marker = "reason:The current answer addresses the question very well."
                status_final = "complete" if success_marker in raw_answer else status
                task_status.status = status_final
                task_status.answer = raw_answer
                task_status.answer_final = answer_final
                task_status.marker_present = (
                    NON_RETRYABLE_MARKER in raw_answer
                    or NON_RETRYABLE_REPEAT_MARKER in raw_answer
                )
                # Keep diagnostics bounded; only needed for debug/trace, not planning payload.
                if raw_answer != answer_final:
                    task_status.diagnostics_excerpt = raw_answer[:1200]
                else:
                    task_status.diagnostics_excerpt = ""
                if eval_result is not None:
                    if status_final == "complete":
                        task_status.failure_reason_code = ""
                        task_status.failure_explanation = ""
                        task_status.missing_requirements = []
                    else:
                        task_status.failure_reason_code = str(eval_result.failure_reason_code or "")
                        task_status.failure_explanation = str(eval_result.failure_explanation or "")
                        task_status.missing_requirements = list(eval_result.missing_requirements or [])[:20]
                break

    def _normalize_prior_task_results(self, prior_task_results: List[dict]) -> List[dict]:
        """Normalize external prior_task_results into common shape."""
        out: List[dict] = []
        for item in prior_task_results or []:
            if not isinstance(item, dict):
                continue
            tid = item.get("task_id")
            agent = item.get("agent", "")
            result = (
                item.get("result", "")
                or item.get("final_answer", "")
                or item.get("answer_final", "")
            )
            if tid is None or not str(result).strip():
                continue
            out.append(
                {
                    "task_id": tid,
                    "agent": agent,
                    "task_description": str(
                        item.get("task_description") or item.get("description") or ""
                    ).strip(),
                    "result": str(result),
                    "status": str(item.get("status", "")),
                    "failure_reason_code": str(item.get("failure_reason_code", "")),
                    "marker_present": bool(item.get("marker_present", False)),
                }
            )
        return out

    def _collect_local_prior_task_results(self, current_task_id: int) -> List[dict]:
        out: List[dict] = []
        for t in self.tasks_status:
            result = (t.answer_final or t.answer or "").strip()
            if t.id == current_task_id or t.status != "complete" or not result:
                continue
            out.append(
                {
                    "task_id": t.id,
                    "agent": t.agent,
                    "task_description": str(t.description or "").strip(),
                    "result": result,
                    "status": t.status,
                    "failure_reason_code": t.failure_reason_code,
                    "marker_present": t.marker_present,
                }
            )
        return out

    def _merge_prior_task_results(self, p0: List[dict], p1: List[dict]) -> List[dict]:
        """Merge P0(metadata) + P1(local) with de-dup."""
        merged: List[dict] = []
        seen: set[str] = set()
        for item in (p0 or []) + (p1 or []):
            result = str(item.get("result", "")).strip()
            digest = hashlib.md5(result.encode("utf-8", errors="ignore")).hexdigest()[:10] if result else ""
            sig = f"{item.get('task_id')}|{item.get('agent','')}|{digest}"
            if sig in seen:
                continue
            seen.add(sig)
            merged.append(item)
        return merged

    def _normalize_outcome_eval_result(self, task: PlannerTask, agent_answer_raw: str, eval_result: TaskOutcomeEval) -> TaskOutcomeEval:
        normalized = eval_result.model_copy(deep=True)
        answer_text = str(agent_answer_raw or "")
        answer_lower = answer_text.lower()
        success_marker = "reason:The current answer addresses the question very well."

        # Success marker takes precedence when mixed logs contain both success and failure traces.
        if success_marker in answer_text:
            normalized.status = "complete"
            normalized.failure_reason_code = ""
            normalized.failure_explanation = ""
            normalized.missing_requirements = []
            normalized.suggested_retry_action = "replan_standard"
            return normalized

        # Strong deterministic override: marker means non-retryable out-of-scope.
        if NON_RETRYABLE_MARKER.lower() in answer_lower:
            if (
                normalized.status != "fail"
                or normalized.failure_reason_code != "non_retryable_misrouted_task"
                or normalized.suggested_retry_action != "abort"
            ):
                logger.warning(
                    "[OutcomeEval][Normalize] task=%s marker_override status=%s->fail reason=%s->non_retryable_misrouted_task action=%s->abort",
                    task.id,
                    normalized.status,
                    normalized.failure_reason_code,
                    normalized.suggested_retry_action,
                )
            normalized.status = "fail"
            normalized.failure_reason_code = "non_retryable_misrouted_task"
            normalized.suggested_retry_action = "abort"
            return normalized

        # REPEATED_FAILURE marker: when structured_control carries actionable
        # unfulfilled_needs we steer the outer loop to replan_with_decomposition
        # (sovereignty re-routing); otherwise fall back to abort like
        # OUT_OF_SCOPE.  Avoids the R5 gap where REPEATED_FAILURE was silently
        # downgraded to ``unknown_failure``.
        if NON_RETRYABLE_REPEAT_MARKER.lower() in answer_lower:
            sc = self._extract_structured_control_from_text(answer_text)
            has_needs = bool(isinstance(sc, dict) and sc.get("unfulfilled_needs"))
            normalized.status = "fail"
            if has_needs:
                normalized.failure_reason_code = "data_sovereignty_gap"
                normalized.suggested_retry_action = "replan_with_decomposition"
            else:
                normalized.failure_reason_code = "non_retryable_misrouted_task"
                normalized.suggested_retry_action = "abort"
            logger.warning(
                "[OutcomeEval][Normalize] task=%s marker=%s status=fail reason=%s action=%s",
                task.id,
                NON_RETRYABLE_REPEAT_MARKER,
                normalized.failure_reason_code,
                normalized.suggested_retry_action,
            )
            return normalized

        if normalized.status == "complete":
            normalized.failure_reason_code = ""
            if normalized.suggested_retry_action not in ALLOWED_RETRY_ACTIONS:
                normalized.suggested_retry_action = "replan_standard"
            return normalized

        reason = str(normalized.failure_reason_code or "").strip()
        if reason not in ALLOWED_FAILURE_REASON_CODES:
            logger.warning(
                "[OutcomeEval][Normalize] task=%s unknown_failure_reason_code=%s fallback=unknown_failure",
                task.id,
                reason,
            )
            normalized.failure_reason_code = "unknown_failure"

        action = str(normalized.suggested_retry_action or "").strip()
        if action not in ALLOWED_RETRY_ACTIONS:
            logger.warning(
                "[OutcomeEval][Normalize] task=%s unknown_retry_action=%s fallback=replan_standard",
                task.id,
                action,
            )
            normalized.suggested_retry_action = "replan_standard"

        if not normalized.failure_reason_code:
            normalized.failure_reason_code = "unknown_failure"

        return normalized

    async def _llm_evaluate_task_outcome(
        self,
        original_query: str,
        task: PlannerTask,
        agent_answer_raw: str,
        plan_context: List[dict],
        prior_task_results: List[dict],
    ) -> TaskOutcomeEval:
        raw_text = str(agent_answer_raw or "")
        raw_lower = raw_text.lower()
        success_marker = "reason:The current answer addresses the question very well."
        # Rule-based fast path:
        # 1) explicit domain-agent success marker -> complete
        # 2) obvious execution error/non-retryable marker -> fail
        # 3) otherwise fall back to LLM evaluation
        if success_marker in raw_text:
            logger.info(
                "[OutcomeEval][RuleBased] task=%s status=complete reason=contains_success_marker",
                task.id,
            )
            return TaskOutcomeEval(
                status="complete",
                confidence=0.99,
                failure_reason_code="",
                failure_explanation="",
                missing_requirements=[],
                suggested_retry_action="replan_standard",
            )
        if NON_RETRYABLE_MARKER.lower() in raw_lower:
            logger.warning(
                "[OutcomeEval][RuleBased] task=%s status=fail reason=marker_non_retryable_out_of_scope",
                task.id,
            )
            return TaskOutcomeEval(
                status="fail",
                confidence=0.99,
                failure_reason_code="non_retryable_misrouted_task",
                failure_explanation="Rule-based fail: agent answer contains NON_RETRYABLE::OUT_OF_SCOPE marker.",
                missing_requirements=[],
                suggested_retry_action="abort",
            )
        if NON_RETRYABLE_REPEAT_MARKER.lower() in raw_lower:
            sc = self._extract_structured_control_from_text(raw_text)
            has_needs = bool(isinstance(sc, dict) and sc.get("unfulfilled_needs"))
            if has_needs:
                logger.warning(
                    "[OutcomeEval][RuleBased] task=%s status=fail reason=data_sovereignty_gap unfulfilled=%d",
                    task.id,
                    len(sc.get("unfulfilled_needs") or []),
                )
                return TaskOutcomeEval(
                    status="fail",
                    confidence=0.99,
                    failure_reason_code="data_sovereignty_gap",
                    failure_explanation=(
                        "Rule-based fail: agent answer contains NON_RETRYABLE::REPEATED_FAILURE marker "
                        "with structured unfulfilled_needs; replan via sovereignty index."
                    ),
                    missing_requirements=[],
                    suggested_retry_action="replan_with_decomposition",
                )
            logger.warning(
                "[OutcomeEval][RuleBased] task=%s status=fail reason=marker_repeated_failure_no_needs",
                task.id,
            )
            return TaskOutcomeEval(
                status="fail",
                confidence=0.99,
                failure_reason_code="non_retryable_misrouted_task",
                failure_explanation=(
                    "Rule-based fail: agent answer contains NON_RETRYABLE::REPEATED_FAILURE marker "
                    "without actionable unfulfilled_needs; abort."
                ),
                missing_requirements=[],
                suggested_retry_action="abort",
            )
        if "error occurred" in raw_lower:
            logger.info(
                "[OutcomeEval][RuleBased] task=%s status=fail reason=contains_error_occurred",
                task.id,
            )
            return TaskOutcomeEval(
                status="fail",
                confidence=0.99,
                failure_reason_code="execution_error_no_data",
                failure_explanation="Rule-based fail: agent answer contains 'Error occurred'.",
                missing_requirements=[],
                suggested_retry_action="replan_standard",
            )
        prompt = TASK_OUTCOME_EVAL_PROMPT.format(
            original_query=original_query,
            task_id=task.id,
            task_description=task.description,
            assigned_agent=task.agent,
            agent_answer_raw=(agent_answer_raw or "")[:6000],
            plan_context=json.dumps(plan_context, ensure_ascii=False),
            prior_task_results=json.dumps(prior_task_results, ensure_ascii=False),
        )
        try:
            eval_tool = StructuredTool(
                name="evaluate_task_outcome",
                description="评估任务执行结果是否完成，输出状态、可信度、失败原因等。",
                args_schema=TaskOutcomeEvalToolResult,
                func=None,
                coroutine=None,
            )
            result = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=eval_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=self.metadata,
                tool_choice="evaluate_task_outcome",
                span_name="group-task-outcome-eval-llm",
                span_input={"task_id": task.id, "task_description": task.description, "agent": task.agent},
            )
            if result is None:
                raise ValueError("LLM did not call evaluate_task_outcome tool")
            eval_result = TaskOutcomeEval(**result)
            eval_result = self._normalize_outcome_eval_result(task=task, agent_answer_raw=agent_answer_raw, eval_result=eval_result)
            return eval_result
        except Exception as e:
            logger.warning("[OutcomeEval] LLM eval failed for task %s: %s", task.id, e)
            return TaskOutcomeEval(
                status="fail",
                confidence=0.0,
                failure_reason_code="outcome_eval_error",
                failure_explanation=f"LLM outcome evaluation failed: {e}",
                missing_requirements=[],
                suggested_retry_action="replan_standard",
            )

    def _build_replan_context(
        self,
        original_query: str,
        current_tasks: TaskList,
        retry_count: int,
        reason_code: str,
        retry_action: str,
        failure_analysis: str,
    ) -> Dict[str, Any]:
        base_query = self._strip_replan_context_block(original_query)
        plan_tasks = [
            {
                "id": t.id,
                "description": t.description,
                "agent": t.agent,
            }
            for t in (current_tasks.tasks or [])
        ]
        execution_results = []
        for t in self.tasks_status:
            eval_data = self._task_eval_results.get(t.id)
            answer_raw = str(t.answer or "")
            answer_final = str(t.answer_final or self._sanitize_display_text(answer_raw))
            answer_excerpt = answer_final[:1200]
            diagnostics_present = (
                answer_raw != answer_final
                or self._count_retry_banner_hits(answer_raw) > 0
                or self._count_failure_analysis_hits(answer_raw) > 0
            )
            failure_reason_code = str(
                t.failure_reason_code
                or (eval_data.failure_reason_code if eval_data else "")
                or ""
            )
            failure_explanation = str(
                t.failure_explanation
                or (eval_data.failure_explanation if eval_data else "")
                or ""
            )
            missing_requirements = list(
                t.missing_requirements
                or ((eval_data.missing_requirements if eval_data else []) or [])
            )[:20]
            execution_results.append(
                {
                    "task_id": t.id,
                    "description": t.description,
                    "agent": t.agent,
                    "status": t.status,
                    "failure_reason_code": failure_reason_code,
                    "failure_explanation": failure_explanation,
                    "missing_requirements": missing_requirements,
                    "marker_present": bool(t.marker_present or (NON_RETRYABLE_MARKER in answer_raw)),
                    "answer_excerpt": answer_excerpt,
                    "answer_chars": len(answer_final),
                    "answer_raw_chars": len(answer_raw),
                    "diagnostics_present": diagnostics_present,
                    "diagnostics_chars": len(str(t.diagnostics_excerpt or "")),
                    "llm_outcome_eval": eval_data.model_dump() if eval_data else {},
                }
            )
        structured_failures = [
            {
                "task_id": t.id,
                "agent": t.agent,
                "reason_code": str(
                    t.failure_reason_code
                    or ((self._task_eval_results.get(t.id).failure_reason_code if self._task_eval_results.get(t.id) else "") or "")
                ),
                "missing_requirements": list(t.missing_requirements or [])[:10],
                "marker_present": bool(t.marker_present),
                # P3 contract: surface SD Expert's machine-readable
                # unfulfilled_needs into the replan context so the Planner can
                # route by table sovereignty rather than re-guessing.
                "unfulfilled_needs": self._collect_task_unfulfilled_needs(t),
            }
            for t in self.tasks_status
            if t.status == "fail"
        ]
        return {
            "original_query": base_query,
            "last_plan": {
                "tasks": plan_tasks,
            },
            "execution_results": execution_results,
            "structured_failures": structured_failures,
            "failure_analysis": self._sanitize_display_text(failure_analysis),
            "retry_decision": {
                "retry_count": retry_count,
                "reason_code": reason_code,
                "action": retry_action,
            },
            "split_decision_trace": self._last_split_decision_trace or {},
        }

    async def _resolve_sovereignty_hints(
        self,
        replan_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute forbidden / recommended agents for a replan.

        Combines per-task ``unfulfilled_needs`` collected in
        :meth:`_build_replan_context` with the :class:`SovereigntyIndex` reverse
        lookup over the parent registry.  Returns ``{}`` when no actionable
        unfulfilled_needs are present so callers can short-circuit.
        """
        structured_failures = replan_context.get("structured_failures") or []
        forbidden_agents: List[str] = []
        all_unfulfilled: List[Dict[str, Any]] = []
        for f in structured_failures:
            if not isinstance(f, dict):
                continue
            agent_name = (f.get("agent") or "").strip()
            needs = f.get("unfulfilled_needs") or []
            if not needs:
                continue
            if agent_name and agent_name not in forbidden_agents:
                forbidden_agents.append(agent_name)
            for need in needs:
                if isinstance(need, dict) and need.get("missing_table"):
                    all_unfulfilled.append(need)

        if not all_unfulfilled:
            logger.info("[ReplanHints] no unfulfilled needs — skipping sovereignty resolution")
            return {}

        try:
            from .data_inventory import SovereigntyIndex
            own_name = (getattr(self.agent_card, "name", None) or "").strip() if getattr(self, "agent_card", None) else ""
            index = getattr(self, "_sovereignty_index", None)
            if index is None:
                index = SovereigntyIndex(
                    data_services_url=os.getenv("DataServicesURL", "http://data-services.dac.svc.cluster.local:8000"),
                    own_agent_name=own_name,
                )
                self._sovereignty_index = index
                logger.info("[ReplanHints] SovereigntyIndex created for agent=%s", own_name)
            tables = [n["missing_table"] for n in all_unfulfilled if n.get("missing_table")]
            logger.info("[ReplanHints] resolving %d missing tables via SovereigntyIndex", len(tables))
            owners_map = await index.find_owners_for_many(tables)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ReplanHints] sovereignty index lookup failed: %s", e)
            return {
                "forbidden_agents": forbidden_agents,
                "recommended_agents": [],
                "unfulfilled_needs": all_unfulfilled,
            }

        recommended: List[Dict[str, Any]] = []
        seen_tables: set = set()
        for need in all_unfulfilled:
            t = (need.get("missing_table") or "").strip()
            if not t or t.lower() in seen_tables:
                continue
            seen_tables.add(t.lower())
            owners = list(owners_map.get(t.lower()) or [])
            # Strip out the same forbidden_agents so the Planner never sees
            # itself as a recommendation for a gap it just failed to fill.
            owners = [o for o in owners if o not in forbidden_agents]
            recommended.append({
                "missing_table": t,
                "owners": owners,
            })

        hints = {
            "forbidden_agents": forbidden_agents,
            "recommended_agents": recommended,
            "unfulfilled_needs": all_unfulfilled,
        }
        logger.info(
            "[ReplanHints] sovereignty hints: forbidden=%d unfulfilled=%d recommended_groups=%d",
            len(forbidden_agents), len(all_unfulfilled), len(recommended),
        )
        logger.info(
            "[ReplanHints] sovereignty hints detail: forbidden=%s recommended=%s",
            forbidden_agents,
            [{"table": r["missing_table"], "owners": r["owners"]} for r in recommended],
        )
        return hints

    def _prior_merged_items_to_document(
        self,
        merged: List[dict],
    ) -> tuple[str, Dict[str, List[str]]]:
        """Format already-merged prior_task_results dicts into a knowledge document for downstream execution.

        Intentionally does not append heuristic \"join_key\" lines: wrong extractions can mislead SD execution;
        rely on **结果摘录** (and full prior in routing payloads) instead. Second return value is always {}.
        """
        if not merged:
            return "", {}
        merged_sorted = sorted(merged, key=lambda x: int(x.get("task_id") or 0))
        blocks: List[str] = []
        for t in merged_sorted:
            answer = (
                str(t.get("result") or "").strip()
                or str(t.get("final_answer") or "").strip()
            )
            t_desc = str(t.get("task_description") or t.get("description") or "").strip()
            desc_part = f"**任务描述：** {t_desc}\n\n" if t_desc else ""
            block = (
                f"### 任务{t.get('task_id')}（agent={t.get('agent', '')}）\n"
                f"{desc_part}"
                f"**结果：**\n{answer}"
            )
            blocks.append(block)
        text = (
            "\n\n---\n"
            "## 前序任务结果（来自上游编排，供当前任务执行参考）\n"
            + "\n\n".join(blocks)
            + "\n---\n"
        )
        return text, {}

    @staticmethod
    def _extract_structured_control_from_text(text: str) -> Dict[str, Any]:
        """Mirror ExpertAgent._extract_structured_control_from_text.

        SD Expert emits ``structured_control: {...}`` lines in its answer; the
        SG Orchestrator parses them here so it can read ``reason_code`` and
        ``unfulfilled_needs`` programmatically (rather than re-classifying via
        free-form regexes).
        """
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("structured_control:"):
                continue
            payload = stripped.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            if isinstance(data, dict):
                return data
        return {}

    def _collect_task_unfulfilled_needs(self, task: TaskStatus) -> List[Dict[str, Any]]:
        """Extract the SD Expert's ``unfulfilled_needs`` for a failed task.

        Returns a normalized list (may be empty).  Used by the replan path so
        the planner sees *which tables* the failing agent could not reach and
        can route them to a peer SG that owns them.
        """
        sc = self._extract_structured_control_from_text(str(task.answer or ""))
        if not isinstance(sc, dict):
            return []
        raw = sc.get("unfulfilled_needs") or []
        out: List[Dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            missing = str(item.get("missing_table") or "").strip()
            if not missing:
                continue
            out.append({
                "missing_table": missing,
                "reason": str(item.get("reason") or "").strip(),
                "intent_fragment": str(item.get("intent_fragment") or "").strip(),
                "stage": str(item.get("stage") or "").strip(),
            })
        return out

    def _classify_task_failure_reason(self, task: TaskStatus) -> str:
        """Classify failure reason into coarse-grained reason codes."""
        # LocalSkill reason codes are set directly via
        # ``_apply_local_skill_reason_code`` (no TaskOutcomeEval is produced for
        # synthetic LocalSkill runs). Preserve them so retry selection and the
        # replan context see the root cause instead of a heuristic re-label.
        existing = str(getattr(task, "failure_reason_code", "") or "").strip()
        if existing in LOCAL_SKILL_FAIL_REASONS:
            return existing
        text = f"{task.description}\n{task.answer}".lower()

        # Parse SD Expert's structured_control first — it is the authoritative
        # programmatic signal.  When it carries unfulfilled_needs we can re-route
        # via the sovereignty index instead of aborting.
        sc = self._extract_structured_control_from_text(str(task.answer or ""))
        sc_reason = str(sc.get("reason_code") or "").strip().lower()
        has_unfulfilled_needs = bool(sc.get("unfulfilled_needs"))

        if NON_RETRYABLE_REPEAT_MARKER.lower() in text or sc_reason == "repeated_failure_non_retryable":
            if has_unfulfilled_needs:
                logger.warning(
                    "[NonRetryablePropagation][SemanticGroup] task_id=%s marker=%s data_sovereignty_gap unfulfilled_needs=%d",
                    task.id,
                    NON_RETRYABLE_REPEAT_MARKER,
                    len(sc.get("unfulfilled_needs") or []),
                )
                return "data_sovereignty_gap"
            logger.warning(
                "[NonRetryablePropagation][SemanticGroup] task_id=%s marker=%s repeated_failure no actionable unfulfilled_needs",
                task.id,
                NON_RETRYABLE_REPEAT_MARKER,
            )
            return "non_retryable_misrouted_task"
        # Expert Agent 自身返回的 structured_control（reason_code=data_sovereignty_gap）。
        # 可能来自 Expert Agent 内部的 repeated_failure 检测（SQL 引用的表确实不在
        # 数据库中），携带 unfulfilled_needs 引导 retry loop 走
        # replan_with_decomposition → _resolve_sovereignty_hints → SovereigntyIndex → 重路由。
        if sc_reason == "data_sovereignty_gap":
            if has_unfulfilled_needs:
                logger.warning(
                    "[SovereigntyGap][Propagation] task_id=%s sc_reason=data_sovereignty_gap → unfulfilled_needs=%d",
                    task.id,
                    len(sc.get("unfulfilled_needs") or []),
                )
                return "data_sovereignty_gap"
            logger.info(
                "[SovereigntyGap][Propagation] task_id=%s sc_reason=data_sovereignty_gap no actionable unfulfilled_needs — 走通用分类",
                task.id,
            )
            # 没有 actionable unfulfilled_needs → 继续走下面 eval_result / heuristic 分类
        if NON_RETRYABLE_MARKER.lower() in text:
            logger.warning(
                "[NonRetryablePropagation][SemanticGroup] task_id=%s marker_detected=%s source=task_answer",
                task.id,
                NON_RETRYABLE_MARKER,
            )
            return "non_retryable_misrouted_task"

        eval_result = self._task_eval_results.get(task.id)
        if eval_result and eval_result.failure_reason_code:
            eval_code = str(eval_result.failure_reason_code or "").strip()
            eval_code_lower = eval_code.lower()
            # Normalize LLM-produced out-of-scope variants (e.g. OUT_OF_SCOPE_NO_RESULT)
            # to a unified non-retryable reason for cross-layer propagation.
            if "out_of_scope" in eval_code_lower:
                logger.warning(
                    "[NonRetryablePropagation][SemanticGroup] task_id=%s eval_reason_code=%s normalized=non_retryable_misrouted_task",
                    task.id,
                    eval_code,
                )
                return "non_retryable_misrouted_task"
            return eval_code
        if any(k in text for k in ("timeout", "timed out", "connection reset", "connection error", "temporarily unavailable", "502", "503", "504")):
            return "transient_network"
        if any(k in text for k in ("401", "403", "unauthorized", "forbidden", "permission denied")):
            return "auth_or_permission"
        # Generic cross-source / context-missing join issues.
        cross_markers = (
            "跨库", "跨域", "无法关联", "无法 join", "cannot join", "no such table", "table", "context",
            "schema", "missing", "不存在", "仅包含", "doesn't exist", "does not exist"
        )
        if ("join" in text or "关联" in text or "relation" in text) and any(k in text for k in cross_markers):
            return "cross_source_join_unavailable"
        if any(k in text for k in ("no such table", "doesn't exist", "does not exist", "unknown column", "schema")):
            return "missing_relation_in_context"
        if any(k in text for k in ("invalid", "bad request", "validation error")):
            return "invalid_request"
        return "unknown_failure"

    def _decide_retry_action(
        self,
        reason_code: str,
        retry_count: int,
        same_plan_retry_count: int,
    ) -> str:
        """Decide retry action for current failure reason."""
        if retry_count >= self.max_loop_count:
            return "abort"
        if reason_code in ("auth_or_permission", "invalid_request", "non_retryable_misrouted_task"):
            return "abort"
        if reason_code == "transient_network" and same_plan_retry_count < MAX_SAME_PLAN_RETRY:
            return "retry_same_plan"
        # data_sovereignty_gap: SD Expert reported ``unfulfilled_needs`` (e.g.
        # SQL_WHITELIST repeated failure with a known missing table).  The
        # sovereignty index will surface the peer SG that owns the table, so
        # decomposition replan is the right action — not abort.
        if reason_code in (
            "cross_source_join_unavailable",
            "missing_relation_in_context",
            "data_sovereignty_gap",
        ):
            return "replan_with_decomposition"
        # LocalSkill (route B) failures: allow the planner to redraft the plan.
        # The failed skill name is already captured in ``execution_results`` so
        # the LLM can naturally avoid LocalSkill or pick a different skill.
        if reason_code in LOCAL_SKILL_FAIL_REASONS:
            return "replan_standard"
        return "replan_standard"

    def _select_retry_reason_code(self, failed_tasks: List[TaskStatus]) -> str:
        if not failed_tasks:
            return "unknown_failure"
        reason_codes = [self._classify_task_failure_reason(t) for t in failed_tasks]
        priority = (
            "non_retryable_misrouted_task",
            "auth_or_permission",
            "invalid_request",
            "agent_not_found",
            "no_agent_available",
            # LocalSkill codes — ranked above generic failure codes so the
            # planner receives a LocalSkill-specific hint first.
            "local_skill_declined",
            "local_skill_max_steps",
            "local_skill_no_finish",
            "local_skill_no_selection",
            "local_skill_not_found",
            "local_skill_error",
        )
        for code in priority:
            if code in reason_codes:
                logger.info("[RetryAware] Selected prioritized reason_code=%s from=%s", code, reason_codes)
                return code
        return reason_codes[0] if reason_codes else "unknown_failure"

    def _build_replan_guidance(
        self,
        reason_code: str,
        *,
        sovereignty_hints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build strategy guidance text for replanning prompt.

        When ``sovereignty_hints`` is supplied (typical for
        ``data_sovereignty_gap``), the guidance embeds explicit "forbidden /
        recommended agents" instructions so the Planner cannot reuse the
        failing route and is steered to the peer SG that actually owns the
        missing tables.
        """
        hints_text = self._format_sovereignty_hints(sovereignty_hints)
        if reason_code == "data_sovereignty_gap":
            base = (
                "重试策略要求（数据归属重路由）：\n"
                "1) 上一轮失败任务的根因是 **数据归属不匹配**（agent 的 whitelist 不包含必要表）。\n"
                "2) 禁止再次将相同的 missing_table 路由到 forbidden_agents 列出的 agent。\n"
                "3) 必须依据 recommended_agents（来自 sovereignty index 反查）选择新的归属 agent。\n"
                "4) 若无单一 agent 同时覆盖所有 missing_table，按归属拆分为多个子任务并在 dependencies 中正确串联。\n"
                "5) 在 task.description 中显式声明所需读取的表名，便于 SD Expert 校验。"
            )
            return f"{base}{hints_text}" if hints_text else base
        if reason_code in ("cross_source_join_unavailable", "missing_relation_in_context"):
            base = (
                "重试策略要求（通用）：\n"
                "1) 不要在单一数据源中执行跨源 JOIN。\n"
                "2) 先在主数据源完成聚合并产出 join_key 列表（如 *_id）。\n"
                "3) 再在其它数据源按 join_key 列表查询补充属性。\n"
                "4) 最终由编排层按 join_key 进行结果合并，并标注缺失 key。\n"
                "5) 禁止复用上轮失败的 task-agent 方案，除非给出可验证修复。"
            )
            return f"{base}{hints_text}" if hints_text else base
        if reason_code == "transient_network":
            return "重试策略要求：优先保持原任务分解，仅微调以降低外部调用失败概率；禁止无关改动。"
        base = "重试策略要求：优先修复失败任务，逐条覆盖 missing_requirements，避免无关任务改动，并说明与上轮差异。"
        return f"{base}{hints_text}" if hints_text else base

    @staticmethod
    def _format_sovereignty_hints(hints: Optional[Dict[str, Any]]) -> str:
        if not hints or not isinstance(hints, dict):
            return ""
        forbidden = hints.get("forbidden_agents") or []
        recommended = hints.get("recommended_agents") or []
        unfulfilled = hints.get("unfulfilled_needs") or []
        if not forbidden and not recommended and not unfulfilled:
            return ""
        sections: List[str] = ["\n\n--- 数据归属提示（sovereignty index）---"]
        if unfulfilled:
            sections.append("unfulfilled_needs:")
            for item in unfulfilled[:20]:
                if not isinstance(item, dict):
                    continue
                missing = item.get("missing_table") or ""
                intent = item.get("intent_fragment") or ""
                stage = item.get("stage") or ""
                sections.append(f"  - missing_table={missing} | stage={stage} | intent={intent}")
        if forbidden:
            sections.append("forbidden_agents (上轮失败，禁止再次承担相同 missing_table):")
            for agent in forbidden[:20]:
                sections.append(f"  - {agent}")
        if recommended:
            sections.append("recommended_agents (sovereignty index 反查，按 missing_table 列出候选归属):")
            for entry in recommended[:30]:
                if isinstance(entry, dict):
                    sections.append(
                        f"  - missing_table={entry.get('missing_table', '')} -> {', '.join(entry.get('owners', []) or [])}"
                    )
        return "\n".join(sections)

    async def analyze_failure_reasons(self, tasks_status: List[TaskStatus]) -> str:
        failure_analysis = []
        
        for task in tasks_status:
            if task.status == "fail":
                reason_code = self._classify_task_failure_reason(task)
                eval_result = self._task_eval_results.get(task.id)
                eval_reason = (
                    task.failure_explanation
                    or ((eval_result.failure_explanation if eval_result else "") or "")
                )
                missing = (
                    task.missing_requirements
                    or ((eval_result.missing_requirements if eval_result else []) or [])
                )
                clean_answer = str(task.answer_final or self._sanitize_display_text(task.answer or ""))
                failure_analysis.append(
                    f"Task {task.id} ('{task.description}') assign to {task.agent} fail."
                    f" reason_code={reason_code}. eval_reason={eval_reason}. missing={missing[:5]}. "
                    f"Answer: {clean_answer[:500]}..."
                )
        
        return "\n".join(failure_analysis) if failure_analysis else "No failed tasks found"

    async def should_retry_planning(self, tasks_status: List[TaskStatus]) -> bool:
        """Determine if replanning is needed"""
        if not tasks_status:
            return False
        
        any_failed = any(task.status == "fail" for task in tasks_status)
        
        return any_failed

    # get knowledge from expert agents (tasks param is TaskList)
    async def a2a_tasks(self, query, initial_tasks, updater, task_name, think, stream=True) -> list[str]:
        # 只把「最后一轮」执行结果交给总结 LLM；每轮结尾用 current_agents_knowledge 覆盖，不累积历轮
        last_round_knowledge: list[str] = []
        base_query = self._strip_replan_context_block(query)

        if initial_tasks is None or not hasattr(initial_tasks, 'tasks') or not initial_tasks.tasks:
            logger.info("Warning: initial tasks is invalid")
            return last_round_knowledge

        retry_count = 0
        same_plan_retry_count = 0
        execution_rounds = 0
        retry_decisions = 0
        current_tasks = initial_tasks
        
        while retry_count <= self.max_loop_count:
            execution_rounds += 1
            logger.info(f"=== Start executing plan, retry count: {retry_count}/{self.max_loop_count} ===")
            await self.emit_progress(
                updater,
                task_name,
                event="group_execution_round_started",
                message=f"Execution round {execution_rounds} started (retry {retry_count}/{self.max_loop_count})",
                status="running",
                extra={"round": execution_rounds, "retry_count": retry_count, "max_retries": self.max_loop_count},
            )
            
            self.tasks_status = []
            self._task_eval_results = {}
            for task in current_tasks.tasks:
                task_status = TaskStatus(
                    id=task.id,
                    description=task.description,
                    agent=task.agent,
                    answer="",
                    status="not_started"
                )
                self.tasks_status.append(task_status)

            current_agents_knowledge = []
            for task in current_tasks.tasks:
                self._update_task_status(task.id, "start", "")
                logger.info(f"Task {task.id}: {task.description} -> [{task.agent}]")
                task_desc_preview = self._truncate_progress_message(task.description or "", 220)

                # Route B: planner routed this task to the local skill executor.
                if self._is_local_skill_task(task):
                    await self._run_local_skill_task(
                        task,
                        updater=updater,
                        task_name=task_name,
                        think=think,
                        current_agents_knowledge=current_agents_knowledge,
                        retry_count=retry_count,
                        task_desc_preview=task_desc_preview,
                    )
                    continue

                # When planner returned agent=NONE (no relevant agent), use fixed description and skip A2A
                if (task.agent or "").strip().upper() == "NONE":
                    # Optional fallback: try LocalSkill once before giving up.
                    if self._has_local_skill() and LOCAL_SKILL_FALLBACK_ON_NONE:
                        handled = await self._try_local_skill_fallback_for_none(
                            task,
                            updater=updater,
                            task_name=task_name,
                            think=think,
                            current_agents_knowledge=current_agents_knowledge,
                            retry_count=retry_count,
                            task_desc_preview=task_desc_preview,
                        )
                        if handled:
                            continue

                    none_description = NONE_TASK_DESCRIPTION
                    logger.info("Task %s: agent=NONE (no relevant agent)", task.id)
                    self._update_task_status(task.id, "complete", none_description)
                    current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, "", none_description, "complete"))
                    none_progress_msg = (
                        f"Task [{task.id}]: {none_description.strip()} - [NONE]"
                    )
                    await self.emit_progress(
                        updater,
                        task_name,
                        event="task_no_agent_available",
                        message=self._truncate_progress_message(none_progress_msg, 640),
                        status="done",
                        task_id=task.id,
                        extra={
                            "reason_code": "planner_assigned_none",
                            "task_description": task_desc_preview,
                            "task_agent": "NONE",
                        },
                    )
                    await self.emit_progress(
                        updater,
                        task_name,
                        event="task_finished",
                        message=(
                            f"task {task.id} skipped: no relevant child agent found"
                        ),
                        status="done",
                        task_id=task.id,
                        extra={"task_agent": "NONE", "task_status": "skipped_no_agent"},
                    )
                    if self.debug == 1:
                        think.append(none_description)
                    continue

                current_tasks_status_json = json.dumps([task_status.model_dump() for task_status in self.tasks_status])
                task_query = task.description
                metadata_prior = (self.metadata or {}).get("prior_task_results") or []
                p0 = self._normalize_prior_task_results(metadata_prior)
                p1 = self._collect_local_prior_task_results(task.id)
                merged_prior_task_results = self._merge_prior_task_results(p0, p1)
                if merged_prior_task_results:
                    logger.info(
                        "[RetryAware] Task %s prior_task_results via metadata | merged_count=%d",
                        task.id,
                        len(merged_prior_task_results),
                    )

                agent_steps_raw: List[str] = []
                summary_text: Optional[str] = None

                if self.debug == 1:
                    agent_knowledge_step = f"Task [{task.id}]: {task.description}; \n\n"
                    think.append(agent_knowledge_step)

                if stream:
                    try:
                        async for agent_step_knowledge in self.a2a_stream(
                            task.id,
                            task_query,
                            task.agent,
                            current_tasks_status_json,
                            merged_prior_task_results,
                        ):
                            if self.is_progress_frame(agent_step_knowledge):
                                await updater.add_artifact(
                                    [TextPart(text=agent_step_knowledge)],
                                    name=task_name,
                                )
                                continue
                            if self.is_summary_artifact(agent_step_knowledge):
                                parsed = self.parse_summary_artifact(agent_step_knowledge)
                                if parsed is not None:
                                    summary_text = parsed
                                    logger.info(
                                        "[DACSummary][SG-Orch] received summary from agent=%s task=%s (%d chars)",
                                        task.agent,
                                        task.id,
                                        len(parsed),
                                    )
                                continue
                            if self.debug == 1:
                                agent_knowledge_step = f"{agent_step_knowledge} \n"
                                think.append(agent_knowledge_step)
                            agent_steps_raw.append(agent_step_knowledge)

                        agent_steps_knowledge_str = self._finalize_a2a_collected_text(
                            agent_steps_raw,
                            summary_text,
                        )
                        if summary_text is not None:
                            logger.info(
                                "[DACSummary][SG-Orch] using summary for task=%s agent=%s, discarded %d raw chunks",
                                task.id,
                                task.agent,
                                len(agent_steps_raw),
                            )

                        eval_result = await self._llm_evaluate_task_outcome(
                            original_query=base_query,
                            task=task,
                            agent_answer_raw=agent_steps_knowledge_str,
                            plan_context=[{"id": t.id, "description": t.description, "agent": t.agent} for t in current_tasks.tasks],
                            prior_task_results=merged_prior_task_results,
                        )
                        self._task_eval_results[task.id] = eval_result
                        current_task_status = eval_result.status
                        self._update_task_status(task.id, current_task_status, agent_steps_knowledge_str, eval_result)
                        if agent_steps_knowledge_str:
                            await self.emit_progress(
                                updater,
                                task_name,
                                event="task_answer",
                                message=(
                                    f"task {task.id} answer:\n{agent_steps_knowledge_str}"
                                ),
                                status="running",
                                task_id=task.id,
                                extra={"task_agent": task.agent},
                            )
                        logger.info(f"Task {task.id} completion status: {current_task_status}")
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="task_finished",
                            message=(
                                f"task {task.id} finished with status={current_task_status}"
                            ),
                            status="done" if current_task_status != "fail" else "fail",
                            task_id=task.id,
                            extra={"task_agent": task.agent, "task_status": current_task_status},
                        )
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_steps_knowledge_str, current_task_status))
                        if current_task_status == "fail":
                            break

                    except Exception as e:
                        logger.error(f"Error occurred while executing Task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="task_error",
                            message=f"Task {task.id} failed: {str(e)}",
                            status="fail",
                            task_id=task.id,
                        )
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}", "fail"))

                else:
                    try:
                        agent_result = await self.a2a_non_stream(
                            task_query,
                            task.agent,
                            merged_prior_task_results,
                        )
                        agent_knowledge_step = f"Task [{task.id}]: {task.description}; \nResult:\n {agent_result} \n"

                        eval_result = await self._llm_evaluate_task_outcome(
                            original_query=base_query,
                            task=task,
                            agent_answer_raw=agent_result or "",
                            plan_context=[{"id": t.id, "description": t.description, "agent": t.agent} for t in current_tasks.tasks],
                            prior_task_results=merged_prior_task_results,
                        )
                        self._task_eval_results[task.id] = eval_result
                        current_task_status = eval_result.status
                        self._update_task_status(task.id, current_task_status, agent_result, eval_result)
                        if agent_result:
                            await self.emit_progress(
                                updater,
                                task_name,
                                event="task_answer",
                                message=(
                                    f"task {task.id} answer:\n{agent_result}"
                                ),
                                status="running",
                                task_id=task.id,
                                extra={"task_agent": task.agent},
                            )
                        
                        if self.debug == 1:
                            think.append(agent_knowledge_step)
                        
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_result or "", current_task_status))
                        
                    except Exception as e:
                        logger.error(f"Error during non-streaming execution of task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}", "fail"))

            # 用本轮结果覆盖，保证交给总结 LLM 的始终是「最后一轮」
            last_round_knowledge = list(current_agents_knowledge)
            
            if await self.should_retry_planning(self.tasks_status):
                retry_decisions += 1
                failure_tasks = [t for t in self.tasks_status if t.status == "fail"]
                reason_code = self._select_retry_reason_code(failure_tasks)
                retry_action = self._decide_retry_action(reason_code, retry_count, same_plan_retry_count) if ENABLE_REASON_AWARE_RETRY else "replan_standard"
                self._last_retry_reason_code = reason_code
                self._last_retry_action = retry_action
                retry_count += 1
                if retry_count <= self.max_loop_count:
                    logger.info(
                        "=== Plan execution failed, preparing for retry attempt %d/%d | reason_code=%s | chosen_action=%s | execution_rounds=%d | retry_decisions=%d ===",
                        retry_count, self.max_loop_count, reason_code, retry_action, execution_rounds, retry_decisions
                    )
                    
                    failure_analysis = await self.analyze_failure_reasons(self.tasks_status)
                    logger.info(f"Failure analysis:\n{failure_analysis}")
                    
                    if self.debug == 1:
                        retry_msg = f"\n=== 计划执行遇到问题，正在进行第 {retry_count} 次重试 ===\n失败分析:\n{failure_analysis}\n"
                        # retry_msg = f"\n=== Plan execution encountered issues, performing retry attempt {retry_count} ===\nFailure analysis:\n{failure_analysis}\n"
                        think.append(retry_msg)

                    if retry_action == "abort":
                        if reason_code == "non_retryable_misrouted_task":
                            abort_notice = (
                                f"{NON_RETRYABLE_MARKER} | retry aborted in semantic-group orchestrator | "
                                f"reason_code={reason_code}"
                            )
                            last_round_knowledge.append(abort_notice)
                            logger.warning(
                                "[NonRetryablePropagation][SemanticGroup] marker_forwarded_upstream=%s retry_count=%d failed_tasks=%d",
                                NON_RETRYABLE_MARKER,
                                retry_count,
                                len(failure_tasks),
                            )
                        logger.warning(
                            "[RetryAware] Abort retry due to non-retryable reason_code=%s",
                            reason_code,
                        )
                        break

                    if retry_action == "retry_same_plan":
                        same_plan_retry_count += 1
                        logger.info(
                            "[RetryAware] Retrying same plan | attempt=%d | reason_code=%s",
                            same_plan_retry_count,
                            reason_code,
                        )
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="group_retry_same_plan",
                            message=f"Retrying current semantic-group plan, reason={reason_code}",
                            status="running",
                            extra={"retry_count": retry_count, "reason_code": reason_code},
                        )
                        await asyncio.sleep(self.loop_retry_delay)
                        continue

                    same_plan_retry_count = 0
                    replan_context = self._build_replan_context(
                        original_query=base_query,
                        current_tasks=current_tasks,
                        retry_count=retry_count,
                        reason_code=reason_code,
                        retry_action=retry_action,
                        failure_analysis=failure_analysis,
                    )
                    # P7: when the failure includes structured unfulfilled_needs,
                    # consult the sovereignty index to mark the failing agent as
                    # forbidden and recommend peer SGs that actually own the
                    # missing tables.  These hints are surfaced both in the
                    # context payload and inlined into the guidance prompt.
                    sovereignty_hints: Dict[str, Any] = {}
                    try:
                        sovereignty_hints = await self._resolve_sovereignty_hints(replan_context)
                    except Exception:  # noqa: BLE001
                        logger.exception("[ReplanHints] sovereignty hint resolution raised — continuing")
                    if sovereignty_hints:
                        replan_context["sovereignty_hints"] = sovereignty_hints
                        logger.info(
                            "[ReplanHints] sovereignty hints applied to replan_context: forbidden=%d recommended=%d",
                            len(sovereignty_hints.get("forbidden_agents") or []),
                            len(sovereignty_hints.get("recommended_agents") or []),
                        )
                    guidance = self._build_replan_guidance(
                        reason_code,
                        sovereignty_hints=sovereignty_hints or None,
                    )
                    if isinstance(self.metadata, dict):
                        self.metadata["replan_context"] = replan_context
                    replan_context_text = json.dumps(replan_context, ensure_ascii=False)
                    logger.info(
                        "[RetryAware][ReplanInput] base_query_chars=%d replan_context_chars=%d planner_query_chars=%d replan_marker_count=%d",
                        len(base_query),
                        len(replan_context_text),
                        len(base_query),
                        self._count_replan_context_markers(base_query),
                    )
                    new_tasks = await self.get_plan(
                        base_query,
                        replan_context=replan_context,
                        replan_guidance=guidance,
                    )

                    if new_tasks is None or not hasattr(new_tasks, 'tasks') or not new_tasks.tasks:
                        logger.error("Re-planning failed, unable to obtain a valid plan")
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="group_replan_failed",
                            message="Semantic-group replanning failed",
                            status="fail",
                            extra={"retry_count": retry_count},
                        )
                        
                        if self.debug == 1:
                            plan_fail_msg = f"\n⚠️ 重新规划失败，已达到最大重试次数 {self.max_loop_count}\n"
                            # plan_fail_msg = f"\n⚠️ Re-planning failed, maximum retry count {self.max_loop_count} reached\n"
                            think.append(plan_fail_msg)
                        break
                    else:
                        current_tasks = new_tasks
                        logger.info(f"Re-planning successful, obtained {len(current_tasks.tasks)} new tasks")
                        plan_msg, plan_extra = self.build_group_plan_ready_progress(
                            task_list=current_tasks,
                            user_query=base_query,
                            replan=True,
                            retry_count=retry_count,
                        )
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="group_plan_ready",
                            message=plan_msg,
                            status="done",
                            extra=plan_extra,
                        )

                        if self.debug == 1:
                            new_plan_msg = f"\n=== 第 {retry_count} 次重新规划成功，新计划如下 ===\n"
                            # new_plan_msg = f"\n=== Retry attempt {retry_count} re-planning successful, new plan as follows ===\n"
                            participant_chain = (self.metadata or {}).get("participant_chain")
                            new_plan_msg += tasklist_to_string(current_tasks, participant_chain=participant_chain)
                            think.append(new_plan_msg)

                        await asyncio.sleep(self.loop_retry_delay)

                        continue
                else:
                    logger.info(f"Reached maximum retry count {self.max_loop_count}, stopping retries")
                    
                    if self.debug == 1:
                        max_retry_msg = f"\n⚠️ 已达到最大重试次数 {self.max_loop_count}，停止重试\n"
                        # max_retry_msg = f"\n⚠️ Maximum retry count {self.max_loop_count} reached, stopping retries\n"
                        think.append(max_retry_msg)
                    break
            else:
                logger.info("All tasks completed successfully")
                await self.emit_progress(
                    updater,
                    task_name,
                    event="group_tasks_completed",
                    message="All subtasks completed, preparing final aggregation context",
                    status="done",
                    extra={"task_count": len(current_tasks.tasks)},
                )
                if self.debug == 1:
                    success_msg = f"\n✅ 所有任务执行成功完成\n"
                    # success_msg = f"\n✅ All tasks executed successfully\n"
                    think.append(success_msg)
                break
                
        logger.info(
            "Task execution completed | execution_rounds=%d retry_decisions=%d max_loops=%d knowledge_items=%d",
            execution_rounds,
            retry_decisions,
            self.max_loop_count,
            len(last_round_knowledge),
        )
        return last_round_knowledge

    def schedule_add_memory(self, query, final_answer) -> None:
        """Fire-and-forget wrapper for ``add_memory``.

        Memory writes are best-effort observability — if the upstream
        mem0/data-services pipeline is slow or down we must never block
        (or worse, break) the orchestrator stream back to the user. Wrap
        the coroutine in a background task that swallows any exception
        and logs it, and keep a reference so the event loop does not GC
        the task mid-flight.
        """
        async def _runner() -> None:
            try:
                await self.add_memory(query, final_answer)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[MemoryOp][SG] schedule_add_memory failed — ignoring "
                    "(run_id=%s)",
                    (self.metadata or {}).get('run_id', ''),
                )

        try:
            tracker = self.__dict__.setdefault("_background_memory_tasks", set())
            task = asyncio.create_task(_runner())
            tracker.add(task)
            task.add_done_callback(tracker.discard)
        except RuntimeError:
            # No running event loop (e.g. sync test harness). Fall back to
            # "best-effort inline" but still guard the exception so the
            # caller flow is unaffected.
            logger.warning(
                "[MemoryOp][SG] schedule_add_memory: no running loop — "
                "falling back to inline execution"
            )

            async def _inline() -> None:
                try:
                    await self.add_memory(query, final_answer)
                except Exception:  # noqa: BLE001
                    logger.exception("[MemoryOp][SG] inline add_memory failed")

            try:
                asyncio.get_event_loop().run_until_complete(_inline())
            except Exception:  # noqa: BLE001
                logger.exception("[MemoryOp][SG] inline fallback also failed")

    async def add_memory(self, query, final_answer):
        final_answer_str = "".join(final_answer)
        memory_owner = self._get_sg_memory_owner()
        logger.info(
            "[MemoryOp][SG] ADD_MEMORY | user_id=%s memory_owner=%s run_id=%s query_preview=%s",
            self.metadata.get('user_id', ''),
            memory_owner,
            self.metadata.get('run_id', ''),
            (query or "")[:80],
        )
        logger.debug(f"add_memory metadata : user_id: {self.metadata.get('user_id', '')}, memory_owner:{memory_owner}, run_id:{self.metadata.get('run_id', '')}")
        
        async with self.data_services_client.session_context() as client:
            memory_response = await client.store_memory(
                user_id=self.metadata.get('user_id', ''),
                agent_id=memory_owner,
                run_id=self.metadata.get('run_id', ''),
                messages=[
                    {
                        "role": "user",
                        "content": query
                    },
                    {
                        "role": "assistant", 
                        "content": final_answer_str
                    }
                ]
            )

        _status = getattr(memory_response, 'status', None) or (memory_response.get('status') if isinstance(memory_response, dict) else 'N/A')
        logger.info(
            "[MemoryOp][SG] ADD_MEMORY done | memory_owner=%s run_id=%s status=%s",
            memory_owner,
            self.metadata.get('run_id', ''),
            _status,
        )
        logger.debug(f"add_memory, query= {query}, final_answer={final_answer_str}, response : {memory_response}")
        return memory_response

    async def get_memory(self, query) -> str:
        memory_owner = self._get_sg_memory_owner()
        logger.info(
            "[MemoryOp][SG] GET_MEMORY | user_id=%s memory_owner=%s run_id=%s query_preview=%s",
            self.metadata.get('user_id', ''),
            memory_owner,
            self.metadata.get('run_id', ''),
            (query or "")[:80],
        )
        logger.debug(f"get_memory metadata :query:{query}, user_id: {self.metadata.get('user_id', '')}, memory_owner:{memory_owner}, run_id:{self.metadata.get('run_id', '')}")
        
        search_items = []

        async with self.data_services_client.session_context() as client:
            memory_search_response = await client.search_memories(
                query=query,
                user_id=self.metadata.get('user_id', ''),
                agent_id=memory_owner,
                run_id=self.metadata.get('run_id', ''),
                limit=10
            )

        if memory_search_response.status == "success":
            search_items = self.data_services_client.parse_memory_search_results(memory_search_response)    
        else:
            if memory_search_response.detail:
                logger.error(f"get_memory error msg: {memory_search_response.detail}")

        memory_texts = [item.memory for item in search_items if item.memory]
        memory_texts_str = "\n".join(memory_texts)
        logger.info(
            "[MemoryOp][SG] GET_MEMORY done | memory_owner=%s run_id=%s found_count=%d memory_chars=%d hit=%s",
            memory_owner,
            self.metadata.get('run_id', ''),
            len(search_items),
            len(memory_texts_str),
            "yes" if memory_texts_str.strip() else "no",
        )
        logger.debug(f"get_memory response : {search_items}")

        return memory_texts_str

    async def add_history(self, query, final_answer, knowledge):
        final_answer_str = "".join(final_answer)
        logger.info(f"add_history metadata : user_id: {self.metadata.get('user_id', '')}, agent_id:{self.metadata.get('agent_id', '')}, run_id:{self.metadata.get('run_id', '')}")
        
        create_request = CreateHistoryRequest(
                user_id=self.metadata.get('user_id', ''),
                agent_id=self.agent_id,
                run_id=self.metadata.get('run_id', ''),
                messages=[
                    HistoryMessage(role="user", content=query),
                    HistoryMessage(role="assistant", content=final_answer_str, think=knowledge or None)
                ]
            )
        async with self.data_services_client.session_context() as client:
            history_response = await client.create_history(create_request)

        logger.debug(f"add_history, query length={len(query)}, final_answer length={len(final_answer_str)}, response : {history_response}")
        return history_response

    async def get_history(self) -> list:
        """
        return:

        [
            HumanMessage(content="Hello"),
            AIMessage(content="Hello! How can I help you? "),
            HumanMessage(content="What's the weather like today?  "), 
            AIMessage(content="Please provide your location information.")
        ]
        """

        logger.debug(f"OrchestratorAgent get_history metadata: user_id: {self.metadata.get('user_id', '')}, agent_id:{self.metadata.get('agent_id', '')}, run_id:{self.metadata.get('run_id', '')}")
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        if normalize_history_turns(propagated.get("turns")):
            return history_messages_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
                user_id=self.metadata.get('user_id', ''),
                run_id=self.metadata.get('run_id', ''),
                limit=get_conversation_history_limit()
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"OrchestratorAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"OrchestratorAgent get_history response : {search_items}")
        return history_messages_from_payload(
            history_payload_from_search_items(search_items, source="sg_summary_fallback")
        )

    async def stream(self, query, task_knowledges, think) -> AsyncIterable[dict[str, Any]]:
        # SG Orchestrator is the business-level summarizer for a root path.
        # It separates downstream task knowledge/context from the final user-facing answer.

        # Retrieve memories related to the question
        # memory = await self.get_memory(query)

        final_answer = []

        knowledge = ""

        _knowledge_sep = "\n\n================\n\n"
        if task_knowledges and all(isinstance(item, list) for item in task_knowledges):
            flat_knowledges = []
            for task_knowledge in task_knowledges:
                flat_knowledges.extend(task_knowledge)
            knowledge = _knowledge_sep.join(flat_knowledges)
        else:
            knowledge = _knowledge_sep.join(task_knowledges) if task_knowledges else ""

        knowledge_for_display = self._sanitize_display_text(knowledge)

        system_template = Orchestrator_INSTRUCTIONS_ZH

        # human_template = "background knowledge: {knowledge}。\n\n history memory: {memory}\n\nuser question:{query}"
        human_template = (
            "background knowledge: {knowledge}。\n\n"
            "user question:{query}\n\n"
            "【重要提示】background knowledge 中每个任务块都标注了「任务状态」。"
            "状态为「fail」的任务，其返回的数据可能是局部/不完整/不正确的，"
            "严禁将其中的具体数据（如查询到的记录、数字、字段值）当作事实引用。"
            "状态为「fail」的任务数据仅能说明「该任务未成功完成」，不能证明任何事实性结论。"
        )

        logger.info(
            "============ biz orchestrator stream, answer user question, knowledge length: %s, knowledge (full):\n%s",
            len(knowledge),
            knowledge,
        )

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = None
        if self.enable_history == "enable":
            # Retrieve history related to the runid
            history_messages = await self.get_history()
            chat_prompt = ChatPromptTemplate.from_messages([system_prompt, *history_messages, human_prompt])
        else:
            chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get('user_id', '')
        run_id = self.metadata.get('run_id', '')
        trace_id = self.metadata.get('trace_id', '')

        answer = None

        chain = chat_prompt | self.llm

        with langfuse.start_as_current_span(
            name="biz-orchestrator-stream",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            
            # for chunk in chain.stream({"query": query, "knowledge": knowledge_for_display, "memory": memory}, config={"callbacks": [langfuse_handler]}):
            for chunk in chain.stream({"query": query, "knowledge": knowledge_for_display}, config={"callbacks": [langfuse_handler]}):
                if hasattr(chunk, 'content') and chunk.content:
                    final_answer.append(chunk.content)
                    yield {'content': chunk.content, 'is_task_complete': False}

            span.update_trace(output={"answer": "".join(final_answer)})

        langfuse.flush()

        yield {'content': '', 'is_task_complete': True}

        # add history
        if self.enable_history == "enable":
            owner_agent_id = (self.metadata or {}).get("history_owner_agent_id")
            is_not_owner = bool(owner_agent_id) and owner_agent_id != self.agent_id
            if (self.metadata or {}).get("skip_history_write") or is_not_owner:
                skip_reason = "skip_history_write" if (self.metadata or {}).get("skip_history_write") else "not_owner"
                logger.info(
                    "[HistoryFlow] orchestrator-history-skip reason=%s skip_history_write=%s owner=%s self=%s run_id=%s",
                    skip_reason,
                    (self.metadata or {}).get("skip_history_write"),
                    owner_agent_id,
                    self.agent_id,
                    (self.metadata or {}).get("run_id", ""),
                )
            else:
                think_str = "".join(think)
                await self.add_history(query, final_answer, think_str)

        # add memory — fire-and-forget so a slow/failing upstream never
        # blocks the stream close or surfaces an exception to the caller.
        self.schedule_add_memory(query, final_answer)


class OrchestratorAgentExecutorSemanticGroup(AgentExecutor):
    """
    A Orchestrator Agent executor call PlannerAgent to get agents, than call agents.
    Also handles capability check requests from the routing agent (broadcast mode).
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        semantic_group_id:str = None,
        debug: int = 0,
        data_services_url: str = None,
        enable_history: str = None,
        agent_id: str = None,
        max_loops: int = 2,
        agent_card: AgentCard = None
    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.semantic_group_id=semantic_group_id
        self.debug = debug
        self.data_services_url=data_services_url
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.max_loops = max_loops
        self.agent_card = agent_card
        self.metadata: Dict[str, Any] = {}
        self._progress_context: Dict[str, str] = {"run_id": "", "user_id": "", "agent_id": ""}
        self.manager = ModelManager()
        _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        # Non-streaming LLM instance for tool-call based invocations.
        self.llm_non_stream = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=False,
            extra_body=_extra_body,
        )
        # LocalSkill (route B) — a process-wide SkillRunner shared across all
        # requests. Lazily initialised on first request so startup stays fast
        # even when skill loading would be expensive. Disabled when
        # ``ENABLE_LOCAL_SKILLS`` is false or ``skill_sdk`` is not installed.
        self._skill_runner: "SkillRunner | None" = None
        self._skill_runner_initialised = False
        self._skill_runner_lock = asyncio.Lock()
        self._log_local_skill_executor_config()

    @staticmethod
    def _execution_hint_ttl_sec() -> float:
        try:
            return max(
                1.0,
                float(os.getenv("SG_EXECUTION_HINT_TTL_SECONDS", "300")),
            )
        except ValueError:
            return 300.0

    @staticmethod
    def _execution_query_fingerprint(query: str) -> str:
        normalized = re.sub(r"\s+", " ", str(query or "").strip()).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _build_execution_hint(
        self,
        *,
        run_id: str,
        query: str,
        check_response: "CapabilityCheckResponse",
    ) -> Dict[str, Any]:
        """Build SG-owned evidence that Routing can transparently round-trip."""
        member_roles = dict(
            getattr(check_response, "collaboration_roles", None) or {}
        )
        selected_members = [
            str(name).strip()
            for name in (getattr(check_response, "collaboration_agents", None) or [])
            if str(name).strip()
        ]
        member_evidence: List[Dict[str, Any]] = []
        for result in list(getattr(check_response, "member_results", None) or [])[:30]:
            if not isinstance(result, dict):
                continue
            agent_name = str(result.get("agent_name") or "").strip()
            if not agent_name:
                continue
            role = str(
                member_roles.get(agent_name)
                or (
                    "handle"
                    if result.get("can_handle")
                    else "contribute"
                    if result.get("can_contribute")
                    else "unsupported"
                )
            ).strip()
            matched = []
            for key in (
                "matched_evidence",
                "matched_entities",
                "matched_tables",
                "matched_metrics",
            ):
                for item in result.get(key) or []:
                    text = str(item).strip()
                    if text and text not in matched:
                        matched.append(text)
                    if len(matched) >= 8:
                        break
                if len(matched) >= 8:
                    break
            member_evidence.append(
                {
                    "agent_name": agent_name,
                    "role": role,
                    "confidence": float(result.get("confidence", 0.0) or 0.0),
                    "reason": str(result.get("reason") or "")[:240],
                    "matched_evidence": matched,
                }
            )
        return {
            "version": "v1",
            "semantic_group_id": str(self.semantic_group_id or ""),
            "agent_name": self.current_agent_label(),
            "run_id": str(run_id or ""),
            "query_fingerprint": self._execution_query_fingerprint(query),
            "created_at_epoch": int(_time.time()),
            "ttl_seconds": int(self._execution_hint_ttl_sec()),
            "can_handle": bool(getattr(check_response, "can_handle", False)),
            "can_contribute": bool(getattr(check_response, "can_contribute", False)),
            "confidence": float(getattr(check_response, "confidence", 0.0) or 0.0),
            "degraded": bool(getattr(check_response, "degraded", False)),
            "missing_requirements": list(
                getattr(check_response, "missing_requirements", None) or []
            )[:20],
            "execution_strategy": str(
                getattr(check_response, "execution_strategy", None) or "single"
            ),
            "selected_members": selected_members,
            "member_roles": member_roles,
            "member_evidence": member_evidence,
            "reason": str(getattr(check_response, "reason", "") or "")[:500],
        }

    def _validated_execution_hint(
        self,
        metadata: Dict[str, Any],
        query: str,
    ) -> Optional[Dict[str, Any]]:
        """Validate the SG-issued hint delivered with the execution request."""
        hint = metadata.get(SG_EXECUTION_HINT_KEY)
        if not isinstance(hint, dict):
            return None
        if hint.get("version") != "v1":
            logger.warning("[Capability][ExecutionHint] rejected: unsupported version")
            return None
        if str(hint.get("semantic_group_id") or "") != str(self.semantic_group_id or ""):
            logger.warning("[Capability][ExecutionHint] rejected: semantic_group_id mismatch")
            return None
        request_run_id = str(metadata.get("run_id") or "")
        if str(hint.get("run_id") or "") != request_run_id:
            logger.warning("[Capability][ExecutionHint] rejected: run_id mismatch")
            return None
        expected_fingerprint = self._execution_query_fingerprint(query)
        if str(hint.get("query_fingerprint") or "") != expected_fingerprint:
            logger.warning("[Capability][ExecutionHint] rejected: query fingerprint mismatch")
            return None
        try:
            created_at = float(hint.get("created_at_epoch", 0) or 0)
            ttl = min(
                max(1.0, float(hint.get("ttl_seconds", 300) or 300)),
                self._execution_hint_ttl_sec(),
            )
        except (TypeError, ValueError):
            logger.warning("[Capability][ExecutionHint] rejected: invalid timestamp/ttl")
            return None
        age = _time.time() - created_at
        if age > ttl:
            logger.info(
                "[Capability][ExecutionHint] rejected: expired | age_sec=%.1f ttl_sec=%.0f",
                age,
                ttl,
            )
            return None
        if not hint.get("can_handle") or hint.get("degraded"):
            logger.info(
                "[Capability][ExecutionHint] ignored: can_handle=%s degraded=%s",
                hint.get("can_handle"),
                hint.get("degraded"),
            )
            return None
        missing = [
            str(item).strip()
            for item in (hint.get("missing_requirements") or [])
            if str(item).strip()
        ]
        if missing:
            logger.info(
                "[Capability][ExecutionHint] ignored: missing_requirements=%s",
                missing[:8],
            )
            return None
        selected = [
            str(name).strip()
            for name in (hint.get("selected_members") or [])
            if str(name).strip()
        ]
        if not selected:
            logger.warning("[Capability][ExecutionHint] rejected: selected_members empty")
            return None
        logger.info(
            "[Capability][ExecutionHint] accepted | run_id=%s strategy=%s "
            "selected=%s confidence=%.2f age_sec=%.1f",
            request_run_id,
            hint.get("execution_strategy") or "single",
            selected[:10],
            float(hint.get("confidence") or 0.0),
            age,
        )
        return hint

    @staticmethod
    def _pick_own_expert_name(own_names: set[str], preferred: str = "") -> str:
        preferred = str(preferred or "").strip()
        if preferred and preferred in own_names and preferred != "LocalSkill":
            return preferred
        candidates = sorted(
            name for name in own_names if name and name != "LocalSkill"
        )
        return candidates[0] if candidates else ""

    def _build_authoritative_execution_plan(
        self,
        *,
        query: str,
        own_names: set[str],
        preferred_own_agent: str,
        execution_hint: Optional[Dict[str, Any]],
    ) -> Optional["TaskList"]:
        """Create the primary own-Expert task from validated member evidence.

        ``missing_requirements`` must NOT block authoritative dispatch: capability
        already established can_handle for the primary ask; out-of-domain slices
        are expected to surface as partial results / mid-exec delegation.
        """
        if not execution_hint or not execution_hint.get("can_handle"):
            return None
        if execution_hint.get("degraded"):
            return None
        own_expert = self._pick_own_expert_name(own_names, preferred_own_agent)
        if not own_expert:
            return None
        return TaskList(
            thought_process=(
                "Reusing validated SG member capability evidence; dispatching "
                "the original query to this SG's Expert."
            ),
            original_query=query,
            tasks=[
                PlannerTask(
                    id=1,
                    description=query,
                    agent=own_expert,
                    depends_on=[],
                )
            ],
        )

    def _execution_hint_memory_note(self, plan: Dict[str, Any]) -> str:
        selected = [
            str(name).strip()
            for name in (plan.get("selected_members") or [])
            if str(name).strip()
        ]
        reason = str(plan.get("reason") or "").strip()
        lines = [
            "[MemberCapabilityEvidence]",
            "A prior member capability check for this run already confirmed that "
            "this Semantic Group can handle the user query via its member data agents.",
            f"can_handle={bool(plan.get('can_handle'))} "
            f"confidence={float(plan.get('confidence') or 0.0):.2f} "
            f"strategy={plan.get('execution_strategy') or 'single'}",
        ]
        if selected:
            lines.append("selected_members=" + ", ".join(selected[:10]))
        if reason:
            lines.append("reason=" + reason[:300])
        lines.append(
            "Therefore prefer this SG's own Expert Agent for execution; "
            "do not return agent=NONE solely because the SG summary card is generic."
        )
        return "\n".join(lines)

    # ─────────────────────── Data-Flow Logging Helper ───────────────────────

    @staticmethod
    def _log_data_flow(
        *,
        direction: str,
        description: str,
        source_id: str = "",
        target_id: str = "",
        payload_chars: int = 0,
        payload_preview: str = "",
        metadata_extra: dict[str, Any] | None = None,
    ) -> None:
        """Structured, visually scannable data-flow log for every agent-agent handoff.

        Example output for a ``direction="OWN_TASK_EXEC"`` call::

            ┌▶ DATA_FLOW  OWN_TASK_EXEC ───────────────────────────┐
            │  来源: UserCenterAgent-sg-xxx
            │  目标: UserCenterAgent-sg-xxx (expert on localhost:10101)
            │  载荷: 2,054 chars
            │  前置上下文: Task#1 (2,054 chars)
            ├───────────────────────────────────────────────────────┤
            │  预览: step 1/1: query: 查询所有用户的信息…
            └───────────────────────────────────────────────────────┘
        """
        block_width = 80

        lines: list[str] = []
        lines.append(f"┌▶ DATA_FLOW  {direction}")
        lines.append("─" * (block_width + 1) + "┐")
        lines.append(f"│  {description}")
        if source_id:
            lines.append(f"│  来源: {source_id}")
        if target_id:
            lines.append(f"│  目标: {target_id}")
        if payload_chars:
            lines.append(f"│  载荷: {payload_chars:,} chars")
        if metadata_extra:
            for k, v in metadata_extra.items():
                vs = str(v)
                if len(vs) > 240:
                    vs = vs[:240] + "…"
                lines.append(f"│  metadata.{k}: {vs}")
        lines.append("├" + "─" * block_width + "┤")
        if payload_preview:
            pp = payload_preview.replace("\n", "⏎ ")
            if len(pp) > 1000:
                pp = pp[:1000] + "…"
            lines.append(f"│  预览: {pp}")
        else:
            lines.append("│  预览: (无内容)")
        lines.append("└" + "─" * block_width + "┘")
        logger.info("\n".join(lines))

    @staticmethod
    def _log_local_skill_executor_config() -> None:
        """One-shot snapshot at executor construction (server startup for SemanticGroup)."""
        use_only = os.getenv("USE_ONLY_OWN_CAPABILITY", "true").strip()
        logger.info(
            "[LocalSkill][Config] route_B env snapshot (effective on first request that needs skills): "
            "ENABLE_LOCAL_SKILLS=%s LOCAL_SKILLS_DIR=%r LOCAL_SKILL_AGENT_NAME=%s "
            "LOCAL_SKILL_INJECT_CARD=%s LOCAL_SKILL_FALLBACK_ON_NONE=%s "
            "LOCAL_SKILL_MAX_STEPS=%d LOCAL_SKILL_CMD_TIMEOUT_SEC=%d LOCAL_SKILL_MAX_CONCURRENCY=%d "
            "USE_ONLY_OWN_CAPABILITY=%s skill_sdk_importable=%s",
            LOCAL_SKILLS_ENABLED,
            LOCAL_SKILLS_DIR,
            LOCAL_SKILL_AGENT_NAME,
            LOCAL_SKILL_INJECT_MODE,
            LOCAL_SKILL_FALLBACK_ON_NONE,
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
            LOCAL_SKILL_MAX_CONCURRENCY,
            use_only,
            SkillRunner is not None,
        )

    def _build_skill_runner_llm(self):
        """Build a dedicated LLM for SkillRunner using the executor-level config.

        Kept separate from the per-request orchestration LLM so that SkillRunner
        can be a true process-wide singleton.
        """
        mgr = ModelManager()
        _extra_body = (
            {"enable_thinking": False}
            if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
            else {}
        )
        return mgr.get_llm(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            stream=False,
            extra_body=_extra_body,
        )

    def _build_code_execution(self, llm: Any) -> Any | None:
        """构造 ``CodeExecution`` 并与 SkillRunner **共用**同一 ``llm``。"""
        if not ENABLE_CODE_EXEC:
            logger.info("[LocalSkill][Init] ENABLE_CODE_EXEC=false — code_exec tool not exposed")
            return None
        if CodeExecution is None:
            logger.warning(
                "[LocalSkill][Init] ``CodeExecution`` not importable — "
                "``code_exec`` will be missing; model may fall back to plan_cmd/python."
            )
            return None
        inst = CodeExecution(llm=llm, max_retries=CODE_EXEC_MAX_RETRIES)
        logger.info(
            "[LocalSkill][Init] CodeExecution enabled (max_retries=%s) — ReAct exposes code_exec",
            CODE_EXEC_MAX_RETRIES,
        )
        return inst

    def _init_skill_runner_sync(self) -> "SkillRunner | None":
        """Build SkillRunner + load skills synchronously. Safe at startup or on first request.

        Logs the full skill inventory so operators can immediately see what the
        orchestrator will expose as LocalSkill.
        """
        if not LOCAL_SKILLS_ENABLED:
            logger.info(
                "[LocalSkill][Init] ENABLE_LOCAL_SKILLS=false — skipping SkillRunner initialisation"
            )
            return None
        if SkillRunner is None:
            logger.warning(
                "[LocalSkill][Init] ENABLE_LOCAL_SKILLS=true but skill_sdk is not importable; "
                "LocalSkill disabled for this process. (Check that the `skill_sdk` wheel is installed "
                "in the image and includes the route-B async changes.)"
            )
            return None
        logger.info(
            "[LocalSkill][Init] bootstrapping SkillRunner: dir=%s max_steps=%d "
            "cmd_timeout_sec=%d max_concurrency=%d inject_mode=%s fallback_on_none=%s "
            "agent_card_name=%s",
            LOCAL_SKILLS_DIR or "(unset)",
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
            LOCAL_SKILL_MAX_CONCURRENCY,
            LOCAL_SKILL_INJECT_MODE,
            LOCAL_SKILL_FALLBACK_ON_NONE,
            LOCAL_SKILL_AGENT_NAME,
        )
        t0 = _time.perf_counter()
        try:
            llm = self._build_skill_runner_llm()
            code_execution = self._build_code_execution(llm)
            try:
                runner = SkillRunner(
                    llm=llm,
                    max_steps=LOCAL_SKILL_MAX_STEPS,
                    cmd_timeout_sec=LOCAL_SKILL_CMD_TIMEOUT_SEC,
                    max_concurrency=LOCAL_SKILL_MAX_CONCURRENCY,
                    code_execution=code_execution,
                )
            except TypeError:
                logger.warning(
                    "[LocalSkill][Init] installed skill_sdk does not accept max_concurrency "
                    "(stale wheel?). Falling back to single-process mode; rebuild the wheel to "
                    "get the async concurrency upgrade."
                )
                runner = SkillRunner(
                    llm=llm,
                    max_steps=LOCAL_SKILL_MAX_STEPS,
                    cmd_timeout_sec=LOCAL_SKILL_CMD_TIMEOUT_SEC,
                    code_execution=code_execution,
                )
            if LOCAL_SKILLS_DIR:
                load_t0 = _time.perf_counter()
                loaded = runner.load_from_dir(LOCAL_SKILLS_DIR)
                load_ms = int((_time.perf_counter() - load_t0) * 1000)
                loaded = loaded or []
                loaded_names = [str(getattr(s, "name", "") or "").strip() for s in loaded]
                loaded_names = [n for n in loaded_names if n]
                logger.info(
                    "[LocalSkill][Init] load_from_dir finished: count=%d path=%s elapsed_ms=%d "
                    "(summary: %s)",
                    len(loaded),
                    LOCAL_SKILLS_DIR,
                    load_ms,
                    ", ".join(loaded_names) if loaded_names else "(none)",
                )
                if loaded:
                    logger.info(
                        "[LocalSkill][Init] ---- skill inventory (%d) ----",
                        len(loaded),
                    )
                    for idx, sk in enumerate(loaded, start=1):
                        nm = str(getattr(sk, "name", "") or "").strip() or "(unnamed)"
                        ver = str(getattr(sk, "version", "") or "").strip() or "?"
                        desc = str(getattr(sk, "description", "") or "").strip().replace("\n", " ")
                        if len(desc) > 140:
                            desc = desc[:140] + "..."
                        logger.info(
                            "[LocalSkill][Init]   %3d. name=%r version=%r description=%s",
                            idx,
                            nm,
                            ver,
                            desc,
                        )
                    logger.info("[LocalSkill][Init] ---- end skill inventory ----")
                else:
                    logger.warning(
                        "[LocalSkill][Init] no skills loaded from %s — expected *.zip skill packs; "
                        "LocalSkill card will be empty until packs appear",
                        LOCAL_SKILLS_DIR,
                    )
            else:
                logger.warning(
                    "[LocalSkill][Init] ENABLE_LOCAL_SKILLS=true but LOCAL_SKILLS_DIR is empty; "
                    "no skills were loaded — LocalSkill will advertise an empty capability."
                )
            logger.info(
                "[LocalSkill][Init] ready in %dms (llm=%s model=%s)",
                int((_time.perf_counter() - t0) * 1000),
                self.provider,
                self.model,
            )
            return runner
        except Exception:  # noqa: BLE001
            logger.exception(
                "[LocalSkill][Init] failed to initialise SkillRunner — disabling for this process"
            )
            return None

    def preload_skill_runner(self) -> "SkillRunner | None":
        """Eagerly initialise the process-wide SkillRunner at server startup.

        Call this synchronously from the server bootstrap so the full skill
        inventory is logged **before** the first A2A request arrives. Safe to
        call multiple times — the second call is a no-op.
        """
        if self._skill_runner_initialised:
            return self._skill_runner
        self._skill_runner = self._init_skill_runner_sync()
        self._skill_runner_initialised = True
        return self._skill_runner

    async def _ensure_skill_runner(self) -> "SkillRunner | None":
        """Return the process-wide SkillRunner, constructing it on first use.

        Normally a no-op because :meth:`preload_skill_runner` ran at startup;
        this path only fires when preload was skipped or failed to short-circuit.
        """
        if self._skill_runner_initialised:
            return self._skill_runner
        async with self._skill_runner_lock:
            if self._skill_runner_initialised:
                return self._skill_runner
            runner = await asyncio.to_thread(self._init_skill_runner_sync)
            self._skill_runner = runner
            self._skill_runner_initialised = True
        return self._skill_runner

    def shutdown_skill_runner(self) -> None:
        """Release any resources held by the shared SkillRunner.

        Safe to call repeatedly; only meaningful once, so follow-up calls are
        no-ops. Intended to be wired into process shutdown hooks.
        """
        runner, self._skill_runner = self._skill_runner, None
        already_initialised = self._skill_runner_initialised
        self._skill_runner_initialised = True  # don't re-init after shutdown
        if runner is not None:
            logger.info("[LocalSkill][Shutdown] closing SkillRunner …")
            try:
                runner.close()
                logger.info("[LocalSkill][Shutdown] SkillRunner closed cleanly")
            except Exception:  # noqa: BLE001
                logger.exception("[LocalSkill][Shutdown] SkillRunner.close() raised")
        elif already_initialised:
            logger.debug("[LocalSkill][Shutdown] no active SkillRunner to close")

    def current_agent_label(self) -> str:
        return (self.agent_id or self.semantic_group_id or "sg_orchestrator").strip()

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 320) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit - 3] + "..."

    async def emit_progress(
        self,
        updater: TaskUpdater,
        task_name: str,
        *,
        event: str,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        layer: str = "sg_orchestrator",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if os.getenv("ENABLE_SG_PROGRESS_STREAM", "true").strip().lower() in ("false", "0", "no"):
            return
        await updater.add_artifact(
            [TextPart(text=OrchestratorAgent.build_progress_frame(
                event,
                message=message,
                status=status,
                run_id=self._progress_context.get("run_id", ""),
                user_id=self._progress_context.get("user_id", ""),
                agent_id=self._progress_context.get("agent_id", "") or self.current_agent_label(),
                task_id=task_id,
                layer=layer,
                extra=extra,
            ))],
            name=task_name,
        )

    async def emit_answer(
        self,
        updater: TaskUpdater,
        task_name: str,
        *,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        status: str = "done",
        task_id: Optional[int] = None,
        layer: str = "sg_orchestrator",
    ) -> None:
        await updater.add_artifact(
            [TextPart(text=OrchestratorAgent.build_answer_frame(
                event,
                payload=payload,
                status=status,
                run_id=self._progress_context.get("run_id", ""),
                user_id=self._progress_context.get("user_id", ""),
                agent_id=self._progress_context.get("agent_id", "") or self.current_agent_label(),
                task_id=task_id,
                layer=layer,
            ))],
            name=task_name,
        )

    @staticmethod
    def _member_capability_flag(name: str, *, default: bool = False) -> bool:
        default_value = "true" if default else "false"
        return os.getenv(name, default_value).strip().lower() in (
            "true",
            "1",
            "yes",
        )

    def _capability_identity(self) -> tuple[str, str]:
        agent_name = self.agent_card.name if self.agent_card else self.agent_id or "Unknown"
        agent_url = self.agent_card.url if self.agent_card else ""
        return agent_name, agent_url

    async def _legacy_capability_check(
        self,
        query: str,
        md: dict[str, Any],
    ) -> CapabilityCheckResponse:
        """Run the original SG self-description LLM capability check."""
        _cc_start = _time.monotonic()
        agent_name, agent_url = self._capability_identity()
        agent_description = self.agent_card.description if self.agent_card else ""
        agent_skills_text = "（无）"
        if self.agent_card and self.agent_card.skills:
            skills_lines = []
            for skill in self.agent_card.skills:
                skill_desc = f"- {skill.name}: {skill.description}"
                if hasattr(skill, 'tags') and skill.tags:
                    skill_desc += f" (tags: {', '.join(skill.tags)})"
                if hasattr(skill, 'examples') and skill.examples:
                    skill_desc += f" (examples: {', '.join(skill.examples)})"
                skills_lines.append(skill_desc)
            agent_skills_text = "\n".join(skills_lines)

        try:
            history_payload = parse_propagated_history(md.get(PROPAGATED_HISTORY_KEY))
            if self.enable_history == "enable" and not normalize_history_turns(history_payload.get("turns")):
                search_items = []
                search_request = SearchHistoryRequest(
                    user_id=md.get("user_id", ""),
                    run_id=md.get("run_id", ""),
                    limit=get_conversation_history_limit(),
                )
                ds_client = DataServicesClient(
                    base_url=self.data_services_url,
                    timeout=600,
                    use_data_descriptor_header=False,
                )
                async with ds_client.session_context() as client:
                    history_search_response = await client.search_history_by_user_and_run(search_request)
                if history_search_response.status == "success":
                    search_items = history_search_response.data
                elif history_search_response.detail:
                    logger.error(f"Capability check get_history error msg: {history_search_response.detail}")
                history_payload = history_payload_from_search_items(
                    search_items,
                    source="sg_capability_fallback",
                )
            history_text = history_text_from_payload(history_payload) or "（无）"
            prompt = CAPABILITY_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                history=history_text,
                query=query,
            )
            cap_tool = StructuredTool(
                name="evaluate_capability",
                description="评估本智能体能否处理用户问题，输出判定结果和推理过程。",
                args_schema=CapabilityCheckToolResult,
                func=None,
                coroutine=None,
            )
            result_data = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=cap_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=self.metadata,
                tool_choice="evaluate_capability",
                span_name="group-capability-check-llm",
                span_input={"query": query, "agent_name": agent_name},
            )
            if result_data is None:
                raise ValueError("LLM did not call evaluate_capability tool")
            conf = result_data.get("confidence", 0.0)
            leaf_path = [agent_name]
            check_response = CapabilityCheckResponse(
                can_handle=result_data.get("can_handle", False),
                confidence=conf,
                reason=result_data.get("reason", ""),
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": conf, "alias": _path_to_alias(leaf_path)}],
                can_contribute=result_data.get("can_contribute", False),
                contribution=result_data.get("contribution", ""),
                latency_ms=int((_time.monotonic() - _cc_start) * 1000),
            )
        except Exception as e:
            logger.error(f"Capability check analysis failed: {e}")
            leaf_path = [agent_name]
            check_response = CapabilityCheckResponse(
                can_handle=False,
                confidence=0.0,
                reason=f"Analysis failed: {str(e)}",
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": 0.0, "alias": _path_to_alias(leaf_path)}],
                latency_ms=int((_time.monotonic() - _cc_start) * 1000),
            )
        return check_response

    def _member_capability_sidecar_card(self) -> AgentCard:
        sidecar_url = (
            os.getenv("SG_MEMBER_CAPABILITY_CHECK_URL", "").strip()
            or "http://localhost:10101"
        )
        if self.agent_card is not None:
            dump = getattr(self.agent_card, "model_dump", None) or getattr(
                self.agent_card, "dict", None
            )
            card_data = dict(dump()) if dump else {}
        else:
            agent_name, _ = self._capability_identity()
            card_data = {
                "name": agent_name,
                "description": "",
                "version": "1.0.0",
                "capabilities": {},
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"],
                "skills": [],
            }
        card_data["url"] = sidecar_url
        return AgentCard(**card_data)

    @staticmethod
    def _parse_capability_json(text: str) -> dict[str, Any]:
        payload = str(text or "").strip()
        if payload.startswith("```json"):
            payload = payload[7:]
        elif payload.startswith("```"):
            payload = payload[3:]
        if payload.endswith("```"):
            payload = payload[:-3]
        result = json.loads(payload.strip())
        if not isinstance(result, dict):
            raise ValueError("member capability response must be a JSON object")
        return result

    @staticmethod
    def _capability_response_text(chunk: Any) -> str:
        """Extract text from an A2A artifact update returned by the SG Expert."""
        dump = getattr(chunk, "model_dump", None)
        if not callable(dump):
            return ""
        data = dump(mode="json", exclude_none=True)
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict) or result.get("kind") != "artifact-update":
            return ""
        artifact = result.get("artifact")
        parts = artifact.get("parts") if isinstance(artifact, dict) else None
        if not isinstance(parts, list):
            return ""
        return "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict) and part.get("text") is not None
        )

    async def _delegated_member_capability_check(
        self,
        query: str,
        md: dict[str, Any],
    ) -> CapabilityCheckResponse:
        """Ask the local SG Expert sidecar to evaluate its member agents."""
        started = _time.monotonic()
        agent_name, agent_url = self._capability_identity()
        sidecar_card = self._member_capability_sidecar_card()
        timeout_raw = (
            os.getenv("SG_MEMBER_CAPABILITY_CHECK_TIMEOUT", "").strip()
            or os.getenv("SG_MEMBER_CAPABILITY_CHECK_TIMEOUT_SECONDS", "").strip()
            or "180"
        )
        timeout = float(timeout_raw)
        send_payload: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": query}],
                "messageId": uuid4().hex,
            },
            "metadata": {
                "message_type": "group_member_capability_check",
                "user_id": str(md.get("user_id") or ""),
                "run_id": str(md.get("run_id") or ""),
                "trace_id": str(md.get("trace_id") or ""),
                PROPAGATED_HISTORY_KEY: parse_propagated_history(
                    md.get(PROPAGATED_HISTORY_KEY)
                ),
            },
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0))
        ) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=sidecar_card)
            request = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_payload),
            )
            chunks: list[str] = []
            async for chunk in client.send_message_streaming(request):
                text = self._capability_response_text(chunk)
                if text:
                    chunks.append(text)

        data = self._parse_capability_json("".join(chunks))
        route_path = data.get("route_path") or [agent_name]
        route_paths = data.get("route_paths") or []
        if not route_paths:
            route_paths = [{
                "path": route_path,
                "confidence": data.get("confidence", 0.0),
                "alias": _path_to_alias(route_path),
            }]
        response = CapabilityCheckResponse(
            can_handle=bool(data.get("can_handle", False)),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            reason=str(data.get("reason") or ""),
            agent_name=str(data.get("agent_name") or agent_name),
            agent_url=str(data.get("agent_url") or agent_url),
            route_path=route_path,
            route_paths=route_paths,
            can_contribute=bool(data.get("can_contribute", False)),
            contribution=str(data.get("contribution") or ""),
            execution_strategy=str(data.get("execution_strategy") or "single"),
            collaboration_agents=data.get("collaboration_agents") or [],
            collaboration_roles=data.get("collaboration_roles") or {},
            collaboration_paths=data.get("collaboration_paths") or [],
            member_results=data.get("member_results") or [],
            degraded=bool(data.get("degraded", False)),
            unavailable_count=int(data.get("unavailable_count", 0) or 0),
            missing_requirements=data.get("missing_requirements") or [],
            latency_ms=int((_time.monotonic() - started) * 1000),
        )
        logger.info(
            "[Capability][MemberDelegation] member_response_count=%d "
            "unavailable_count=%d strategy=%s degraded=%s delegated_latency_ms=%d",
            len(response.member_results),
            response.unavailable_count,
            response.execution_strategy,
            response.degraded,
            response.latency_ms,
        )
        return response

    @staticmethod
    def _log_capability_shadow_difference(
        legacy: CapabilityCheckResponse,
        delegated: CapabilityCheckResponse,
    ) -> None:
        fields = (
            "can_handle",
            "can_contribute",
            "confidence",
            "execution_strategy",
            "collaboration_agents",
            "missing_requirements",
        )
        differences = {
            field: {
                "old": getattr(legacy, field),
                "new": getattr(delegated, field),
            }
            for field in fields
            if getattr(legacy, field) != getattr(delegated, field)
        }
        logger.info(
            "[Capability][MemberDelegation] shadow_difference=%s "
            "old_new_disagreement=%s",
            json.dumps(differences, ensure_ascii=False, default=str),
            bool(differences),
        )

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """Handle routing probes without entering normal task execution."""
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        request_metadata = context.metadata if isinstance(context.metadata, dict) else {}
        if request_metadata:
            self.metadata = request_metadata
        md = request_metadata or (self.metadata if isinstance(self.metadata, dict) else {})
        agent_name, _ = self._capability_identity()
        enabled = self._member_capability_flag(
            "SG_MEMBER_CAPABILITY_CHECK_ENABLED",
            default=True,
        )
        shadow = self._member_capability_flag("SG_MEMBER_CAPABILITY_CHECK_SHADOW")
        mode = "shadow" if shadow else ("delegated" if enabled else "legacy")
        logger.info(
            "[RoutePlan] ----- %s | capability_check start | mode=%s | query: %s -----",
            agent_name,
            mode,
            query[:80] + ("..." if len(query) > 80 else ""),
        )

        if shadow:
            delegated_started = _time.monotonic()
            legacy_result, delegated_result = await asyncio.gather(
                self._legacy_capability_check(query, md),
                self._delegated_member_capability_check(query, md),
                return_exceptions=True,
            )
            if isinstance(legacy_result, BaseException):
                raise legacy_result
            check_response = legacy_result
            if isinstance(delegated_result, BaseException):
                logger.warning(
                    "[Capability][MemberDelegation] mode=shadow sidecar_unavailable=true "
                    "delegated_latency_ms=%d error_type=%s error=%s",
                    int((_time.monotonic() - delegated_started) * 1000),
                    type(delegated_result).__name__,
                    delegated_result,
                )
            else:
                self._log_capability_shadow_difference(check_response, delegated_result)
        elif enabled:
            delegated_started = _time.monotonic()
            try:
                delegated_result = await self._delegated_member_capability_check(query, md)
                if delegated_result.degraded:
                    logger.warning(
                        "[Capability][MemberDelegation] mode=delegated degraded=true "
                        "fallback=legacy member_response_count=%d unavailable_count=%d "
                        "delegated_latency_ms=%d",
                        len(delegated_result.member_results),
                        delegated_result.unavailable_count,
                        delegated_result.latency_ms,
                    )
                    check_response = await self._legacy_capability_check(query, md)
                else:
                    check_response = delegated_result
            except Exception as exc:
                logger.warning(
                    "[Capability][MemberDelegation] mode=delegated sidecar_unavailable=true "
                    "fallback=legacy delegated_latency_ms=%d error_type=%s error=%s",
                    int((_time.monotonic() - delegated_started) * 1000),
                    type(exc).__name__,
                    exc,
                )
                check_response = await self._legacy_capability_check(query, md)
        else:
            check_response = await self._legacy_capability_check(query, md)

        # Single-layer SG: do not probe child groups or build subtree collaboration plans.
        path_display = " -> ".join(check_response.route_path) if check_response.route_path else check_response.agent_name
        paths_count = len(getattr(check_response, "route_paths", []) or [])
        strategy = getattr(check_response, "execution_strategy", None) or "single"
        collab = getattr(check_response, "collaboration_agents", None) or []
        collab_paths = getattr(check_response, "collaboration_paths", None) or []
        collab_paths_display = "; ".join(
            f"{e.get('agent', '?')}:[{'->'.join(e.get('path', []))}]"
            for e in collab_paths[:5]
            if isinstance(e, dict)
        )
        logger.info(
            "[Capability] ========== Result for '%s' ==========\n"
            "  can_handle=%s | confidence=%.2f | strategy=%s | paths=%d\n"
            "  best_path: %s%s\n"
            "%s"
            "========================================",
            query[:60] + ("..." if len(query) > 60 else ""),
            check_response.can_handle,
            check_response.confidence,
            strategy,
            paths_count or 1,
            path_display,
            (" | collaboration=" + str(collab)) if collab else "",
            (f"  collaboration_paths: {collab_paths_display}\n" if collab_paths_display else ""),
        )
        check_response.execution_hint = self._build_execution_hint(
            run_id=str(md.get("run_id") or ""),
            query=query,
            check_response=check_response,
        )
        logger.info(
            "[Capability][ExecutionHint] issued | run_id=%s can_handle=%s "
            "strategy=%s selected=%s ttl_sec=%s",
            md.get("run_id") or "",
            check_response.execution_hint.get("can_handle"),
            check_response.execution_hint.get("execution_strategy"),
            check_response.execution_hint.get("selected_members"),
            check_response.execution_hint.get("ttl_seconds"),
        )
        response_json = check_response.model_dump_json()

        await updater.add_artifact(
            [TextPart(text=response_json)],
            name="capability-check-response",
        )
        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

    async def handle_pre_make_plan(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """Handle a pre-make-plan request from the routing agent.

        Called when the routing agent sends ``message_type="pre_make_plan"``
        to evaluate this agent's task-planning capability.  Creates an
        ``OrchestratorAgent``, runs the planner, and returns the resulting
        ``TaskList`` as JSON.
        """
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        metadata = dict(context.metadata or {})

        logger.info(
            "[PreMakePlan] request received | agent=%s query=%s",
            self.agent_id,
            (query or "")[:150],
        )

        try:
            skill_runner = await self._ensure_skill_runner()

            agent = OrchestratorAgent(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                stream=self.stream,
                temperature=self.temperature,
                semantic_group_id=self.semantic_group_id,
                debug=self.debug,
                data_services_url=self.data_services_url,
                metadata=metadata,
                enable_history=self.enable_history,
                agent_id=self.agent_id,
                max_loops=self.max_loops,
                agent_card=self.agent_card,
                skill_runner=skill_runner,
            )

            all_cards, own_names, collab_names = await agent._resolve_planner_agent_pool(query)

            base_group_memory = await agent.get_memory(query)
            upstream_context = dict(metadata.get("upstream_context", {}))
            group_memory = self._enrich_group_memory_with_upstream(
                upstream_context=upstream_context,
                base_group_memory=base_group_memory,
            )

            plan = await agent.planner_agent.make_plan(
                query, all_cards, group_memory=group_memory,
            )

            response = plan.model_dump_json()
            task_details = []
            for t in plan.tasks:
                task_details.append(
                    f"  Task#{t.id} agent={t.agent} "
                    f"depends_on={t.depends_on or []} "
                    f"desc={t.description or ''}"
                )
            logger.info(
                "[PreMakePlan] agent=%s produced plan: tasks=%d\n%s",
                self.agent_id,
                len(plan.tasks),
                "\n".join(task_details),
            )
        except Exception as e:
            logger.error(
                "[PreMakePlan] agent=%s failed: %s", self.agent_id, e, exc_info=True,
            )
            response = json.dumps({"error": str(e)})

        await updater.add_artifact(
            [TextPart(text=response)],
            name="pre-make-plan-response",
        )
        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

    @staticmethod
    def _enrich_group_memory_with_upstream(
        upstream_context: dict,
        base_group_memory: str = "",
        extra_context: dict | None = None,
    ) -> str:
        """Enrich group_memory with upstream delegation context.

        Injects the upstream's executed_tasks, key_findings, delegator_plan,
        and (in mid-exec rounds) already_delegated / synthesized_query /
        detection_reason into the group_memory string so the Planner can
        produce more precise task descriptions that reference prior work.
        """
        parts: list[str] = []
        if base_group_memory:
            parts.append(base_group_memory)

        exec_tasks = upstream_context.get("executed_tasks")
        key_findings = upstream_context.get("key_findings_so_far")
        delegator_plan = upstream_context.get("delegator_plan")
        upstream_inner = upstream_context.get("upstream_context")

        upstream_info_parts: list[str] = []
        if delegator_plan:
            plan_text = json.dumps(delegator_plan, ensure_ascii=False)
            upstream_info_parts.append(f"上游原始计划: {plan_text}")
        if exec_tasks:
            tasks_text = json.dumps(exec_tasks, ensure_ascii=False)
            upstream_info_parts.append(f"上游已执行任务及结果: {tasks_text}")
        if key_findings:
            upstream_info_parts.append(f"上游关键发现: {key_findings}")
        if upstream_inner:
            inner_text = json.dumps(upstream_inner, ensure_ascii=False)
            upstream_info_parts.append(f"更上层上下文: {inner_text}")

        if extra_context:
            ctx_parts: list[str] = []
            already = extra_context.get("already_delegated")
            synth = extra_context.get("synthesized_query")
            reason = extra_context.get("detection_reason")
            if already:
                ctx_parts.append(
                    f"已委托结果: {json.dumps(already, ensure_ascii=False)}"
                )
            if synth:
                ctx_parts.append(f"当前合成子问题: {synth}")
            if reason:
                ctx_parts.append(f"委托原因: {reason}")
            if ctx_parts:
                upstream_info_parts.append(
                    "当前轮次上下文:\n" + "\n".join(ctx_parts)
                )

        if upstream_info_parts:
            banner = (
                "=== 上游委托上下文（仅供理解关联键来源；规划远程任务时"
                "禁止把其它域目标或整题扩写写进 description） ===\n"
            )
            parts.append(banner + "\n\n".join(upstream_info_parts))

        result = "\n\n".join(parts)
        # Build a compact preview of upstream content for INFO-level visibility
        _preview_parts: list[str] = []
        if delegator_plan:
            _task_descs = ", ".join(
                f"#{t.get('id', '?')}:{str(t.get('description', ''))}"
                for t in (delegator_plan if isinstance(delegator_plan, list) else [])
            )
            _preview_parts.append(f"plan=[{_task_descs}]")
        if exec_tasks:
            _exec_descs = ", ".join(
                f"#{t.get('task_id', '?')}:{str(t.get('result', ''))}"
                for t in (exec_tasks if isinstance(exec_tasks, list) else [])
            )
            _preview_parts.append(f"executed=[{_exec_descs}]")
        if key_findings:
            _preview_parts.append(f"findings='{str(key_findings)[:200]}'")
        if upstream_inner:
            _preview_parts.append("hasUpstreamChain")
        _preview = " | ".join(_preview_parts) if _preview_parts else "(none)"
        logger.info(
            "[Cross-SG][CollabEnrichMem] upstream_context injection | base_chars=%d enriched_chars=%d fields=%s preview=%s",
            len(base_group_memory or ""),
            len(result),
            [
                k
                for k in ("delegator_plan", "executed_tasks", "key_findings_so_far", "upstream_context")
                if upstream_context.get(k)
            ],
            _preview,
        )
        return result

    @staticmethod
    def _format_upstream_context_summary(upstream_context: dict | None) -> str:
        """Produce a compact, human-readable summary of upstream_context for logging.

        Example output: ``plan=3tasks executed=2tasks findings=450chars chain=1``
        If upstream_context is empty or None, returns ``(none)``.
        """
        if not upstream_context:
            return "(none)"
        parts: list[str] = []
        _plan = upstream_context.get("delegator_plan")
        _exec = upstream_context.get("executed_tasks")
        _findings = upstream_context.get("key_findings_so_far")
        _inner = upstream_context.get("upstream_context")
        if _plan:
            parts.append(f"plan={len(_plan)}tasks")
        if _exec:
            parts.append(f"executed={len(_exec)}tasks")
        if _findings:
            parts.append(f"findings={len(_findings)}chars")
        if _inner:
            parts.append(f"upstreamChain=depth+1")
        return " ".join(parts) if parts else "(empty)"

    async def _emit_collab_mid_round_done(
        self,
        updater: TaskUpdater,
        *,
        round_num: int,
        max_rounds: int,
        total_delegated: int,
        early_exit: str = "",
    ) -> None:
        msg = f"Mid-execution round {round_num}/{max_rounds} finished"
        if early_exit:
            msg = f"{msg}: {early_exit}"
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_mid_round_done",
            message=msg,
            status="done",
            extra={
                "round": round_num,
                "total_delegated": total_delegated,
            },
        )

    async def _emit_collab_mid_exec_loop_done(
        self,
        updater: TaskUpdater,
        *,
        total_rounds: int,
        total_delegated: int,
    ) -> None:
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_mid_exec_loop_done",
            message=f"Mid-execution loop finished ({total_rounds} round(s))",
            status="done",
            extra={
                "total_rounds": total_rounds,
                "total_delegated": total_delegated,
            },
        )

    async def execute_collaborative(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cross-SG collaborative execution entry point.

        When ``metadata.collaboration_delegation`` is ``True`` this request
        was delegated from another SG; otherwise it is the original user
        request that happened to arrive with collaborative mode enabled.
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
        self._progress_context = {
            "run_id": run_id,
            "user_id": user_id,
            "agent_id": self.agent_id or self.current_agent_label(),
        }

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

        # Guard: hop exhausted — stop immediately, do not execute any tasks.
        if is_delegated and current_hop <= 0:
            await self.emit_progress(
                updater,
                "collaboration-progress",
                event="collab_started",
                message=(
                    f"Collaborative execution aborted (SG: {sg_label}, "
                    f"delegated: {is_delegated}, hop: {current_hop}) — hop exhausted"
                ),
                status="done",
                extra={
                    "sg_label": sg_label,
                    "sg_id": self.semantic_group_id or "?",
                    "is_delegated": is_delegated,
                    "hop": current_hop,
                    "chain_depth": len(delegation_chain),
                },
            )
            return {
                "answer": "",
                "tasks": [],
                "reason": "hop_exhausted",
                "status": "fail",
            }

        sg_label = self.agent_card.name if self.agent_card else (self.agent_id or self.semantic_group_id or "?")

        # --- Data Flow: log upstream context at entry ---
        _upstream_summary = self._format_upstream_context_summary(upstream_context)
        logger.info(
            "[Cross-SG][CollabEntry] execute_collaborative started | sg=%s sg_id=%s is_delegated=%s hop=%d chain=%s "
            "query_len=%d user_id=%s run_id=%s trace_id=%s upstream=%s",
            sg_label,
            self.semantic_group_id,
            is_delegated,
            current_hop,
            delegation_chain,
            len(query or ""),
            user_id,
            run_id,
            trace_id,
            _upstream_summary,
        )

        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_started",
            message=f"Collaborative execution started (SG: {sg_label}, delegated: {is_delegated}, hop: {current_hop})",
            status="running",
            extra={
                "sg_label": sg_label,
                "sg_id": self.semantic_group_id or "?",
                "is_delegated": is_delegated,
                "hop": current_hop,
                "chain_depth": len(delegation_chain),
            },
        )

        # ---- 发现协作 SG ----
        skill_runner = await self._ensure_skill_runner()
        agent = OrchestratorAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            semantic_group_id=self.semantic_group_id,
            debug=self.debug,
            data_services_url=self.data_services_url,
            metadata=metadata,
            enable_history=self.enable_history,
            agent_id=self.agent_id,
            max_loops=self.max_loops,
            agent_card=self.agent_card,
            skill_runner=skill_runner,
        )
        agent._init_routing_pool_from_metadata(metadata)

        if agent._routing_pool_flow_enabled():
            augmented_pool, own_names, collaborator_names = await agent._resolve_planner_agent_pool(query)
            agent.agent_cards = augmented_pool
            collaborator_cards = [
                c for c in augmented_pool if getattr(c, "name", "") in collaborator_names
            ]
        else:
            agent.agent_cards = await agent.list_agent_cards(query, for_collaboration=True)
            collaborator_cards = await agent.discover_collaborator_sgs()
            own_names = {c.name for c in (agent.agent_cards or [])}
            collaborator_names = {c.name for c in collaborator_cards}
            augmented_pool, dup_drop = agent._dedupe_agent_cards_by_name_preserve_order(
                (agent.agent_cards or []) + collaborator_cards
            )

        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_discovered_sgs",
            message=f"Collaborator pool ready: {', '.join(sorted(collaborator_names)) or '(none)'}",
            status="running",
            extra={
                "own_expert_count": len(own_names),
                "collab_sg_count": len(collaborator_names),
                "collab_sg_names": sorted(collaborator_names),
                "pool_source": "routing_agent_pool" if agent._routing_pool_flow_enabled() else "legacy_discover",
            },
        )

        # ---- 规划：agent 池 ----
        own_cards = [c for c in (augmented_pool or []) if getattr(c, "name", "") in own_names]
        if not agent._routing_pool_flow_enabled():
            own_cards = agent.agent_cards or []
        coll_collection = os.getenv(
            "SG_COLLABORATION_COLLECTION",
            "biz_orchestrator_agent_cards",
        )
        local_names_sorted = sorted(own_names)
        collab_names_sorted = sorted(collaborator_names)
        local_dup_rows = len(own_cards) - len(own_names)
        self_agent_name = agent._self_planner_agent_name()
        logger.info(
            "[Cross-SG][CollabPlanning] local execution pool | agents run on this SG (Expert + LocalSkill) | "
            "count=%d unique=%d%s | agents=[%s]",
            len(own_cards),
            len(own_names),
            f" dup_rows={local_dup_rows}" if local_dup_rows else "",
            ", ".join(local_names_sorted) if local_names_sorted else "(empty)",
        )
        if agent._routing_pool_flow_enabled():
            routing_pool_size = len(
                agent._routing_agent_pool or sg_broadcast.parse_routing_agent_pool(metadata)
            )
            logger.info(
                "[Cross-SG][CollabPlanning] peer delegation pool | from RoutingAgent routing_agent_pool "
                "routing_pool_size=%d self=%s peer_count=%d peers=[%s]",
                routing_pool_size,
                self_agent_name or "(unknown)",
                len(collaborator_names),
                ", ".join(collab_names_sorted) if collab_names_sorted else "(none)",
            )
        else:
            logger.info(
                "[Cross-SG][CollabPlanning] peer delegation pool | from registry discover "
                "(collection=%s → delegate_to_collaborator_sg candidates) | "
                "peer_count=%d peers=[%s]",
                coll_collection,
                len(collaborator_names),
                ", ".join(collab_names_sorted) if collab_names_sorted else "(none)",
            )
        logger.info(
            "[Cross-SG][CollabPlanning] planner input pool | local + peer merged for make_plan | "
            "total=%d agents=[%s]",
            len(augmented_pool or []),
            ", ".join(sorted({getattr(c, "name", "") for c in (augmented_pool or [])})),
        )

        base_group_memory = await agent.get_memory(query)
        group_memory = self._enrich_group_memory_with_upstream(
            upstream_context=upstream_context,
            base_group_memory=base_group_memory,
        )
        execution_hint = self._validated_execution_hint(metadata, query)
        if execution_hint:
            note = self._execution_hint_memory_note(execution_hint)
            group_memory = f"{group_memory}\n\n{note}".strip() if group_memory else note
            logger.info(
                "[Capability][ExecutionHint] injected into execution context | run_id=%s "
                "selected=%s",
                run_id,
                (execution_hint.get("selected_members") or [])[:10],
            )
        logger.info(
            "[Cross-SG][CollabPlanning] group_memory prepared | base_chars=%d enriched_chars=%d",
            len(base_group_memory or ""),
            len(group_memory or ""),
        )
        authoritative_plan = self._build_authoritative_execution_plan(
            query=query,
            own_names=own_names,
            preferred_own_agent=self_agent_name,
            execution_hint=execution_hint,
        )
        if authoritative_plan:
            # A fresh, non-degraded member capability decision is authoritative
            # for the primary execution attempt. Do not let a second LLM plan
            # replace it with LocalSkill, another SG, or NONE.
            plan = authoritative_plan
            logger.info(
                "[Capability][ExecutionHint] authoritative dispatch | own_expert=%s "
                "selected_members=%s strategy=%s",
                plan.tasks[0].agent,
                (execution_hint.get("selected_members") or [])[:10],
                execution_hint.get("execution_strategy") or "single",
            )
        else:
            if execution_hint:
                logger.warning(
                    "[Capability][ExecutionHint] no own Expert available; "
                    "falling back to normal planner"
                )
            try:
                plan = await agent.planner_agent.make_plan(
                    query,
                    augmented_pool,
                    group_memory=group_memory,
                )
            except ValueError as plan_err:
                # Planning failed after retries; return a normal failed task.
                err_msg = f"任务规划失败：{plan_err}"
                logger.error(
                    "[Cross-SG][CollabPlanning] make_plan failed after retries | sg=%s err=%s",
                    sg_label, plan_err,
                )
                await updater.add_artifact(
                    [TextPart(text=err_msg)],
                    name="planning-error",
                )
                await updater.failed(
                    message=new_agent_text_message(err_msg, context_id=task.context_id),
                )
                return

        own_tasks: list[PlannerTask] = []
        delegation_tasks: list[PlannerTask] = []
        for t in plan.tasks:
            agent_name = (t.agent or "").strip()
            if agent_name.upper() == "NONE":
                own_tasks.append(t)
                continue
            # --- mutual-exclusive classification: own_pool wins for execution ---
            if agent_name in own_names:
                own_tasks.append(t)
            elif agent_name in collaborator_names:
                delegation_tasks.append(t)

        _orphan_tasks = [
            t for t in plan.tasks
            if (t.agent or "").strip().upper() != "NONE"
            and t.agent not in own_names
            and t.agent not in collaborator_names
        ]
        if _orphan_tasks:
            logger.warning(
                "[Cross-SG][CollabPlanning] orphan tasks detected — agent not found in own or collaborator cards: %s",
                [{"task_id": t.id, "agent": t.agent, "desc": (t.description or "")[:80]} for t in _orphan_tasks],
            )

        def _collab_plan_task_one_line(_t: PlannerTask) -> str:
            agent_nm = (_t.agent or "").strip() or "?"
            desc = ((_t.description or "").replace("\n", " ").strip())[:140]
            deps = f"(depends on: [{', '.join(str(d) for d in _t.depends_on)}]) " if _t.depends_on else ""
            return f"#{_t.id} {deps}agent={agent_nm!r} | {desc}"

        task_blocks = [_collab_plan_task_one_line(t) for t in plan.tasks]
        logger.info(
            "[Cross-SG][CollabPlan] %d planner task(s) — breakdown: exec_in_local_pool=%d (agents: %s) | delegate_to_SG=%d (agents: %s)",
            len(plan.tasks),
            len(own_tasks),
            ", ".join(sorted({t.agent for t in own_tasks})) or "(n/a)",
            len(delegation_tasks),
            ", ".join(sorted({t.agent for t in delegation_tasks})) or "(none)",
        )
        if task_blocks:
            logger.info("[Cross-SG][CollabPlan] tasks:\n%s", "\n".join(f"  • {ln}" for ln in task_blocks))
        else:
            logger.info("[Cross-SG][CollabPlan] tasks: (empty list)")

        # Build a human-readable plan summary message with task details
        plan_lines = [f"Plan ready: {len(own_tasks)} local tasks, {len(delegation_tasks)} delegate tasks"]
        for t in plan.tasks:
            agent_nm = (t.agent or "").strip() or "?"
            desc = ((t.description or "").replace("\n", " ").strip())[:140]
            deps = f"(depends on: [{', '.join(str(d) for d in t.depends_on)}]) " if t.depends_on else ""
            plan_lines.append(f"  • #{t.id} {deps}agent='{agent_nm}' | {desc}")
        plan_msg = "\n".join(plan_lines)

        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_plan_ready",
            message=plan_msg,
            status="running",
            extra={
                "total_tasks": len(plan.tasks),
                "own_task_count": len(own_tasks),
                "delegation_count": len(delegation_tasks),
                "own_agents": [t.agent for t in own_tasks],
                "delegation_targets": [t.agent for t in delegation_tasks],
            },
        )

        # ---- 按 plan 顺序依次执行任务（own 与 delegation 交替执行，保证 depends_on 顺序正确） ----
        own_results: dict[int, str] = {}
        delegated_results: dict[str, str] = {}
        # 用于跨 own/delegation 边界的依赖传播：按 task_id 索引所有已执行完成的结果
        _all_task_results: dict[int, str] = {}
        # 记录已跳过的 delegation 任务（hop 耗尽时标记，避免遗漏 summary）
        skipped_delegation_agents: set[str] = set()
        _own_executed_count = 0
        _delegation_executed_count = 0
        for plan_idx, t in enumerate(plan.tasks):
            agent_name = (t.agent or "").strip()
            # --- Route A (NONE): 跳过 ---
            if agent_name.upper() == "NONE":
                self._log_data_flow(
                    direction="TASK_SKIPPED",
                    description=f"Task #{t.id} agent=NONE, skip",
                    source_id="planner",
                    target_id=agent.agent_name or "?",
                    metadata_extra={"task_id": t.id, "reason": "agent_is_none"},
                )
                continue

            # --- Route B: LocalSkill 或 Own Expert ---
            if agent_name in own_names:
                _own_executed_count += 1
                await self.emit_progress(
                    updater,
                    "collaboration-progress",
                    event="collab_executing_own",
                    message=f"Executing task {_own_executed_count} (plan #{plan_idx + 1}/{len(plan.tasks)}): [{agent_name}] {(t.description or '')[:80]}",
                    status="running",
                    extra={
                        "plan_index": plan_idx + 1,
                        "own_task_index": _own_executed_count,
                        "total_own_tasks": len(own_tasks),
                        "agent": agent_name,
                        "task_id": t.id,
                        "desc_preview": (t.description or "")[:120],
                    },
                )
                logger.info(
                    "[Cross-SG][CollabExecuteOwn] dispatching task | plan_idx=%d task_id=%d agent=%s desc_preview=%s",
                    plan_idx,
                    t.id,
                    agent_name,
                    (t.description or "")[:100],
                )
                result = await self._execute_own_task_via_expert(
                    t, user_id, run_id, trace_id, updater, agent,
                    prior_task_results=_all_task_results,
                    collaboration_original_query=query,
                )
                own_results.setdefault(t.id, "")
                own_results[t.id] = result
                _all_task_results.setdefault(t.id, "")
                _all_task_results[t.id] = result
                # --- Data Flow: task execution complete ---
                self._log_data_flow(
                    direction="A2A_RESULT",
                    description=f"Task #{t.id} 执行完毕",
                    source_id=f"{t.agent or '?'}",
                    target_id=f"{agent.agent_name or '?'}",
                    payload_chars=len(result or ""),
                    payload_preview=(result or "")[:1000],
                    metadata_extra={
                        "task_id": t.id,
                        "depends_on": t.depends_on if t.depends_on else [],
                    },
                )
                _own_done_desc = self._truncate_progress_message(t.description or "", 120)
                await self.emit_progress(
                    updater,
                    "collaboration-progress",
                    event="collab_own_task_done",
                    message=(
                        f"Task #{t.id} done: [{agent_name}] {_own_done_desc} "
                        f"({len(result or '')} chars)"
                    ),
                    status="done",
                    task_id=t.id,
                    extra={
                        "task_id": t.id,
                        "agent": agent_name,
                        "plan_index": plan_idx + 1,
                        "desc_preview": _own_done_desc,
                        "result_chars": len(result or ""),
                    },
                )
                logger.info(
                    "[Cross-SG][CollabExecuteOwn] task complete | plan_idx=%d task_id=%d agent=%s result_chars=%d result_preview=%s",
                    plan_idx,
                    t.id,
                    agent_name,
                    len(result or ""),
                    (result or "")[:5000],
                )
                continue

            # --- Route C: 委托给协作 SG ---
            if agent_name in collaborator_names:
                _target_card = next((c for c in collaborator_cards if c.name == agent_name), None)
                if _target_card is None:
                    logger.warning(
                        "[Cross-SG][CollabPreExecDelegation] no card found for target=%s, skip", agent_name,
                    )
                    continue
                _can_delegate = current_hop > 1
                if _can_delegate:
                    _delegation_executed_count += 1
                    # Consume 1 hop for this delegation edge.
                    current_hop -= 1
                    _next_hop = current_hop
                    _new_chain = delegation_chain + [agent.agent_name]

                    _task_desc_for_delegate = t.description or ""
                    if self._llm_dependent_query_refine_enabled() and t.depends_on:
                        _deps = list(t.depends_on)
                        if all(
                            tid in _all_task_results and (_all_task_results.get(tid) or "").strip()
                            for tid in _deps
                        ):
                            _upstream_blob = "\n\n".join(
                                f"=== Task #{tid} （上游已成功执行的结果）===\n{(_all_task_results.get(tid) or '').strip()}"
                                for tid in sorted(_deps)
                            )
                            _task_desc_for_delegate = await self._llm_refine_dependent_task_query(
                                original_query=query,
                                planned_downstream_description=t.description or "",
                                downstream_agent_name=agent_name,
                                upstream_results_blob=_upstream_blob,
                                user_id=user_id,
                                run_id=run_id,
                                trace_id=trace_id,
                                refine_stage="pre_delegate_sg",
                            )
                            # --- 上游数据无效：跳过当前委托任务 ---
                            if _task_desc_for_delegate.startswith(DEPENDENT_TASK_SKIP_MARKER):
                                logger.info(
                                    "[Cross-SG][CollabPreExecDelegation] task_id=%s skipped — "
                                    "upstream data invalid, cancelling delegation to %s",
                                    t.id,
                                    agent_name,
                                )
                                self._log_data_flow(
                                    direction="TASK_SKIPPED",
                                    description=f"Task #{t.id} skipped — upstream dep returned no usable data for {agent_name}",
                                    source_id="planner",
                                    target_id=agent_name,
                                    metadata_extra={
                                        "task_id": t.id,
                                        "reason": "upstream_no_data",
                                        "depends_on": t.depends_on if t.depends_on else [],
                                    },
                                )
                                delegated_results[agent_name] = _task_desc_for_delegate
                                _all_task_results[t.id] = _task_desc_for_delegate
                                continue
                        else:
                            logger.info(
                                "[Cross-SG][CollabPreExecDelegation] skip dependent-query refine "
                                "| task_id=%s missing_prior_results deps=%s",
                                t.id,
                                _deps,
                            )

                    # Build upstream context with only completed results (not "delegated" placeholders)
                    _completed_tasks_context = [
                        {
                            "task_id": tid,
                            "description": "",
                            "agent": "",
                            "status": "completed",
                            "result": res,
                        }
                        for tid, res in _all_task_results.items() if res
                    ]
                    _ctx: dict[str, Any] = {
                        "delegator_plan": [pt.model_dump() for pt in plan.tasks],
                        "executed_tasks": _completed_tasks_context,
                        "key_findings_so_far": "\n".join(
                            f"[Task#{tid}] {res[:300]}"
                            for tid, res in _all_task_results.items() if res
                        ),
                        "remaining_tasks": [dt.model_dump() for dt in delegation_tasks],
                        "upstream_context": upstream_context,
                    }
                    # --- Data Flow: upstream context being packed for delegation ---
                    _ctx_chars = len(json.dumps(_ctx, ensure_ascii=False))
                    self._log_data_flow(
                        direction="PRE_DELEGATE_SEND",
                        description=f"委派给 [{agent_name}] — 构造 upstream_context",
                        source_id=agent.agent_name or "?",
                        target_id=agent_name,
                        payload_chars=_ctx_chars,
                        payload_preview=(
                            f"delegator_plan (tasks={len(plan.tasks)}), "
                            f"executed_tasks (count={len(_completed_tasks_context)}), "
                            f"key_findings_so_far ({len(_ctx.get('key_findings_so_far','') or '')} chars), "
                            f"remaining_tasks (count={len(delegation_tasks)})"
                        ),
                        metadata_extra={
                            "delegation_chain": _new_chain,
                            "hop_remaining": _next_hop,
                            "task_description": (_task_desc_for_delegate[:200] if _task_desc_for_delegate else ""),
                            "llm_dependency_refined": (_task_desc_for_delegate != (t.description or "").strip()),
                        },
                    )
                    _pre_delegate_desc = self._truncate_progress_message(
                        _task_desc_for_delegate or t.description or "", 120,
                    )
                    await self.emit_progress(
                        updater,
                        "collaboration-progress",
                        event="collab_pre_delegating",
                        message=(
                            f"Pre-exec delegating Task #{t.id} to [{agent_name}] "
                            f"(plan #{plan_idx + 1}/{len(plan.tasks)}): {_pre_delegate_desc}"
                        ),
                        status="running",
                        task_id=t.id,
                        extra={
                            "target_sg": agent_name,
                            "task_id": t.id,
                            "remaining_hop": _next_hop,
                            "plan_index": plan_idx + 1,
                            "desc_preview": _pre_delegate_desc,
                            "planned_task_desc_preview": self._truncate_progress_message(
                                t.description or "", 120,
                            ),
                        },
                    )
                    logger.info(
                        "[Cross-SG][CollabPreExecDelegation] delegating task | plan_idx=%d target_sg=%s hop=%d chain=%s desc_preview=%s",
                        plan_idx,
                        agent_name,
                        _next_hop,
                        _new_chain,
                        _task_desc_for_delegate[:100] if _task_desc_for_delegate else "",
                    )
                    result = await agent.delegate_to_collaborator_sg(
                        target_card=_target_card,
                        task_description=_task_desc_for_delegate,
                        user_id=user_id,
                        run_id=run_id,
                        trace_id=trace_id,
                        hop_remaining=_next_hop,
                        delegation_chain=_new_chain,
                        upstream_context=_ctx,
                        progress_updater=updater,
                        progress_artifact_name="collaboration-progress",
                    )
                    delegated_results[agent_name] = result
                    # 写入 _all_task_results，使得后续依赖此 delegation task 的 own 任务能访问到结果
                    _all_task_results.setdefault(t.id, "")
                    _all_task_results[t.id] = result
                    # --- Data Flow: delegation result received ---
                    self._log_data_flow(
                        direction="PRE_DELEGATE_RECV",
                        description=f"委派 [{agent_name}] 结果返回 → delegated_results 字典",
                        source_id=agent_name,
                        target_id=agent.agent_name or "?",
                        payload_chars=len(result or ""),
                        payload_preview=(result or "")[:1000],
                        metadata_extra={"hop_used": _next_hop, "chain": _new_chain},
                    )

                    logger.info(
                        "[Cross-SG][CollabPreExecDelegation] delegation returned | plan_idx=%d target_sg=%s result_chars=%d",
                        plan_idx,
                        agent_name,
                        len(result or ""),
                    )
                    await self.emit_progress(
                        updater,
                        "collaboration-progress",
                        event="collab_pre_delegation_done",
                        message=(
                            f"Pre-exec Task #{t.id} done via [{agent_name}]: {_pre_delegate_desc} "
                            f"({len(result or '')} chars)"
                        ),
                        status="done",
                        task_id=t.id,
                        extra={
                            "target_sg": agent_name,
                            "task_id": t.id,
                            "plan_index": plan_idx + 1,
                            "desc_preview": _pre_delegate_desc,
                            "result_chars": len(result or ""),
                        },
                    )
                else:
                    skipped_delegation_agents.add(agent_name)
                    _skipped_desc = self._truncate_progress_message(t.description or "", 120)
                    await self.emit_progress(
                        updater,
                        "collaboration-progress",
                        event="collab_pre_delegation_skipped",
                        message=(
                            f"Pre-exec Task #{t.id} skipped (hop exhausted): "
                            f"[{agent_name}] {_skipped_desc}"
                        ),
                        status="done",
                        task_id=t.id,
                        extra={
                            "target_sg": agent_name,
                            "task_id": t.id,
                            "plan_index": plan_idx + 1,
                            "desc_preview": _skipped_desc,
                            "reason": "hop_exhausted",
                        },
                    )
                    logger.info(
                        "[Cross-SG][CollabPreExecDelegation] hop exhausted, cannot delegate | target_sg=%s",
                        agent_name,
                    )
                    delegated_results[agent_name] = NONE_TASK_DESCRIPTION

        # ---- 执行进度汇总 ----
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_own_all_done",
            message=f"All {len(_all_task_results)} results accumulated (own: {_own_executed_count}, delegated: {_delegation_executed_count})",
            status="done",
            extra={
                "completed_count": len(_all_task_results),
                "own_executed": _own_executed_count,
                "delegation_executed": _delegation_executed_count,
            },
        )
        logger.info(
            "[Cross-SG][CollabExecuteOwn] all tasks done | accumulated_results=%d own=%d delegated=%d",
            len(_all_task_results),
            _own_executed_count,
            _delegation_executed_count,
        )

        # ---- 构造 own_task_context（用于后续 mid-exec 和 summary） ----
        # 只包含真正已执行完成的任务，不包含尚未执行的未完成占位符
        own_task_context = [
            {
                "task_id": tid,
                "description": "",
                "agent": "",
                "status": "completed",
                "result": res,
            }
            for tid, res in _all_task_results.items() if res
        ]

        if skipped_delegation_agents:
            logger.info(
                "[Cross-SG][CollabPreExecDelegation] %d delegation task(s) skipped due to hop exhausted: %s",
                len(skipped_delegation_agents),
                sorted(skipped_delegation_agents),
            )
        if len(delegation_tasks) == 0:
            pre_exec_msg = "No tasks to delegate"
        elif len(delegated_results) < len(delegation_tasks):
            pre_exec_msg = f"Delegation complete: {len(delegated_results)}/{len(delegation_tasks)} results returned"
        else:
            pre_exec_msg = f"Delegation complete: all {len(delegated_results)} results returned"
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_pre_delegations_all_done",
            message=pre_exec_msg,
            status="done",
            extra={
                "total_count": len(delegation_tasks),
                "result_count": len(delegated_results),
            },
        )
        logger.info(
            "[Cross-SG][CollabPreExecDelegation] all pre-exec delegations complete | total=%d results=%d",
            len(delegation_tasks),
            len(delegated_results),
        )

        # ---- mid-execution: 递归检测 + 规划 + 派发 ----
        # Guard: if hop is already exhausted, skip mid-exec entirely.
        if current_hop <= 1:
            logger.info("[Cross-SG][CollabMidExecLoop] hop exhausted (current_hop=%d), skipping mid-exec loop", current_hop)
            await self._emit_collab_mid_exec_loop_done(
                updater,
                total_rounds=0,
                total_delegated=len(delegated_results),
            )
            return _all_task_results, delegated_results

        mid_exec_round = 0
        max_mid_exec_rounds = int(os.getenv("CROSS_SG_MID_EXEC_ROUNDS", "3"))
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_mid_exec_loop_started",
            message=f"Mid-execution loop starting (max {max_mid_exec_rounds} rounds)",
            status="running",
            extra={
                "max_rounds": max_mid_exec_rounds,
            },
        )
        logger.info(
            "[Cross-SG][CollabMidExecLoop] mid-execution loop starting | max_rounds=%d",
            max_mid_exec_rounds,
        )
        while mid_exec_round < max_mid_exec_rounds:
            # Guard: if hop is exhausted, no further delegation is possible.
            # Skip remaining rounds to avoid wasting LLM calls (detect, select,
            # plan) when dispatch will only produce NONE_TASK_DESCRIPTION.
            if current_hop <= 1:
                logger.info(
                    "[Cross-SG][CollabMidExecLoop] hop exhausted "
                    "(current_hop=%d) at round %d, exiting mid-exec loop",
                    current_hop,
                    mid_exec_round + 1,
                )
                await self.emit_progress(
                    updater,
                    "collaboration-progress",
                    event="collab_mid_exec_hop_exhausted",
                    message=(
                        f"Mid-exec hop exhausted, skipping remaining "
                        f"rounds ({mid_exec_round + 1}/{max_mid_exec_rounds})"
                    ),
                    status="done",
                    extra={
                        "round": mid_exec_round + 1,
                        "max_rounds": max_mid_exec_rounds,
                        "hop": current_hop,
                    },
                )
                break

            # Routing peer pool may be empty (sole can_handle root). Mid-exec
            # must still discover remote SGs via registry broadcast — do not
            # exit with rounds=0 just because routing_agent_pool had no peers.
            if not collaborator_cards:
                collaborator_cards = await self._load_mid_exec_broadcast_candidates()
                if not collaborator_cards:
                    logger.info(
                        "[Cross-SG][CollabMidExecLoop] no broadcast SG candidates "
                        "in registry; exiting mid-exec loop"
                    )
                    break
                logger.info(
                    "[Cross-SG][CollabMidExecLoop] peer pool empty; loaded "
                    "broadcast candidates | count=%d names=%s",
                    len(collaborator_cards),
                    [getattr(c, "name", "") for c in collaborator_cards[:12]],
                )

            logger.info(
                "[Cross-SG][CollabMidExecLoop] round %d / %d started",
                mid_exec_round + 1,
                max_mid_exec_rounds,
            )
            await self.emit_progress(
                updater,
                "collaboration-progress",
                event="collab_mid_exec_round",
                message=f"Mid-execution round {mid_exec_round + 1}/{max_mid_exec_rounds} started",
                status="running",
                extra={
                    "round": mid_exec_round + 1,
                    "max_rounds": max_mid_exec_rounds,
                },
            )

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
                await self.emit_progress(
                    updater,
                    "collaboration-progress",
                    event="collab_mid_detect_none",
                    message="Mid-execution detection: no further delegation needed",
                    status="done",
                )
                logger.info("[Cross-SG][CollabMidExecLoop] no further delegation needed, exiting loop")
                await self._emit_collab_mid_round_done(
                    updater,
                    round_num=mid_exec_round + 1,
                    max_rounds=max_mid_exec_rounds,
                    total_delegated=len(delegated_results),
                    early_exit="no further delegation needed",
                )
                break

            synthesized_query = detection.get("synthesized_query", "")
            soft_target_hints = list(detection.get("target_sgs") or [])
            # Filter out LLM-hallucinated agent names that don't exist in collaborator pool
            if soft_target_hints and collaborator_cards:
                valid_names = {c.name for c in collaborator_cards if getattr(c, "name", "")}
                soft_target_hints = [n for n in soft_target_hints if n in valid_names]
            reason = detection.get("reason", "")
            detection_source = detection.get("source") or "llm_detection"
            skipped_owners = detection.get("skipped_owners") or []
            await self.emit_progress(
                updater,
                "collaboration-progress",
                event="collab_mid_detect_result",
                message=(
                    f"Mid-execution detection ({detection_source}): gap found; "
                    f"soft_hints={', '.join(soft_target_hints) or '(none)'}; "
                    f"reason: {(reason or '')[:80]}"
                ),
                status="running",
                extra={
                    "needs_help": True,
                    "soft_target_hints": soft_target_hints,
                    "reason_preview": (reason or "")[:120],
                    "detection_source": detection_source,
                    "structured_unfulfilled_needs": detection.get("structured_unfulfilled_needs") or [],
                    "skipped_owners": skipped_owners,
                },
            )
            if not synthesized_query:
                logger.info(
                    "[Cross-SG][CollabMidExecDetect] detection returned empty synthesized_query, exiting loop"
                )
                await self._emit_collab_mid_round_done(
                    updater,
                    round_num=mid_exec_round + 1,
                    max_rounds=max_mid_exec_rounds,
                    total_delegated=len(delegated_results),
                    early_exit="empty detection query",
                )
                break

            # Step 1.5: authoritative remote SG selection via one-shot concurrent
            # capability_check over the full broadcast pool. Soft hints from
            # detect only rank ties / empty-result fallback — never a sequential
            # first-probe gate.
            hints_by_sg: dict[str, dict] = {}
            capability_evidence = ""
            if self._mid_delegate_capability_select_enabled():
                logger.info(
                    "[Cross-SG][CollabMidExecLoop] selecting mid-delegate targets "
                    "via concurrent capability_check | soft_hints=%s",
                    soft_target_hints[:10],
                )
                selection = await self._select_mid_delegate_targets_via_capability(
                    synthesized_query=synthesized_query,
                    collaborator_cards=collaborator_cards,
                    soft_target_hints=soft_target_hints,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    get_response_text=getattr(agent, "get_response_text", None),
                )
                target_cards = list(selection.get("target_cards") or [])
                target_sg_names = list(selection.get("target_sg_names") or [])
                hints_by_sg = dict(selection.get("hints_by_sg") or {})
                capability_evidence = str(selection.get("evidence_text") or "")
                await self.emit_progress(
                    updater,
                    "collaboration-progress",
                    event="collab_mid_capability_select",
                    message=(
                        f"Mid-exec capability_check selected: "
                        f"{', '.join(target_sg_names) or '(none)'}"
                    ),
                    status="running",
                    extra={
                        "target_sgs": target_sg_names,
                        "soft_target_hints": soft_target_hints,
                        "probed_names": selection.get("probed_names") or [],
                        "with_execution_hint": list(hints_by_sg.keys()),
                    },
                )
                if not target_cards:
                    logger.info(
                        "[Cross-SG][CollabMidExecLoop] capability_check found no "
                        "capable remote SG, exiting loop | soft_hints=%s probed=%s",
                        soft_target_hints[:10],
                        (selection.get("probed_names") or [])[:12],
                    )
                    await self._emit_collab_mid_round_done(
                        updater,
                        round_num=mid_exec_round + 1,
                        max_rounds=max_mid_exec_rounds,
                        total_delegated=len(delegated_results),
                        early_exit="no capable remote SG from capability_check",
                    )
                    break
            else:
                # Legacy fallback: name-filter collaborator cards by detect hints.
                target_sg_names = soft_target_hints
                target_cards = [c for c in collaborator_cards if c.name in target_sg_names]
                logger.warning(
                    "[Cross-SG][CollabMidExecLoop] capability select disabled; "
                    "legacy name-filter targets=%s",
                    target_sg_names,
                )
                if not target_sg_names or not target_cards:
                    logger.info(
                        "[Cross-SG][CollabMidExecDetect] legacy path empty targets, exiting loop"
                    )
                    await self._emit_collab_mid_round_done(
                        updater,
                        round_num=mid_exec_round + 1,
                        max_rounds=max_mid_exec_rounds,
                        total_delegated=len(delegated_results),
                        early_exit="empty detection targets or query",
                    )
                    break

            # Build execution context for this mid-exec round
            # 只包含真正已执行完成的任务
            own_task_context = [
                {
                    "task_id": tid,
                    "description": "",
                    "agent": "",
                    "status": "completed",
                    "result": res,
                }
                for tid, res in _all_task_results.items() if res
            ]
            key_findings_so_far = "\n".join(
                f"[Task#{tid}] {res[:300]}"
                for tid, res in _all_task_results.items() if res
            )

            # Merge upstream_context with current execution results so the Planner
            # sees both what was done before (upstream) and what this SG just did
            mid_upstream: dict[str, Any] = dict(upstream_context)
            mid_upstream["delegator_plan"] = [t.model_dump() for t in plan.tasks]
            mid_upstream["executed_tasks"] = own_task_context
            mid_upstream["key_findings_so_far"] = key_findings_so_far

            mid_group_memory = self._enrich_group_memory_with_upstream(
                upstream_context=mid_upstream,
                base_group_memory=group_memory,
                extra_context={
                    "already_delegated": [
                        {"target_sg": name, "result": result or ""}
                        for name, result in delegated_results.items() if result
                    ],
                    "synthesized_query": synthesized_query,
                    "detection_reason": reason,
                    # Inject capability evidence so planner does not rely on
                    # generic peer card descriptions.
                    "capability_check_evidence": capability_evidence,
                },
            )
            if capability_evidence:
                mid_group_memory = (
                    f"{mid_group_memory}\n\n{capability_evidence}"
                    if mid_group_memory
                    else capability_evidence
                )

            logger.info(
                "[Cross-SG][CollabMidExecPlan] planning mid-exec delegation | "
                "targets=%s synth_query_len=%d evidence_chars=%d",
                target_sg_names,
                len(synthesized_query or ""),
                len(capability_evidence or ""),
            )

            mid_plan = await self._plan_mid_exec_delegation(
                synthesized_query=synthesized_query,
                target_cards=target_cards,
                group_memory=mid_group_memory,
                agent=agent,
                skill_runner=skill_runner,
            )
            if mid_plan is None:
                logger.warning("[Cross-SG][CollabMidExecPlan] mid-exec plan returned None")
                await self._emit_collab_mid_round_done(
                    updater,
                    round_num=mid_exec_round + 1,
                    max_rounds=max_mid_exec_rounds,
                    total_delegated=len(delegated_results),
                    early_exit="mid-exec plan failed",
                )
                break

            logger.info(
                "[Cross-SG][CollabMidExecPlan] mid-exec plan produced | task_count=%d agents=%s",
                len(mid_plan.tasks),
                [t.agent for t in mid_plan.tasks],
            )
            _mid_plan_lines = [
                f"Mid-exec plan ready (round {mid_exec_round + 1}): "
                f"{len(mid_plan.tasks)} tasks for {', '.join(target_sg_names)}",
            ]
            for _mt in mid_plan.tasks:
                _m_agent = (_mt.agent or "").strip() or "?"
                _m_desc = self._truncate_progress_message(_mt.description or "", 140)
                _m_deps = (
                    f"(depends on: [{', '.join(str(d) for d in _mt.depends_on)}]) "
                    if _mt.depends_on else ""
                )
                _mid_plan_lines.append(f"  • #{_mt.id} {_m_deps}agent='{_m_agent}' | {_m_desc}")
            await self.emit_progress(
                updater,
                "collaboration-progress",
                event="collab_mid_plan_ready",
                message="\n".join(_mid_plan_lines),
                status="running",
                extra={
                    "task_count": len(mid_plan.tasks),
                    "agents": [t.agent for t in mid_plan.tasks],
                    "mid_exec_round": mid_exec_round + 1,
                },
            )

            # Step 3: dispatch
            upstream_ctx: dict[str, Any] = dict(mid_upstream)
            upstream_ctx.update({
                "already_delegated": [
                    {"target_sg": name, "result": result or ""}
                    for name, result in delegated_results.items() if result
                ],
                "mid_exec_round": mid_exec_round + 1,
                "synthesized_query": synthesized_query,
                "detection_reason": reason,
            })
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
                agent=agent,
                progress_updater=updater,
                collaboration_original_query=query,
                execution_hints_by_sg=hints_by_sg,
            )
            # --- Data Flow: mid-exec round dispatch ---
            _mid_ctx_chars = len(json.dumps(upstream_ctx, ensure_ascii=False))
            self._log_data_flow(
                direction="MID_DISPATCH_SEND",
                description=f"Mid-exec R{mid_exec_round+1} 委派出参 → 目标 SGs {target_sg_names}",
                source_id=agent.agent_name or "?",
                target_id=", ".join(target_sg_names) or "?",
                payload_chars=_mid_ctx_chars,
                payload_preview=(
                    f"已委托: {len(delegated_results)} 条, "
                    f"synthesized_query: {(synthesized_query or '')[:200]}"
                ),
                metadata_extra={
                    "mid_exec_round": mid_exec_round + 1,
                    "delegation_chain": delegation_chain,
                },
            )
            for sg_name, result in mid_results.items():
                delegated_results.setdefault(sg_name, "")
                delegated_results[sg_name] = result
                # --- Data Flow: mid-exec result received ---
                self._log_data_flow(
                    direction="MID_DISPATCH_RECV",
                    description=f"Mid-exec 委派 [{sg_name}] 结果返回 → delegated_results 字典",
                    source_id=sg_name or "?",
                    target_id=agent.agent_name or "?",
                    payload_chars=len(result or ""),
                    payload_preview=(result or "")[:1000],
                )

                logger.info(
                    "[Cross-SG][CollabMidExecDispatch] dispatch returned | target_sg=%s result_chars=%d",
                    sg_name,
                    len(result or ""),
                )

            # Consume hop for each actual delegation that happened in this round.
            _actual_mid_delegations = sum(
                1 for v in mid_results.values()
                if v and v != NONE_TASK_DESCRIPTION
            )
            current_hop -= _actual_mid_delegations

            mid_exec_round += 1

            logger.info(
                "[Cross-SG][CollabMidExecLoop] round %d complete | total_delegated=%d",
                mid_exec_round,
                len(delegated_results),
            )
            await self._emit_collab_mid_round_done(
                updater,
                round_num=mid_exec_round,
                max_rounds=max_mid_exec_rounds,
                total_delegated=len(delegated_results),
            )

        logger.info(
            "[Cross-SG][CollabMidExecLoop] mid-execution loop finished | rounds=%d total_delegated=%d",
            mid_exec_round,
            len(delegated_results),
        )
        await self._emit_collab_mid_exec_loop_done(
            updater,
            total_rounds=mid_exec_round,
            total_delegated=len(delegated_results),
        )

        # ---- Step 4: summary ----
        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_summarizing",
            message=f"Summarizing results: {len(own_results)} own + {len(delegated_results)} delegated",
            status="running",
            extra={
                "own_result_count": len(own_results),
                "delegated_result_count": len(delegated_results),
            },
        )
        logger.info(
            "[Cross-SG][CollabSummary] generating final summary | own_results=%d delegated_results=%d",
            len(own_results),
            len(delegated_results),
        )
        # --- Data Flow: summary input aggregation ---
        _summary_input_chars = sum(len(v or "") for v in own_results.values()) + sum(
            len(v or "") for v in delegated_results.values()
        )
        _own_snippets = []
        for _tid, _res in own_results.items():
            _snip = (_res or "").replace("\n", " ").strip()[:120]
            _own_snippets.append(f"#{_tid}: {_snip}")
        _own_preview = "\n".join(_own_snippets) if _own_snippets else "(none)"
        _del_snippets = []
        for _name, _res in delegated_results.items():
            _snip = (_res or "").replace("\n", " ").strip()[:120]
            _del_snippets.append(f"[{_name}]: {_snip}")
        _del_preview = "\n".join(_del_snippets) if _del_snippets else "(none)"
        self._log_data_flow(
            direction="SUMMARY_INPUT",
            description=f"聚合 {len(own_results)} 项 own_results + {len(delegated_results)} 项 delegated_results → 送入 Summary LLM",
            source_id=agent.agent_name or "?",
            target_id="SummaryLLM",
            payload_chars=_summary_input_chars,
            payload_preview=(
                f"own_results:\n{_own_preview}\n\ndelegated_results:\n{_del_preview}"
            ),
            metadata_extra={
                "own_result_chars": sum(len(v or "") for v in own_results.values()),
                "delegated_result_chars": sum(len(v or "") for v in delegated_results.values()),
            },
        )
        summary = await self._summarize_delegated_result(
            query=query,
            own_results=own_results,
            delegated_results=delegated_results,
            upstream_context=upstream_context,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
        )

        await self.emit_progress(
            updater,
            "collaboration-progress",
            event="collab_done",
            message=f"Collaborative execution complete, final summary {len(summary or '')} chars",
            status="done",
            extra={
                "result_chars": len(summary or ""),
            },
        )
        logger.info(
            "[Cross-SG][CollabSummary] final summary ready | result_chars=%d",
            len(summary or ""),
        )
        # --- Data Flow: summary output ---
        self._log_data_flow(
            direction="SUMMARY_OUTPUT",
            description=f"Summary LLM 产出最终回答 → 返回 {agent.agent_name}",
            source_id="SummaryLLM",
            target_id=agent.agent_name or "?",
            payload_chars=len(summary or ""),
            payload_preview=(summary or "")[:1000],
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
        user_id: str,
        run_id: str,
        trace_id: str,
        updater: TaskUpdater,
        agent,
        prior_task_results: dict[int, str] | None = None,
        collaboration_original_query: str = "",
    ) -> str:
        """Execute a single own task by forwarding it to the matching Expert Agent.

        Pure A2A dispatch — no SQL generation, DB queries, or knowledge retrieval.
        When the task is routed to the synthetic LocalSkill card, the local
        SkillRunner executes it in-process instead.

        ``prior_task_results`` contains results from dependency tasks that must
        complete before this one.  Their text is prepended to the task description
        so the downstream Expert Agent can use upstream data (user IDs, token lists,
        etc.) without guessing.
        """
        if (task.agent or "").strip().upper() == "NONE":
            return NONE_TASK_DESCRIPTION

        # Route B: local skill execution (in-process, no A2A).
        if agent._is_local_skill_task(task):
            return await self._execute_local_skill_task(
                task, user_id, run_id, trace_id, updater, agent,
                prior_task_results=prior_task_results,
                collaboration_original_query=collaboration_original_query,
            )

        agent_card = next(
            (c for c in (agent.agent_cards or []) if c.name == task.agent),
            None,
        )
        if agent_card is None:
            logger.warning(
                "[Cross-SG][CollabExecuteOwn] no card for agent=%s, returning empty", task.agent,
            )
            return ""

        logger.info(
            "[Cross-SG][CollabExecuteOwn] A2A call to agent | agent=%s url=%s",
            task.agent,
            agent_card.url,
        )

        prior = prior_task_results or {}
        _message_body = task.description or ""
        if self._llm_dependent_query_refine_enabled() and task.depends_on:
            _deps = list(task.depends_on)
            if all(tid in prior and (prior.get(tid) or "").strip() for tid in _deps):
                _refine_blob = "\n\n".join(
                    f"=== Task #{tid} （上游已成功执行的结果）===\n{(prior.get(tid) or '').strip()}"
                    for tid in sorted(_deps)
                )
                _message_body = await self._llm_refine_dependent_task_query(
                    original_query=(collaboration_original_query or "").strip(),
                    planned_downstream_description=task.description or "",
                    downstream_agent_name=task.agent or "",
                    upstream_results_blob=_refine_blob,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    refine_stage="own_expert",
                )
                # --- 上游数据无效：跳过当前依赖任务 ---
                if _message_body.startswith(DEPENDENT_TASK_SKIP_MARKER):
                    logger.info(
                        "[Cross-SG][OwnExpertDependRefine] task_id=%s skipped — upstream data invalid | "
                        "skip_reason=%s",
                        task.id,
                        _message_body[len(DEPENDENT_TASK_SKIP_MARKER):],
                    )
                    self._log_data_flow(
                        direction="TASK_SKIPPED",
                        description=f"Task #{task.id} skipped — upstream dependency returned no usable data",
                        source_id="planner",
                        target_id=task.agent or "?",
                        metadata_extra={
                            "task_id": task.id,
                            "reason": "upstream_no_data",
                            "depends_on": task.depends_on if task.depends_on else [],
                        },
                    )
                    return _message_body
                logger.info(
                    "[Cross-SG][OwnExpertDependRefine] task_id=%s refined_chars=%d",
                    task.id,
                    len(_message_body or ""),
                )
            else:
                logger.info(
                    "[Cross-SG][OwnExpertDependRefine] skip refine task_id=%s deps=%s "
                    "| missing non-empty prior for some dependency",
                    task.id,
                    _deps,
                )

        # ── Package prior-task results into metadata.upstream_context ──
        # (NOT injected into the task description – keeps the A2A message body pure)
        _upstream_executed_tasks: list[dict] = []
        _packaged_task_ids: list[int] = []
        if prior:
            completed_tids = sorted(tid for tid, res in prior.items() if res)
            for _tid in completed_tids:
                _upstream_executed_tasks.append({
                    "task_id": _tid,
                    "description": "",
                    "agent": task.agent,
                    "status": "completed",
                    "result": prior[_tid],
                })
            _packaged_task_ids = completed_tids
            if _upstream_executed_tasks:
                _inject_summary = (
                    f"前置任务已完成 ({len(_upstream_executed_tasks)}): "
                    f"{_packaged_task_ids} — 完整结果在 metadata.upstream_context.executed_tasks 中"
                )
                logger.info(
                    "[Cross-SG][CollabExecuteOwn] packaging prior results as upstream_context | task_id=%d "
                    "depends_on=%s completed_context_count=%d "
                    "task_desc_chars=%d",
                    task.id,
                    task.depends_on if task.depends_on else [],
                    len(completed_tids),
                    len(task.description or ""),
                )
                # --- Data Flow: prior context packaging (metadata, NOT task description) ---
                self._log_data_flow(
                    direction="PRIOR_INJECT",
                    description=f"Task #{task.id} 打包 {len(_upstream_executed_tasks)} 个前置任务结果 → metadata.upstream_context.executed_tasks",
                    source_id="own_results (已完成任务)",
                    target_id=f"{task.agent or '?'} (task #{task.id} 的 downstream expert)",
                    payload_chars=sum(len(r.get("result", "")) for r in _upstream_executed_tasks),
                    payload_preview=_inject_summary,
                    metadata_extra={
                        "injected_task_ids": _packaged_task_ids,
                        "depends_on": task.depends_on if task.depends_on else [],
                    },
                )

        _current_tasks_status: list[dict] = []
        if prior:
            for _tid, _res in sorted(prior.items()):
                _ts = {
                    "id": _tid,
                    "description": "",
                    "agent": task.agent,
                    "answer": _res or "",
                    "status": "completed" if _res else "unknown",
                }
                _current_tasks_status.append(_ts)
        current_tasks_status_json = json.dumps(_current_tasks_status)

        # ── upstream_context for the downstream expert (own expert or peer SG) ──
        _a2a_upstream_context: dict = {}
        if _upstream_executed_tasks:
            _a2a_upstream_context = {"executed_tasks": _upstream_executed_tasks}

        send_payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": _message_body}],
                "messageId": uuid4().hex,
            },
            "metadata": {
                "user_id": user_id,
                "run_id": run_id,
                "trace_id": trace_id,
                PROPAGATED_HISTORY_KEY: parse_propagated_history(
                    (agent.metadata or {}).get(PROPAGATED_HISTORY_KEY),
                ),
                "current_tasks_status": current_tasks_status_json,
                "current_task": (
                    f"current task id: [{task.id}], task description: {_message_body} "
                ),
                "current_task_id": str(task.id),
                "answer_model": OrchestratorAgent._downstream_answer_model_for_a2a(
                    task.agent or "",
                    agent_card,
                ),
                "skip_history_write": True,
                "upstream_context": _a2a_upstream_context,
            },
        }
        execution_hint = self._validated_execution_hint(
            agent.metadata if isinstance(agent.metadata, dict) else {},
            collaboration_original_query or _message_body,
        )
        if execution_hint:
            send_payload["metadata"][SG_EXECUTION_HINT_KEY] = execution_hint
            # Also nest under propagated_history so SD can recover the hint if
            # some A2A transports drop top-level extension metadata keys.
            hist = dict(send_payload["metadata"].get(PROPAGATED_HISTORY_KEY) or {})
            hist[SG_EXECUTION_HINT_KEY] = execution_hint
            send_payload["metadata"][PROPAGATED_HISTORY_KEY] = hist
            logger.info(
                "[Capability][ExecutionHint] forwarded to SG Expert | "
                "selected=%s strategy=%s",
                (execution_hint.get("selected_members") or [])[:10],
                execution_hint.get("execution_strategy") or "single",
            )
        # Same artifact task name as OrchestratorAgentExecutor.a2a_tasks so RoutingAgent
        # sees sg_expert / nested progress in the same stream channel.
        task_progress_name = f"{agent.agent_name}-result"
        # --- Data Flow: expert A2A call (body may be LLM-refined when depends_on; context in metadata) ---
        _a2a_message_text = _message_body
        self._log_data_flow(
            direction="A2A_SEND",
            description=f"Task #{task.id} → 调用 Expert Agent: {task.agent} ({agent_card.url})",
            source_id=agent.agent_name or "?",
            target_id=f"{task.agent or '?'} ({agent_card.url})",
            payload_chars=len(_a2a_message_text),
            payload_preview=_a2a_message_text[:1000],
            metadata_extra={
                "task_id": task.id,
                "current_tasks_status_count": len(_current_tasks_status),
                "upstream_task_ids": _packaged_task_ids if _packaged_task_ids else [],
            },
        )
        _a2a_timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(_a2a_timeout, connect=10.0)) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            req = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_payload),
            )
            stream = client.send_message_streaming(req)
            return await OrchestratorAgent.stream_a2a_collect_forward_progress_frames(
                stream,
                agent.get_response_text,
                updater,
                task_progress_name,
            )

    async def _execute_local_skill_task(
        self,
        task: PlannerTask,
        user_id: str,
        run_id: str,
        trace_id: str,
        updater: TaskUpdater,
        agent,
        prior_task_results: dict[int, str] | None = None,
        collaboration_original_query: str = "",
    ) -> str:
        """Execute a task routed to the synthetic LocalSkill card in-process."""
        prior = prior_task_results or {}
        _run_query = task.description or ""
        if self._llm_dependent_query_refine_enabled() and task.depends_on:
            _deps = list(task.depends_on)
            if all(tid in prior and (prior.get(tid) or "").strip() for tid in _deps):
                _refine_blob = "\n\n".join(
                    f"=== Task #{tid} （上游已成功执行的结果）===\n{(prior.get(tid) or '').strip()}"
                    for tid in sorted(_deps)
                )
                _run_query = await self._llm_refine_dependent_task_query(
                    original_query=(collaboration_original_query or "").strip(),
                    planned_downstream_description=task.description or "",
                    downstream_agent_name="LocalSkill",
                    upstream_results_blob=_refine_blob,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    refine_stage="local_skill",
                )
                if _run_query.startswith(DEPENDENT_TASK_SKIP_MARKER):
                    logger.info(
                        "[Cross-SG][LocalSkillDependRefine] task_id=%s skipped — upstream data invalid",
                        task.id,
                    )
                    return _run_query
                logger.info(
                    "[Cross-SG][LocalSkillDependRefine] task_id=%s refined_chars=%d",
                    task.id,
                    len(_run_query or ""),
                )
            else:
                logger.info(
                    "[Cross-SG][LocalSkillDependRefine] skip refine task_id=%s deps=%s",
                    task.id,
                    list(task.depends_on),
                )

        logger.info(
            "[Cross-SG][CollabExecuteOwn] local skill execution | task_id=%d desc_preview=%s",
            task.id,
            (_run_query or "")[:120],
        )
        try:
            result = await agent.skill_runner.plan_and_run(
                query=_run_query,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
            final_answer = str(result.get("final_answer") or "").strip()
            logger.info(
                "[Cross-SG][CollabExecuteOwn] local skill done | task_id=%d status=%s skill=%s result_chars=%d",
                task.id,
                result.get("status"),
                result.get("skill", ""),
                len(final_answer),
            )
            return final_answer
        except Exception as exc:
            logger.exception(
                "[Cross-SG][CollabExecuteOwn] local skill failed for task_id=%d: %s",
                task.id, exc,
            )
            return f"LocalSkill execution error: {exc}"

    @staticmethod
    def _llm_dependent_query_refine_enabled() -> bool:
        """Gate for depends_on LLM query synthesis (Expert, LocalSkill, SG delegation paths)."""
        raw = os.getenv("ENABLE_LLM_DEPENDENT_QUERY_REFINE")
        if raw is None:
            raw = os.getenv("ENABLE_LLM_DEPENDENT_DELEGATION_REFINE", "true")
        return str(raw).strip().lower() in ("true", "1", "yes")

    @staticmethod
    def _task_results_from_upstream_ctx(upstream_context: dict | None) -> dict[int, str]:
        out: dict[int, str] = {}
        for row in (upstream_context or {}).get("executed_tasks") or []:
            if not isinstance(row, dict):
                continue
            tid = row.get("task_id")
            if tid is None:
                continue
            try:
                out[int(tid)] = str(row.get("result") or "")
            except (TypeError, ValueError):
                continue
        return out

    _REFINED_DEP_QUERY_ROUTE_AGENT_RE = re.compile(
        r"\b[A-Za-z0-9_-]+(?:Agent|agent)(?:-sg-[\w\-]+|-dd-[\w\-]+)\b"
    )

    def _sanitize_refined_dependent_query(self, text: str) -> str:
        """Remove routing/card-style agent identifiers leaked into refined text (best-effort)."""
        scrubbed = self._REFINED_DEP_QUERY_ROUTE_AGENT_RE.sub("", (text or "").strip())
        scrubbed = re.sub(r"[ \t]{2,}", " ", scrubbed)
        scrubbed = re.sub(r"\s*,\s*,", ",", scrubbed).strip(", ")
        scrubbed = re.sub(r"（\s*）|\(\s*\)", "", scrubbed)
        return scrubbed.strip()

    async def _llm_refine_dependent_task_query(
        self,
        *,
        original_query: str,
        planned_downstream_description: str,
        downstream_agent_name: str,
        upstream_results_blob: str,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        refine_stage: str = "generic",
    ) -> str:
        """LLM merges original user query + planner subtask text + deps' execution output into one coherent query."""
        if not (planned_downstream_description or "").strip():
            return planned_downstream_description or ""

        _max_prior = max(4096, int(os.getenv("SG_DELEGATION_REFINE_PRIOR_CHARS", "20000")))
        _prior = (upstream_results_blob or "").strip()
        if len(_prior) > _max_prior:
            _prior = _prior[: _max_prior] + "\n\n[truncated upstream results for dependent-task refine]"

        prompt = (
            "你是一个「依赖任务 Query 改写助手」，用于多智能体编排。把下面三段材料合成 **一段话**："
            "作为下游收到的**唯一用户 Query（正文）**（可能是本语义组 Expert、跨组委派或其它路由；"
            "**输出中永远不要写出**任何编排器/agent 卡片名或内部路由 ID）。\n\n"
            "硬性要求：\n"
            "0）**有效性先行判断（最高优先级）**：首先分析「上游依赖任务的综合执行结果」是否真实包含本条下游任务所需的数据"
            "（如用户ID、订单号、支付流水等关联键或事实记录）。如果上游结果明确表示未查询到任何有效记录"
            "（例如包含\u201c未找到\u201d、\u201c无匹配记录\u201d、\u201c返回 0 条\u201d、\u201c查询结果为空\u201d、\u201cNo records found\u201d等语义），"
            "或上游结果仅包含描述性文字但未给出任何可用于本任务的具体标识符或事实数据，"
            "则必须调用 refine_dependent_query 工具并设置 skip=true、reason=<简短说明跳过原因>，"
            "且此时无需设置 delegation_query 字段。\n"
            "1）**任务边界**：以「原计划中当前任务的描述」为**本条必须完成的工作范围**。"
            "原始用户问题是**业务语境与自然用语**的补充参考，可帮助你还原说法与字段关注点，"
            "但不得把**计划中分配给其它并行/后续子任务的工作**塞进本条正文（除非该 planned 表述本身明确包含）。"
            "**禁止扩写**：本条不得新增 planned 任务未隐含的新交付目标（例如在仅查用户资料的子任务里，"
            "不要附带要求查订单支付明细、退款记录等除非你从 planned 能看出该资料任务确实需要这些内容）。\n"
            "2）**业务语义**：在遵守第 1 条边界的前提下，用自然业务措辞写清要完成什么（查什么字段、对谁、"
            "要什么粒度），使执行方不靠猜就能理解。**不要**假定对方能读到未在此处给出的库表。\n"
            "3）**上游事实**：从「上游依赖任务的综合执行结果」中抽取本条所需的关键事实"
            "（主键、订单号、用户标识等），**自然嵌入**正文；只允许使用已在这些结果中出现的值，严禁编造。\n"
            "4）**命名禁区**：`delegation_query` 正文**禁止出现**任何形式的智能体卡片名、组名、`Agent-sg-…`、`Agent-dd-…`、"
            "十六进制式路由后缀，以及「请以某某 Agent」「以某某身份」「由某某语义组」「针对某某Expert」之类指向执行单元的措辞。"
            "只写领域对象与操作（订单、用户、SKU、支付方式、开票信息等）。\n"
            "5）**自包含**：尽量单靠这段话即可完成当前步，少用「见上文 JSON」。\n"
            "6）请调用 refine_dependent_query 工具来输出结果，"
            "不需要跳过时设置 delegation_query 字段；"
            "需要跳过时设置 skip=true 和 reason。\n"
            "（键名沿用 delegation_query；与是否跨 SG 无关。）\n\n"
            "--- 原始用户问题（全文） ---\n{}\n\n"
            "--- 原计划中当前任务的描述 ---\n{}\n\n"
            "--- 上游依赖任务的综合执行结果 ---\n{}\n"
        ).format(
            (original_query or "").strip(),
            (planned_downstream_description or "").strip(),
            _prior,
        )

        _span_tag = refine_stage.replace(" ", "_")[:48]
        logger.info(
            "[DepQueryRefine][%s] invoking LLM | agent=%s prior_chars=%d planned_chars=%d query_chars=%d",
            refine_stage,
            downstream_agent_name,
            len(_prior),
            len(planned_downstream_description or ""),
            len(original_query or ""),
        )

        try:
            refine_tool = StructuredTool(
                name="refine_dependent_query",
                description="基于上游依赖任务输出和原始计划，合成下游任务的查询正文。",
                args_schema=DependentQueryRefineResult,
                func=None,
                coroutine=None,
            )
            result = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=refine_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=self.metadata,
                tool_choice="refine_dependent_query",
                span_name=f"dependent-task-query-refine-{_span_tag}",
                span_input={
                    "stage": refine_stage,
                    "downstream_agent": downstream_agent_name,
                    "upstream_chars": len(_prior),
                },
            )
            if result is None:
                logger.warning(
                    "[DepQueryRefine][%s] LLM did not call refine_dependent_query tool, fallback to planned description",
                    refine_stage,
                )
                return planned_downstream_description
            parsed = result
        except Exception as exc:
            logger.error("[DepQueryRefine][%s] LLM failed: %s", refine_stage, exc)
            return planned_downstream_description

        # --- 上游数据有效性检查：LLM 判定上游无可用数据，标记跳过 ---
        if parsed.get("skip") is True:
            _skip_reason = str(parsed.get("reason", "")).strip()
            logger.info(
                "[DepQueryRefine][%s] upstream data invalid — skipping dependent task | agent=%s "
                "planned_chars=%d upstream_chars=%d reason=%s",
                refine_stage,
                downstream_agent_name,
                len(planned_downstream_description or ""),
                len(_prior),
                _skip_reason[:200] if _skip_reason else "(no reason)",
            )
            return DEPENDENT_TASK_SKIP_DESCRIPTION

        refined = (
            parsed.get("delegation_query")
            or parsed.get("task_query")
            or parsed.get("refined_description")
            or parsed.get("query")
            or ""
        )
        refined = str(refined).strip()
        if not refined:
            logger.warning(
                "[DepQueryRefine][%s] empty synthesized query after parse, fallback", refine_stage
            )
            return planned_downstream_description

        refined_scrubbed = self._sanitize_refined_dependent_query(refined)
        if not refined_scrubbed.strip():
            logger.warning(
                "[DepQueryRefine][%s] refined text empty after sanitizing leaks, fallback", refine_stage
            )
            return planned_downstream_description
        refined = refined_scrubbed

        logger.info(
            "[DepQueryRefine][%s] refined | out_chars=%d preview=%s",
            refine_stage,
            len(refined),
            refined[:400],
        )
        return refined

    def _detect_delegation_via_structured(
        self,
        query: str,
        own_results: dict[int, str],
        collaborator_cards: list[AgentCard],
        delegated_results: Optional[dict[str, str]] = None,
    ) -> Optional[dict]:
        """P10 fast-path: derive delegation directly from structured signals.

        Scans every own-task answer for ``structured_control.unfulfilled_needs``
        (emitted by the SD Expert under the P3 contract), and looks up the
        owners over the *local* ``collaborator_cards`` set so the returned
        ``target_sgs`` names are guaranteed to be routable downstream.

        ``delegated_results`` carries the mid-exec round history (peer SG ->
        result string).  Any SG already present there is treated as
        "already attempted" for *every* still-unfulfilled need, so the
        fast-path won't re-issue the same delegation.  When every candidate
        owner has already been tried, the fast-path **yields** to the LLM
        Track 2 (returns ``None``) — Track 2 sees both own_results and
        delegated_results and can decide whether the prior delegation already
        produced enough data or whether we are truly stuck.

        Returns ``None`` when no actionable structured signal is present, in
        which case the caller falls back to the original LLM detection.  This
        gives deterministic mid-exec routing whenever the SD Expert produced a
        proper unfulfilled_needs payload, and only pays the LLM cost otherwise.
        """
        if not own_results:
            return None
        try:
            from .data_inventory import build_table_owner_index
        except Exception:  # noqa: BLE001
            return None

        # collaborator_cards may be empty (routing peer pool vacant). Still emit
        # the structured signal + scoped synth so mid-exec can broadcast
        # capability_check over the full registry.
        peer_cards = list(collaborator_cards or [])

        # Aggregate unfulfilled_needs across all own-task answers.  The
        # ``_extract_structured_control_from_text`` helper lives on
        # ``OrchestratorAgent`` (it is shared with the retry/eval paths there)
        # and is intentionally a @staticmethod, so we invoke it via the class
        # rather than ``self`` because the executor class does not inherit
        # from ``OrchestratorAgent``.
        aggregated: List[Dict[str, Any]] = []
        seen_tables: set = set()
        join_keys: Dict[str, List[str]] = {}
        for tid, raw_answer in own_results.items():
            if not raw_answer:
                continue
            sc = OrchestratorAgent._extract_structured_control_from_text(str(raw_answer))
            if not isinstance(sc, dict):
                continue
            raw_keys = sc.get("join_keys") or {}
            if isinstance(raw_keys, dict):
                for key, vals in raw_keys.items():
                    name = str(key or "").strip()
                    if not name:
                        continue
                    values = vals if isinstance(vals, (list, tuple)) else [vals]
                    bucket = join_keys.setdefault(name, [])
                    for item in values:
                        text = str(item).strip()
                        if text and text not in bucket:
                            bucket.append(text)
            for need in sc.get("unfulfilled_needs") or []:
                if not isinstance(need, dict):
                    continue
                missing = str(need.get("missing_table") or "").strip()
                if not missing:
                    continue
                key = missing.lower()
                if key in seen_tables:
                    continue
                seen_tables.add(key)
                aggregated.append({
                    "task_id": tid,
                    "missing_table": missing,
                    "reason": str(need.get("reason") or "").strip(),
                    "intent_fragment": str(need.get("intent_fragment") or "").strip(),
                    "stage": str(need.get("stage") or "").strip(),
                })
        if not aggregated:
            return None

        owner_index = build_table_owner_index(peer_cards)
        own_name = (
            (getattr(self.agent_card, "name", None) or "").strip()
            if getattr(self, "agent_card", None) else ""
        )
        # Treat every SG that appears in ``delegated_results`` as already
        # attempted in a prior mid-exec round.  We don't track per-(sg,table)
        # success/failure here, so the conservative rule is: if the fast-path
        # already routed work to a SG, don't pick it again — let Track 2 LLM
        # (which sees both own + delegated context) decide whether to retry.
        already_tried: set = {
            name
            for name in (delegated_results or {}).keys()
            if isinstance(name, str) and name
        }
        target_sgs: List[str] = []
        mapped_needs: List[Dict[str, Any]] = []
        any_owner_visible = False
        any_owner_skipped = False
        for need in aggregated:
            raw_owners = list(owner_index.get(need["missing_table"].lower()) or [])
            raw_owners = [o for o in raw_owners if o and o != own_name]
            fresh_owners = [o for o in raw_owners if o not in already_tried]
            skipped_owners = [o for o in raw_owners if o in already_tried]
            if raw_owners:
                any_owner_visible = True
            if skipped_owners:
                any_owner_skipped = True
            need_entry = dict(need)
            need_entry["owners"] = fresh_owners
            need_entry["all_owners"] = raw_owners
            need_entry["skipped_owners"] = skipped_owners
            mapped_needs.append(need_entry)
            for o in fresh_owners:
                if o not in target_sgs:
                    target_sgs.append(o)

        if not target_sgs:
            if any_owner_skipped and any_owner_visible:
                logger.info(
                    "[Cross-SG][CollabMidExecDetect][Structured] %d unfulfilled need(s) — all owners already delegated to (already_tried=%s); yielding to LLM Track 2",
                    len(aggregated),
                    sorted(already_tried),
                )
                return None
            logger.info(
                "[Cross-SG][CollabMidExecDetect][Structured] %d unfulfilled need(s) with no local owner in collaborator pool — keep signal for full-registry capability_check",
                len(aggregated),
            )

        # Build a scoped peer sub-query: join keys + missing fields only.
        # Do NOT embed the full original question — that causes the downstream
        # Expert to chase out-of-scope goals from other domains.
        need_labels: List[str] = []
        for n in mapped_needs:
            frag = str(n.get("intent_fragment") or "").strip()
            table = str(n.get("missing_table") or "").strip()
            label = frag if frag and len(frag) <= 80 else (table or frag[:80])
            if label and label not in need_labels:
                need_labels.append(label)
        need_text = "、".join(need_labels[:6]) or "缺失的外域字段"
        key_bits: List[str] = []
        for key, vals in (join_keys or {}).items():
            key_name = str(key or "").strip()
            if not key_name:
                continue
            value_text = ",".join(str(v).strip() for v in (vals or [])[:50] if str(v).strip())
            if value_text:
                key_bits.append(f"{key_name}={value_text}")
        keys_text = "; ".join(key_bits)
        synthesized_query = (
            f"请仅查询并返回以下信息（勿处理本子任务以外的目标，勿扩展为完整原题）："
            f"{need_text}。"
        )
        if keys_text:
            synthesized_query += f" 关联键：{keys_text}。"
        synthesized_query += " 按关联键返回对应结果即可。"

        result = {
            "synthesized_query": synthesized_query,
            "target_sgs": target_sgs,
            "reason": (
                "structured_signal: SD Expert 报告 unfulfilled_needs，"
                + (
                    f"已通过 local owner index 命中 {len(target_sgs)} 个 owner SG"
                    if target_sgs
                    else "本地 collaborator 池未命中 owner，交由全量 capability_check 选人"
                )
                + (
                    f"（跳过已委托过的 {len(already_tried)} 个 SG）"
                    if already_tried
                    else ""
                )
            ),
            "structured_unfulfilled_needs": mapped_needs,
            "skipped_owners": sorted(already_tried),
            "join_keys": join_keys,
            "source": "structured_signal",
        }
        logger.info(
            "[Cross-SG][CollabMidExecDetect][Structured] resolved | needs=%d fresh_owners=%d skipped=%d synth_query_len=%d",
            len(aggregated),
            len(target_sgs),
            len(already_tried),
            len(synthesized_query),
        )
        return result

    def _mid_delegate_capability_select_enabled(self) -> bool:
        """Whether mid-delegate target selection uses standard capability_check."""
        return os.getenv(
            "SG_MID_DELEGATE_CAPABILITY_SELECT_ENABLED", "true"
        ).strip().lower() not in ("false", "0", "no")

    def _mid_delegate_max_targets(self) -> int:
        try:
            return max(1, int(os.getenv("SG_MID_DELEGATE_MAX_TARGETS", "3") or 3))
        except ValueError:
            return 3

    def _mid_exec_self_agent_name(self) -> str:
        return str(
            getattr(self.agent_card, "name", None)
            or getattr(self, "agent_id", None)
            or ""
        ).strip()

    @staticmethod
    def _is_mid_exec_sg_card(card: Any) -> bool:
        name = str(getattr(card, "name", "") or "")
        url = getattr(card, "url", None)
        return bool(name and url and "-sg-" in name)

    async def _load_mid_exec_broadcast_candidates(
        self,
        *,
        extra_cards: Optional[list[AgentCard]] = None,
    ) -> list[AgentCard]:
        """Load mid-exec remote SG candidates from the full orchestrator registry.

        Mid-exec planning intentionally uses broadcast discovery rather than
        trusting Routing's peer/contribute pool (which may be empty or incomplete).
        """
        self_name = self._mid_exec_self_agent_name()
        by_name: dict[str, AgentCard] = {}

        registry_cards = await sg_broadcast.list_all_orchestrator_agent_cards()
        for card in registry_cards or []:
            if not self._is_mid_exec_sg_card(card):
                continue
            if card.name == self_name:
                continue
            by_name[card.name] = card

        # Merge any routing-peer cards that registry missed (URL refresh).
        for card in extra_cards or []:
            if not self._is_mid_exec_sg_card(card):
                continue
            if card.name == self_name:
                continue
            by_name.setdefault(card.name, card)

        cards = list(by_name.values())
        logger.info(
            "[Cross-SG][MidCapSelect] broadcast candidate pool | count=%d self=%s",
            len(cards),
            self_name,
        )
        return cards

    def _mid_exec_soft_hint_fallback_enabled(self) -> bool:
        return os.getenv(
            "SG_MID_DELEGATE_SOFT_HINT_FALLBACK", "true"
        ).strip().lower() not in ("false", "0", "no")

    def _resolve_mid_exec_soft_hint_cards(
        self,
        hint_names: list[str],
        candidates: list[AgentCard],
        extra_cards: Optional[list[AgentCard]] = None,
    ) -> tuple[list[AgentCard], list[str]]:
        """Resolve detect soft_hints into probeable cards.

        Soft hints may name a peer that registry listing briefly missed; still
        accept a matching card from ``extra_cards`` (routing/detect pool).
        """
        by_name: dict[str, AgentCard] = {}
        for card in list(candidates or []) + list(extra_cards or []):
            if not self._is_mid_exec_sg_card(card):
                continue
            name = str(getattr(card, "name", "") or "").strip()
            if name and name not in by_name:
                by_name[name] = card
        hinted: list[AgentCard] = []
        missing: list[str] = []
        seen: set[str] = set()
        for raw in hint_names or []:
            name = str(raw or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            card = by_name.get(name)
            if card is None:
                missing.append(name)
                continue
            hinted.append(card)
        return hinted, missing

    @staticmethod
    def _mid_exec_capability_probe_query(synthesized_query: str) -> str:
        """Frame mid-exec sub-task so capability judges scope the ask, not the full original question."""
        scoped = (synthesized_query or "").strip()
        if not scoped:
            return scoped
        return (
            "【跨 SG 补数子任务】请仅根据下列子任务判断本智能体是否拥有所需数据域"
            "（can_handle / can_contribute）。不要按完整原题的其它域目标来否决。\n\n"
            f"{scoped}"
        )

    @staticmethod
    def _rank_mid_exec_capable_pairs(
        capable_pairs: list[tuple[AgentCard, Any]],
        soft_hint_names: list[str],
    ) -> list[tuple[AgentCard, Any]]:
        """Rank capability evidence; soft hints only break ties (never gate probing)."""
        hint_set = {n for n in soft_hint_names if n}
        hint_order = {n: i for i, n in enumerate(soft_hint_names) if n}

        def _key(pair: tuple[AgentCard, Any]) -> tuple:
            card, resp = pair
            name = str(getattr(card, "name", "") or "")
            return (
                1 if getattr(resp, "can_handle", False) else 0,
                float(getattr(resp, "confidence", 0.0) or 0.0),
                1 if name in hint_set else 0,
                # Earlier detect hints win among equal soft-hinted peers.
                -hint_order.get(name, 10_000),
            )

        return sorted(capable_pairs, key=_key, reverse=True)

    async def _select_mid_delegate_targets_via_capability(
        self,
        synthesized_query: str,
        collaborator_cards: list[AgentCard],
        *,
        soft_target_hints: Optional[list[str]] = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        get_response_text: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Select mid-delegate peer SGs via concurrent standard ``capability_check``.

        Authoritative mid-exec candidate source is a **one-shot full-registry
        broadcast** of SG orchestrators (not Routing's peer/contribute pool).
        Soft hints from structured/LLM detection never form a sequential first
        probe set — they only (1) ensure missing peers stay in the pool,
        (2) break ranking ties, and (3) optionally fall back when every probe
        returns empty while detect already named resolvable peers.
        """
        empty: dict[str, Any] = {
            "target_cards": [],
            "target_sg_names": [],
            "capable_pairs": [],
            "hints_by_sg": {},
            "evidence_text": "",
            "probed_names": [],
        }
        if not (synthesized_query or "").strip():
            logger.info(
                "[Cross-SG][MidCapSelect] skip | reason=empty_synthesized_query"
            )
            return empty

        candidates = await self._load_mid_exec_broadcast_candidates(
            extra_cards=collaborator_cards,
        )
        hint_names = [n for n in (soft_target_hints or []) if n]
        hinted, missing_hints = self._resolve_mid_exec_soft_hint_cards(
            hint_names,
            candidates,
            collaborator_cards,
        )
        if missing_hints:
            logger.warning(
                "[Cross-SG][MidCapSelect] soft_hints not resolvable to cards | missing=%s",
                missing_hints[:10],
            )
        # Ensure resolved soft-hint cards are in the candidate pool even if
        # registry listing omitted them.
        if hinted:
            by_name = {c.name: c for c in candidates}
            for card in hinted:
                by_name.setdefault(card.name, card)
            candidates = list(by_name.values())

        if not candidates:
            logger.info(
                "[Cross-SG][MidCapSelect] skip | reason=no_broadcast_candidates "
                "routing_peers=%d soft_hints=%s",
                len(collaborator_cards or []),
                hint_names[:10],
            )
            return empty

        probe_query = self._mid_exec_capability_probe_query(synthesized_query)
        logger.info(
            "[Cross-SG][MidCapSelect] concurrent capability_check | set=broadcast_pool "
            "candidates=%d soft_hints=%s names=%s synth_query_preview=%s",
            len(candidates),
            hint_names[:10],
            [c.name for c in candidates[:12]],
            (synthesized_query or "")[:120],
        )
        capable_pairs = await sg_broadcast.probe_agents_capability_concurrent(
            probe_query,
            candidates,
            user_id,
            run_id,
            trace_id,
            get_response_text=get_response_text,
        )
        probed_names = [c.name for c in candidates]
        if capable_pairs:
            capable_pairs = self._rank_mid_exec_capable_pairs(capable_pairs, hint_names)
            logger.info(
                "[Cross-SG][MidCapSelect] capable peers found | set=broadcast_pool "
                "capable=%d handlers=%s contributors=%s soft_hint_ranked=%s",
                len(capable_pairs),
                [c.name for c, r in capable_pairs if r.can_handle][:10],
                [
                    c.name
                    for c, r in capable_pairs
                    if (not r.can_handle) and r.can_contribute
                ][:10],
                [n for n in hint_names if n in {c.name for c, _ in capable_pairs}][:10],
            )

        if (
            not capable_pairs
            and hinted
            and self._mid_exec_soft_hint_fallback_enabled()
        ):
            logger.warning(
                "[Cross-SG][MidCapSelect] capability_check empty after probing; "
                "falling back to detect soft_hints | hints=%s probed=%d",
                [c.name for c in hinted][:10],
                len(probed_names),
            )
            capable_pairs = [
                (
                    card,
                    sg_broadcast.CapabilityCheckResponse(
                        can_handle=True,
                        can_contribute=True,
                        confidence=0.55,
                        reason=(
                            "mid-exec soft_hint fallback: detection named this SG "
                            "for an unresolved data gap, but capability_check "
                            "returned no capable peer"
                        ),
                        agent_name=card.name,
                        agent_url=str(getattr(card, "url", "") or ""),
                    ),
                )
                for card in hinted
            ]

        if not capable_pairs:
            logger.info(
                "[Cross-SG][MidCapSelect] no capable remote SG | probed=%d "
                "soft_hints=%s missing_hints=%s",
                len(probed_names),
                hint_names[:10],
                missing_hints[:10],
            )
            return {
                **empty,
                "probed_names": probed_names,
                "evidence_text": sg_broadcast.format_capability_evidence_for_planner([]),
            }

        max_targets = self._mid_delegate_max_targets()
        selected = capable_pairs[:max_targets]
        target_cards = [card for card, _ in selected]
        target_sg_names = [card.name for card in target_cards]
        hints_by_sg: dict[str, dict] = {}
        for card, resp in selected:
            hint = getattr(resp, "execution_hint", None) or {}
            if isinstance(hint, dict) and hint:
                hints_by_sg[card.name] = hint
                logger.info(
                    "[Cross-SG][MidCapSelect] peer issued execution_hint | "
                    "sg=%s selected_members=%s can_handle=%s",
                    card.name,
                    (hint.get("selected_members") or [])[:10],
                    hint.get("can_handle"),
                )

        evidence_text = sg_broadcast.format_capability_evidence_for_planner(selected)
        logger.info(
            "[Cross-SG][MidCapSelect] selected mid-delegate targets | "
            "count=%d max=%d targets=%s with_hint=%s",
            len(target_sg_names),
            max_targets,
            target_sg_names,
            list(hints_by_sg.keys()),
        )
        return {
            "target_cards": target_cards,
            "target_sg_names": target_sg_names,
            "capable_pairs": selected,
            "hints_by_sg": hints_by_sg,
            "evidence_text": evidence_text,
            "probed_names": probed_names,
        }

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
        """Mid-execution Step 1: detect whether a data gap still exists.

        Two-track design:

        1. **Structured fast-path** (P10): scan ``own_results`` for
           ``structured_control.unfulfilled_needs`` (P3 contract) and resolve
           soft owner hints via the local owner index over ``collaborator_cards``.
           Deterministic, LLM-free.
        2. **LLM fallback**: reason over natural-language outputs to decide
           ``needs_help`` and produce ``synthesized_query``.

        Final remote-SG selection happens later via concurrent standard
        ``capability_check`` (``_select_mid_delegate_targets_via_capability``).
        ``target_sgs`` from either track is only a soft inventory hint.

        Returns:
            ``None`` if no delegation is needed.
            ``dict`` with ``synthesized_query``, optional soft ``target_sgs``,
            ``reason``, and optionally ``source`` / ``structured_unfulfilled_needs``.
        """
        # Empty routing peer pool is OK: detect only decides whether a gap
        # remains and builds synthesized_query. Final remote SG selection is
        # always done via full-registry capability_check broadcast.
        if not collaborator_cards:
            logger.info(
                "[Cross-SG][CollabMidExecDetect] collaborator cards empty; "
                "continuing detect (targets via broadcast capability_check)"
            )

        # Track 1: structured signal (deterministic, free).  Gated by env so
        # operators can fall back to LLM-only behaviour if needed.
        # ``delegated_results`` is forwarded so the fast-path can skip peer
        # SGs already attempted in earlier mid-exec rounds — if every owner
        # has been tried we deliberately yield to Track 2 (LLM), which sees
        # both own + delegated context and can judge whether we are done or
        # truly stuck.
        if os.getenv("ENABLE_STRUCTURED_DELEGATION_DETECT", "true").strip().lower() not in ("false", "0", "no"):
            structured = self._detect_delegation_via_structured(
                query=query,
                own_results=own_results,
                collaborator_cards=collaborator_cards or [],
                delegated_results=delegated_results,
            )
            if structured:
                logger.info(
                    "[Cross-SG][CollabMidExecDetect] structured fast-path matched | "
                    "soft_target_hints=%s skipped=%s reason=%s "
                    "(final targets still require capability_check)",
                    structured.get("target_sgs"),
                    structured.get("skipped_owners") or [],
                    (structured.get("reason") or "")[:120],
                )
                return structured
            logger.info(
                "[Cross-SG][CollabMidExecDetect] structured fast-path produced no actionable target — falling back to LLM Track 2 | own_results=%d delegated_results=%d",
                len(own_results),
                len(delegated_results),
            )

        own_text = "\n".join(
            f"[Task#{tid}]: {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}]: {res}" for name, res in delegated_results.items() if res
        )
        # Provide a short description preview for better domain awareness,
        # but authoritative remote selection is still capability_check broadcast.
        if collaborator_cards:
            sg_options = "\n".join(
                f"- {c.name}（{str(c.description or '')[:100]}）" for c in collaborator_cards
            )
        else:
            sg_options = (
                "(当前 Routing peer 池为空；不要据此判定无法委派。"
                "最终远程 SG 由后续全量 capability_check 广播决定，target_sgs 可留空。)"
            )

        prompt = (
            "你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，"
            "判断是否还需要其他领域的补充数据。\n\n"
            "核心判断逻辑：\n"
            "1）首先分析本层自身执行结果，判断当前结果是否足以完整回答原始问题。\n"
            "2）如果本层结果是空结果（如 'not found'、'查询结果为空'、'0 条记录'、'no records'），"
            "不能因此直接拒绝委派。需要进一步判断：\n"
            "   a) 本层 skill 说明或结果中是否提到了其他可用的技能/数据源/agent？\n"
            "   b) 原始问题中是否包含可以传递给下游的实体信息（如姓名、关键词、ID、自然语言描述）？\n"
            "   c) 下游 agent 是否有可能通过自身数据独立完成查询（即使没有精确的 join_key）？\n"
            "   如果 a/b/c 任一为真，仍应返回 needs_help=true。\n"
            "3）当本层有具体标识符（join_keys）时，synthesized_query 必须包含这些标识符。\n"
            "   当本层没有具体标识符时，synthesized_query 应包含原始问题中的实体信息"
            "   （如姓名、描述、关键词）作为查询线索，下游 agent 可自行完成映射或查询。\n"
            "4）部分成功也要委派：若结果写了 task fail / 无法确认，但正文或 "
            "structured_control 里已有可传递的关联键，且明确缺外域字段，"
            "应 needs_help=true，synthesized_query 必须带上这些关联键。\n"
            "5）outcome=partial 或 reason_code=data_sovereignty_gap 时，一律 needs_help=true。\n"
            "6）只有当本层结果明确表示：原始问题中的实体或概念在自身数据域中确实不存在，"
            "且没有任何其他 agent 可能拥有该数据时，才返回 needs_help=false。\n\n"
            "synthesized_query 书写规则（强制）：\n"
            "- 只写下游 SG 本轮需要交付的子问题：关联键 + 缺失字段；\n"
            "- 当没有关联键时，传递原始问题中的实体信息（姓名、ID、关键词等）作为查询线索；\n"
            "- 禁止复述完整原题；禁止写入其它域目标或整题扩写；\n"
            "- 禁止要求下游去计算本层已有或本层负责的指标；\n"
            "- 下游拿到这句话应能直接执行并结束，无需理解整题其它部分。\n\n"
            "重要约束：\n"
            "- 不要依据 SG 的自描述文案选择目标；最终远程 SG 由后续标准 "
            "capability_check 全量广播（成员能力证据）决定；\n"
            "- 即使下方 SG 名称列表为空，只要存在数据缺口，仍应 "
            "needs_help=true；\n"
            "- 当 needs_help=true 时，target_sgs 应填写你认为可补充数据的 SG 名称。\n"
            "  最终远程 SG 由后续标准 capability_check 全量广播决定，此处的 target_sgs 用于辅助性提示。\n"
            "- target_sgs 中的名称必须从上方列表中的 SG 名称中精确选取，不得编造不存在的 SG 名称。\n\n"
            "注意: 如果已有结果已经能完整回答原始问题，应返回 needs_help=false。\n\n"
            f"原始问题（仅供判断缺口，勿整段写入 synthesized_query）：{query}\n\n"
            f"本层自身执行结果：\n{own_text}\n\n"
            f"已完成委托结果：\n{del_text}\n\n"
            f"可委托的 SG 名称列表（仅供参考，非选人依据）：\n{sg_options}\n\n"
            "请调用 detect_delegation_needs 工具来输出结果："
        )

        logger.info(
            "[Cross-SG][CollabMidExecDetect] invoking detection LLM | own_results=%d delegated_results=%d coll_sgs=%d prompt_chars=%d",
            len(own_results),
            len(delegated_results),
            len(collaborator_cards),
            len(prompt),
        )

        try:
            detect_tool = StructuredTool(
                name="detect_delegation_needs",
                description=(
                    "检测是否仍有数据缺口需要跨 SG 补充；输出 synthesized_query 与原因。"
                    "target_sgs 仅为可选软提示，最终选人由 capability_check 完成。"
                ),
                args_schema=DelegationDetectionResult,
                func=None,
                coroutine=None,
            )
            data_dict = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=detect_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=self.metadata,
                tool_choice="detect_delegation_needs",
                span_name="cross-sg-detect-delegation-needs",
                span_input={"query": query, "own_task_count": len(own_results)},
            )
            if data_dict is None or not isinstance(data_dict, dict):
                logger.warning(
                    "[Cross-SG][CollabMidExecDetect] LLM did not call detect_delegation_needs tool"
                )
                return None
        except Exception as e:
            logger.error("[Cross-SG][CollabMidExecDetect] LLM invocation failed: %s", e)
            return None

        if not data_dict.get("needs_help", False):
            logger.info("[Cross-SG][CollabMidExecDetect] LLM decided no additional delegation needed")
            return None

        result = {
            "synthesized_query": data_dict.get("synthesized_query", ""),
            "target_sgs": data_dict.get("target_sgs", []),
            "reason": data_dict.get("reason", ""),
            "source": "llm_detection",
        }
        logger.info(
            "[Cross-SG][CollabMidExecDetect] LLM detected gap | source=llm_detection "
            "soft_target_hints=%s reason=%s synth_query_len=%d "
            "(final targets require capability_check)",
            result["target_sgs"],
            (result["reason"] or "")[:100],
            len(str(result["synthesized_query"] or "")),
        )
        return result

    @staticmethod
    def _apply_scoped_mid_exec_task_descriptions(
        plan: Optional[TaskList],
        synthesized_query: str,
    ) -> Optional[TaskList]:
        """Force mid-exec peer task descriptions to the scoped synthesized_query.

        The planner may expand descriptions with the full original goal.
        Downstream Experts then chase out-of-scope work. For a mid-exec round
        the authoritative ask is ``synthesized_query``.
        """
        if plan is None:
            return None
        scoped = (synthesized_query or "").strip()
        if not scoped:
            return plan
        for task in list(getattr(plan, "tasks", None) or []):
            prev = str(getattr(task, "description", "") or "").strip()
            if prev != scoped:
                logger.info(
                    "[Cross-SG][CollabMidExecPlan] scoped task description | "
                    "task_id=%s agent=%s prev_chars=%d scoped_chars=%d",
                    getattr(task, "id", None),
                    getattr(task, "agent", ""),
                    len(prev),
                    len(scoped),
                )
            task.description = scoped
        return plan

    async def _plan_mid_exec_delegation(
        self,
        synthesized_query: str,
        target_cards: list[AgentCard],
        group_memory: str = "",
        agent=None,
        skill_runner=None,
    ) -> Optional[TaskList]:
        """Mid-execution Step 2: plan tasks against capability-selected peers.

        ``target_cards`` must already be chosen by concurrent
        ``capability_check`` (or legacy name filter when the feature is off).
        Do NOT rebroadcast / re-resolve the planner pool here — that would
        reintroduce card-description-based selection.
        """
        if not target_cards or not synthesized_query:
            return None
        try:
            logger.info(
                "[Cross-SG][CollabMidExecPlan] invoking planner for mid-exec | "
                "capability_selected_targets=%s synth_query_len=%d group_memory_chars=%d",
                [c.name for c in target_cards],
                len(synthesized_query or ""),
                len(group_memory or ""),
            )
            _agent = agent or OrchestratorAgent(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                stream=self.stream,
                temperature=self.temperature,
                semantic_group_id=self.semantic_group_id,
                debug=self.debug,
                data_services_url=self.data_services_url,
                metadata=self.metadata,
                enable_history=self.enable_history,
                agent_id=self.agent_id,
                max_loops=self.max_loops,
                agent_card=self.agent_card,
                skill_runner=skill_runner,
            )
            # Scope banner: planner must not expand peer tasks into the full
            # original multi-domain question.
            scoped_plan_query = (
                "【Mid-exec 子任务】下列内容即远程 SG 的全部工作范围。"
                "规划时 description 必须忠实于该子任务，"
                "禁止追加原题中其它域目标或整题扩写。\n\n"
                f"{synthesized_query}"
            )
            mid_memory = (
                f"{group_memory}\n\n"
                "【Mid-exec 规划约束】远程任务 description = 上方子任务原文；"
                "上游上下文只用于理解关联键，不得写入 description。"
                if group_memory
                else (
                    "【Mid-exec 规划约束】远程任务 description = 上方子任务原文；"
                    "不得扩写为完整原题。"
                )
            )
            # Plan only against the capability-selected peer cards.
            plan = await _agent.planner_agent.make_plan(
                scoped_plan_query,
                target_cards,
                group_memory=mid_memory,
            )
            return self._apply_scoped_mid_exec_task_descriptions(
                plan, synthesized_query
            )
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
        agent,
        progress_updater: Optional[Any] = None,
        collaboration_original_query: str = "",
        execution_hints_by_sg: Optional[dict[str, dict]] = None,
    ) -> dict[str, str]:
        """Mid-execution Step 3: dispatch plan tasks to target SGs.

        Iterates the plan's tasks, maps each to its target card, and calls
        ``delegate_to_collaborator_sg``.  When capability_check returned an
        ``execution_hint`` for a peer, forward it opaquely on dispatch.
        Returns ``{sg_name: result}``.
        """
        results: dict[str, str] = {}
        name_to_card = {c.name: c for c in target_cards}
        hints_by_sg = dict(execution_hints_by_sg or {})
        mid_exec_round = int((upstream_context or {}).get("mid_exec_round") or 0)

        logger.info(
            "[Cross-SG][CollabMidExecDispatch] dispatching mid-exec tasks | "
            "task_count=%d targets=%s hop=%d hints=%s",
            len(plan.tasks),
            [t.agent for t in plan.tasks],
            current_hop,
            list(hints_by_sg.keys()),
        )

        for task in plan.tasks:
            agent_name = (task.agent or "").strip()
            target_card = name_to_card.get(agent_name)
            if target_card is None:
                logger.warning(
                    "Cross-SG: mid-exec dispatch, no card for agent=%s", agent_name,
                )
                continue

            can_delegate = current_hop > 1
            if not can_delegate:
                results[agent_name] = NONE_TASK_DESCRIPTION
                continue

            # Every delegation edge (including mid-exec dispatch) consumes 1 hop.
            # The receiver will further decrement when it delegates onward.
            current_hop -= 1
            next_hop = current_hop
            new_chain = delegation_chain + [agent.agent_name]
            ctx = dict(upstream_context or {})
            tid_map = self._task_results_from_upstream_ctx(ctx)

            task_desc_for_delegate = task.description or ""
            if self._llm_dependent_query_refine_enabled() and task.depends_on:
                _deps = list(task.depends_on)
                if all(tid in tid_map and (tid_map.get(tid) or "").strip() for tid in _deps):
                    _blob = "\n\n".join(
                        f"=== Task #{tid} （上游已成功执行的结果）===\n{(tid_map.get(tid) or '').strip()}"
                        for tid in sorted(_deps)
                    )
                    task_desc_for_delegate = await self._llm_refine_dependent_task_query(
                        original_query=(collaboration_original_query or "").strip(),
                        planned_downstream_description=task.description or "",
                        downstream_agent_name=task.agent or "",
                        upstream_results_blob=_blob,
                        user_id=user_id,
                        run_id=run_id,
                        trace_id=trace_id,
                        refine_stage="mid_exec_delegate",
                    )
                    # --- 上游数据无效：跳过当前委托任务 ---
                    if task_desc_for_delegate.startswith(DEPENDENT_TASK_SKIP_MARKER):
                        logger.info(
                            "[Cross-SG][MidExecDependRefine] task_id=%s skipped — "
                            "upstream data invalid, cancelling mid-exec delegation to %s",
                            task.id,
                            agent_name,
                        )
                        results[agent_name] = task_desc_for_delegate
                        continue
                else:
                    logger.info(
                        "[Cross-SG][MidExecDependRefine] skip refine agent=%s missing deps in ctx deps=%s",
                        agent_name,
                        _deps,
                    )

            _mid_delegate_desc = self._truncate_progress_message(task_desc_for_delegate, 120)
            peer_hint = hints_by_sg.get(agent_name) or {}
            if progress_updater is not None:
                await self.emit_progress(
                    progress_updater,
                    "collaboration-progress",
                    event="collab_mid_delegating",
                    message=(
                        f"Mid-exec delegating Task #{task.id} to [{agent_name}] "
                        f"(round {mid_exec_round or '?'}): {_mid_delegate_desc}"
                    ),
                    status="running",
                    task_id=task.id,
                    extra={
                        "target_sg": agent_name,
                        "task_id": task.id,
                        "mid_exec_round": mid_exec_round,
                        "remaining_hop": next_hop,
                        "desc_preview": _mid_delegate_desc,
                        "has_execution_hint": bool(peer_hint),
                    },
                )

            result = await agent.delegate_to_collaborator_sg(
                target_card=target_card,
                task_description=task_desc_for_delegate,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                hop_remaining=next_hop,
                delegation_chain=new_chain,
                upstream_context=ctx,
                progress_updater=progress_updater,
                progress_artifact_name="collaboration-progress",
                execution_hint=peer_hint or None,
            )
            results[agent_name] = result
            if progress_updater is not None:
                await self.emit_progress(
                    progress_updater,
                    "collaboration-progress",
                    event="collab_mid_dispatched",
                    message=(
                        f"Mid-exec Task #{task.id} done via [{agent_name}]: {_mid_delegate_desc} "
                        f"({len(result or '')} chars)"
                    ),
                    status="done",
                    task_id=task.id,
                    extra={
                        "target_sg": agent_name,
                        "task_id": task.id,
                        "mid_exec_round": mid_exec_round,
                        "desc_preview": _mid_delegate_desc,
                        "result_chars": len(result or ""),
                    },
                )

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
        """Summarise own results + downstream delegated results + upstream context.

        Pure LLM summarisation — no data processing.
        """
        own_text = "\n".join(
            f"[Task#{tid}] {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}] {res}" for name, res in delegated_results.items() if res
        )
        upstream_text = json.dumps(upstream_context, ensure_ascii=False) if upstream_context else "无"

        prompt = (
            "请基于以下各层执行结果，综合回答用户的原始问题。\n\n"
            "输出要求：\n"
            "1. 直接输出答案正文，从实质内容开始。\n"
            "2. 不要自我介绍，不要说明你是汇总器或 agent，不要描述协作/整合过程。\n"
            "3. 不要使用「好的，作为…」「我已收到/整合了…」「以下是针对…的完整/综合回答」等开场白。\n"
            "4. 下游结果中若含类似套话，请忽略并只提取实质信息，不要在输出中重复。\n"
            "5. 信息冲突时简要说明；缺信息时说明缺什么，勿编造。\n\n"
            f"原始问题：{query}\n\n"
            f"上游传入上下文：{upstream_text}\n\n"
            f"本层自身执行结果：\n{own_text}\n\n"
            f"委托给下游 SG 的返回结果（可能已包含多级汇总）：\n{del_text}\n\n"
            "请直接输出答案："
        )

        logger.info(
            "[Cross-SG][CollabSummary] invoking summary LLM | own_results=%d delegated_results=%d prompt_chars=%d",
            len(own_results),
            len(delegated_results),
            len(prompt),
        )

        try:
            with langfuse.start_as_current_span(
                name="cross-sg-summarize-delegated-result",
                trace_context={"trace_id": trace_id},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={
                        "query": query,
                        "own_task_count": len(own_results),
                        "delegated_sg_count": len(delegated_results),
                    },
                )
                response = await self.llm.ainvoke(
                    [HumanMessage(content=prompt)],
                    config={"callbacks": [langfuse_handler]},
                )
                span.update_trace(
                    output={"result_chars": len(str(response.content or ""))},
                )
            langfuse.flush()
        except Exception as e:
            logger.error("[Cross-SG][CollabSummary] LLM invocation failed: %s", e)
            return (
                "由于汇总阶段出错，未能生成综合答案。以下为各协作 SG 返回的原始结果：\n\n"
                f"{own_text}\n\n"
                f"{del_text}"
            )

        result = str(response.content or "").strip()
        logger.info(
            "[Cross-SG][CollabSummary] summary generated | result_chars=%d preview=%s",
            len(result),
            result[:1000],
        )
        return result

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()

        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        self.metadata = metadata
        self._progress_context = {
            "run_id": (metadata or {}).get("run_id", ""),
            "user_id": (metadata or {}).get("user_id", ""),
            "agent_id": self.agent_id or self.current_agent_label(),
        }
        exec_strategy = (metadata or {}).get("execution_strategy") or "single"
        logger.info(
            "[Execute] ========== Orchestrator Execute ==========\n"
            "  agent_id=%s | semantic_group_id=%s | strategy=%s\n"
            "  metadata keys=%s\n"
            "========================================",
            self.agent_id,
            self.semantic_group_id,
            exec_strategy,
            list(metadata.keys()) if isinstance(metadata, dict) else "?",
        )
        if isinstance(metadata, dict) and "prior_task_results" in metadata:
            _ptr = metadata.get("prior_task_results")
            try:
                if isinstance(_ptr, str):
                    _ptr_log = _ptr
                else:
                    _ptr_log = json.dumps(_ptr, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                _ptr_log = repr(_ptr)
            logger.info(
                "[Execute][SemanticGroupOrchestrator] prior_task_results: %s",
                _ptr_log,
            )
        else:
            logger.info(
                "[Execute][SemanticGroupOrchestrator] prior_task_results: (metadata key absent)",
            )

        if isinstance(metadata, dict) and metadata.get(sg_broadcast.ROUTING_AGENT_POOL_KEY):
            sg_broadcast.log_routing_agent_pool_received(metadata)

        # ---- Capability Check: respond quickly if this is a broadcast routing probe ----
        # Must run before Cross-SG collaborative mode — otherwise probes are mis-handled as
        # full execute_collaborative and RoutingAgent receives non-JSON / wrong-shaped replies.
        if metadata and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            logger.info(f"[Capability] Received capability check request, query: {query[:100]}...")
            await self.handle_capability_check(context, event_queue, query)
            return

        if metadata and metadata.get("message_type") == PRE_MAKE_PLAN_MESSAGE_TYPE:
            logger.info(
                "[PreMakePlan] Received pre-make-plan request, query: %s...",
                query[:100],
            )
            await self.handle_pre_make_plan(context, event_queue, query)
            return

        # ---- Cross-SG Collaborative Mode ----
        if os.getenv("ENABLE_CROSS_SG_COLLABORATION", "true").strip().lower() in ("true", "1", "yes"):
            try:
                await self.execute_collaborative(context, event_queue)
            except Exception as e:  # noqa: BLE001
                # execute_collaborative 内部已对 make_plan 的 ValueError 做了
                # 优雅降级（updater.failed）。这里再兜一层是为了防止其它
                # 未预期异常（网络抖动 / 下游 SG 不可达等）冒泡到 ASGI
                # TaskGroup 而被记成未处理异常。
                logger.error(
                    "[Execute] execute_collaborative raised unhandled exception: %s",
                    e, exc_info=True,
                )
                try:
                    task = context.current_task
                    if task is not None:
                        updater = TaskUpdater(event_queue, task.id, task.context_id)
                        await updater.failed(
                            message=new_agent_text_message(
                                f"协同执行失败：{e}", context_id=task.context_id,
                            ),
                        )
                except Exception as inner:  # noqa: BLE001
                    logger.error("[Execute] failed to send failure status: %s", inner)
            return

        legacy_route_paths = []
        if metadata:
            route_paths = metadata.get("route_paths") or []
            route_path = metadata.get("route_path") or []
            if isinstance(route_paths, list):
                legacy_route_paths.extend(
                    [entry.get("path") or entry.get("route_path") for entry in route_paths if isinstance(entry, dict)]
                )
            if isinstance(route_path, list) and route_path:
                legacy_route_paths.append(route_path)
        multi_hop_paths = [p for p in legacy_route_paths if isinstance(p, list) and len(p) > 1]
        if multi_hop_paths:
            logger.warning(
                "[SingleLayerSG] ignoring legacy multi-hop route metadata for sg execute | agent_id=%s paths=%s",
                self.agent_id,
                multi_hop_paths,
            )

        skill_runner = await self._ensure_skill_runner()

        agent = OrchestratorAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            semantic_group_id=self.semantic_group_id,
            debug=self.debug,
            data_services_url=self.data_services_url,
            metadata=metadata,
            enable_history=self.enable_history,
            agent_id=self.agent_id,
            max_loops=self.max_loops,
            agent_card=self.agent_card,
            skill_runner=skill_runner,
        )

        if not context.message:
            raise Exception('No message provided')

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # Keep user query clean. Prior task results are propagated via metadata only.
        query_for_plan = query

        # make plans for user question, each plan is the name of agent card
        tasks = await agent.get_plan(query_for_plan)

        think = []

        if tasks is None:
            logger.info(f"===== OrchestratorAgentExecutor, tasks is empty.")
            not_found_agents = (
                NO_SIDECAR_FALLBACK_DESCRIPTION
                if getattr(agent, "_no_sidecar_fallback", False)
                else "Not found agents. You can provide more information."
            )
            await self.emit_answer(
                updater,
                f'{agent.agent_name}-result',
                event="final_answer",
                payload={"text": not_found_agents, "presentation": "text"},
            )
            think.append(not_found_agents)
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )
        else:
            plan_msg, plan_extra = OrchestratorAgent.build_group_plan_ready_progress(
                task_list=tasks,
                user_query=query_for_plan,
            )
            await agent.emit_progress(
                updater,
                f'{agent.agent_name}-result',
                event="group_plan_ready",
                message=plan_msg,
                status="done",
                extra=plan_extra,
            )
            if self.debug == 1:
                participant_chain = (metadata or {}).get("participant_chain")
                tasks_str = tasklist_to_string(tasks, participant_chain=participant_chain)
                think.append(tasks_str)

            # call each agent to get the knowledge owned by each agent, then get some knowledges from agents
            task_name = f'{agent.agent_name}-result'
            task_knowledges = await agent.a2a_tasks(query_for_plan, tasks, updater, task_name, think)

            if task_knowledges:
                logger.info(
                    "===== OrchestratorAgentExecutor.task_knowledges count=%s",
                    len(task_knowledges),
                )
                for _i, tk in enumerate(task_knowledges):
                    logger.info("===== task_knowledge[%s] (full):\n%s", _i, tk)
            else:
                logger.info("===== OrchestratorAgentExecutor.task_knowledges count=0")

            # SemanticGroup orchestrator 始终需要 LLM 总结回答，不跳过
            # （answer_model=original 仅透传给下游 agent 让它们跳过各自的 LLM，但本层一定要总结）
            conversation = []
            async for event in agent.stream(query_for_plan, task_knowledges, think):
                is_task_complete = event['is_task_complete']
                if not is_task_complete:
                    if event['content']:
                        await self.emit_answer(
                            updater,
                            f'{agent.agent_name}-result',
                            event="final_answer_chunk",
                            payload={"text": event['content']},
                            status="running",
                        )
                        await asyncio.sleep(0.01)
                        conversation.append(event['content'])
                else:
                    # The answer emitted here is the root SG's final answer.
                    # RoutingAgent may later repackage it for UI, or aggregate multiple roots above this layer.
                    final_text = "".join(conversation).strip()
                    if final_text:
                        await self.emit_progress(
                            updater,
                            f'{agent.agent_name}-result',
                            event="group_final_answer_ready",
                            message="Final answer is ready",
                            status="done",
                            extra={"answer_chars": len(final_text)},
                        )
                        await self.emit_answer(
                            updater,
                            f'{agent.agent_name}-result',
                            event="final_answer",
                            payload={"text": final_text, "presentation": "text"},
                        )
                    await updater.complete(
                        message=new_agent_text_message(
                            event['content'], context_id=task.context_id
                        )
                    )

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')