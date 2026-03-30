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

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "

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

**重规划上下文（JSON，仅在重试时提供，首轮通常为空）：**
{replan_context}

**重规划指导（仅在重试时提供，首轮通常为空）：**
{replan_guidance}

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

---
**Available Agents:**
{agents}


**Contextual Reference Data:**
{information}

**Replan Context (JSON, provided on retries, usually empty on first attempt):**
{replan_context}

**Replan Guidance (provided on retries, usually empty on first attempt):**
{replan_guidance}

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

**重规划上下文（JSON，仅在重试时提供，首轮通常为空）：**
{replan_context}

**重规划指导（仅在重试时提供，首轮通常为空）：**
{replan_guidance}

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

**Replan Context (JSON, provided on retries, usually empty on first attempt):**
{replan_context}

**Replan Guidance (provided on retries, usually empty on first attempt):**
{replan_guidance}

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
   * **默认结构**：先用 1-2 句给出结论；当答案里包含多个数字、属性、对象信息或对比关系时，优先补一个简短的“关键依据”或“补充信息”小节，不要只输出一整段纯文本。
   * **轻量结构化表达优先**：默认使用短标题、项目符号或简短表格提升可读性；保持结构轻量，不要堆砌大段背景说明。
   * **标题自然**：不要机械使用“直接答案”“补充说明”这类模板化标题；若需要标题，优先使用更自然的标题，如“结论”“核心结论”“关键信息”“关键依据”，并允许根据内容自适应命名。
   * **图表建议**：若用户要求“画图”且 `knowledge` 中包含chart包装的多维度或趋势性数据，你应该原封不动的保留chart包装好的结构化的数据，浏览器的ui自己会负责渲染的。

4. **判定“无法回答”的标准**
   * 只有当 `knowledge` 内容与问题**毫无关联**，或信息量极度匮乏（如仅有零碎词汇）无法构成逻辑链条时，才触发该规则。
   * **此时回复**：「抱歉，目前的知识库中暂无与 [原始问题关键点] 直接或间接相关的信息，无法为您提供有效的分析。」

5. **多轮对话处理**
   * 始终以最新的 `knowledge` 为最高准则。若 `history` 中之前的结论与当前 `knowledge` 不符，请以 `knowledge` 为准，并可在回答中顺带说明数据已更新。

6. **收敛但可读（强制）**
   * 必须先给结论，不要先铺垫过程。
   * 若用户未明确要求“方法对比/扩展建议/治理建议/补充分析”，默认不要主动展开这些内容。
   * 补充内容只保留与问题直接相关的 2-4 个要点；既不要发散，也不要压缩成毫无层次的一小段话。
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
        description='sanitized business answer for planning/display.'
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

    reported_reason_code: str = Field(
        default="",
        description='reason code reported by downstream expert.'
    )

    reported_non_retryable: bool = Field(
        default=False,
        description='whether downstream expert marked this failure as non-retryable.'
    )

    status: str = Field(
        description='the status of the task to be executed.'
    )

# Fixed description when no agent is relevant (agent=NONE)
NONE_TASK_DESCRIPTION = "No available agent can do this task. "
NON_RETRYABLE_MARKER = "NON_RETRYABLE::OUT_OF_SCOPE"
NON_RETRYABLE_REPEAT_MARKER = "NON_RETRYABLE::REPEATED_FAILURE"

def tasklist_to_string(task_list: TaskList) -> str:
    lines = []
    for task in task_list.tasks:
        if (task.agent or "").strip().upper() == "NONE":
            line = f"[{task.id}]: {NONE_TASK_DESCRIPTION} - [NONE]"
        else:
            line = f"[{task.id}]: {task.description} - [{task.agent}]"
        lines.append(line)
    return "\nAll Tasks:\n" + "\n".join(lines) + "\n\n"


def log_size_trace(stage: str, **metrics: Any) -> None:
    lines = [f"[SemanticDomain][SizeTrace] {stage}"]
    for key, value in metrics.items():
        lines.append(f"  {key}={value}")
    logger.info("\n".join(lines))

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
        dd_namespace: str = None,
        data_descriptors:list = None,
        descriptor_types:list = None
    ):
        logger.info('Initializing PlannerAgent')
        logger.info(f"PlannerAgent received descriptor_types: {descriptor_types}")
        logger.info(f"PlannerAgent received data_descriptors: {data_descriptors}")
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
            use_data_descriptor_header=True,
        )
        self.metadata = metadata
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.dd_namespace = dd_namespace
        self.data_descriptors = data_descriptors
        self.descriptor_types = descriptor_types

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

    def analyze_descriptor_types(self):
        """
        Parse descriptor_types from JSON format.

        Expected input: self.descriptor_types is a list with one element that is a
        JSON array string produced by the execution-engine, e.g.
          ['[{"name":"dd-mysql","descriptorType":"structured-mysql","dbType":"mysql",...}]']

        Returns: (ddname, agent_type, db_type)
        """
        if not self.descriptor_types or not isinstance(self.descriptor_types, list) or len(self.descriptor_types) == 0:
            logger.error(f"analyze_descriptor_types: invalid descriptor_types={self.descriptor_types}")
            return "", "unknown", ""

        logger.info(f"PlannerAgent analyze_descriptor_types, descriptor_types:{self.descriptor_types}")

        first_item = self.descriptor_types[0].strip()
        try:
            data_list = json.loads(first_item)
            if not isinstance(data_list, list):
                data_list = [data_list]
            if not data_list:
                return "", "unknown", ""

            cfg = data_list[0]
            name = cfg.get("name", "")
            descriptor_type = cfg.get("descriptorType", "unknown")
            db_type = cfg.get("dbType", "")

            match = re.search(r'structured-([a-zA-Z0-9_]+)', descriptor_type)
            if match:
                return name, "structured", match.group(1) if not db_type else db_type

            logger.info(f"PlannerAgent analyze_descriptor_types: name={name}, type={descriptor_type}, db_type={db_type}")
            return name, descriptor_type, db_type
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"analyze_descriptor_types: failed to parse JSON: {e}, raw={first_item[:200]}")
            return "", "unknown", ""

    async def get_history(self) -> list:
        """
        human: Hello  
        assistant: Hello! How can I help you?  
        human: What's the weather like today?  
        assistant: Please provide your location information.
        """

        logger.info(f"PlannerAgent get_history metadata: user_id: {self.metadata['user_id']}, run_id:{self.metadata['run_id']}")
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        if normalize_history_turns(propagated.get("turns")):
            return history_text_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
                user_id=self.metadata['user_id'],
                run_id=self.metadata['run_id'],
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
            history_payload_from_search_items(search_items, source="sd_orchestrator_fallback")
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

    async def get_knowledge(self, query) -> str:
        logger.info(f"=========get_knowledge, query: {query}, data_descriptors: {self.data_descriptors}")
        try:
            collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]

            knowledge = await self.data_services_client.search_multiple_collections(
                collection_names=collection_names,
                query=query,
                search_type="hybrid",
                limit=10,
                hybrid_threshold=0.1
            )

        except Exception as e:
            logger.error(f'An error occurred during search knowledge from dataservices: {e}')
            knowledge = None
            raise
        finally:
            await self.data_services_client.close()

        knowledge_str = ""
        if knowledge:
            knowledge_str = knowledge.all_content
        logger.debug(f"get knowledge: {knowledge_str}")
        return knowledge_str

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
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
    ) -> TaskList:

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        logger.info(f" === PlannerAgent.make_plan,  ddname = {ddname}, agent_type = {agent_type}, db_type= {db_type}")

        if agent_type not in ["structured", "unstructured", "code"]:
            raise ValueError(f"Unsupported descriptor type: {agent_type}. ")

        information = ""

        # if agent is unstructured or code, do not use knowledge as context for planning.
        if agent_type in ["unstructured", "code"]:
            logger.info(f" === PlannerAgent. agent is {agent_type}, do not use knowledge as context for planning")
            information = ""
        else:
            # get knowledge for plan
            information = await self.get_knowledge(query)

        system_template = ""
        if self.enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_ZH

        replan_context_text = json.dumps(replan_context or {}, ensure_ascii=False)
        replan_guidance_text = (replan_guidance or "").strip()

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
                input_variables=["history", "agents", "information", "replan_context", "replan_guidance"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents", "information", "replan_context", "replan_guidance"],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        chain = chat_prompt | self.llm

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']
        history = ""
        planner_prompt_chars = (
            len(str(system_template or ""))
            + len(str(query or ""))
            + len(str(system_prompt_agents or ""))
            + len(str(information or ""))
            + len(str(replan_context_text or ""))
            + len(str(replan_guidance_text or ""))
        )

        answer = None

        with langfuse.start_as_current_span(
            name="orchestrator-make_plan",
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
            log_size_trace(
                "planner-input",
                query_chars=len(str(query or "")),
                agents_chars=len(str(system_prompt_agents or "")),
                information_chars=len(str(information or "")),
                history_chars=len(str(history or "")),
                replan_context_chars=len(str(replan_context_text or "")),
                replan_guidance_chars=len(str(replan_guidance_text or "")),
                planner_prompt_chars=planner_prompt_chars,
                planner_prompt_tokens_est=int(planner_prompt_chars / 4),
            )
            if self.enable_history == "enable":
                answer = chain.invoke(
                    {
                        "query": query,
                        "history": history,
                        "agents": system_prompt_agents,
                        "information": information,
                        "replan_context": replan_context_text,
                        "replan_guidance": replan_guidance_text,
                    },
                    config={"callbacks": [langfuse_handler]}
                )
            else:
                answer = chain.invoke(
                    {
                        "query": query,
                        "agents": system_prompt_agents,
                        "information": information,
                        "replan_context": replan_context_text,
                        "replan_guidance": replan_guidance_text,
                    },
                    config={"callbacks": [langfuse_handler]}
                )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        log_size_trace(
            "planner-output",
            llm_output_chars=len(str(getattr(answer, "content", "") or "")),
        )

        logger.info(f" === PlannerAgent.make_plan , llm result = {answer.content}")

        data_dict = self.format_llm_ouput(answer)

        tasks = TaskList(**data_dict)

        logger.info(f" === PlannerAgent.make_plan , tasks = {tasks}")

        return tasks


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
        data_descriptors:list = None,
        descriptor_types:list = None,
        debug: int = 0,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        dd_namespace:str = None,
        max_loops: int = None,
        agent_card: AgentCard = None
    ):
        logger.info('Initializing OrchestratorAgent')
        logger.info(f"OrchestratorAgent received descriptor_types: {descriptor_types}")
        logger.info(f"OrchestratorAgent received data_descriptors: {data_descriptors}")

        super().__init__(
            agent_name=(agent_id or 'OrchestratorAgent'),
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
            dd_namespace=dd_namespace,
            data_descriptors=data_descriptors,
            descriptor_types=descriptor_types
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
        self.data_descriptors = data_descriptors
        self.descriptor_types = descriptor_types
        self.debug = debug
        self.tasks_status = []
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=True,
        )
        self.metadata = metadata
        self.enable_history = enable_history
        self.agent_id = agent_id or self.agent_name
        self.max_loop_count = max_loops
        self.agent_card = agent_card
        self.loop_retry_delay = 1
        self.agent_cards = []

    @staticmethod
    def _extract_structured_control_from_answer(raw_answer: str) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []
        for line in str(raw_answer or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("structured_control:"):
                continue
            payload = stripped.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                candidates.append(data)
        if not candidates:
            return {}
        # Prefer explicit non-retryable signals across multiple structured_control blocks.
        for data in reversed(candidates):
            if bool(data.get("non_retryable", False)):
                return data
        # Fallback: use the latest structured_control emitted by expert.
        return candidates[-1]

    # get all plans (agent names) for user question to execute
    async def get_plan(
        self,
        query,
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
    ) -> TaskList:

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            return None

        # Fast path: single agent available (typical for Semantic Domain with USE_ONLY_OWN_CAPABILITY=true).
        # Skip LLM planning entirely — the only possible plan is "send query to the sole agent".
        if len(self.agent_cards) == 1:
            sole_agent = self.agent_cards[0]
            history_note = ""
            if self.enable_history == "enable":
                history_text = await self.planner_agent.get_history()
                history_note = (
                    " conversation_history available for follow-up context."
                    if str(history_text or "").strip()
                    else " no prior conversation_history available."
                )
            logger.info(f"Single agent available ({sole_agent.name}), skipping LLM planning — direct dispatch")
            return TaskList(
                thought_process=f"Only one agent available ({sole_agent.name}), direct dispatch without LLM planning.{history_note}",
                original_query=query,
                tasks=[PlannerTask(id=1, description=query, agent=sole_agent.name)]
            )

        # Multi-agent path: use LLM planner to decompose and assign tasks
        steps = await self.planner_agent.make_plan(
            query,
            self.agent_cards,
            replan_context=replan_context,
            replan_guidance=replan_guidance,
        )
        if steps is None:
            return None

        return steps


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
        If env USE_ONLY_OWN_CAPABILITY is set (e.g. true/1/yes), returns only self.agent_card
        with url overridden to http://localhost:10101.
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
        # Default true: use registry; set to true/1/yes to return only self.agent_card with url=http://localhost:10101
        use_only_own = (os.getenv("USE_ONLY_OWN_CAPABILITY", "true").strip().lower() in ("true", "1", "yes"))
        if use_only_own and self.agent_card is not None:
            _dump = getattr(self.agent_card, "model_dump", None) or getattr(self.agent_card, "dict", None)
            card_dict = dict(_dump()) if _dump else {}
            card_dict["url"] = "http://localhost:10101"
            logger.info("USE_ONLY_OWN_CAPABILITY is set, returning only self agent_card with url=http://localhost:10101")
            return [AgentCard(**card_dict)]

        agent_cards = []

        agent_registry_client = AgentRegistryClient()
        
        collection_name = os.getenv("CollectionName", "expert_agent_cards")

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
                
                logger.info(f"Successfully retrieved {len(agent_cards)} agent cards, agent cards: {agent_names}")
                return agent_cards
            else:
                logger.warning(f"Search returned non-success status: {response.status}")
                return []

        except Exception as e:
            logger.error(f'An error occurred during list_agent_cards: {e}')
            raise ValueError(f"An error occurred during list_agent_cards: {e}")


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
    def is_progress_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith(PROGRESS_FRAME_PREFIX)

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 320) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[: limit - 3] + "..."

    @classmethod
    def build_sd_plan_ready_progress(
        cls,
        *,
        task_list: TaskList,
        user_query: str = "",
        replan: bool = False,
        retry_count: Optional[int] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Build message + extra for sd_orchestrator_plan_ready (aligned with group_plan_ready)."""
        tasks = list(getattr(task_list, "tasks", None) or [])
        n = len(tasks)
        thought_raw = (getattr(task_list, "thought_process", None) or "").strip()
        planner_thought = cls._truncate_progress_message(thought_raw, 480) if thought_raw else ""
        orig_from_plan = (getattr(task_list, "original_query", None) or "").strip()
        query_source = (user_query or "").strip() or orig_from_plan
        query_preview = cls._truncate_progress_message(query_source, 220)

        task_lines: List[str] = []
        structured_tasks: List[Dict[str, Any]] = []
        for t in tasks[:20]:
            tid = getattr(t, "id", 0)
            desc_full = getattr(t, "description", "") or ""
            agent_name = (getattr(t, "agent", "") or "").strip()
            desc_trunc = cls._truncate_progress_message(desc_full, 200)
            task_lines.append(f"#{tid} → [{agent_name}] {desc_trunc}")
            structured_tasks.append(
                {"id": tid, "description": desc_trunc, "agent": agent_name}
            )
        if len(tasks) > 20:
            task_lines.append(f"... +{len(tasks) - 20} more task(s)")
        plan_tasks_summary = " ; ".join(task_lines) if task_lines else "(no tasks)"
        plan_tasks_summary = cls._truncate_progress_message(plan_tasks_summary, 950)

        segments: List[str] = [f"{n} task(s)", f"query: {query_preview}"]
        if planner_thought:
            segments.append(f"planner thought: {planner_thought}")
        segments.append(f"tasks: {plan_tasks_summary}")

        message = cls._truncate_progress_message(" | ".join(segments), 720)

        extra: Dict[str, Any] = {
            "task_count": n,
            "query_preview": query_preview,
            "plan_tasks_summary": plan_tasks_summary,
            "plan_tasks": structured_tasks[:40],
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
            "layer": "sd_orchestrator",
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
        updater: TaskUpdater,
        artifact_name: str,
        *,
        event: str,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        await updater.add_artifact(
            [TextPart(text=self.build_progress_frame(
                event,
                message=message,
                status=status,
                run_id=(self.metadata or {}).get("run_id", ""),
                user_id=(self.metadata or {}).get("user_id", ""),
                agent_id=self.agent_id,
                task_id=task_id,
                extra=extra,
            ))],
            name=artifact_name,
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
    async def a2a_stream(self, task_id, query, agent_name, current_tasks_status) -> AsyncIterable[str]:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            yield "Not found agent"
            return

        # Retrieve memories related to the question
        memory = await self.get_memory(query)
        logger.info(
            "[MemoryUse][SD-Orchestrator][a2a_stream] target=%s query_chars=%d memory_chars=%d memory_non_empty=%s",
            agent_name,
            len(str(query or "")),
            len(str(memory or "")),
            bool(str(memory or "").strip()),
        )

        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata['user_id'],
            'run_id': self.metadata['run_id'],
            'trace_id': self.metadata['trace_id'],
            'memory': memory,
            'current_tasks_status': current_tasks_status,
            'current_task': f"current task id: [{task_id}], task description: {query} ",
            'current_task_id': f"{task_id}",
        }

        # 透传 answer_model，让下游 expert agent 也能感知到 original 模式
        if self.metadata.get('answer_model'):
            a2a_metadata['answer_model'] = self.metadata['answer_model']
            logger.info(f">>>>>> [answer_model=original] OrchestratorAgent.a2a_stream() 透传 answer_model={self.metadata['answer_model']} 给 agent={agent_name} <<<<<<")

        # 透传 extra_context（来自 semantic group 的其他 agent 结果），让下游 expert agent 能获取代码等上下文
        extra_context = self.metadata.get('extra_context', '')
        if extra_context:
            a2a_metadata['extra_context'] = extra_context
            logger.info(f"[OrchestratorAgent.a2a_stream] 透传 extra_context ({len(extra_context)} 字) 给 agent={agent_name}")

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
                logger.error(f"An error occurred: {e}")
                yield "Error occurred"

    # call agent with a2a according to agent name which is from plan task (non-stream mode)
    async def a2a_non_stream(self, query, agent_name) -> str:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            return "Not found agent"

        # Retrieve memories related to the question
        memory = await self.get_memory(query)
        logger.info(
            "[MemoryUse][SD-Orchestrator][a2a_non_stream] target=%s query_chars=%d memory_chars=%d memory_non_empty=%s",
            agent_name,
            len(str(query or "")),
            len(str(memory or "")),
            bool(str(memory or "").strip()),
        )

        a2a_metadata: dict[str, Any] = {
            'user_id': self.metadata['user_id'],
            'run_id': self.metadata['run_id'],
            'memory': memory,
        }

        # 透传 answer_model，让下游 expert agent 也能感知到 original 模式
        if self.metadata.get('answer_model'):
            a2a_metadata['answer_model'] = self.metadata['answer_model']
            logger.info(f">>>>>> [answer_model=original] OrchestratorAgent.a2a_non_stream() 透传 answer_model={self.metadata['answer_model']} 给 agent={agent_name} <<<<<<")

        # 透传 extra_context（来自 semantic group 的其他 agent 结果），让下游 expert agent 能获取代码等上下文
        extra_context = self.metadata.get('extra_context', '')
        if extra_context:
            a2a_metadata['extra_context'] = extra_context
            logger.info(f"[OrchestratorAgent.a2a_non_stream] 透传 extra_context ({len(extra_context)} 字) 给 agent={agent_name}")

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
                        if self.is_progress_frame(result):
                            logger.info(
                                "[DACProgress][SD-Orchestrator][a2a_non_stream] target=%s relayed downstream progress frame",
                                agent_name,
                            )
                            continue
                        agent_knowledge.append(result)
                return " ".join(agent_knowledge)

            except Exception as e:
                logger.error(f"An error occurred: {e}")
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

    def _update_task_status(self, task_id: int, status: str, answer: str):
        for task_status in self.tasks_status:
            if task_status.id == task_id:
                raw_answer = str(answer or "")
                answer_final = self._sanitize_display_text(raw_answer)
                structured_control = self._extract_structured_control_from_answer(raw_answer)
                reported_reason_code = str(structured_control.get("reason_code") or "").strip()
                reported_non_retryable = bool(structured_control.get("non_retryable", False))
                success_marker = "reason:The current answer addresses the question very well."
                status_final = "complete" if success_marker in raw_answer else status
                task_status.status = status_final
                task_status.answer = raw_answer
                task_status.answer_final = answer_final
                task_status.marker_present = NON_RETRYABLE_MARKER in raw_answer
                task_status.reported_reason_code = reported_reason_code
                task_status.reported_non_retryable = reported_non_retryable
                task_status.failure_reason_code = (
                    reported_reason_code if (status_final == "fail" and reported_reason_code) else
                    (self._classify_task_failure_reason(task_status) if status_final == "fail" else "")
                )
                if status_final == "fail" and NON_RETRYABLE_REPEAT_MARKER in raw_answer:
                    task_status.reported_reason_code = "repeated_failure_non_retryable"
                    task_status.reported_non_retryable = True
                    task_status.failure_reason_code = "repeated_failure_non_retryable"
                task_status.diagnostics_excerpt = raw_answer[:1200] if raw_answer != answer_final else ""
                break

    def _get_task_status(self, task_id: int) -> Optional[TaskStatus]:
        for task_status in self.tasks_status:
            if task_status.id == task_id:
                return task_status
        return None

    def _build_task_progress_extra(self, task_id: int, target_agent: str, completion: str) -> Dict[str, Any]:
        task_status = self._get_task_status(task_id)
        return {
            "target_agent": target_agent,
            "completion": completion,
            "failure_reason_code": str(getattr(task_status, "failure_reason_code", "") or ""),
            "reported_reason_code": str(getattr(task_status, "reported_reason_code", "") or ""),
            "reported_non_retryable": bool(getattr(task_status, "reported_non_retryable", False)),
            "marker_present": bool(getattr(task_status, "marker_present", False)),
        }

    def _build_failed_tasks_progress_summary(self, failed_tasks: List[TaskStatus]) -> List[Dict[str, Any]]:
        summary: List[Dict[str, Any]] = []
        for task in failed_tasks:
            summary.append({
                "task_id": task.id,
                "agent": task.agent,
                "status": task.status,
                "failure_reason_code": str(task.failure_reason_code or self._classify_task_failure_reason(task)),
                "reported_reason_code": str(task.reported_reason_code or ""),
                "reported_non_retryable": bool(task.reported_non_retryable),
            })
        return summary

    def _truncate_text(self, text: str, max_chars: int) -> str:
        raw = str(text or "")
        return raw if len(raw) <= max_chars else raw[:max_chars] + "...(truncated)"

    def _strip_retry_diagnostics_block(self, text: str) -> str:
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
        raw = str(text or "")
        cleaned = self._strip_retry_diagnostics_block(raw)
        if NON_RETRYABLE_MARKER in raw and NON_RETRYABLE_MARKER not in cleaned:
            return f"{NON_RETRYABLE_MARKER}\n{cleaned}" if cleaned else NON_RETRYABLE_MARKER
        if NON_RETRYABLE_REPEAT_MARKER in raw and NON_RETRYABLE_REPEAT_MARKER not in cleaned:
            return f"{NON_RETRYABLE_REPEAT_MARKER}\n{cleaned}" if cleaned else NON_RETRYABLE_REPEAT_MARKER
        return cleaned

    def _classify_task_failure_reason(self, task: TaskStatus) -> str:
        reported = str(getattr(task, "reported_reason_code", "") or "").strip()
        if reported:
            return reported
        answer = str(task.answer or "").lower()
        if NON_RETRYABLE_REPEAT_MARKER.lower() in answer:
            return "repeated_failure_non_retryable"
        if NON_RETRYABLE_MARKER.lower() in answer:
            logger.warning(
                "[NonRetryablePropagation][SemanticDomain] task_id=%s marker_detected=%s source=task_answer",
                task.id,
                NON_RETRYABLE_MARKER,
            )
            return "out_of_scope_non_retryable"
        if (task.agent or "").strip().upper() == "NONE":
            return "no_agent_available"
        if "not found agent" in answer:
            return "agent_not_found"
        if "execution error" in answer or "error occurred" in answer:
            return "execution_error"
        if not answer.strip():
            return "empty_answer"
        return "insufficient_or_incorrect_answer"

    def _decide_retry_action(self, reason_code: str, same_plan_retry_count: int) -> str:
        if reason_code in {"agent_not_found", "no_agent_available", "out_of_scope_non_retryable", "repeated_failure_non_retryable"}:
            return "abort"
        if reason_code in {"execution_error", "empty_answer"} and same_plan_retry_count < 1:
            return "retry_same_plan"
        return "replan"

    def _select_retry_reason_code(self, failed_tasks: List[TaskStatus]) -> str:
        if not failed_tasks:
            return "unknown_failure"
        reason_codes = [self._classify_task_failure_reason(t) for t in failed_tasks]
        priority = (
            "repeated_failure_non_retryable",
            "out_of_scope_non_retryable",
            "agent_not_found",
            "no_agent_available",
            "execution_error",
            "empty_answer",
        )
        for code in priority:
            if code in reason_codes:
                logger.info("[RetryAware][SemanticDomain] selected reason=%s from=%s", code, reason_codes)
                return code
        return reason_codes[0] if reason_codes else "unknown_failure"

    def _build_replan_context(
        self,
        original_query: str,
        current_tasks: TaskList,
        retry_count: int,
        reason_code: str,
        failure_analysis: str,
    ) -> Dict[str, Any]:
        plan_tasks = []
        for t in current_tasks.tasks:
            plan_tasks.append(
                {
                    "id": t.id,
                    "description": t.description,
                    "agent": t.agent,
                }
            )

        execution_results = []
        total_answer_chars = 0
        for t in self.tasks_status:
            answer_raw = str(t.answer or "")
            answer_final = str(t.answer_final or self._sanitize_display_text(answer_raw))
            total_answer_chars += len(answer_final)
            task_reason_code = str(t.failure_reason_code or (self._classify_task_failure_reason(t) if t.status == "fail" else ""))
            execution_results.append(
                {
                    "task_id": t.id,
                    "description": t.description,
                    "agent": t.agent,
                    "status": t.status,
                    "failure_reason_code": task_reason_code,
                    "marker_present": bool(t.marker_present or (NON_RETRYABLE_MARKER in answer_raw)),
                    "answer_excerpt": answer_final,
                    "answer_chars": len(answer_final),
                    "answer_raw_chars": len(answer_raw),
                    "diagnostics_present": bool(t.diagnostics_excerpt),
                    "diagnostics_chars": len(str(t.diagnostics_excerpt or "")),
                }
            )
        structured_failures = [
            {
                "task_id": t.id,
                "agent": t.agent,
                "reason_code": str(t.failure_reason_code or self._classify_task_failure_reason(t)),
                "marker_present": bool(t.marker_present),
            }
            for t in self.tasks_status
            if t.status == "fail"
        ]
        replan_context = {
            "original_query": original_query,
            "last_plan": {"tasks": plan_tasks},
            "execution_results": execution_results,
            "structured_failures": structured_failures,
            "failure_analysis": self._sanitize_display_text(failure_analysis),
            "retry_decision": {
                "retry_count": retry_count,
                "reason_code": reason_code,
            },
        }
        log_size_trace(
            "replan-context-build",
            original_query_chars=len(str(original_query or "")),
            tasks_count=len(plan_tasks),
            execution_results_count=len(execution_results),
            total_answer_chars=total_answer_chars,
            failure_analysis_chars=len(str(failure_analysis or "")),
            replan_context_chars=len(json.dumps(replan_context, ensure_ascii=False)),
        )
        return replan_context

    async def analyze_failure_reasons(self, tasks_status: List[TaskStatus]) -> str:
        failure_analysis = []
        
        for task in tasks_status:
            if task.status == "fail":
                reason_code = self._classify_task_failure_reason(task)
                failure_analysis.append(
                    f"Task {task.id} ('{task.description}') assign to {task.agent} fail."
                    f" reason_code={reason_code}. "
                    f"Answer: {self._truncate_text(task.answer_final or self._sanitize_display_text(task.answer or ''), 1200)}"
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
        same_plan_retry_count = 0
        current_tasks = initial_tasks
        execution_rounds = 0
        retry_decisions = 0

        def _dedup_knowledge_items(items: List[str]) -> List[str]:
            deduped: List[str] = []
            seen: set[str] = set()
            for item in items or []:
                text = str(item or "").strip()
                if not text:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                deduped.append(text)
            return deduped
        
        while retry_count <= self.max_loop_count:
            execution_rounds += 1
            logger.info(f"=== Start executing plan, retry count: {retry_count}/{self.max_loop_count} ===")
            log_size_trace(
                "plan-round-start",
                retry_count=retry_count,
                execution_round=execution_rounds,
                max_loops=self.max_loop_count,
                query_chars=len(str(query or "")),
                tasks_count=len(current_tasks.tasks or []),
                tasks_text_chars=len(tasklist_to_string(current_tasks)),
            )
            
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
                task_desc_preview = self._truncate_progress_message(task.description or "", 220)
                agent_label = (task.agent or "").strip() or "UNKNOWN"
                started_msg = (
                    f"started task {task.id}: {task_desc_preview} → agent [{agent_label}]"
                )
                await self.emit_progress(
                    updater,
                    task_name,
                    event="sd_orchestrator_task_started",
                    message=self._truncate_progress_message(started_msg, 640),
                    status="running",
                    task_id=task.id,
                    extra={
                        "target_agent": task.agent,
                        "task_description": task_desc_preview,
                        "retry_count": retry_count,
                    },
                )

                # When planner returned agent=NONE (no relevant agent), use fixed description and skip A2A
                if (task.agent or "").strip().upper() == "NONE":
                    none_description = NONE_TASK_DESCRIPTION
                    logger.info("Task %s: agent=NONE (no relevant agent)", task.id)
                    self._update_task_status(task.id, "complete", none_description)
                    none_progress_msg = (
                        f"Task [{task.id}]: {none_description.strip()} - [NONE]"
                    )
                    await self.emit_progress(
                        updater,
                        task_name,
                        event="sd_orchestrator_task_no_agent",
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
                        event="sd_orchestrator_task_finished",
                        message=f"completed task {task.id} without downstream agent",
                        status="done",
                        task_id=task.id,
                        extra={
                            "target_agent": "",
                            "completion": "complete",
                            "task_status": "skipped_no_agent",
                        },
                    )
                    current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, "", none_description))
                    if self.debug == 1:
                        await updater.add_artifact(
                            [TextPart(text=f"Task [{task.id}]: {none_description}\n")],
                            name=task_name,
                        )
                        think.append(none_description)
                    continue

                current_tasks_status_json = json.dumps([task_status.model_dump() for task_status in self.tasks_status])
                log_size_trace(
                    "task-dispatch",
                    retry_count=retry_count,
                    task_id=task.id,
                    task_desc_chars=len(str(task.description or "")),
                    task_agent_chars=len(str(task.agent or "")),
                    current_tasks_status_chars=len(current_tasks_status_json),
                )

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
                            if self.is_progress_frame(agent_step_knowledge):
                                logger.info(
                                    "[DACProgress][SD-Orchestrator][a2a_tasks] relay progress task_id=%s agent=%s",
                                    task.id,
                                    task.agent,
                                )
                                await updater.add_artifact(
                                    [TextPart(text=agent_step_knowledge)],
                                    name=task_name,
                                )
                                if self.debug == 1:
                                    think.append(agent_step_knowledge)
                                continue
                            if self.debug == 1:
                                agent_knowledge_step = f"{agent_step_knowledge} \n"
                                await updater.add_artifact(
                                    [TextPart(text=agent_knowledge_step)],
                                    name=task_name,
                                )
                                think.append(agent_knowledge_step)
                            agent_steps_knowledge.append(agent_step_knowledge)

                        agent_steps_knowledge_str = "\n".join(agent_steps_knowledge)
                        log_size_trace(
                            "task-result-stream",
                            retry_count=retry_count,
                            task_id=task.id,
                            chunks_count=len(agent_steps_knowledge),
                            task_result_chars=len(agent_steps_knowledge_str),
                        )

                        current_task_status = ""
                        if agent_steps_knowledge_str == "Error occurred":
                            current_task_status = "fail"
                        else:
                            # 统一使用完整拼接结果判定：只要包含 success marker 即视为成功，
                            # 避免最后一个 chunk 不含 marker 导致误判 fail。
                            current_task_status = await self.get_last_step_status(agent_steps_knowledge_str)
                            if self.metadata.get('answer_model') == 'original':
                                logger.info(
                                    f">>>>>> [answer_model=original] OrchestratorAgent.a2a_tasks() "
                                    f"Task {task.id} 按 step_status_llm_check_success 判定状态: {current_task_status} <<<<<<"
                                )

                        self._update_task_status(task.id, current_task_status, agent_steps_knowledge_str)
                        logger.info(f"Task {task.id} completion status: {current_task_status}")
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="sd_orchestrator_task_finished",
                            message=f"completed task {task.id}",
                            status="done" if current_task_status == "complete" else "fail",
                            task_id=task.id,
                            extra=self._build_task_progress_extra(task.id, task.agent, current_task_status),
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
                            event="sd_orchestrator_task_finished",
                            message=f"failed task {task.id}",
                            status="fail",
                            task_id=task.id,
                            extra=self._build_task_progress_extra(task.id, task.agent, "fail"),
                        )
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

                else:
                    try:
                        agent_result = await self.a2a_non_stream(task.description, task.agent)
                        agent_knowledge_step = f"Task [{task.id}]: {task.description}; \nResult:\n {agent_result} \n"
                        log_size_trace(
                            "task-result-non-stream",
                            retry_count=retry_count,
                            task_id=task.id,
                            task_result_chars=len(str(agent_result or "")),
                        )

                        current_task_status = "complete" if agent_result and "Error" not in agent_result else "fail"
                        self._update_task_status(task.id, current_task_status, agent_result)
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="sd_orchestrator_task_finished",
                            message=f"completed task {task.id}",
                            status="done" if current_task_status == "complete" else "fail",
                            task_id=task.id,
                            extra=self._build_task_progress_extra(task.id, task.agent, current_task_status),
                        )
                        
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
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="sd_orchestrator_task_finished",
                            message=f"failed task {task.id}",
                            status="fail",
                            task_id=task.id,
                            extra=self._build_task_progress_extra(task.id, task.agent, "fail"),
                        )
                        current_agents_knowledge.append(self._format_task_knowledge(task.id, task.description, task.agent, f"Execution error: {str(e)}"))

            # 用本轮结果覆盖，保证交给总结 LLM 的始终是「最后一轮」
            last_round_knowledge = list(current_agents_knowledge)
            log_size_trace(
                "plan-round-finished",
                retry_count=retry_count,
                round_knowledge_items=len(last_round_knowledge),
                round_knowledge_total_chars=sum(len(str(item or "")) for item in last_round_knowledge),
            )
            
            if await self.should_retry_planning(self.tasks_status):
                retry_decisions += 1
                retry_count += 1
                if retry_count <= self.max_loop_count:
                    failed_tasks = [t for t in self.tasks_status if t.status == "fail"]
                    reason_code = self._select_retry_reason_code(failed_tasks)
                    retry_action = self._decide_retry_action(reason_code, same_plan_retry_count)
                    logger.info(
                        "=== Plan execution failed, preparing for retry attempt %d/%d | reason=%s | action=%s ===",
                        retry_count,
                        self.max_loop_count,
                        reason_code,
                        retry_action,
                    )
                    
                    failure_analysis = await self.analyze_failure_reasons(self.tasks_status)
                    logger.info(f"Failure analysis:\n{failure_analysis}")
                    log_size_trace(
                        "failure-analysis",
                        retry_count=retry_count,
                        failed_tasks_count=len(failed_tasks),
                        failure_analysis_chars=len(str(failure_analysis or "")),
                    )
                    
                    if self.debug == 1:
                        retry_msg = f"\n=== 计划执行遇到问题，正在进行第 {retry_count} 次重试 ===\n失败分析:\n{failure_analysis}\n"
                        # retry_msg = f"\n=== Plan execution encountered issues, performing retry attempt {retry_count} ===\nFailure analysis:\n{failure_analysis}\n"
                        await updater.add_artifact(
                            [TextPart(text=retry_msg)],
                            name=task_name,
                        )
                        think.append(retry_msg)

                    if retry_action == "abort":
                        failed_tasks_summary = self._build_failed_tasks_progress_summary(failed_tasks)
                        # Propagate a non-retryable marker upward so parent groups/orchestrators
                        # can also stop useless retries in higher layers.
                        if reason_code == "out_of_scope_non_retryable":
                            for ft in failed_tasks:
                                if NON_RETRYABLE_MARKER not in str(ft.answer or ""):
                                    ft.answer = f"{NON_RETRYABLE_MARKER} | {ft.answer}"
                                    logger.warning(
                                        "[NonRetryablePropagation][SemanticDomain] task_id=%s marker_appended_to_failed_answer=%s",
                                        ft.id,
                                        NON_RETRYABLE_MARKER,
                                    )
                            # Avoid adding an extra synthetic line when marker already exists
                            # in round knowledge; this keeps UI output concise.
                            if not any(NON_RETRYABLE_MARKER in str(k or "") for k in last_round_knowledge):
                                abort_notice = (
                                    f"{NON_RETRYABLE_MARKER} | retry aborted in semantic-domain orchestrator | "
                                    f"reason_code={reason_code}"
                                )
                                last_round_knowledge.append(abort_notice)
                            logger.warning(
                                "[NonRetryablePropagation][SemanticDomain] marker_forwarded_upstream=%s retry_count=%d failed_tasks=%d",
                                NON_RETRYABLE_MARKER,
                                retry_count,
                                len(failed_tasks),
                            )
                        elif reason_code == "repeated_failure_non_retryable":
                            if not any(NON_RETRYABLE_REPEAT_MARKER in str(k or "") for k in last_round_knowledge):
                                abort_notice = (
                                    f"{NON_RETRYABLE_REPEAT_MARKER} | retry aborted in semantic-domain orchestrator | "
                                    f"reason_code={reason_code}"
                                )
                                last_round_knowledge.append(abort_notice)
                        logger.warning(
                            "Detected non-retryable failure reason=%s, aborting retries to avoid meaningless replans | failed_tasks=%s",
                            reason_code,
                            failed_tasks_summary,
                        )
                        await self.emit_progress(
                            updater,
                            task_name,
                            event="sd_orchestrator_retry_aborted",
                            message="aborted retries due to non-retryable failure",
                            status="fail",
                            extra={
                                "reason_code": reason_code,
                                "retry_action": retry_action,
                                "retry_count": retry_count,
                                "same_plan_retry_count": same_plan_retry_count,
                                "failed_tasks": failed_tasks_summary,
                            },
                        )
                        break

                    if retry_action == "retry_same_plan":
                        same_plan_retry_count += 1
                        logger.info(
                            "Retrying same plan once due to reason=%s (same_plan_retry_count=%d)",
                            reason_code,
                            same_plan_retry_count,
                        )
                        await asyncio.sleep(self.loop_retry_delay)
                        continue

                    same_plan_retry_count = 0
                    replan_guidance = "请只输出可执行计划，优先修复失败任务，避免重复上轮失败的分配方式。"
                    replan_context = self._build_replan_context(
                        original_query=query,
                        current_tasks=current_tasks,
                        retry_count=retry_count,
                        reason_code=reason_code,
                        failure_analysis=failure_analysis,
                    )
                    log_size_trace(
                        "replan-input",
                        retry_count=retry_count,
                        planner_query_chars=len(str(query or "")),
                        replan_guidance_chars=len(str(replan_guidance or "")),
                        replan_context_chars=len(json.dumps(replan_context, ensure_ascii=False)),
                    )
                    new_tasks = await self.get_plan(
                        query,
                        replan_context=replan_context,
                        replan_guidance=replan_guidance,
                    )

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
                
        last_round_knowledge = _dedup_knowledge_items(last_round_knowledge)
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
        logger.info(
            "[MemoryOp][SD] ADD_MEMORY | user_id=%s agent_id=%s run_id=%s query_preview=%s",
            self.metadata.get('user_id', ''),
            self.agent_id,
            self.metadata.get('run_id', ''),
            (query or "")[:80],
        )
        logger.debug(f"add_memory metadata : user_id: {self.metadata['user_id']}, run_id:{self.metadata['run_id']}")
        
        async with self.data_services_client.session_context() as client:
            memory_response = await client.store_memory(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
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
            "[MemoryOp][SD] ADD_MEMORY done | agent_id=%s run_id=%s status=%s",
            self.agent_id,
            self.metadata.get('run_id', ''),
            _status,
        )
        logger.debug(f"add_memory, query= {query}, final_answer={final_answer_str}, response : {memory_response}")
        return memory_response

    async def get_memory(self, query) -> str:
        logger.info(
            "[MemoryOp][SD] GET_MEMORY | user_id=%s agent_id=%s run_id=%s query_preview=%s",
            self.metadata.get('user_id', ''),
            self.agent_id,
            self.metadata.get('run_id', ''),
            (query or "")[:80],
        )
        logger.debug(f"get_memory metadata :query:{query}, user_id: {self.metadata['user_id']}, run_id:{self.metadata['run_id']}")
        
        search_items = []

        async with self.data_services_client.session_context() as client:
            memory_search_response = await client.search_memories(
                query=query,
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
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
            "[MemoryOp][SD] GET_MEMORY done | agent_id=%s run_id=%s found_count=%d memory_chars=%d hit=%s",
            self.agent_id,
            self.metadata.get('run_id', ''),
            len(search_items),
            len(memory_texts_str),
            "yes" if memory_texts_str.strip() else "no",
        )
        if memory_texts_str.strip():
            _mem_display = memory_texts_str if len(memory_texts_str) <= 500 else memory_texts_str[:500] + "...[truncated]"
            logger.info("[MemoryOp][SD] GET_MEMORY content=%s", repr(_mem_display))
        logger.debug(f"get_memory response : {search_items}")

        return memory_texts_str

    async def add_history(self, query, final_answer, knowledge):
        final_answer_str = "".join(final_answer)
        logger.info(f"add_history metadata : user_id: {self.metadata['user_id']}, run_id:{self.metadata['run_id']}")
        
        create_request = CreateHistoryRequest(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
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

        logger.debug(f"OrchestratorAgent get_history metadata: user_id: {self.metadata['user_id']}, run_id:{self.metadata['run_id']}")
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        if normalize_history_turns(propagated.get("turns")):
            return history_messages_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
                user_id=self.metadata['user_id'],
                run_id=self.metadata['run_id'],
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
            history_payload_from_search_items(search_items, source="sd_summary_fallback")
        )

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

        log_size_trace(
            "summary-input",
            query_chars=len(str(query or "")),
            task_knowledges_items=len(task_knowledges or []),
            knowledge_chars=len(str(knowledge or "")),
            knowledge_tokens_est=int(len(str(knowledge or "")) / 4),
        )

        system_template = Orchestrator_INSTRUCTIONS_ZH

        # human_template = "background knowledge: {knowledge}。\n\n{memory}\n\nuser question:{query}"
        human_template = "background knowledge: {knowledge}。\n\nuser question:{query}"

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

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        prompt_chars_est = (
            len(str(system_template or ""))
            + len(str(query or ""))
            + len(str(knowledge or ""))
        )
        log_size_trace(
            "summary-prompt",
            prompt_chars_est=prompt_chars_est,
            prompt_tokens_est=int(prompt_chars_est / 4),
            enable_history=self.enable_history,
        )

        with langfuse.start_as_current_span(
            name="orchestrator-stream",
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

        log_size_trace(
            "summary-output",
            final_answer_chars=len("".join(final_answer)),
            final_answer_tokens_est=int(len("".join(final_answer)) / 4),
        )

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


class OrchestratorAgentExecutorSemanticDomain(AgentExecutor):
    """
    A Orchestrator Agent executor call PlannerAgent to get agents, than call agents.
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_descriptors:list = None,
        descriptor_types:list = None,
        debug: int = 0,
        data_services_url: str = None,
        enable_history: str = None,
        agent_id: str = None,
        dd_namespace:str = None,
        max_loops: int = 1,
        agent_card: AgentCard = None
    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.data_descriptors=data_descriptors
        self.descriptor_types=descriptor_types
        self.debug = debug
        self.data_services_url=data_services_url
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.dd_namespace = dd_namespace
        self.max_loops = max_loops
        self.agent_card = agent_card

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        logger.info(f"===== OrchestratorAgentExecutor, user query is {query}.")
        
        metadata = context.metadata
        logger.info(f"===== OrchestratorAgentExecutor, user request metadata is {metadata}.")
        _md = metadata if isinstance(metadata, dict) else {}
        _xc = _md.get("extra_context")
        _xc_s = str(_xc or "").strip()
        if _xc_s:
            logger.info(
                "[Execute][SDOrchestrator] extra_context (%d chars):\n%s",
                len(_xc_s),
                _xc_s,
            )
        else:
            logger.info(
                "[Execute][SDOrchestrator] extra_context: (absent or empty) raw=%r",
                _xc,
            )

        agent = OrchestratorAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            descriptor_types=self.descriptor_types,
            debug=self.debug,
            data_services_url=self.data_services_url,
            metadata=metadata,
            enable_history=self.enable_history,
            agent_id=self.agent_id,
            dd_namespace= self.dd_namespace,
            max_loops= self.max_loops,
            agent_card= self.agent_card

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
            not_found_agents = "Not found agents. You can provide more information."
            await agent.emit_progress(
                updater,
                f'{agent.agent_name}-result',
                event="sd_orchestrator_plan_empty",
                message="did not find an executable plan",
                status="fail",
                extra={"task_count": 0},
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
            plan_msg, plan_extra = OrchestratorAgent.build_sd_plan_ready_progress(
                task_list=steps,
                user_query=query,
            )
            await agent.emit_progress(
                updater,
                f'{agent.agent_name}-result',
                event="sd_orchestrator_plan_ready",
                message=plan_msg,
                status="done",
                extra=plan_extra,
            )
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

            # answer_model=original: 跳过 LLM 总结，直接返回 expert agent 的原始知识
            answer_model = metadata.get('answer_model', '')
            if answer_model == "original":
                logger.info(">>>>>> [answer_model=original] OrchestratorAgent.execute() 跳过 LLM 总结，直接返回 expert agent 原始知识 <<<<<<")
                await agent.emit_progress(
                    updater,
                    task_name,
                    event="sd_orchestrator_summary_skipped",
                    message="skipped summary because answer_model=original",
                    status="done",
                    extra={"reason": "answer_model_original"},
                )
                # answer_model=original 时 stream() 被跳过，需在此显式写入 memory，否则后续 get_memory 永远查不到
                if task_knowledges:
                    if all(isinstance(item, list) for item in task_knowledges):
                        flat = []
                        for tk in task_knowledges:
                            flat.extend(tk)
                        final_answer = [str(x) for x in flat]
                    else:
                        final_answer = [str(tk) for tk in task_knowledges]
                    await agent.add_memory(query, final_answer)
            else:
                await agent.emit_progress(
                    updater,
                    task_name,
                    event="sd_orchestrator_summary_started",
                    message="started final summary",
                    status="running",
                    extra={"knowledge_items": len(task_knowledges or [])},
                )
                conversition = []
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
                            conversition.append(event['content'])
                    else:
                        await agent.emit_progress(
                            updater,
                            task_name,
                            event="sd_orchestrator_summary_finished",
                            message="finished final summary",
                            status="done",
                            extra={"answer_chars": len("".join(conversition).strip())},
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