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
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Union
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

AgentRegistry = os.getenv("AgentRegistry", "biz-expert-registry.dac.svc.cluster.local::10100")

os.environ["DASHSCOPE_API_KEY"] = "sk-xxx"

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


PLANNER_COT_INSTRUCTIONS_EN = """
# Role: Chief Strategy Planner (Expert in Multi-Agent Orchestration)

## Core Mission
Decompose the user's query into one or more executable tasks and assign each task to the appropriate **Domain Owner**. You must focus on the agent's **Territory** (business domain) rather than just the specific skills listed.

## Strategic Thinking Process (Chain of Thought)
Before generating the JSON, perform these steps:
1. **Domain Extraction**: Identify the core business entities in the query (e.g., "Order", "Weather", "Financials").
2. **Territory Mapping**: Match these entities to an agent's description. If an agent is a "Master of E-commerce," they own all logic related to "Orders" (Querying, Planning, or Executing).
3. **Implicit Capacity**: Assume domain experts have total knowledge of their field. A "Transaction Expert" can naturally "Analyze Order Distribution" even if that specific skill isn't listed.

## Agent Selection & Task Rules
1. **Sovereignty First**: Assign tasks based on which agent's domain covers the subject matter.
2. **Task Decomposition**: Only split into multiple tasks when the query genuinely involves **multiple different domains** or has **clear sequential dependencies**. Do not over-decompose a simple question.
3. **The "NONE" Protocol**: Only use "NONE" if a task's subject is completely outside all available agents' territories.
4. **Name Accuracy**: The `agent` field must exactly match the "name" from the agent list.

## ⚠ Critical Rules for Task Descriptions (MUST follow strictly)

**Core Principle: You are a planner, NOT an executor. Your job is to faithfully relay the user's intent, NOT to refine or rewrite their question.**

1. **Faithful Relay**: The `description` must faithfully reflect the user's original intent using wording close to what the user said. Do NOT rephrase, embellish, or "professionalize" the user's question.
2. **NEVER fabricate conditions**: You must NEVER add any qualifying conditions to the `description` that are not present in the user's original query, including but not limited to:
   - Time ranges (e.g., "in 2024", "last 3 months", "Q4")
   - Categories (e.g., "electronics", "VIP customers", "East region")
   - Metrics or dimensions (e.g., "year-over-year growth", "average order value distribution")
   - Quantities or thresholds (e.g., "Top 10", "over $1000")
   - Sorting or aggregation methods (e.g., "grouped by month", "compared by category")
3. **Preserve user-specified conditions**: If the user mentioned a condition (e.g., "last month's orders"), keep it exactly as stated — do not add to it or remove from it.
4. **Keep it simple**: When the user's question is broad (e.g., "check order status"), the task description should remain broad (e.g., "Check order status"), letting the domain expert decide how to interpret and execute.

---
**Available Agents:**
{agents}


**Contextual Reference Data:**
{information}

---
## Output Requirements
1. **Format**: Return ONLY a valid JSON string.
2. **Schema**:
   - `thought_process`: Concise reasoning of domain mapping and sovereignty.
   - `original_query`: The raw user input.
   - `tasks`: A list of objects containing:
     - `id`: Integer (starting from 1).
     - `description`: The sub-task or question relayed to the agent (faithful to the user's original wording, NO fabricated conditions).
     - `agent`: The exact agent name or "NONE".

## Examples
{instructions}

Or when no agent is found:
{none_instructions}

Questions:
"""


PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
将用户查询分解为一个或多个可执行任务，并将每个任务分配给合适的**领域负责人**。您必须关注智能体的**领域范围**（业务领域），而不仅仅是其列出的特定技能。

## 战略思考过程（思维链）
在生成JSON之前，执行以下步骤：
1. **领域提取**：识别查询中的核心业务实体（例如"订单"、"天气"、"财务"）。
2. **领域映射**：将这些实体与智能体的描述相匹配。如果一个智能体是"电商大师"，那么所有与"订单"相关的逻辑（查询、规划或执行）都由其负责。
3. **隐含能力**：假定领域专家对其领域拥有全部知识。即使未列出特定技能，"交易专家"自然能够"分析订单分布"。
4. **权限优先原则**：如果一个智能体是某个业务实体（如"订单"）的唯一代表，您必须将相关任务分配给该智能体，即使其描述中包含"我不执行查询"等技术性免责声明。在规划阶段，我们将领域专家视为该实体的通用入口。

## 智能体选择与任务规则
1. **主权优先**：根据哪个智能体的领域覆盖了主题事项来分配任务。
2. **任务分解**：仅当查询确实涉及**多个不同领域**或存在**明确的先后依赖**时，才拆分为多个任务。不要将一个简单问题过度拆分。
3. **"无对应"协议**：仅当任务的议题完全超出所有可用智能体的领域范围时，才使用"NONE"。
4. **名称准确性**：`agent`字段必须与智能体列表中的"名称"完全一致。

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

## 对话历史使用规则
- **仅用于理解指代**：对话历史仅用于理解当前问题中的指代关系（如"它"指什么、"继续"指继续什么、"那个"指哪个）。
- **禁止无关条件搬运**：不要将历史对话中与当前追问无关的过滤条件搬运到当前任务的 description 中。
- **对比性追问须继承完整上下文**：当用户使用对比性语言追问（如"那XX呢"、"换成XX呢"、"XX怎么样"），说明用户只想更改其中一个维度，其余维度（如年份、机构、指标等）均需从历史中继承，以确保 description 完整且无歧义。
  例如：上轮查询"某某银行总行2023年12月的存款总额"，用户说"那9月份呢" → description 应为"查询某某银行总行2023年9月份的存款总额" ✅，而不是"查询某某银行总行9月份的存款总额" ❌（缺少年份会导致歧义）。
- **指代追问必须自包含**：当用户的问题是指代性的后续追问（如"更详细一点"、"继续"、"那个呢"），`description` 必须补充历史中被指代的主题，使其对不了解上下文的人也能理解。
  例如：上轮谈的是"订单数据"，用户说"更详细一点" → description 应为"更详细地查询订单数据"，而不是只写"更详细一点"。

---
**对话历史：**
{history}

**可用智能体：**
{agents}

**上下文参考数据：**
{information}

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

PLANNER_COT_INSTRUCTIONS_EN_HISTORY = """
# Role: Chief Strategy Planner (Expert in Multi-Agent Orchestration)

## Core Mission
Decompose the user's query into one or more executable tasks and assign each task to the appropriate **Domain Owner**. You must focus on the agent's **Territory** (business domain) rather than just the specific skills listed.

## Strategic Thinking Process (Chain of Thought)
Before generating the JSON, perform these steps:
1. **Domain Extraction**: Identify the core business entities in the query (e.g., "Order", "Weather", "Financials").
2. **Territory Mapping**: Match these entities to an agent's description. If an agent is a "Master of E-commerce," they own all logic related to "Orders" (Querying, Planning, or Executing).
3. **Implicit Capacity**: Assume domain experts have total knowledge of their field. A "Transaction Expert" can naturally "Analyze Order Distribution" even if that specific skill isn't listed.
4. **Authority Over Disclaimer**: If an agent is the only one representing a business entity (e.g., "Order"), you MUST assign the task to it, even if the agent's description contains technical disclaimers like "I don't do queries." In the planning phase, we treat the domain expert as the universal gateway for that entity.

## Agent Selection & Task Rules
1. **Sovereignty First**: Assign tasks based on which agent's domain covers the subject matter.
2. **Task Decomposition**: Only split into multiple tasks when the query genuinely involves **multiple different domains** or has **clear sequential dependencies**. Do not over-decompose a simple question.
3. **The "NONE" Protocol**: Only use "NONE" if a task's subject is completely outside all available agents' territories.
4. **Name Accuracy**: The `agent` field must exactly match the "name" from the agent list.

## ⚠ Critical Rules for Task Descriptions (MUST follow strictly)

**Core Principle: You are a planner, NOT an executor. Your job is to faithfully relay the user's intent, NOT to refine or rewrite their question.**

1. **Faithful Relay**: The `description` must faithfully reflect the user's original intent using wording close to what the user said. Do NOT rephrase, embellish, or "professionalize" the user's question.
2. **NEVER fabricate conditions**: You must NEVER add any qualifying conditions to the `description` that are not present in the user's original query, including but not limited to:
   - Time ranges (e.g., "in 2024", "last 3 months", "Q4")
   - Categories (e.g., "electronics", "VIP customers", "East region")
   - Metrics or dimensions (e.g., "year-over-year growth", "average order value distribution")
   - Quantities or thresholds (e.g., "Top 10", "over $1000")
   - Sorting or aggregation methods (e.g., "grouped by month", "compared by category")
3. **Preserve user-specified conditions**: If the user mentioned a condition (e.g., "last month's orders"), keep it exactly as stated — do not add to it or remove from it.
4. **Keep it simple**: When the user's question is broad (e.g., "check order status"), the task description should remain broad (e.g., "Check order status"), letting the domain expert decide how to interpret and execute.

## Conversation History Usage Rules
- **Only for resolving references**: Conversation history is only for understanding references in the current question (e.g., what "it" refers to, what "continue" means, what "that" points to).
- **Do NOT carry over unrelated conditions**: Do NOT carry over filter conditions from previous conversations that are unrelated to the current follow-up question.
- **Comparative follow-ups must inherit full context**: When the user uses comparative language (e.g., "what about X?", "how about X instead?", "and for X?"), it means they want to change only ONE dimension while keeping everything else the same. All other dimensions (e.g., year, entity, metric) must be inherited from the history to ensure the description is complete and unambiguous.
  Example: Previous turn queried "total deposits for ABC Bank HQ in December 2023", user says "what about September?" → description should be "Query total deposits for ABC Bank HQ in September 2023" ✅, NOT "Query total deposits for ABC Bank HQ in September" ❌ (missing year causes ambiguity).
- **Follow-up references must be self-contained**: When the user's question is a referential follow-up (e.g., "more details please", "continue", "what about that"), the `description` must incorporate the referenced topic from history so that it is understandable without context.
  Example: Previous turn was about "order data", user says "more details please" → description should be "Provide more details on order data", NOT just "more details please".

---
**Conversation History:**
{history}


**Available Agents:**
{agents}


**Contextual Reference Data:**
{information}

---
## Output Requirements
1. **Format**: Return ONLY a valid JSON string.
2. **Schema**:
   - `thought_process`: Concise reasoning of domain mapping and sovereignty.
   - `original_query`: The raw user input.
   - `tasks`: A list of objects containing:
     - `id`: Integer (starting from 1).
     - `description`: The sub-task or question relayed to the agent (faithful to the user's original wording, NO fabricated conditions; comparative follow-ups must inherit full context; follow-up references must include context to be self-contained).
     - `agent`: The exact agent name or "NONE".

## Examples
{instructions}

Or when no agent is found:
{none_instructions}

Questions:
"""

Orchestrator_INSTRUCTIONS_ZH = """
你是一位知识分析与总结专家。你的任务是基于提供的子问题答案（`knowledge`）和对话上下文（`history`），通过逻辑严密的分析，回答用户的原始问题。

**核心原则与回答规则**

1. **答案来源的唯一性**
   * 你的所有事实性结论必须源于 `knowledge`。`history` 仅用于理解当前问题的指代（如“他”指代谁）或语境。
   * **严禁幻觉**：禁止编造 `knowledge` 中不存在的数字、日期或具体事实。

2. **信息处理与灵活匹配（核心优化）**
   * **精确匹配**：若 `knowledge` 包含原始问题所需的全部精确信息，请直接进行整合归纳，给出直接答案。
   * **退守匹配（重要）**：若 `knowledge` 中缺乏原始问题要求的“精确时间点”或“精确维度”的数据，但包含**高度相关**的信息（例如：没有11月数据但有三季度数据；没有公司客户数但有总客户数），你应当：
     1. 告知用户当前缺乏精确到 [具体维度] 的数据。
     2. 主动提供 `knowledge` 中现有的、最接近的参考数据作为替代。
     3. 严禁直接回答“没有数据”，除非 `knowledge` 与问题完全无关。

3. **回答表现形式**
   * **逻辑性**：使用分点、表格或对比等方式让答案易于阅读。
   * **图表建议**：若用户要求“画图”且 `knowledge` 中包含chart包装的多维度或趋势性数据，你应该原封不动的保留chart包装好的结构化的数据，浏览器的ui自己会负责渲染的。

4. **判定“无法回答”的标准**
   * 只有当 `knowledge` 内容与问题**毫无关联**，或信息量极度匮乏（如仅有零碎词汇）无法构成逻辑链条时，才触发该规则。
   * **此时回复**：「抱歉，目前的知识库中暂无与 [原始问题关键点] 直接或间接相关的信息，无法为您提供有效的分析。」

5. **多轮对话处理**
   * 始终以最新的 `knowledge` 为最高准则。若 `history` 中之前的结论与当前 `knowledge` 不符，请以 `knowledge` 为准，并可在回答中顺带说明数据已更新。
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

    status: str = Field(
        description='the status of the task to be executed.'
    )

# ==================== Capability Check Protocol ====================
# Message type flag used in A2A metadata to indicate a capability check request
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"


class CapabilityCheckResponse(BaseModel):
    """Standard response model for capability check A2A requests.
    
    When routing broadcasts a 'can you handle this?' request to all orchestrators,
    each orchestrator responds with this structured JSON so the router can easily
    parse and compare answers.
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


# LLM prompt for the responder side: analyze whether this agent can handle the query
# Use CoT (Chain-of-Thought) to reason step by step and avoid rigid rule-based errors.
CAPABILITY_CHECK_PROMPT = """# Role：业务领域匹配判定器

请按以下步骤**逐步思考**，每步写出你的推理，最后给出结论。

## 思考步骤

**步骤 1 - 提取数据实体**：从用户问题中剥离动作词（查询、统计、分析、画图、导出等）和输出形式（图表、报表等），只保留**核心数据/实体**。问：用户问的是哪些行业、哪些业务的数据？

**步骤 2 - 识别领域归属**：这些数据实体属于哪个大业务领域？（领域由数据所属行业决定，不由操作方式决定）

**步骤 3 - 匹配智能体**：本智能体名称与描述已指明其所在**行业**。判定标准是**数据所属行业**，而非行业内的子领域划分。只要数据属于该行业，无论涉及何种业务环节，均属可处理范围。

**步骤 4 - 反思（关键）**：① 若步骤 1 提取不到任何业务数据实体（纯工具类请求：编程、脚本、翻译、计算器等无行业数据），则不属于任何业务领域，应判定为不能处理。② **领域归属由数据所属行业决定，不由操作类型（分析/统计/可视化/导出）决定**——操作类型不是领域。③ **不按行业内的子领域细分**：智能体覆盖整个行业，不因描述侧重某环节而排斥同行业其他环节的数据。④ 同一名词可能对应不同行业。需从**用户问题的核心诉求**推断：用户真正关心的是哪个行业的数据？

**步骤 5 - 结论**：综合以上做出判定。不确定时倾向于 can_handle=true。

---
**本智能体信息：**
- 名称：{agent_name}
- 描述：{agent_description}
- 技能参考（仅供参考，不限定能力边界）：
{agent_skills}

**用户问题：**
{query}

---
## 输出格式
**只输出一个 JSON 对象**，不包含 Markdown。将步骤 1～5 的推理过程写入 reason 字段：
{{"can_handle": true 或 false, "confidence": 0.0 到 1.0, "reason": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：... 结论：..."}}
"""

# ==================== End Capability Check Protocol ====================

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

def tasklist_to_string(task_list: TaskList) -> str:
    lines = []
    for task in task_list.tasks:
        if (task.agent or "").strip().upper() == "NONE":
            line = f"[{task.id}]: {NONE_TASK_DESCRIPTION} - [NONE]"
        else:
            line = f"[{task.id}]: {task.description} - [{task.agent}]"
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
        self.metadata = metadata
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
        
        search_items = []

        search_request = SearchHistoryRequest(
                user_id=self.metadata.get('user_id', ''),
                run_id=self.metadata.get('run_id', ''),
                limit=10
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"PlannerAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"PlannerAgent get_history response : {search_items}")

        all_messages = []
        for item in search_items:
            if hasattr(item, 'messages') and item.messages:
                all_messages.extend(item.messages)

        converted_messages = []
        for msg in all_messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                if msg.role == "user":
                    converted_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    converted_messages.append(AIMessage(content=msg.content))
            else:
                logger.warning(f"Unexpected message format: {msg}")

        logger.debug(f"PlannerAgent Converted {len(converted_messages)} history messages")

        formatted_lines = []
        for msg in converted_messages:
            if isinstance(msg, HumanMessage):
                formatted_lines.append(f"human：{msg.content}")
            elif isinstance(msg, AIMessage):
                formatted_lines.append(f"assistant：{msg.content}")

        return "\n".join(formatted_lines)

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

    async def make_plan(self, query, agent_cards) -> TaskList:

        information = ""

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
                    "agent": "天气查询员"
                },
                {
                    "id": 2,
                    "description": "推荐合适的穿衣建议",
                    "agent": "时尚顾问"
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
                    "agent": "Weather-Checker"
                },
                {
                    "id": 2,
                    "description": "Recommend suitable clothing advice",
                    "agent": "Fashion-Consultant"
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
                input_variables=["history", "agents", "information"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents", "information"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        chain = chat_prompt | self.llm

        user_id = self.metadata.get('user_id', '')
        run_id = self.metadata.get('run_id', '')
        trace_id = self.metadata.get('trace_id', '')

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
                answer = await chain.ainvoke(
                    {"query": query, "history": history, "agents": system_prompt_agents, "information": information},
                    config={"callbacks": [langfuse_handler]}
                )
            else:
                answer = await chain.ainvoke(
                    {"query": query, "agents": system_prompt_agents, "information": information},
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
            agent_name='OrchestratorAgent',
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
        self.metadata = metadata
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.max_loop_count = max_loops if max_loops is not None else 1
        self.loop_retry_delay = 1
        self.agent_cards = []
        self.agent_card = agent_card
        self._no_sidecar_fallback = False

    # get all plans (agent names) for user question to execute
    async def get_plan(self, query) -> Optional[TaskList]:
        self.agent_cards = await self.list_agent_cards(query)
        if len(self.agent_cards) == 0:
            return None
        if len(self.agent_cards) == 1:
            agent_name = self.agent_cards[0].name
            logger.info("get_plan: only 1 agent (%s), skip LLM make_plan", agent_name)
            return TaskList(
                thought_process="Single agent available, direct assignment.",
                original_query=query,
                tasks=[PlannerTask(id=1, description=query, agent=agent_name)],
            )
        try:
            return await self.planner_agent.make_plan(query, self.agent_cards)
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
                answer = await self.llm.ainvoke([msg])
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
                parts = artifact.get('parts')
                if len(parts) > 0 and isinstance(parts[0], dict):
                    return parts[0].get('text')

            return ""


    # find one AgentCard with agent name which is from plan task
    async def find_agent(self, agent_name) -> AgentCard:
        # find agentcard using agent name
        agent_card = None

        for agentcard in self.agent_cards:
            if agentcard.name == agent_name:
                agent_card = agentcard

        return agent_card


    # call agent with a2a according to agent name which is from plan task (stream mode)
    async def a2a_stream(self, task_id, query, agent_name, current_tasks_status) -> AsyncIterable[str]:
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

        # Retrieve memories related to the question
        memory = await self.get_memory(query)

        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata.get('user_id', ''),
            'agent_id': self.metadata.get('agent_id', ''),
            'run_id': self.metadata.get('run_id', ''),
            'trace_id': self.metadata.get('trace_id', ''),
            'memory': memory,
            'current_tasks_status': current_tasks_status,
            'current_task': f"current task id: [{task_id}], task description: {query} ",
            'current_task_id': f"{task_id}",
            # SemanticGroup orchestrator 始终让下游 agent 返回原始知识，由自己做 LLM 总结
            'answer_model': 'original',
        }
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
    async def a2a_non_stream(self, query, agent_name) -> str:
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

        # Retrieve memories related to the question
        memory = await self.get_memory(query)

        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata.get('user_id', ''),
            'agent_id': self.metadata.get('agent_id', ''),
            'run_id': self.metadata.get('run_id', ''),
            'memory': memory,
            # SemanticGroup orchestrator 始终让下游 agent 返回原始知识，由自己做 LLM 总结
            'answer_model': 'original',
        }
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
                    if result != "":
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

        if step_status_llm_check_success in step_result:
            last_step_last_status = "complete"
        else:
            last_step_last_status = "fail"
        
        return last_step_last_status

    def _format_task_knowledge(self, task_id: int, description: str, agent: str, result: str) -> str:
        """将单条任务结果格式化为大模型易读的块，便于总结时区分任务与结果。"""
        agent_label = (agent or "").strip() or "（未分配）"
        return f"【任务 {task_id}】\n{description}\n\n【执行 Agent】\n{agent_label}\n\n【结果】\n{(result or '').strip()}"

    def _update_task_status(self, task_id: int, status: str, answer: str):
        for task_status in self.tasks_status:
            if task_status.id == task_id:
                task_status.status = status
                task_status.answer = answer
                break

    async def analyze_failure_reasons(self, tasks_status: List[TaskStatus]) -> str:
        failure_analysis = []
        
        for task in tasks_status:
            if task.status == "fail":
                failure_analysis.append(
                    f"Task {task.id} ('{task.description}') assign to {task.agent} fail."
                    f"Answer: {task.answer[:500]}..."
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

        if initial_tasks is None or not hasattr(initial_tasks, 'tasks') or not initial_tasks.tasks:
            logger.info("Warning: initial tasks is invalid")
            return last_round_knowledge

        retry_count = 0
        current_tasks = initial_tasks
        
        while retry_count <= self.max_loop_count:
            logger.info(f"=== Start executing plan, retry count: {retry_count}/{self.max_loop_count} ===")
            
            self.tasks_status = []
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
                    if self.debug == 1:
                        await updater.add_artifact(
                            [TextPart(text=f"Task [{task.id}]: {none_description}\n")],
                            name=task_name,
                        )
                        think.append(none_description)
                    continue

                current_tasks_status_json = json.dumps([task_status.model_dump() for task_status in self.tasks_status])

                agent_steps_knowledge = []

                if self.debug == 1:
                    agent_knowledge_step = f"Task [{task.id}]: {task.description}; \n\n"
                    await updater.add_artifact(
                        [TextPart(text=agent_knowledge_step)],
                        name=task_name,
                    )
                    think.append(agent_knowledge_step)

                if stream:
                    try:
                        async for agent_step_knowledge in self.a2a_stream(task.id, task.description, task.agent, current_tasks_status_json):
                            if self.debug == 1:
                                agent_knowledge_step = f"{agent_step_knowledge} \n"
                                await updater.add_artifact(
                                    [TextPart(text=agent_knowledge_step)],
                                    name=task_name,
                                )
                                think.append(agent_knowledge_step)
                            agent_steps_knowledge.append(agent_step_knowledge)

                        agent_steps_knowledge_str = "\n".join(agent_steps_knowledge)

                        current_task_status = ""
                        if agent_steps_knowledge_str == "Error occurred":
                            current_task_status = "fail"
                        else:
                            # SemanticGroup orchestrator 始终给下游设置 answer_model=original，
                            # 下游 agent 跳过了 observe_common 验证，返回的原始内容不含
                            # "reason:The current answer addresses the question very well." 标记，
                            # 因此直接视为 complete，不走 get_last_step_status 检查
                            current_task_status = "complete"
                            logger.info(f">>>>>> [answer_model=original] OrchestratorAgent(SemanticGroup).a2a_tasks() Task {task.id} 下游返回原始知识，直接标记为 complete <<<<<<")

                        self._update_task_status(task.id, current_task_status, agent_steps_knowledge_str)
                        logger.info(f"Task {task.id} completion status: {current_task_status}")
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_steps_knowledge_str))
                        if current_task_status == "fail":
                            break

                    except Exception as e:
                        logger.error(f"Error occurred while executing Task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

                else:
                    try:
                        agent_result = await self.a2a_non_stream(task.description, task.agent)
                        agent_knowledge_step = f"Task [{task.id}]: {task.description}; \nResult:\n {agent_result} \n"

                        current_task_status = "complete" if agent_result and "Error" not in agent_result else "fail"
                        self._update_task_status(task.id, current_task_status, agent_result)
                        
                        if self.debug == 1:
                            await updater.add_artifact(
                                [TextPart(text=agent_knowledge_step)],
                                name=task_name,
                            )
                            think.append(agent_knowledge_step)
                        
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, agent_result or ""))
                        
                    except Exception as e:
                        logger.error(f"Error during non-streaming execution of task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

            # 用本轮结果覆盖，保证交给总结 LLM 的始终是「最后一轮」
            last_round_knowledge = list(current_agents_knowledge)
            
            if await self.should_retry_planning(self.tasks_status):
                retry_count += 1
                if retry_count <= self.max_loop_count:
                    logger.info(f"=== Plan execution failed, preparing for retry attempt {retry_count}  ===")
                    
                    failure_analysis = await self.analyze_failure_reasons(self.tasks_status)
                    logger.info(f"Failure analysis:\n{failure_analysis}")
                    
                    if self.debug == 1:
                        retry_msg = f"\n=== 计划执行遇到问题，正在进行第 {retry_count} 次重试 ===\n失败分析:\n{failure_analysis}\n"
                        # retry_msg = f"\n=== Plan execution encountered issues, performing retry attempt {retry_count} ===\nFailure analysis:\n{failure_analysis}\n"
                        await updater.add_artifact(
                            [TextPart(text=retry_msg)],
                            name=task_name,
                        )
                        think.append(retry_msg)

                    improved_query = f"{query}\n\n之前的执行遇到了以下问题:\n{failure_analysis}\n请基于这些问题重新制定一个更好的计划。"
                    # improved_query = f"{query}\n\nThe previous execution encountered the following issues:\n{failure_analysis}\nPlease develop a better plan based on these problems."
                    new_tasks = await self.get_plan(improved_query)

                    if new_tasks is None or not hasattr(new_tasks, 'tasks') or not new_tasks.tasks:
                        logger.error("Re-planning failed, unable to obtain a valid plan")
                        
                        if self.debug == 1:
                            plan_fail_msg = f"\n⚠️ 重新规划失败，已达到最大重试次数 {self.max_loop_count}\n"
                            # plan_fail_msg = f"\n⚠️ Re-planning failed, maximum retry count {self.max_loop_count} reached\n"
                            await updater.add_artifact(
                                [TextPart(text=plan_fail_msg)],
                                name=task_name,
                            )
                            think.append(plan_fail_msg)
                        break
                    else:
                        current_tasks = new_tasks
                        logger.info(f"Re-planning successful, obtained {len(current_tasks.tasks)} new tasks")

                        if self.debug == 1:
                            new_plan_msg = f"\n=== 第 {retry_count} 次重新规划成功，新计划如下 ===\n"
                            # new_plan_msg = f"\n=== Retry attempt {retry_count} re-planning successful, new plan as follows ===\n"
                            new_plan_msg += tasklist_to_string(current_tasks)
                            await updater.add_artifact(
                                [TextPart(text=new_plan_msg)],
                                name=task_name,
                            )
                            think.append(new_plan_msg)

                        await asyncio.sleep(self.loop_retry_delay)

                        continue
                else:
                    logger.info(f"Reached maximum retry count {self.max_loop_count}, stopping retries")
                    
                    if self.debug == 1:
                        max_retry_msg = f"\n⚠️ 已达到最大重试次数 {self.max_loop_count}，停止重试\n"
                        # max_retry_msg = f"\n⚠️ Maximum retry count {self.max_loop_count} reached, stopping retries\n"
                        await updater.add_artifact(
                            [TextPart(text=max_retry_msg)],
                            name=task_name,
                        )
                        think.append(max_retry_msg)
                    break
            else:
                logger.info("All tasks completed successfully")
                if self.debug == 1:
                    success_msg = f"\n✅ 所有任务执行成功完成\n"
                    # success_msg = f"\n✅ All tasks executed successfully\n"
                    await updater.add_artifact(
                        [TextPart(text=success_msg)],
                        name=task_name,
                    )
                    think.append(success_msg)
                break
                
        logger.info(f"Task execution completed, total of {retry_count + 1} attempts made, returning last round only ({len(last_round_knowledge)} items) to summary LLM")
        return last_round_knowledge

    async def add_memory(self, query, final_answer):
        final_answer_str = "".join(final_answer)
        logger.debug(f"add_memory metadata : user_id: {self.metadata.get('user_id', '')}, agent_id:{self.metadata.get('agent_id', '')}, run_id:{self.metadata.get('run_id', '')}")
        
        async with self.data_services_client.session_context() as client:
            memory_response = await client.store_memory(
                user_id=self.metadata.get('user_id', ''),
                agent_id=self.agent_id,
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

        logger.debug(f"add_memory, query= {query}, final_answer={final_answer_str}, response : {memory_response}")
        return memory_response

    async def get_memory(self, query) -> str:
        logger.debug(f"get_memory metadata :query:{query}, user_id: {self.metadata.get('user_id', '')}, agent_id:{self.metadata.get('agent_id', '')}, run_id:{self.metadata.get('run_id', '')}")
        
        search_items = []

        async with self.data_services_client.session_context() as client:
            memory_search_response = await client.search_memories(
                query=query,
                user_id=self.metadata.get('user_id', ''),
                agent_id=self.agent_id,
                run_id=self.metadata.get('run_id', ''),
                limit=10
            )

        if memory_search_response.status == "success":
            search_items = self.data_services_client.parse_memory_search_results(memory_search_response)    
        else:
            if memory_search_response.detail:
                logger.error(f"get_memory error msg: {memory_search_response.detail}")

        logger.debug(f"get_memory response : {search_items}")

        memory_texts = [item.memory for item in search_items if item.memory]

        memory_texts_str = "\n".join(memory_texts)

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
        
        search_items = []

        search_request = SearchHistoryRequest(
                user_id=self.metadata.get('user_id', ''),
                run_id=self.metadata.get('run_id', ''),
                limit=10
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"OrchestratorAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"OrchestratorAgent get_history response : {search_items}")

        all_messages = []
        for item in search_items:
            if hasattr(item, 'messages') and item.messages:
                all_messages.extend(item.messages)

        converted_messages = []
        for msg in all_messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                if msg.role == "user":
                    converted_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    converted_messages.append(AIMessage(content=msg.content))
            else:
                logger.warning(f"Unexpected message format: {msg}")

        logger.debug(f"OrchestratorAgent onverted {len(converted_messages)} history messages")
        return converted_messages

    async def stream(self, query, task_knowledges, think) -> AsyncIterable[dict[str, Any]]:

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
            
            # for chunk in chain.stream({"query": query, "knowledge": knowledge, "memory": memory}, config={"callbacks": [langfuse_handler]}):
            for chunk in chain.stream({"query": query, "knowledge": knowledge}, config={"callbacks": [langfuse_handler]}):
                if hasattr(chunk, 'content') and chunk.content:
                    final_answer.append(chunk.content)
                    yield {'content': chunk.content, 'is_task_complete': False}

            span.update_trace(output={"answer": "".join(final_answer)})

        langfuse.flush()

        yield {'content': '', 'is_task_complete': True}

        # add history
        if self.enable_history == "enable":
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
        max_loops: int = 1,
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

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """Handle a capability check request from the routing agent.
        
        Analyzes whether this orchestrator agent can handle the given query
        based on its own agent card (name, description, skills) using LLM,
        then responds with a structured CapabilityCheckResponse JSON.
        """
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # Build agent info from our own agent card
        agent_name = self.agent_card.name if self.agent_card else self.agent_id or "Unknown"
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

        # Use LLM to analyze if this agent can handle the query
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

            prompt = CAPABILITY_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                query=query,
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            response_text = response.content.strip()

            # Clean markdown wrappers if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            elif response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            result_data = json.loads(response_text)

            check_response = CapabilityCheckResponse(
                can_handle=result_data.get("can_handle", False),
                confidence=result_data.get("confidence", 0.0),
                reason=result_data.get("reason", ""),
                agent_name=agent_name,
                agent_url=agent_url,
            )
        except Exception as e:
            logger.error(f"Capability check analysis failed: {e}")
            check_response = CapabilityCheckResponse(
                can_handle=False,
                confidence=0.0,
                reason=f"Analysis failed: {str(e)}",
                agent_name=agent_name,
                agent_url=agent_url,
            )

        response_json = check_response.model_dump_json()
        logger.info(f"Capability check response for query '{query[:80]}...': {response_json}")

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

        metadata = context.metadata
        logger.info(f"===== OrchestratorAgentExecutor, user request metadata is {metadata}.")

        # ---- Capability Check: respond quickly if this is a broadcast routing probe ----
        if metadata and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            logger.info(f"===== Received capability check request, query: {query[:100]}...")
            await self.handle_capability_check(context, event_queue, query)
            return

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

        # make plans for user question, each plan is the name of agent card
        steps = await agent.get_plan(query)

        think = []

        if steps is None:
            logger.info(f"===== OrchestratorAgentExecutor, steps is empty.")
            not_found_agents = (
                NO_SIDECAR_FALLBACK_DESCRIPTION
                if getattr(agent, "_no_sidecar_fallback", False)
                else "Not found agents. You can provide more information."
            )
            await updater.add_artifact(
                [TextPart(text=not_found_agents)],
                name=f'{agent.agent_name}-result',
            )
            think.append(not_found_agents)
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )
        else:
            if self.debug == 1:
                steps_str = tasklist_to_string(steps)
                await updater.add_artifact(
                    [TextPart(text=steps_str)],
                    name=f'{agent.agent_name}-result',
                )
                think.append(steps_str)

            # call each agent to get the knowledge owned by each agent, then get some knowledges from agents
            task_name = f'{agent.agent_name}-result'
            task_knowledges = await agent.a2a_tasks(query, steps, updater, task_name, think)

            _tk_preview = [str(tk)[:200] + "..." for tk in task_knowledges] if task_knowledges else []
            logger.info(f"===== OrchestratorAgentExecutor.task_knowledges count={len(task_knowledges) if task_knowledges else 0}, preview: {_tk_preview}")

            # SemanticGroup orchestrator 始终需要 LLM 总结回答，不跳过
            # （answer_model=original 仅透传给下游 agent 让它们跳过各自的 LLM，但本层一定要总结）
            conversation = []
            async for event in agent.stream(query, task_knowledges, think):
                is_task_complete = event['is_task_complete']
                if not is_task_complete:
                    if event['content']:
                        part = TextPart(text=event['content'])
                        await updater.add_artifact(
                            [part],
                            name=f'{agent.agent_name}-result',
                        )
                        await asyncio.sleep(0.01)
                        conversation.append(event['content'])
                else:
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