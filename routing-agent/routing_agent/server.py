import json
import logging
import sys
import time
from pathlib import Path
import click
import httpx
import uvicorn
import os
import asyncio
import re
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Any, AsyncIterable, Awaitable, Callable, Dict, Literal, List, Optional, Tuple, Union
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
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import StructuredTool, tool
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .agentregistry_client import AgentRegistryClient
from .dataservices_client import DataServicesClient, CreateHistoryRequest, HistoryMessage, SearchHistoryRequest
from .tool_call_utils import invoke_llm_with_tool, extract_tool_call_result


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
    "routing_plan_ready": {"mode", "task_count"},
    "multi_root_plan_reason": {
        "task_count",
        "needs_split",
        "reasoning",
        "requirements",
        "tasks",
    },
    "root_selected": {"mode", "route_paths"},
    "route_plan_with_capability_check": {
        "mode",
        "strategy",
        "selected_root",
        "route_paths",
        "best_path",
        "task_count",
        "root_count",
        "task_agents",
        "tasks",
        "root_plans",
    },
    "root_forward_started": {"route_paths", "strategy", "strategy_human"},
    "multi_root_level_started": {"task_ids", "task_count"},
    "multi_root_task_finished": set(),
    "routing_final_answer_ready": {"mode", "answer_chars"},
}

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_ZH = """
# Role：专业任务规划师（业务领地导航专家）

## 核心使命
通过识别用户意图中的“核心本体”，将其分发至拥有该业务领地主权的专家智能体。

## 任务执行逻辑（Chain-of-Thought）
在构造 JSON 响应时，必须在内部完成以下“领地判定”逻辑：
1. **本体提取（Entity Extraction）**：从用户输入中剥离动作（如统计、查询、处理），锁定**核心业务名词**（即“业务实体”）。
2. **领地归属判定（Domain Ownership）**：
   - 将提取的“业务实体”与各智能体的 `description` 进行语义映射。
   - **判定准则**：智能体的描述决定了其**业务边界**。只要该实体属于该智能体的业务范畴，该智能体即拥有该问题的“第一处理权”。
3. **能力泛化推断（Capability Generalization）**：
   - **屏蔽显式限制**：忽略智能体技能列表中是否缺失特定动词。只要业务实体对齐，应默认该智能体具备处理该实体相关一切需求（包括但不限于查询、分析、操作、管理）的隐含能力。
   - **主权优先**：当智能体身份与业务实体高度一致时，即使其声称不负责某细分操作，也应视其为该业务的唯一入口进行分发。

## 智能体选择流程
1. **实体主权匹配**：优先匹配用户问题的“主语”与智能体的“业务定义”。
2. **拒绝盲目过滤**：不得因技能（Skills）描述不全而拒绝分发。技能仅作为功能参考，不作为准入限制。
3. **严防“跨领地”分发**：
   - 只有当用户问题的实体与智能体的业务领地**完全无关**（属于不同维度的业务系统）时，才允许返回空字符串 `""`。
   - 在同一个业务体系内，必须选择最相关的领地专家。
4. **上下文一致性**：保持多轮对话中业务实体的逻辑承接。
5. **名称精确匹配**：agent 字段必须与列表中 **name** 完全一致。

---
**可用的智能体（领域专家）：**
{agents}

---
## 输出要求
1. **格式控制**：**只允许输出一个合法的 JSON 字符串**，不包含 Markdown。
2. **字段定义**：
   - `thought_process`: 记录 1. 识别的核心业务实体；2. 该实体如何映射到智能体的领地；3. 基于主权原则的隐含能力推断过程。
   - `original_query`: 用户原始输入。
   - `agent`: 匹配的智能体 `name`，若无任何领地相关专家则填 `""`。

## 示例参考
{instructions}
"""

PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# Role：专业任务规划师（业务领地导航专家）

## 核心使命
通过识别用户意图中的“核心本体”，将其分发至拥有该业务领地主权的专家智能体。

## 任务执行逻辑（Chain-of-Thought）
在构造 JSON 响应时，必须在内部完成以下“领地判定”逻辑：
1. **本体提取（Entity Extraction）**：从用户输入中剥离动作（如统计、查询、处理），锁定**核心业务名词**（即“业务实体”）。
2. **领地归属判定（Domain Ownership）**：
   - 将提取的“业务实体”与各智能体的 `description` 进行语义映射。
   - **判定准则**：智能体的描述决定了其**业务边界**。只要该实体属于该智能体的业务范畴，该智能体即拥有该问题的“第一处理权”。
3. **能力泛化推断（Capability Generalization）**：
   - **屏蔽显式限制**：忽略智能体技能列表中是否缺失特定动词。只要业务实体对齐，应默认该智能体具备处理该实体相关一切需求（包括但不限于查询、分析、操作、管理）的隐含能力。
   - **主权优先**：当智能体身份与业务实体高度一致时，即使其声称不负责某细分操作，也应视其为该业务的唯一入口进行分发。

## 智能体选择流程
1. **实体主权匹配**：优先匹配用户问题的“主语”与智能体的“业务定义”。
2. **拒绝盲目过滤**：不得因技能（Skills）描述不全而拒绝分发。技能仅作为功能参考，不作为准入限制。
3. **严防“跨领地”分发**：
   - 只有当用户问题的实体与智能体的业务领地**完全无关**（属于不同维度的业务系统）时，才允许返回空字符串 `""`。
   - 在同一个业务体系内，必须选择最相关的领地专家。
4. **上下文一致性**：保持多轮对话中业务实体的逻辑承接。
5. **名称精确匹配**：agent 字段必须与列表中 **name** 完全一致。

## 对话历史使用规则（必须遵守）
1. **仅用于理解指代**：history 仅用于解析当前追问里的“它/那个/继续”等指代关系。
2. **禁止无关条件搬运**：不要把历史中与当前问题无关的筛选条件直接带入本轮判定。
3. **禁止补充字段细节**：如果用户本轮没有要求具体字段名（如 `product_id`、`sku_id`），不要仅凭历史自行补充到任务语义中。
4. **仅在对比追问时继承必要上下文**：当用户明确是“换成XX/那XX呢”的对比追问时，才继承其余必要维度，且必须保持最小继承。

---
**对话历史（按时间顺序）：**
{history}

**可用的智能体（领域专家）：**
{agents}

---
## 输出要求
1. **格式控制**：**只允许输出一个合法的 JSON 字符串**，不包含 Markdown。
2. **字段定义**：
   - `thought_process`: 记录 1. 识别的核心业务实体；2. 该实体如何映射到智能体的领地；3. 基于主权原则的隐含能力推断过程。
   - `original_query`: 用户原始输入。
   - `agent`: 匹配的智能体 `name`，若无任何领地相关专家则填 `""`。

## 示例参考
{instructions}
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


def extract_history_turns(search_items: Any) -> list[dict]:
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
    return turns


def build_propagated_history(turns: Any, *, source: str = "local_history") -> dict:
    normalized = normalize_history_turns(turns)
    return {
        "turns": normalized,
        "turn_count": len(normalized),
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

class PlannerStep(BaseModel):
    """Output schema for the Planner Agent."""

    original_query: Optional[str] = Field(
        description='The original user query for context.'
    )

    agent: str = Field(
        description='agent name of the step to be executed.'
    )


# ==================== Capability Check Protocol (Broadcast Routing) ====================
# Message type flag used in A2A metadata to indicate a capability check request
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"
ROUTING_AGENT_POOL_KEY = "routing_agent_pool"
ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY = "routing_skip_broadcast_eligible"
ROUTING_SELECTED_ROOT_KEY = "routing_selected_root"
SG_EXECUTION_HINT_KEY = "sg_execution_hint"


class CapabilityCheckResponse(BaseModel):
    """Standard response model for capability check A2A requests.

    route_path: best path (backward compat).
    route_paths: top-K paths [{"path": [...], "confidence": 0.9}, ...] for fallback retry.
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
    route_path: list[str] = Field(
        default_factory=list,
        description="Best path (first in route_paths)."
    )
    route_paths: list[dict] = Field(
        default_factory=list,
        description="Top-K paths for fallback retry."
    )
    can_contribute: bool = Field(
        default=False,
        description="Whether this agent can partially contribute even if cannot fully handle."
    )
    contribution: str = Field(
        default="",
        description="Brief description of contribution scope when can_contribute=true."
    )
    execution_strategy: str = Field(
        default="single",
        description="Execution strategy for the selected SG. Single-layer SG only returns 'single'."
    )
    execution_hint: dict = Field(
        default_factory=dict,
        description="Opaque SG-issued execution evidence; Routing only transports it."
    )
    latency_ms: int = Field(
        default=0,
        description="Capability check end-to-end latency in milliseconds, measured by the responding agent."
        # 与各 agent 的 CapabilityCheckResponse 对齐：agent 上报自身耗时，routing 用于观测广播链路耗时。
    )

# ==================== Multi-Root Task Plan Protocol ====================

MULTI_ROOT_CONFIDENCE_THRESHOLD = float(os.getenv("MULTI_ROOT_CONFIDENCE_THRESHOLD", "0.6"))
ROOT_SINGLE_FAST_PATH_MIN_CONFIDENCE = float(os.getenv("ROOT_SINGLE_FAST_PATH_MIN_CONFIDENCE", "0.78"))
ROOT_SINGLE_FAST_PATH_GAP = float(os.getenv("ROOT_SINGLE_FAST_PATH_GAP", "0.15"))


def _is_non_actionable_contribution_text(text: str) -> bool:
    """Detect vague contribution text that should not trigger multi-root."""
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
        r"无法访问",
        r"无法查询",
        r"无任何业务数据库",
        r"仅具备 weather",
        r"cannot access",
        r"no business database",
    )
    return any(re.search(pattern, normalized) for pattern in generic_patterns)


def _agent_card_to_pool_dict(card: AgentCard) -> dict:
    dump = getattr(card, "model_dump", None) or getattr(card, "dict", None)
    if dump:
        return dump()
    return {"name": getattr(card, "name", ""), "url": getattr(card, "url", "")}


def _build_routing_agent_pool_from_capable(
    capable_agents: list[tuple[AgentCard, "CapabilityCheckResponse"]],
) -> list[dict]:
    pool: list[dict] = []
    for card, resp in capable_agents:
        name = getattr(card, "name", "") or getattr(resp, "agent_name", "")
        if not name:
            continue
        role = "handle" if getattr(resp, "can_handle", False) else "contribute"
        contribution = str(getattr(resp, "contribution", "") or "")
        reason = str(getattr(resp, "reason", "") or "")
        if len(contribution) > 300:
            contribution = contribution[:300] + "..."
        if len(reason) > 200:
            reason = reason[:200] + "..."
        pool.append(
            {
                "agent": _agent_card_to_pool_dict(card),
                "agent_name": name,
                "role": role,
                "confidence": float(getattr(resp, "confidence", 0.0) or 0.0),
                "contribution": contribution,
                "reason": reason,
            }
        )
    return pool


def _nonredundant_root_plan_routes_summary(root_plans: list) -> str:
    """Route lines for DAC progress only when they add info beyond repeating agent names.

    For single-layer SGs, best_path often equals root; omitting avoids
    ``agents=[A,B], root_plans=A:single:[A]; B:single:[B]`` style duplication.
    """
    if not root_plans:
        return ""
    parts: list[str] = []
    for rp in root_plans:
        if not isinstance(rp, dict):
            continue
        root = str(rp.get("root") or "").strip()
        best = str(rp.get("best_path") or "").strip()
        strategy = str(rp.get("strategy") or "single").strip().lower()
        if not root:
            continue
        if strategy != "single":
            parts.append(f"{root} ({strategy}) → {best or '—'}")
            continue
        if not best or best == root:
            continue
        norm = re.sub(r"\s*->\s*", " -> ", best)
        tokens = [t.strip() for t in norm.split(" -> ") if t.strip()]
        if len(tokens) == 1 and tokens[0] == root:
            continue
        parts.append(f"{root} → {best}")
    return "; ".join(parts)


MULTI_ROOT_TASK_PLAN_PROMPT = """# Role：智能任务分析与规划师

多个领域专家都表示可以处理用户的问题，请你**逐步分析**该问题是否真的需要多个专家协作，还是交给一个最合适的专家即可。

## 历史对话

{history}

## 历史使用边界（必须遵守）

1. 历史仅用于理解当前问题中的指代与上下文承接，不可替代当前用户问题本身。
2. 不得将历史中无关的筛选条件、时间范围、字段名搬运到本轮任务描述中。
3. 若用户未明确要求字段级细节，不要在任务中主动引入具体物理字段（如 `product_id`、`sku_id`）。
4. 仅当用户是对比性追问（如“那9月呢/换成XX呢”）时，才继承必要上下文，且需保持最小继承。

## 思考步骤（Chain-of-Thought，写入 reasoning 字段）

**步骤 1 - 提取核心意图**：用户问题中涉及哪些**数据实体**和**业务动作**？逐一列出，并产出 requirements（需求单元）。

**步骤 2 - 领域归属判定**：将步骤 1 提取的每个数据实体映射到下面的领域专家。判断：这些实体是否分属**不同专家的独占领域**？还是存在一个专家能完整覆盖所有实体？
注意：能力判定以领域边界为主，skills 只作参考，不作为准入限制。不要因为 skills 文案缺失某个动词就排除本领域专家。

**步骤 3 - 拆解必要性判定（关键）**：
- 如果所有数据实体都属于**同一个专家的领域**，则**不需要拆解**，直接交给该专家。
- 如果数据实体明确分属**两个或以上专家的独占领域**，且用户确实需要来自不同领域的数据，才**需要拆解**。
- **不要为了“更全面”而强行拆解**——如果一个专家能完整回答，拆解反而会降低回答质量。
- 当领域有重叠时，优先选择**置信度更高**或**描述更匹配**的单个专家。

**步骤 4 - 任务规划**：
- 若判定**不需要拆解**：tasks 中只放 1 条任务，description 使用用户原始问题，agent 为最佳专家。
- 若判定**需要拆解**：将问题按领域拆为多个子任务，每个子任务只涉及一个专家擅长的内容。description 忠实反映用户原始意图中属于该领域的部分，不捏造用户未提及的条件。
- 每个任务都必须写明 why_agent（为什么是这个专家）和 covers（覆盖了哪些 requirements）。

**步骤 5 - 依赖关系**：子任务之间是否有先后依赖？后续任务需要前序任务的结果时，设置 depends_on。无依赖的子任务可以并行执行。

---
## 可用的领域专家

{agents}

---
## 输出格式

**只输出一个合法 JSON 对象**，不包含 Markdown：

{{
  "reasoning": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：...",
  "requirements": ["需求单元A", "需求单元B"],
  "needs_split": true 或 false,
  "tasks": [
    {{
      "id": 1,
      "description": "任务描述",
      "agent": "专家名称",
      "depends_on": [],
      "why_agent": "该专家承接本任务的理由",
      "covers": ["需求单元A"]
    }}
  ]
}}

注意：
- agent 字段必须与上面列表中的 name **完全一致**
- needs_split=false 时 tasks 中只有 1 条任务
- needs_split=true 时 tasks 中有 2 条或以上任务
- 采用最小必要拆分：能由单个专家完整处理时，不要过度拆分
- **JSON 字符串合法性**：`reasoning`、`description`、`why_agent` 等所有字符串值中，若需出现双引号则必须写为 `\\"`；当用户原话里含 JSON 或引号时，在字符串内请改写为单引号或中文引号「」，**禁止**在字符串里直接粘贴未转义的 `{{` `"` `}}` 片段，否则输出无法解析。
- 【禁止项】不要规划“最终汇总/跨任务整合/最终报告/最终回答”类任务（例如“整合任务1和任务2输出最终答案”）。
- 最终面向用户的汇总回答由 Orchestrator 聚合阶段统一完成，tasks 仅规划数据获取/计算/补充任务。

Few-shot（错误示例，禁止）：
- query: 查询每个用户订单数量和总消费金额，并显示用户详情
- bad_tasks:
  1) 查询用户详情（UserAgent）
  2) 统计订单金额（OrderAgent）
  3) 整合任务1和任务2并输出最终回答（OrderAgent）  <-- 禁止

Few-shot（正确示例）：
- query: 查询每个用户订单数量和总消费金额，并显示用户详情
- good_tasks:
  1) 查询用户详情（UserAgent）
  2) 统计订单数量与总消费金额（OrderAgent）
  （最终整合由 Orchestrator 聚合完成，不规划为任务）

## 用户问题

{query}
"""

MULTI_ROOT_AGGREGATE_PROMPT = """你是一个智能综合分析师。多个领域专家分别完成了各自的子任务，请综合他们的结果，为用户提供一个完整、连贯的最终答案。

## 用户原始问题

{query}

## 历史对话

{history}

## 各领域专家的回答

{results}

## 要求

1. 综合所有专家的回答，形成一个完整的答案
2. 如果不同专家的回答有关联，请建立联系并做对比/分析
3. 使用自然、流畅的语言，不要简单罗列
4. 如果某个专家未能提供有效回答，说明该部分信息暂不可用
5. 对上下文不确定、证据不足或口径冲突的信息，不要自行猜测补全，不要把推测当成事实输出
6. 首段 1-2 句直接回答用户核心问题；不要先写背景过程
7. 在不影响简洁的前提下，默认使用轻量结构化表达提升可读性，例如短标题、项目符号或简短表格；不要输出成没有层次的一大段纯文本
8. 当答案包含统计结果、对象属性、对比项或多条关键信息时，优先组织为“结论先行 + 关键依据/补充信息”这类结构；若信息很少，可仅保留“结论 + 1 个简短补充小节”
9. 不要机械使用“直接答案”“补充说明”这类模板化标题；若需要标题，优先使用更自然的标题，如“结论”“核心结论”“关键信息”“关键依据”，并允许根据内容自适应命名
10. 若用户未明确要求，不要主动展开“方法对比/补充视角/建议项”
11. 补充内容只保留与问题直接相关的 2-4 个要点，避免冗长，但也不要为了简短牺牲可读性
"""


class MultiRootTask(BaseModel):
    id: int = Field(description="Task ID")
    description: str = Field(description="Sub-task description")
    agent: str = Field(description="Agent name to handle this task")
    depends_on: List[int] = Field(default_factory=list, description="IDs of tasks this depends on")
    why_agent: str = Field(default="", description="Why this agent handles the task")
    covers: List[str] = Field(default_factory=list, description="Requirement units covered by this task")


class MultiRootTaskPlan(BaseModel):
    reasoning: str = Field(default="", description="Planning reasoning")
    requirements: List[str] = Field(default_factory=list, description="Requirement units extracted from query")
    needs_split: bool = Field(default=True, description="Whether the query truly needs multi-agent split")
    tasks: List[MultiRootTask] = Field(default_factory=list, description="List of sub-tasks")


class ResolvedTaskQuery(BaseModel):
    """Tool-call schema for routing_resolve_task_query_for_multi_root LLM output."""
    model_config = {"extra": "ignore"}
    resolved_query: str = Field(default="", description="The rewritten task description ready to be executed downstream")
    selected_keys: List[str] = Field(default_factory=list, description="Key info sources actually depended on (field/column/semantic labels)")
    applied: bool = Field(default=False, description="Whether the prior results were actually used to rewrite the task")
    reason: str = Field(default="", description="One-sentence reason why the rewrite was or was not applied")


class SplitJudgement(BaseModel):
    """Tool-call schema for split-necessity judge LLM output."""
    model_config = {"extra": "ignore"}
    needs_split: bool = Field(default=False, description="Whether the query truly needs multi-agent split")


class AgentRankToolResult(BaseModel):
    """Tool-call schema for single-root fallback best-agent ranking LLM output."""
    model_config = {"extra": "ignore"}
    best_agent: str = Field(default="", description="Name of the best agent to handle the query")
    confidence: float = Field(default=0.0, description="Confidence level from 0.0 to 1.0")
    reason: str = Field(default="", description="Brief reason for the selection")


MULTI_ROOT_PRIOR_RESULT_MAX_CHARS = int(os.getenv("MULTI_ROOT_PRIOR_RESULT_MAX_CHARS", "12000"))
MAX_JOIN_KEY_VALUES_PER_KEY = int(os.getenv("MAX_JOIN_KEY_VALUES_PER_KEY", "50"))
JOIN_KEY_ALLOWLIST = [k.strip() for k in os.getenv("JOIN_KEY_ALLOWLIST", "").split(",") if k.strip()]
MULTI_ROOT_RESOLVE_PRIOR_TASK_LIMIT = int(os.getenv("MULTI_CHILD_RESOLVE_PRIOR_TASK_LIMIT", "4"))
MULTI_ROOT_RESOLVE_ANSWER_CHARS = int(os.getenv("MULTI_CHILD_RESOLVE_ANSWER_CHARS", "1500"))
MULTI_ROOT_RESOLVE_KEY_LIMIT = int(os.getenv("MULTI_CHILD_RESOLVE_KEY_LIMIT", "4"))
MULTI_ROOT_RESOLVE_VALUES_LIMIT = int(os.getenv("MULTI_CHILD_RESOLVE_VALUES_LIMIT", "12"))


def _truncate_text_for_routing_prior(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    head = max(limit - 80, 0)
    return s[:head] + "\n…(prior output truncated; routing limit MULTI_ROOT_PRIOR_RESULT_MAX_CHARS)"


def _routing_truncate_for_log(text: str, limit: int = 260) -> str:
    raw = (text or "").replace("\n", " ").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."


def _is_allowed_join_key(key: str) -> bool:
    key_low = (key or "").strip().lower()
    if not key_low:
        return False
    if JOIN_KEY_ALLOWLIST:
        return key in JOIN_KEY_ALLOWLIST or key_low in [k.lower() for k in JOIN_KEY_ALLOWLIST]
    return key_low == "id" or key_low.endswith("_id") or key_low.endswith("id")


def _extract_join_keys_structured(text: str) -> Dict[str, List[str]]:
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

    key_map: Dict[str, set] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if _is_allowed_join_key(str(k)) and isinstance(v, (int, str)):
                    sval = str(v).strip()
                    if sval.isdigit():
                        key_map.setdefault(str(k), set()).add(sval)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return {k: sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY] for k, vals in key_map.items()}


def _extract_join_keys_regex_fallback(text: str) -> Dict[str, List[str]]:
    pattern = re.compile(
        r'["\']?([A-Za-z_][A-Za-z0-9_]{0,63})["\']?\s*[:=]\s*["\']?(\d{1,18})["\']?',
        flags=re.IGNORECASE,
    )
    key_map: Dict[str, set] = {}
    for m in pattern.finditer(text):
        key = (m.group(1) or "").strip()
        value = (m.group(2) or "").strip()
        if not key or not value:
            continue
        if _is_allowed_join_key(key):
            key_map.setdefault(key, set()).add(value)
    return {k: sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY] for k, vals in key_map.items()}


def _extract_join_keys_from_text(text: str) -> Dict[str, List[str]]:
    if not (text or "").strip():
        return {}
    structured = _extract_join_keys_structured(text)
    if structured:
        return structured
    return _extract_join_keys_regex_fallback(text)


def _routing_render_values_inline(values: List[str], limit: int = 20) -> str:
    picked = [str(v or "").strip() for v in (values or []) if str(v or "").strip()]
    if not picked:
        return ""
    if len(picked) > limit:
        return ", ".join(picked[:limit]) + f", ...(+{len(picked) - limit})"
    return ", ".join(picked)


def routing_build_balanced_prior_task_payload(
    task_id: int,
    agent: str,
    result_text: str,
    *,
    task_description: str = "",
    run_id: str = "",
    trace_id: str = "",
) -> Dict[str, Any]:
    raw_full = str(result_text or "").strip()
    join_keys = _extract_join_keys_from_text(raw_full)
    raw = _truncate_text_for_routing_prior(raw_full, MULTI_ROOT_PRIOR_RESULT_MAX_CHARS)
    success_marker = "reason:The current answer addresses the question very well."
    if success_marker in raw_full:
        status = "complete"
    else:
        status = (
            "fail"
            if any(k in raw_full.lower() for k in ("[error:", " error:", " failed", "exception"))
            else "complete"
        )
    evidence_lines = [ln.strip() for ln in raw_full.splitlines() if ln.strip()][:5]
    core_metrics: Dict[str, Any] = {}
    for k, vals in sorted((join_keys or {}).items())[:5]:
        core_metrics[f"{k}_count"] = len(vals)
    return {
        "task_id": task_id,
        "agent": agent,
        "task_description": str(task_description or "").strip(),
        "result": raw,
        "status": status,
        "final_answer": raw,
        "join_keys": join_keys,
        "core_metrics": core_metrics,
        "error_summary": raw[:300] if status == "fail" else "",
        "evidence_summary": evidence_lines,
        "trace_ref": {"run_id": run_id or "", "trace_id": trace_id or "", "task_id": task_id},
    }


def routing_collect_join_keys_from_prior_results(
    prior_task_results: List[dict],
    allowed_task_ids: Optional[set[int]] = None,
) -> Dict[str, List[str]]:
    key_map: Dict[str, set] = {}
    for item in prior_task_results or []:
        try:
            item_task_id = int(item.get("task_id") or 0)
        except (TypeError, ValueError):
            continue
        if allowed_task_ids and item_task_id not in allowed_task_ids:
            continue
        join_keys = item.get("join_keys") if isinstance(item.get("join_keys"), dict) else {}
        if not join_keys:
            text = str(item.get("final_answer") or item.get("result") or "")
            join_keys = _extract_join_keys_from_text(text)
        for key, values in (join_keys or {}).items():
            nk = str(key or "").strip()
            if not nk:
                continue
            for value in list(values or []):
                sval = str(value or "").strip()
                if not sval:
                    continue
                key_map.setdefault(nk, set()).add(sval)
    return {k: sorted(vals)[:MAX_JOIN_KEY_VALUES_PER_KEY] for k, vals in key_map.items()}


def routing_build_prior_semantic_context(task_description: str, prior_task_results: List[dict]) -> Dict[str, Any]:
    dep_payload: List[Dict[str, Any]] = []
    for item in prior_task_results[:MULTI_ROOT_RESOLVE_PRIOR_TASK_LIMIT]:
        join_keys = item.get("join_keys") if isinstance(item.get("join_keys"), dict) else {}
        trimmed: Dict[str, List[str]] = {}
        for k, vals in list((join_keys or {}).items())[:MULTI_ROOT_RESOLVE_KEY_LIMIT]:
            trimmed[str(k)] = [str(v) for v in list(vals or [])[:MULTI_ROOT_RESOLVE_VALUES_LIMIT]]
        dep_payload.append(
            {
                "task_id": int(item.get("task_id") or 0),
                "agent": str(item.get("agent") or ""),
                "task_description": str(
                    item.get("task_description") or item.get("description") or ""
                ).strip(),
                "join_keys": trimmed,
                "result_excerpt": _routing_truncate_for_log(
                    str(item.get("final_answer") or item.get("result") or ""),
                    MULTI_ROOT_RESOLVE_ANSWER_CHARS,
                ),
            }
        )
    return {
        "task_description": str(task_description or "").strip(),
        "prior_results": dep_payload,
    }


def routing_fallback_resolve_description_with_join_keys(
    desc: str,
    join_keys: Dict[str, List[str]],
) -> Tuple[str, List[str]]:
    if not desc or not join_keys:
        return desc, []
    dependency_like = re.search(
        r"(任务\s*\d+|task\s*\d+|上一步|前序|依赖|返回的|结果中|根据.+(?:id|ID|编号|列表)|基于.+(?:id|ID|编号|列表))",
        desc,
        flags=re.IGNORECASE,
    )
    if not dependency_like:
        return desc, []
    ranked = sorted(
        [(k, list(vs or [])) for k, vs in (join_keys or {}).items() if k and list(vs or [])],
        key=lambda kv: (-len(kv[1]), kv[0]),
    )[:MULTI_ROOT_RESOLVE_KEY_LIMIT]
    if not ranked:
        return desc, []
    hints: List[str] = []
    selected_keys: List[str] = []
    for key, vals in ranked:
        selected_keys.append(str(key))
        rendered = _routing_render_values_inline(vals, limit=MULTI_ROOT_RESOLVE_VALUES_LIMIT)
        if rendered:
            hints.append(f"{key}: {rendered}")
    if not hints:
        return desc, []
    return (
        f"{desc}。前序任务中已识别到可直接使用的字段和值：{'; '.join(hints)}",
        selected_keys,
    )


async def routing_resolve_task_query_for_multi_root(
    llm: Any,
    task_description: str,
    depends_on: List[int],
    prior_task_results: List[dict],
) -> Tuple[str, str, List[str], Dict[str, Any]]:
    """Align with SG Orchestrator MultiChild: LLM rewrite + join-key fallback (no brute-force concat)."""
    desc = str(task_description or "").strip()
    if not desc or not prior_task_results:
        return desc, "none", [], {
            "reason": "empty_description_or_prior",
            "filtered_prior_count": 0,
            "join_key_count": 0,
        }
    dep_ids: set[int] = set()
    for d in depends_on or []:
        try:
            di = int(d)
            if di > 0:
                dep_ids.add(di)
        except (TypeError, ValueError):
            continue
    filtered_prior: List[dict] = []
    for item in prior_task_results or []:
        if not isinstance(item, dict):
            continue
        try:
            tid = int(item.get("task_id") or 0)
        except (TypeError, ValueError):
            tid = 0
        if not dep_ids or tid in dep_ids:
            filtered_prior.append(item)
    if not filtered_prior:
        return desc, "none", [], {
            "reason": "no_matching_dependency_prior",
            "filtered_prior_count": 0,
            "join_key_count": 0,
        }

    context_payload = routing_build_prior_semantic_context(desc, filtered_prior)
    prompt = (
        "你是多智能体编排器中的依赖任务解析器。请根据当前子任务描述和前序任务结果，"
        "把当前任务改写成可以直接执行的描述。你的职责不是只看结构化字段，而是要主动从前序文本里提取当前任务真正需要的信息。"
        "前序结果可能是自然语言、项目符号、markdown 表格、排行榜、对比说明或混合文本，只要信息真实存在于文本里，你就应该识别并使用。"
        "不要臆造不存在的数据，不要改变任务目标。通过调用 `resolve_task` 工具输出结果。\n\n"
        "规则：\n"
        "1) 优先依据语义理解前序结果，不要因为前序结果不是 JSON/数组/显式字段结构，就判定为无法提取。\n"
        "2) 如果前序文本中已经出现了当前任务所需的 ID、名称、时间、筛选条件、排名结果或对象列表，应主动抽取并写入 resolved_query。\n"
        "3) markdown 表格中的列和值也属于可直接使用的信息。例如表格列名是 `商品ID`，则应识别该列下的所有 ID。\n"
        "4) 如果当前任务描述里出现“根据...ID列表/根据返回结果/基于上一步结果”等占位式说法，而前序文本里已经给出了对应信息，应该 applied=true。\n"
        "5) applied=false 只在前序结果确实不包含当前任务所需关键信息时才允许；不能因为信息以自然语言或表格形式出现就返回 false。\n"
        "6) selected_keys 填写你实际依赖的关键信息来源，可以是字段名、表格列名或语义标签。\n"
        "7) resolved_query 必须是可直接交给下游子智能体执行的文本，写清楚你从前序结果中识别出的关键值。\n\n"
        f"输入数据：\n{json.dumps(context_payload, ensure_ascii=False)}"
    )

    llm_reason = ""
    try:
        resolve_tool = StructuredTool(
            name="resolve_task",
            description="Rewrite the current task description using info extracted from the prior task results.",
            args_schema=ResolvedTaskQuery,
            func=None,
            coroutine=None,
        )
        data = await invoke_llm_with_tool(
            llm=llm,
            tool=resolve_tool,
            messages=[HumanMessage(content=prompt)],
            metadata=None,
            tool_choice="resolve_task",
            span_name="routing-resolve-task",
        )
        if not isinstance(data, dict):
            raise ValueError("resolve_task tool call returned no structured args")
        resolved = str(data.get("resolved_query") or "").strip()
        applied = bool(data.get("applied", False))
        llm_reason = str(data.get("reason") or "").strip()
        selected_keys = [str(v) for v in list(data.get("selected_keys") or []) if str(v or "").strip()]
        if applied and resolved and resolved != desc:
            return resolved, "llm", selected_keys[:MULTI_ROOT_RESOLVE_KEY_LIMIT], {
                "reason": llm_reason or "llm_applied",
                "filtered_prior_count": len(filtered_prior),
                "join_key_count": sum(
                    len((item.get("join_keys") or {}).keys())
                    for item in filtered_prior
                    if isinstance(item.get("join_keys"), dict)
                ),
            }
        if not applied:
            llm_reason = llm_reason or "llm_applied_false"
        elif not resolved:
            llm_reason = llm_reason or "llm_resolved_query_empty"
        elif resolved == desc:
            llm_reason = llm_reason or "llm_resolved_query_unchanged"
        else:
            llm_reason = llm_reason or "llm_unknown_no_apply"
    except Exception as e:
        logger.warning("[RoutePlan] multi-root query resolution LLM failed, using join-key fallback: %s", e)
        llm_reason = f"llm_exception:{type(e).__name__}"

    jkeys = routing_collect_join_keys_from_prior_results(filtered_prior, dep_ids if dep_ids else None)
    fallback_desc, selected = routing_fallback_resolve_description_with_join_keys(desc, jkeys)
    if fallback_desc != desc:
        return fallback_desc, "fallback_join_keys", selected, {
            "reason": llm_reason or "fallback_join_keys_applied",
            "filtered_prior_count": len(filtered_prior),
            "join_key_count": len(jkeys),
        }
    return desc, "none", [], {
        "reason": llm_reason or "fallback_not_applicable",
        "filtered_prior_count": len(filtered_prior),
        "join_key_count": len(jkeys),
    }


SPLIT_NECESSITY_PROMPT = """你是任务拆分必要性判定器。

目标：判断用户问题是否必须拆分给多个专家，还是单专家可完整处理。

规则：
1) 仅在“关键需求单元明确跨多个专家能力边界，且单专家无法闭环”时，needs_split=true。
2) 若存在单专家可完整覆盖主要需求，needs_split=false（最小必要拆分）。
3) 不要因为表达习惯、输出形式、轻微口径差异而强制拆分。
4) 仅基于问题语义与候选专家能力信息判断，不依赖任何特定行业硬编码词。

候选专家：
{agents}

历史对话：
{history}

用户问题：
{query}

输出：只输出 JSON，不要 markdown
{{"needs_split": true 或 false, "reason": "简要原因"}}
"""


SINGLE_ROOT_FALLBACK_RANK_PROMPT = """你是 single-root fallback 的主处理专家选择器。

目标：当 multi-root 规划失败、必须退化为单专家处理时，请在多个候选 root 专家中选择最适合直接承接整个用户问题的一个专家。

规则：
1) 只能从候选列表中选择一个 best_agent。
2) 重点判断用户问题的核心主体、主要筛选条件、主要结果对象与哪个专家最直接匹配。
3) 不要因为某个专家可能提供辅助信息，就把它选为主处理者；应优先选择与问题主体直接匹配的专家。
4) 输出必须是 JSON，不要 markdown。

候选 root 专家：
{agents}

用户问题：
{query}

输出 JSON：
{{"best_agent": "候选专家名称之一", "confidence": 0.0 到 1.0, "reason": "简要原因"}}
"""


# ==================== End Multi-Root Task Plan Protocol ====================


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
        data_services_url: str = None
    ):
        logger.info('Initializing PlannerAgent')
        super().__init__(
            agent_name='PlannerAgent',
            description='Breakdown the user request into executable tasks',
            content_types=['text', 'text/plain'],
        )
        self.manager = ModelManager()
        # 默认设置 enable_thinking 参数；设 ENABLE_THINKING_PARAM=false/0/no 时不传该参数（extra_body={}，用模型默认）
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
        self.data_services_client = DataServicesClient(base_url=data_services_url, timeout=600)

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

    # Generate a prompt containing information about all agents for the large language model to determine which agents to use.
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

    async def get_history_payload(
        self,
        user_id: str,
        run_id: str,
        propagated_history: Optional[dict] = None,
    ) -> dict:
        payload = parse_propagated_history(propagated_history)
        if normalize_history_turns(payload.get("turns")):
            payload.setdefault("source", "propagated_history")
            payload["turn_count"] = len(normalize_history_turns(payload.get("turns")))
            return payload

        logger.info(f"PlannerAgent get_history metadata: user_id: {user_id}, run_id:{run_id}")

        search_items = []
        history_limit = get_conversation_history_limit()
        search_request = SearchHistoryRequest(
                user_id=user_id,
                run_id=run_id,
                limit=history_limit
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"PlannerAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"PlannerAgent get_history response : {search_items}")
        return build_propagated_history(
            extract_history_turns(search_items),
            source="routing_prefetch",
        )

    async def get_history(
        self,
        user_id:str,
        run_id:str,
        propagated_history: Optional[dict] = None,
    ) -> str:
        """
        return ->：

        human: Hello  
        assistant: Hello! How can I help you?  
        human: What's the weather like today?  
        assistant: Please provide your location information.
        """

        payload = await self.get_history_payload(
            user_id=user_id,
            run_id=run_id,
            propagated_history=propagated_history,
        )
        return history_text_from_payload(payload)

    async def make_plan(
        self,
        query,
        agent_cards,
        user_id,
        run_id,
        trace_id,
        propagated_history: Optional[dict] = None,
    ) -> PlannerStep:
        """
        Based on the information from all provided agent cards, analyze which agents are required for the user's query, and finally return the names and descriptions of these agent cards.
        """
        enable_history = os.getenv('Enable_History',"enable")
        logger.info(f"enable_history is: {enable_history}")

        system_template = ""
        if enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_ZH

        human_template = "{query}"

        json_prompt_instructions: dict = {
          "thought_process": "1.本体提取：对象为'订单'；2.领域判定：EcommerceAgent 负责订单领域；3.能力推断：该 Agent 具备统计功能。结论：匹配成功。",
          "original_query": "查询订单状态分布",
          "agent": "EcommerceTransactionOrchestrator"
        }

        system_prompt = None
        if enable_history == "enable":
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["history", "agents"],
                partial_variables={"instructions": json_prompt_instructions},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents"],
                partial_variables={"instructions": json_prompt_instructions},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        logger.info(f"PlannerAgent.make_plan, system_prompt_agents = {system_prompt_agents}")

        # Build the messages once, then reuse them across tool-call retry attempts.
        if enable_history == "enable":
            history = await self.get_history(
                user_id=user_id,
                run_id=run_id,
                propagated_history=propagated_history,
            )
            messages = chat_prompt.format_messages(
                **{"query": query, "history": history, "agents": system_prompt_agents}
            )
        else:
            messages = chat_prompt.format_messages(
                **{"query": query, "agents": system_prompt_agents}
            )

        make_plan_tool = StructuredTool(
            name="make_plan_cmd",
            description="Provide the routing plan as structured tool arguments (original_query and selected agent).",
            args_schema=PlannerStep,
            func=None,
            coroutine=None,
        )

        metadata = {"user_id": user_id, "run_id": run_id, "trace_id": trace_id}

        # Use the predefined trace ID with trace_context
        with langfuse.start_as_current_span(
            name="routingagent-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            step = None
            for attempt in range(1, 3):
                data_dict = await invoke_llm_with_tool(
                    llm=self.llm,
                    tool=make_plan_tool,
                    messages=messages,
                    metadata=metadata,
                    tool_choice="make_plan_cmd",
                    span_name="routingagent-make_plan-step",
                    span_input={"query": query, "attempt": attempt},
                )
                if not isinstance(data_dict, dict):
                    logger.warning(
                        f"PlannerAgent.make_plan attempt {attempt}/2: LLM did not call tool, nudging."
                    )
                    messages = messages + [
                        AIMessage(content=""),
                        HumanMessage(
                            content="你上一次没有调用工具。请**必须**调用 `make_plan_cmd` 工具来输出规划结果，不要直接输出文本或 JSON。"
                        ),
                    ]
                    continue

                logger.info(f" === PlannerAgent.make_plan, data_dict = {data_dict}")
                try:
                    step = PlannerStep(**data_dict)
                    break
                except Exception as e:
                    logger.warning(
                        f"PlannerAgent.make_plan attempt {attempt}/2: failed to parse PlannerStep from args: {e}, nudging."
                    )
                    messages = messages + [
                        AIMessage(content=""),
                        HumanMessage(
                            content=f"工具调用参数解析失败: {e}。请重新调用 `make_plan_cmd`，并确保提供 original_query 和 agent 字段。"
                        ),
                    ]

            span.update_trace(output={"step": step.dict() if step else None})

        langfuse.flush()

        if step is None:
            raise ValueError("PlannerAgent.make_plan failed to obtain a valid plan after retries")
        logger.info(f" === PlannerAgent.make_plan , step = {step}")
        return step


@asynccontextmanager
async def init_session(host, port, transport):
    """Initializes and manages an MCP ClientSession based on the specified transport.

    This asynchronous context manager establishes a connection to an MCP server
    using either Server-Sent Events (SSE) or Standard I/O (STDIO) transport.
    It handles the setup and teardown of the connection and yields an active
    `ClientSession` object ready for communication.

    Args:
        host: The hostname or IP address of the MCP server (used for SSE).
        port: The port number of the MCP server (used for SSE).
        transport: The communication transport to use ('sse' or 'stdio').

    Yields:
        ClientSession: An initialized and ready-to-use MCP client session.

    Raises:
        ValueError: If an unsupported transport type is provided (implicitly,
                    as it won't match 'sse' or 'stdio').
        Exception: Other potential exceptions during client initialization or
                   session setup.
    """
    if transport == 'sse':
        url = f'http://{host}:{port}/sse'
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(
                read_stream=read_stream, write_stream=write_stream
            ) as session:
                logger.debug('SSE ClientSession created, initializing...')
                await session.initialize()
                logger.info('SSE ClientSession initialized successfully.')
                yield session
    else:
        logger.error(f'Unsupported transport type: {transport}')
        raise ValueError(
            f"Unsupported transport type: {transport}. Must be 'sse' or 'stdio'."
        )


class RoutingAgent(BaseAgent):
    """Routing Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_services_url: str = None
    ):
        logger.info('Initializing RoutingAgent')
        super().__init__(
            agent_name='RoutingAgent',
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
            data_services_url=data_services_url
        )
        self.manager = ModelManager()
        # 默认设置 enable_thinking 参数；设 ENABLE_THINKING_PARAM=false/0/no 时不传该参数（extra_body={}，用模型默认）
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
        self.data_services_url = (
            data_services_url
            if data_services_url
            else os.getenv("DataServicesURL", "http://data-services.dac.svc.cluster.local:8000")
        )
        self.agent_cards = []

    def _extract_semantic_group_id_from_agent_name(self, agent_name: str) -> Optional[str]:
        """Extract semantic group id from orchestrator name suffix: xxx-sg-<group_id>."""
        marker = "-sg-"
        if marker not in agent_name:
            return None
        group_id = agent_name.split(marker)[-1].strip()
        return group_id or None

    def _normalize_capability_check_response(
        self,
        response: CapabilityCheckResponse,
    ) -> CapabilityCheckResponse:
        """Drop vague contributor responses so they do not trigger multi-root."""
        if response.can_handle:
            return response
        if not response.can_contribute:
            return response
        if _is_non_actionable_contribution_text(response.contribution):
            logger.info(
                "Broadcast routing: normalize non-actionable contributor '%s' contribution='%s'",
                response.agent_name,
                (response.contribution or "")[:120],
            )
            response.can_contribute = False
            response.contribution = ""
            return response
        blob = f"{response.contribution or ''} {response.reason or ''}"
        if _is_non_actionable_contribution_text(blob):
            response.can_contribute = False
            response.contribution = ""
            return response
        name = str(getattr(response, "agent_name", "") or "").lower()
        if "weather" in name and not re.search(r"天气|weather|forecast|气温", blob, flags=re.I):
            logger.info(
                "Broadcast routing: normalize skill-mismatch contributor '%s'",
                response.agent_name,
            )
            response.can_contribute = False
            response.contribution = ""
        return response

    def _prior_task_payloads_for_multi_root(
        self,
        task_def: MultiRootTask,
        tasks_by_id: dict[int, MultiRootTask],
        task_results: dict[int, str],
        run_id: str = "",
        trace_id: str = "",
    ) -> list[dict]:
        """Balanced prior payloads (join_keys + excerpt), aligned with SG MultiChild / raytest orchestrator."""
        out: list[dict] = []
        for dep in task_def.depends_on or []:
            try:
                dep_id = int(dep)
            except (TypeError, ValueError):
                continue
            if dep_id not in task_results:
                continue
            dep_t = tasks_by_id.get(dep_id)
            raw = str(task_results[dep_id] or "").strip()
            if not raw:
                continue
            ag = dep_t.agent if dep_t else ""
            dep_desc = (dep_t.description or "").strip() if dep_t else ""
            out.append(
                routing_build_balanced_prior_task_payload(
                    dep_id,
                    ag,
                    raw,
                    task_description=dep_desc,
                    run_id=run_id,
                    trace_id=trace_id,
                )
            )
        return out

    def _extract_semantic_group_id_from_agent_card(self, card: AgentCard) -> Optional[str]:
        """Extract semantic_group_id from capabilities.extensions contract first.

        Preferred source:
          - capabilities.extensions[uri='dac.semantic_group'].params["dac.semantic_group_id"]
        Backward compatibility:
          - params["semantic_group_id"]
        Fallback:
          - name suffix xxx-sg-<group_id>
        """
        caps = getattr(card, "capabilities", None)
        ext_list = None
        if isinstance(caps, dict):
            ext_list = caps.get("extensions")
        elif caps is not None:
            ext_list = getattr(caps, "extensions", None)

        if isinstance(ext_list, list):
            for ext in ext_list:
                if isinstance(ext, dict):
                    uri = ext.get("uri")
                    params = ext.get("params") or {}
                else:
                    uri = getattr(ext, "uri", None)
                    params = getattr(ext, "params", None) or {}
                if uri != "dac.semantic_group" or not isinstance(params, dict):
                    continue
                gid = (params.get("dac.semantic_group_id") or params.get("semantic_group_id") or "").strip()
                if gid:
                    return gid

        return self._extract_semantic_group_id_from_agent_name(card.name)

    async def _is_root_semantic_group(self, group_id: str) -> tuple[Optional[bool], str]:
        """Check whether semantic group is root by parent_id.

        Returns:
            (is_root, reason), where is_root=None means unknown/failed.
        """
        try:
            url = f"{self.data_services_url.rstrip('/')}/semantic_groups/{group_id}"
            logger.info("[RootGuardCheck] request: group_id=%s, url=%s", group_id, url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                body_preview = (resp.text or "")[:300]
                logger.warning(
                    "[RootGuardCheck] response non-200: group_id=%s, url=%s, status=%s, body_preview=%s",
                    group_id, url, resp.status_code, body_preview
                )
                return None, f"http_{resp.status_code}"
            parent_id = resp.json().get("data", {}).get("parent_id")
            logger.info(
                "[RootGuardCheck] response ok: group_id=%s, url=%s, parent_id=%s, is_root=%s",
                group_id, url, parent_id, parent_id is None
            )
            return parent_id is None, "ok"
        except Exception as e:
            logger.error(
                "[RootGuardCheck] request exception: group_id=%s, url=%s, error=%s",
                group_id,
                f"{self.data_services_url.rstrip('/')}/semantic_groups/{group_id}",
                e,
            )
            return None, f"exception:{e}"

    async def _apply_root_membership_guard(self, agent_cards: list[AgentCard]) -> list[AgentCard]:
        """Optional guard: filter out non-root SG agents before capability checks."""
        guard_enabled = os.getenv("ENABLE_ROOT_MEMBERSHIP_GUARD", "true").strip().lower() in ("true", "1", "yes")
        if not guard_enabled:
            return agent_cards

        guard_fail_policy = os.getenv("ROOT_GUARD_FAIL_POLICY", "fail_close").strip().lower()
        if guard_fail_policy not in ("fail_open", "fail_close"):
            logger.warning("Invalid ROOT_GUARD_FAIL_POLICY=%s, fallback to fail_close", guard_fail_policy)
            guard_fail_policy = "fail_close"

        kept: list[AgentCard] = []
        filtered: list[str] = []
        unknown: list[str] = []

        for card in agent_cards:
            group_id = self._extract_semantic_group_id_from_agent_card(card)
            # Non-SG agents are kept as-is.
            if not group_id:
                kept.append(card)
                continue

            is_root, reason = await self._is_root_semantic_group(group_id)
            if is_root is True:
                kept.append(card)
                continue
            if is_root is False:
                filtered.append(f"{card.name}(non_root)")
                continue

            # Unknown root status
            if guard_fail_policy == "fail_open":
                kept.append(card)
                unknown.append(f"{card.name}({reason},kept)")
            else:
                filtered.append(f"{card.name}(unknown:{reason})")
                unknown.append(f"{card.name}({reason},filtered)")

        logger.info(
            "Root membership guard: total=%d, kept=%d, filtered=%d, unknown=%d",
            len(agent_cards), len(kept), len(filtered), len(unknown)
        )
        if filtered:
            logger.warning("Root membership guard filtered agents: %s", filtered)
        return kept

    # get all plans (agent names) for user question to execute
    async def get_plan(
        self,
        query,
        user_id,
        run_id,
        trace_id,
        propagated_history: Optional[dict] = None,
    ) -> PlannerStep:

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            logger.info("No agents found in registry, using default agent card: %s", self.default_agentcard().url)
            self.agent_cards = [self.default_agentcard()]

        return await self.planner_agent.make_plan(
            query,
            self.agent_cards,
            user_id,
            run_id,
            trace_id,
            propagated_history=propagated_history,
        )


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

    # get all AgentCards using find_resource func
    async def list_agent_cards(self, query) -> list[AgentCard]:
        """Reads all resources from the connected agent registry.
        Returns:
            agent_cards = [
                {
                "name": "Expert Agent",
                "description": "answer user question using self knowledge",
                "url": "http://192.168.xxx.xxx:20001",
                "provider": null,
                "version": "1.0.0",
                "documentationUrl": null
                ...},
                ...
            ]
        """
        agent_cards = []

        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("AgentRegistryCollection", "orchestrator_agent_cards")
        logger.info(
            "list_agent_cards: AgentRegistry base_url=%s, collection=%s (env AgentRegistryCollection)",
            os.getenv("AgentRegistry", "http://orchestrator-registry.dac.svc.cluster.local:10100").rstrip("/"),
            collection_name,
        )
        try:
            response = await agent_registry_client.asearch(query, collection_name=collection_name)

            if response.status == "success":
                agent_cards_dict = []
                for item in response.result:
                    metadata = item.metadata
                    agent_data = metadata.get("agent", {})
                    
                    if isinstance(agent_data, dict):
                        agent_cards_dict.append(agent_data)
                    elif hasattr(agent_data, '__dict__'):
                        agent_dict = agent_data.__dict__.copy()
                        agent_cards_dict.append(agent_dict)
                
                agent_cards = [AgentCard(**agent_data) for agent_data in agent_cards_dict]
                
                agent_names = [card.name for card in agent_cards]
                logger.info(f"Successfully retrieved {len(agent_cards)} agent cards: {agent_names}")
                return agent_cards
            else:
                logger.warning(f"Search returned non-success status: {response.status}")
                return []

        except Exception as e:
            logger.error(f'An error occurred during list_agent_cards: {e}')
            raise ValueError(f"An error occurred during list_agent_cards: {e}")


    def default_agentcard(self) -> AgentCard:
        """Build a default AgentCard when no agents are found in registry. URL points to common orchestrator."""
        default_url = "http://common-orchestrator-agent.dac.svc.cluster.local:10100"
        return AgentCard(
            name="CommonAgent",
            description="I am a common system intelligent agent that can answer user-related questions.",
            url=default_url,
            version="1.0.0",
            capabilities={"streaming": "True", "pushNotifications": "True", "stateTransitionHistory": "False"},
            defaultInputModes=["text", "text/plain"],
            defaultOutputModes=["text", "text/plain"],
            skills=[],
        )

    # handle response artifact-update event to get knowledge string from a2a server
    def get_response_text(self, chunk) -> str:
        data = chunk.model_dump(mode='json', exclude_none=True)
        if (result := data.get('result')) is not None:
            kind = result.get('kind')
            if kind == 'artifact-update':
                artifact = result.get('artifact')
                parts = artifact.get('parts')
                if len(parts) > 0 and isinstance(parts[0], dict):
                    return parts[0].get('text')

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
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        allowed = PROGRESS_EXTRA_ALLOWLIST.get(event, set())
        filtered_extra: Dict[str, Any] = {}
        if extra and allowed:
            filtered_extra = {k: v for k, v in extra.items() if k in allowed}
        payload: Dict[str, Any] = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "layer": "routing",
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
    def is_internal_dac_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_")

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
        layer: str = "routing",
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
    def is_final_answer_frame(cls, text: str) -> bool:
        data = cls.parse_answer_frame(text)
        if not data:
            return False
        return str(data.get("event") or "").strip() in {"final_answer_chunk", "final_answer"}

    @classmethod
    def strip_progress_lines(cls, text: str) -> str:
        if not text:
            return ""
        lines = [line for line in text.splitlines() if not cls.is_progress_frame(line)]
        return "\n".join(lines).strip()

    def summarize_multi_root_plan(self, plan: Optional["MultiRootTaskPlan"]) -> str:
        if not plan or not getattr(plan, "tasks", None):
            return "no tasks"
        items: List[str] = []
        for task in plan.tasks[:5]:
            deps = ",".join(str(dep) for dep in (task.depends_on or [])) or "-"
            desc = (task.description or "").replace("\n", " ").strip()
            if len(desc) > 80:
                desc = desc[:77] + "..."
            items.append(f"{task.id}:{task.agent}:deps={deps}:{desc}")
        if len(plan.tasks) > 5:
            items.append(f"... total={len(plan.tasks)}")
        return " | ".join(items)

    # find one AgentCard with agent name which is from plan task
    async def find_agent(self, agent_name) -> AgentCard:
        # find agentcard using agent name

        agent_names = [c.name for c in (self.agent_cards or [])]
        logger.info("find_agent, agent_names=%s, agent_name=%s", agent_names, agent_name)
        agent_card = None

        for agentcard in self.agent_cards:
            if agentcard.name == agent_name:
                agent_card = agentcard

        return agent_card

    # ==================== Broadcast Routing Methods ====================

    async def list_all_agent_cards(self) -> list[AgentCard]:
        """Fetch ALL registered orchestrator agents from the registry service.
        
        Unlike list_agent_cards() which uses vector search,
        this retrieves every agent without query-based filtering.
        
        Returns:
            List of all AgentCard objects from the registry.
        """
        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("AgentRegistryCollection", "orchestrator_agent_cards")
        all_agent_cards: list[AgentCard] = []

        try:
            agents_data = await agent_registry_client.alist_all_agents(
                collection_name=collection_name
            )
            logger.info(f"[DEBUG] list_all_agent_cards: agents_data type={type(agents_data).__name__}, len={len(agents_data)}")
            for idx, agent_data in enumerate(agents_data):
                logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] type={type(agent_data).__name__}, value(first 500 chars)={str(agent_data)[:500]}")
                if isinstance(agent_data, dict):
                    # Handle nested format where agent card is inside an "agent" key
                    if "agent" in agent_data and isinstance(agent_data["agent"], dict):
                        agent_data = agent_data["agent"]
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] unwrapped 'agent' key, keys now={list(agent_data.keys())}")
                    try:
                        all_agent_cards.append(AgentCard(**agent_data))
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] parsed OK as AgentCard, name={all_agent_cards[-1].name}")
                    except Exception as e:
                        logger.warning(f"Failed to parse agent card item[{idx}]: {e}, keys={list(agent_data.keys())}, data={str(agent_data)[:500]}")
                elif hasattr(agent_data, '__dict__'):
                    try:
                        all_agent_cards.append(AgentCard(**agent_data.__dict__))
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] parsed OK from object, name={all_agent_cards[-1].name}")
                    except Exception as e:
                        logger.warning(f"Failed to parse agent card from object item[{idx}]: {e}")
                else:
                    logger.warning(f"[DEBUG] list_all_agent_cards: item[{idx}] skipped, not dict and no __dict__, type={type(agent_data).__name__}")

            agent_names = [card.name for card in all_agent_cards]
            logger.info(f"Broadcast routing: retrieved {len(all_agent_cards)} agents from registry: {agent_names}")
        except Exception as e:
            logger.error(f"Broadcast routing: failed to list all agents: {e}", exc_info=True)

        filtered_cards = await self._apply_root_membership_guard(all_agent_cards)
        filtered_names = [card.name for card in filtered_cards]
        logger.info(
            "Broadcast routing: candidates after root guard = %d, names=%s",
            len(filtered_cards),
            filtered_names,
        )
        return filtered_cards

    async def send_capability_check(
        self,
        query: str,
        agent_card: AgentCard,
        user_id: str,
        run_id: str,
        trace_id: str,
        propagated_history: Optional[dict] = None,
    ) -> Optional[CapabilityCheckResponse]:
        """Send a capability check A2A request to a single orchestrator agent.
        
        Sends the user query with message_type='capability_check' in metadata.
        The receiving orchestrator should respond with a CapabilityCheckResponse JSON.
        
        Args:
            query: The user's question.
            agent_card: The target orchestrator agent's card.
            user_id: User ID for tracing.
            run_id: Run ID for tracing.
            trace_id: Trace ID for tracing.
            
        Returns:
            CapabilityCheckResponse if successful, None on failure.
        """
        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'message_type': CAPABILITY_CHECK_MESSAGE_TYPE,
                'user_id': user_id,
                'run_id': run_id,
                'trace_id': trace_id,
                PROPAGATED_HISTORY_KEY: propagated_history or {},
            },
        }

        broadcast_timeout = float(os.getenv("BROADCAST_TIMEOUT", "30"))
        _t0 = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=broadcast_timeout) as httpx_client:
                client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                response_parts = []
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result and result != "":
                        response_parts.append(result)

                full_response = "".join(response_parts).strip()

                # Clean markdown wrappers if present
                if full_response.startswith("```json"):
                    full_response = full_response[7:]
                elif full_response.startswith("```"):
                    full_response = full_response[3:]
                if full_response.endswith("```"):
                    full_response = full_response[:-3]
                full_response = full_response.strip()

                response_data = json.loads(full_response)
                rp = response_data.get("route_path") or []
                rps = response_data.get("route_paths") or []
                if not rps and rp:
                    rps = [{"path": rp, "confidence": response_data.get("confidence", 0.0)}]
                agent_latency_ms = int(response_data.get("latency_ms", 0) or 0)  # agent 自身上报的端到端耗时
                wait_ms = int((time.monotonic() - _t0) * 1000)  # routing 侧观测到的完整等待耗时
                logger.info(
                    "[Capability] agent=%s respond in wait_ms=%d agent_latency_ms=%d",
                    response_data.get("agent_name", agent_card.name),
                    wait_ms,
                    agent_latency_ms,
                )
                return CapabilityCheckResponse(
                    can_handle=response_data.get("can_handle", False),
                    confidence=response_data.get("confidence", 0.0),
                    reason=response_data.get("reason", ""),
                    agent_name=response_data.get("agent_name", agent_card.name),
                    agent_url=response_data.get("agent_url", agent_card.url),
                    route_path=rp,
                    route_paths=rps,
                    can_contribute=response_data.get("can_contribute", False),
                    contribution=response_data.get("contribution", ""),
                    execution_strategy=response_data.get("execution_strategy", "single"),
                    execution_hint=response_data.get("execution_hint") or {},
                    latency_ms=agent_latency_ms,
                )
        except json.JSONDecodeError as e:
            logger.error(
                f"Broadcast routing: JSON parse error for agent {agent_card.name} ({agent_card.url}): {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Broadcast routing: capability check failed for agent {agent_card.name} ({agent_card.url}): {e}"
            )
            return None

    async def broadcast_capability_check(
        self,
        query: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        propagated_history: Optional[dict] = None,
    ) -> list[tuple[AgentCard, CapabilityCheckResponse]]:
        """Broadcast a capability check to ALL registered orchestrator agents concurrently.
        
        Returns all capable agents sorted by confidence (highest first), not just the top one.
        The caller decides whether to use single-root or multi-root routing.
        """
        all_agent_cards = await self.list_all_agent_cards()

        if not all_agent_cards:
            logger.warning("Broadcast routing: no agents found in registry")
            return []

        logger.info(
            f"Broadcast routing: sending capability check to {len(all_agent_cards)} agents "
            f"for query: {query[:100]}..."
        )
        tasks = [
            self.send_capability_check(
                query,
                agent_card,
                user_id,
                run_id,
                trace_id,
                propagated_history=propagated_history,
            )
            for agent_card in all_agent_cards
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Broadcast routing: exception for agent {all_agent_cards[i].name}: {result}"
                )
                continue
            if result is None:
                logger.info(
                    f"Broadcast routing: agent {all_agent_cards[i].name} returned no valid response"
                )
                continue
            result = self._normalize_capability_check_response(result)
            if result.can_handle:
                capable_agents.append((all_agent_cards[i], result))
                logger.info(
                    f"Broadcast routing: agent '{result.agent_name}' CAN handle "
                    f"(confidence: {result.confidence}, reason: {result.reason})"
                )
            elif result.can_contribute:
                capable_agents.append((all_agent_cards[i], result))
                logger.info(
                    f"Broadcast routing: agent '{result.agent_name}' can_contribute=true "
                    f"(confidence: {result.confidence}, contribution: {result.contribution}, reason: {result.reason})"
                )
            else:
                logger.info(
                    f"Broadcast routing: agent '{result.agent_name}' CANNOT handle "
                    f"(reason: {result.reason})"
                )

        capable_agents.sort(key=lambda x: (1 if x[1].can_handle else 0, x[1].confidence), reverse=True)
        logger.info(
            "[RoutePlan] ========== Planning complete: %d root(s) can handle ==========",
            len(capable_agents),
        )
        for i, (card, resp) in enumerate(capable_agents[:5], 1):
            rps = getattr(resp, "route_paths", None) or []
            if not rps and resp.route_path:
                rps = [{"path": resp.route_path, "confidence": resp.confidence}]
            paths_str = "; ".join(
                "[%s] conf=%.2f [%s]" % (
                    e.get("alias", "?"),
                    e.get("confidence", 0),
                    "->".join(e.get("path", [])),
                )
                for j, e in enumerate(rps[:5])
            )
            logger.info(
                "[RoutePlan]   #%d %s | executable_paths=%d | %s",
                i, card.name, len(rps), paths_str,
            )
        logger.info("[RoutePlan] ==========================================")
        return capable_agents

    def _validate_multi_root_plan(
        self,
        query: str,
        plan: MultiRootTaskPlan,
        candidate_agent_names: set[str],
    ) -> tuple[bool, str]:
        """Validate multi-root plan quality and enforce minimum necessary split."""
        if not plan.tasks:
            return False, "empty tasks"

        ids = [t.id for t in plan.tasks]
        if len(ids) != len(set(ids)):
            return False, "duplicate task ids"
        id_set = set(ids)

        for t in plan.tasks:
            if t.agent not in candidate_agent_names:
                return False, f"unknown agent: {t.agent}"
            if not (t.description or "").strip():
                return False, f"empty description in task {t.id}"
            if self._is_forbidden_summary_task_description(t.description):
                return (
                    False,
                    f"task {t.id} is summary/reconcile intent; remove final-summary task and keep only data tasks",
                )
            for dep in t.depends_on:
                if dep not in id_set or dep == t.id:
                    return False, f"invalid dependency in task {t.id}"

        # DAG guard: reject cyclic dependencies.
        deps = {t.id: list(t.depends_on or []) for t in plan.tasks}
        state: dict[int, int] = {}  # 0/None=unvisited, 1=visiting, 2=done

        def _has_cycle(node: int) -> bool:
            st = state.get(node, 0)
            if st == 1:
                return True
            if st == 2:
                return False
            state[node] = 1
            for p in deps.get(node, []):
                if _has_cycle(p):
                    return True
            state[node] = 2
            return False

        for node in deps:
            if _has_cycle(node):
                return False, "dependency cycle detected"

        if plan.needs_split and len(plan.tasks) < 2:
            return False, "needs_split=true but tasks<2"
        if (not plan.needs_split) and len(plan.tasks) != 1:
            return False, "needs_split=false but tasks!=1"
        if len(plan.tasks) > 1:
            # Guard against pseudo-split: every task repeats the original query.
            if all((t.description or "").strip() == (query or "").strip() for t in plan.tasks):
                return False, "all task descriptions equal original query"

        requirements = [r.strip() for r in (plan.requirements or []) if (r or "").strip()]
        if requirements:
            covered = set()
            for t in plan.tasks:
                covered.update([(c or "").strip() for c in (t.covers or []) if (c or "").strip()])
            missing = [r for r in requirements if r not in covered]
            if missing:
                return False, f"missing requirement coverage: {missing[:5]}"

        return True, "ok"

    def _is_forbidden_summary_task_description(self, description: str) -> bool:
        """Reject summary/reconcile tasks in planning; final summary belongs to Orchestrator."""
        text = str(description or "").strip().lower()
        if not text:
            return False
        strong_markers = (
            "最终答案", "最终报告", "最终回复", "最终结论",
            "综合所有专家", "整合所有任务", "汇总所有任务",
            "汇总前序结果", "整合前序结果", "跨任务整合", "关联整合",
        )
        if any(m in text for m in strong_markers):
            return True

        context_markers = ("任务", "前序", "上游", "子任务", "专家", "结果")
        action_markers = ("整合", "汇总", "合并", "综合", "归并", "拼接")
        has_context = any(m in text for m in context_markers)
        has_action = any(m in text for m in action_markers)
        has_final = ("最终" in text) or ("给用户" in text) or ("回答用户" in text)
        return has_context and has_action and has_final

    async def _judge_split_necessity_root(
        self,
        query: str,
        capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]],
        history_text: str = "",
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> Optional[bool]:
        """Use LLM voting to judge whether split is necessary (domain-agnostic)."""
        agents_desc = "\n".join(
            f"- name: {card.name}, description: {card.description}, "
            f"can_handle: {resp.can_handle}, can_contribute: {resp.can_contribute}, "
            f"confidence: {resp.confidence}, contribution: {resp.contribution}, reason: {resp.reason}"
            for card, resp in capable_agents
        )
        prompt = SPLIT_NECESSITY_PROMPT.format(
            agents=agents_desc,
            history=history_text or "（无）",
            query=query,
        )
        votes = max(1, int(os.getenv("SPLIT_JUDGE_VOTES", "3")))
        try:
            with langfuse.start_as_current_span(
                name="routing-split-judge-root",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "votes": votes, "candidate_count": len(capable_agents)},
                )

                judge_tool = StructuredTool(
                    name="judge_split",
                    description="Judge whether the query truly needs multi-agent split.",
                    args_schema=SplitJudgement,
                    func=None,
                    coroutine=None,
                )

                async def _one_vote() -> bool:
                    data = await invoke_llm_with_tool(
                        llm=self.planner_agent.llm,
                        tool=judge_tool,
                        messages=[HumanMessage(content=prompt)],
                        metadata={"user_id": user_id, "run_id": run_id, "trace_id": trace_id},
                        tool_choice="judge_split",
                        span_name="routing-split-judge-vote",
                        span_input={"query": query},
                    )
                    if not isinstance(data, dict):
                        return False
                    return bool(data.get("needs_split", False))

                ballot = await asyncio.gather(*[_one_vote() for _ in range(votes)])
                true_votes = sum(1 for v in ballot if v)
                false_votes = len(ballot) - true_votes
                span.update_trace(output={"true_votes": true_votes, "false_votes": false_votes})
            if true_votes == false_votes:
                return None
            return true_votes > false_votes
        except Exception as e:
            logger.warning("Split necessity judge failed (root), fallback to None: %s", e)
            return None

    def _pick_dominant_single_root(
        self,
        high_confidence: list[tuple[AgentCard, CapabilityCheckResponse]],
        high_confidence_contribute: list[tuple[AgentCard, CapabilityCheckResponse]],
    ) -> Optional[tuple[AgentCard, CapabilityCheckResponse, str]]:
        """Prefer single-root execution when one capable root is clearly dominant."""
        if not high_confidence:
            return None

        top_card, top_resp = high_confidence[0]
        top_conf = float(getattr(top_resp, "confidence", 0.0) or 0.0)
        if top_conf < ROOT_SINGLE_FAST_PATH_MIN_CONFIDENCE:
            return None

        if len(high_confidence) == 1:
            if not high_confidence_contribute:
                return top_card, top_resp, "only_high_confidence_handle"
            top_contrib_conf = float(
                getattr(high_confidence_contribute[0][1], "confidence", 0.0) or 0.0
            )
            conf_gap = top_conf - top_contrib_conf
            if conf_gap >= ROOT_SINGLE_FAST_PATH_GAP:
                return (
                    top_card,
                    top_resp,
                    (
                        "single_handle_dominates_contributors"
                        f"(handle={top_conf:.2f}, contribute={top_contrib_conf:.2f}, gap={conf_gap:.2f})"
                    ),
                )
            return None

        if high_confidence_contribute:
            return None

        second_conf = float(getattr(high_confidence[1][1], "confidence", 0.0) or 0.0)
        conf_gap = top_conf - second_conf
        if conf_gap >= ROOT_SINGLE_FAST_PATH_GAP:
            return (
                top_card,
                top_resp,
                f"top_handle_gap(handle={top_conf:.2f}, next={second_conf:.2f}, gap={conf_gap:.2f})",
            )
        return None

    async def get_plan_by_broadcast(
        self,
        query: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        propagated_history: Optional[dict] = None,
        on_multi_root_plan_validated: Optional[Callable[[MultiRootTaskPlan], Awaitable[None]]] = None,
    ) -> tuple[Optional[PlannerStep], Optional[MultiRootTaskPlan], list[AgentCard], Optional[list[dict]], dict]:
        """Broadcast-based routing with single-root fast path and multi-root task plan.
        
        Returns:
            (step, multi_plan, agent_cards, route_paths, execution_meta)
            execution_meta: {"execution_strategy": "single"|"multi_root", ...}
            - Single root: (PlannerStep, None, [agent], route_paths, execution_meta)
            - Multi root: (None, MultiRootTaskPlan, [agents...], None, execution_meta)
            - No match: (None, None, [], None, {})
        """
        logger.info("[RoutePlan] ========== Hierarchical Route Planning Start ==========")
        history_payload = {}
        if os.getenv('Enable_History', "enable") == "enable":
            history_payload = await self.planner_agent.get_history_payload(
                user_id=user_id,
                run_id=run_id,
                propagated_history=propagated_history,
            )
        history_text = history_text_from_payload(history_payload)
        capable_agents = await self.broadcast_capability_check(
            query,
            user_id,
            run_id,
            trace_id,
            propagated_history=history_payload,
        )

        if not capable_agents:
            logger.info("[RoutePlan] No capable agent found => (None, None, [], None, {})")
            return None, None, [], None, {}

        high_confidence = [
            (card, resp) for card, resp in capable_agents
            if resp.can_handle and resp.confidence >= MULTI_ROOT_CONFIDENCE_THRESHOLD
        ]
        high_confidence_contribute = [
            (card, resp) for card, resp in capable_agents
            if (not resp.can_handle) and resp.can_contribute and resp.confidence >= MULTI_ROOT_CONFIDENCE_THRESHOLD
        ]

        def _execution_meta(_resp) -> dict:
            meta = {
                "execution_strategy": "single",
                PROPAGATED_HISTORY_KEY: history_payload,
            }
            hint = getattr(_resp, "execution_hint", None) if _resp else None
            if isinstance(hint, dict) and hint:
                meta[SG_EXECUTION_HINT_KEY] = hint
            return meta

        def _root_plan_entry(card: AgentCard, resp: CapabilityCheckResponse) -> dict:
            rps = getattr(resp, "route_paths", None) or []
            if not rps and getattr(resp, "route_path", None):
                rps = [{"path": resp.route_path, "confidence": resp.confidence}]
            best_path = " -> ".join((rps[0].get("path", []) if rps else [])) if rps else card.name
            return {
                "root": card.name,
                "can_handle": bool(getattr(resp, "can_handle", False)),
                "can_contribute": bool(getattr(resp, "can_contribute", False)),
                "confidence": round(float(getattr(resp, "confidence", 0.0) or 0.0), 2),
                "strategy": "single",
                "route_paths": len(rps),
                "best_path": best_path,
            }

        if not high_confidence:
            top_handle = next(((c, r) for c, r in capable_agents if r.can_handle), None)
            if not top_handle:
                logger.info("[RoutePlan] No can_handle root (only contributors) => (None, None, [], None, {})")
                return None, None, [], None, {}
            selected_card, selected_resp = top_handle
            self.agent_cards = [selected_card]
            step = PlannerStep(original_query=query, agent=selected_card.name)
            rps = getattr(selected_resp, "route_paths", None) or []
            if not rps and selected_resp.route_path:
                rps = [{"path": selected_resp.route_path, "confidence": selected_resp.confidence}]
            exec_meta = _execution_meta(selected_resp)
            logger.info(
                "[RoutePlan] No high-confidence root; fallback to top capable root=%s conf=%.2f",
                selected_card.name,
                selected_resp.confidence,
            )
            return step, None, [selected_card], (rps if rps else None), exec_meta

        # Single-root fast path: one high-confidence handle and no strong contributors
        if len(high_confidence) <= 1 and not high_confidence_contribute:
            selected_card, selected_resp = capable_agents[0]
            self.agent_cards = [selected_card]
            step = PlannerStep(original_query=query, agent=selected_card.name)
            rps = getattr(selected_resp, "route_paths", None) or []
            if not rps and selected_resp.route_path:
                rps = [{"path": selected_resp.route_path, "confidence": selected_resp.confidence}]
            path_str = " -> ".join(selected_resp.route_path) if selected_resp.route_path else selected_card.name
            exec_meta = _execution_meta(selected_resp)
            strat = exec_meta.get("execution_strategy", "single")
            logger.info(
                "[RoutePlan] ========== Final Plan (single root) ==========\n"
                "  Root: %s | executable_paths=%d | strategy=%s\n"
                "  Best: conf=%.2f, path=[%s]\n"
                "  => Request will be sent to: %s\n"
                "==========================================",
                selected_card.name,
                len(rps),
                strat,
                selected_resp.confidence,
                path_str,
                selected_card.url,
            )
            return step, None, [selected_card], (rps if rps else None), exec_meta

        dominant_single = self._pick_dominant_single_root(
            high_confidence=high_confidence,
            high_confidence_contribute=high_confidence_contribute,
        )
        if dominant_single:
            selected_card, selected_resp, fast_path_reason = dominant_single
            self.agent_cards = [selected_card]
            step = PlannerStep(original_query=query, agent=selected_card.name)
            rps = getattr(selected_resp, "route_paths", None) or []
            if not rps and selected_resp.route_path:
                rps = [{"path": selected_resp.route_path, "confidence": selected_resp.confidence}]
            exec_meta = _execution_meta(selected_resp)
            logger.info(
                "[RoutePlan] Dominant single-root fast path => root=%s conf=%.2f reason=%s",
                selected_card.name,
                selected_resp.confidence,
                fast_path_reason,
            )
            return step, None, [selected_card], (rps if rps else None), exec_meta

        # Multi-root: use LLM task planning when there are multiple strong handlers
        # or one handler plus strong contributors.
        logger.info(
            "Broadcast routing: MULTI ROOT candidates handle=%d contribute=%d (threshold=%.2f)",
            len(high_confidence),
            len(high_confidence_contribute),
            MULTI_ROOT_CONFIDENCE_THRESHOLD,
        )
        planning_candidates = list(high_confidence)
        seen_names = {c.name for c, _ in planning_candidates}
        for c, r in high_confidence_contribute:
            if c.name not in seen_names:
                planning_candidates.append((c, r))
                seen_names.add(c.name)

        agent_cards = [card for card, _ in planning_candidates]
        self.agent_cards = agent_cards
        root_plans = [_root_plan_entry(card, resp) for card, resp in planning_candidates]

        multi_plan = await self._plan_cross_root_tasks(
            query,
            planning_candidates,
            history_text=history_text,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
            on_plan_validated=on_multi_root_plan_validated,
        )

        if multi_plan and multi_plan.tasks:
            # LLM may decide split is unnecessary (needs_split=false, single task)
            if len(multi_plan.tasks) == 1:
                single_agent_name = multi_plan.tasks[0].agent
                single_card = next((c for c in agent_cards if c.name == single_agent_name), agent_cards[0])
                self.agent_cards = [single_card]
                step = PlannerStep(original_query=query, agent=single_card.name)
                single_resp = next((r for c, r in high_confidence if c.name == single_agent_name), None)
                rps = getattr(single_resp, "route_paths", None) if single_resp else []
                if not rps and single_resp and single_resp.route_path:
                    rps = [{"path": single_resp.route_path, "confidence": single_resp.confidence}]
                path_str = (" -> ".join(single_resp.route_path) if single_resp and single_resp.route_path else single_card.name)
                exec_meta = _execution_meta(single_resp) if single_resp else {}
                logger.info(
                    "[RoutePlan] ========== Final Plan (multi-root→single) ==========\n"
                    "  Selected: %s | path=%s | executable_paths=%d\n"
                    "  (LLM: split not needed)\n"
                    "==========================================",
                    single_card.name, path_str, len(rps or []),
                )
                return step, None, [single_card], (rps if rps else None), exec_meta
            logger.info(
                "[RoutePlan] ========== Final Plan (multi-root split) ==========\n"
                "  Tasks: %s\n==========================================",
                [(t.id, t.agent, t.description[:40]) for t in multi_plan.tasks],
            )
            return None, multi_plan, agent_cards, None, {
                "execution_strategy": "multi_root",
                "root_plans": root_plans,
                PROPAGATED_HISTORY_KEY: history_payload,
            }

        # Fallback to single root if planning fails
        handle_candidates = [(c, r) for c, r in planning_candidates if r.can_handle]
        if len(handle_candidates) > 1:
            selected = await self._pick_best_root_for_fallback(
                query,
                handle_candidates,
                trace_id=trace_id,
                user_id=user_id,
                run_id=run_id,
            )
            if selected:
                selected_card, selected_resp = selected
            else:
                selected_card, selected_resp = handle_candidates[0]
        elif handle_candidates:
            selected_card, selected_resp = handle_candidates[0]
        else:
            selected_card, selected_resp = planning_candidates[0]
        step = PlannerStep(original_query=query, agent=selected_card.name)
        rps = getattr(selected_resp, "route_paths", None) if selected_resp else []
        if not rps and selected_resp and selected_resp.route_path:
            rps = [{"path": selected_resp.route_path, "confidence": selected_resp.confidence}]
        path_str = (" -> ".join(selected_resp.route_path) if selected_resp and selected_resp.route_path else selected_card.name)
        exec_meta = _execution_meta(selected_resp) if selected_resp else {}
        logger.warning(
            "[RoutePlan] Multi-root planning failed => fallback to single root: %s | path=%s",
            selected_card.name, path_str,
        )
        return step, None, [selected_card], (rps if rps else None), exec_meta

    async def get_best_agent_by_broadcast(
        self,
        query: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        propagated_history: Optional[dict] = None,
    ) -> tuple[Optional[PlannerStep], Optional[list[dict]], dict]:
        """Broadcast capability check and pick the single best agent.

        Minimal version of get_plan_by_broadcast: always returns a single-root
        decision, never enters multi-root task planning.
        """
        logger.info("[RoutePlan] ========== Simple Route Planning Start ==========")

        history_payload = {}
        if os.getenv('Enable_History', "enable") == "enable":
            history_payload = await self.planner_agent.get_history_payload(
                user_id=user_id,
                run_id=run_id,
                propagated_history=propagated_history,
            )

        capable_agents = await self.broadcast_capability_check(
            query,
            user_id,
            run_id,
            trace_id,
            propagated_history=history_payload,
        )

        if not capable_agents:
            logger.info("[RoutePlan] Simple route: no capable agent found")
            return None, None, {}

        selected_card, selected_resp = capable_agents[0]
        self.agent_cards = [selected_card]

        step = PlannerStep(original_query=query, agent=selected_card.name)

        rps = getattr(selected_resp, "route_paths", None) or []
        if not rps and selected_resp.route_path:
            rps = [{"path": selected_resp.route_path, "confidence": selected_resp.confidence}]

        exec_meta = {
            "execution_strategy": "single",
            PROPAGATED_HISTORY_KEY: history_payload,
            ROUTING_AGENT_POOL_KEY: _build_routing_agent_pool_from_capable(capable_agents),
            ROUTING_SELECTED_ROOT_KEY: selected_card.name,
        }
        if isinstance(selected_resp.execution_hint, dict) and selected_resp.execution_hint:
            exec_meta[SG_EXECUTION_HINT_KEY] = selected_resp.execution_hint

        path_str = (
            " -> ".join(selected_resp.route_path)
            if selected_resp.route_path
            else selected_card.name
        )
        logger.info(
            "[RoutePlan] ========== Simple Route Result ==========\n"
            "  Selected: %s | can_handle=%s | confidence=%.2f | path=%s\n"
            "  routing_agent_pool size=%d\n"
            "==========================================",
            selected_card.name,
            selected_resp.can_handle,
            selected_resp.confidence,
            path_str,
            len(exec_meta.get(ROUTING_AGENT_POOL_KEY) or []),
        )

        return step, (rps if rps else None), exec_meta

    async def _pick_best_root_for_fallback(
        self,
        query: str,
        handle_candidates: list[tuple[AgentCard, CapabilityCheckResponse]],
        trace_id: str = "",
        user_id: str = "",
        run_id: str = "",
    ) -> Optional[tuple[AgentCard, CapabilityCheckResponse]]:
        """Use LLM to choose the best root agent when fallback from multi-root planning.
        Reference: sg orchestrator _pick_best_handle_agent_with_llm.
        """
        if len(handle_candidates) <= 1:
            return handle_candidates[0] if handle_candidates else None
        agents_desc = "\n".join([
            f"- name: {card.name}, description: {card.description}, "
            f"can_handle: {resp.can_handle}, can_contribute: {resp.can_contribute}, "
            f"contribution: {resp.contribution}, confidence: {resp.confidence}, reason: {resp.reason}"
            for card, resp in handle_candidates
        ])
        prompt = SINGLE_ROOT_FALLBACK_RANK_PROMPT.format(agents=agents_desc, query=query)
        handle_names = {c.name for c, _ in handle_candidates}
        try:
            with langfuse.start_as_current_span(
                name="routing-single-root-fallback-rank",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "handle_agents": list(handle_names)},
                )
                rank_tool = StructuredTool(
                    name="rank_agent",
                    description="Rank the best root agent to handle the query.",
                    args_schema=AgentRankToolResult,
                    func=None,
                    coroutine=None,
                )
                data = await invoke_llm_with_tool(
                    llm=self.planner_agent.llm,
                    tool=rank_tool,
                    messages=[HumanMessage(content=prompt)],
                    metadata={"user_id": user_id, "run_id": run_id, "trace_id": trace_id},
                    tool_choice="rank_agent",
                    span_name="routing-single-root-fallback-rank",
                    span_input={"query": query, "handle_agents": list(handle_names)},
                )
                if not isinstance(data, dict):
                    raise ValueError("rank_agent tool call returned no structured args")
                best_agent = str(data.get("best_agent") or "").strip()
                confidence = float(data.get("confidence", 0.0) or 0.0)
                reason = str(data.get("reason") or "").strip()
                span.update_trace(
                    output={"best_agent": best_agent, "confidence": confidence, "reason": reason},
                )
            if best_agent in handle_names:
                match = next((cr for c, r in handle_candidates if c.name == best_agent), None)
                if match:
                    logger.info(
                        "[RoutePlan] LLM selected best root for fallback: %s confidence=%.3f reason=%s",
                        best_agent, confidence, reason,
                    )
                    return match
            logger.warning(
                "[RoutePlan] LLM selected invalid best root=%s among=%s",
                best_agent, list(handle_names),
            )
        except Exception as e:
            logger.warning("[RoutePlan] Single-root fallback LLM rank failed: %s", e)
        return None

    async def _plan_cross_root_tasks(
        self,
        query: str,
        capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]],
        history_text: str = "",
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        on_plan_validated: Optional[Callable[[MultiRootTaskPlan], Awaitable[None]]] = None,
    ) -> Optional[MultiRootTaskPlan]:
        """Use LLM to decompose a user query into sub-tasks across multiple Root Orchestrators."""
        agents_desc = "\n".join([
            f"- name: {card.name}, description: {card.description}, "
            f"can_handle: {resp.can_handle}, can_contribute: {resp.can_contribute}, "
            f"contribution: {resp.contribution}, confidence: {resp.confidence}, reason: {resp.reason}"
            for card, resp in capable_agents
        ])

        prompt_text = MULTI_ROOT_TASK_PLAN_PROMPT.format(
            agents=agents_desc,
            history=history_text or "（无）",
            query=query,
        )
        candidate_names = {card.name for card, _ in capable_agents}
        # Default off: extra LLM votes before planning rarely change the final plan (planner wins after retry).
        # Set ENABLE_SPLIT_NECESSITY_JUDGE=true to compare needs_split against a majority vote.
        if os.getenv("ENABLE_SPLIT_NECESSITY_JUDGE", "").strip().lower() in ("true", "1", "yes"):
            expected_split = await self._judge_split_necessity_root(
                query,
                capable_agents,
                history_text=history_text,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        else:
            expected_split = None
        feedback = ""

        for attempt in range(2):
            try:
                final_prompt = prompt_text
                if feedback:
                    final_prompt += (
                        "\n\n上一次规划未通过校验，请修复后重试。"
                        f"\n校验反馈：{feedback}\n"
                        "请重新调用 `plan_multi_root` 工具输出新的规划结果。"
                    )

                plan_tool = StructuredTool(
                    name="plan_multi_root",
                    description="Decompose the user query into sub-tasks across multiple root orchestrators.",
                    args_schema=MultiRootTaskPlan,
                    func=None,
                    coroutine=None,
                )

                with langfuse.start_as_current_span(
                    name="routing-multiroot-plan-attempt",
                    trace_context={"trace_id": trace_id} if trace_id else {},
                ) as span:
                    span.update_trace(
                        user_id=user_id,
                        session_id=run_id,
                        input={"query": query, "attempt": attempt + 1, "candidate_count": len(capable_agents)},
                    )
                    plan_data = await invoke_llm_with_tool(
                        llm=self.planner_agent.llm,
                        tool=plan_tool,
                        messages=[HumanMessage(content=final_prompt)],
                        metadata={"user_id": user_id, "run_id": run_id, "trace_id": trace_id},
                        tool_choice="plan_multi_root",
                        span_name="routing-multiroot-plan-toolcall",
                        span_input={"query": query, "attempt": attempt + 1},
                    )
                    span.update_trace(output={"attempt": attempt + 1})

                logger.info(f"Multi-root task plan : llm result={plan_data}")

                if not isinstance(plan_data, dict):
                    raise ValueError("multi-root plan: LLM did not call plan_multi_root tool")

                plan = MultiRootTaskPlan(**plan_data)

                valid, reason = self._validate_multi_root_plan(query, plan, candidate_names)
                if valid:
                    if expected_split is not None and bool(plan.needs_split) != bool(expected_split):
                        if attempt == 0:
                            feedback = (
                                f"needs_split mismatch with split-judge: expected={expected_split}, "
                                f"got={plan.needs_split}. 请重新检查是否最小必要拆分。"
                            )
                            logger.warning("Multi-root plan split mismatch on attempt 1/2, retrying.")
                            continue
                        logger.warning(
                            "Multi-root plan accepted with split mismatch after retries: expected=%s got=%s",
                            expected_split,
                            plan.needs_split,
                        )
                    reasoning_full = (plan.reasoning or "").strip()
                    logger.info(
                        "Multi-root task plan validated: tasks=%d needs_split=%s reasoning=%s",
                        len(plan.tasks),
                        plan.needs_split,
                        reasoning_full,
                    )
                    if on_plan_validated:
                        await on_plan_validated(plan)
                    return plan
                feedback = reason
                logger.warning("Multi-root task plan invalid on attempt %d/2: %s", attempt + 1, reason)
            except Exception as e:
                feedback = f"planning/parsing error: {e}"
                logger.error("Multi-root task planning failed on attempt %d/2: %s", attempt + 1, e, exc_info=True)

        return None

    async def dispatch_single_task_to_agent(
        self, task_description: str, agent_card: AgentCard,
        user_id: str, run_id: str, trace_id: str,
        history_owner_agent_id: str = "",
        propagated_history: Optional[dict] = None,
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        prior_task_results: Optional[list[dict]] = None,
        depends_on: Optional[List[int]] = None,
    ) -> str:
        """Dispatch a single sub-task to an agent via A2A streaming and collect the full response."""
        prior = list(prior_task_results or [])
        dep_list = list(depends_on or [])
        if prior:
            user_text, resolve_source, _, rmeta = await routing_resolve_task_query_for_multi_root(
                self.llm,
                task_description,
                dep_list,
                prior,
            )
            logger.info(
                "[RoutePlan] multi-root dispatch query | agent=%s source=%s reason=%s original=%s resolved=%s",
                agent_card.name,
                resolve_source,
                (rmeta or {}).get("reason", ""),
                _routing_truncate_for_log(task_description, 180),
                _routing_truncate_for_log(user_text, 260),
            )
        else:
            user_text = task_description
        md: dict[str, Any] = {
            'user_id': user_id,
            'run_id': run_id,
            'trace_id': trace_id,
            PROPAGATED_HISTORY_KEY: propagated_history or {},
            'history_owner_agent_id': history_owner_agent_id,
            'history_write_mode': 'single_writer_v1',
            'skip_history_write': True,
        }
        if prior:
            md['prior_task_results'] = prior
        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [{'type': 'text', 'text': user_text}],
                'messageId': uuid4().hex,
            },
            'metadata': md,
        }
        dispatch_timeout = float(os.getenv("MULTI_ROOT_DISPATCH_TIMEOUT", "120"))
        try:
            async with httpx.AsyncClient(timeout=dispatch_timeout) as httpx_client:
                client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                parts: List[str] = []
                answer_parts: List[str] = []
                final_answer_text = ""
                async for chunk in client.send_message_streaming(streaming_request):
                    text = self.get_response_text(chunk)
                    if text:
                        if self.is_progress_frame(text):
                            if progress_callback is not None:
                                await progress_callback(text)
                            continue
                        if self.is_answer_frame(text):
                            data = self.parse_answer_frame(text) or {}
                            payload = data.get("payload") or {}
                            event_name = str(data.get("event") or "").strip()
                            answer_text = str(payload.get("text") or "")
                            if event_name == "final_answer_chunk":
                                if answer_text:
                                    answer_parts.append(answer_text)
                            elif event_name == "final_answer":
                                final_answer_text = answer_text.strip()
                            continue
                        if self.is_internal_dac_frame(text):
                            continue
                        parts.append(text)
                return final_answer_text or "".join(answer_parts).strip() or "".join(parts).strip()
        except Exception as e:
            logger.error(f"Multi-root dispatch failed for agent {agent_card.name}: {e}")
            return f"[Error: {agent_card.name} 未能完成任务 - {e}]"

    async def execute_multi_root_plan(
        self, query: str, plan: MultiRootTaskPlan,
        user_id: str, run_id: str, trace_id: str,
        history_owner_agent_id: str = "",
        propagated_history: Optional[dict] = None,
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """Execute a multi-root task plan: dispatch sub-tasks (respecting dependencies) and aggregate."""
        task_results: dict[int, str] = {}
        tasks_by_id = {t.id: t for t in plan.tasks}

        # Group tasks by dependency level for staged execution
        remaining = set(tasks_by_id.keys())
        while remaining:
            ready = [tid for tid in remaining if all(d in task_results for d in tasks_by_id[tid].depends_on)]
            if not ready:
                logger.error("Multi-root plan: circular dependency detected, breaking")
                break

            dispatch_coros = []
            for tid in ready:
                task_def = tasks_by_id[tid]
                agent_card = await self.find_agent(task_def.agent)
                if agent_card is None:
                    logger.warning(f"Multi-root plan: agent '{task_def.agent}' not found, skipping task {tid}")
                    task_results[tid] = f"[Agent '{task_def.agent}' 不可用]"
                    continue
                prior_payload = self._prior_task_payloads_for_multi_root(
                    task_def, tasks_by_id, task_results, run_id, trace_id
                )
                dispatch_coros.append((tid, self.dispatch_single_task_to_agent(
                    task_def.description,
                    agent_card,
                    user_id,
                    run_id,
                    trace_id,
                    history_owner_agent_id,
                    propagated_history,
                    progress_callback,
                    prior_payload,
                    list(task_def.depends_on or []),
                )))

            if dispatch_coros:
                results = await asyncio.gather(*[coro for _, coro in dispatch_coros], return_exceptions=True)
                for (tid, _), result in zip(dispatch_coros, results):
                    if isinstance(result, Exception):
                        task_results[tid] = f"[Error: {result}]"
                    else:
                        task_results[tid] = result
                    logger.info(f"Multi-root plan: task {tid} completed (len={len(task_results[tid])})")

            remaining -= set(ready)

        # Keep exact child raw outputs for history think (no fabricated template).
        ordered_raw_outputs: list[str] = []
        for t in plan.tasks:
            raw = str(task_results.get(t.id, "") or "").strip()
            if raw:
                ordered_raw_outputs.append(raw)
        self._last_multi_root_think = "\n\n================\n\n".join(ordered_raw_outputs).strip()

        return await self._aggregate_multi_root_results(
            query,
            plan,
            task_results,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
            propagated_history=propagated_history,
        )

    async def execute_multi_root_plan_stream(
        self,
        query: str,
        plan: MultiRootTaskPlan,
        user_id: str,
        run_id: str,
        trace_id: str,
        history_owner_agent_id: str = "",
        propagated_history: Optional[dict] = None,
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        progress_agent_id: str = "",
    ) -> AsyncIterable[str]:
        """Execute multi-root plan and stream the final aggregation output."""
        task_results: dict[int, str] = {}
        tasks_by_id = {t.id: t for t in plan.tasks}

        remaining = set(tasks_by_id.keys())
        while remaining:
            ready = [tid for tid in remaining if all(d in task_results for d in tasks_by_id[tid].depends_on)]
            if not ready:
                logger.error("Multi-root plan: circular dependency detected, breaking")
                break

            if progress_callback is not None:
                ready_labels = [
                    f"{tasks_by_id[tid].id}:{tasks_by_id[tid].agent}:{(tasks_by_id[tid].description or '')[:60]}"
                    for tid in ready
                ]
                await progress_callback(self.build_progress_frame(
                    "multi_root_level_started",
                    message=f"RoutingAgent starting dependency level with tasks: {', '.join(ready_labels)}",
                    status="running",
                    run_id=run_id,
                    user_id=user_id,
                    agent_id=progress_agent_id or self.agent_name,
                    extra={"task_ids": ready, "task_count": len(ready)},
                ))

            dispatch_coros = []
            for tid in ready:
                task_def = tasks_by_id[tid]
                agent_card = await self.find_agent(task_def.agent)
                if agent_card is None:
                    logger.warning(f"Multi-root plan: agent '{task_def.agent}' not found, skipping task {tid}")
                    task_results[tid] = f"[Agent '{task_def.agent}' 不可用]"
                    continue
                prior_payload = self._prior_task_payloads_for_multi_root(
                    task_def, tasks_by_id, task_results, run_id, trace_id
                )
                dispatch_coros.append((tid, self.dispatch_single_task_to_agent(
                    task_def.description,
                    agent_card,
                    user_id,
                    run_id,
                    trace_id,
                    history_owner_agent_id,
                    propagated_history,
                    progress_callback,
                    prior_payload,
                    list(task_def.depends_on or []),
                )))

            if dispatch_coros:
                results = await asyncio.gather(*[coro for _, coro in dispatch_coros], return_exceptions=True)
                for (tid, _), result in zip(dispatch_coros, results):
                    if isinstance(result, Exception):
                        task_results[tid] = f"[Error: {result}]"
                        task_status = "fail"
                    else:
                        task_results[tid] = result
                        task_status = "done"
                    logger.info(f"Multi-root plan: task {tid} completed (len={len(task_results[tid])})")
                    if progress_callback is not None:
                        await progress_callback(self.build_progress_frame(
                            "multi_root_task_finished",
                            message=(
                                f"RoutingAgent observed task {tid} finished by {tasks_by_id[tid].agent}: "
                                f"{tasks_by_id[tid].description}"
                            ),
                            status=task_status,
                            run_id=run_id,
                            user_id=user_id,
                            agent_id=progress_agent_id or self.agent_name,
                            task_id=tid,
                        ))

            remaining -= set(ready)

        ordered_raw_outputs: list[str] = []
        for t in plan.tasks:
            raw = str(task_results.get(t.id, "") or "").strip()
            if raw:
                ordered_raw_outputs.append(raw)
        self._last_multi_root_think = "\n\n================\n\n".join(ordered_raw_outputs).strip()

        async for chunk in self._aggregate_multi_root_results_stream(
            query,
            plan,
            task_results,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
            propagated_history=propagated_history,
        ):
            if chunk:
                yield chunk

    async def _aggregate_multi_root_results(
        self,
        query: str,
        plan: MultiRootTaskPlan,
        task_results: dict[int, str],
        propagated_history: Optional[dict] = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> str:
        """Use LLM to aggregate results from multiple root agents into a coherent answer."""
        results_text = "\n\n".join([
            f"### 子任务 {t.id}: {t.description}\n**执行专家**: {t.agent}\n**结果**:\n{task_results.get(t.id, '[无结果]')}"
            for t in plan.tasks
        ])

        prompt_text = MULTI_ROOT_AGGREGATE_PROMPT.format(
            query=query,
            history=history_text_from_payload(propagated_history) or "（无）",
            results=results_text,
        )

        try:
            with langfuse.start_as_current_span(
                name="routing-multiroot-aggregate",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "task_count": len(plan.tasks)},
                )
                response = await self.planner_agent.llm.ainvoke(
                    [HumanMessage(content=prompt_text)],
                    config={"callbacks": [langfuse_handler]},
                )
                span.update_trace(output={"task_count": len(plan.tasks)})
            return response.content.strip()
        except Exception as e:
            logger.error(f"Multi-root aggregation failed: {e}")
            return f"各领域专家的回答:\n\n{results_text}"

    async def _aggregate_multi_root_results_stream(
        self,
        query: str,
        plan: MultiRootTaskPlan,
        task_results: dict[int, str],
        propagated_history: Optional[dict] = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> AsyncIterable[str]:
        """Stream LLM aggregation output for multi-root execution."""
        results_text = "\n\n".join([
            f"### 子任务 {t.id}: {t.description}\n**执行专家**: {t.agent}\n**结果**:\n{task_results.get(t.id, '[无结果]')}"
            for t in plan.tasks
        ])
        prompt_text = MULTI_ROOT_AGGREGATE_PROMPT.format(
            query=query,
            history=history_text_from_payload(propagated_history) or "（无）",
            results=results_text,
        )

        try:
            with langfuse.start_as_current_span(
                name="routing-multiroot-aggregate",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "task_count": len(plan.tasks)},
                )
                yielded = False
                async for chunk in self.planner_agent.llm.astream(
                    [HumanMessage(content=prompt_text)],
                    config={"callbacks": [langfuse_handler]},
                ):
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        yielded = True
                        yield content
                if not yielded:
                    response = await self.planner_agent.llm.ainvoke(
                        [HumanMessage(content=prompt_text)],
                        config={"callbacks": [langfuse_handler]},
                    )
                    body = (response.content or "").strip()
                    if body:
                        yield body
                span.update_trace(output={"task_count": len(plan.tasks)})
        except Exception as e:
            logger.error(f"Multi-root aggregation stream failed: {e}")
            yield f"各领域专家的回答:\n\n{results_text}"

    # ==================== End Broadcast Routing Methods ====================

class RoutingAgentExecutor(AgentExecutor):
    """
    A Routing Agent executor call PlannerAgent to get agents, than call agents.
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_services_url: str = None,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ):
        self.agent = RoutingAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=stream,
            temperature=temperature,
            data_services_url=data_services_url
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._progress_context: Dict[str, str] = {"run_id": "", "user_id": "", "agent_id": ""}
        self._history_progress_frames: List[str] = []

    @staticmethod
    def _history_async_enabled() -> bool:
        # Default to async history persistence so streamed UX can finish immediately.
        return os.getenv("ROUTING_HISTORY_ASYNC", "true").strip().lower() not in ("false", "0", "no")

    @staticmethod
    def _spawn_background(coro: "asyncio.Future[Any] | asyncio.coroutines") -> None:
        task = asyncio.create_task(coro)

        def _on_done(t: asyncio.Task) -> None:
            try:
                t.result()
            except asyncio.CancelledError:
                logger.warning("[HistoryFlow] background task cancelled")
            except Exception as e:
                logger.error("[HistoryFlow] background task failed: %s", e)

        task.add_done_callback(_on_done)

    @staticmethod
    def _progress_stream_enabled() -> bool:
        return os.getenv("ENABLE_ROUTING_PROGRESS_STREAM", "true").strip().lower() not in ("false", "0", "no")

    @staticmethod
    def _normalize_progress_frame_text(text: str) -> str:
        if not text:
            return ""
        return text if text.endswith("\n") else (text + "\n")

    def _append_history_progress_frame(self, text: str) -> None:
        if not text:
            return
        if not self.agent.is_progress_frame(text):
            return
        self._history_progress_frames.append(self._normalize_progress_frame_text(text))

    def _build_history_progress_think(self) -> str:
        return "".join(self._history_progress_frames).strip()

    async def _emit_progress_text(self, updater: TaskUpdater, text: str) -> None:
        if not text:
            return
        self._append_history_progress_frame(text)
        if not self._progress_stream_enabled():
            return
        await updater.add_artifact(
            [TextPart(text=text)],
            name=f'{self.agent.agent_name}-result',
        )

    async def _emit_progress(
        self,
        updater: TaskUpdater,
        *,
        event: str,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        frame = self.agent.build_progress_frame(
            event,
            message=message,
            status=status,
            run_id=self._progress_context.get("run_id", ""),
            user_id=self._progress_context.get("user_id", ""),
            agent_id=self._progress_context.get("agent_id", "") or self.agent.agent_name,
            task_id=task_id,
            extra=extra,
        )
        await self._emit_progress_text(updater, frame)

    async def _emit_answer(
        self,
        updater: TaskUpdater,
        *,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        status: str = "done",
        task_id: Optional[int] = None,
    ) -> None:
        await updater.add_artifact(
            [TextPart(text=self.agent.build_answer_frame(
                event,
                payload=payload,
                status=status,
                run_id=self._progress_context.get("run_id", ""),
                user_id=self._progress_context.get("user_id", ""),
                agent_id=self._progress_context.get("agent_id", "") or self.agent.agent_name,
                task_id=task_id,
                layer="routing",
            ))],
            name=f'{self.agent.agent_name}-result',
        )

    async def _summarize_single_root_for_history(
        self,
        *,
        query: str,
        agent_name: str,
        raw_stream_text: str,
        user_id: str,
        run_id: str,
        trace_id: str,
        propagated_history: Optional[dict] = None,
    ) -> str:
        """Generate routing-level final answer for history content.

        The full upstream raw stream is kept in `think`; this method returns a
        concise routing-summary answer for `content`.
        """
        raw = str(raw_stream_text or "").strip()
        if not raw:
            return ""

        results_text = (
            f"### 子任务 1: {query}\n"
            f"**执行专家**: {agent_name}\n"
            f"**结果**:\n{raw}"
        )
        prompt_text = MULTI_ROOT_AGGREGATE_PROMPT.format(
            query=query,
            history=history_text_from_payload(propagated_history) or "（无）",
            results=results_text,
        )

        try:
            with langfuse.start_as_current_span(
                name="routing-single-root-history-aggregate",
                trace_context={"trace_id": trace_id} if trace_id else {},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query, "target_agent": agent_name},
                )
                response = await self.agent.planner_agent.llm.ainvoke(
                    [HumanMessage(content=prompt_text)],
                    config={"callbacks": [langfuse_handler]},
                )
                summary = (response.content or "").strip()
                span.update_trace(output={"summary_chars": len(summary)})
                return summary or raw
        except Exception as e:
            logger.warning("[HistoryFlow] single-root history summary failed, fallback to raw content: %s", e)
            return raw

    async def _persist_history_from_routing_owner(
        self,
        *,
        user_id: str,
        run_id: str,
        query: str,
        final_answer: str,
        history_owner_agent_id: str,
        think: str = "",
    ) -> None:
        """Persist final conversation once, by routing owner only."""
        enable_history = os.getenv('Enable_History', "enable")
        logger.info(
            "[HistoryFlow] persist-check\n"
            "  step=final_history_persist\n"
            "  run_id=%s\n"
            "  user_id=%s\n"
            "  owner=%s\n"
            "  self=%s\n"
            "  enable_history=%s\n"
            "  query_len=%d\n"
            "  answer_len=%d",
            run_id,
            user_id,
            history_owner_agent_id,
            self.agent.agent_name,
            enable_history,
            len(query or ""),
            len(final_answer or ""),
        )
        if enable_history != "enable":
            logger.info("[HistoryFlow] persist-skip reason=enable_history_disabled run_id=%s", run_id)
            return
        if history_owner_agent_id != self.agent.agent_name:
            logger.info(
                "[HistoryFlow] persist-skip reason=not_owner owner=%s self=%s run_id=%s",
                history_owner_agent_id,
                self.agent.agent_name,
                run_id,
            )
            return
        if not user_id or not run_id:
            logger.warning(
                "[HistoryFlow] persist-skip reason=missing_user_or_run user_id=%s run_id=%s",
                user_id,
                run_id,
            )
            return

        create_request = CreateHistoryRequest(
            user_id=user_id,
            agent_id=self.agent.agent_name,
            run_id=run_id,
            messages=[
                HistoryMessage(role="user", content=query or ""),
                HistoryMessage(role="assistant", content=final_answer or "", think=think or None),
            ],
        )
        try:
            ds_client = DataServicesClient(base_url=self.agent.data_services_url, timeout=600)
            async with ds_client.session_context() as client:
                await client.create_history(create_request)
            logger.info(
                "[HistoryFlow] persist-success owner=%s run_id=%s answer_len=%d",
                history_owner_agent_id,
                run_id,
                len(final_answer or ""),
            )
        except Exception as e:
            logger.error("[History] Persist final conversation at routing failed: %s", e)

    async def _persist_single_root_history_flow(
        self,
        *,
        query: str,
        final_answer: str,
        think: str,
        user_id: str,
        run_id: str,
        history_owner_agent_id: str,
    ) -> None:
        """Persist single-root history with final answer + progress think."""
        await self._persist_history_from_routing_owner(
            user_id=user_id,
            run_id=run_id,
            query=query,
            final_answer=final_answer,
            history_owner_agent_id=history_owner_agent_id,
            # Keep ordered DAC_PROGRESS frames in think for history inspection.
            think=think,
        )

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        if not context.message:
            raise Exception('No message provided')

        metadata = context.metadata or {}
        logger.info(f"=====user request metadata is {metadata}.")

        user_id = metadata.get('user_id') or str(uuid4())

        run_id = metadata.get('run_id') or str(uuid4())
        history_owner_agent_id = metadata.get('history_owner_agent_id') or self.agent.agent_name
        propagated_history = parse_propagated_history(metadata.get(PROPAGATED_HISTORY_KEY))
        if os.getenv('Enable_History', "enable") == "enable":
            propagated_history = await self.agent.planner_agent.get_history_payload(
                user_id=user_id,
                run_id=run_id,
                propagated_history=propagated_history,
            )
        self._progress_context = {
            "run_id": run_id,
            "user_id": user_id,
            "agent_id": self.agent.agent_name,
        }
        logger.info(
            "[HistoryFlow] owner-resolved\n"
            "  run_id=%s\n"
            "  user_id=%s\n"
            "  owner=%s\n"
            "  self=%s\n"
            "  source=%s",
            run_id,
            user_id,
            history_owner_agent_id,
            self.agent.agent_name,
            "metadata" if metadata.get("history_owner_agent_id") else "default=self",
        )

        request_id = str(uuid4())

        trace_id = Langfuse.create_trace_id(seed=request_id)

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Determine routing mode: "broadcast" (default, new) or "vector" (legacy)
        routing_mode = os.getenv("ROUTING_MODE", "simple").strip().lower()
        logger.info(f"===== RoutingAgentExecutor, routing_mode={routing_mode}")

        step = None
        multi_plan = None
        route_paths: Optional[list[dict]] = None
        execution_meta: dict = {}
        self._history_progress_frames = []

        if routing_mode == "simple":
            # ---- Simple Mode: pick the single best agent, forward original query ----
            # Controlled by env ROUTING_MODE=simple.
            # No multi-root task planning — Routing Agent only selects, does not decompose.
            logger.info("===== RoutingAgentExecutor, using SIMPLE routing mode")

            for attempt in range(self.max_retries):
                step, route_paths, execution_meta = await self.agent.get_best_agent_by_broadcast(
                    query,
                    user_id,
                    run_id,
                    trace_id,
                    propagated_history=propagated_history,
                )
                logger.info(
                    "===== RoutingAgentExecutor (simple), attempt %d, step=%s",
                    attempt + 1, step,
                )

                if step is not None and step.agent and step.agent != "":
                    break

                if attempt < self.max_retries - 1:
                    logger.warning(
                        "===== Simple routing: no capable agent found, retrying "
                        "(%d/%d)...",
                        attempt + 1, self.max_retries,
                    )
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

        elif routing_mode == "broadcast":
            # ---- Broadcast Mode: ask ALL agents, supports single-root fast path + multi-root task plan ----
            logger.info("===== RoutingAgentExecutor, using BROADCAST routing mode")

            async def _on_multi_root_plan_validated(plan: MultiRootTaskPlan) -> None:
                reasoning_full = (plan.reasoning or "").strip()
                tasks_snapshot = [
                    {
                        "id": int(t.id),
                        "description": (t.description or "").strip(),
                        "agent": str(t.agent or ""),
                        "depends_on": [int(x) for x in (t.depends_on or [])],
                    }
                    for t in plan.tasks
                ]
                split_zh = "是" if plan.needs_split else "否"
                body = reasoning_full.replace("\r\n", "\n")
                headline = (
                    f"多root计划已验证：任务数={len(plan.tasks)} 需要拆分={split_zh}；推理过程=\n\n"
                    f"{body}"
                )
                await self._emit_progress(
                    updater,
                    event="multi_root_plan_reason",
                    message=headline,
                    status="done",
                    extra={
                        "task_count": len(plan.tasks),
                        "needs_split": bool(plan.needs_split),
                        "reasoning": reasoning_full,
                        "requirements": list(plan.requirements or []),
                        "tasks": tasks_snapshot,
                    },
                )

            for attempt in range(self.max_retries):
                step, multi_plan, _, route_paths, execution_meta = await self.agent.get_plan_by_broadcast(
                    query,
                    user_id,
                    run_id,
                    trace_id,
                    propagated_history=propagated_history,
                    on_multi_root_plan_validated=_on_multi_root_plan_validated,
                )
                rps_count = len(route_paths) if route_paths else 0
                logger.info(
                    "===== RoutingAgentExecutor (broadcast), attempt %d, step=%s, multi_plan tasks=%d, route_paths=%d",
                    attempt + 1, step, len(multi_plan.tasks) if multi_plan else 0, rps_count,
                )

                if multi_plan and multi_plan.tasks:
                    break
                if step is not None and step.agent and step.agent != "":
                    break

                if attempt < self.max_retries - 1:
                    logger.warning(f"===== Broadcast routing: no capable agent found, retrying ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

            if multi_plan and multi_plan.tasks:
                await self._emit_progress(
                    updater,
                    event="routing_plan_ready",
                    message=f"Routing produced {len(multi_plan.tasks)} root task(s) for cross-root aggregation",
                    status="done",
                    extra={"mode": "multi_root", "task_count": len(multi_plan.tasks)},
                )
                task_agents = []
                for t in multi_plan.tasks:
                    if t.agent and t.agent not in task_agents:
                        task_agents.append(t.agent)
                root_plans = execution_meta.get("root_plans", []) if execution_meta else []
                root_count = len(root_plans)
                agents_readable = ", ".join(task_agents)
                route_detail = _nonredundant_root_plan_routes_summary(root_plans)
                tasks_extra: list[dict[str, Any]] = []
                task_detail_parts: list[str] = []
                for t in multi_plan.tasks:
                    desc_full = (t.description or "").strip()
                    deps = [int(x) for x in (t.depends_on or [])]
                    tasks_extra.append(
                        {
                            "id": int(t.id),
                            "description": desc_full,
                            "agent": str(t.agent or ""),
                            "depends_on": deps,
                            "why_agent": str(t.why_agent or "").strip(),
                            "covers": list(t.covers or []),
                        }
                    )
                    desc_preview = _routing_truncate_for_log(desc_full, 220)
                    # depends_on: upstream task id(s), same as Task #n; [] means parallel root (no upstream).
                    if deps:
                        dep_hint = "需先完成 " + ", ".join(f"任务#{d}" for d in deps)
                    else:
                        dep_hint = "与其它root任务并行（无上游依赖）"
                    agent_s = str(t.agent or "")
                    task_detail_parts.append(
                        f"Task #{t.id} - {agent_s}\n"
                        f"  depends_on: {deps}  |  {dep_hint}\n"
                        f"  {desc_preview}"
                    )
                tasks_readable = "\n\n".join(task_detail_parts)
                header = (
                    f"Routing final plan: mode=multi_root, tasks={len(multi_plan.tasks)}, "
                    f"agents={agents_readable}"
                )
                if route_detail:
                    header = f"{header}, routes={route_detail}"
                plan_msg = f"{header}\n\nSub-tasks:\n{tasks_readable}"
                await self._emit_progress(
                    updater,
                    event="route_plan_with_capability_check",
                    message=plan_msg,
                    status="done",
                    extra={
                        "mode": "multi_root",
                        "strategy": "multi_root",
                        "task_count": len(multi_plan.tasks),
                        "root_count": root_count,
                        "task_agents": task_agents,
                        "tasks": tasks_extra,
                        "root_plans": root_plans,
                    },
                )
            elif step is not None and step.agent:
                selected_path = " -> ".join((route_paths or [{}])[0].get("path", [])) if route_paths else step.agent
                await self._emit_progress(
                    updater,
                    event="root_selected",
                    message=f"Routing selected root={step.agent} via path {selected_path} (best capability match)",
                    status="done",
                    extra={"mode": "single_root", "route_paths": len(route_paths or [])},
                )

            # Multi-root path: dispatch sub-tasks, aggregate, and return
            if multi_plan and multi_plan.tasks:
                # In multi-root mode, RoutingAgent is the final answer owner for the UI.
                # Child roots only provide source material; RoutingAgent performs the last aggregation pass.
                logger.info(f"===== RoutingAgentExecutor: MULTI-ROOT plan with {len(multi_plan.tasks)} sub-tasks")
                logger.info(
                    "[HistoryFlow] execution-branch strategy=multi_root owner=%s run_id=%s",
                    history_owner_agent_id,
                    run_id,
                )
                aggregated_parts: List[str] = []
                async for chunk in self.agent.execute_multi_root_plan_stream(
                    query,
                    multi_plan,
                    user_id,
                    run_id,
                    trace_id,
                    history_owner_agent_id,
                    propagated_history,
                    lambda text: self._emit_progress_text(updater, text),
                    self.agent.agent_name,
                ):
                    if chunk:
                        if self.agent.is_progress_frame(chunk):
                            await self._emit_progress_text(updater, chunk)
                            continue
                        if self.agent.is_internal_dac_frame(chunk):
                            continue
                        aggregated_parts.append(chunk)
                        await self._emit_answer(
                            updater,
                            event="final_answer_chunk",
                            payload={"text": chunk},
                            status="running",
                        )
                aggregated = "".join(aggregated_parts).strip()
                if aggregated:
                    await self._emit_progress(
                        updater,
                        event="routing_final_answer_ready",
                        message="Routing final answer is ready",
                        status="done",
                        extra={"mode": "multi_root", "answer_chars": len(aggregated)},
                    )
                    await self._emit_answer(
                        updater,
                        event="final_answer",
                        payload={"text": aggregated, "presentation": "text"},
                    )
                await updater.complete(
                    message=new_agent_text_message("", context_id=task.context_id)
                )
                if self._history_async_enabled():
                    self._spawn_background(
                        self._persist_history_from_routing_owner(
                            user_id=user_id,
                            run_id=run_id,
                            query=query,
                            final_answer=aggregated or "",
                            history_owner_agent_id=history_owner_agent_id,
                            think=self._build_history_progress_think(),
                        )
                    )
                else:
                    await self._persist_history_from_routing_owner(
                        user_id=user_id,
                        run_id=run_id,
                        query=query,
                        final_answer=aggregated or "",
                        history_owner_agent_id=history_owner_agent_id,
                        think=self._build_history_progress_think(),
                    )
                return
        else:
            # ---- Vector Mode (default): vector search + LLM planner ----
            logger.info("===== RoutingAgentExecutor, using VECTOR routing mode")
            for attempt in range(self.max_retries):
                step = await self.agent.get_plan(
                    query,
                    user_id,
                    run_id,
                    trace_id,
                    propagated_history=propagated_history,
                )
                logger.info(f"===== RoutingAgentExecutor, attempt {attempt + 1}, step is {step}.")
                
                if step is not None and step.agent and step.agent != "":
                    break
                    
                if attempt < self.max_retries - 1:
                    logger.warning(f"===== Empty step or agent, retrying ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

        # No routable agent: do not fall back to CommonAgent (not deployed); prompt the user instead.
        _no_suitable_agent_text = (
            "当前没有合适的智能体可以处理这个问题。"
            "你可以尝试换一种问法，或补充更多说明后再试。"
        )
        if step is None or (step is not None and (step.agent is None or step.agent == "")):
            logger.info("===== RoutingAgentExecutor, no agent from plan after retries; user prompt instead of fallback.")
            await self._emit_answer(
                updater,
                event="final_answer",
                payload={
                    "text": _no_suitable_agent_text,
                    "presentation": "text",
                },
            )
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )
        else:
            # get agent card with agent name
            agent_card = await self.agent.find_agent(step.agent)

            if agent_card is None:
                logger.info(
                    "===== RoutingAgentExecutor, planned agent not in local registry: %s; user prompt instead of fallback.",
                    step.agent,
                )
                await self._emit_answer(
                    updater,
                    event="final_answer",
                    payload={
                        "text": _no_suitable_agent_text,
                        "presentation": "text",
                    },
                )
                await updater.complete(
                    message=new_agent_text_message(
                        "", context_id=task.context_id
                    )
                )
            else:
                logger.info(
                    "===== RoutingAgentExecutor, found agent: %s.",
                    getattr(agent_card, "name", None) or step.agent,
                )
                rps = route_paths or []
                path_aliases = [e.get("alias", "?") for e in rps[:5]]
                logger.info(
                    "===== RoutingAgentExecutor: sending to %s with route_paths=%d path(s): %s",
                    step.agent, len(rps), ", ".join(path_aliases) if path_aliases else "[]",
                )
                exec_strategy = execution_meta.get("execution_strategy", "single") if execution_meta else "single"
                strategy_human = {
                    "single": "single-root direct handling",
                    "multi_root": "cross-root split and aggregate",
                }.get(exec_strategy, exec_strategy)
                best_path = " -> ".join((rps[0].get("path", []) if rps else [])) if rps else step.agent
                await self._emit_progress(
                    updater,
                    event="route_plan_with_capability_check",
                    message=(
                        f"Routing final plan: mode=single_root, root={step.agent}, strategy={exec_strategy}, "
                        f"paths={len(rps)}, best_path={best_path}"
                    ),
                    status="done",
                    extra={
                        "mode": "single_root",
                        "strategy": exec_strategy,
                        "selected_root": step.agent,
                        "route_paths": len(rps),
                        "best_path": best_path,
                    },
                )
                await self._emit_progress(
                    updater,
                    event="root_forward_started",
                    message=f"Routing forwarding request to root={step.agent}, strategy={strategy_human}",
                    status="running",
                    extra={"route_paths": len(rps), "strategy": exec_strategy, "strategy_human": strategy_human},
                )
                logger.info(
                    "[HistoryFlow] execution-branch strategy=single_root_forward\n"
                    "  run_id=%s\n"
                    "  owner=%s\n"
                    "  target_agent=%s\n"
                    "  route_paths=%d\n"
                    "  history_write_mode=%s\n"
                    "  child_skip_history_write=%s",
                    run_id,
                    history_owner_agent_id,
                    step.agent,
                    len(rps),
                    "single_writer_v1",
                    True,
                )

                send_message_payload = {
                    'message': {
                        'role': 'user',
                        'parts': [
                            {'type': 'text', 'text': query}
                        ],
                        'messageId': uuid4().hex,
                    },
                    'metadata': {
                        'user_id': user_id,
                        'run_id': run_id,
                        'trace_id': trace_id,
                        PROPAGATED_HISTORY_KEY: propagated_history,
                        'route_paths': route_paths if route_paths else [],
                        'execution_strategy': exec_strategy,
                        'history_owner_agent_id': history_owner_agent_id,
                        'history_write_mode': 'single_writer_v1',
                        'skip_history_write': True,
                    },
                }
                routing_pool = (execution_meta or {}).get(ROUTING_AGENT_POOL_KEY)
                if routing_pool:
                    send_message_payload['metadata'][ROUTING_AGENT_POOL_KEY] = routing_pool
                    execution_hint = (execution_meta or {}).get(SG_EXECUTION_HINT_KEY)
                    skip_eligible = True
                    if isinstance(execution_hint, dict) and execution_hint.get("missing_requirements"):
                        skip_eligible = False
                    send_message_payload['metadata'][ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY] = skip_eligible
                    selected_root = (execution_meta or {}).get(ROUTING_SELECTED_ROOT_KEY)
                    if selected_root:
                        send_message_payload['metadata'][ROUTING_SELECTED_ROOT_KEY] = selected_root
                    logger.info(
                        "Routing forward: routing_agent_pool size=%d skip_broadcast_eligible=%s root=%s",
                        len(routing_pool),
                        skip_eligible,
                        selected_root or step.agent,
                    )
                execution_hint = (execution_meta or {}).get(SG_EXECUTION_HINT_KEY)
                if isinstance(execution_hint, dict) and execution_hint:
                    send_message_payload["metadata"][SG_EXECUTION_HINT_KEY] = execution_hint
                    logger.info(
                        "Routing forward: opaque SG execution hint | target=%s "
                        "selected_members=%s",
                        execution_hint.get("agent_name") or step.agent,
                        (execution_hint.get("selected_members") or [])[:10],
                    )

                # build a2a client from agent_card.url
                async with httpx.AsyncClient() as httpx_client:
                    client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                    try:
                        streaming_request = SendStreamingMessageRequest(
                            id=uuid4().hex,
                            params=MessageSendParams(**send_message_payload)
                        )
                        stream_response = client.send_message_streaming(streaming_request)
                        raw_answer_parts: List[str] = []
                        streamed_answer_parts: List[str] = []
                        saw_final_answer_frame = False
                        final_answer_for_history = ""
                        async for chunk in stream_response:
                            result = self.agent.get_response_text(chunk)
                            if result:
                                if self.agent.is_progress_frame(result):
                                    await self._emit_progress_text(updater, result)
                                    continue
                                if self.agent.is_answer_frame(result):
                                    # In single-root mode, the root SG owns the business summary.
                                    # RoutingAgent only republishes that answer in its own DAC_ANSWER envelope.
                                    data = self.agent.parse_answer_frame(result) or {}
                                    event_name = str(data.get("event") or "").strip()
                                    payload = data.get("payload") or {}
                                    status = str(data.get("status") or "done")
                                    text = str(payload.get("text") or "")
                                    if event_name == "final_answer_chunk":
                                        if text:
                                            streamed_answer_parts.append(text)
                                            await self._emit_answer(
                                                updater,
                                                event="final_answer_chunk",
                                                payload={"text": text},
                                                status="running" if status == "running" else "done",
                                            )
                                    elif event_name == "final_answer":
                                        saw_final_answer_frame = True
                                        final_text = str(payload.get("text") or "").strip()
                                        if final_text:
                                            final_answer_for_history = final_text
                                            await self._emit_progress(
                                                updater,
                                                event="routing_final_answer_ready",
                                                message="Routing final answer is ready",
                                                status="done",
                                                extra={"mode": "single_root", "answer_chars": len(final_text)},
                                            )
                                            await self._emit_answer(
                                                updater,
                                                event="final_answer",
                                                payload={"text": final_text, "presentation": str(payload.get("presentation") or "text")},
                                                status="done",
                                            )
                                        else:
                                            fallback_text = "".join(streamed_answer_parts).strip()
                                            if fallback_text:
                                                final_answer_for_history = fallback_text
                                                await self._emit_progress(
                                                    updater,
                                                    event="routing_final_answer_ready",
                                                    message="Routing final answer is ready",
                                                    status="done",
                                                    extra={"mode": "single_root", "answer_chars": len(fallback_text)},
                                                )
                                                await self._emit_answer(
                                                    updater,
                                                    event="final_answer",
                                                    payload={"text": fallback_text, "presentation": "text"},
                                                    status="done",
                                                )
                                    continue
                                if self.agent.is_internal_dac_frame(result):
                                    continue
                                raw_answer_parts.append(result)
                        raw_stream_think = "".join(raw_answer_parts).strip()
                        streamed_answer = "".join(streamed_answer_parts).strip()
                        if not saw_final_answer_frame:
                            fallback_text = streamed_answer or raw_stream_think
                            if fallback_text:
                                final_answer_for_history = fallback_text
                                await self._emit_progress(
                                    updater,
                                    event="routing_final_answer_ready",
                                    message="Routing final answer is ready",
                                    status="done",
                                    extra={"mode": "single_root", "answer_chars": len(fallback_text)},
                                )
                                await self._emit_answer(
                                    updater,
                                    event="final_answer",
                                    payload={"text": fallback_text, "presentation": "text"},
                                    status="done",
                                )
                        await updater.complete(
                            message=new_agent_text_message(
                                "", context_id=task.context_id
                            )
                        )
                        if self._history_async_enabled():
                            self._spawn_background(
                                self._persist_single_root_history_flow(
                                    query=query,
                                    final_answer=final_answer_for_history,
                                    think=self._build_history_progress_think(),
                                    user_id=user_id,
                                    run_id=run_id,
                                    history_owner_agent_id=history_owner_agent_id,
                                )
                            )
                        else:
                            await self._persist_single_root_history_flow(
                                query=query,
                                final_answer=final_answer_for_history,
                                think=self._build_history_progress_think(),
                                user_id=user_id,
                                run_id=run_id,
                                history_owner_agent_id=history_owner_agent_id,
                            )
                    except Exception as e:
                        logger.error(f"An error occurred: {e}")

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')



@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=10100)
@click.option('--agent-card', 'agent_card', default='/app/agent_card/routing_agent.json')
@click.option('--redis-host', 'redis_host',default='localhost', help='Redis server host')
@click.option('--redis-port', 'redis_port', default=6379, type=int)
@click.option('--redis-db', 'redis_db', default=0, type=int)
@click.option('--password', 'password', default=None)
@click.option('--provider', 'provider', default='openai_compatible')
@click.option('--api-key', 'api_key', default=None, help='API key for the LLM provider')
@click.option('--base-url', 'base_url', default='https://dashscope.aliyuncs.com/compatible-mode/v1')
@click.option('--model', 'model', default='qwen2.5-72b-instruct')
@click.option('--temperature', 'temperature', default=0.01, type=float, help='Temperature for LLM generation')
@click.option('--heartbeat-interval', 'heartbeat_interval',default=10, type=int, help='Heartbeat interval in seconds')
def main(host, port, agent_card, redis_host, redis_port, redis_db, password, provider, api_key, base_url, model, temperature, heartbeat_interval):
    """Starts an Agent server."""

    # reset login config , otherwise there is no time info in the log message.
    logging.basicConfig(
        force=True,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    try:
        if not agent_card:
            raise ValueError('Agent card is required')
        with Path.open(agent_card) as file:
            data = json.load(file)
        agent_card = AgentCard(**data)
        agent_host = os.getenv('Agent_Host')
        agent_port = os.getenv('Agent_Port',"19999")
        agent_card.url = f'http://{agent_host}:{agent_port}'

        logger.info(f"agent_card is: {agent_card}")
        logger.info(
            "Runtime build info: hostname=%s, pod_name=%s, app_version=%s, image=%s, image_tag=%s, git_sha=%s",
            os.getenv("HOSTNAME", "unknown"),
            os.getenv("POD_NAME", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
        )

        #dataservices
        data_services_url = os.getenv('DataServicesURL',"http://data-services.dac.svc.cluster.local:8000")
        
        max_retries = int(os.getenv('max_retries','2'))

        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)
        request_handler = DefaultRequestHandler(
            agent_executor=RoutingAgentExecutor(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                data_services_url=data_services_url,
                max_retries = max_retries
            ),
            task_store=InMemoryTaskStore(),
            push_config_store=push_config_store,
            push_sender= push_sender
        )

        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        logger.info(f'Starting server on {host}:{port}')

        uvicorn.run(server.build(), host=host, port=port)
    except FileNotFoundError:
        logger.error(f"Error: File '{agent_card}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Error: File '{agent_card}' contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
