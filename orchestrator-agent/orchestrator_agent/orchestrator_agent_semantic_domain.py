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
import time as _time
from typing import Any
from uuid import uuid4
from typing import Any, AsyncIterable, ClassVar, Dict, Literal, List, Optional, Union
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
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
    AgentCard,
    AgentCapabilities,
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
from langchain_core.tools import tool, StructuredTool
from .tool_call_utils import invoke_llm_with_tool

def truncate_progress_detail(text: str, limit: int = 4000) -> str:
    """Truncate a structured progress detail while keeping its line breaks.

    Distinct from _truncate_progress_message, which flattens newlines because it
    builds the one-line summary shown in the log header. The detail fields carry
    the planner's actual reasoning and plan, so collapsing them to a single line
    made them unreadable in the UI even before the length limit clipped them.
    """
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."



try:
    from skill_sdk.skill.runner import SkillRunner  # noqa: F401  (used when local skills enabled)
except ImportError:  # pragma: no cover - skill_sdk is an optional runtime dep
    SkillRunner = None  # type: ignore[assignment]

try:
    from skill_sdk.tool.code_execution import CodeExecution
except ImportError:  # pragma: no cover
    CodeExecution = None  # type: ignore[assignment,misc]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "
SUMMARY_FRAME_PREFIX = "[[DAC_SUMMARY]] "

# Planner: upstream orchestration outcomes (metadata.extra_context), not RAG knowledge.
PRIOR_EXECUTION_CONTEXT_EMPTY_HINT = (
    "（无：未携带来自上游编排或其他前置任务的执行结果。）"
)


def resolve_prior_execution_context_for_planner(metadata: Optional[Dict[str, Any]]) -> str:
    """Build the prior-task-outcomes block for the planner LLM.

    Source: ``metadata['extra_context']`` from parent orchestration (e.g. Semantic Group).
    This must stay separate from **[执行上下文]** (RAG / get_knowledge), by design.
    """
    if not isinstance(metadata, dict):
        return PRIOR_EXECUTION_CONTEXT_EMPTY_HINT
    raw = str(metadata.get("extra_context") or "").strip()
    return raw if raw else PRIOR_EXECUTION_CONTEXT_EMPTY_HINT

# Do not overwrite DASHSCOPE_API_KEY - use env or explicit api_key for real LLM

# System Instructions to the Planner Agent

PLANNER_COT_INSTRUCTIONS_ZH = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
根据业务领域将用户查询分解为可执行任务。你必须通过 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]** 建立反馈闭环，确保规划路径既能解决指代关系，又能避免重复失败、复用已有数据。

## 战略思考过程（思维链）
在调用 `make_plan_cmd` 工具之前，请严格执行以下 **业务领域决策流**：

1. **业务领域提取**：识别查询中的核心业务实体（如“订单”、“财务”、“天气”），锁定其所属的业务边界。
2. **反馈闭环分析**：
   - 结合 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]**：若上一轮失败，必须根据 `replan_context` 中的报错信息进行“避坑”设计。但避坑是指调整任务拆分方式、更换 Agent 或补充必要约束，**绝非**把上一轮返回的具体数值（如某个订单ID、用户ID、姓名）直接写进任务描述，除非该数值本就是用户原始问题中明确给定的。
3. **领域主权映射**：
   - **主权优先**：将任务分配给负责该领域的 Agent。若某 Agent 是该领域的唯一代表，将其视为**通用入口**，无视其“不执行查询”等技术性免责声明。
   - **隐含能力**：假定领域专家拥有该业务范畴内的全量知识（如“交易专家”天然能“分析订单分布”）。
4. **依赖编排**：若当前任务**绝对依赖于**上一步产出的某个确切值（例如用户追问“把它删掉”中的“它”必须从历史中解析出具体 ID），才可将该值写入 `description`。写入时只取完成任务所必需的最小信息，并保留原始问题中的表达形式（如订单编号保持字符串 `'ORD-2025-00001'`，绝不替换为内部数字 ID）。**严禁**将执行过程中返回的冗余数据（如用户姓名、邮箱、其他无关字段）混入描述。

## 智能体选择与任务规则（必须严格遵守）
1. **主权优先**：根据哪个智能体的领域覆盖了主题事项来分配任务。
2. **任务分解**：仅当查询确实涉及**多个不同领域**或存在**明确的先后依赖**时，才拆分为多个任务。不要将一个简单问题过度拆分。
3. **"无对应"协议**：仅当任务的议题完全超出所有可用智能体的领域范围时，才使用"NONE"。
4. **名称准确性**：`agent` 字段必须与智能体列表中的“名称”完全一致。


## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化、修改或缩水问题。**

1. **忠实转述与最小必要依赖注入**：
   - 任务描述必须**原样反映用户问题中所有明确要求**（如具体订单编号、时间范围、统计指标）。
   - 若任务**确实依赖**上一步解析出的某个值（且该值在用户原话中以指代形式出现），才可将该值以用户原始表述的形式补入描述。补入时只添加该必要值，**不附带任何额外解释、历史执行细节或中间结果**。
   - **绝对禁止**将 `replan_context`、`prior_execution_context` 中返回的具体 id、姓名、数量等作为“背景知识”直接描述给下游 Agent。
   - **绝对禁止**在描述中添加对系统能力、表结构缺失的判断（如“系统无支付表”“请按可用数据返回”），此类判断应由下游 Agent 自行处理，规划器不得越权。

2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户“查订单” → `description`：“查询订单情况” ✅
   - **错误示例**：用户“查订单” → `description`：“查询2024年Q4电子产品订单及同比增长” ❌（捏造了时间、类别、指标）
   - **错误示例（新增强调）**：用户“查询订单ORD-2025-00001的支付记录” → 描述中写：“查询订单ORD-2025-00001的支付记录。注意：上一轮已确认该订单对应order_id=1，且无支付表，请按可用数据返回。” ❌（注入了内部 id 和自行判断）

3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。即使在重规划时，也要克制补充细节的冲动，只调整任务结构或 Agent 指定，不堆砌历史数据。

---

**[可用智能体] (Agents):**
{agents}


**[前置任务执行情况] (Prior task outcomes — not RAG knowledge):**
{prior_execution_context}
*注：来自上层编排已完成的子任务产出（例如 Semantic Group 通过请求 metadata 传入的 `extra_context`）。**此块不是知识库检索结果，不得与下方 [执行上下文] 混淆。** 若用户问题依赖其中的字段，必须在 `description` 中写入具体值，但仅限用户原问题中已明确提及的字段值，且保持原格式，不添加内部 id 或冗余数据。*


**[执行上下文] (Information):**
{information}


**[上一轮的执行结果]:**
{replan_context}
*注：包含**本 Orchestrator 内**已执行的任务 ID、任务描述、执行 Agent 以及执行结果（成功/失败/具体数据）；重试时 JSON 内带有 `prior_execution_context` 字段，与上方 **[前置任务执行情况]** 对齐。*


**[replan的指导规则]（仅在重试时提供，首轮通常为空）：**
{replan_guidance}

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本，也不要返回 JSON Schema 的 `properties` 包装。

工具参数结构：
   - `thought_process`：关于领域映射和主权原则的简明推理。
   - `original_query`：逐字复制原始用户输入，必须保留全部字符、空格、引号和标点，不得改写、规范化或删减。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务或问题。必须忠实于用户原始表述，禁止添加额外条件，禁止注入历史执行中的具体数值或对系统能力的判断。对比性追问需继承完整上下文；指代性追问需补充上下文使其自包含，但仅限于补全指代对象本身。
     - `agent`：确切的智能体名称或"NONE"。

## `make_plan_cmd` 工具参数示例
{instructions}

或当未找到智能体时：
{none_instructions}

问题：

"""


PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
根据业务领域将用户查询分解为可执行任务。你必须通过 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]** 建立反馈闭环，结合 **[对话历史]** 的语境，确保规划路径既能解决指代关系，又能避免重复失败、复用已有数据。

## 战略思考过程（思维链）
在调用 `make_plan_cmd` 工具之前，请严格执行以下 **业务领域决策流**：

1. **业务领域提取**：识别查询中的核心业务实体（如“订单”、“财务”、“天气”），锁定其所属的业务边界。
2. **反馈闭环分析**：
   - 结合 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]**：若上一轮失败，必须根据 `replan_context` 中的报错信息进行“避坑”设计。但避坑是指调整任务拆分方式、更换 Agent 或补充必要约束，**绝非**把上一轮返回的具体数值（如某个订单ID、用户ID、姓名）直接写进任务描述，除非该数值本就是用户原始问题中明确给定的。
3. **领域主权映射**：
   - **主权优先**：将任务分配给负责该领域的 Agent。若某 Agent 是该领域的唯一代表，将其视为**通用入口**，无视其“不执行查询”等技术性免责声明。
   - **隐含能力**：假定领域专家拥有该业务范畴内的全量知识（如“交易专家”天然能“分析订单分布”）。
4. **依赖编排**：若当前任务**绝对依赖于**上一步产出的某个确切值（例如用户追问“把它删掉”中的“它”必须从历史中解析出具体 ID），才可将该值写入 `description`。写入时只取完成任务所必需的最小信息，并保留原始问题中的表达形式（如订单编号保持字符串 `'ORD-2025-00001'`，绝不替换为内部数字 ID）。**严禁**将执行过程中返回的冗余数据（如用户姓名、邮箱、其他无关字段）混入描述。

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

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化、修改或缩水问题。**

1. **忠实转述与最小必要依赖注入**：
   - 任务描述必须**原样反映用户问题中所有明确要求**（如具体订单编号、时间范围、统计指标）。
   - 若任务**确实依赖**上一步解析出的某个值（且该值在用户原话中以指代形式出现），才可将该值以用户原始表述的形式补入描述。补入时只添加该必要值，**不附带任何额外解释、历史执行细节或中间结果**。
   - **绝对禁止**将 `replan_context`、`prior_execution_context` 中返回的具体 id、姓名、数量等作为“背景知识”直接描述给下游 Agent。
   - **绝对禁止**在描述中添加对系统能力、表结构缺失的判断（如“系统无支付表”“请按可用数据返回”），此类判断应由下游 Agent 自行处理，规划器不得越权。

2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户“查订单” → `description`：“查询订单情况” ✅
   - **错误示例**：用户“查订单” → `description`：“查询2024年Q4电子产品订单及同比增长” ❌（捏造了时间、类别、指标）
   - **错误示例（新增强调）**：用户“查询订单ORD-2025-00001的支付记录” → 描述中写：“查询订单ORD-2025-00001的支付记录。注意：上一轮已确认该订单对应order_id=1，且无支付表，请按可用数据返回。” ❌（注入了内部 id 和自行判断）

3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。即使在重规划时，也要克制补充细节的冲动，只调整任务结构或 Agent 指定，不堆砌历史数据。

---

**[对话历史] (History):**
{history}
*注：包含用户与系统的自然语言对话，用于理解语境和指代。*


**[可用智能体] (Agents):**
{agents}


**[前置任务执行情况] (Prior task outcomes — not RAG knowledge):**
{prior_execution_context}
*注：来自上层编排已完成的子任务产出（例如 Semantic Group 通过请求 metadata 传入的 `extra_context`）。**此块不是知识库检索结果，不得与下方 [执行上下文] 混淆。** 若用户问题依赖其中的字段，必须在 `description` 中写入具体值，但仅限用户原问题中已明确提及的字段值，且保持原格式，不添加内部 id 或冗余数据。*


**[执行上下文] (Information):**
{information}


**[上一轮的执行结果]:**
{replan_context}
*注：包含**本 Orchestrator 内**已执行的任务 ID、任务描述、执行 Agent 以及执行结果（成功/失败/具体数据）；重试时 JSON 内带有 `prior_execution_context` 字段，与上方 **[前置任务执行情况]** 对齐。*


**[replan的指导规则]（仅在重试时提供，首轮通常为空）：**
{replan_guidance}

---

## 工具调用要求
必须调用 `make_plan_cmd` 工具输出规划结果，直接填充工具参数字段。不要直接输出自然语言或 JSON 文本，也不要返回 JSON Schema 的 `properties` 包装。

工具参数结构：
   - `thought_process`：关于领域映射和主权原则的简明推理。
   - `original_query`：逐字复制原始用户输入，必须保留全部字符、空格、引号和标点，不得改写、规范化或删减。
   - `tasks`：包含以下字段的对象列表：
     - `id`：整数（从1开始）。
     - `description`：转述给智能体的子任务或问题。必须忠实于用户原始表述，禁止添加额外条件，禁止注入历史执行中的具体数值或对系统能力的判断。对比性追问需继承完整上下文；指代性追问需补充上下文使其自包含，但仅限于补全指代对象本身。
     - `agent`：确切的智能体名称或"NONE"。

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

2. **信息处理**
   * **精确匹配**：若 `knowledge` 包含原始问题所需的全部精确信息，请直接进行整合归纳，给出直接答案。
   * **证据不足**：若 `knowledge` 缺少回答所必需的精确维度，应明确说明无法确认或仅部分可答；不要用弱相关、近似或过程性数据冒充精确答案。
   * **退守参考（可选）**：仅当任务状态为成功且 expert 未否定结论时，才可补充最接近的参考数据，并明确标注其口径或时间范围与问题的差异。

3. **回答表现形式**
   * **逻辑性**：使用分点、表格或对比等方式让答案易于阅读。
   * **默认结构**：先用 1-2 句给出结论；当答案里包含多个数字、属性、对象信息或对比关系时，优先补一个简短的“关键依据”或“补充信息”小节，不要只输出一整段纯文本。
   * **轻量格式优先**：默认使用短标题、项目符号或简短表格提升可读性；保持结构轻量，不要堆砌大段背景说明。
   * **标题自然**：不要机械使用“直接答案”“补充说明”这类模板化标题；若需要标题，优先使用更自然的标题，如“结论”“核心结论”“关键信息”“关键依据”，并允许根据内容自适应命名。
   * **图表建议**：若用户要求“画图”且 `knowledge` 中包含 chart 包装的多维度或趋势性数据，你应该原封不动地保留 chart 包装好的结构化数据，浏览器的 UI 会负责渲染。

4. **判定“无法回答”的标准**
   * 触发条件：`knowledge` 与问题毫无关联、信息量极度匮乏，或相关任务块标注为失败/不可确认且无可信结论。
   * **此时回复**：明确说明无法确认或暂未找到用户所问对象/指标；不要用失败任务中的过程数据暗示已找到答案。

5. **多轮对话处理**
   * 始终以最新的 `knowledge` 为最高准则。若 `history` 中之前的结论与当前 `knowledge` 不符，请以 `knowledge` 为准，并可在回答中顺带说明数据已更新。

6. **证据约束（强制）**
   * 只输出可被 `knowledge` 直接支持的结论。
   * 每个任务块若标注「任务状态」为 fail，或结果中声明执行失败/不可作为事实引用，则该块内的具体数据（记录、数字、字段值）**不得**写入最终结论，只能用于说明“该子任务未成功完成”。
   * 若同一问题存在成功与失败任务块，优先采信成功块；失败块不能 override 成功结论，也不能单独拼出实体级答案。

7. **收敛输出（强制）**
   * 必须先给结论，首段 1-2 句内明确回答用户问题核心结论（不要先讲过程）。
   * 默认使用轻量结构化表达提升可读性，例如短标题、项目符号或简短表格；不要输出成没有层次的一大段纯文本。
   * 若用户未明确要求“方法对比/扩展建议/治理建议/补充分析”，默认不要主动展开这些内容。
   * 补充内容只保留与用户问题直接相关的 2-4 个要点；保持表达简洁，但不要为了简短牺牲可读性（图表原始结构化数据透传场景除外）。
"""

SUMMARY_HUMAN_TEMPLATE_ZH = (
    "background knowledge: {knowledge}。\n\n"
    "user question:{query}\n\n"
    "【重要提示】background knowledge 中每个任务块都标注了「任务状态」。"
    "状态为「fail」的任务，其返回的数据可能是局部/不完整/不正确的，"
    "严禁将其中的具体数据（如查询到的记录、数字、字段值）当作事实引用。"
    "状态为「fail」的任务数据仅能说明「该任务未成功完成」，不能证明任何事实性结论。"
)

DOC_ORCHESTRATOR_INSTRUCTIONS_ZH = Orchestrator_INSTRUCTIONS_ZH + """
8. **文档域专用：参考材料，非实体查询结果（强制）**
   * 你总结的是**文档/RAG 检索结果**，不是数据库 live query。职责是提供字段含义、接口说明、表结构描述、业务口径——**不是**替 structured 回答「某订单/某用户是谁」。
   * **禁止**把文档/API 示例里的占位数据说成用户所问实体的答案，例如：
     - 用户问订单编号 `ORD-2025-00001`，文档示例里只有 `order_id: 1001` 或示例用户「张三」→ **不得**写「ORD-2025-00001 的购买用户是张三」；
     - 不得把示例 JSON、Swagger 样例、教程里的记录当作该业务键在系统中的真实映射。
   * 仅当 `knowledge` 中**明确出现与用户问题相同的业务标识**（如完全一致的订单号字符串、用户名）且任务状态为成功时，才可作实体结论；否则必须写 **无法根据文档确认** 该实体。
   * 可以说明：文档中订单编号字段类型（如整数 order_id）、是否存在支付相关表/接口、示例数据的格式——但必须标注为**文档描述/示例**，与用户所问实体是否匹配要单独说明。
   * 若 `knowledge` 仅有示例、无与用户问题精确匹配的条目，结论必须是「文档未记载该订单/用户，无法确认」，**不要**用最近似的示例用户或订单顶替。
"""

DOC_SUMMARY_HUMAN_TEMPLATE_ZH = (
    "background knowledge: {knowledge}。\n\n"
    "user question:{query}\n\n"
    "【文档域总结 · 必读】"
    "你输出的是**参考材料总结**，供下游理解字段/接口/口径，不是 structured 数据库查询的最终实体答案。"
    "禁止把 API/文档示例中的 order_id、user_id、示例姓名邮箱等写成用户所问业务编号（如 ORD-*）的真实查询结果。"
    "若 knowledge 中没有与用户问题完全一致的业务标识，结论必须是无法确认，不得用示例数据凑答案。"
    "同时遵守任务状态规则：fail 任务中的数据不可作为事实引用。"
)

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


class DependencyJudgeResult(BaseModel):
    """Tool-call schema for _judge_task_dependency LLM output."""
    model_config = {"extra": "ignore"}
    needs_upstream: bool = Field(default=False, description="Whether the current task relies on upstream output")
    unmet: bool = Field(default=False, description="Whether any dependency is unmet")
    unmet_upstream_ids: List[int] = Field(default_factory=list, description="IDs of upstream tasks that block dispatch")
    missing_fields: List[str] = Field(default_factory=list, description="Data fields missing from upstream results")
    rationale: str = Field(default="", description="One-sentence reason in user's language")


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

# ---------------------------------------------------------------------------
# Local skill (route B) configuration
# ---------------------------------------------------------------------------
# When enabled, the orchestrator carries a process-wide SkillRunner and exposes
# it to the planner as a synthetic AgentCard named ``LOCAL_SKILL_AGENT_NAME``.
# Tasks the planner routes to this agent are executed in-process via
# ``SkillRunner.plan_and_run`` instead of being dispatched over A2A.
#
# Environment variables (all optional):
#   ENABLE_LOCAL_SKILLS            : "true" to turn the feature on (default: true)
#   LOCAL_SKILLS_DIR               : directory containing skill zip packs (default: /app/skills/)
#   LOCAL_SKILL_AGENT_NAME         : display name of the synthetic card (default: LocalSkill)
#   LOCAL_SKILL_MAX_STEPS          : per-call ReAct step budget passed to SkillRunner
#   LOCAL_SKILL_CMD_TIMEOUT_SEC    : subprocess timeout passed to SkillRunner
#   LOCAL_SKILL_MAX_CONCURRENCY    : max concurrent plan_cmd executions, 0 = unlimited
#   LOCAL_SKILL_FALLBACK_ON_NONE   : when planner emits agent=NONE, try LocalSkill first
#   LOCAL_SKILL_INJECT_CARD        : auto|always|never (default: auto)
#   LOCAL_SKILL_FORCE_ATTACHED     : keep all explicitly attached skills inside this DAC
#
# ``USE_ONLY_OWN_CAPABILITY`` (default true, read in ``list_agent_cards``) is separate:
# when true, skip the external agent registry and use only ``self.agent_card`` at
# http://localhost:10101 plus (when enabled) the LocalSkill card. It does **not**
# disable LocalSkill injection.
LOCAL_SKILL_AGENT_NAME = os.getenv("LOCAL_SKILL_AGENT_NAME", "LocalSkill").strip() or "LocalSkill"
LOCAL_SKILLS_ENABLED = os.getenv("ENABLE_LOCAL_SKILLS", "true").strip().lower() in ("1", "true", "yes")
LOCAL_SKILLS_DIR = os.getenv("LOCAL_SKILLS_DIR", "/app/skills/").strip()
LOCAL_SKILL_FALLBACK_ON_NONE = os.getenv("LOCAL_SKILL_FALLBACK_ON_NONE", "true").strip().lower() in ("1", "true", "yes")
LOCAL_SKILL_INJECT_MODE = os.getenv("LOCAL_SKILL_INJECT_CARD", "auto").strip().lower()
LOCAL_SKILL_FORCE_ATTACHED = os.getenv(
    "LOCAL_SKILL_FORCE_ATTACHED",
    os.getenv("LOCAL_SKILL_FORCE_SINGLE", "false"),
).strip().lower() in ("1", "true", "yes")
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

# ---------------------------------------------------------------------------
# Dependency guard (LLM-based, fail-close)
#
# When an earlier task in the current round has status="fail", the downstream
# task may silently produce a *plausible-looking* answer that masks the
# unresolved dependency. A small LLM judge decides whether the current task
# actually needs output from any prior task and — for prior tasks that did
# complete — whether the required data is present in their answer.
#
# Knobs:
#   DEPENDENCY_CHECK_ENABLED       : master switch (default on)
#   DEPENDENCY_CHECK_TIMEOUT_SEC   : per-judge timeout (fail-close on timeout)
#   DEPENDENCY_CHECK_MAX_UPSTREAM  : cap how many prior tasks are fed in
#   DEPENDENCY_CHECK_ANSWER_CHARS  : cap per-upstream answer length
# ---------------------------------------------------------------------------

DEPENDENCY_UNMET_REASON = "dependency_unmet"
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

# Raised by the pre-flight dependency guard in ``a2a_tasks`` when a task's
# description references an upstream task id that either (a) is missing from
# the current plan entirely, or (b) is present but ended with status='fail'.
# Preserved through ``_classify_task_failure_reason`` re-classification the
# same way LocalSkill codes are.
DEPENDENCY_UNMET_REASON = "dependency_unmet"

# Detect references like "任务1", "任务 1", "Task 1", "task#1", "step 2", "步骤3".
# Only ASCII digits are captured; non-Latin number words ("一"/"二") are
# intentionally not supported — planner output always uses Arabic numerals.
_UPSTREAM_TASK_REFERENCE_RE = re.compile(
    r"(?:任务|步骤|task|step)\s*#?\s*(\d+)",
    re.IGNORECASE,
)

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

        # Upstream orchestration outcomes (metadata.extra_context) — not RAG; separate from ``information``.
        prior_execution_context = resolve_prior_execution_context_for_planner(self.metadata)
        _pec_raw = ""
        if isinstance(self.metadata, dict):
            _pec_raw = str(self.metadata.get("extra_context") or "").strip()
        if _pec_raw:
            logger.info(
                " === PlannerAgent.make_plan prior_execution_context (extra_context): %d chars",
                len(_pec_raw),
            )

        system_template = ""
        if self.enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_ZH

        replan_context_text = json.dumps(replan_context or {}, ensure_ascii=False)
        replan_guidance_text = (replan_guidance or "").strip()

        human_template = "{query}"

        # Few-shot values below illustrate make_plan_cmd arguments. They are
        # injected as semantic examples, not as instructions to emit JSON text.
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
                input_variables=[
                    "history",
                    "agents",
                    "prior_execution_context",
                    "information",
                    "replan_context",
                    "replan_guidance",
                ],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=[
                    "agents",
                    "prior_execution_context",
                    "information",
                    "replan_context",
                    "replan_guidance",
                ],
                partial_variables={"instructions": json_prompt_instructions_en, "none_instructions": json_prompt_no_agent_en},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']
        history = ""
        planner_prompt_chars = (
            len(str(system_template or ""))
            + len(str(query or ""))
            + len(str(system_prompt_agents or ""))
            + len(str(prior_execution_context or ""))
            + len(str(information or ""))
            + len(str(replan_context_text or ""))
            + len(str(replan_guidance_text or ""))
        )

        if self.enable_history == "enable":
            history = await self.get_history()
            planner_prompt_chars += len(str(history or ""))

        log_size_trace(
            "planner-input",
            query_chars=len(str(query or "")),
            agents_chars=len(str(system_prompt_agents or "")),
            prior_execution_context_chars=len(str(prior_execution_context or "")),
            information_chars=len(str(information or "")),
            history_chars=len(str(history or "")),
            replan_context_chars=len(str(replan_context_text or "")),
            replan_guidance_chars=len(str(replan_guidance_text or "")),
            planner_prompt_chars=planner_prompt_chars,
            planner_prompt_tokens_est=int(planner_prompt_chars / 4),
        )

        # Build initial messages (system + human) for tool-calling loop
        format_kwargs = {
            "query": query,
            "agents": system_prompt_agents,
            "prior_execution_context": prior_execution_context,
            "information": information,
            "replan_context": replan_context_text,
            "replan_guidance": replan_guidance_text,
        }
        if self.enable_history == "enable":
            format_kwargs["history"] = history
        messages = chat_prompt.format_messages(**format_kwargs)

        tasks = None

        with langfuse.start_as_current_span(
            name="orchestrator-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": query,
                    "prior_execution_context_chars": len(str(prior_execution_context or "")),
                    "prior_execution_context_non_empty": bool(_pec_raw),
                },
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
                        "  task id=%s agent=%s description=%s",
                        t.id,
                        t.agent,
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

        log_size_trace(
            "planner-output",
            llm_output_chars=len(str(tasks.model_dump_json())),
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
        data_descriptors:list = None,
        descriptor_types:list = None,
        debug: int = 0,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        dd_namespace:str = None,
        max_loops: int = None,
        agent_card: AgentCard = None,
        skill_runner: "SkillRunner | None" = None,
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
        self.skill_runner = skill_runner
        self.local_skill_agent_name = LOCAL_SKILL_AGENT_NAME
        if self.skill_runner is not None:
            try:
                _loaded = len(getattr(self.skill_runner.lister, "skills", []) or [])
            except Exception:  # noqa: BLE001
                _loaded = -1
            logger.info(
                "[LocalSkill][Bind] OrchestratorAgent bound SkillRunner: agent_name=%s "
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

    def _single_local_skill(self):
        """Return the sole loaded skill, or ``None`` when the inventory is not singular."""
        if not self._has_local_skill():
            return None
        try:
            skills = list(getattr(self.skill_runner.lister, "skills", []) or [])
        except Exception:  # noqa: BLE001
            logger.exception("[LocalSkill][ForceSingle] failed to inspect skill inventory")
            return None
        return skills[0] if len(skills) == 1 else None

    def _has_loaded_local_skills(self) -> bool:
        if not self._has_local_skill():
            return False
        try:
            return bool(getattr(self.skill_runner.lister, "skills", []) or [])
        except Exception:  # noqa: BLE001
            logger.exception("[LocalSkill][ForceAttached] failed to inspect skill inventory")
            return False

    def _should_force_attached_local_skills(self) -> bool:
        return LOCAL_SKILL_FORCE_ATTACHED and self._has_loaded_local_skills()

    async def _run_local_skill_query(
        self,
        query: str,
        *,
        user_id: str,
        run_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Run the sole attachment directly when forced; otherwise use normal selection."""
        skill = self._single_local_skill()
        if LOCAL_SKILL_FORCE_ATTACHED and skill is not None:
            logger.info(
                "[LocalSkill][ForceSingle] executing skill=%s directly inside DAC",
                getattr(skill, "name", "(unknown)"),
            )
            return await self.skill_runner.run(
                query=query,
                skill=skill,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        return await self.skill_runner.plan_and_run(
            query=query,
            user_id=user_id,
            run_id=run_id,
            trace_id=trace_id,
        )

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
        # auto: inject when we have loaded zip skills. USE_ONLY_OWN_CAPABILITY only controls
        # whether list_agent_cards hits the external registry — it must NOT block LocalSkill.
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
        """Overwrite the failure_reason_code written by ``_update_task_status``.

        ``_update_task_status`` re-runs ``_classify_task_failure_reason`` when
        no ``reported_reason_code`` is present, which would drop our code. We
        intentionally set the reason after calling ``_update_task_status``.
        """
        if not reason_code:
            return
        for t in self.tasks_status:
            if t.id == task_id:
                t.failure_reason_code = reason_code
                break

    # ------------------------------------------------------------------
    # Dependency guard (LLM-based, fail-close)
    # ------------------------------------------------------------------

    def _dependency_upstream_snapshot(
        self, current_task_id: int
    ) -> list[dict[str, Any]]:
        """Collect prior tasks in this round as context for the dependency judge.

        Keeps the payload small and deterministic so the judge prompt stays
        cheap: capped count, truncated answers, no internal reason codes that
        would bias the LLM.
        """
        snapshot: list[dict[str, Any]] = []
        for ts in self.tasks_status:
            if ts.id >= current_task_id:
                continue
            answer_raw = str(ts.answer_final or ts.answer or "")
            if DEPENDENCY_CHECK_ANSWER_CHARS > 0 and len(answer_raw) > DEPENDENCY_CHECK_ANSWER_CHARS:
                answer_raw = answer_raw[:DEPENDENCY_CHECK_ANSWER_CHARS] + "...(truncated)"
            snapshot.append(
                {
                    "id": ts.id,
                    "description": str(ts.description or ""),
                    "agent": str(ts.agent or ""),
                    "status": str(ts.status or ""),
                    "answer_excerpt": answer_raw,
                }
            )
        if DEPENDENCY_CHECK_MAX_UPSTREAM > 0 and len(snapshot) > DEPENDENCY_CHECK_MAX_UPSTREAM:
            # Prefer keeping the most recent upstream tasks.
            snapshot = snapshot[-DEPENDENCY_CHECK_MAX_UPSTREAM:]
        return snapshot

    async def _judge_task_dependency(
        self,
        task: "PlannerTask",
        upstream: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Ask the planner LLM whether ``task`` can proceed given upstream state.

        Returns a dict:
            {
              "unmet": bool,                    # True → block dispatch
              "needs_upstream": bool,           # judge's raw answer (diagnostic)
              "unmet_upstream_ids": [int, ...], # which upstream ids block us
              "missing_fields": [str, ...],     # data fields judge couldn't find
              "rationale": str,                 # short explanation
              "error": str | None,              # non-None on fail-close path
            }

        Never raises; on LLM errors / timeouts / malformed output, returns a
        fail-close verdict (``unmet=True``, ``error`` set) per config.
        """
        default_fail_close = {
            "unmet": True,
            "needs_upstream": True,
            "unmet_upstream_ids": [u["id"] for u in upstream if u.get("status") == "fail"],
            "missing_fields": [],
            "rationale": "",
            "error": None,
        }

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
        human_template = (
            "CURRENT_TASK:\n"
            "{current_task}\n\n"
            "UPSTREAM_TASKS (executed earlier in this round, ordered by id):\n"
            "{upstream_tasks}"
        )

        try:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["current_task", "upstream_tasks"],
            )
            human_prompt = HumanMessagePromptTemplate.from_template(human_template)
            chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

            current_task_payload = json.dumps(
                {
                    "id": task.id,
                    "description": str(task.description or ""),
                    "agent": str(task.agent or ""),
                },
                ensure_ascii=False,
            )
            upstream_payload = json.dumps(upstream, ensure_ascii=False)

            messages = await chat_prompt.aformat_prompt(
                current_task=current_task_payload,
                upstream_tasks=upstream_payload,
            )
            messages = messages.to_messages()

            judge_tool = StructuredTool(
                name="judge_dependency",
                description="Judge whether a task can proceed given upstream dependency state.",
                args_schema=DependencyJudgeResult,
                func=None,
                coroutine=None,
            )

            parsed = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=judge_tool,
                messages=messages,
                metadata=self.metadata,
                tool_choice="judge_dependency",
                span_name="dependency-judge",
                span_input={"task_id": task.id},
            )
            if not isinstance(parsed, dict):
                logger.warning(
                    "[DependencyGuard] malformed judge output — fail-close for task_id=%s",
                    task.id,
                )
                return {**default_fail_close, "error": "malformed_output"}

            unmet = bool(parsed.get("unmet", False))
            needs_upstream = bool(parsed.get("needs_upstream", unmet))
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
                "needs_upstream": needs_upstream,
                "unmet_upstream_ids": unmet_ids,
                "missing_fields": missing_fields,
                "rationale": rationale,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[DependencyGuard] judge raised — fail-close for task_id=%s err=%s",
                task.id,
                exc,
            )
            return {**default_fail_close, "error": "exception"}

    async def _preflight_dependency_check(
        self, task: "PlannerTask"
    ) -> Optional[dict[str, Any]]:
        """Return a verdict dict when the task should be blocked, else None.

        - Returns ``None`` when the feature is disabled, there are no upstream
          tasks, or the LLM judge says the dependency is met.
        - Returns the judge's verdict (with ``unmet=True``) when the task should
          be short-circuited with reason ``dependency_unmet``.
        """
        if not DEPENDENCY_CHECK_ENABLED:
            return None
        if not self.tasks_status:
            return None

        upstream = self._dependency_upstream_snapshot(task.id)
        if not upstream:
            return None

        # Cost control: only run the judge when at least one upstream task
        # actually failed; otherwise the dependency (if any) is trivially met.
        if not any((u.get("status") == "fail") for u in upstream):
            return None

        logger.info(
            "[DependencyGuard] checking task_id=%s upstream_count=%d failed_upstream_ids=%s",
            task.id,
            len(upstream),
            [u["id"] for u in upstream if u.get("status") == "fail"],
        )
        verdict = await self._judge_task_dependency(task, upstream)
        logger.info(
            "[DependencyGuard] verdict task_id=%s unmet=%s needs_upstream=%s "
            "unmet_upstream_ids=%s missing_fields=%s error=%s rationale=%r",
            task.id,
            verdict.get("unmet"),
            verdict.get("needs_upstream"),
            verdict.get("unmet_upstream_ids"),
            verdict.get("missing_fields"),
            verdict.get("error"),
            (verdict.get("rationale") or "")[:200],
        )
        if not verdict.get("unmet"):
            return None
        return verdict

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
            result = await self._run_local_skill_query(
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
            await updater.add_artifact([TextPart(text=dbg_text)], name=task_name)
            think.append(dbg_text)

        extra = {
            **self._build_task_progress_extra(task.id, self.local_skill_agent_name, status_code),
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
            event="sd_orchestrator_task_finished",
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
            result = await self._run_local_skill_query(
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
                task.id,
                task.description,
                self.local_skill_agent_name,
                final_answer,
                "complete",
            )
        )
        if self.debug == 1:
            dbg_text = (
                f"Task [{task.id}] via LocalSkill (NONE fallback"
                f"{f', skill={skill_name_used}' if skill_name_used else ''}):\n"
                f"{final_answer}\n"
            )
            await updater.add_artifact([TextPart(text=dbg_text)], name=task_name)
            think.append(dbg_text)

        await self.emit_progress(
            updater,
            task_name,
            event="sd_orchestrator_task_finished",
            message=f"completed task {task.id} via LocalSkill (NONE fallback)",
            status="done",
            task_id=task.id,
            extra={
                **self._build_task_progress_extra(task.id, self.local_skill_agent_name, "complete"),
                "execution_mode": "local_skill_fallback",
                "local_skill_name": skill_name_used,
                "reason_code": "local_skill_fallback_ok",
            },
        )
        return True

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
        *,
        recovery_retry_index: int = 0,
    ) -> TaskList:
        """recovery_retry_index: 0 = first plan from the request entrypoint (may use single-agent fast path).
        >= 1 = replan after failed execution rounds inside a2a_tasks (aligned with retry_count after increment);
        those calls always run make_plan for single-agent so the LLM sees replan_context.
        """

        if self._should_force_attached_local_skills():
            skills = list(getattr(self.skill_runner.lister, "skills", []) or [])
            logger.info(
                "[LocalSkill][ForceAttached] bypassing agent planner for %d attached skill(s)",
                len(skills),
            )
            return TaskList(
                thought_process="Explicitly attached skills are forced to execute inside this DAC.",
                original_query=query,
                tasks=[
                    PlannerTask(
                        id=1,
                        description=query,
                        agent=self.local_skill_agent_name,
                    )
                ],
            )

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            return None

        # Fast path: exactly one agent card and first attempt — skip LLM planner.
        # When LocalSkill is injected alongside the local expert, len >= 2 so this path is skipped.
        if len(self.agent_cards) == 1 and recovery_retry_index == 0:
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

        if len(self.agent_cards) == 1 and recovery_retry_index > 0:
            sole_name = self.agent_cards[0].name
            logger.info(
                "Single agent (%s), recovery_retry_index=%s — using LLM make_plan (replan after failure)",
                sole_name,
                recovery_retry_index,
            )

        # Single-agent replan or multi-agent path: LLM planner decomposes / refines tasks
        steps = await self.planner_agent.make_plan(
            query,
            self.agent_cards,
            replan_context=replan_context,
            replan_guidance=replan_guidance,
        )
        if steps is None:
            return None

        return steps


    async def list_agent_cards(self, query) -> list[AgentCard]:
        """Resolve which expert agents the planner may choose.

        If ``USE_ONLY_OWN_CAPABILITY`` is true (default), **does not** call the external
        agent registry: returns ``self.agent_card`` with ``url`` set to
        ``http://localhost:10101`` (the local expert), then optionally appends the
        synthetic LocalSkill card when route B is enabled and injection rules allow.

        If ``USE_ONLY_OWN_CAPABILITY`` is false, searches the agent registry for remote
        expert cards and appends LocalSkill the same way.

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
        # Default true: skip external registry; local expert only at localhost:10101 (+ LocalSkill).
        # Set to false/0/no to search the agent registry instead.
        use_only_own = (os.getenv("USE_ONLY_OWN_CAPABILITY", "true").strip().lower() in ("true", "1", "yes"))
        if use_only_own and self.agent_card is not None:
            _dump = getattr(self.agent_card, "model_dump", None) or getattr(self.agent_card, "dict", None)
            card_dict = dict(_dump()) if _dump else {}
            card_dict["url"] = "http://localhost:10101"
            logger.info(
                "[AgentCards] USE_ONLY_OWN_CAPABILITY=true — skipping agent registry; "
                "local expert url=http://localhost:10101 (LocalSkill may be appended next)"
            )
            return self._maybe_append_local_skill_card([AgentCard(**card_dict)])

        logger.info(
            "[AgentCards] USE_ONLY_OWN_CAPABILITY=false — querying agent registry "
            "(collection=%s)",
            os.getenv("CollectionName", "expert_agent_cards"),
        )
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
                agent_cards = self._maybe_append_local_skill_card(agent_cards)

                agent_names = [card.name for card in agent_cards]
                
                logger.info(f"Successfully retrieved {len(agent_cards)} agent cards, agent cards: {agent_names}")
                return agent_cards
            else:
                logger.warning(f"Search returned non-success status: {response.status}")
                return self._maybe_append_local_skill_card([])

        except Exception as e:
            logger.error(f'An error occurred during list_agent_cards: {e}')
            raise ValueError(f"An error occurred during list_agent_cards: {e}")

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
        planner_thought = truncate_progress_detail(thought_raw, 4000) if thought_raw else ""
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

    @staticmethod
    def build_summary_artifact(*, summary_text: str) -> str:
        """构造 DAC_SUMMARY 协议帧，携带 LLM 总结后的最终答案，SG Expert 解析后作为最终知识。"""
        payload: Dict[str, Any] = {
            "schema_version": "v1",
            "layer": "sd_orchestrator",
            "summary": summary_text or "",
        }
        return f"{SUMMARY_FRAME_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"

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
        return resolve_agent_card_by_planner_name(self.agent_cards, agent_name)

    def _utility_answer_model_for_a2a(self) -> str:
        """answer_model for utility a2a calls, derived from DescriptorTypes env (analyze_descriptor_types).

        Unstructured SD (doc domain): utilities are DocAgent → always ``original`` (RAG fast path).
        SG may still send ``summarized`` in request metadata; ``execute()`` uses that for DAC_SUMMARY.
        Structured/code SD: pass through request metadata unchanged.
        """
        upstream = str((self.metadata or {}).get("answer_model") or "").strip()
        _, agent_type, _ = self.planner_agent.analyze_descriptor_types()
        if agent_type == "unstructured":
            if upstream and upstream != "original":
                logger.info(
                    ">>>>>> [answer_model] SD Orchestrator a2a: utility=original "
                    "(descriptorType=unstructured; upstream=%s for execute summary) <<<<<<",
                    upstream,
                )
            return "original"
        return upstream

    def _summary_prompt_templates(self) -> tuple[str, str]:
        """Return (system_template, human_template) for execute() summary LLM."""
        _, agent_type, _ = self.planner_agent.analyze_descriptor_types()
        if agent_type == "unstructured":
            return DOC_ORCHESTRATOR_INSTRUCTIONS_ZH, DOC_SUMMARY_HUMAN_TEMPLATE_ZH
        return Orchestrator_INSTRUCTIONS_ZH, SUMMARY_HUMAN_TEMPLATE_ZH

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

        # answer_model: unstructured SD → utility original; execute() still uses request metadata
        am = self._utility_answer_model_for_a2a()
        if am:
            a2a_metadata['answer_model'] = am
            logger.info(
                ">>>>>> [answer_model=%s] OrchestratorAgent.a2a_stream() a2a answer_model=%s → agent=%s <<<<<<",
                self.metadata.get('answer_model', ''),
                am,
                agent_name,
            )

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

        # answer_model: unstructured SD → utility original; execute() still uses request metadata
        am = self._utility_answer_model_for_a2a()
        if am:
            a2a_metadata['answer_model'] = am
            logger.info(
                ">>>>>> [answer_model=%s] OrchestratorAgent.a2a_non_stream() a2a answer_model=%s → agent=%s <<<<<<",
                self.metadata.get('answer_model', ''),
                am,
                agent_name,
            )

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
        _a2a_timeout = float(os.getenv("A2A_REQUEST_TIMEOUT", "3600"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(_a2a_timeout, connect=10.0)) as httpx_client:
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

    def _format_task_knowledge(
        self,
        task_id: int,
        description: str,
        agent: str,
        result: str,
        status: str = "",
    ) -> str:
        """将单条任务结果格式化为大模型易读的块，便于总结时区分任务与结果。"""
        agent_label = (agent or "").strip() or "（未分配）"
        status_line = f"\n【任务状态】\n{status}\n" if status else ""
        if status == "fail":
            result = (
                "【此任务执行失败，以下内容为多步尝试过程摘要，其中的具体数据不可作为事实引用】\n"
                + (result or "").strip()
            )
        return (
            f"【任务 {task_id}】\n{description}\n\n"
            f"【执行 Agent】\n{agent_label}{status_line}\n【结果】\n{(result or '').strip()}"
        )

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
                task_status.marker_present = (
                    NON_RETRYABLE_MARKER in raw_answer
                    or NON_RETRYABLE_REPEAT_MARKER in raw_answer
                )
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
        # LocalSkill reason codes are set directly via ``_apply_local_skill_reason_code``
        # and must be preserved here (there is no ``reported_reason_code`` for the
        # synthetic LocalSkill agent). The dependency-guard code follows the
        # same "pre-set then preserve" contract.
        existing = str(getattr(task, "failure_reason_code", "") or "").strip()
        if existing in LOCAL_SKILL_FAIL_REASONS or existing == DEPENDENCY_UNMET_REASON:
            return existing
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
        # All LocalSkill failures allow a replan; the failed skill name is tracked in
        # ``execution_results`` so the planner naturally avoids LocalSkill next round.
        if reason_code in LOCAL_SKILL_FAIL_REASONS:
            return "replan"
        # Dependency-guard short-circuits: the downstream task never actually ran,
        # so the only sensible recovery is to let the planner redo the plan (e.g.
        # inline the dependency into the same task or reorder).
        if reason_code == DEPENDENCY_UNMET_REASON:
            return "replan"
        # retry_same_plan disabled: go straight to replan on execution_error / empty_answer instead of
        # re-running the identical plan once. Handler for retry_same_plan below is kept for easy revert.
        # if reason_code in {"execution_error", "empty_answer"} and same_plan_retry_count < 1:
        #     return "retry_same_plan"
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
            # LocalSkill codes — ranked above execution_error so the planner sees
            # a LocalSkill-specific hint before the generic one.
            "local_skill_declined",
            "local_skill_max_steps",
            "local_skill_no_finish",
            "local_skill_no_selection",
            "local_skill_not_found",
            "local_skill_error",
            # dependency_unmet ranks below LocalSkill-specific codes: when both
            # exist in the same round (e.g. task1 declined + task2 blocked),
            # the planner should first see the root cause (LocalSkill), not the
            # downstream consequence.
            DEPENDENCY_UNMET_REASON,
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
        pec_replan = ""
        if isinstance(self.metadata, dict):
            pec_replan = str(self.metadata.get("extra_context") or "").strip()
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
            # Same source as planner ``prior_execution_context`` / metadata.extra_context (raw; may be empty).
            "prior_execution_context": pec_replan,
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

                # ------------------------------------------------------------------
                # Pre-flight dependency guard (LLM-based, fail-close).
                #
                # Before routing to LocalSkill / NONE-fallback / A2A, check whether
                # this task references output from an upstream task in the current
                # round that already failed (or that completed without producing
                # the data we need). If so, short-circuit with reason
                # ``dependency_unmet`` so the replan context no longer contains a
                # fake "downstream succeeded while dependency failed" signal.
                # ------------------------------------------------------------------
                dep_verdict = await self._preflight_dependency_check(task)
                if dep_verdict is not None:
                    unmet_ids = list(dep_verdict.get("unmet_upstream_ids") or [])
                    missing_fields = list(dep_verdict.get("missing_fields") or [])
                    rationale = str(dep_verdict.get("rationale") or "").strip()
                    judge_error = dep_verdict.get("error")

                    ids_str = ", ".join(str(i) for i in unmet_ids) if unmet_ids else "(unknown)"
                    fields_str = ", ".join(missing_fields) if missing_fields else ""
                    detail_bits = [
                        f"blocked by unmet upstream task(s): [{ids_str}]",
                    ]
                    if fields_str:
                        detail_bits.append(f"missing fields: {fields_str}")
                    if rationale:
                        detail_bits.append(f"reason: {rationale}")
                    if judge_error:
                        detail_bits.append(f"judge_error: {judge_error} (fail-close)")
                    block_msg = (
                        "Skipped: this task depends on output from upstream tasks that did "
                        "not complete with the required data. "
                        + "; ".join(detail_bits)
                        + "."
                    )

                    logger.warning(
                        "[DependencyGuard] blocked task_id=%s agent=%s unmet_ids=%s "
                        "missing_fields=%s judge_error=%s",
                        task.id,
                        task.agent,
                        unmet_ids,
                        missing_fields,
                        judge_error,
                    )
                    self._update_task_status(task.id, "fail", block_msg)
                    # Must overwrite after _update_task_status, which otherwise
                    # reclassifies via ``_classify_task_failure_reason``.
                    self._apply_local_skill_reason_code(task.id, DEPENDENCY_UNMET_REASON)

                    await self.emit_progress(
                        updater,
                        task_name,
                        event="sd_orchestrator_task_dependency_unmet",
                        message=self._truncate_progress_message(
                            f"Task [{task.id}] blocked: unmet upstream tasks [{ids_str}]"
                            + (f" — {rationale}" if rationale else ""),
                            640,
                        ),
                        status="failed",
                        task_id=task.id,
                        extra={
                            "reason_code": DEPENDENCY_UNMET_REASON,
                            "unmet_upstream_ids": unmet_ids,
                            "missing_fields": missing_fields,
                            "judge_error": judge_error,
                            "task_description": task_desc_preview,
                            "task_agent": task.agent,
                            "retry_count": retry_count,
                        },
                    )
                    current_agents_knowledge.append(
                        self._format_task_knowledge(
                            task.id, task.description, task.agent, block_msg, "fail"
                        )
                    )
                    if self.debug == 1:
                        await updater.add_artifact(
                            [TextPart(text=f"Task [{task.id}]: {block_msg}\n")],
                            name=task_name,
                        )
                        think.append(block_msg)
                    continue

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
                    current_agents_knowledge.append(
                        self._format_task_knowledge(
                            task.id, task.description, "", none_description, "complete"
                        )
                    )
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
                                    ">>>>>> [answer_model=original] OrchestratorAgent.a2a_tasks() "
                                    "Task %s 按 step_status_llm_check_success 判定状态: %s <<<<<<",
                                    task.id, current_task_status,
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
                        current_agents_knowledge.append(
                            self._format_task_knowledge(
                                task.id,
                                task.description,
                                task.agent,
                                agent_steps_knowledge_str,
                                current_task_status,
                            )
                        )
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
                        current_agents_knowledge.append(
                            self._format_task_knowledge(
                                task.id,
                                task.description,
                                task.agent,
                                f"Execution error: {str(e)}",
                                "fail",
                            )
                        )

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
                        
                        current_agents_knowledge.append(
                            self._format_task_knowledge(
                                task.id,
                                task.description,
                                task.agent,
                                agent_result or "",
                                current_task_status,
                            )
                        )
                        
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
                        current_agents_knowledge.append(
                            self._format_task_knowledge(
                                task.id,
                                task.description,
                                task.agent,
                                f"Execution error: {str(e)}",
                                "fail",
                            )
                        )

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
                    _xc_replan = ""
                    if isinstance(self.metadata, dict):
                        _xc_replan = str(self.metadata.get("extra_context") or "").strip()
                    if _xc_replan:
                        replan_guidance += (
                            " 重试时 `replan_context` 内 `prior_execution_context` 为上游前置任务结果（与规划模板中的"
                            " **[前置任务执行情况]** 同源），新计划必须在相关任务的 `description` 中写入其中已给出的具体取值，"
                            "不得再使用「上下文缺失该依赖」等表述。"
                        )
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
                        recovery_retry_index=retry_count,
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
                    "[MemoryOp][SD] schedule_add_memory failed — ignoring "
                    "(run_id=%s)",
                    (self.metadata or {}).get('run_id', ''),
                )

        try:
            tracker = self.__dict__.setdefault("_background_memory_tasks", set())
            task = asyncio.create_task(_runner())
            tracker.add(task)
            task.add_done_callback(tracker.discard)
        except RuntimeError:
            logger.warning(
                "[MemoryOp][SD] schedule_add_memory: no running loop — "
                "falling back to inline execution"
            )

            async def _inline() -> None:
                try:
                    await self.add_memory(query, final_answer)
                except Exception:  # noqa: BLE001
                    logger.exception("[MemoryOp][SD] inline add_memory failed")

            try:
                asyncio.get_event_loop().run_until_complete(_inline())
            except Exception:  # noqa: BLE001
                logger.exception("[MemoryOp][SD] inline fallback also failed")

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
        logger.info(
            "[SummaryInput] query=%s | knowledge (%d chars):\n%s",
            query, len(knowledge or ""), knowledge,
        )

        system_template, human_template = self._summary_prompt_templates()
        _, agent_type, _ = self.planner_agent.analyze_descriptor_types()
        logger.info(
            "[SummaryPrompt] agent_type=%s system_chars=%d human_chars=%d",
            agent_type,
            len(system_template or ""),
            len(human_template or ""),
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
        logger.info(
            "[SummaryOutput] final_answer (%d chars): %s",
            len("".join(final_answer)), "".join(final_answer),
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

        # add memory — fire-and-forget so a slow/failing upstream never
        # blocks the stream close or surfaces an exception to the caller.
        self.schedule_add_memory(query, final_answer)


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
        # LocalSkill (route B) — a process-wide SkillRunner shared across all
        # requests. Lazily initialised on first request so startup stays fast
        # even when skill loading would be expensive. Disabled when
        # ``ENABLE_LOCAL_SKILLS`` is false or ``skill_sdk`` is not installed.
        self._skill_runner: "SkillRunner | None" = None
        self._skill_runner_initialised = False
        self._skill_runner_lock = asyncio.Lock()
        self._log_local_skill_executor_config()

    @staticmethod
    def _log_local_skill_executor_config() -> None:
        """One-shot snapshot at executor construction (server startup for SemanticDomain)."""
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
        _am = _md.get('answer_model', '(not in metadata)')
        logger.info(
            "[Execute][SDOrchestrator] answer_model=%s",
            _am,
        )
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

        skill_runner = await self._ensure_skill_runner()

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
            agent_card= self.agent_card,
            skill_runner=skill_runner,

        )

        if not context.message:
            raise Exception('No message provided')

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # make plans for user question, each plan is the name of agent card
        tasks = await agent.get_plan(query)

        think = []

        if tasks is None:
            logger.info(f"===== OrchestratorAgentExecutor, tasks is empty.")
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
                task_list=tasks,
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
                tasks_str = tasklist_to_string(tasks)
                await updater.add_artifact(
                    [TextPart(text=tasks_str)],
                    name=f'{agent.agent_name}-result',
                )
                think.append(tasks_str)

            # call each agent to get the knowledge owned by each agent, then get some knowledges from agents
            task_name = f'{agent.agent_name}-result'
            task_knowledges = await agent.a2a_tasks(query, tasks, updater, task_name, think)

            _tk_preview = [str(tk)[:200] + "..." for tk in task_knowledges] if task_knowledges else []
            logger.info(f"===== OrchestratorAgentExecutor.task_knowledges count={len(task_knowledges) if task_knowledges else 0}, preview: {_tk_preview}")

            # answer_model=original: 跳过 LLM 总结，直接返回 expert agent 的原始知识
            answer_model = metadata.get('answer_model', '')
            if answer_model == "original":
                logger.info(
                    ">>>>>> [answer_model=original] OrchestratorAgent.execute() answer_model=%s, "
                    "跳过 LLM 总结，直接返回 expert agent 原始知识 <<<<<<",
                    answer_model,
                )
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
                    # Fire-and-forget: memory write is best-effort and
                    # must not block the answer_model=original fast path.
                    agent.schedule_add_memory(query, final_answer)
            else:
                logger.info(
                    ">>>>>> [answer_model=%s] OrchestratorAgent.execute() 执行 LLM 总结 (非 original 路径) <<<<<<",
                    answer_model,
                )
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
                        # 发送 DAC_SUMMARY 帧，携带 LLM 总结后的最终答案，供 SG Expert 解析作为最终知识
                        final_summary = "".join(conversition).strip()
                        if final_summary:
                            summary_frame = OrchestratorAgent.build_summary_artifact(summary_text=final_summary)
                            await updater.add_artifact(
                                [TextPart(text=summary_frame)],
                                name=task_name,
                            )
                            logger.info(
                                "[DACSummary][SD-Orchestrator] sent summary frame (%d chars)",
                                len(final_summary),
                            )
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
