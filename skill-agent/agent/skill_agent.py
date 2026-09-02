"""SkillAgent — upgraded standalone A2A agent with planning, mid-exec evaluation,
cross-SG collaboration, and LLM summarization.

Upgraded from a simple SkillRunner executor to a full orchestration-capable agent
that mirrors the key orchestration patterns from orchestrator-agent while
remaining lightweight (no Route A / SG Expert Agent).

Capabilities:
  1. 能力广播响应：Active capability broadcast (proactive)
  2. Plan 任务分解：PlannerAgent for task decomposition
  3. Mid-exec 评估补漏：Dual-track detection + broadcast delegation
  4. 跨 SG 协作：Cross-SG delegation via A2A
  5. LLM 汇总：Summary LLM
  6. 依赖任务查询精炼：Upstream context injection for dependent tasks
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time as _time
from abc import ABC
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterable,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Union,
)
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    MessageSendParams,
    SendStreamingMessageRequest,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.tools import StructuredTool, tool
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from model_sdk import ModelManager
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import override

from . import broadcast_capability_check as sg_broadcast
from .agent_card_resolve import resolve_agent_card_by_planner_name
from .agentregistry_client import AgentRegistryClient
from .dataservices_client import (
    CreateHistoryRequest,
    DataServicesClient,
    HistoryMessage,
    SearchHistoryRequest,
)
from .tool_call_utils import invoke_llm_with_tool

try:
    from skill_sdk.skill.runner import SkillRunner
except ImportError:
    SkillRunner = None

try:
    from skill_sdk.tool.code_execution import CodeExecution
except ImportError:
    CodeExecution = None

try:
    from json_repair import repair_json as _json_repair
except ImportError:
    _json_repair = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "
DAC_PROGRESS_LAYER = "sd_skill"
PROGRESS_SCHEMA_VERSION = "v1"
PROGRESS_BASE_FIELDS = (
    "schema_version", "layer", "event", "run_id", "user_id", "agent_id",
    "task_id", "message", "status",
)
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"
PRE_MAKE_PLAN_MESSAGE_TYPE = "pre_make_plan"
PROPAGATED_HISTORY_KEY = "propagated_history"
SG_EXECUTION_HINT_KEY = "sg_execution_hint"
NONE_TASK_DESCRIPTION = "No available agent can do this task. "
DEPENDENT_TASK_SKIP_MARKER = "__SG_SKIP_UPSTREAM_NO_DATA__"
DEPENDENT_TASK_SKIP_DESCRIPTION = (
    DEPENDENT_TASK_SKIP_MARKER + "上游依赖任务未返回有效数据，当前子任务无输入来源，已自动跳过。"
)
CONVERSATION_HISTORY_LIMIT_DEFAULT = 6
CONVERSATION_HISTORY_LIMIT_MAX = 10
NON_RETRYABLE_MARKER = "NON_RETRYABLE::OUT_OF_SCOPE"

# Langfuse
langfuse = get_client()
if os.getenv("LANGFUSE_AUTH_CHECK", "disable") == "enable":
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Langfuse authentication failed.")
langfuse_handler = CallbackHandler()

# ---------------------------------------------------------------------------
# Skill runner configuration
# ---------------------------------------------------------------------------
LOCAL_SKILLS_ENABLED = os.getenv("ENABLE_LOCAL_SKILLS", "true").strip().lower() in ("1", "true", "yes")
LOCAL_SKILLS_DIR = os.getenv("LOCAL_SKILLS_DIR", "/app/skills/").strip()
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

ENABLE_CODE_EXEC = os.getenv("ENABLE_CODE_EXEC", "true").strip().lower() in ("1", "true", "yes")
try:
    CODE_EXEC_MAX_RETRIES = int(os.getenv("CODE_EXEC_MAX_RETRIES", "3"))
except (TypeError, ValueError):
    CODE_EXEC_MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# LocalSkill card injection (aligned with orchestrator-agent)
# ---------------------------------------------------------------------------
LOCAL_SKILL_AGENT_NAME = os.getenv("LOCAL_SKILL_AGENT_NAME", "LocalSkill").strip() or "LocalSkill"
LOCAL_SKILL_INJECT_MODE = os.getenv("LOCAL_SKILL_INJECT_CARD", "auto").strip().lower()

# ---------------------------------------------------------------------------
# Dependency guard configuration (aligned with orchestrator-agent)
# ---------------------------------------------------------------------------
DEPENDENCY_CHECK_ENABLED = os.getenv(
    "DEPENDENCY_CHECK_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
try:
    DEPENDENCY_CHECK_TIMEOUT_SEC = float(os.getenv("DEPENDENCY_CHECK_TIMEOUT_SEC", "12"))
except (TypeError, ValueError):
    DEPENDENCY_CHECK_TIMEOUT_SEC = 12.0
try:
    DEPENDENCY_CHECK_MAX_UPSTREAM = int(os.getenv("DEPENDENCY_CHECK_MAX_UPSTREAM", "6"))
except (TypeError, ValueError):
    DEPENDENCY_CHECK_MAX_UPSTREAM = 6
try:
    DEPENDENCY_CHECK_ANSWER_CHARS = int(os.getenv("DEPENDENCY_CHECK_ANSWER_CHARS", "600"))
except (TypeError, ValueError):
    DEPENDENCY_CHECK_ANSWER_CHARS = 600
DEPENDENCY_UNMET_REASON = "dependency_unmet"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _short(text: Any, limit: int = 200) -> str:
    s = str(text or "").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _map_skill_runner_status(raw_status: Any) -> tuple[str, str]:
    s = str(raw_status or "").strip()
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


def _parse_propagated_history(value: Any) -> dict:
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


def _normalize_history_turns(turns: Any) -> list[dict]:
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


def _history_text_from_metadata(md: dict) -> str:
    payload = _parse_propagated_history(md.get(PROPAGATED_HISTORY_KEY))
    turns = _normalize_history_turns(payload.get("turns"))
    lines: list[str] = []
    for item in turns:
        prefix = "human" if item["role"] == "user" else "assistant"
        lines.append(f"{prefix}：{item['content']}")
    return "\n".join(lines) if lines else "（无）"


def _path_to_alias(path: list[str]) -> str:
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
    return _parse_propagated_history(value)


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
    return {"turns": turns, "turn_count": len(turns), "source": source}


def history_text_from_payload(payload: Any) -> str:
    parsed = _parse_propagated_history(payload)
    turns = _normalize_history_turns(parsed.get("turns"))
    lines: list[str] = []
    for item in turns:
        prefix = "human" if item["role"] == "user" else "assistant"
        lines.append(f"{prefix}：{item['content']}")
    return "\n".join(lines)


def history_messages_from_payload(payload: Any) -> list[Union[HumanMessage, AIMessage]]:
    parsed = _parse_propagated_history(payload)
    turns = _normalize_history_turns(parsed.get("turns"))
    messages: list[Union[HumanMessage, AIMessage]] = []
    for item in turns:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        else:
            messages.append(AIMessage(content=item["content"]))
    return messages


def _log_history_turns(turns: list[dict], source: str, max_content_len: int = 600) -> None:
    """Log formatted history turns at INFO level for debugging/tracing."""
    if not turns:
        return
    lines = ["", "=" * 60, f"  GetHistory 查询结果 (来源: {source})", "=" * 60]
    for i, item in enumerate(turns, start=1):
        prefix = "用户" if item["role"] == "user" else "助手"
        content = item.get("content", "")
        content_display = content[:max_content_len]
        if len(content) > max_content_len:
            content_display += f"...（截断，共 {len(content)} 字符）"
        lines.append(f"  ── 第 {i} 轮 ({prefix}) ──")
        lines.append(f"  {content_display}")
        lines.append("")
    lines.append("=" * 60)
    logger.info("\n".join(lines))


# ---------------------------------------------------------------------------
# JSON repair for LLM output
# ---------------------------------------------------------------------------

_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query", "description", "thought_process", "reason", "rationale", "final_answer",
)


def _escape_known_string_field_inner_quotes(text: str) -> str:
    if not text or '"' not in text:
        return text
    pattern_fields = "|".join(re.escape(f) for f in _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
    pattern = re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'
        r'(.*?)'
        r'((?<!\\)"[ \t]*,?[ \t]*$)',
        re.MULTILINE,
    )

    def _repl(m: "re.Match[str]") -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        fixed_chars: List[str] = []
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BaseAgent(BaseModel, ABC):
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}
    agent_name: str = Field(description="The name of the agent.")
    description: str = Field(description="A brief description of the agent's purpose.")
    content_types: list[str] = Field(description="Supported content types.")


class PlannerTask(BaseModel):
    id: int = Field(description="Sequential ID for the task.")
    description: str = Field(description="description of subtask")
    agent: str = Field(description="agent name of the task to be executed.")
    depends_on: list[int] = Field(
        default_factory=list,
        description="List of task IDs that this task depends on.",
    )


class TaskList(BaseModel):
    thought_process: Optional[str] = Field(default=None, description="The internal reasoning steps of the planner.")
    original_query: Optional[str] = Field(description="Verbatim original user query.")
    tasks: List[PlannerTask] = Field(description="A list of tasks to be executed sequentially.")


class TaskStatus(BaseModel):
    id: int = Field(description="Sequential ID for the task.")
    description: str = Field(description="description of subtask")
    agent: str = Field(description="agent name of the task to be executed.")
    answer: str = Field(description="answer of the task.")
    answer_final: str = Field(default="", description="sanitized business answer.")
    diagnostics_excerpt: str = Field(default="", description="diagnostic/process excerpt.")
    marker_present: bool = Field(default=False, description="whether NON_RETRYABLE marker is present.")
    failure_reason_code: str = Field(default="", description="normalized failure reason code.")
    failure_explanation: str = Field(default="", description="failure explanation.")
    missing_requirements: List[str] = Field(default_factory=list, description="missing requirements.")
    status: str = Field(description="the status of the task.")


class CapabilityCheckToolResult(BaseModel):
    """Capability check result for handle_capability_check (aligned with SD orchestrator)."""
    model_config = {"extra": "ignore"}
    can_handle: bool = Field(description="Whether this SG can handle the query")
    can_contribute: bool = Field(description="Whether this SG can contribute")
    contribution: str = Field(description="What this SG can contribute")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0")
    reason: str = Field(description="Detailed reasoning")


def _normalize_capability_result(result_data: dict[str, Any]) -> tuple[bool, bool]:
    """Normalize LLM capability result, aligned with SD orchestrator
    _normalize_member_capability_judgment.

    When can_handle=True, can_contribute is also True.
    """
    can_handle = bool(result_data.get("can_handle", False))
    can_contribute = bool(result_data.get("can_contribute", False))
    if can_handle:
        can_contribute = True
    return can_handle, can_contribute


class DelegationDetectionResult(BaseModel):
    model_config = {"extra": "ignore"}
    needs_help: bool = Field(description="Whether another SG's help is needed")
    synthesized_query: str = Field(description="Scoped sub-query for the downstream SG.")
    target_sgs: List[str] = Field(default_factory=list, description="SG names that should supplement the data gap. Fill when needs_help=true; final selection uses capability_check. Names must be selected from the provided SG list, do NOT invent non-existent SG names.")
    reason: str = Field(description="Why additional data is needed")


class DependentQueryRefineResult(BaseModel):
    model_config = {"extra": "ignore"}
    delegation_query: str = Field(description="Synthesized delegation query body")
    skip: bool = Field(description="Whether to skip delegation")
    reason: str = Field(description="Reason for skip (only when skip=True)")


class TaskOutcomeEval(BaseModel):
    status: Literal["complete", "fail"] = Field(default="fail", description="Task execution outcome")
    confidence: float = Field(default=0.0, description="Evaluation confidence")
    failure_reason_code: str = Field(default="", description="Failure reason code")
    failure_explanation: str = Field(default="", description="Natural language failure explanation")
    missing_requirements: List[str] = Field(default_factory=list, description="Missing requirement units")
    suggested_retry_action: str = Field(default="replan_standard", description="retry_same_plan | replan_standard | abort")


class DependencyJudgeResult(BaseModel):
    """Tool-call schema for dependency guard LLM output."""
    model_config = {"extra": "ignore"}
    needs_upstream: bool = Field(description="Whether the current task relies on upstream output")
    unmet: bool = Field(description="Whether any dependency is unmet")
    unmet_upstream_ids: List[int] = Field(default_factory=list, description="IDs of upstream tasks that block dispatch")


class SummaryEvaluationResult(BaseModel):
    """Tool-call schema for _summarize_with_evaluation LLM output.

    Used by the turn-based retry loop to determine whether the accumulated
    task results are sufficient to answer the user's original question.
    All fields are required (no defaults) — the LLM is forced to provide
    explicit values for every field via the tool-calling mechanism.
    """
    model_config = {"extra": "ignore"}
    answer: str = Field(description="The final answer text for the user")
    satisfactory: bool = Field(
        description="Whether the current information is sufficient to answer the user's question"
    )
    missing_info: str = Field(
        description="When satisfactory=false, describe what information is still missing and should be retrieved in the next turn. When satisfactory=true, set to empty string."
    )
    rationale: str = Field(
        description="One-sentence reason for the evaluation decision (e.g. why the answer is sufficient or insufficient)"
    )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

PLANNER_COT_INSTRUCTIONS_ZH = """
# ⚠ 输出格式（最高优先级，必须最先阅读）

**你必须调用 `make_plan_cmd` 工具输出规划结果。禁止直接输出自然语言文本或 JSON。**
- 思考过程写在 `thought_process` 参数中，不要作为正文输出。
- 所有结论必须通过工具参数交付，不得以任何形式输出到对话正文中。

---

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

### Step 1：数据需求识别
对用户查询，思考并写出：
- **核心数据需求**：要回答这个问题，必须获得**什么业务性质的数据**？用一句话描述。
- **过滤维度**（可空）：这份数据要按什么条件过滤。

### Step 2：数据本体性质判定（核心二分）
对 Step 1 写出的"核心数据需求"，必须明确判定它是：
- **(A) 静态本体数据** — "X 的内在属性 / 自身状态"，那么归属于持有 X 实体生命周期的 Agent；或
- **(B) 动态行为数据** — "由某种动作/事件产生的流水或统计"，那么归属于记录该动作的 Agent。

### Step 3：业务能力语义匹配
逐个审视 [可用智能体]，对每个候选 Agent：
- **读懂它的业务能力范围**，而不是死扣它的描述里出现了哪些字。
- 自问：**Step 1 那份数据，是不是这个 Agent 业务能力的"自然产物 / 直接职责覆盖"？**

### Step 4：路由前自检（强制）
在最终落定 Agent 前，必须在 `thought_process` 中显式回答下面四问：
1. **本体性质**：Step 1 这份数据，是 (A) 静态本体属性 还是 (B) 动态行为产物？
2. **业务覆盖**：选定 Agent 的业务能力，是不是**天然产生 / 直接覆盖**这份数据？
3. **名词陷阱**：我是否仅因为"用户问题里的名词" 与 "Agent 主体名词" 同名就做了路由？
4. **更优候选**：是否存在另一个 Agent，其业务本质比当前选择**更直接地**对应这份数据的产出？

### Step 5：[执行上下文] + [对话历史] 闭环分析
- **结果复用**：若 **[执行上下文]** 中已有相关任务的成功结果，直接继承，严禁创建重复查询任务。
- **路径纠偏（避坑）**：若上下文显示先前尝试已失败，本次规划必须改变策略。
- **历史指代解析**：用 [对话历史] 仅解析"它 / 那个 / 继续 / 更详细一点"等指代，不要把历史中与当前追问无关的过滤条件机械搬运过来。

### Step 6：跨域编排判定
- 当 **数据归属方 ≠ 过滤维度持有方** 时：
  - **首选方案**：让"数据归属方"独立完成查询。
  - **仅当**过滤条件需要先由另一个 Agent 解析为 ID / 枚举 / 名单后才能传给主查询 Agent 时，才安排上游任务。
- 编排顺序：**数据持有方**（产出关联键）→ **数据消费方**（消费关联键），消费方必须在 `depends_on` 中声明依赖。
- 严禁循环依赖（A↔B）。

### Step 7：依赖与描述注入（自洽校验规则）
若当前任务需要先前任务的产出，必须在 `description` 中明确注入（说明需要哪些上游数据，如关键字段、标识符等）。

**描述与依赖的自洽规则（强制）**：
- 若某任务的 `description` 中明确或隐含地依赖了另一个任务的结果（例如描述中出现了"根据上一步"、"需要从上游获取"、"基于任务 X 的结果"、或引用了尚未产出的数据），则该任务的 `depends_on` 字段**必须**包含对应任务的 ID。**禁止出现**描述中声明依赖、但 `depends_on` 为空的自相矛盾情况。
- 同时，若 `depends_on` 非空，则 `description` 中**必须**说明需要从上游获取哪些具体数据或字段，而不是仅笼统写一句"需要从上游获取"。

## 智能体选择规则（必须严格遵守）
1. **数据本体归属优先**：分配给"业务能力天然产出该数据"的 Agent。
2. **领域内隐含能力**：领域专家拥有**该领域内**的全量知识。
3. **⚠ 不可跨域扩张（重点）**：不要假设"X Agent 是 X 全能专家就能处理 X 的 Y"。
4. **任务分解节制**：仅当查询确实涉及**多个不同领域**或存在**明确先后依赖**时才拆分。
5. **"无对应"协议（NONE）**：
   - **仅当**用户问题的**全部**可执行议题都超出当前可用 Agent 的领域范围时，才使用 `agent="NONE"`。
6. **名称准确性**：`agent` 字段必须与智能体列表中的"名称"完全一致。

## ⚠ 反模式（已知路由失败案例 — 必须避免）
1. **名词陷阱（最高频错误）**：把"X 的 Y"中的动态行为数据 Y 当成 X 领域的事。
2. **关键词字面匹配陷阱**：仅因为 Agent 描述里出现了某个相关词就路由。
3. **跨域隐含能力误判**：以为"X 领域专家"能处理"X 的 Y"，而 Y 实际是另一领域的行为产物。
4. **静态/动态判定错误**：把动态行为数据当成静态本体数据。

## ⚠ 跨域串联规则（强制）
当用户查询需要跨 SG 串联两个领域的数据时：
1. 拥有关联键的 SG（**数据持有方**）的任务排在前面。
2. 需要关联键的 SG（**数据消费方**）在其 `depends_on` 中声明对持有方任务的依赖。
3. 消费方任务的 `description` 中需明确说明需要从上游获得的关键字段。

## ⚠ 对话历史使用规则（指代与继承）
1. **仅用于理解指代**：解析"它"、"那个"、"继续"等含义。
2. **禁止无关条件搬运**：不要将历史对话中与当前追问无关的过滤条件搬运到当前任务中。
3. **对比性追问须继承完整上下文**：用户进行对比追问（如"那2024年呢"），必须从历史中完整继承未变化的维度，确保 `description` 语义自包含。
4. **指代追问必须自包含**：对于"更详细一点"这类指代，描述必须补充历史主题，使其对 Agent 而言是完整的。

## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）
1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[执行上下文]** 中的关键结果。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。
4. **保留过滤维度**：当 **谓词数据 ≠ 过滤维度** 时，description 必须保留过滤维度。

---

**[对话历史] (History):**
{history}
*注：包含用户与系统的自然语言对话，用于理解语境和指代。*

**[可用智能体] (Agents):**
{agents}

**[执行上下文] (Information):**
{information}
*注：包含之前已执行的任务 ID、任务描述、执行 Agent 以及执行结果。*

**[组级记忆] (Group Memory):**
{group_memory}
*注：包含长期策略沉淀及 Agent 间协作的特殊规则。*

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本。

工具参数结构：
   - `thought_process`：必须按以下结构化模板输出：
     ```
     [Step1 数据需求] 核心数据需求=...; 过滤维度=...
     [Step2 本体性质] (A) 静态本体 / (B) 动态行为产物 二选一
     [Step3 业务能力匹配] 逐个候选 Agent: 是否"业务能力天然产出 / 直接职责覆盖"该数据?
     [Step4 自检] (1) 本体性质判定与所选 Agent 业务能力是否相容? (2) 是否仅因名词同名/字面相关而路由? (3) 是否存在业务本质更直接对应的另一 Agent?
     [Step5 上下文/历史] 是否复用先前结果 / 是否需要纠偏 / 历史指代解析（简述）
     [Step6 跨域] 是否拆分及理由
     ```
   - `original_query`：逐字复制原始用户输入。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务（忠实于用户原始表述）。
     - `agent`：确切的智能体名称或"NONE"。
     - `depends_on`：整数列表，标明此任务依赖哪些 task id 必须先完成。

## `make_plan_cmd` 工具参数示例
{instructions}

或当未找到智能体时：
{none_instructions}

问题：

"""

PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# ⚠ 输出格式（最高优先级，必须最先阅读）

**你必须调用 `make_plan_cmd` 工具输出规划结果。禁止直接输出自然语言文本或 JSON。**
- 思考过程写在 `thought_process` 参数中，不要作为正文输出。
- 所有结论必须通过工具参数交付，不得以任何形式输出到对话正文中。

---

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

### Step 1：数据需求识别
对用户查询，思考并写出：
- **核心数据需求**：要回答这个问题，必须获得**什么业务性质的数据**？用一句话描述。
- **过滤维度**（可空）：这份数据要按什么条件过滤。

### Step 2：数据本体性质判定（核心二分）
对 Step 1 写出的"核心数据需求"，必须明确判定它是：
- **(A) 静态本体数据** — "X 的内在属性 / 自身状态"，那么归属于持有 X 实体生命周期的 Agent；或
- **(B) 动态行为数据** — "由某种动作/事件产生的流水或统计"，那么归属于记录该动作的 Agent。

### Step 3：业务能力语义匹配
逐个审视 [可用智能体]，对每个候选 Agent：
- **读懂它的业务能力范围**，而不是死扣它的描述里出现了哪些字。
- 自问：**Step 1 那份数据，是不是这个 Agent 业务能力的"自然产物 / 直接职责覆盖"？**

### Step 4：路由前自检（强制）
在最终落定 Agent 前，必须在 `thought_process` 中显式回答下面四问：
1. **本体性质**：Step 1 这份数据，是 (A) 静态本体属性 还是 (B) 动态行为产物？
2. **业务覆盖**：选定 Agent 的业务能力，是不是**天然产生 / 直接覆盖**这份数据？
3. **名词陷阱**：我是否仅因为"用户问题里的名词" 与 "Agent 主体名词" 同名就做了路由？
4. **更优候选**：是否存在另一个 Agent，其业务本质比当前选择**更直接地**对应这份数据的产出？

### Step 5：[执行上下文] + [对话历史] 闭环分析
- **结果复用**：若 **[执行上下文]** 中已有相关任务的成功结果，直接继承，严禁创建重复查询任务。
- **路径纠偏（避坑）**：若上下文显示先前尝试已失败，本次规划必须改变策略。
- **历史指代解析**：用 [对话历史] 仅解析"它 / 那个 / 继续 / 更详细一点"等指代，不要把历史中与当前追问无关的过滤条件机械搬运过来。

### Step 6：跨域编排判定
- 当 **数据归属方 ≠ 过滤维度持有方** 时：
  - **首选方案**：让"数据归属方"独立完成查询。
  - **仅当**过滤条件需要先由另一个 Agent 解析为 ID / 枚举 / 名单后才能传给主查询 Agent 时，才安排上游任务。
- 编排顺序：**数据持有方**（产出关联键）→ **数据消费方**（消费关联键），消费方必须在 `depends_on` 中声明依赖。
- 严禁循环依赖（A↔B）。

### Step 7：依赖与描述注入（自洽校验规则）
若当前任务需要先前任务的产出，必须在 `description` 中明确注入（说明需要哪些上游数据，如关键字段、标识符等）。

**描述与依赖的自洽规则（强制）**：
- 若某任务的 `description` 中明确或隐含地依赖了另一个任务的结果（例如描述中出现了"根据上一步"、"需要从上游获取"、"基于任务 X 的结果"、或引用了尚未产出的数据），则该任务的 `depends_on` 字段**必须**包含对应任务的 ID。**禁止出现**描述中声明依赖、但 `depends_on` 为空的自相矛盾情况。
- 同时，若 `depends_on` 非空，则 `description` 中**必须**说明需要从上游获取哪些具体数据或字段，而不是仅笼统写一句"需要从上游获取"。

## 智能体选择规则（必须严格遵守）
1. **数据本体归属优先**：分配给"业务能力天然产出该数据"的 Agent。
2. **领域内隐含能力**：领域专家拥有**该领域内**的全量知识。
3. **⚠ 不可跨域扩张（重点）**：不要假设"X Agent 是 X 全能专家就能处理 X 的 Y"。
4. **任务分解节制**：仅当查询确实涉及**多个不同领域**或存在**明确先后依赖**时才拆分。
5. **"无对应"协议（NONE）**：
   - **仅当**用户问题的**全部**可执行议题都超出当前可用 Agent 的领域范围时，才使用 `agent="NONE"`。
6. **名称准确性**：`agent` 字段必须与智能体列表中的"名称"完全一致。

## ⚠ 反模式（已知路由失败案例 — 必须避免）
1. **名词陷阱（最高频错误）**：把"X 的 Y"中的动态行为数据 Y 当成 X 领域的事。
2. **关键词字面匹配陷阱**：仅因为 Agent 描述里出现了某个相关词就路由。
3. **跨域隐含能力误判**：以为"X 领域专家"能处理"X 的 Y"，而 Y 实际是另一领域的行为产物。
4. **静态/动态判定错误**：把动态行为数据当成静态本体数据。

## ⚠ 跨域串联规则（强制）
当用户查询需要跨 SG 串联两个领域的数据时：
1. 拥有关联键的 SG（**数据持有方**）的任务排在前面。
2. 需要关联键的 SG（**数据消费方**）在其 `depends_on` 中声明对持有方任务的依赖。
3. 消费方任务的 `description` 中需明确说明需要从上游获得的关键字段。

## ⚠ 对话历史使用规则（指代与继承）
1. **仅用于理解指代**：解析"它"、"那个"、"继续"等含义。
2. **禁止无关条件搬运**：不要将历史对话中与当前追问无关的过滤条件搬运到当前任务中。
3. **对比性追问须继承完整上下文**：用户进行对比追问（如"那2024年呢"），必须从历史中完整继承未变化的维度，确保 `description` 语义自包含。
4. **指代追问必须自包含**：对于"更详细一点"这类指代，描述必须补充历史主题，使其对 Agent 而言是完整的。

## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）
1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[执行上下文]** 中的关键结果。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。
4. **保留过滤维度**：当 **谓词数据 ≠ 过滤维度** 时，description 必须保留过滤维度。

---

**[对话历史] (History):**
{history}
*注：包含用户与系统的自然语言对话，用于理解语境和指代。*

**[可用智能体] (Agents):**
{agents}

**[执行上下文] (Information):**
{information}
*注：包含之前已执行的任务 ID、任务描述、执行 Agent 以及执行结果。*

**[组级记忆] (Group Memory):**
{group_memory}
*注：包含长期策略沉淀及 Agent 间协作的特殊规则。*

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本。

工具参数结构：
   - `thought_process`：必须按以下结构化模板输出：
     ```
     [Step1 数据需求] 核心数据需求=...; 过滤维度=...
     [Step2 本体性质] (A) 静态本体 / (B) 动态行为产物 二选一
     [Step3 业务能力匹配] 逐个候选 Agent: 是否"业务能力天然产出 / 直接职责覆盖"该数据?
     [Step4 自检] (1) 本体性质判定与所选 Agent 业务能力是否相容? (2) 是否仅因名词同名/字面相关而路由? (3) 是否存在业务本质更直接对应的另一 Agent?
     [Step5 上下文/历史] 是否复用先前结果 / 是否需要纠偏 / 历史指代解析（简述）
     [Step6 跨域] 是否拆分及理由
     ```
   - `original_query`：逐字复制原始用户输入。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务（忠实于用户原始表述）。
     - `agent`：确切的智能体名称或"NONE"。
     - `depends_on`：整数列表，标明此任务依赖哪些 task id 必须先完成。

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
   * 你的所有事实性结论必须源于 `knowledge`。`history` 仅用于理解当前问题的指代或语境。
   * **严禁幻觉**：禁止编造 `knowledge` 中不存在的数字、日期或具体事实。
   * **不确定不猜测**：凡是上下文证据不足、字段缺失、口径冲突或无法确认的内容，不要自行补全或猜测。

2. **信息处理与灵活匹配**
   * **精确匹配**：若 `knowledge` 包含原始问题所需的全部精确信息，请直接进行整合归纳。
   * **退守匹配**：若 `knowledge` 中缺乏原始问题要求的"精确时间点"或"精确维度"的数据，但包含**高度相关**的信息，你应当：
     1. 告知用户当前缺乏精确到 [具体维度] 的数据。
     2. 主动提供 `knowledge` 中现有的、最接近的参考数据作为替代。
     3. 严禁直接回答"没有数据"，除非 `knowledge` 与问题完全无关。

3. **回答表现形式**
   * **逻辑性**：使用分点、表格或对比等方式让答案易于阅读。
   * **默认结构**：先用 1-2 句给出结论；当答案里包含多个数字、属性、对象信息或对比关系时，优先补一个简短的"关键依据"或"补充信息"小节。
   * **轻量格式优先**：默认使用短标题、项目符号或简短表格提升可读性。
   * **标题自然**：不要机械使用"直接答案""补充说明"这类模板化标题。

4. **判定"无法回答"的标准**
   * 只有当 `knowledge` 内容与问题**毫无关联**，或信息量极度匮乏时，才触发该规则。
   * **此时回复**：「抱歉，目前的知识库中暂无与 [原始问题关键点] 直接或间接相关的信息。」

5. **多轮对话处理**
   * 始终以最新的 `knowledge` 为最高准则。若 `history` 中之前的结论与当前 `knowledge` 不符，请以 `knowledge` 为准。

6. **证据约束（强制）**
   * 只输出可被 `knowledge` 直接支持的结论。
   * 默认不输出推测性内容。

7. **收敛输出（强制）**
   * 必须先给结论，首段 1-2 句内明确回答用户问题核心结论。
   * 默认使用轻量结构化表达提升可读性。
   * 若用户未明确要求扩展分析，默认不要主动展开这些内容。
"""

SKILL_CAPABILITY_CHECK_PROMPT = """# Role: capability judge for a skill agent

You are a capability judge for a skill agent. Your task is to determine whether
this agent can handle or contribute to the user's query, based on domain
alignment and skill inventory.

Think step by step, then call evaluate_capability.

## Core Principle: Domain-First Decision

The fundamental question is: **does this agent's primary domain match the
primary domain of the user's query?**

### Decision Steps (follow in order):

D1) **Identify the query's primary domain(s).**
    What is the main subject / topic the user is asking about? Look at the
    central entity, the core question being asked, or the main problem area.
    A query may touch multiple domains. If the query has a single clear
    primary domain, identify it. If the query explicitly asks about two or
    more domains as parallel, equally-weighted concerns (e.g., "同时排查 A 和 B",
    "既需要 X 也需要 Y"), there may be MULTIPLE peer primary domains — each is
    an equally valid primary domain from the perspective of its respective agent.

    **Distinguishing peer vs. secondary**: A domain is a PEER primary domain
    only when it is presented as a first-class problem/concern, not merely a
    supporting check to help diagnose the main problem. Key signals:
    - Peer: "同时排查 A 和 B", "分别检查 X 和 Y", "X 和 Y 都需要确认"
    - Secondary: "排查 A 的同时看看 B", "A 出了问题，顺便确认下 B",
      "主要排查 A，同时 B 也查一下", "排查 A（原因），同时确认 B（是否受牵连）"
    When one domain is the CLEAR trigger/root problem and the other is just a
    supporting check to help explain it, the trigger domain is the PRIMARY
    domain and the supporting check is SECONDARY.

D2) **Compare with the agent's domain.**
    Determine whether this agent's domain (inferred from its name, description,
    and skill inventory) matches the query's primary domain. This is a topical
    / subject-matter judgment, not a completeness check.

D3) **Determine can_handle and can_contribute.**

## Core Rules

### Rule 1: Primary Domain Match → can_handle = true

If the agent's primary domain MATCHES the query's domain (or at least one of
the query's peer primary domains from D1), set **can_handle = true**, regardless
of how complex the query is.

**Key insight**: A complex query may require multiple agents to fully solve.
That does NOT mean this agent cannot handle it. If the query's domain (or one
of its peer domains) is this agent's domain, this agent is the right owner for
that portion. Other agents can collaborate to fill in the gaps. Do NOT downgrade
to can_handle=false just because the query is complex or spans multiple domains.

**Peer domain rule**: When the query has multiple TRUE peer-level primary domains
(see D1 definition — both are first-class problems, not one supporting the other),
the agent whose domain matches ANY of those peer domains should get can_handle=true.
Multiple agents can each be can_handle=true for the same query — each handles
their own domain and collaborates on the rest.

**Important — when NOT to use peer domain rule**: If the query has ONE clear
trigger/root problem (primary domain) and the other mentioned domains are just
supporting checks to help diagnose it, those supporting checks are SECONDARY
domains. The agent for the secondary domain should get can_handle=false,
can_contribute=true. 

Examples of domain match (can_handle=true):
- Query: "Analyze the deployment status of service X and check if there are
  related alerts" → primary domain = deployment/operations. If this agent is a
  deployment agent, can_handle=true, even though alerts may need another agent.
- Query: "Monitor the database performance and suggest optimizations" →
  primary domain = database. If this agent is a database monitoring agent,
  can_handle=true, even though optimization suggestions may need another agent.
- Query: "排查数据库连接数异常增长和部署配置变更" → peer primary domains =
  database AND deployment. If this agent is a DB agent, can_handle=true.
  If this agent is a deploy agent, ALSO can_handle=true. Both are valid.

### Rule 2: Not Primary Domain, But Concrete Overlap → can_contribute = true

If the agent's domain is NOT the query's primary domain, but the agent's skill
inventory can concretely supply a needed slice of the answer, set
**can_handle = false, can_contribute = true**.

"Concrete overlap" means the agent's skills can actually answer a specific
sub-question or provide a specific data point the user is asking for. Vague
"might be helpful" or "the agent knows about related things" is NOT enough.

Examples of concrete contribution (can_contribute=true):
- Query: "Analyze the deployment status of service X and check related alerts"
  → primary domain = deployment. If this agent is an alert monitoring agent,
  it can contribute the alert data (can_handle=false, can_contribute=true).
- Query: "Investigate the root cause of a slow API response" → primary domain
  = API/investigation. If this agent is a database agent that can provide
  query latency data, can_handle=false, can_contribute=true.

### Rule 3: No Domain Overlap → can_handle = false, can_contribute = false

If the agent's domain has nothing to do with the query, set both to false.
A neighboring domain that cannot answer any concrete asked question is
insufficient.

### Rule 4: Evidence from Skill Inventory

- **Skill inventory** (loaded skills listed below) is the primary evidence
  for what this agent can actually do.
- Agent name and description provide domain context but are NOT sufficient
  alone to prove can_handle. The inventory must back it up.
- If the agent's inventory clearly covers the query's primary domain but
  lacks some related sub-topics, keep can_handle=true and note the gaps in
  the reason field — do NOT downgrade.

### Rule 5: Complex / Multi-Domain Queries

When a query is complex and spans multiple domains:
- The agent whose domain matches the query's domain (or one of its peer domains
  from D1) → can_handle=true.
- Agents whose domains match SECONDARY aspects → can_contribute=true.
- Multiple agents can simultaneously have can_handle=true for the same query
  when the query has multiple peer-level primary domains.
- Do not deny can_handle just because the query needs other agents too.
- Do not confuse "can fully answer alone" with "can handle". An agent can
  handle a query even if it needs collaboration.
- When judging whether a domain is primary or secondary, look at the perspective
  of THIS agent — if the query asks about this agent's domain as a first-class
  topic (not just a supporting check), it is a primary domain for this agent.

### Rule 6: Confidence

- domain match + inventory covers the core → confidence >= 0.8
- domain match but inventory has gaps → confidence 0.5–0.8
- no domain match but concrete contribution → confidence 0.3–0.5
- no domain overlap → confidence 0.0–0.2

---
Agent info:
- name: {agent_name}
- description: {agent_description}
- skill inventory (loaded skills; evidence for judgment):
{agent_skills}

History:
{history}

User query:
{query}

---
Output guidance:
- Put your D1–D3 step-by-step reasoning into the reason field.
- Call evaluate_capability to output the verdict.
"""


# ---------------------------------------------------------------------------
# Mid-exec detection prompts
# ---------------------------------------------------------------------------

MID_EXEC_DETECT_PROMPT_ZH = """你是一个任务差距检测器，负责判断当前任务执行结果是否满足用户原始问题要求。

## 输入
- **原始用户问题**: {original_query}
- **当前任务描述**: {task_description}
- **当前任务执行结果**: {task_result}
- **已执行的其他任务结果**: {other_results}

## 判定标准
1. 判断当前结果是否完全覆盖了原始问题的核心需求
2. 如果存在缺失，明确指出缺失什么数据、需要哪个业务领域的支持
3. 如果有缺失，合成一个精确的子查询，只包含缺失部分需要的字段和条件

## 输出格式
调用 `detect_gap` 工具，参数：
- `needs_help`: 是否需要其他 Agent 的帮助
- `synthesized_query`: 精确的子查询（仅缺失部分，不要重复原问题已覆盖的内容）
- `target_sgs`: 建议的业务领域名称列表（可选）
- `reason`: 为什么需要帮助的详细说明
"""


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent(BaseAgent):
    """Planner Agent — decomposes user queries into executable tasks."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_services_url: str = None,
        metadata: dict = None,
        agent_id: str = None,
    ):
        logger.info("Initializing PlannerAgent")
        super().__init__(
            agent_name="PlannerAgent",
            description="Breakdown the user request into executable tasks",
            content_types=["text", "text/plain"],
        )
        self.manager = ModelManager()
        _extra_body = (
            {"enable_thinking": False}
            if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
            else {}
        )
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        try:
            self.llm = self.llm.bind_tools(
                [self.make_plan_tool],
                tool_choice="make_plan_cmd",
            )
        except TypeError:
            logger.warning(
                "[PlannerAgent] tool_choice='make_plan_cmd' not supported by provider=%s model=%s, "
                "falling back to bind_tools without tool_choice — LLM may produce text instead of tool calls",
                provider, model,
            )
            self.llm = self.llm.bind_tools([self.make_plan_tool])
        self.make_plan_max_attempts = int(os.getenv("MAKE_PLAN_MAX_ATTEMPTS", "3"))
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.agent_id = agent_id

    make_plan_tool: ClassVar[Any]

    @tool("make_plan_cmd", args_schema=TaskList, description="Create a structured plan with tasks to be executed sequentially.")
    def make_plan_tool(
        thought_process: Optional[str] = None,
        original_query: Optional[str] = None,
        tasks: List[PlannerTask] = None,
    ) -> str:
        plan_data = {
            "thought_process": thought_process,
            "original_query": original_query,
            "tasks": [
                task.dict() if isinstance(task, PlannerTask) else task for task in (tasks or [])
            ],
        }
        return json.dumps(plan_data, ensure_ascii=False)

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
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        turns = _normalize_history_turns(propagated.get("turns"))
        if turns:
            _log_history_turns(turns, source="propagated")
            return history_text_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
            user_id=self.metadata.get("user_id", ""),
            run_id=self.metadata.get("run_id", ""),
            limit=get_conversation_history_limit(),
        )
        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        payload = history_payload_from_search_items(search_items, source="skill_agent_planner_fallback")
        _log_history_turns(payload.get("turns", []), source="data-services API")
        return history_text_from_payload(payload)

    def format_llm_output(self, answer) -> dict:
        raw = getattr(answer, "content", "") or ""
        try:
            return json.loads(raw, strict=False)
        except json.JSONDecodeError:
            pass

        cleaned_content = raw.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        elif cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            return json.loads(cleaned_content, strict=False)
        except json.JSONDecodeError:
            pass

        escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                return json.loads(escaped_content, strict=False)
            except json.JSONDecodeError:
                pass

        if _json_repair is not None:
            try:
                repaired = _json_repair(escaped_content, return_objects=True)
                if isinstance(repaired, dict):
                    return repaired
            except Exception:
                pass

        try:
            import ast
            parsed = ast.literal_eval(cleaned_content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass

        try:
            return json.loads(cleaned_content.replace("'", '"'), strict=False)
        except json.JSONDecodeError:
            pass

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
                    "REPLAN_CONTEXT(JSON):\n" + json.dumps(replan_context, ensure_ascii=False)
                )
            if replan_guidance:
                info_parts.append(f"REPLAN_GUIDANCE:\n{replan_guidance}")
            information = "\n\n".join(info_parts)

        system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY

        human_template = "{query}"

        json_prompt_instructions_en: dict = {
            "thought_process": "[Step1 Data Need] Subq1: core-need=current real-time meteorological observation for Beijing, filter=city(Beijing)+now; Subq2: core-need=outfit/styling advice matching the given weather, filter=that weather condition. [Step2 Ontology] Subq1=(A) Static-State (weather observations exist objectively regardless of any query); Subq2=(B) Dynamic-Output (advice produced by a styling inference action). [Step3 Capability Semantics] Weather-Checker's business is to fetch and serve meteorological state → Subq1 is its direct duty → owns Subq1; Fashion-Consultant's business is to produce outfit advice from a context → Subq2 is its natural output → owns Subq2. [Step4 Self-Check] (1) Ontology vs chosen agent's capability are aligned: yes; (2) Routed solely by noun/keyword coincidence: no, based on business essence; (3) Any agent more essentially aligned: none. [Step5 Context] No reusable prior result, no correction needed. [Step6 Cross-Domain] Two distinct domains (meteorology vs lifestyle) with sequential dependency, so split into two tasks with dependency. Note: description faithfully relays user's words without adding extra conditions.",
            "original_query": "Help me check the weather in Beijing and recommend suitable clothing advice",
            "tasks": [
                {"id": 1, "description": "Check the weather in Beijing", "agent": "Weather-Checker", "depends_on": []},
                {"id": 2, "description": "Recommend suitable clothing advice", "agent": "Fashion-Consultant", "depends_on": [1]},
            ],
        }

        json_prompt_no_agent_en: dict = {
            "thought_process": "[Step1 Data Need] core-need=knowledge/explanation about the Starlink project (aerospace + satellite-communication domain), filter=Starlink. [Step2 Ontology] (B) Dynamic-Output (an explanation produced by a knowledge-bearing agent). [Step3 Capability Semantics] Reviewed every available agent's business essence — none of them naturally produces aerospace/satellite knowledge as a core duty. [Step4 Self-Check] (1) No agent's business naturally covers this need: confirmed; (2) Not routed by noun coincidence: yes; (3) Any agent more essentially aligned: none. [Step5 Context] N/A. [Step6 Cross-Domain] N/A. Conclusion: subject lies outside every available agent's business sovereignty, fall back to NONE.",
            "original_query": "What is the Starlink project?",
            "tasks": [
                {"id": 1, "description": NONE_TASK_DESCRIPTION, "agent": "NONE"},
            ],
        }

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["history", "agents", "information", "group_memory"],
            partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
        )
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self.metadata.get("trace_id", "")

        history = await self.get_history()

        format_kwargs = {
            "query": query,
            "agents": system_prompt_agents,
            "information": information,
            "group_memory": group_memory,
            "history": history,
        }
        messages = chat_prompt.format_messages(**format_kwargs)

        tasks = None

        with langfuse.start_as_current_span(
            name="skill-agent-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            for attempt in range(1, self.make_plan_max_attempts + 1):
                logger.info("make_plan llm_invoke attempt=%d/%d", attempt, self.make_plan_max_attempts)
                answer = await self.llm.ainvoke(messages, config={"callbacks": [langfuse_handler]})
                messages.append(answer)
                tool_calls = getattr(answer, "tool_calls", None) or []

                if not tool_calls:
                    logger.warning("make_plan attempt %s: no tool call, nudging.", attempt)
                    messages.append(HumanMessage(content="你上一次没有调用工具。请**必须**调用 `make_plan_cmd` 工具来输出规划结果。"))
                    continue

                call = next((c for c in tool_calls if c.get("name") == "make_plan_cmd"), None)
                if call is None:
                    logger.warning("make_plan attempt %s: unknown tool, nudging.", attempt)
                    messages.append(HumanMessage(content="你调用了未知工具。请只使用 `make_plan_cmd` 工具。"))
                    continue

                args = call.get("args", {}) or {}
                try:
                    tasks = TaskList(
                        thought_process=args.get("thought_process"),
                        original_query=str(query),
                        tasks=args.get("tasks") or [],
                    )
                except Exception as e:
                    logger.warning("make_plan attempt %s: failed to parse TaskList: %s, nudging.", attempt, e)
                    messages.append(HumanMessage(content=f"工具调用参数解析失败: {e}。请检查然后重新调用 `make_plan_cmd`。"))
                    continue

                if not tasks.tasks:
                    logger.warning("make_plan attempt %s: empty tasks list, nudging.", attempt)
                    messages.append(HumanMessage(content=f"你返回的 `tasks` 列表为空。如果确实没有合适的智能体，请使用 agent='NONE' 和 description='{NONE_TASK_DESCRIPTION}'。"))
                    continue

                logger.info("make_plan SELECTED attempt=%d tasks_count=%d", attempt, len(tasks.tasks))
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
                thought_process=f"Planner failed to produce a valid plan after {self.make_plan_max_attempts} attempts.",
                original_query=str(query),
                tasks=[PlannerTask(id=1, description=NONE_TASK_DESCRIPTION, agent="NONE")],
            )

        logger.info(" === PlannerAgent.make_plan , tasks = %s", tasks)
        return tasks


# ---------------------------------------------------------------------------
# SkillAgent (per-request handler)
# ---------------------------------------------------------------------------

class SkillAgent(BaseAgent):
    """Per-request wrapper that runs one SkillRunner.plan_and_run call."""

    def __init__(
        self,
        *,
        skill_runner: "SkillRunner | None" = None,
        query: str | None = None,
        metadata: dict | None = None,
        current_task_id: int | None = None,
        agent_id: str = "SkillAgent",
    ):
        super().__init__(
            agent_name="SkillAgent",
            description="Run a local skill pack selected from the loaded skill library.",
            content_types=["text", "text/plain"],
        )
        self.skill_runner = skill_runner
        self.query = query
        self.original_query = query
        self.metadata = metadata or {}
        self.current_task_id = current_task_id
        self.agent_id = agent_id
        self.reason_code: str = ""

    def _log_propagated_history(self) -> None:
        payload = _parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        turns = _normalize_history_turns(payload.get("turns"))
        if not turns:
            return
        lines = ["", "=" * 60, "  SkillAgent 接收到的历史对话数据", "=" * 60]
        for i, item in enumerate(turns, start=1):
            prefix = "用户" if item["role"] == "user" else "助手"
            content_display = item["content"][:600]
            if len(item["content"]) > 600:
                content_display += "...（截断）"
            lines.append(f"  ── 第 {i} 轮 ({prefix}) ──")
            lines.append(f"  {content_display}")
            lines.append("")
        lines.append("=" * 60)
        logger.info("\n".join(lines))

    def _build_query_with_history(self, query: str) -> str:
        history_text = _history_text_from_metadata(self.metadata)
        if history_text and history_text != "（无）":
            return f"当前问题: {query}\n\n【历史对话上下文】\n{history_text}"
        return query

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
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload: Dict[str, Any] = {
            "schema_version": "v1",
            "layer": DAC_PROGRESS_LAYER,
            "event": event,
            "run_id": run_id or "",
            "user_id": user_id or "",
            "agent_id": agent_id or "",
            "task_id": task_id,
            "message": message or "",
            "status": status or "",
        }
        if extra:
            payload["extra"] = extra
        return f"{PROGRESS_FRAME_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"

    async def emit_progress(
        self,
        event: str,
        *,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        callback = getattr(self, "progress_callback", None)
        if callback is None:
            return
        await callback(self.build_progress_frame(
            event,
            message=message,
            status=status,
            run_id=self.metadata.get("run_id", ""),
            user_id=self.metadata.get("user_id", ""),
            agent_id=self.agent_id,
            task_id=task_id,
            extra=extra,
        ))

    async def run(self) -> AsyncIterable[str]:
        query = (self.query or "").strip()
        query_preview = _short(query)

        if self.skill_runner is None or SkillRunner is None:
            reason = "SkillRunner unavailable: ENABLE_LOCAL_SKILLS or skill_sdk import failed."
            logger.warning("[LocalSkill][Run] %s", reason)
            yield reason
            return

        trace_id = self.metadata.get("trace_id")
        user_id = self.metadata.get("user_id")
        run_id = self.metadata.get("run_id")

        effective_query = self._build_query_with_history(query)

        await self.emit_progress(
            "sd_skill_started",
            message=f"running local skill | query: {query_preview}",
            status="running",
            task_id=self.current_task_id,
            extra={"skill_query": query_preview},
        )

        t0 = _time.perf_counter()
        try:
            result = await self.skill_runner.plan_and_run(
                query=effective_query,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        except asyncio.CancelledError:
            logger.warning("[LocalSkill][RunCancel] cancelled")
            raise
        except Exception as exc:
            logger.exception("[LocalSkill][RunError] plan_and_run raised")
            result = {
                "status": "local_skill_error",
                "skill": "",
                "final_answer": f"LocalSkill execution error: {exc}",
                "attempts": [],
            }

        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        status_code, reason_code = _map_skill_runner_status(result.get("status"))
        self.reason_code = reason_code
        final_answer = str(result.get("final_answer") or "").strip()
        skill_name_used = str(result.get("skill") or "")

        display_answer = final_answer or (
            f"LocalSkill did not produce a final answer (status={result.get('status')})."
        )

        await self.emit_progress(
            "sd_skill_finished",
            message=f"completed skill {skill_name_used or '(unknown)'}" if status_code == "complete"
            else f"skill failed ({reason_code or 'error'})",
            status="done" if status_code == "complete" else "fail",
            task_id=self.current_task_id,
            extra={
                "skill_name": skill_name_used,
                "skill_status": str(result.get("status") or ""),
                "skill_attempts": len(result.get("attempts") or []),
                "reason_code": reason_code,
                "elapsed_ms": elapsed_ms,
            },
        )

        yield display_answer


# ---------------------------------------------------------------------------
# SkillAgentExecutor (the main A2A executor, upgraded with full orchestration)
# ---------------------------------------------------------------------------

class SkillAgentExecutor(AgentExecutor):
    """A2A executor that owns a process-wide SkillRunner and full orchestration capabilities.

    Upgraded capabilities:
      1. Proactive capability broadcast
      2. PlannerAgent for task decomposition
      3. Mid-execution gap detection and broadcast delegation
      4. Cross-SG collaboration (delegation to peer agents)
      5. LLM summarization of multi-source results
      6. Dependent task query refinement with upstream context
    """

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        max_steps: int = 20,
        data_services_url: str = None,
        agent_id: str = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.stream = stream
        self.stream_enabled = stream
        self.temperature = temperature
        self.max_steps = max_steps
        self.data_services_url = data_services_url or "http://data-services.dac.svc.cluster.local:8000"
        self.agent_id = agent_id or os.getenv("Agent_Name", "SkillAgent").strip() or "SkillAgent"
        self.agent_card: AgentCard | None = None
        self.metadata: dict = {}

        # SkillRunner
        self._skill_runner: "SkillRunner | None" = None
        self._skill_runner_initialised = False
        self._skill_runner_lock = asyncio.Lock()
        self._log_skill_executor_config()

        # Planner
        self._planner: Optional[PlannerAgent] = None

        # Orchestration LLM (for summary, mid-exec detection, etc.)
        self._orchestration_llm = None

        # Progress context
        self._progress_context: dict = {}

        # Routing pool state (aligned with orchestrator-agent)
        self._routing_agent_pool: list[dict] = []
        self._routing_skip_broadcast_used = False

        # LocalSkill card injection (aligned with orchestrator-agent)
        self.local_skill_agent_name = LOCAL_SKILL_AGENT_NAME

        # Data services client (for memory/history)
        self._data_services_client = DataServicesClient(
            base_url=self.data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )

    def _log_skill_executor_config(self) -> None:
        logger.info(
            "[LocalSkill][Config] env snapshot: "
            "ENABLE_LOCAL_SKILLS=%s LOCAL_SKILLS_DIR=%r "
            "LOCAL_SKILL_MAX_STEPS=%d LOCAL_SKILL_CMD_TIMEOUT_SEC=%d "
            "LOCAL_SKILL_MAX_CONCURRENCY=%d ENABLE_CODE_EXEC=%s",
            LOCAL_SKILLS_ENABLED,
            LOCAL_SKILLS_DIR,
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
            LOCAL_SKILL_MAX_CONCURRENCY,
            ENABLE_CODE_EXEC,
        )

    def _get_orchestration_llm(self):
        if self._orchestration_llm is None:
            mgr = ModelManager()
            _extra_body = (
                {"enable_thinking": False}
                if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
                else {}
            )
            self._orchestration_llm = mgr.get_llm(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=0.01,
                stream=False,
                extra_body=_extra_body,
            )
        return self._orchestration_llm

    def _get_planner(self) -> PlannerAgent:
        if self._planner is None:
            self._planner = PlannerAgent(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=self.temperature,
                data_services_url=self.data_services_url,
                metadata=self.metadata,
                agent_id=self.agent_id,
            )
        else:
            # Update metadata on each request so get_history() can access the
            # current request's user_id, run_id, and propagated_history.
            self._planner.metadata = self.metadata if isinstance(self.metadata, dict) else {}
        return self._planner

    # ------------------------------------------------------------------
    # Routing pool flow + group_memory (aligned with orchestrator-agent)
    # ------------------------------------------------------------------

    def _routing_pool_flow_enabled(self) -> bool:
        return os.getenv("ENABLE_ROUTING_AGENT_POOL", "true").strip().lower() in ("true", "1", "yes")

    def _sg_capability_rebroadcast_enabled(self) -> bool:
        return os.getenv("ENABLE_SG_CAPABILITY_REBROADCAST", "true").strip().lower() in ("true", "1", "yes")

    def _self_planner_agent_name(self) -> str:
        if self.agent_card and getattr(self.agent_card, "name", None):
            return str(self.agent_card.name)
        return (self.agent_id or "").strip()

    # ------------------------------------------------------------------
    # LocalSkill (route B) helpers (aligned with orchestrator-agent)
    # ------------------------------------------------------------------

    def _has_local_skill(self) -> bool:
        return self._skill_runner is not None and SkillRunner is not None

    def _is_local_skill_task(self, task: "PlannerTask") -> bool:
        if not self._has_local_skill():
            return False
        return (getattr(task, "agent", "") or "").strip() == self.local_skill_agent_name

    def _apply_local_skill_reason_code(self, task_id: int, reason_code: str) -> None:
        """Overwrite the failure_reason_code on a task_status entry.

        ``_tasks_status_list`` entries may not have ``failure_reason_code`` set
        when the task outcome is determined without a TaskOutcomeEval. For
        LocalSkill runs there is no TaskOutcomeEval, so we set the code directly
        so dependency guard and replan logic can distinguish failure causes.
        """
        if not reason_code:
            return
        for ts in self._tasks_status_list or []:
            if ts.get("id") == task_id:
                ts["failure_reason_code"] = reason_code
                break

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
            skills_loaded = len(getattr(self._skill_runner.lister, "skills", []) or [])
        except Exception:
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
            for s in (self._skill_runner.lister.skills or []):
                name = str(getattr(s, "name", "") or "").strip()
                desc = str(getattr(s, "description", "") or "").strip().replace("\n", " ")
                if len(desc) > 140:
                    desc = desc[:140] + "..."
                if name:
                    lines.append(f"- {name}: {desc}")
        except Exception:
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

    def _maybe_append_local_skill_card(self, cards: list[AgentCard]) -> list[AgentCard]:
        """Append the synthetic LocalSkill card when route B is enabled + allowed."""
        if not self._should_inject_local_skill_card():
            return cards
        try:
            card = self._build_local_skill_card()
        except Exception:
            logger.exception(
                "[LocalSkill][Inject] failed to build local skill AgentCard; skipping injection"
            )
            return cards
        try:
            skills_count = len(getattr(self._skill_runner.lister, "skills", []) or [])
        except Exception:
            skills_count = -1
        logger.info(
            "[LocalSkill][Inject] appended synthetic AgentCard name=%s skills_count=%d "
            "(total cards: %d -> %d)",
            card.name,
            skills_count,
            len(cards),
            len(cards) + 1,
        )
        return list(cards) + [card]

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
        if not md.get(sg_broadcast.ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY):
            return False
        if self._routing_skip_broadcast_used:
            return False
        pool = self._routing_agent_pool or sg_broadcast.parse_routing_agent_pool(md)
        return bool(pool)

    async def _resolve_planner_agent_pool(
        self,
        query: str,
    ) -> tuple[list[AgentCard], set[str], set[str]]:
        """Build planner agent_cards: local execution pool + peer SGs from routing pool or broadcast."""
        if not self._routing_pool_flow_enabled():
            # Legacy: just list all agent cards from registry
            local_card = self.agent_card
            local_name = local_card.name if local_card else "SkillAgent"
            peer_cards = await sg_broadcast.list_all_orchestrator_agent_cards()
            peer_cards = [c for c in peer_cards if getattr(c, "name", "") != local_name]
            all_cards = ([local_card] if local_card else []) + peer_cards
            all_cards = self._maybe_append_local_skill_card(all_cards)
            own_names = {local_name} if local_card else set()
            own_names = own_names | {self.local_skill_agent_name} if self._should_inject_local_skill_card() else own_names
            collab_names = {getattr(c, "name", "") for c in peer_cards}
            return all_cards, own_names, collab_names

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
            # Fallback to legacy
            local_card = self.agent_card
            local_name = local_card.name if local_card else "SkillAgent"
            peer_cards = await sg_broadcast.list_all_orchestrator_agent_cards()
            peer_cards = [c for c in peer_cards if getattr(c, "name", "") != local_name]
            all_cards = ([local_card] if local_card else []) + peer_cards
            all_cards = self._maybe_append_local_skill_card(all_cards)
            own_names = {local_name} if local_card else set()
            own_names = own_names | {self.local_skill_agent_name} if self._should_inject_local_skill_card() else own_names
            collab_names = {getattr(c, "name", "") for c in peer_cards}
            return all_cards, own_names, collab_names

        self_name = self._self_planner_agent_name()
        peer_cards = sg_broadcast.pool_to_peer_agent_cards(pool, self_name)
        local_card = self.agent_card
        local_cards = [local_card] if local_card else []
        local_cards = self._maybe_append_local_skill_card(local_cards)
        augmented_pool = local_cards + peer_cards
        own_names = {getattr(c, "name", "") for c in local_cards if getattr(c, "name", "")}
        collab_names = {getattr(c, "name", "") for c in peer_cards if getattr(c, "name", "")}
        logger.info(
            "[RoutingPool] planner_pool local=%d peer=%d total=%d",
            len(local_cards),
            len(peer_cards),
            len(augmented_pool),
        )
        return augmented_pool, own_names, collab_names

    async def _get_memory(self, query: str) -> str:
        """Retrieve group memory for planner context."""
        md = self.metadata if isinstance(self.metadata, dict) else {}
        memory_owner = self.agent_id
        logger.info(
            "[MemoryOp][Skill] GET_MEMORY | user_id=%s memory_owner=%s run_id=%s query_preview=%s",
            md.get("user_id", ""),
            memory_owner,
            md.get("run_id", ""),
            (query or "")[:80],
        )
        try:
            async with self._data_services_client.session_context() as client:
                memory_search_response = await client.search_memories(
                    query=query,
                    user_id=md.get("user_id", ""),
                    agent_id=memory_owner,
                    run_id=md.get("run_id", ""),
                    limit=10,
                )
            if getattr(memory_search_response, "status", None) == "success":
                search_items = self._data_services_client.parse_memory_search_results(memory_search_response)
                memory_texts = [item.memory for item in search_items if getattr(item, "memory", None)]
                memory_texts_str = "\n".join(memory_texts)

                # 格式化日志输出，与 GetHistory 风格一致
                found_count = len(search_items)
                total_chars = len(memory_texts_str)
                lines = [
                    "",
                    "=" * 60,
                    f"  GetMemory 查询结果 (来源: data-services, memory_owner={memory_owner})",
                    "=" * 60,
                ]
                if memory_texts:
                    for i, text in enumerate(memory_texts, start=1):
                        display = text[:600]
                        if len(text) > 600:
                            display += f"...（截断，共 {len(text)} 字符）"
                        lines.append(f"  ── 第 {i} 条 ──")
                        lines.append(f"  {display}")
                    lines.append("")
                else:
                    lines.append("  (无匹配记忆)")
                    lines.append("")
                lines.append(f"  found_count={found_count}  total_chars={total_chars}  hit={'yes' if memory_texts_str.strip() else 'no'}")
                lines.append("=" * 60)
                logger.info("\n".join(lines))

                return memory_texts_str
        except Exception as e:
            logger.warning("[Memory] get_memory failed: %s", e)
        return ""

    def schedule_add_memory(self, query: str, final_answer: str) -> None:
        """Fire-and-forget wrapper for ``add_memory``.

        Memory writes are best-effort — if the upstream mem0/data-services
        pipeline is slow or down we must never block (or worse, break) the
        stream back to the user.  Wrap the coroutine in a background task
        that swallows any exception.
        """
        async def _runner() -> None:
            try:
                await self.add_memory(query, final_answer)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[MemoryOp][Skill] schedule_add_memory failed — ignoring "
                    "(run_id=%s)",
                    (self.metadata or {}).get("run_id", ""),
                )

        try:
            tracker = self.__dict__.setdefault("_background_memory_tasks", set())
            task = asyncio.create_task(_runner())
            tracker.add(task)
            task.add_done_callback(tracker.discard)
        except RuntimeError:
            logger.warning(
                "[MemoryOp][Skill] schedule_add_memory: no running loop — "
                "falling back to inline execution"
            )
            async def _inline() -> None:
                try:
                    await self.add_memory(query, final_answer)
                except Exception:  # noqa: BLE001
                    logger.exception("[MemoryOp][Skill] inline add_memory failed")

            try:
                asyncio.get_event_loop().run_until_complete(_inline())
            except Exception:  # noqa: BLE001
                logger.exception("[MemoryOp][Skill] inline fallback also failed")

    async def add_memory(self, query: str, final_answer: str) -> None:
        """Persist the current Q&A turn to data-services memory store."""
        final_answer_str = str(final_answer or "").strip()
        if not final_answer_str:
            return
        md = self.metadata if isinstance(self.metadata, dict) else {}
        memory_owner = self.agent_id
        logger.info(
            "[MemoryOp][Skill] ADD_MEMORY | user_id=%s memory_owner=%s run_id=%s query_preview=%s",
            md.get("user_id", ""),
            memory_owner,
            md.get("run_id", ""),
            (query or "")[:80],
        )
        async with self._data_services_client.session_context() as client:
            memory_response = await client.store_memory(
                user_id=md.get("user_id", ""),
                agent_id=memory_owner,
                run_id=md.get("run_id", ""),
                messages=[
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": final_answer_str},
                ],
            )
        _status = (
            getattr(memory_response, "status", None)
            or (memory_response.get("status") if isinstance(memory_response, dict) else "N/A")
        )
        logger.info(
            "[MemoryOp][Skill] ADD_MEMORY done | memory_owner=%s run_id=%s status=%s",
            memory_owner,
            md.get("run_id", ""),
            _status,
        )

    # ------------------------------------------------------------------
    # Execution hint helpers (aligned with orchestrator-agent)
    # ------------------------------------------------------------------

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
        check_response: "sg_broadcast.CapabilityCheckResponse",
    ) -> dict[str, Any]:
        """Build SG-owned evidence that Routing can transparently round-trip."""
        member_roles = dict(
            getattr(check_response, "collaboration_roles", None) or {}
        )
        selected_members = [
            str(name).strip()
            for name in (getattr(check_response, "collaboration_agents", None) or [])
            if str(name).strip()
        ]
        member_evidence: list[dict[str, Any]] = []
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
            "semantic_group_id": str(self.agent_id or ""),
            "agent_name": self._self_planner_agent_name(),
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
        metadata: dict[str, Any],
        query: str,
    ) -> Optional[dict[str, Any]]:
        """Validate the SG-issued hint delivered with the execution request."""
        hint = metadata.get(SG_EXECUTION_HINT_KEY)
        if not isinstance(hint, dict):
            return None
        if hint.get("version") != "v1":
            logger.warning("[Capability][ExecutionHint] rejected: unsupported version")
            return None
        if str(hint.get("semantic_group_id") or "") != str(self.agent_id or ""):
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

    def _execution_hint_memory_note(self, plan: dict[str, Any]) -> str:
        selected = [
            str(name).strip()
            for name in (plan.get("selected_members") or [])
            if str(name).strip()
        ]
        reason = str(plan.get("reason") or "").strip()
        lines = [
            "[MemberCapabilityEvidence]",
            "A prior member capability check for this run already confirmed that "
            "this agent can handle the user query via its member data agents.",
            f"can_handle={bool(plan.get('can_handle'))} "
            f"confidence={float(plan.get('confidence') or 0.0):.2f} "
            f"strategy={plan.get('execution_strategy') or 'single'}",
        ]
        if selected:
            lines.append("selected_members=" + ", ".join(selected[:10]))
        if reason:
            lines.append("reason=" + reason[:300])
        lines.append(
            "Therefore prefer this agent's own member for execution; "
            "do not return agent=NONE solely because the agent card is generic."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # SkillRunner lifecycle
    # ------------------------------------------------------------------

    def _build_skill_runner_llm(self):
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
        if not ENABLE_CODE_EXEC:
            return None
        if CodeExecution is None:
            return None
        inst = CodeExecution(llm=llm, max_retries=CODE_EXEC_MAX_RETRIES)
        return inst

    def _init_skill_runner_sync(self) -> "SkillRunner | None":
        if not LOCAL_SKILLS_ENABLED:
            return None
        if SkillRunner is None:
            return None
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
                logger.warning("[LocalSkill][Init] older skill_sdk wheel, falling back to single-process")
                runner = SkillRunner(
                    llm=llm,
                    max_steps=LOCAL_SKILL_MAX_STEPS,
                    cmd_timeout_sec=LOCAL_SKILL_CMD_TIMEOUT_SEC,
                    code_execution=code_execution,
                )
            if LOCAL_SKILLS_DIR:
                loaded = runner.load_from_dir(LOCAL_SKILLS_DIR) or []
                logger.info("[LocalSkill][Init] loaded %d skills from %s", len(loaded), LOCAL_SKILLS_DIR)
            logger.info("[LocalSkill][Init] ready in %dms", int((_time.perf_counter() - t0) * 1000))
            return runner
        except Exception:
            logger.exception("[LocalSkill][Init] failed to initialise SkillRunner")
            return None

    def preload_skill_runner(self) -> "SkillRunner | None":
        if self._skill_runner_initialised:
            return self._skill_runner
        self._skill_runner = self._init_skill_runner_sync()
        self._skill_runner_initialised = True
        return self._skill_runner

    async def _ensure_skill_runner(self) -> "SkillRunner | None":
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
        runner, self._skill_runner = self._skill_runner, None
        self._skill_runner_initialised = True
        if runner is not None:
            try:
                runner.close()
            except Exception:
                logger.exception("[LocalSkill][Shutdown] SkillRunner.close() raised")

    # ------------------------------------------------------------------
    # Dynamic AgentCard composition
    # ------------------------------------------------------------------

    _EMPTY_SKILL_DESCRIPTION = "本地技能执行器。当前未加载任何技能。"
    _SKILL_LIST_HEADER = "本地技能执行器，可在本进程内直接运行以下技能："
    _MAX_DESC_PREVIEW_LINES = 30

    def build_dynamic_agent_card_fields(self) -> tuple[str, list[AgentSkill]]:
        runner = self._skill_runner
        lister = getattr(runner, "lister", None) if runner is not None else None
        try:
            skills = list(getattr(lister, "skills", None) or []) if lister is not None else []
        except Exception:
            skills = []

        lines: list[str] = []
        agent_skills: list[AgentSkill] = []
        for s in skills:
            name = str(getattr(s, "name", "") or "").strip()
            desc_raw = str(getattr(s, "description", "") or "").strip()
            desc_inline = desc_raw.replace("\n", " ").strip()
            if not name:
                continue
            lines.append(f"- {name}: {desc_inline}")
            try:
                agent_skills.append(
                    AgentSkill(
                        id=name,
                        name=name,
                        description=desc_raw or desc_inline,
                        tags=[name, "local skill", "skill sdk"],
                        examples=[],
                        input_modes=["text", "text/plain"],
                        output_modes=["text", "text/plain"],
                    )
                )
            except Exception:
                pass

        if not lines:
            return self._EMPTY_SKILL_DESCRIPTION, []

        preview_lines = lines[: self._MAX_DESC_PREVIEW_LINES]
        description = self._SKILL_LIST_HEADER + "\n" + "\n".join(preview_lines)
        hidden = max(0, len(lines) - self._MAX_DESC_PREVIEW_LINES)
        if hidden:
            description += f"\n（另有 {hidden} 个技能未列出）"
        return description, agent_skills

    # ------------------------------------------------------------------
    # Data-flow logging (mirrors orchestrator-agent)
    # ------------------------------------------------------------------

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

        Example output for a ``direction="LOCAL_TASK_EXEC"`` call::

            ┌▶ DATA_FLOW  LOCAL_TASK_EXEC ───────────────────────────┐
            │  Task #1 → 本地 SkillAgent 执行
            │  来源: SkillAgent-xxx
            │  目标: SkillAgent-xxx (in-process)
            │  载荷: 39 chars
            ├───────────────────────────────────────────────────────┤
            │  预览: 查询每个用户的订单总数和消费总额…
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

    def _log_summary_input(
        self,
        task_results: dict[int, str],
        delegate_results: dict[str, str],
        *,
        extra_desc: str = "",
    ) -> None:
        """Log SUMMARY_INPUT data flow before _summarize / _summarize_with_evaluation."""
        _own_snippets = []
        for _tid, _res in task_results.items():
            _snip = (_res or "").replace("\n", " ").strip()[:120]
            _own_snippets.append(f"#{_tid}: {_snip}")
        _own_preview = "\n".join(_own_snippets) if _own_snippets else "(none)"
        _del_snippets = []
        for _name, _res in delegate_results.items():
            _snip = (_res or "").replace("\n", " ").strip()[:120]
            _del_snippets.append(f"[{_name}]: {_snip}")
        _del_preview = "\n".join(_del_snippets) if _del_snippets else "(none)"
        _summary_input_chars = sum(len(v or "") for v in task_results.values()) + sum(len(v or "") for v in delegate_results.values())
        desc = f"聚合 {len(task_results)} 项 task_results + {len(delegate_results)} 项 delegated_results → 送入 Summary LLM"
        if extra_desc:
            desc += f" ({extra_desc})"
        self._log_data_flow(
            direction="SUMMARY_INPUT",
            description=desc,
            source_id=self._self_planner_agent_name(),
            target_id="SummaryLLM",
            payload_chars=_summary_input_chars,
            payload_preview=(
                f"task_results:\n{_own_preview}\n\ndelegated_results:\n{_del_preview}"
            ),
            metadata_extra={
                "own_result_chars": sum(len(v or "") for v in task_results.values()),
                "delegated_result_chars": sum(len(v or "") for v in delegate_results.values()),
            },
        )

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------

    def _build_progress_frame(
        self,
        event: str,
        *,
        message: str = "",
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        ctx = self._progress_context
        payload: Dict[str, Any] = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "layer": "collaboration",
            "event": event,
            "run_id": ctx.get("run_id", ""),
            "user_id": ctx.get("user_id", ""),
            "agent_id": ctx.get("agent_id", ""),
            "task_id": task_id,
            "message": message,
            "status": status,
        }
        if extra:
            payload["extra"] = extra
        return f"{PROGRESS_FRAME_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"

    async def _emit_progress(
        self,
        updater: TaskUpdater,
        event: str,
        *,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        frame = self._build_progress_frame(
            event,
            message=message,
            status=status,
            task_id=task_id,
            extra=extra,
        )
        await updater.add_artifact([TextPart(text=frame)], name="progress")

    # ------------------------------------------------------------------
    # A2A delegation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_response_text(chunk: Any) -> str:
        """Extract text from A2A streaming chunk."""
        data = chunk.model_dump(mode="json", exclude_none=True)
        if (result := data.get("result")) is not None:
            kind = result.get("kind")
            if kind == "artifact-update":
                artifact = result.get("artifact")
                parts = artifact.get("parts")
                if parts and len(parts) > 0 and isinstance(parts[0], dict):
                    text = parts[0].get("text")
                    return text if text else ""
        return ""

    @staticmethod
    def _is_progress_frame(text: str) -> bool:
        """Check if a text line is a [[DAC_PROGRESS]] frame."""
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_PROGRESS]] ")

    @staticmethod
    def _is_answer_frame(text: str) -> bool:
        """Check if a text line is a [[DAC_ANSWER]] frame."""
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_ANSWER]] ")

    @classmethod
    def _strip_progress_lines(cls, text: str) -> str:
        """Strip [[DAC_PROGRESS]] lines from body text.

        Mirrors ``OrchestratorAgent.strip_progress_lines`` so that progress
        frames leaking from delegated agents never pollute downstream LLM
        prompts or answer text.
        """
        if not text:
            return ""
        lines = [line for line in text.splitlines() if not cls._is_progress_frame(line)]
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Mid-execution detection and delegation
    # ------------------------------------------------------------------

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
        """Mid-execution Step 1: detect whether a data gap still exists via LLM reasoning."""
        own_text = "\n".join(
            f"[Task#{tid}]: {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}]: {res}" for name, res in delegated_results.items() if res
        )
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
            "请调用 detect_delegation_needs 工具来输出结果。"
            "当 needs_help=true 时，reason 字段必须说明具体缺了什么数据、为什么需要补充。"
        )

        try:
            llm = self._get_orchestration_llm()
            detect_tool = StructuredTool(
                name="detect_delegation_needs",
                description=(
                    "检测是否仍有数据缺口需要跨 SG 补充；输出 synthesized_query 与原因。"
                    "当 needs_help=true 时应填写 target_sgs，最终选人由 capability_check 完成。"
                ),
                args_schema=DelegationDetectionResult,
                func=None,
                coroutine=None,
            )
            data_dict = await invoke_llm_with_tool(
                llm=llm,
                tool=detect_tool,
                messages=[HumanMessage(content=prompt)],
                metadata={"user_id": user_id, "run_id": run_id, "trace_id": trace_id},
                tool_choice="detect_delegation_needs",
                span_name="mid-exec-detect-delegation",
            )
            if data_dict is None or not isinstance(data_dict, dict):
                return None
            wants_help = data_dict.get("needs_help", False)
            if not wants_help:
                logger.info(
                    "[MidExec][Detect] LLM verdict: no help needed | reason=%s",
                    (data_dict.get("reason") or "")[:120],
                )
                return None
            result = {
                "needs_help": True,
                "synthesized_query": data_dict.get("synthesized_query", ""),
                "target_sgs": data_dict.get("target_sgs", []),
                "reason": data_dict.get("reason", ""),
                "source": "llm_detection",
            }
            return result
        except Exception as e:
            logger.error("[MidExec][Detect] LLM detection failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Mid-exec target selection helpers (aligned with orchestrator-agent)
    # ------------------------------------------------------------------

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
            _preview_parts.append(f"findings='{_short(str(key_findings), 200)}'")
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

    def _mid_delegate_capability_select_enabled(self) -> bool:
        return os.getenv("SG_MID_DELEGATE_CAPABILITY_SELECT_ENABLED", "true").strip().lower() not in ("false", "0", "no")

    def _mid_delegate_max_targets(self) -> int:
        try:
            return max(1, int(os.getenv("SG_MID_DELEGATE_MAX_TARGETS", "3") or 3))
        except ValueError:
            return 3

    def _mid_exec_soft_hint_fallback_enabled(self) -> bool:
        return os.getenv("SG_MID_DELEGATE_SOFT_HINT_FALLBACK", "true").strip().lower() not in ("false", "0", "no")

    @staticmethod
    def _mid_exec_capability_probe_query(synthesized_query: str) -> str:
        scoped = (synthesized_query or "").strip()
        if not scoped:
            return scoped
        return (
            "【跨 SG 补数子任务】请仅根据下列子任务判断本智能体是否拥有所需数据域"
            "（can_handle / can_contribute）。不要按完整原题的其它域目标来否决。\n\n"
            f"{scoped}"
        )

    async def _load_mid_exec_broadcast_candidates(
        self,
        *,
        extra_cards: Optional[list[AgentCard]] = None,
    ) -> list[AgentCard]:
        self_name = self._self_planner_agent_name()
        by_name: dict[str, AgentCard] = {}

        registry_cards = await sg_broadcast.list_all_orchestrator_agent_cards()
        for card in registry_cards or []:
            if card.name == self_name:
                continue
            by_name[card.name] = card

        for card in extra_cards or []:
            if card.name == self_name:
                continue
            by_name.setdefault(card.name, card)

        cards = list(by_name.values())
        logger.info(
            "[MidExec][CapSelect] broadcast candidate pool | count=%d self=%s",
            len(cards), self_name,
        )
        return cards

    def _resolve_mid_exec_soft_hint_cards(
        self,
        hint_names: list[str],
        candidates: list[AgentCard],
        extra_cards: Optional[list[AgentCard]] = None,
    ) -> tuple[list[AgentCard], list[str]]:
        by_name: dict[str, AgentCard] = {}
        for card in list(candidates or []) + list(extra_cards or []):
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
    def _rank_mid_exec_capable_pairs(
        capable_pairs: list[tuple[AgentCard, Any]],
        soft_hint_names: list[str],
    ) -> list[tuple[AgentCard, Any]]:
        hint_set = {n for n in soft_hint_names if n}
        hint_order = {n: i for i, n in enumerate(soft_hint_names) if n}

        def _key(pair: tuple[AgentCard, Any]) -> tuple:
            card, resp = pair
            name = str(getattr(card, "name", "") or "")
            return (
                1 if getattr(resp, "can_handle", False) else 0,
                float(getattr(resp, "confidence", 0.0) or 0.0),
                1 if name in hint_set else 0,
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
    ) -> dict[str, Any]:
        """Select mid-delegate peer SGs via concurrent standard capability_check."""
        empty: dict[str, Any] = {
            "target_cards": [], "target_sg_names": [], "capable_pairs": [],
            "hints_by_sg": {}, "evidence_text": "", "probed_names": [],
        }
        if not (synthesized_query or "").strip():
            return empty

        candidates = await self._load_mid_exec_broadcast_candidates(
            extra_cards=collaborator_cards,
        )
        hint_names = [n for n in (soft_target_hints or []) if n]
        hinted, missing_hints = self._resolve_mid_exec_soft_hint_cards(
            hint_names, candidates, collaborator_cards,
        )
        if hinted:
            by_name = {c.name: c for c in candidates}
            for card in hinted:
                by_name.setdefault(card.name, card)
            candidates = list(by_name.values())

        if not candidates:
            return empty

        probe_query = self._mid_exec_capability_probe_query(synthesized_query)
        capable_pairs = await sg_broadcast.probe_agents_capability_concurrent(
            probe_query, candidates, user_id, run_id, trace_id,
        )
        probed_names = [c.name for c in candidates]
        if capable_pairs:
            capable_pairs = self._rank_mid_exec_capable_pairs(capable_pairs, hint_names)

        if not capable_pairs and hinted and self._mid_exec_soft_hint_fallback_enabled():
            logger.warning("[MidExec][CapSelect] capability_check empty, falling back to soft_hints")
            capable_pairs = [
                (card, sg_broadcast.CapabilityCheckResponse(
                    can_handle=True, can_contribute=True, confidence=0.55,
                    reason="mid-exec soft_hint fallback", agent_name=card.name,
                    agent_url=str(getattr(card, "url", "") or ""),
                ))
                for card in hinted
            ]

        if not capable_pairs:
            return {**empty, "probed_names": probed_names}

        max_targets = self._mid_delegate_max_targets()
        selected = capable_pairs[:max_targets]
        target_cards = [card for card, _ in selected]
        target_sg_names = [card.name for card in target_cards]
        hints_by_sg: dict[str, dict] = {}
        for card, resp in selected:
            hint = getattr(resp, "execution_hint", None) or {}
            if isinstance(hint, dict) and hint:
                hints_by_sg[card.name] = hint

        evidence_text = sg_broadcast.format_capability_evidence_for_planner(selected)
        return {
            "target_cards": target_cards, "target_sg_names": target_sg_names,
            "capable_pairs": selected, "hints_by_sg": hints_by_sg,
            "evidence_text": evidence_text, "probed_names": probed_names,
        }

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
                    "[MidExec][Plan] scoped task description | "
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
    ) -> Optional[TaskList]:
        """Mid-execution Step 2: plan tasks against capability-selected peers."""
        if not target_cards or not synthesized_query:
            return None
        try:
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
                else "【Mid-exec 规划约束】远程任务 description = 上方子任务原文；不得扩写为完整原题。"
            )
            planner = PlannerAgent(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=self.temperature,
                data_services_url=self.data_services_url,
                metadata=self.metadata,
                agent_id=self.agent_id,
            )
            plan = await planner.make_plan(scoped_plan_query, target_cards, group_memory=mid_memory)
            return self._apply_scoped_mid_exec_task_descriptions(plan, synthesized_query)
        except Exception as e:
            logger.warning("[MidExec][Plan] mid-exec plan failed: %s", e)
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
        hints_by_sg: Optional[dict[str, dict]] = None,
        updater: Optional[Any] = None,
    ) -> dict[str, str]:
        """Mid-execution Step 3: dispatch plan tasks to target SGs.

        Forward progress frames from delegated agents via ``updater`` so the
        delegated agent's DAC progress is visible to the end user.
        """
        results: dict[str, str] = {}
        name_to_card = {c.name: c for c in target_cards}
        hints = dict(hints_by_sg or {})
        mid_exec_round = int((upstream_context or {}).get("mid_exec_round") or 0)

        for task in plan.tasks:
            agent_name = (task.agent or "").strip()
            target_card = name_to_card.get(agent_name)
            if target_card is None:
                logger.warning("[MidExec][Dispatch] no card for agent=%s", agent_name)
                continue
            if current_hop <= 1:
                results[agent_name] = NONE_TASK_DESCRIPTION
                continue

            # Consume 1 hop for this delegation edge.
            current_hop -= 1
            next_hop = current_hop
            new_chain = delegation_chain + [self._self_planner_agent_name()]
            peer_hint = hints.get(agent_name) or {}

            _mid_delegate_desc = _short(task.description or "", 120)
            if updater is not None:
                await self._emit_progress(
                    updater,
                    "mid_exec_delegating",
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

            result = await self._delegate_to_peer(
                task.description or "",
                target_card,
                user_id, run_id, trace_id,
                hop_remaining=next_hop,
                delegation_chain=new_chain,
                upstream_context=upstream_context,
                execution_hint=peer_hint,
                updater=updater,
            )
            results[agent_name] = result

            if updater is not None:
                await self._emit_progress(
                    updater,
                    "mid_exec_dispatched",
                    message=(
                        f"Mid-exec Task #{task.id} done via [{agent_name}]: "
                        f"{_mid_delegate_desc} ({len(result or '')} chars)"
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

    # ------------------------------------------------------------------
    # Updated _delegate_to_peer with delegation_chain and execution_hint
    # ------------------------------------------------------------------

    async def _delegate_to_peer(
        self,
        query: str,
        target_card: AgentCard,
        user_id: str,
        run_id: str,
        trace_id: str,
        *,
        propagated_history: Optional[dict] = None,
        hop_remaining: int = 5,
        upstream_context: dict | None = None,
        delegation_chain: list[str] = None,
        execution_hint: dict | None = None,
        updater: Optional[Any] = None,
    ) -> str:
        """Delegate a task to a peer agent via A2A streaming.

        Consume A2A streaming chunks with line-buffering (frames may be split
        across chunk boundaries), relay ``[[DAC_PROGRESS]]`` / ``[[DAC_ANSWER]]``
        frames to ``updater``, and return body text with progress lines stripped.
        Mirrors the orchestrator's ``stream_a2a_collect_forward_progress_frames``.
        """
        logger.info(
            "[Cross-SG][Delegate] delegating to %s | hop=%d | query_preview=%s",
            target_card.name,
            hop_remaining,
            (query or "")[:100],
        )
        chain = list(delegation_chain or [])
        metadata: dict[str, Any] = {
            "user_id": user_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "collaboration_delegation": True,
            "hop_remaining": hop_remaining,
            "delegation_chain": chain,
            "upstream_context": upstream_context or {},
            "delegator_name": self._self_planner_agent_name(),
            "skip_history_write": True,
            PROPAGATED_HISTORY_KEY: propagated_history or {},
        }
        if isinstance(execution_hint, dict) and execution_hint:
            metadata[sg_broadcast.SG_EXECUTION_HINT_KEY] = execution_hint
            logger.info(
                "[Cross-SG][Delegate] transporting peer execution_hint | target=%s",
                target_card.name,
            )
        send_payload: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": query}],
                "messageId": uuid4().hex,
            },
            "metadata": metadata,
        }
        timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as httpx_client:
                client = A2AClient(httpx_client=httpx_client, agent_card=target_card)
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_payload),
                )
                stream_response = client.send_message_streaming(streaming_request)

                # Line-buffered collection: frames may be split across chunk
                # boundaries.  Accumulate text in a buffer and process
                # complete lines only.
                line_buf = ""
                result_segments: list[str] = []

                async def _handle_line(raw_line: str) -> None:
                    s = raw_line.strip()
                    if not s:
                        return
                    if self._is_progress_frame(s):
                        if updater is not None:
                            await updater.add_artifact(
                                [TextPart(text=s + "\n")],
                                name="progress",
                            )
                        return
                    if self._is_answer_frame(s):
                        if updater is not None:
                            await updater.add_artifact(
                                [TextPart(text=s + "\n")],
                                name="progress",
                            )
                        return
                    result_segments.append(s)

                async for chunk in stream_response:
                    text = self._get_response_text(chunk)
                    if not text:
                        continue
                    line_buf += text
                    while "\n" in line_buf:
                        raw_line, line_buf = line_buf.split("\n", 1)
                        await _handle_line(raw_line)
                if line_buf:
                    await _handle_line(line_buf)

                full_response = "\n".join(result_segments).strip()
                # Strip any remaining progress lines from the body (belt-and-suspenders)
                full_response = self._strip_progress_lines(full_response)
                logger.info(
                    "[Cross-SG][Delegate] result from %s | chars=%d",
                    target_card.name,
                    len(full_response),
                )
                return full_response
        except Exception as e:
            logger.error("[Cross-SG][Delegate] failed to delegate to %s: %s", target_card.name, e)
            return f"Delegation failed: {e}"

    # ------------------------------------------------------------------
    # Dependency guard (aligned with orchestrator-agent)
    # ------------------------------------------------------------------

    def _dependency_upstream_snapshot(self, task_id: int) -> list[dict[str, Any]]:
        """Build upstream task snapshot for dependency guard."""
        upstream: list[dict[str, Any]] = []
        # We accumulate upstream from the task execution loop's all_task_results
        # and the task's depends_on
        if not hasattr(self, "_tasks_status_list"):
            return upstream
        for ts in self._tasks_status_list or []:
            tid = getattr(ts, "id", None)
            if tid is None:
                continue
            if tid >= task_id:
                continue
            upstream.append({
                "id": tid,
                "description": getattr(ts, "description", "") or "",
                "agent": getattr(ts, "agent", "") or "",
                "status": getattr(ts, "status", "fail") or "fail",
                "answer_excerpt": (getattr(ts, "answer", "") or "")[:DEPENDENCY_CHECK_ANSWER_CHARS],
                "failure_reason_code": getattr(ts, "failure_reason_code", "") or "",
            })
        if len(upstream) > DEPENDENCY_CHECK_MAX_UPSTREAM:
            upstream = upstream[-DEPENDENCY_CHECK_MAX_UPSTREAM:]
        return upstream

    async def _judge_task_dependency(
        self,
        task_description: str,
        task_agent: str,
        upstream: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """LLM-based dependency judge. Fail-close on errors."""
        default_fail_close = {
            "unmet": True,
            "needs_upstream": True,
            "unmet_upstream_ids": [u["id"] for u in upstream if u.get("status") == "fail"],
            "missing_fields": [],
            "rationale": "",
            "error": None,
        }

        try:
            system_template = (
                "You are a dependency auditor for a multi-agent task orchestrator. "
                "Given the CURRENT task and the UPSTREAM tasks already executed in this round, "
                "decide whether the current task can be safely dispatched.\n\n"
                "Rules:\n"
                "1. If the current task's description explicitly or implicitly relies on the "
                "output of any upstream task (e.g. uses a value, decoded field, identifier, "
                "aggregate, flag, etc. produced upstream), that upstream task is a dependency.\n"
                "2. For each dependency:\n"
                "   - If its status is 'fail' (or its answer is empty/error text) → dependency is UNMET.\n"
                "   - If its status is 'complete' BUT the answer_excerpt does not contain the "
                "     concrete data the current task needs (e.g. missing grain value, missing "
                "     decoded string, missing ids) → dependency is UNMET.\n"
                "   - Otherwise the dependency is MET.\n"
                "3. If the current task does not need upstream output at all, report unmet=false.\n"
                "4. Be conservative: when uncertain, prefer unmet=true.\n\n"
                "Call the judge_dependency tool to output your verdict."
            )

            current_task_payload = json.dumps(
                {"description": str(task_description or ""), "agent": str(task_agent or "")},
                ensure_ascii=False,
            )
            upstream_payload = json.dumps(upstream, ensure_ascii=False)

            prompt = (
                f"{system_template}\n\n"
                f"CURRENT_TASK:\n{current_task_payload}\n\n"
                f"UPSTREAM_TASKS (executed earlier in this round, ordered by id):\n{upstream_payload}"
            )

            llm = self._get_orchestration_llm()
            judge_tool = StructuredTool(
                name="judge_dependency",
                description="Judge whether a task can proceed given upstream dependency state.",
                args_schema=DependencyJudgeResult,
                func=None,
                coroutine=None,
            )
            parsed = await invoke_llm_with_tool(
                llm=llm,
                tool=judge_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=self.metadata,
                tool_choice="judge_dependency",
                span_name="dependency-judge",
            )
            if not isinstance(parsed, dict):
                return {**default_fail_close, "error": "malformed_output"}

            unmet = bool(parsed.get("unmet", False))
            unmet_ids_raw = parsed.get("unmet_upstream_ids") or []
            unmet_ids: list[int] = []
            if isinstance(unmet_ids_raw, list):
                for v in unmet_ids_raw:
                    try:
                        unmet_ids.append(int(v))
                    except (TypeError, ValueError):
                        continue
            missing_fields_raw = parsed.get("missing_fields") or []
            missing_fields = [str(x) for x in missing_fields_raw if isinstance(x, (str, int))] \
                if isinstance(missing_fields_raw, list) else []
            rationale = str(parsed.get("rationale") or "").strip()

            return {
                "unmet": unmet,
                "needs_upstream": bool(parsed.get("needs_upstream", unmet)),
                "unmet_upstream_ids": unmet_ids,
                "missing_fields": missing_fields,
                "rationale": rationale,
                "error": None,
            }
        except Exception as exc:
            logger.exception("[DependencyGuard] judge raised — fail-close | err=%s", exc)
            return {**default_fail_close, "error": "exception"}

    async def _preflight_dependency_check(
        self,
        task_id: int,
        task_description: str,
        task_agent: str,
        depends_on: list[int],
    ) -> Optional[dict[str, Any]]:
        """Return a verdict dict when the task should be blocked, else None."""
        if not DEPENDENCY_CHECK_ENABLED:
            return None
        if not depends_on:
            return None

        upstream = self._dependency_upstream_snapshot(task_id)
        if not upstream:
            return None

        # Only run the judge when at least one upstream task actually failed
        if not any((u.get("status") == "fail") for u in upstream):
            return None

        logger.info(
            "[DependencyGuard] checking task_id=%s upstream_count=%d failed_upstream_ids=%s",
            task_id,
            len(upstream),
            [u["id"] for u in upstream if u.get("status") == "fail"],
        )
        verdict = await self._judge_task_dependency(task_description, task_agent, upstream)
        logger.info(
            "[DependencyGuard] verdict task_id=%s unmet=%s unmet_upstream_ids=%s error=%s rationale=%r",
            task_id,
            verdict.get("unmet"),
            verdict.get("unmet_upstream_ids"),
            verdict.get("error"),
            (verdict.get("rationale") or "")[:200],
        )
        if not verdict.get("unmet"):
            return None
        return verdict

    # ------------------------------------------------------------------
    # Dependent query refinement
    # ------------------------------------------------------------------

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

    def _llm_dependent_query_refine_enabled(self) -> bool:
        return os.getenv("ENABLE_LLM_DEP_QUERY_REFINE", "true").strip().lower() not in ("false", "0", "no")

    async def _llm_refine_dependent_task_query(
        self,
        original_query: str,
        planned_downstream_description: str,
        downstream_agent_name: str,
        upstream_results_blob: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        refine_stage: str = "pre_delegate",
    ) -> str:
        """LLM merges original user query + planner subtask text + deps' execution output into one coherent query."""
        if not (planned_downstream_description or "").strip():
            return planned_downstream_description or ""

        if not self._llm_dependent_query_refine_enabled():
            return planned_downstream_description

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
            "则必须调用 refine_query 工具并设置 skip=true、reason=<简短说明跳过原因>，"
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
            "4）**命名禁区**：`delegation_query` 正文**禁止出现**任何形式的智能体卡片名、组名、`Agent-sg-\u2026`、`Agent-dd-\u2026`、"
            "十六进制式路由后缀，以及「请以某某 Agent」「以某某身份」「由某某语义组」「针对某某Expert」之类指向执行单元的措辞。"
            "只写领域对象与操作（订单、用户、SKU、支付方式、开票信息等）。\n"
            "5）**自包含**：尽量单靠这段话即可完成当前步，少用「见上文 JSON」。\n"
            "6）请调用 refine_query 工具来输出结果，"
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
            llm = self._get_orchestration_llm()
            refine_tool = StructuredTool(
                name="refine_query",
                description="基于上游依赖任务输出和原始计划，合成下游任务的查询正文。",
                args_schema=DependentQueryRefineResult,
                func=None,
                coroutine=None,
            )
            result_data = await invoke_llm_with_tool(
                llm=llm,
                tool=refine_tool,
                messages=[HumanMessage(content=prompt)],
                metadata={"user_id": user_id, "run_id": run_id, "trace_id": trace_id},
                tool_choice="refine_query",
                span_name=f"dep-query-refine-{_span_tag}",
            )
            if result_data is None:
                logger.warning(
                    "[DepQueryRefine][%s] LLM did not call refine_query tool, fallback to planned description",
                    refine_stage,
                )
                return planned_downstream_description
            parsed = result_data
        except Exception as exc:
            logger.error("[DepQueryRefine][%s] LLM failed: %s", refine_stage, exc)
            return planned_downstream_description

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

    # ------------------------------------------------------------------
    # Conversation history (aligned with SG orchestrator)
    # ------------------------------------------------------------------

    async def add_history(self, query: str, final_answer: str, think: str = "") -> None:
        """Persist the current Q&A turn to data-services conversation history."""
        final_answer_str = str(final_answer or "").strip()
        if not final_answer_str:
            return
        logger.info(
            "[HistoryFlow] skill-agent add_history user_id=%s agent_id=%s run_id=%s "
            "query_chars=%d answer_chars=%d",
            self.metadata.get("user_id", ""),
            self.agent_id,
            self.metadata.get("run_id", ""),
            len(str(query or "")),
            len(final_answer_str),
        )
        create_request = CreateHistoryRequest(
            user_id=self.metadata.get("user_id", ""),
            agent_id=self.agent_id,
            run_id=self.metadata.get("run_id", ""),
            messages=[
                HistoryMessage(role="user", content=str(query or "")),
                HistoryMessage(role="assistant", content=final_answer_str, think=think or None),
            ],
        )
        try:
            async with self._data_services_client.session_context() as client:
                history_response = await client.create_history(create_request)
            _status = getattr(history_response, "status", None) or (
                history_response.get("status") if isinstance(history_response, dict) else "N/A"
            )
            logger.info(
                "[HistoryFlow] skill-agent add_history done | status=%s run_id=%s",
                _status,
                self.metadata.get("run_id", ""),
            )
        except Exception as exc:
            logger.error("[HistoryFlow] skill-agent add_history failed: %s", exc)

    async def get_history(self) -> list:
        """Retrieve conversation history as a list of HumanMessage/AIMessage.

        Checks propagated_history first, then falls back to data-services API.
        """
        md = self.metadata if isinstance(self.metadata, dict) else {}
        propagated = parse_propagated_history(md.get(PROPAGATED_HISTORY_KEY))
        if _normalize_history_turns(propagated.get("turns")):
            logger.info(
                "[HistoryFlow] skill-agent get_history from propagated | turns=%d",
                len(propagated.get("turns", [])),
            )
            messages = history_messages_from_payload(propagated)
            _log_history_turns(propagated.get("turns", []), source="propagated")
            return messages

        search_items = []
        search_request = SearchHistoryRequest(
            user_id=md.get("user_id", ""),
            run_id=md.get("run_id", ""),
            limit=get_conversation_history_limit(),
        )
        try:
            async with self._data_services_client.session_context() as client:
                history_search_response = await client.search_history_by_user_and_run(search_request)
            if getattr(history_search_response, "status", None) == "success":
                search_items = history_search_response.data
            else:
                detail = getattr(history_search_response, "detail", None)
                if detail:
                    logger.error("[HistoryFlow] skill-agent get_history error: %s", detail)
        except Exception as exc:
            logger.error("[HistoryFlow] skill-agent get_history API call failed: %s", exc)

        payload = history_payload_from_search_items(search_items, source="skill_agent_executor_fallback")
        logger.info(
            "[HistoryFlow] skill-agent get_history from API | turns=%d",
            payload.get("turn_count", 0),
        )
        _log_history_turns(payload.get("turns", []), source="data-services API")
        return history_messages_from_payload(payload)

    # ------------------------------------------------------------------
    # Summary LLM
    # ------------------------------------------------------------------

    # _summarize_with_evaluation uses the top-level SummaryEvaluationResult
    # Pydantic model (defined near the other tool-call schemas above) as
    # the args_schema for the evaluate_summary StructuredTool.

    async def _summarize_with_evaluation(
        self,
        original_query: str,
        task_results: dict[int, str],
        delegate_results: dict[str, str],
        upstream_context: dict | None = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> SummaryEvaluationResult:
        """Summarize task results AND evaluate whether the answer is sufficient.

        Uses the same ``bind_tools`` / ``invoke_llm_with_tool`` mechanism
        as PlannerAgent and other orchestration methods.  The LLM is
        forced to call ``evaluate_summary``, whose ``args_schema`` is
        :class:`SummaryEvaluationResult`.  This guarantees the output is
        always valid structured data — no regex parsing of free-text
        markers.

        Returns a :class:`SummaryEvaluationResult` with the answer text
        and the evaluation outcome.
        """
        own_text = "\n".join(
            f"[Task#{tid}] {res}" for tid, res in task_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}] {res}" for name, res in delegate_results.items() if res
        )
        upstream_text = (
            json.dumps(upstream_context, ensure_ascii=False)
            if upstream_context
            else "无"
        )

        system_prompt_text = (
            "你是一位知识分析与总结专家。你的任务是基于提供的执行结果和对话上下文，"
            "通过逻辑严密的分析，回答用户的原始问题。\n\n"
            "**核心原则**\n"
            "1. 直接输出答案正文，从实质内容开始。\n"
            "2. 不要自我介绍，不要说明你是汇总器或 agent，不要描述协作/整合过程。\n"
            "3. 不要使用「好的，作为…」「我已收到/整合了…」「以下是针对…的完整/综合回答」等开场白。\n"
            "4. 下游结果中若含类似套话，请忽略并只提取实质信息，不要在输出中重复。\n"
            "5. 信息冲突时简要说明；缺信息时说明缺什么，勿编造。\n"
            "6. 对话历史仅用于理解当前问题的指代和语境，不要将历史中的旧结论当作当前事实。\n\n"
            "**你需要做的事情**\n"
            "1. 撰写回答正文（填入 answer 字段）。\n"
            "2. 判断当前信息是否足以完整回答用户问题（填入 satisfactory 字段）：\n"
            "   - 如果足以回答 → satisfactory=true，missing_info 设为空字符串。\n"
            "   - 如果不足以回答 → satisfactory=false，missing_info 中说明缺少什么信息，"
            "需要在下轮执行中补充获取（例如：'缺少模块 X 的运行日志'、'数据库 Y 的配置信息未返回'）。\n"
            "3. 简要说明本次评估的决策理由（填入 rationale 字段，一句话即可）。\n\n"
            "**判断 satisfactory 的核心原则**\n"
            "你需要严格区分两类信息：\n"
            "- 实质性结果：用户请求的数据、分析结论、操作产出等。\n"
            "- 执行过程描述：执行过程中发生了什么，以及为什么没有拿到实质性结果。\n\n"
            "判断规则：\n"
            "- 只有当用户请求的实质性结果已完整获取时，satisfactory 才为 true。\n"
            "- 如果实质性结果缺失，即使执行过程描述得很详细，satisfactory 也必须为 false。\n"
            "- 执行过程描述（包括失败原因、错误说明、状态报告等）不能替代实质性结果。\n\n"
            "**重要**：你必须调用 evaluate_summary 工具来输出结果，不要直接输出文本。"
        )

        human_prompt_text = (
            "原始问题：" + original_query + "\n\n"
            "上游传入上下文：" + upstream_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "本层自身执行结果：\n" + own_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "委托给下游 SG 的返回结果（可能已包含多级汇总）：\n" + del_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "请调用 evaluate_summary 工具输出结果。"
        )

        try:
            llm = self._get_orchestration_llm()
            history_messages = await self.get_history()

            # Build the same ChatPromptTemplate used by the planner
            chat_prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_prompt_text),
                *history_messages,
                HumanMessagePromptTemplate.from_template(human_prompt_text),
            ])
            messages = chat_prompt.format_messages()

            eval_tool = StructuredTool(
                name="evaluate_summary",
                description=(
                    "输出汇总回答及其充分性评估。"
                    "answer: 回答正文。"
                    "satisfactory: 当前信息是否足以回答问题。"
                    "missing_info: 信息不足时，说明缺少什么信息。"
                    "rationale: 评估决策的一句话理由。"
                ),
                args_schema=SummaryEvaluationResult,
                func=None,
                coroutine=None,
            )

            result_data = await invoke_llm_with_tool(
                llm=llm,
                tool=eval_tool,
                messages=messages,
                metadata={
                    "user_id": user_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                },
                tool_choice="evaluate_summary",
                span_name="skill-summarize-eval",
            )

            if result_data is None:
                logger.warning(
                    "[SummaryEval] LLM did not call evaluate_summary — falling back to "
                    "satisfactory=True"
                )
                return SummaryEvaluationResult(
                    answer="汇总阶段：LLM 未调用评估工具，请重试。",
                    satisfactory=True,
                    missing_info="",
                    rationale="LLM did not call evaluate_summary tool",
                )

            return SummaryEvaluationResult(
                answer=result_data.get("answer", ""),
                satisfactory=bool(result_data.get("satisfactory", True)),
                missing_info=result_data.get("missing_info", ""),
                rationale=result_data.get("rationale", ""),
            )

        except Exception as e:
            logger.error("[SummaryEval] LLM summarization failed: %s", e)
            return SummaryEvaluationResult(
                answer=(
                    "由于汇总阶段出错，未能生成综合答案。以下为各协作 SG 返回的原始结果：\n\n"
                    f"{own_text}\n\n"
                    f"{del_text}"
                ),
                satisfactory=True,
                missing_info="",
                rationale=f"LLM call failed: {e}",
            )

    async def _summarize(
        self,
        original_query: str,
        task_results: dict[int, str],
        delegate_results: dict[str, str],
        upstream_context: dict | None = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> str:
        """Use LLM to summarize all task results into a final answer.

        Injects upstream_context, conversation history, and annotates task statuses.
        """
        own_text = "\n".join(
            f"[Task#{tid}] {res}" for tid, res in task_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}] {res}" for name, res in delegate_results.items() if res
        )
        upstream_text = (json.dumps(upstream_context, ensure_ascii=False)
                         if upstream_context else "无")

        system_prompt_text = (
            "你是一位知识分析与总结专家。你的任务是基于提供的执行结果和对话上下文，"
            "通过逻辑严密的分析，回答用户的原始问题。\n\n"
            "**核心原则**\n"
            "1. 直接输出答案正文，从实质内容开始。\n"
            "2. 不要自我介绍，不要说明你是汇总器或 agent，不要描述协作/整合过程。\n"
            "3. 不要使用「好的，作为…」「我已收到/整合了…」「以下是针对…的完整/综合回答」等开场白。\n"
            "4. 下游结果中若含类似套话，请忽略并只提取实质信息，不要在输出中重复。\n"
            "5. 信息冲突时简要说明；缺信息时说明缺什么，勿编造。\n"
            "6. 对话历史仅用于理解当前问题的指代和语境，不要将历史中的旧结论当作当前事实。\n"
        )

        human_prompt_text = (
            "原始问题：" + original_query + "\n\n"
            "上游传入上下文：" + upstream_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "本层自身执行结果：\n" + own_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "委托给下游 SG 的返回结果（可能已包含多级汇总）：\n" + del_text.replace("{", "{{").replace("}", "}}") + "\n\n"
            "请直接输出答案："
        )

        try:
            llm = self._get_orchestration_llm()
            history_messages = await self.get_history()
            chat_prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_prompt_text),
                *history_messages,
                HumanMessagePromptTemplate.from_template(human_prompt_text),
            ])
            messages = chat_prompt.format_messages()

            with langfuse.start_as_current_span(
                name="skill-agent-summarize",
                trace_context={"trace_id": trace_id}
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": original_query}
                )

                answer = await llm.ainvoke(
                    messages,
                    config={"callbacks": [langfuse_handler]},
                )
                final_text = str(getattr(answer, "content", "") or "").strip()

                span.update_trace(output={"answer": final_text})

            langfuse.flush()
            return final_text
        except Exception as e:
            logger.error("[Summary] LLM summarization failed: %s", e)
            return (
                "由于汇总阶段出错，未能生成综合答案。以下为各协作 SG 返回的原始结果：\n\n"
                f"{own_text}\n\n"
                f"{del_text}"
            )

    # ------------------------------------------------------------------
    # Capability check
    # ------------------------------------------------------------------

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        request_metadata = context.metadata if isinstance(context.metadata, dict) else {}
        md = request_metadata

        card = self.agent_card
        agent_name = card.name if card else "SkillAgent"
        agent_description = (card.description if card else "") or ""
        agent_url = (card.url if card else "") or ""

        agent_skills_text = "（无）"
        if card and card.skills:
            skills_lines = []
            for skill in card.skills:
                skill_desc = f"- {skill.name}: {skill.description}"
                if hasattr(skill, "tags") and skill.tags:
                    skill_desc += f" (tags: {', '.join(skill.tags)})"
                skills_lines.append(skill_desc)
            agent_skills_text = "\n".join(skills_lines)

        history_text = _history_text_from_metadata(md)
        _cc_start = _time.monotonic()

        try:
            mgr = ModelManager()
            _extra_body = (
                {"enable_thinking": False}
                if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
                else {}
            )
            llm = mgr.get_llm(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=0.01,
                stream=False,
                extra_body=_extra_body,
            )
            prompt = SKILL_CAPABILITY_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                history=history_text,
                query=query,
            )
            cap_tool = StructuredTool(
                name="evaluate_capability",
                description="评估本智能体能否处理用户问题",
                args_schema=CapabilityCheckToolResult,
                func=None,
                coroutine=None,
            )
            result_data = await invoke_llm_with_tool(
                llm=llm,
                tool=cap_tool,
                messages=[HumanMessage(content=prompt)],
                metadata=md,
                tool_choice="evaluate_capability",
                span_name="skill-capability-check-llm",
            )
            if result_data is None:
                raise ValueError("LLM did not call evaluate_capability tool")

            # Normalize (aligned with SD orchestrator _normalize_member_capability_judgment)
            can_handle, can_contribute = _normalize_capability_result(result_data)
            try:
                conf = float(result_data.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            reason = str(result_data.get("reason") or "").strip()[:500]

            leaf_path = [agent_name]
            check_response = sg_broadcast.CapabilityCheckResponse(
                can_handle=can_handle,
                confidence=round(conf, 2),
                reason=reason,
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": round(conf, 2), "alias": _path_to_alias(leaf_path)}],
                can_contribute=can_contribute,
                contribution=str(result_data.get("contribution", "")),
                execution_strategy="single",
                collaboration_agents=[],
                collaboration_roles={},
                collaboration_paths=[],
                member_results=[],
                degraded=False,
                unavailable_count=0,
                missing_requirements=[],
                execution_hint={},
                latency_ms=int((_time.monotonic() - _cc_start) * 1000),
            )
        except Exception as e:
            logger.error("Capability check failed: %s", e, exc_info=True)
            leaf_path = [agent_name]
            check_response = sg_broadcast.CapabilityCheckResponse(
                can_handle=False,
                confidence=0.0,
                reason=f"Analysis failed: {str(e)}",
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": 0.0, "alias": _path_to_alias(leaf_path)}],
                execution_strategy="single",
                collaboration_agents=[],
                collaboration_roles={},
                collaboration_paths=[],
                member_results=[],
                degraded=False,
                unavailable_count=0,
                missing_requirements=[],
                execution_hint={},
                latency_ms=int((_time.monotonic() - _cc_start) * 1000),
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
        await updater.add_artifact([TextPart(text=response_json)], name="capability-check-response")
        await updater.complete(message=new_agent_text_message("", context_id=task.context_id))

    async def handle_pre_make_plan(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """Handle a pre-make-plan request from the routing agent.

        Called when the routing agent sends ``message_type="pre_make_plan"``
        to evaluate this agent's task-planning capability before making a
        final routing decision.  The agent runs :meth:`make_plan` with the
        query and returns the resulting ``TaskList`` as JSON.
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

        # --- Data Flow: log upstream context at pre-make-plan entry ---
        upstream_context = dict(metadata.get("upstream_context", {}))
        _upstream_summary = self._format_upstream_context_summary(upstream_context)
        if _upstream_summary != "(none)":
            logger.info(
                "[PreMakePlan] upstream_context received | agent=%s upstream=%s",
                self.agent_id,
                _upstream_summary,
            )

        try:
            all_cards, own_names, collab_names = await self._resolve_planner_agent_pool(query)

            base_group_memory = await self._get_memory(query)
            group_memory = self._enrich_group_memory_with_upstream(
                upstream_context=upstream_context,
                base_group_memory=base_group_memory,
            )

            planner = self._get_planner()
            plan = await planner.make_plan(query, all_cards, group_memory=group_memory)

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
            logger.error("[PreMakePlan] agent=%s failed: %s", self.agent_id, e, exc_info=True)
            response = json.dumps({"error": str(e)})

        await updater.add_artifact(
            [TextPart(text=response)],
            name="pre-make-plan-response",
        )
        await updater.complete(message=new_agent_text_message("", context_id=task.context_id))

    # ------------------------------------------------------------------
    # Main execute — full orchestration flow
    # ------------------------------------------------------------------

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        metadata = dict(context.metadata or {})
        self.metadata = metadata

        if isinstance(metadata, dict) and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            await self.handle_capability_check(context, event_queue, query)
            return

        if isinstance(metadata, dict) and metadata.get("message_type") == PRE_MAKE_PLAN_MESSAGE_TYPE:
            await self.handle_pre_make_plan(context, event_queue, query)
            return

        user_id = str(metadata.get("user_id", ""))
        run_id = str(metadata.get("run_id", ""))
        trace_id = str(metadata.get("trace_id", ""))
        self._progress_context = {
            "run_id": run_id,
            "user_id": user_id,
            "agent_id": self.agent_id,
        }

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # ------------------------------------------------------------------
        # Extract cross-SG delegation context early (needed for both
        # pre-exec and mid-exec delegation paths).  Mirrors the orchestrator
        # execute_collaborative entry point.
        # ------------------------------------------------------------------
        is_delegated = metadata.get("collaboration_delegation") is True
        hop_remaining = int(metadata.get("hop_remaining", 0))
        delegation_chain = list(metadata.get("delegation_chain", []))
        upstream_context = dict(metadata.get("upstream_context", {}))

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

        # Guard: hop exhausted — stop immediately, do not execute any tasks.
        if is_delegated and current_hop <= 0:
            await self._emit_progress(
                updater,
                "collab_started",
                message=(
                    f"Collaborative execution aborted (SG: {self.agent_id}, "
                    f"delegated: {is_delegated}, hop: {current_hop}) — hop exhausted"
                ),
                status="done",
                extra={
                    "sg_label": self.agent_id,
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

        await self._emit_progress(
            updater,
            "collab_started",
            message=(
                f"Collaborative execution started (SG: {self.agent_id}, "
                f"delegated: {is_delegated}, hop: {current_hop})"
            ),
            status="running",
            extra={
                "sg_label": self.agent_id,
                "is_delegated": is_delegated,
                "hop": current_hop,
                "chain_depth": len(delegation_chain),
            },
        )
        # --- Data Flow: log upstream context at entry ---
        _upstream_summary = self._format_upstream_context_summary(upstream_context)
        logger.info(
            "[Cross-SG][CollabEntry] execute started | agent=%s is_delegated=%s hop=%d chain=%s upstream=%s",
            self.agent_id,
            is_delegated,
            current_hop,
            delegation_chain,
            _upstream_summary,
        )

        # ------------------------------------------------------------------
        # Step 1: Ensure SkillRunner is ready
        # ------------------------------------------------------------------
        skill_runner = await self._ensure_skill_runner()

        # ------------------------------------------------------------------
        # Step 2: Build agent card pool for planner (routing pool flow)
        # ------------------------------------------------------------------
        # Log routing pool received from upstream if present
        if isinstance(metadata, dict) and metadata.get(sg_broadcast.ROUTING_AGENT_POOL_KEY):
            sg_broadcast.log_routing_agent_pool_received(metadata)

        self._init_routing_pool_from_metadata(metadata)
        all_cards, own_names, collab_names = await self._resolve_planner_agent_pool(query)
        local_name = self._self_planner_agent_name()

        logger.info(
            "[Orchestration] planning pool: local=%s peers=%d total=%d own_names=%s collab_names=%s",
            local_name,
            len(collab_names),
            len(all_cards),
            sorted(own_names) if own_names else "(none)",
            sorted(collab_names) if collab_names else "(none)",
        )

        # ------------------------------------------------------------------
        # Step 3-5: Execute plan and mid-exec loop (extracted method)
        # ------------------------------------------------------------------
        all_task_results, delegate_results, _remaining_hop = await self._execute_plan_and_mid_exec(
            query=query,
            all_cards=all_cards,
            own_names=own_names,
            collab_names=collab_names,
            skill_runner=skill_runner,
            metadata=metadata,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
            updater=updater,
            upstream_context=upstream_context,
            is_delegated=is_delegated,
            current_hop=current_hop,
            delegation_chain=delegation_chain,
        )

        # ------------------------------------------------------------------
        # Step 6: Summarize results
        # ------------------------------------------------------------------
        await self._emit_progress(
            updater,
            "summarizing",
            message="Summarizing results from all sources...",
            status="running",
        )

        # --- Data Flow: summary input ---
        self._log_summary_input(
            task_results=all_task_results,
            delegate_results=delegate_results,
        )

        final_answer = await self._summarize(
            original_query=query,
            task_results=all_task_results,
            delegate_results=delegate_results,
            upstream_context=upstream_context,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
        )

        # --- Data Flow: summary output ---
        self._log_data_flow(
            direction="SUMMARY_OUTPUT",
            description=f"Summary LLM 产出最终回答 → 返回 {self._self_planner_agent_name()}",
            source_id="SummaryLLM",
            target_id=self._self_planner_agent_name(),
            payload_chars=len(final_answer or ""),
            payload_preview=(final_answer or "")[:1000],
        )

        await self._emit_progress(
            updater,
            "final_answer_ready",
            message=f"Final answer ready ({len(final_answer)} chars)",
            status="done",
            extra={"answer_chars": len(final_answer)},
        )

        # ------------------------------------------------------------------
        # Step 7: Return final answer
        # ------------------------------------------------------------------
        await updater.add_artifact(
            [TextPart(text=final_answer)],
            name="final-answer",
        )

        # Persist conversation history (aligned with SG orchestrator)
        md = self.metadata if isinstance(self.metadata, dict) else {}
        owner_agent_id = md.get("history_owner_agent_id")
        is_not_owner = bool(owner_agent_id) and owner_agent_id != self.agent_id
        if md.get("skip_history_write") or is_not_owner:
            skip_reason = "skip_history_write" if md.get("skip_history_write") else "not_owner"
            logger.info(
                "[HistoryFlow] skill-agent history-skip reason=%s skip_history_write=%s "
                "owner=%s self=%s run_id=%s",
                skip_reason,
                md.get("skip_history_write"),
                owner_agent_id,
                self.agent_id,
                md.get("run_id", ""),
            )
        else:
            await self.add_history(query, final_answer)

        # add memory — fire-and-forget so a slow/failing upstream never
        # blocks the stream close or surfaces an exception to the caller.
        self.schedule_add_memory(query, final_answer)

        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

    # ------------------------------------------------------------------
    # Turn support: execute plan → execute → mid-exec as a reusable unit
    # ------------------------------------------------------------------

    async def _execute_plan_and_mid_exec(
        self,
        query: str,
        all_cards: list[AgentCard],
        own_names: set[str],
        collab_names: set[str],
        skill_runner: "SkillRunner | None",
        metadata: dict,
        user_id: str,
        run_id: str,
        trace_id: str,
        updater: TaskUpdater,
        upstream_context: dict,
        is_delegated: bool,
        current_hop: int,
        delegation_chain: list[str],
        failure_context: str = "",
    ) -> tuple[dict[int, str], dict[str, str], int]:
        """Execute Steps 3-5 (plan → execute tasks → mid-exec loop).

        Extracted from :meth:`execute` so that subclasses can wrap this in a
        turn-based retry loop.  When *failure_context* is non-empty it is
        injected into the planner's ``group_memory`` so the next turn can
        adjust its decomposition strategy.

        Returns
        -------
        tuple[dict[int, str], dict[str, str], int]
            ``(all_task_results, delegate_results, remaining_hop)``.
            ``remaining_hop`` is the hop count after all pre-exec and mid-exec
            delegations have been consumed.  Callers should use this to decide
            whether further delegation is possible.
        """
        # ------------------------------------------------------------------
        # Step 3: Plan tasks (with group_memory injection + upstream context)
        # ------------------------------------------------------------------
        await self._emit_progress(
            updater,
            "planning_started",
            message=f"Planning tasks for query: {_short(query)}",
            status="running",
            extra={"query_preview": _short(query)},
        )

        base_group_memory = await self._get_memory(query)
        group_memory = self._enrich_group_memory_with_upstream(
            upstream_context=upstream_context,
            base_group_memory=base_group_memory,
        )
        execution_hint = self._validated_execution_hint(metadata, query)
        if execution_hint:
            note = self._execution_hint_memory_note(execution_hint)
            group_memory = f"{group_memory}\n\n{note}".strip() if group_memory else note
            logger.info(
                "[Capability][ExecutionHint] injected into planning context | run_id=%s "
                "selected=%s",
                run_id,
                (execution_hint.get("selected_members") or [])[:10],
            )

        # Inject failure context from previous turn (if any)
        if failure_context:
            group_memory = f"{group_memory}\n\n{failure_context}" if group_memory else failure_context
            logger.info(
                "[TurnLoop] failure_context injected | chars=%d",
                len(failure_context),
            )

        logger.info(
            "[Orchestration] group_memory prepared | base_chars=%d enriched_chars=%d",
            len(base_group_memory or ""),
            len(group_memory or ""),
        )
        planner = self._get_planner()
        plan = await planner.make_plan(query, all_cards, group_memory=group_memory)

        task_lines = "\n".join(
            f"{i}. {t.description or '(无描述)'}"
            f"{'  [depends_on: ' + str(t.depends_on) + ']' if t.depends_on else ''}"
            for i, t in enumerate(plan.tasks, 1)
        )
        await self._emit_progress(
            updater,
            "plan_ready",
            message=f"Plan ready: {len(plan.tasks)} tasks\n{task_lines}",
            status="running",
            extra={
                "task_count": len(plan.tasks),
                "plan_tasks_summary": [
                    {
                        "id": t.id,
                        "agent": t.agent,
                        "desc": (t.description or "")[:80],
                        "depends_on": t.depends_on or [],
                    }
                    for t in plan.tasks
                ],
            },
        )

        # ------------------------------------------------------------------
        # Step 4: Execute tasks sequentially
        # ------------------------------------------------------------------
        own_results: dict[int, str] = {}
        delegate_results: dict[str, str] = {}
        all_task_results: dict[int, str] = {}
        self._tasks_status_list: list[dict] = []

        for task_item in plan.tasks:
            agent_name = (task_item.agent or "").strip()

            # NONE tasks — skip
            if agent_name.upper() == "NONE":
                continue

            # ---- Dependency guard: preflight check ----
            if task_item.depends_on and DEPENDENCY_CHECK_ENABLED:
                dep_verdict = await self._preflight_dependency_check(
                    task_id=task_item.id,
                    task_description=task_item.description or "",
                    task_agent=agent_name,
                    depends_on=list(task_item.depends_on),
                )
                if dep_verdict is not None:
                    reason = f"dependency_unmet: upstream tasks {dep_verdict.get('unmet_upstream_ids', [])} failed"
                    all_task_results[task_item.id] = reason
                    self._tasks_status_list.append({
                        "id": task_item.id,
                        "description": task_item.description,
                        "agent": agent_name,
                        "status": "fail",
                        "failure_reason_code": DEPENDENCY_UNMET_REASON,
                        "answer": reason,
                    })
                    logger.info("[Orchestration] task #%d blocked by dependency guard", task_item.id)
                    continue

            # Check if this is a dependency chain — refine query if needed
            task_query = task_item.description or ""
            if self._llm_dependent_query_refine_enabled() and task_item.depends_on:
                deps = list(task_item.depends_on)
                if all(
                    tid in all_task_results and (all_task_results.get(tid) or "").strip()
                    for tid in deps
                ):
                    upstream_blob = "\n\n".join(
                        f"=== Task #{tid} ===\n{all_task_results.get(tid, '')}"
                        for tid in sorted(deps)
                    )
                    refined = await self._llm_refine_dependent_task_query(
                        original_query=query,
                        planned_downstream_description=task_item.description or "",
                        downstream_agent_name=agent_name,
                        upstream_results_blob=upstream_blob,
                        user_id=user_id,
                        run_id=run_id,
                        trace_id=trace_id,
                    )
                    if refined.startswith(DEPENDENT_TASK_SKIP_MARKER):
                        logger.info("[Orchestration] task #%d skipped — upstream data invalid", task_item.id)
                        all_task_results[task_item.id] = refined
                        self._tasks_status_list.append({
                            "id": task_item.id,
                            "description": task_item.description,
                            "agent": agent_name,
                            "status": "fail",
                            "failure_reason_code": DEPENDENT_TASK_SKIP_MARKER,
                            "answer": refined,
                        })
                        continue
                    task_query = refined

            # --- Local execution (self or local skill) ---
            if agent_name in own_names:
                await self._emit_progress(
                    updater,
                    "task_started",
                    message=f"Executing local task #{task_item.id}: {_short(task_query)}",
                    status="running",
                    task_id=task_item.id,
                    extra={"task_id": task_item.id, "agent": agent_name, "desc_preview": _short(task_query)},
                )

                # --- Data Flow: local task execution (in-process SkillAgent, no A2A) ---
                self._log_data_flow(
                    direction="LOCAL_TASK_EXEC",
                    description=f"Task #{task_item.id} → 本地 SkillAgent 执行",
                    source_id=self.agent_id,
                    target_id=f"{agent_name} (in-process)",
                    payload_chars=len(task_query or ""),
                    payload_preview=(task_query or "")[:1000],
                    metadata_extra={
                        "task_id": task_item.id,
                        "task_desc_chars": len(task_query or ""),
                    },
                )

                local_agent = SkillAgent(
                    skill_runner=skill_runner,
                    query=task_query,
                    metadata=metadata,
                    current_task_id=task_item.id,
                    agent_id=self.agent_id,
                )
                result_parts: list[str] = []
                async for chunk in local_agent.run():
                    if chunk:
                        result_parts.append(chunk)
                result = "\n".join(result_parts)
                own_results[task_item.id] = result
                all_task_results[task_item.id] = result
                is_fail = result.startswith("Delegation failed:") or result.startswith("Execution error:") or not result.strip()
                self._tasks_status_list.append({
                    "id": task_item.id,
                    "description": task_item.description,
                    "agent": agent_name,
                    "status": "fail" if is_fail else "complete",
                    "answer": result,
                })
                if is_fail and self._is_local_skill_task(task_item) and local_agent.reason_code:
                    self._apply_local_skill_reason_code(task_item.id, local_agent.reason_code)

                # --- Data Flow: local task result ---
                self._log_data_flow(
                    direction="LOCAL_TASK_RESULT",
                    description=f"Task #{task_item.id} 执行完毕",
                    source_id=agent_name,
                    target_id=self.agent_id,
                    payload_chars=len(result or ""),
                    payload_preview=(result or "")[:1000],
                    metadata_extra={
                        "task_id": task_item.id,
                        "status": "fail" if is_fail else "complete",
                    },
                )

                await self._emit_progress(
                    updater,
                    "task_finished",
                    message=f"Local task #{task_item.id} done ({len(result)} chars)",
                    status="done",
                    task_id=task_item.id,
                    extra={"task_id": task_item.id, "agent": agent_name, "result_chars": len(result)},
                )

            # --- Peer delegation (use collab_names for SG delegation) ---
            # NOTE: every delegation edge consumes 1 hop.  The receiver will
            # further decrement when it delegates onward.
            elif agent_name in collab_names:
                if current_hop <= 1:
                    logger.warning(
                        "[Cross-SG][PreExecDelegation] hop exhausted | agent=%s current_hop=%d",
                        agent_name,
                        current_hop,
                    )
                    all_task_results[task_item.id] = NONE_TASK_DESCRIPTION
                    self._tasks_status_list.append({
                        "id": task_item.id,
                        "description": task_item.description,
                        "agent": agent_name,
                        "status": "fail",
                        "failure_reason_code": "hop_exhausted",
                        "answer": NONE_TASK_DESCRIPTION,
                    })
                    continue

                # Consume 1 hop for this delegation edge.
                current_hop -= 1
                _next_hop = current_hop
                _new_chain = delegation_chain + [self._self_planner_agent_name()]

                target_card = next((c for c in all_cards if getattr(c, "name", "") == agent_name), None)
                if target_card is None:
                    logger.warning("[Orchestration] task #%d: no peer card found for agent=%s", task_item.id, agent_name)
                    continue

                # Build upstream context with completed results so far
                _completed_tasks_context = [
                    {
                        "task_id": tid,
                        "description": "",
                        "agent": "",
                        "status": "completed",
                        "result": res,
                    }
                    for tid, res in all_task_results.items() if res
                ]
                _ctx: dict[str, Any] = {
                    "delegator_plan": [t.dict() for t in plan.tasks],
                    "executed_tasks": _completed_tasks_context,
                    "key_findings_so_far": "\n".join(
                        f"[Task#{tid}] {res[:300]}"
                        for tid, res in all_task_results.items() if res
                    ),
                    "upstream_context": upstream_context,
                }

                await self._emit_progress(
                    updater,
                    "task_delegating",
                    message=(
                        f"Pre-exec delegating Task #{task_item.id} to [{agent_name}] "
                        f"(hop: {_next_hop}): {_short(task_query, 120)}"
                    ),
                    status="running",
                    task_id=task_item.id,
                    extra={
                        "task_id": task_item.id,
                        "target_sg": agent_name,
                        "desc_preview": _short(task_query),
                        "remaining_hop": _next_hop,
                    },
                )

                logger.info(
                    "[Cross-SG][PreExecDelegation] delegating | task_id=%d target_sg=%s hop=%d chain=%s desc_preview=%s",
                    task_item.id,
                    agent_name,
                    _next_hop,
                    _new_chain,
                    (task_query or "")[:100],
                )

                # --- Data Flow: upstream context being packed for delegation ---
                _ctx_chars = len(json.dumps(_ctx, ensure_ascii=False))
                self._log_data_flow(
                    direction="PRE_DELEGATE_SEND",
                    description=f"委派给 [{agent_name}] — 构造 upstream_context",
                    source_id=self._self_planner_agent_name(),
                    target_id=agent_name,
                    payload_chars=_ctx_chars,
                    payload_preview=(
                        f"delegator_plan (tasks={len(plan.tasks)}), "
                        f"executed_tasks (count={len(_completed_tasks_context)}), "
                        f"key_findings_so_far ({len(_ctx.get('key_findings_so_far','') or '')} chars)"
                    ),
                    metadata_extra={
                        "delegation_chain": _new_chain,
                        "hop_remaining": _next_hop,
                        "task_description": (task_query or "")[:200],
                    },
                )

                result = await self._delegate_to_peer(
                    task_query,
                    target_card,
                    user_id,
                    run_id,
                    trace_id,
                    hop_remaining=_next_hop,
                    delegation_chain=_new_chain,
                    upstream_context=_ctx,
                    updater=updater,
                )
                delegate_results[agent_name] = result
                all_task_results[task_item.id] = result
                is_fail = result.startswith("Delegation failed:") or result.startswith("Execution error:") or not result.strip()
                self._tasks_status_list.append({
                    "id": task_item.id,
                    "description": task_item.description,
                    "agent": agent_name,
                    "status": "fail" if is_fail else "complete",
                    "answer": result,
                })

                # --- Data Flow: delegation result received ---
                self._log_data_flow(
                    direction="PRE_DELEGATE_RECV",
                    description=f"委派 [{agent_name}] 结果返回 → delegated_results 字典",
                    source_id=agent_name,
                    target_id=self._self_planner_agent_name(),
                    payload_chars=len(result or ""),
                    payload_preview=(result or "")[:1000],
                    metadata_extra={"hop_used": _next_hop, "chain": _new_chain},
                )

                await self._emit_progress(
                    updater,
                    "task_finished",
                    message=f"Delegated task #{task_item.id} to {agent_name} done ({len(result)} chars)",
                    status="done",
                    task_id=task_item.id,
                    extra={"task_id": task_item.id, "target_sg": agent_name, "result_chars": len(result)},
                )

        # ------------------------------------------------------------------
        # Step 5: Mid-execution loop (Detect → Select → Plan → Dispatch)
        # ------------------------------------------------------------------
        # Guard: if hop is already exhausted, skip mid-exec entirely.
        if current_hop <= 1:
            logger.info("[MidExec] hop exhausted (current_hop=%d), skipping mid-exec loop", current_hop)
            return all_task_results, delegate_results, current_hop

        await self._emit_progress(
            updater,
            "mid_exec_started",
            message="Checking if local results are sufficient...",
            status="running",
        )

        max_mid_exec_rounds = int(os.getenv("CROSS_SG_MID_EXEC_ROUNDS", "3"))
        mid_exec_round = 0
        collaborator_cards_list = [
            c for c in all_cards if getattr(c, "name", "") in collab_names
        ]

        # Build upstream context with executed tasks and delegator plan for the mid-exec loop
        own_task_context = [
            {
                "id": tid,
                "description": (task_item.description or ""),
                "agent": (task_item.agent or ""),
                "status": "completed",
                "result": res,
            }
            for task_item in plan.tasks
            for tid, res in own_results.items()
            if tid == task_item.id and res
        ]
        key_findings_so_far = "\n".join(
            f"[Task#{tid}] {res[:300]}"
            for tid, res in all_task_results.items() if res
        )

        mid_upstream: dict[str, Any] = dict(upstream_context)
        mid_upstream["delegator_plan"] = [t.dict() for t in plan.tasks]
        mid_upstream["executed_tasks"] = own_task_context
        mid_upstream["key_findings_so_far"] = key_findings_so_far

        while mid_exec_round < max_mid_exec_rounds:
            # Guard: if hop is exhausted, no further delegation is possible.
            # Skip remaining rounds to avoid wasting LLM calls (detect, select,
            # plan) when dispatch will only produce NONE_TASK_DESCRIPTION.
            if current_hop <= 1:
                logger.info(
                    "[MidExec] hop exhausted (current_hop=%d) at round %d, "
                    "exiting mid-exec loop",
                    current_hop,
                    mid_exec_round + 1,
                )
                await self._emit_progress(
                    updater,
                    "mid_exec_hop_exhausted",
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

            if not collaborator_cards_list:
                collaborator_cards_list = await self._load_mid_exec_broadcast_candidates(
                    extra_cards=collaborator_cards_list,
                )
                if not collaborator_cards_list:
                    logger.info("[MidExec] no broadcast SG candidates, exiting loop")
                    break

            logger.info("[MidExec] round %d / %d started", mid_exec_round + 1, max_mid_exec_rounds)

            # Step 1: Detect
            detection = await self._detect_delegation_needs(
                query=query,
                own_results=own_results,
                delegated_results=delegate_results,
                collaborator_cards=collaborator_cards_list,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
            if detection is None:
                await self._emit_progress(
                    updater,
                    "mid_exec_detect_none",
                    message="检测当前结果：无需补充数据，所有信息已完整",
                    status="done",
                    extra={
                        "round": mid_exec_round + 1,
                    },
                )
                logger.info("[MidExec] no further delegation needed, exiting loop")
                break

            reason_text = (detection.get("reason") or "")[:400]
            target_sgs = list(detection.get("target_sgs") or [])
            # Filter out LLM-hallucinated agent names that don't exist in collaborator pool
            if target_sgs and collaborator_cards_list:
                valid_names = {c.name for c in collaborator_cards_list if getattr(c, "name", "")}
                target_sgs = [n for n in target_sgs if n in valid_names]
            detection_source = detection.get("source") or "llm_detection"
            target_label = ", ".join(target_sgs)
            reason_part = f"原因：{_short(reason_text, 300)}" if reason_text.strip() else ""
            if target_label:
                message_parts = [
                    f"检测到数据缺口：需要 {target_label} 补充数据。"
                ]
            else:
                message_parts = ["检测到数据缺口。"]
            if reason_part:
                message_parts.append(reason_part)
            await self._emit_progress(
                updater,
                "mid_exec_detect_result",
                message=" ".join(message_parts),
                status="running",
                extra={
                    "needs_help": True,
                    "reason": reason_text,
                    "target_sgs": target_sgs,
                    "round": mid_exec_round + 1,
                    "detection_source": detection_source,
                },
            )

            synthesized_query = detection.get("synthesized_query", "")
            soft_target_hints = list(detection.get("target_sgs") or [])
            if not synthesized_query:
                break

            # Step 1.5: Select targets via concurrent capability_check
            target_sg_names: list[str] = []
            target_cards_list: list[AgentCard] = []
            hints_by_sg: dict[str, dict] = {}
            capability_evidence = ""
            if self._mid_delegate_capability_select_enabled():
                selection = await self._select_mid_delegate_targets_via_capability(
                    synthesized_query=synthesized_query,
                    collaborator_cards=collaborator_cards_list,
                    soft_target_hints=soft_target_hints,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                )
                target_cards_list = list(selection.get("target_cards") or [])
                target_sg_names = list(selection.get("target_sg_names") or [])
                hints_by_sg = dict(selection.get("hints_by_sg") or {})
                capability_evidence = str(selection.get("evidence_text") or "")
                if not target_cards_list:
                    logger.info("[MidExec] no capable remote SG, exiting loop")
                    break
            else:
                target_sg_names = soft_target_hints
                target_cards_list = [c for c in collaborator_cards_list if c.name in target_sg_names]
                if not target_cards_list:
                    break

            # Step 2: Plan
            mid_group_memory = self._enrich_group_memory_with_upstream(
                upstream_context=mid_upstream,
                base_group_memory=group_memory,
                extra_context={
                    "already_delegated": [
                        {"target_sg": name, "result": result or ""}
                        for name, result in delegate_results.items() if result
                    ],
                    "synthesized_query": synthesized_query,
                    "detection_reason": detection.get("reason", ""),
                    "capability_check_evidence": capability_evidence,
                },
            )
            if capability_evidence:
                mid_group_memory = f"{mid_group_memory}\n\n{capability_evidence}" if mid_group_memory else capability_evidence

            mid_plan = await self._plan_mid_exec_delegation(
                synthesized_query=synthesized_query,
                target_cards=target_cards_list,
                group_memory=mid_group_memory,
            )
            if mid_plan is None:
                logger.warning("[MidExec] plan returned None, exiting loop")
                break

            # Fallback: if planner returned all-NONE tasks but capability
            # check already confirmed capable targets, build a synthetic
            # plan to dispatch directly to those targets.
            if mid_plan.tasks and all(
                (t.agent or "").strip().upper() == "NONE" for t in mid_plan.tasks
            ) and target_cards_list:
                logger.warning(
                    "[MidExec][Plan] planner returned all-NONE, "
                    "falling back to capability-checked targets: %s",
                    [c.name for c in target_cards_list],
                )
                fallback_tasks = []
                for i, card in enumerate(target_cards_list, start=1):
                    fallback_tasks.append(
                        PlannerTask(
                            id=i,
                            description=synthesized_query,
                            agent=card.name,
                        )
                    )
                mid_plan = TaskList(
                    thought_process=(
                        f"Planner returned NONE; "
                        f"fallback to capability-checked targets: "
                        f"{[c.name for c in target_cards_list]}"
                    ),
                    original_query=synthesized_query,
                    tasks=fallback_tasks,
                )
                logger.info(
                    "[MidExec][Plan] fallback plan built | tasks=%d agents=%s",
                    len(fallback_tasks),
                    [c.name for c in target_cards_list],
                )

            # Step 3: Dispatch
            # Build enriched upstream context for dispatch
            dispatch_ctx: dict[str, Any] = dict(mid_upstream)
            dispatch_ctx.update({
                "already_delegated": [
                    {"target_sg": name, "result": result or ""}
                    for name, result in delegate_results.items() if result
                ],
                "mid_exec_round": mid_exec_round + 1,
                "synthesized_query": synthesized_query,
                "detection_reason": detection.get("reason", ""),
            })
            # --- Data Flow: mid-exec round dispatch ---
            _mid_ctx_chars = len(json.dumps(dispatch_ctx, ensure_ascii=False))
            target_sg_names = list(target_sg_names) if target_sg_names else []
            self._log_data_flow(
                direction="MID_DISPATCH_SEND",
                description=f"Mid-exec R{mid_exec_round+1} 委派出参 → 目标 SGs {target_sg_names}",
                source_id=self._self_planner_agent_name(),
                target_id=", ".join(target_sg_names) or "?",
                payload_chars=_mid_ctx_chars,
                payload_preview=(
                    f"已委托: {len(delegate_results)} 条, "
                    f"synthesized_query: {(synthesized_query or '')[:200]}"
                ),
                metadata_extra={
                    "mid_exec_round": mid_exec_round + 1,
                    "delegation_chain": delegation_chain,
                },
            )
            mid_results = await self._dispatch_mid_exec_delegation(
                plan=mid_plan,
                target_cards=target_cards_list,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                current_hop=current_hop,
                delegation_chain=delegation_chain,
                upstream_context=dispatch_ctx,
                hints_by_sg=hints_by_sg,
                updater=updater,
            )
            delegate_results.update(mid_results)

            # Consume hop for each actual delegation that happened in this round.
            _actual_mid_delegations = sum(
                1 for v in mid_results.values()
                if v and v != NONE_TASK_DESCRIPTION
            )
            current_hop -= _actual_mid_delegations

            # Merge delegated results into own_results for next round detection
            for sg_name, result in mid_results.items():
                # --- Data Flow: mid-exec result received ---
                self._log_data_flow(
                    direction="MID_DISPATCH_RECV",
                    description=f"Mid-exec 委派 [{sg_name}] 结果返回 → delegated_results 字典",
                    source_id=sg_name or "?",
                    target_id=self._self_planner_agent_name(),
                    payload_chars=len(result or ""),
                    payload_preview=(result or "")[:1000],
                )
                fake_task_id = 10000 + mid_exec_round * 100 + len(delegate_results)
                own_results[fake_task_id] = f"[从 {sg_name} 获取]: {result}"

            mid_exec_round += 1

        await self._emit_progress(
            updater,
            "mid_exec_done",
            message=f"Mid-execution complete ({len(delegate_results)} total delegations)",
            status="done",
            extra={"mid_delegate_count": len(delegate_results), "rounds": mid_exec_round},
        )

        return all_task_results, delegate_results, current_hop

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception("cancel not supported")