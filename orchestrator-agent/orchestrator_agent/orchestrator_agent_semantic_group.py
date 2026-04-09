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
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Any, AsyncIterable, Awaitable, Callable, Dict, Literal, List, Optional, Union
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from abc import ABC
from langchain_core.prompts.chat import(
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
    )
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import CallToolRequest, ReadResourceResult
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
    "task_finished": {"task_agent", "task_status"},
    "task_error": set(),
    "group_retry_same_plan": {"retry_count", "reason_code"},
    "group_replan_failed": {"retry_count"},
    "group_tasks_completed": {"task_count"},
    "group_final_answer_ready": {"answer_chars"},
    # Planner assigned NONE: no downstream agent can handle this task
    "task_no_agent_available": {"reason_code", "task_description", "task_agent"},
}

# Do not overwrite DASHSCOPE_API_KEY - use env or explicit api_key for real LLM

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_ZH = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
将用户查询分解为一个或多个可执行任务，并将每个任务分配给合适的**领域负责人**。您必须聚焦于智能体的**领域范围**（业务领域），而不仅仅是其列出的特定技能。

## 战略思考过程（思维链）
在生成JSON之前，执行以下步骤：
1. **领域提取**：识别查询中的核心业务实体（例如"订单"、"天气"、"财务"）。
2. **领域映射**：将这些实体与智能体的描述相匹配。如果某个智能体是"电子商务大师"，则其拥有所有与"订单"相关的逻辑（查询、规划或执行）。
3. **隐含能力**：假定领域专家对其所在领域拥有全面知识。"交易专家"自然能够"分析订单分布"，即使该特定技能未被列出。

## 智能体选择与任务规则
1. **主权优先**：根据哪个智能体的领域覆盖了主题事项来分配任务。
2. **任务分解**：仅当查询确实涉及**多个不同领域**或存在**明确的先后依赖**时，才拆分为多个任务。不要将一个简单问题过度拆分。
3. **"无对应"协议**：仅当任务的议题完全超出所有可用智能体的领域范围时，才使用"NONE"。
4. **名称准确性**：`agent`字段必须与智能体列表中的"name"完全一致。

## ⚠ 任务描述的关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。你的职责是忠实传递用户意图，而不是替用户细化或改写问题。**

1. **忠实转述**：`description` 必须忠实反映用户的原始意图，使用与用户相近的自然语言表述。不要改写、美化或"专业化"用户的问题。
2. **严禁捏造条件**：绝对不允许在 `description` 中添加用户原始问题里没有提到的任何限定条件，包括但不限于：
   - 时间范围（如"2024年"、"最近三个月"、"上季度"）
   - 分类/类别（如"电子产品"、"VIP客户"、"华东地区"）
   - 指标或维度（如"同比增长率"、"客单价分布"、"环比变化"）
   - 数量或阈值（如"Top 10"、"超过1000元"）
   - 排序或聚合方式（如"按月统计"、"分组对比"）
3. **保留用户已有条件**：如果用户自己提到了条件（如"上个月的订单"），则原样保留，不增不减。
4. **宁简勿繁**：当用户问题本身比较宽泛时（如"看看订单情况"），任务描述也应保持宽泛（如"查询订单情况"），让领域专家自行决定如何解读和执行。

**正确示例：**
- 用户："查一下订单情况" → description："查询订单情况" ✅
- 用户："上个月的销售额是多少" → description："查询上个月的销售额" ✅

**错误示例（严禁）：**
- 用户："查一下订单情况" → description："查询2024年Q4电子产品订单的销售额及同比增长" ❌ （捏造了时间、类别、指标）
- 用户："看看客户数据" → description："统计VIP客户的购买频次和客单价分布" ❌ （捏造了分类和指标）

---
**可用智能体：**
{agents}

**上下文参考数据：**
{information}

**组级决策记忆：**
{group_memory}

---
## 输出要求
1. **格式**：仅返回一个有效的JSON字符串。
2. **结构**：
   - `thought_process`：关于领域映射和主权原则的简明推理。
   - `original_query`：原始用户输入。
   - `tasks`：对象列表，包含：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务或问题（忠实于用户原始表述，禁止添加额外条件）。
     - `agent`：确切的智能体名称或"NONE"。

## 示例
{instructions}

或当未找到智能体时：
{none_instructions}

问题：
"""

PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
根据业务领域将用户查询分解为可执行任务。你必须通过 **[执行上下文]** 建立反馈闭环，结合 **[对话历史]** 的语境，确保规划路径既能解决指代关系，又能避免重复失败、复用已有数据。

## 战略思考过程（思维链）
在生成 JSON 之前，请严格执行以下 **业务领域决策流**：

1. **业务领域提取**：识别查询中的核心业务实体（如“订单”、“财务”、“天气”），锁定其所属的业务边界。
2. **[执行上下文] 分析（闭环检查）**：
   - **结果复用**：若 **[执行上下文]** 中已有相关任务的成功结果（如已获取 ID、Token 或数据），直接继承，严禁创建重复的查询任务。
   - **路径纠偏（避坑）**：若显示之前的尝试已失败（报错、权限不足、超时），本次规划必须改变策略（如：更换 Agent、调整参数或在描述中注入修正指令）。
3. **领域主权映射**：
   - **主权优先**：将任务分配给负责该领域的 Agent。若某 Agent 是该领域的唯一代表，将其视为**通用入口**，无视其“不执行查询”等技术性免责声明。
   - **隐含能力**：假定领域专家拥有该业务范畴内的全量知识（如“交易专家”天然能“分析订单分布”）。
4. **依赖编排**：若当前任务需要之前任务的产出，须在 `description` 中明确注入。

## 智能体选择与任务规则（必须严格遵守）
1. **主权优先**：根据哪个智能体的领域覆盖了主题事项来分配任务。
2. **任务分解**：仅当查询确实涉及**多个不同领域**或存在**明确的先后依赖**时，才拆分为多个任务。不要将一个简单问题过度拆分。
3. **"无对应"协议**：仅当任务的议题完全超出所有可用智能体的领域范围时，才使用"NONE"。
4. **名称准确性**：`agent` 字段必须与智能体列表中的“名称”完全一致。

## ⚠ 对话历史使用规则（指代与继承）
1. **仅用于理解指代**：解析“它”、“那个”、“继续”等含义。
2. **禁止无关条件搬运**：不要将历史对话中与当前追问无关的过滤条件搬运到当前任务中。
3. **对比性追问须继承完整上下文**：用户进行对比追问（如“那2024年呢”），必须从历史中完整继承未变化的维度（年份、机构、指标等），确保 `description` 语义自包含。
4. **指代追问必须自包含**：对于“更详细一点”这类指代，描述必须补充历史主题，使其对 Agent 而言是完整的。

## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化或改写问题。**

1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[执行上下文]** 中的关键结果（如已获 ID、特定报错原因）。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户“查订单” → `description`：“查询订单情况” ✅
   - **错误示例**：用户“查订单” → `description`：“查询2024年Q4电子产品订单及同比增长” ❌（捏造了时间、类别、指标）
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。

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

## 输出要求
1. **格式**：仅返回一个有效的JSON字符串。
2. **结构**：
   - `thought_process`：关于领域映射和主权原则的简明推理。
   - `original_query`：原始用户输入。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务或问题（忠实于用户原始表述，禁止添加额外条件；对比性追问需继承完整上下文；指代性追问需补充上下文使其自包含）。
     - `agent`：确切的智能体名称或"NONE"。

## 示例
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


class TaskList(BaseModel):
    """Output schema for the Planner Agent."""

    thought_process: Optional[str] = Field(
        default=None, 
        description='The internal reasoning steps of the planner.'
    )
    
    original_query: Optional[str] = Field(
        description='The original user query for context.'
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
TOP_K_PATHS_PER_TREE = int(os.getenv("TOP_K_PATHS_PER_TREE", "5"))
MAX_PATH_FAILURES_BEFORE_STOP = int(os.getenv("MAX_PATH_FAILURES_BEFORE_STOP", "3"))
MIN_CONTRIBUTION_CONFIDENCE = float(os.getenv("MIN_CONTRIBUTION_CONFIDENCE", "0.6"))
MIN_MULTI_HANDLE_CONFIDENCE = float(os.getenv("MIN_MULTI_HANDLE_CONFIDENCE", "0.6"))
MULTI_HANDLE_GAP_THRESHOLD = float(os.getenv("MULTI_HANDLE_GAP_THRESHOLD", "0.30"))
MAX_MULTI_HANDLE_COLLAB_AGENTS = int(os.getenv("MAX_MULTI_HANDLE_COLLAB_AGENTS", "3"))
ENABLE_REASON_AWARE_RETRY = os.getenv("ENABLE_REASON_AWARE_RETRY", "true").strip().lower() in ("true", "1", "yes")
MAX_SAME_PLAN_RETRY = int(os.getenv("MAX_SAME_PLAN_RETRY", "1"))
NON_RETRYABLE_MARKER = "NON_RETRYABLE::OUT_OF_SCOPE"
MAX_JOIN_KEY_VALUES_PER_KEY = int(os.getenv("MAX_JOIN_KEY_VALUES_PER_KEY", "50"))
JOIN_KEY_ALLOWLIST = [k.strip() for k in os.getenv("JOIN_KEY_ALLOWLIST", "").split(",") if k.strip()]


def _is_non_actionable_free_text(text: str) -> bool:
    """Detect vague filler text that does not define concrete contribution or work."""
    normalized = re.sub(r"\s+", " ", str(text or "").strip()).lower()
    if len(normalized) < 6:
        return True
    generic_patterns = (
        r"互补的信息",
        r"补充并完善",
        r"补充相关信息",
        r"完善相关信息",
        r"辅助信息",
        r"相关信息",
        r"相关数据",
        r"更多信息",
        r"其他信息",
        r"其它信息",
        r"complementary information",
        r"supplementary information",
        r"additional information",
        r"related information",
        r"auxiliary information",
    )
    return any(re.search(pattern, normalized) for pattern in generic_patterns)


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


def _deduplicate_path_aliases(route_paths: List[dict]) -> List[dict]:
    """Ensure unique aliases by appending -2, -3 when duplicates."""
    seen: dict[str, int] = {}
    out: List[dict] = []
    for e in route_paths:
        entry = dict(e)
        base = entry.get("alias") or _path_to_alias(entry.get("path") or [])
        if base in seen:
            seen[base] += 1
            entry["alias"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
            entry["alias"] = base
        out.append(entry)
    return out


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

**步骤 5 - 结论**：综合以上做出判定。不确定时倾向于 can_handle=true。

**步骤 6 - 可贡献性（仅当 can_handle=false 时）**：只有当本智能体能提供**当前问题直接需要、且可明确说清楚的具体补充内容**时，才能设 can_contribute=true，并在 contribution 中写明具体补充什么；否则必须为 false。
补充约束：
- 若已有单一专家可端到端回答当前问题，则其它专家应倾向于 can_contribute=false。
- contribution 必须是可执行、可验证的具体内容，禁止输出“补充相关信息/互补信息/完善信息/辅助信息”这类空泛表述。
- 不要因为“也许以后有用”或“同属一个行业”就判定 can_contribute=true。

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
**只输出一个 JSON 对象**，不包含 Markdown。将步骤 1～6 的推理过程写入 reason 字段：
{{"can_handle": true 或 false, "can_contribute": true 或 false, "contribution": "可贡献的内容简述（仅当 can_contribute=true 时）", "confidence": 0.0 到 1.0, "reason": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：... 步骤6：... 结论：..."}}
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


ALLOWED_FAILURE_REASON_CODES = {
    "",
    "non_retryable_misrouted_task",
    "execution_error_no_data",
    "transient_network",
    "auth_or_permission",
    "invalid_request",
    "cross_source_join_unavailable",
    "missing_relation_in_context",
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
10) 输出必须是 JSON，不要 markdown。
11) status 只能是 "complete" 或 "fail"，严禁输出 "partial"/"unknown"/其它值。

输入：
- original_query: {original_query}
- task_id: {task_id}
- task_description: {task_description}
- assigned_agent: {assigned_agent}
- agent_answer_raw: {agent_answer_raw}
- plan_context: {plan_context}
- prior_task_results: {prior_task_results}

输出 JSON:
{{
  "status": "complete" 或 "fail",
  "confidence": 0.0 到 1.0,
  "coverage_scope": "full 或 partial 或 unknown",
  "coverage_score": 0.0 到 1.0,
  "consistency_score": 0.0 到 1.0,
  "merge_readiness_score": 0.0 到 1.0,
  "evidence_quality_score": 0.0 到 1.0,
  "failure_reason_code": "简短代码，若complete可为空",
  "failure_explanation": "失败原因说明，若complete可为空",
  "missing_requirements": ["缺失点A", "缺失点B"],
  "suggested_retry_action": "retry_same_plan 或 replan_standard 或 replan_with_decomposition 或 abort"
}}

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

错误示例（禁止）：
{{"status":"partial", ...}}
"""

# Fixed description when no agent is relevant (agent=NONE)
NONE_TASK_DESCRIPTION = "No available agent can do this task. "

# Agent selection evaluation prompt (batch_llm mode)
AGENT_SELECTION_EVALUATION_PROMPT = """你是一个智能体选择专家。给定用户问题和一组候选智能体，请评估每个智能体能否处理该问题，并给出 0-1 的可信度（confidence）。

用户问题：
{query}

候选智能体：
{agents}

请严格输出 JSON 数组，每个元素格式为：{{"agent": "智能体名称", "can_handle": true/false, "confidence": 0.0-1.0, "reason": "简短理由"}}
注意：agent 必须与上述智能体列表中的 name 完全一致。仅输出 JSON，不要其他内容。"""

# 无可用 agent 且未配置 expert agent 时的提示（HAS_EXPERTAGENT=false），展示给用户
NO_SIDECAR_FALLBACK_DESCRIPTION = "暂时没有找到可以处理此问题的智能体，请稍后再试或换个方式描述您的问题。"

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
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.semantic_group_id = semantic_group_id

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

    def generate_collection_name(self, dd_name: str) -> str:
        """
        Format: namespace_name
        Rule: Replace '-' with '_'
        Returns:
        str: The generated collection_name
        """

        collection_name = f"{self.dd_namespace}_{dd_name}"

        # Replace '-' in namespace with '_'
        collection_name = collection_name.replace('-', '_')
        
        return collection_name


    def format_llm_ouput(self, answer) -> dict:
        data_dict = None
    
        try:
            data_dict = json.loads(answer.content)
        except json.JSONDecodeError as e:

            cleaned_content = answer.content.strip()

            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]
            elif cleaned_content.startswith('```'):
                cleaned_content = cleaned_content[3:]
            
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]
            
            cleaned_content = cleaned_content.strip()
            
            try:
                data_dict = json.loads(cleaned_content)
            except json.JSONDecodeError as e2:
                logger.error(f" === format_llm_ouput, Parsing failed after cleanup.: {e2}")
                try:
                    import ast
                    data_dict = ast.literal_eval(cleaned_content)
                except (ValueError, SyntaxError) as e3:
                    logger.error(f" === format_llm_ouput, ast parsing fail: {e3}")
                    try:
                        cleaned_content = cleaned_content.replace("'", '"')
                        data_dict = json.loads(cleaned_content)
                    except json.JSONDecodeError as e4:
                        logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")
                except Exception as e5:
                    logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        return data_dict

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

        json_prompt_instructions_zh: dict = {
            "thought_process": "1. 识别实体：'北京天气'（气象领地）和'穿衣建议'（生活方式领地）。2. 领地映射：'气象'归属于天气查询员，'穿衣'归属于时尚顾问。3. 涉及两个不同领域且有先后依赖，拆分为两个任务。注意：description 忠实转述用户原话，不添加额外条件。",
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
            "thought_process": "1. Domain Extraction: 'Beijing weather' and 'clothing advice'. 2. Sovereignty Mapping: 'Weather-Checker' owns meteorological data; 'Fashion-Consultant' owns lifestyle styling. 3. Two different domains with sequential dependency, split into two tasks. Note: description faithfully relays user's words without adding extra conditions.",
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
            "thought_process": "1. Entity Extraction: 'Starlink project' (Aerospace/Telecommunications). 2. Territory Check: No available agents cover aerospace or satellite tech domains. 3. Conclusion: Subject is outside all known agent sovereignties.",
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

        chain = chat_prompt | self.llm

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

        answer = None

        with langfuse.start_as_current_span(
            name="biz-orchestrator-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            
            if self.enable_history == "enable":
                history = await self.get_history()
                planner_prompt_chars += len(str(history or ""))
            logger.info(
                "[RetryAware][PlannerInput] query_chars=%d replan_context_chars=%d group_memory_chars=%d replan_marker_count=%d planner_prompt_chars=%d",
                len(str(query or "")),
                len(str(information or "")),
                len(str(group_memory or "")),
                replan_marker_count,
                planner_prompt_chars,
            )
            if self.enable_history == "enable":
                answer = await chain.ainvoke(
                    {"query": query, "history": history, "agents": system_prompt_agents, "information": information, "group_memory": group_memory},
                    config={"callbacks": [langfuse_handler]}
                )
            else:
                answer = await chain.ainvoke(
                    {"query": query, "agents": system_prompt_agents, "information": information, "group_memory": group_memory},
                    config={"callbacks": [langfuse_handler]}
                )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === PlannerAgent.make_plan , llm result = {answer.content}")

        data_dict = self.format_llm_ouput(answer)
        if data_dict is None or not isinstance(data_dict, dict):
            logger.error("PlannerAgent.make_plan: LLM output could not be parsed as JSON")
            raise ValueError("LLM plan output could not be parsed; please retry or rephrase.")
        if "tasks" not in data_dict or not isinstance(data_dict.get("tasks"), list):
            logger.error("PlannerAgent.make_plan: parsed output missing valid 'tasks' list")
            raise ValueError("LLM plan output missing valid 'tasks' field; please retry or rephrase.")

        tasks = TaskList(**data_dict)

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
        agent_card: AgentCard = None
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


    # get all or one resource (agent card) with resource name, such as list or expert_agent 
    async def find_resource(self, session: ClientSession, resource) -> ReadResourceResult:
        """Reads a resource from the connected MCP server.

        Args:
            session: The active ClientSession.
            resource: The URI of the resource to read (e.g., 'resource://agent_cards/list').

        Returns:
            The result of the resource read operation.
        """
        logger.info(f'Reading resource: {resource}')
        return await session.read_resource(resource)

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
                msg = HumanMessage(content=prompt)
                _md = getattr(self, "metadata", {}) or {}
                trace_id = _md.get("trace_id", "")
                user_id = _md.get("user_id", "")
                run_id = _md.get("run_id", "")
                with langfuse.start_as_current_span(
                    name="group-batch-agent-eval",
                    trace_context={"trace_id": trace_id} if trace_id else {},
                ) as span:
                    span.update_trace(
                        user_id=user_id,
                        session_id=run_id,
                        input={"query": query, "batch_size": len(batch_cards)},
                    )
                    answer = await self.llm.ainvoke([msg], config={"callbacks": [langfuse_handler]})
                    span.update_trace(output={"selected_count_hint": len(batch_cards)})
                content = answer.content if hasattr(answer, "content") else str(answer)
                content = content.strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                data = json.loads(content)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                return []
            except Exception as e:
                logger.warning(f"batch_llm_evaluate parse error: {e}, using full batch as fallback")
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

    async def _list_agent_cards_semantic_group(self, query) -> list[AgentCard]:
        """SemanticGroup mode: candidate pool = own Expert Agent + global utility agents.
        Tree-internal agents (-sg-/-dd-) are filtered out to prevent cross-tree routing.
        Fast path: when no utility agents exist, skip LLM evaluation entirely."""
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

        utility_cards = self._filter_tree_internal_agents(all_cards)

        if not utility_cards:
            logger.info("SemanticGroup mode: no utility agents found, fast path with own expert only")
            return [own_expert]

        candidates = [own_expert] + utility_cards
        logger.info("SemanticGroup mode: %d candidates (1 own expert + %d utility)", len(candidates), len(utility_cards))
        return candidates

    # get all AgentCards using find_resource func
    async def list_agent_cards(self, query) -> list[AgentCard]:
        """Reads agent cards from registry.
        - SemanticGroup mode: scoped pool (own expert + utility agents, no cross-tree)
        - SemanticDomain mode: controlled by AGENT_SELECTION_MODE (batch_llm / vector)
        """
        if self.semantic_group_id:
            return await self._list_agent_cards_semantic_group(query)

        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("CollectionName", "biz_expert_agent_cards")
        mode = os.getenv("AGENT_SELECTION_MODE", "batch_llm").strip().lower()

        try:
            if mode == "vector":
                return await self._list_agent_cards_vector(query, agent_registry_client, collection_name)
            return await self._list_agent_cards_batch_llm(query, agent_registry_client, collection_name)
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

    @classmethod
    def strip_progress_lines(cls, text: str) -> str:
        if not text:
            return ""
        lines = [line for line in text.splitlines() if not cls.is_progress_frame(line)]
        return "\n".join(lines).strip()

    def current_agent_label(self) -> str:
        return (self.agent_id or self.semantic_group_id or self.agent_name or "sg_orchestrator").strip()

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 320) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit - 3] + "..."

    def summarize_task_plan(self, task_list: Optional[TaskList]) -> str:
        if not task_list or not getattr(task_list, "tasks", None):
            return "no tasks"
        items: List[str] = []
        for task in task_list.tasks[:5]:
            items.append(f"{task.id}:{self._truncate_progress_message(task.description, 80)}")
        if len(task_list.tasks) > 5:
            items.append(f"... total={len(task_list.tasks)}")
        return " | ".join(items)

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
        # find agentcard using agent name
        agent_card = None

        for agentcard in self.agent_cards:
            if agentcard.name == agent_name:
                agent_card = agentcard

        return agent_card


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
            # SemanticGroup orchestrator 始终让下游 agent 返回原始知识，由自己做 LLM 总结
            'answer_model': 'original',
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
        logger.info(f">>>>>> [answer_model=original] OrchestratorAgent(SemanticGroup).a2a_stream() 设置 answer_model=original 给 agent={agent_name} <<<<<<")

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
        async with httpx.AsyncClient() as httpx_client:
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
            # SemanticGroup orchestrator 始终让下游 agent 返回原始知识，由自己做 LLM 总结
            'answer_model': 'original',
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
        logger.info(f">>>>>> [answer_model=original] OrchestratorAgent(SemanticGroup).a2a_non_stream() 设置 answer_model=original 给 agent={agent_name} <<<<<<")

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
        async with httpx.AsyncClient() as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            try:
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                agent_knowledge = []
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result != "" and not self.is_progress_frame(result):
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
                return " ".join(agent_knowledge)

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

    async def get_last_step_status(self, step_result) -> str:
        last_step_last_status = ""

        step_status_llm_check_success = "reason:The current answer addresses the question very well."

        if step_status_llm_check_success in str(step_result or ""):
            last_step_last_status = "complete"
        else:
            last_step_last_status = "fail"
        
        return last_step_last_status

    def _format_task_knowledge(self, task_id: int, description: str, agent: str, result: str) -> str:
        """将单条任务结果格式化为大模型易读的块，便于总结时区分任务与结果。"""
        agent_label = (agent or "").strip() or "（未分配）"
        return f"【任务 {task_id}】\n{description}\n\n【执行 Agent】\n{agent_label}\n\n【结果】\n{(result or '').strip()}"

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
                task_status.marker_present = NON_RETRYABLE_MARKER in raw_answer
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

    def _extract_join_keys_from_text(self, text: str) -> Dict[str, List[str]]:
        """Best-effort extraction of candidate join keys from text.

        Merge multiple strategies to improve robustness:
        1) structured JSON extraction
        2) regex key:value fallback
        3) markdown table column extraction (e.g. 商品ID | 1)
        """
        if not text:
            return {}
        merged: Dict[str, set[str]] = {}

        def merge_map(src: Dict[str, List[str]]) -> None:
            for k, vals in (src or {}).items():
                key = str(k or "").strip()
                if not key:
                    continue
                for v in list(vals or []):
                    sval = str(v or "").strip()
                    if sval:
                        merged.setdefault(key, set()).add(sval)

        merge_map(self._extract_join_keys_structured(text))
        merge_map(self._extract_join_keys_regex_fallback(text))
        merge_map(self._extract_join_keys_markdown_table(text))

        return {
            k: sorted(vs)[:MAX_JOIN_KEY_VALUES_PER_KEY]
            for k, vs in merged.items()
        }

    def _is_allowed_join_key(self, key: str) -> bool:
        key_low = (key or "").strip().lower()
        if not key_low:
            return False
        if JOIN_KEY_ALLOWLIST:
            return key in JOIN_KEY_ALLOWLIST or key_low in [k.lower() for k in JOIN_KEY_ALLOWLIST]
        return key_low == "id" or key_low.endswith("_id") or key_low.endswith("id")

    def _extract_join_keys_structured(self, text: str) -> Dict[str, List[str]]:
        """Extract join keys from JSON payloads (object/array), if parseable."""
        raw = (text or "").strip()
        if not raw:
            return {}
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif raw.startswith("```") and "```" in raw[3:]:
            raw = raw.split("```", 2)[1].strip()
        try:
            data = json.loads(raw)
        except Exception:
            return {}

        key_map: Dict[str, set[str]] = {}

        def walk(node: Any):
            if isinstance(node, dict):
                for k, v in node.items():
                    if self._is_allowed_join_key(str(k)) and isinstance(v, (int, str)):
                        sval = str(v).strip()
                        if sval.isdigit():
                            key_map.setdefault(str(k), set()).add(sval)
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return {
            k: sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY]
            for k, vals in key_map.items()
        }

    def _extract_join_keys_regex_fallback(self, text: str) -> Dict[str, List[str]]:
        """Fallback extraction for non-JSON free text."""
        # Capture key:value pairs like user_id: 1 / orderId=2 / "id": 3
        pattern = re.compile(
            r'["\']?([A-Za-z_][A-Za-z0-9_]{0,63})["\']?\s*[:=]\s*["\']?(\d{1,18})["\']?',
            flags=re.IGNORECASE,
        )
        key_map: Dict[str, set[str]] = {}
        for m in pattern.finditer(text):
            key = (m.group(1) or "").strip()
            value = (m.group(2) or "").strip()
            if not key or not value:
                continue
            if self._is_allowed_join_key(key):
                key_map.setdefault(key, set()).add(value)
        out: Dict[str, List[str]] = {}
        for k, vals in key_map.items():
            # Keep bounded payload to avoid prompt explosion.
            out[k] = sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY]
        return out

    def _extract_join_keys_markdown_table(self, text: str) -> Dict[str, List[str]]:
        """Extract join-key-like numeric values from markdown tables.

        Supports headers such as `id`, `product_id`, `商品ID`, `订单ID` etc.
        """
        if not text:
            return {}

        lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
        key_map: Dict[str, set[str]] = {}

        def parse_row(row: str) -> List[str]:
            raw = row.strip().strip("|")
            return [c.strip() for c in raw.split("|")]

        def is_separator_row(row: str) -> bool:
            cells = parse_row(row)
            if not cells:
                return False
            return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) is not None for c in cells)

        i = 0
        while i < len(lines) - 1:
            header_line = lines[i]
            sep_line = lines[i + 1] if i + 1 < len(lines) else ""
            if "|" not in header_line or "|" not in sep_line or not is_separator_row(sep_line):
                i += 1
                continue

            headers = parse_row(header_line)
            if not headers:
                i += 1
                continue
            lowered_headers = [h.lower() for h in headers]
            candidate_idx = [idx for idx, h in enumerate(lowered_headers) if self._is_allowed_join_key(h)]
            if not candidate_idx:
                i += 1
                continue

            j = i + 2
            while j < len(lines):
                row = lines[j]
                if "|" not in row:
                    break
                cells = parse_row(row)
                if len(cells) < len(headers):
                    break
                for idx in candidate_idx:
                    if idx >= len(cells):
                        continue
                    cell_text = str(cells[idx] or "").strip()
                    if not cell_text:
                        continue
                    for m in re.finditer(r"\b\d{1,18}\b", cell_text):
                        key_map.setdefault(headers[idx], set()).add(m.group(0))
                j += 1
            i = j

        return {
            k: sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY]
            for k, vals in key_map.items()
        }

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

    def _strip_json_fences(self, raw: str) -> str:
        text = (raw or "").strip()
        for p, s in [("```json", "```"), ("```", "```")]:
            if text.startswith(p):
                text = text[len(p):]
            if text.endswith(s):
                text = text[:-len(s)]
        return text.strip()

    def _get_non_stream_llm(self) -> Any:
        manager = ModelManager()
        _extra = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        return manager.get_llm(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            stream=False,
            extra_body=_extra,
        )

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
        llm = self._get_non_stream_llm()
        prompt = TASK_OUTCOME_EVAL_PROMPT.format(
            original_query=original_query,
            task_id=task.id,
            task_description=task.description,
            assigned_agent=task.agent,
            agent_answer_raw=(agent_answer_raw or "")[:6000],
            plan_context=json.dumps(plan_context, ensure_ascii=False),
            prior_task_results=json.dumps(prior_task_results, ensure_ascii=False),
        )
        _md = getattr(self, "metadata", {}) or {}
        trace_id = _md.get("trace_id", "")
        user_id = _md.get("user_id", "")
        run_id = _md.get("run_id", "")
        try:
            with langfuse.start_as_current_span(
                name="group-task-outcome-eval-llm",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"task_id": task.id, "task_description": task.description, "agent": task.agent},
                )
                response = await llm.ainvoke(
                    [HumanMessage(content=prompt)],
                    config={"callbacks": [langfuse_handler]},
                )
                raw = self._strip_json_fences(response.content if hasattr(response, "content") else str(response))
                data = json.loads(raw)
                eval_result = TaskOutcomeEval(**data)
                eval_result = self._normalize_outcome_eval_result(task=task, agent_answer_raw=agent_answer_raw, eval_result=eval_result)
                span.update_trace(
                    output={
                        "task_id": task.id,
                        "status": eval_result.status,
                        "confidence": eval_result.confidence,
                        "failure_reason_code": eval_result.failure_reason_code,
                    }
                )
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

    def _build_prior_task_context(
        self,
        current_task_id: int,
        metadata_prior_task_results: Optional[List[dict]] = None,
        *,
        include_local_completed_tasks: bool = True,
    ) -> tuple[str, str, Dict[str, List[str]]]:
        """Build prior knowledge text for prompts (not appended to user query).

        - include_local_completed_tasks=True: merge inbound metadata prior (P0) with local
          completed tasks except ``current_task_id`` (for per-task prompt injection).
        - include_local_completed_tasks=False: only normalized metadata P0 (e.g. inspect / tooling;
          execution-time injection uses merged list + `_prior_merged_items_to_document` per A2A call).
        """
        md = self.metadata if isinstance(self.metadata, dict) else {}
        if metadata_prior_task_results is None:
            metadata_prior_task_results = md.get("prior_task_results")
        p0 = self._normalize_prior_task_results(metadata_prior_task_results or [])
        p1 = (
            self._collect_local_prior_task_results(current_task_id)
            if include_local_completed_tasks
            else []
        )
        merged = self._merge_prior_task_results(p0, p1)
        if not merged:
            return "", "none", {}
        if include_local_completed_tasks:
            source = "p0" if p0 and not p1 else ("p1" if p1 and not p0 else "p0+p1")
        else:
            source = "p0" if p0 else "none"
        text, normalized_keys = self._prior_merged_items_to_document(merged)
        return text, source, normalized_keys

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

    def _classify_task_failure_reason(self, task: TaskStatus) -> str:
        """Classify failure reason into coarse-grained reason codes."""
        text = f"{task.description}\n{task.answer}".lower()
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
        if reason_code in ("cross_source_join_unavailable", "missing_relation_in_context"):
            return "replan_with_decomposition"
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
        )
        for code in priority:
            if code in reason_codes:
                logger.info("[RetryAware] Selected prioritized reason_code=%s from=%s", code, reason_codes)
                return code
        return reason_codes[0] if reason_codes else "unknown_failure"

    def _build_replan_guidance(self, reason_code: str) -> str:
        """Build strategy guidance text for replanning prompt."""
        if reason_code in ("cross_source_join_unavailable", "missing_relation_in_context"):
            return (
                "重试策略要求（通用）：\n"
                "1) 不要在单一数据源中执行跨源 JOIN。\n"
                "2) 先在主数据源完成聚合并产出 join_key 列表（如 *_id）。\n"
                "3) 再在其它数据源按 join_key 列表查询补充属性。\n"
                "4) 最终由编排层按 join_key 进行结果合并，并标注缺失 key。\n"
                "5) 禁止复用上轮失败的 task-agent 方案，除非给出可验证修复。"
            )
        if reason_code == "transient_network":
            return "重试策略要求：优先保持原任务分解，仅微调以降低外部调用失败概率；禁止无关改动。"
        return "重试策略要求：优先修复失败任务，逐条覆盖 missing_requirements，避免无关任务改动，并说明与上轮差异。"

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

                # When planner returned agent=NONE (no relevant agent), use fixed description and skip A2A
                if (task.agent or "").strip().upper() == "NONE":
                    none_description = NONE_TASK_DESCRIPTION
                    logger.info("Task %s: agent=NONE (no relevant agent)", task.id)
                    self._update_task_status(task.id, "complete", none_description)
                    current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, "", none_description))
                    task_desc_preview = self._truncate_progress_message(task.description or "", 220)
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

                agent_steps_knowledge = []

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
                            if self.debug == 1:
                                agent_knowledge_step = f"{agent_step_knowledge} \n"
                                think.append(agent_knowledge_step)
                            agent_steps_knowledge.append(agent_step_knowledge)

                        agent_steps_knowledge_str = "\n".join(agent_steps_knowledge)

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
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_steps_knowledge_str))
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
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

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
                        
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_result or ""))
                        
                    except Exception as e:
                        logger.error(f"Error during non-streaming execution of task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

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
                    guidance = self._build_replan_guidance(reason_code)
                    replan_context = self._build_replan_context(
                        original_query=base_query,
                        current_tasks=current_tasks,
                        retry_count=retry_count,
                        reason_code=reason_code,
                        retry_action=retry_action,
                        failure_analysis=failure_analysis,
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
        human_template = "background knowledge: {knowledge}。\n\nuser question:{query}"

        logger.info(f"============ biz orchestrator stream, answer user question, knowledge length: {len(knowledge)}, preview: {knowledge[:300]}...")

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

        # add memory
        await self.add_memory(query, final_answer)


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

    @staticmethod
    def is_progress_frame(text: str) -> bool:
        return OrchestratorAgent.is_progress_frame(text)

    @staticmethod
    def is_answer_frame(text: str) -> bool:
        return OrchestratorAgent.is_answer_frame(text)

    @classmethod
    def parse_answer_frame(cls, text: str) -> Optional[Dict[str, Any]]:
        return OrchestratorAgent.parse_answer_frame(text)

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

    def _strip_json_fences(self, raw: str) -> str:
        text = (raw or "").strip()
        for p, s in [("```json", "```"), ("```", "```")]:
            if text.startswith(p):
                text = text[len(p):]
            if text.endswith(s):
                text = text[:-len(s)]
        return text.strip()

    def _get_response_text_from_stream_chunk(self, chunk: Any) -> str:
        """Extract text from A2A streaming chunk (artifact-update)."""
        d = chunk.model_dump(mode="json", exclude_none=True) if hasattr(chunk, "model_dump") else (chunk if isinstance(chunk, dict) else {})
        res = d.get("result") or {}
        if res.get("kind") != "artifact-update":
            return ""
        artifact = res.get("artifact") or {}
        parts = artifact.get("parts") or []
        if not isinstance(parts, list):
            return ""
        texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict) and p.get("text") is not None]
        return "".join(texts)

    async def _persist_history_from_executor(
        self,
        metadata: Optional[Dict[str, Any]],
        query: str,
        final_answer: str,
        think: str = "",
    ) -> None:
        """Persist final history at executor layer when enabled."""
        if self.enable_history != "enable":
            return
        md = metadata or {}
        owner_agent_id = md.get("history_owner_agent_id")
        is_not_owner = bool(owner_agent_id) and owner_agent_id != self.agent_id
        if md.get("skip_history_write") or is_not_owner:
            skip_reason = "skip_history_write" if md.get("skip_history_write") else "not_owner"
            logger.info(
                "[HistoryFlow] executor-history-skip reason=%s skip_history_write=%s owner=%s self=%s run_id=%s",
                skip_reason,
                md.get("skip_history_write"),
                owner_agent_id,
                self.agent_id,
                md.get("run_id", ""),
            )
            return
        if not md.get("user_id") or not md.get("run_id"):
            logger.warning(
                "[History] Skip executor history persist due to missing user_id/run_id | agent_id=%s user_id=%s run_id=%s",
                self.agent_id,
                md.get("user_id", ""),
                md.get("run_id", ""),
            )
            return

        create_request = CreateHistoryRequest(
            user_id=md.get("user_id", ""),
            agent_id=self.agent_id,
            run_id=md.get("run_id", ""),
            messages=[
                HistoryMessage(role="user", content=query or ""),
                HistoryMessage(role="assistant", content=final_answer or "", think=think or None),
            ],
        )
        try:
            client = DataServicesClient(
                base_url=self.data_services_url,
                timeout=600,
                use_data_descriptor_header=False,
            )
            async with client.session_context() as ds_client:
                await ds_client.create_history(create_request)
            logger.info(
                "[History] Executor persisted final conversation | agent_id=%s run_id=%s answer_len=%d",
                self.agent_id,
                md.get("run_id", ""),
                len(final_answer or ""),
            )
        except Exception as e:
            logger.error("[History] Executor persist history failed: %s", e)

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """Handle a capability check request from the routing agent.

        In single-layer SG mode every SG is both root and leaf, so capability
        check only evaluates the current SG itself and returns a single-node path.
        """
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        request_metadata = context.metadata if isinstance(context.metadata, dict) else {}
        if request_metadata:
            # Keep executor metadata fresh for this request lifecycle.
            self.metadata = request_metadata
        md = request_metadata or (self.metadata if isinstance(self.metadata, dict) else {})

        agent_name = self.agent_card.name if self.agent_card else self.agent_id or "Unknown"
        logger.info(
            "[RoutePlan] ----- %s | capability_check start | query: %s -----",
            agent_name, (query[:80] + "..." if len(query) > 80 else query),
        )
        agent_description = self.agent_card.description if self.agent_card else ""
        agent_url = self.agent_card.url if self.agent_card else ""

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
            manager = ModelManager()
            _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
            llm = manager.get_llm(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=0.01,
                stream=False,
                extra_body=_extra_body,
            )
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
            trace_id = md.get("trace_id", "")
            user_id = md.get("user_id", "")
            run_id = md.get("run_id", "")
            with langfuse.start_as_current_span(
                name="group-capability-check-llm",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "agent_name": agent_name},
                )
                response = await llm.ainvoke(
                    [HumanMessage(content=prompt)],
                    config={"callbacks": [langfuse_handler]},
                )
                span.update_trace(output={"agent_name": agent_name})
            response_text = response.content.strip()
            for p, s in [("```json", "```"), ("```", "```")]:
                if response_text.startswith(p):
                    response_text = response_text[len(p):]
                if response_text.endswith(s):
                    response_text = response_text[:-len(s)]
            response_text = response_text.strip()
            result_data = json.loads(response_text)
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
            )

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
        response_json = check_response.model_dump_json()

        await updater.add_artifact(
            [TextPart(text=response_json)],
            name="capability-check-response",
        )
        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

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

        # ---- Capability Check: respond quickly if this is a broadcast routing probe ----
        if metadata and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            logger.info(f"[Capability] Received capability check request, query: {query[:100]}...")
            await self.handle_capability_check(context, event_queue, query)
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
            agent_card=self.agent_card
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
        steps = await agent.get_plan(query_for_plan)

        think = []

        if steps is None:
            logger.info(f"===== OrchestratorAgentExecutor, steps is empty.")
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
                task_list=steps,
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
                steps_str = tasklist_to_string(steps, participant_chain=participant_chain)
                think.append(steps_str)

            # call each agent to get the knowledge owned by each agent, then get some knowledges from agents
            task_name = f'{agent.agent_name}-result'
            task_knowledges = await agent.a2a_tasks(query_for_plan, steps, updater, task_name, think)

            _tk_preview = [str(tk)[:200] + "..." for tk in task_knowledges] if task_knowledges else []
            logger.info(f"===== OrchestratorAgentExecutor.task_knowledges count={len(task_knowledges) if task_knowledges else 0}, preview: {_tk_preview}")

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