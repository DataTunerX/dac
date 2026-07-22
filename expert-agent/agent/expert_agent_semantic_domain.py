import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import click
import httpx
import uvicorn
from enum import Enum
import os
import re
import asyncio
import atexit
import signal
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import uuid
import numpy as np
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Union
from pydantic import BaseModel, Field
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TaskStatus, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .dataservices_client import DataServicesClient, MetadataValuesResult  # MetadataValuesResult 用于两阶段 LLM 知识检索
from .schema import ROLE_TYPE, AgentState, Memory, Message
from .prompts import ( 
    TASK_ANALYZE_NEXT_STEP_PROMPT_ZH, 
    MYSQL_NEXT_STEP_PROMPT_ZH, 
    POSTGRES_NEXT_STEP_PROMPT_ZH, 
    TABLE_SELECTOR_NEXT_STEP_PROMPT_ZH, 
    DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH, 
    COMMON_NEXT_STEP_PROMPT_ZH, 
    REQUERY_PROMPT_ZH,
    REQUERY_SQL_PROMPT_ZH,
    OBSERVE_PROMPT_SQL_ZH,
    OBSERVE_PROMPT_COMMON_ZH,
    SQL_EXEC_FAILURE_KIND_PROMPT_ZH,
    SQL_EXEC_FAILURE_KIND_HUMAN_ZH,
)
from .executors.mysql.mysql_reader import AsyncMySQLReaderContextManager, execute_mysql, get_mysql_tables_schema, get_mysql_tables_relationship, get_mysql_tables_sampledata
from .executors.postgres.postgres_reader import AsyncPostgresReaderContextManager, execute_postgres, get_postgres_tables_schema, get_postgres_tables_relationship, get_postgres_tables_sampledata
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler

try:
    # json_repair is a tolerant JSON parser designed specifically for LLM output.
    # It handles common failure modes such as unescaped inner double quotes,
    # trailing commas, missing quotes, python-style single quotes, etc.
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]


# Top-level (and same-line) JSON string keys where expert LLM inlines long text
# or user queries with unescaped ``"`` — next-step (answer/requery), observe
# (reason), table/dimension (intent_analysis, reasoning), group planner CoT
# (reasoning), plus planner-shaped keys from upstream.
_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "reason",
    "rationale",
    "final_answer",
    "answer",
    "requery",
    "reasoning",
    "intent_analysis",
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
    # See the sibling implementation in orchestrator_agent_semantic_group.py
    # for detailed rationale about the regex anchoring strategy.
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


def _llm_output_text_from_message(answer: Any) -> str:
    """Normalize message ``content`` (``str`` or list of text blocks) to a single string.

    - ``or ""`` on list would wrongly drop non-empty list bodies; list blocks must be joined.
    - Some callers pass a bare string as ``answer``.
    """
    c = getattr(answer, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: List[str] = []
        for part in c:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text", "")
                parts.append(t if isinstance(t, str) else str(t))
            else:
                parts.append(str(part))
        return "".join(parts)
    if c is not None:
        return str(c)
    if isinstance(answer, str):
        return answer
    return str(answer)


def _strip_markdown_code_fences(text: str) -> str:
    """Remove a single GFM `` ```[lang] ... ``` `` wrapper if present.

    LLMs often wrap SQL/JSON in fenced blocks. Stripping only the first three
    backticks leaves a language line such as ``sql`` and breaks ``json.loads``.
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    line1_end = t.find("\n", 3)
    if line1_end != -1:
        t = t[line1_end + 1 :]
    else:
        t = t[3:].lstrip()
    t = t.rstrip()
    if t.endswith("```"):
        t = t[:-3].rstrip()
    return t


_STANDALONE_SQL_HEADER = re.compile(
    r"^\s*(?:with|select|insert|update|delete|show|desc|describe|"
    r"create|alter|drop|truncate|explain)\b",
    re.IGNORECASE | re.DOTALL,
)


def _coerce_standalone_sql_to_llm_dict(text: str) -> Optional[Dict[str, Any]]:
    """When the model returns only SQL (often after a ```sql fence), map to ``LLMResult`` shape."""
    t = text.strip()
    if len(t) < 8 or not _STANDALONE_SQL_HEADER.search(t):
        return None
    return {
        "answer": t,
        "conclusion": "terminate",
        "requery": "",
        "reason_code": "",
    }


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

SUPPORTED_DATABASE_TYPES = ["mysql", "postgres"]
PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "

SQL_PROCESS_MODE = os.getenv('SQL_PROCESS_MODE', "dictionary")
NON_RETRYABLE_MARKER = "NON_RETRYABLE::OUT_OF_SCOPE"
NON_RETRYABLE_REPEAT_MARKER = "NON_RETRYABLE::REPEATED_FAILURE"
STUCK_SIMILARITY_CONFIDENCE_THRESHOLD = float(os.getenv("STUCK_SIMILARITY_CONFIDENCE_THRESHOLD", "0.8"))
STUCK_MIN_SIMILAR_FAILURES = max(2, int(os.getenv("STUCK_MIN_SIMILAR_FAILURES", "2")))

# System Instructions to Agent
INSTRUCTIONS = """
You are an intelligent expert who answers user questions based on relevant knowledge.

"""

NEXT_STEP_PROMPT_EN = """
Based on the user's question and the provided background knowledge, please follow the following rules to respond:


**current time**
{current_time}


**Response Rules:**
1. If the background knowledge can fully address the user's question, return `terminate` in the conclusion field and **write the actual answer content** (facts, data, events) extracted from the background knowledge in the `answer` field. Do not only state that "the background knowledge provides/answers..."; instead, directly state the facts (e.g. "According to the material, the product sold 1 million units last year, mainly in Asia and Europe.").
2. If the background knowledge is irrelevant or insufficient, do not answer the question directly. Based on the original question, preserve the original meaning and regenerate a clearer and more understandable new question, placing it in the `requery` field. You only need to regenerate the question.
3. When generating questions, do not ask users to supplement materials.
4. When generating questions, check the historical query list and avoid generating duplicate questions.
5. In the `answer` field, explain the reason for not being able to answer directly and prompt for more relevant information.
6. If the background knowledge contains source code snippets (extra context from other agents), you must carefully analyze the business logic in the code (e.g., data processing workflows, field mappings, enum value definitions, state transition rules, etc.) and use these business rules to answer the question more accurately. The business rules in code are critical for understanding data semantics.

**Output Format Requirements:**
- Must return a standard JSON format string
- Ensure the output can be directly parsed by `json.loads()`
- Include three required fields: `answer`, `conclusion`, `requery`

**requery Examples**

1. Example 1
Original question: What is Java?
New question: What is the definition of Java?

2. Example 2
Original question: What is Java?
New question: What is the Java programming language?

3. Example 3
Original question: What is Java?
New question: What are the main uses of Java?


**Historical query list as follows:**
{history_querys}

**Example Reference:**

Output example when a complete answer can be provided:
{terminate_fewshots}

Output example when more information is needed:
{continue_fewshots}

**Relevant information:**
{memory}

**Current Background Knowledge:**
{knowledge}

**Note:** Strictly adhere to the JSON format for output. Do not include any additional explanations or text.

"""

NEXT_STEP_PROMPT_ZH = """
根据用户的问题和提供的背景知识，请遵循以下规则进行响应：


**当前时间**
{current_time}


**回答规则：**
1. 若背景知识能够充分解答用户问题，请在结论字段返回 `terminate`，并在 `answer` 字段中**直接写出从背景知识中提取的具体答案内容**（事实、数据、事件等），不要只写“背景知识提供了…能够解答”之类的说明。例如：应写“根据资料，该产品在去年销量达100万台，主要市场在亚洲和欧洲”，而不要写“当前背景知识提供了该产品的市场情况，能够充分解答用户的问题”。
2. 若背景知识与用户问题无关或信息不足，请不要直接回答问题，请根据原始的问题，保留原问题的语意，重新生成一个更清晰易懂的相似的新问题，放入 `requery` 字段, 你要重新生成问题就行。
3. 在生成问题的时候, 不要让用户补充材料。
4. 在生成问题的时候, 要仔细检查历史的query列表，不要生成和历史query重复或者相同的问题，生成出来5个相似的问题，然后从中选择一个和之前的历史query不同的问题，作为下次提问的问题。
5. 在 `answer` 字段中说明无法直接回答的原因，并提示需要更相关的信息。
6. 如果背景知识中包含源代码片段（来自其他智能体的额外上下文），你必须仔细分析代码中的业务逻辑（如数据处理流程、字段映射关系、枚举值定义、状态转换规则等），并结合这些业务逻辑来更准确地回答问题。代码中的业务规则是理解数据含义的重要依据。

**输出格式要求：**
- 必须返回标准的 JSON 格式字符串
- 确保输出可直接被 `json.loads()` 解析
- 包含三个必要字段：`answer`, `conclusion`, `requery`

**requery的示例**

原来的提问: python是什么?

新的相似的问题:

1. Python语言的基本概念和主要应用领域是什么？
2. 请介绍Python编程语言的特点和典型使用场景
3. Python是什么类型的语言？它主要用于哪些方面？
4. 能详细说明Python的定义和它的主要功能用途吗？
5. Python编程语言的核心特征和常见应用有哪些？
6. 解释Python的定位以及它在实际项目中的主要作用
7. Python语言的基本介绍和其主要应用范围
8. 什么是Python？它在软件开发中的主要用途是什么？
9. 请描述Python语言的性质和它最常被使用的领域
10. Python编程语言的基本概况和典型应用场景有哪些？


**原始的问题**

{original_query}

**历史的query列表:**

{history_querys}

**示例参考：**

可完整回答时的输出示例：
{terminate_fewshots}

需要更多信息时的输出示例：
{continue_fewshots}

**相关信息**
{memory}

**当前背景知识：**
{knowledge}

**注意：** 请严格遵循JSON格式输出，不要包含任何额外的解释或文本。

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

class TaskAnalyze(BaseModel):

    task: Optional[str] = Field(
        description='The name of  current task description.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class LLMResult(BaseModel):

    answer: Optional[str] = Field(
        description='The answer of llm for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

    requery: Optional[str] = Field(
        description='The regenerated new user query.'
    )

    reason_code: Optional[str] = Field(
        default="",
        description='Structured reason code. Use out_of_scope_non_retryable when task is outside this expert domain.'
    )

class RequeryResult(BaseModel):

    requery: Optional[str] = Field(
        description='The new query for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class ObserveResult(BaseModel):

    reason: Optional[str] = Field(
        description='The reason for answer.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )


class SqlFailureKindResult(BaseModel):
    """LLM output for SQL execution failure attribution (invoke_sql_execution_failure_kind)."""

    model_config = {"extra": "ignore"}

    sql_failure_kind: str = Field(description='syntax_issue or other')
    reason: str = Field(default="", description="Brief reason in Chinese.")


class FailureSnapshot(BaseModel):
    step_id: int = Field(description='Step id for this failure snapshot.')
    query: str = Field(description='Query used in this step.')
    sql: str = Field(default="", description='SQL used in this step if any.')
    sql_signature: str = Field(default="", description='Normalized SQL signature.')
    error_type: str = Field(default="", description='Normalized error type.')
    error_code: str = Field(default="", description='Normalized DB error code.')
    error_stage: str = Field(default="", description='Execution stage where failure happened.')
    root_cause_type: str = Field(default="", description='Normalized database root cause type.')
    root_cause_target: str = Field(default="", description='Normalized database object or target.')
    root_cause_signature: str = Field(default="", description='Stable root cause signature for deterministic matching.')
    answer_excerpt: str = Field(default="", description='Short answer excerpt for debugging.')

class FailureSimilarityResult(BaseModel):
    same_failure: bool = Field(default=False, description='Whether two failures are essentially the same.')
    confidence: float = Field(default=0.0, description='Confidence score for same_failure.')
    reason: str = Field(default="", description='Brief explanation.')

class TaskStatus(BaseModel):

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

class TaskStatusList(BaseModel):
    """Represents a list of tasks."""
    
    tasks: List[TaskStatus] = Field(description='List of tasks')

class StepStatus(BaseModel):

    id: int = Field(description='Sequential ID for the steps.')

    query: str = Field(
        description='description of subtask'
    )

    answer: str = Field(
        description='answer of the step.'
    )

class StepStatusList(BaseModel):
    """Represents a list of steps."""
    
    steps: List[StepStatus] = Field(description='List of steps')

class DimensionItem(BaseModel):
    name: str = Field(description="Dimension name")
    column: str = Field(description="Column name")
    table: str = Field(description="Table name")
    sql: str = Field(description="SQL query statement")

class Dimensions(BaseModel):
    """SQL Dimensions"""
    
    dimensions: Optional[List[DimensionItem]] = Field(
        default=None,
        description='LLM response to user question, containing dimension list'
    )
    
    reason: Optional[str] = Field(
        default=None,
        description='Regenerated new user query'
    )

# ============================================================================
# 两阶段 LLM 知识检索 —— DB (structured) 专用 Prompt
#
# 替代原有的向量/混合搜索，改为与 code-agent / doc-agent 一致的 LLM 索引匹配：
#   Stage 1: 将所有知识块摘要（表结构、字段、模块描述）发给 LLM，
#            LLM 根据用户问题选出相关的 knowledge_id
#   Stage 2: 按选中的 ID 取完整内容（CREATE TABLE、业务描述等），
#            传给后续 SQL 生成流程
#
# 此 Prompt 专为结构化数据库场景设计，强调：
#   - 表结构相关性（字段是否能满足查询条件）
#   - 关联表识别（多表 JOIN 需要同时选中所有参与表）
#   - 宁多勿少（多给几张表不影响 SQL 生成，少给会导致缺失）
# ============================================================================
LOCATE_DB_KNOWLEDGE_PROMPT_ZH = """

# Role
你是一位精通数据库架构和业务数据建模的专家。你能根据用户问题的真实意图，从数据库知识摘要（表结构、模块分组、业务描述）中精准定位与问题相关的知识记录。

**当前时间**
{current_time}

# Task
基于提供的【知识摘要列表】，深入理解每条记录描述的数据库表结构、字段含义、表间关系和业务模块。根据用户的【查询问题】，判断哪些知识记录包含回答问题所需的表结构信息（用于生成 SQL 或理解数据模型），返回这些记录的 Knowledge ID。

# 检索推理法则
在选择相关知识时，请遵循以下逻辑：
1. **意图理解**：理解用户问题的真实意图——用户可能需要查询特定数据、统计汇总、关联分析等，要判断需要哪些表参与。
2. **表结构相关性**：摘要中描述的表是否包含与问题相关的字段、业务实体或关联关系？
3. **关联表识别**：如果问题涉及多表关联（如订单和用户），需要同时选择所有参与关联的表的知识块。
4. **宁多勿少**：如果不确定某个表结构是否会被 SQL 查询用到，倾向于将其包含进来，确保后续 SQL 生成有足够的表结构信息。
5. **排除无关**：明显与问题无关的表（如完全不同的业务模块）应排除。

# Constraints
- **禁止猜测**：只基于摘要内容进行判断，不要假设摘要未提及的内容。
- **输出要求**：仅返回标准 JSON，严禁任何 markdown 代码块标识符或多余文字。

# Output Format (JSON)
{{
  "knowledge_ids": ["Knowledge ID 1", "Knowledge ID 2", "Knowledge ID 3"],
  "intent_analysis": "对用户真实意图的理解，以及需要哪些表来满足查询。",
  "reasoning": "选择这些知识记录的原因，说明各表在回答问题中的作用。",
  "domain_fit": "fit | mismatch | uncertain",
  "mismatch_evidence": "当 domain_fit=mismatch 时，简要说明为何当前领域无法处理"
}}

---
# Context: 知识摘要列表
{knowledge}

---
# User Query: 用户问题

"""

class KnowledgeSelectionResult(BaseModel):
    """LLM 从摘要中筛选出的相关知识 ID 列表"""

    knowledge_ids: List[str] = Field(
        default_factory=list,
        description="与用户问题相关的知识记录 ID 列表"
    )

    intent_analysis: Optional[str] = Field(
        default=None,
        description="对用户真实意图的理解"
    )

    reasoning: Optional[str] = Field(
        default=None,
        description="选择这些知识记录的原因"
    )

    domain_fit: Optional[str] = Field(
        default="uncertain",
        description="fit | mismatch | uncertain"
    )

    mismatch_evidence: Optional[str] = Field(
        default="",
        description="Domain mismatch evidence when domain_fit=mismatch"
    )


class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class ExpertAgent(BaseAgent):
    """Expert Agent"""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_descriptors:list = None,
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None,
        agent_id: str = None,

    ):
        logger.info('Initializing ExpertAgent')
        super().__init__(
            agent_name=(agent_id or 'ExpertAgent'),
            description='answer user question using yourself knowledge.',
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
        self.query=query
        self.original_query=query
        self.data_descriptors = data_descriptors
        self.dd_namespace = dd_namespace
        self.descriptor_types = descriptor_types
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=True,
        )
        self.current_step = 0
        self.state: AgentState = AgentState.IDLE
        self.duplicate_threshold: int = 2
        self.next_step_prompt = NEXT_STEP_PROMPT_ZH
        self.memory = Memory()
        self.old_querys = []
        self.metadata = metadata
        self.max_steps=max_steps
        self.current_tasks_status = current_tasks_status
        self.current_task_id = current_task_id
        self.agent_id = agent_id or self.agent_name
        self.step_status_list: List[StepStatus] = []
        # Domain-mismatch fast-fail heuristics (evidence-based, not single-step hard failure)
        self._consecutive_empty_knowledge_rounds: int = 0
        self._last_selection_domain_fit: str = "uncertain"
        self._last_selection_mismatch_evidence: str = ""
        self._last_sql_execution_error: bool = False
        self._last_stuck_reason: str = ""
        self._selected_table_whitelist: List[str] = []
        # Snapshot of the full set of tables enumerated from the DD's DB on the
        # last ``invoke_structured_with_table_selector`` call.  Used by the
        # SQL-stage self-heal path to distinguish "the table selector LLM
        # dropped a same-DB table" (recoverable: expand whitelist & retry)
        # from "the DD's DB genuinely doesn't have that table" (real
        # sovereignty gap → keep P3 unfulfilled_needs flow).
        self._cached_available_tables: List[str] = []
        # Selector-stage drops (tables the LLM chose but were not in the DB
        # whitelist) carried forward to enrich structured_control on the SQL
        # execution-error branch — see P3 unfulfilled_needs contract.
        self._selector_invalid_tables_with_intent: List[Dict[str, Any]] = []

    @staticmethod
    def _extract_db_error_code(error_text: str) -> str:
        raw = str(error_text or "")
        m = re.search(r"\((\d{3,6})\s*,", raw)
        return m.group(1) if m else ""

    @staticmethod
    def _normalize_db_object_name(name: str) -> str:
        raw = str(name or "").strip().strip("`'\"")
        raw = re.sub(r"\s+", "", raw)
        return raw.lower()

    @classmethod
    def _normalize_table_reference(cls, name: str) -> str:
        raw = str(name or "").strip()
        if not raw or raw.startswith("("):
            return ""
        parts = [part for part in raw.split(".") if part]
        if not parts:
            return ""
        return cls._normalize_db_object_name(parts[-1])

    @classmethod
    def _is_system_catalog_from_ref(cls, raw: str) -> bool:
        """FROM/JOIN target is under a system schema (not user-selected data tables)."""
        s = str(raw or "").strip()
        if not s or s.startswith("("):
            return False
        s = re.sub(r"[`\"]", "", s)
        parts = [p.strip() for p in re.split(r"\s*\.\s*", s) if p.strip()]
        if len(parts) < 2:
            return False
        schema = cls._normalize_db_object_name(parts[-2])
        return schema in (
            "information_schema",
            "pg_catalog",
            "performance_schema",
            "sys",
            "mysql",
        )

    @classmethod
    def _coerce_table_name_list(cls, payload: Any) -> List[str]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get("tables", [])
        else:
            items = []

        cleaned: List[str] = []
        seen = set()
        for item in items:
            name = str(item or "").strip()
            normalized = cls._normalize_db_object_name(name)
            if not normalized or normalized in seen:
                continue
            cleaned.append(name)
            seen.add(normalized)
        return cleaned

    async def _get_available_table_names(self, db_connect_config: dict, db_type: str) -> List[str]:
        db_type_lower = str(db_type or "").strip().lower()
        results: List[Dict[str, Any]] = []

        if db_type_lower == "mysql":
            async with AsyncMySQLReaderContextManager(db_connect_config) as reader:
                results = await reader.schema()
        elif db_type_lower == "postgres":
            async with AsyncPostgresReaderContextManager(db_connect_config) as reader:
                results = await reader.schema()
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

        table_names: List[str] = []
        seen = set()
        for item in results or []:
            table_name = str((item or {}).get("table_name") or "").strip()
            normalized = self._normalize_db_object_name(table_name)
            if not normalized or normalized in seen:
                continue
            table_names.append(table_name)
            seen.add(normalized)
        return table_names

    def _filter_tables_by_whitelist(self, candidate_tables: List[str], available_tables: List[str]) -> tuple[List[str], List[str]]:
        normalized_to_actual = {
            self._normalize_db_object_name(table_name): table_name
            for table_name in available_tables
            if str(table_name or "").strip()
        }

        valid_tables: List[str] = []
        invalid_tables: List[str] = []
        seen_valid = set()

        for table_name in candidate_tables or []:
            normalized = self._normalize_db_object_name(table_name)
            actual = normalized_to_actual.get(normalized)
            if actual:
                if normalized not in seen_valid:
                    valid_tables.append(actual)
                    seen_valid.add(normalized)
            elif str(table_name or "").strip():
                invalid_tables.append(str(table_name).strip())

        return valid_tables, invalid_tables

    def _extract_sql_table_names(self, sql: str) -> List[str]:
        raw_sql = str(sql or "")
        if not raw_sql.strip():
            return []

        pattern = re.compile(
            r"\b(?:FROM|JOIN)\s+((?!\()(?:(?:`[^`]+`|\"[^\"]+\"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:`[^`]+`|\"[^\"]+\"|[A-Za-z_][\w$]*))?))",
            flags=re.IGNORECASE,
        )
        table_names: List[str] = []
        seen = set()
        for match in pattern.finditer(raw_sql):
            raw_ref = match.group(1)
            if self._is_system_catalog_from_ref(raw_ref):
                continue
            normalized = self._normalize_table_reference(raw_ref)
            if not normalized or normalized in seen:
                continue
            table_names.append(normalized)
            seen.add(normalized)
        return table_names

    def _validate_sql_table_whitelist(self, sql: str, allowed_tables: List[str]) -> tuple[bool, List[str]]:
        referenced_tables = self._extract_sql_table_names(sql)
        if not allowed_tables:
            return len(referenced_tables) == 0, referenced_tables

        allowed = {
            self._normalize_db_object_name(table_name)
            for table_name in allowed_tables
            if str(table_name or "").strip()
        }
        unknown_tables = [table_name for table_name in referenced_tables if table_name not in allowed]
        return len(unknown_tables) == 0, unknown_tables

    @classmethod
    def _extract_db_root_cause(cls, error_text: str, error_code: str) -> Dict[str, str]:
        raw = str(error_text or "")
        if not raw:
            return {
                "root_cause_type": "",
                "root_cause_target": "",
                "root_cause_signature": "",
            }

        patterns = [
            (
                "missing_table",
                re.search(r"table ['\"]?([^'\"\s]+)['\"]? doesn't exist", raw, flags=re.IGNORECASE),
            ),
            (
                "missing_table",
                re.search(r"relation ['\"]?([^'\"\s]+)['\"]? does not exist", raw, flags=re.IGNORECASE),
            ),
            (
                "unknown_column",
                re.search(r"unknown column ['\"]?([^'\"\s]+)['\"]? in", raw, flags=re.IGNORECASE),
            ),
            (
                "unknown_column",
                re.search(r"column ['\"]?([^'\"\s]+)['\"]? does not exist", raw, flags=re.IGNORECASE),
            ),
            (
                "permission_denied",
                re.search(r"(?:select|insert|update|delete|alter|drop)\s+command denied .*? for table ['\"]?([^'\"\s]+)['\"]?", raw, flags=re.IGNORECASE),
            ),
            (
                "permission_denied",
                re.search(r"permission denied for table ['\"]?([^'\"\s]+)['\"]?", raw, flags=re.IGNORECASE),
            ),
            (
                "permission_denied",
                re.search(r"permission denied for relation ['\"]?([^'\"\s]+)['\"]?", raw, flags=re.IGNORECASE),
            ),
        ]

        for root_cause_type, match in patterns:
            if not match:
                continue
            target = cls._normalize_db_object_name(match.group(1))
            signature = f"{root_cause_type}:{target}" if target else root_cause_type
            return {
                "root_cause_type": root_cause_type,
                "root_cause_target": target,
                "root_cause_signature": signature,
            }

        fallback_by_code = {
            "1146": "missing_table",
            "1054": "unknown_column",
            "1142": "permission_denied",
            "1044": "permission_denied",
            "1045": "permission_denied",
        }
        root_cause_type = fallback_by_code.get(str(error_code or "").strip(), "")
        return {
            "root_cause_type": root_cause_type,
            "root_cause_target": "",
            "root_cause_signature": root_cause_type,
        } if root_cause_type else {
            "root_cause_type": "",
            "root_cause_target": "",
            "root_cause_signature": "",
        }

    @staticmethod
    def _build_structured_error(*, error_type: str, error_code: str, error_stage: str, retryable: bool) -> Dict[str, Any]:
        return {
            "error_type": str(error_type or ""),
            "error_code": str(error_code or ""),
            "error_stage": str(error_stage or ""),
            "retryable": bool(retryable),
        }

    @staticmethod
    def _build_structured_control(
        *,
        reason_code: str,
        non_retryable: bool,
        error_type: str = "",
        error_code: str = "",
        error_stage: str = "",
        retryable: bool = True,
        sql_failure_kind: str = "",
        unfulfilled_needs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "reason_code": str(reason_code or ""),
            "non_retryable": bool(non_retryable),
            "error_type": str(error_type or ""),
            "error_code": str(error_code or ""),
            "error_stage": str(error_stage or ""),
            "retryable": bool(retryable),
        }
        if str(sql_failure_kind or "").strip():
            d["sql_failure_kind"] = str(sql_failure_kind).strip()
        if unfulfilled_needs:
            # Structured "what this DD could not reach" payload so upstream
            # planners (SG Orchestrator / mid-exec detector) can do precise
            # cross-SG delegation without LLM guesswork.  Schema:
            #   [{"missing_table": "order_shipping",
            #     "reason": "outside_whitelist" | "selector_filtered",
            #     "intent_fragment": "判断是否超期未发货",
            #     "stage": "sql_validation" | "table_selection"}]
            cleaned: List[Dict[str, Any]] = []
            for item in unfulfilled_needs:
                if not isinstance(item, dict):
                    continue
                missing = str(item.get("missing_table") or "").strip()
                if not missing:
                    continue
                cleaned.append({
                    "missing_table": missing,
                    "reason": str(item.get("reason") or "").strip(),
                    "intent_fragment": str(item.get("intent_fragment") or "").strip(),
                    "stage": str(item.get("stage") or "").strip(),
                })
            if cleaned:
                d["unfulfilled_needs"] = cleaned
        return d

    @staticmethod
    def _extract_structured_error_from_text(text: str) -> Dict[str, Any]:
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("structured_error:"):
                continue
            payload = stripped.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        return {}

    def _collect_recent_unfulfilled_needs(self) -> List[Dict[str, Any]]:
        """Aggregate unique ``unfulfilled_needs`` items across recent steps.

        Used when emitting the ``repeated_failure_non_retryable`` marker so the
        upstream SG Orchestrator can route the gap precisely — every retried
        step that hit the SQL_WHITELIST validator contributed an
        ``unfulfilled_needs`` payload via :meth:`_build_structured_control`.
        Also folds in the selector-stage drops captured by
        :meth:`invoke_structured_with_table_selector`.
        """
        seen: set = set()
        aggregated: List[Dict[str, Any]] = []

        def _add(item: Dict[str, Any]) -> None:
            missing = str(item.get("missing_table") or "").strip()
            if not missing:
                return
            key = missing.lower()
            if key in seen:
                return
            seen.add(key)
            aggregated.append({
                "missing_table": missing,
                "reason": str(item.get("reason") or "").strip(),
                "intent_fragment": str(item.get("intent_fragment") or "").strip(),
                "stage": str(item.get("stage") or "").strip(),
            })

        for step in reversed(self.step_status_list or []):
            answer = str(getattr(step, "answer", "") or "")
            sc = self._extract_structured_control_from_text(answer)
            if not isinstance(sc, dict):
                continue
            for need in sc.get("unfulfilled_needs") or []:
                if isinstance(need, dict):
                    _add(need)

        for need in getattr(self, "_selector_invalid_tables_with_intent", []) or []:
            if isinstance(need, dict):
                _add(need)

        return aggregated

    @staticmethod
    def _extract_structured_control_from_text(text: str) -> Dict[str, Any]:
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("structured_control:"):
                continue
            payload = stripped.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        return {}

    @staticmethod
    def _last_structured_control_from_text(text: str) -> Dict[str, Any]:
        last: Dict[str, Any] = {}
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("structured_control:"):
                continue
            payload = stripped.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                last = data
        return last

    @staticmethod
    def _extract_sql_from_answer(text: str) -> str:
        raw = str(text or "")
        match = re.search(r"sql:\s*(select\b.*?)(?:\n|$)", raw, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _split_sql_statements(sql: str) -> List[str]:
        """
        Split a script into statements on ';' outside quotes / backtick identifiers (best-effort).
        Needed because drivers return only one result set per execute (MySQL) or reject multi-command
        queries in common asyncpg usage.
        """
        raw = str(sql or "").strip()
        if not raw:
            return []
        statements: List[str] = []
        buf: List[str] = []
        i = 0
        n = len(raw)
        in_single = False
        in_double = False
        in_backtick = False
        escape = False
        while i < n:
            c = raw[i]
            if escape:
                buf.append(c)
                escape = False
                i += 1
                continue
            if in_single:
                if c == "\\" and i + 1 < n:
                    escape = True
                    buf.append(c)
                    i += 1
                    continue
                if c == "'" and i + 1 < n and raw[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                if c == "'":
                    in_single = False
                buf.append(c)
                i += 1
                continue
            if in_double:
                if c == '"' and i + 1 < n and raw[i + 1] == '"':
                    buf.append('""')
                    i += 2
                    continue
                if c == '"':
                    in_double = False
                buf.append(c)
                i += 1
                continue
            if in_backtick:
                if c == "`" and i + 1 < n and raw[i + 1] == "`":
                    buf.append("``")
                    i += 2
                    continue
                if c == "`":
                    in_backtick = False
                buf.append(c)
                i += 1
                continue
            if c == "'":
                in_single = True
                buf.append(c)
                i += 1
                continue
            if c == '"':
                in_double = True
                buf.append(c)
                i += 1
                continue
            if c == "`":
                in_backtick = True
                buf.append(c)
                i += 1
                continue
            if c == ";":
                piece = "".join(buf).strip()
                if piece:
                    statements.append(piece)
                buf = []
                i += 1
                continue
            buf.append(c)
            i += 1
        tail = "".join(buf).strip()
        if tail:
            statements.append(tail)
        return statements

    @staticmethod
    def _flatten_query_result_rows(
        query_results: Union[List[Dict[str, Any]], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Normalize execute_db_query output to a flat row list (for dimension aggregation)."""
        if isinstance(query_results, list):
            return query_results
        if isinstance(query_results, dict) and query_results.get("multi_statement"):
            flat: List[Dict[str, Any]] = []
            for batch in query_results.get("batches") or []:
                flat.extend(batch.get("rows") or [])
            return flat
        return []

    @staticmethod
    def _prepare_sql_for_signature(sql: str) -> str:
        raw = str(sql or "").strip().lower()
        if not raw:
            return ""
        raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.DOTALL)
        raw = re.sub(r"--.*?(?:\n|$)", " ", raw)
        raw = re.sub(r"#.*?(?:\n|$)", " ", raw)
        raw = raw.replace("`", "").replace('"', "")
        raw = re.sub(r"'(?:''|[^'])*'", "?", raw)
        raw = re.sub(r"\b\d+(?:\.\d+)?\b", "?", raw)
        raw = re.sub(r"%s|\$\d+|:[a-zA-Z_][a-zA-Z0-9_]*|\?", "?", raw)
        raw = re.sub(r"\s+", " ", raw).strip().rstrip(";")
        return raw

    @staticmethod
    def _normalize_sql_identifier(identifier: str, keep_schema: bool = False) -> str:
        raw = str(identifier or "").strip().strip(",;()")
        if not raw:
            return ""
        raw = raw.replace("`", "").replace('"', "")
        raw = re.split(r"\s+as\s+|\s+", raw, maxsplit=1, flags=re.IGNORECASE)[0]
        parts = [part for part in raw.split(".") if part]
        if not parts:
            return ""
        if keep_schema and len(parts) >= 2:
            return ".".join(parts[-2:])
        return parts[-1]

    @staticmethod
    def _normalize_sql_expression_signature(expr: str) -> str:
        raw = str(expr or "").strip().lower()
        if not raw:
            return ""
        raw = raw.replace("`", "").replace('"', "")
        raw = re.sub(r"\b[a-z_][a-z0-9_]*\.([a-z_][a-z0-9_]*)\b", r"\1", raw)
        raw = re.sub(r"\s+", " ", raw).strip(" ,()")
        return raw

    @staticmethod
    def _extract_sql_clauses(sql: str, clause: str, stop_clauses: List[str]) -> List[str]:
        stop_patterns = [rf"\b{re.escape(keyword)}\b" for keyword in stop_clauses]
        stop_patterns.extend([
            r"\)\s*(?:select|update|insert|delete)\b",
            r"\)\s*,",
        ])
        stop_pattern = "|".join(stop_patterns)
        matches = re.finditer(
            rf"\b{re.escape(clause)}\b\s+(.*?)(?={stop_pattern}|$)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        clauses: List[str] = []
        for match in matches:
            body = match.group(1).strip()
            if body:
                clauses.append(body)
        return clauses

    @classmethod
    def _extract_sql_table_signatures(cls, sql: str) -> List[str]:
        tables: List[str] = []
        seen = set()
        patterns = [
            r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
            r"\bjoin\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
            r"\bupdate\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
            r"\binsert\s+into\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
            r"\bdelete\s+from\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, sql, flags=re.IGNORECASE):
                table_name = cls._normalize_sql_identifier(match.group(1), keep_schema=True)
                if table_name and table_name not in seen:
                    seen.add(table_name)
                    tables.append(table_name)
        tables.sort()
        return tables

    @classmethod
    def _extract_sql_predicate_signatures(cls, where_clause: str) -> List[str]:
        clause = str(where_clause or "").strip()
        if not clause:
            return []
        signatures: List[str] = []
        seen = set()
        pattern = re.compile(
            r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s*"
            r"(is\s+not\s+null|is\s+null|not\s+in|between|like|in|<=|>=|<>|!=|=|<|>|is)(?=\s|\(|$)",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(clause):
            identifier = cls._normalize_sql_identifier(match.group(1))
            operator = re.sub(r"\s+", "_", match.group(2).strip().lower())
            if not identifier:
                continue
            signature = f"{identifier}:{operator}"
            if signature not in seen:
                seen.add(signature)
                signatures.append(signature)
        if signatures:
            signatures.sort()
            return signatures
        raw_signature = cls._normalize_sql_expression_signature(clause)
        return [raw_signature[:120]] if raw_signature else []

    @classmethod
    def _extract_sql_list_signatures(cls, clause: str) -> List[str]:
        body = str(clause or "").strip()
        if not body:
            return []
        signatures: List[str] = []
        seen = set()
        for part in body.split(","):
            normalized = cls._normalize_sql_expression_signature(part)
            if not normalized:
                continue
            if normalized not in seen:
                seen.add(normalized)
                signatures.append(normalized)
        signatures.sort()
        return signatures

    @classmethod
    def _normalize_sql_signature(cls, sql: str) -> str:
        raw = cls._prepare_sql_for_signature(sql)
        if not raw:
            return ""

        statement_match = re.search(r"\b(select|update|insert|delete)\b", raw, flags=re.IGNORECASE)
        statement_type = statement_match.group(1).lower() if statement_match else "unknown"
        tables = cls._extract_sql_table_signatures(raw)

        where_clauses = cls._extract_sql_clauses(
            raw,
            "where",
            ["group by", "order by", "having", "limit", "offset", "union", "for update"],
        )
        group_clauses = cls._extract_sql_clauses(
            raw,
            "group by",
            ["having", "order by", "limit", "offset", "union", "for update"],
        )
        having_clauses = cls._extract_sql_clauses(
            raw,
            "having",
            ["order by", "limit", "offset", "union", "for update"],
        )
        order_clauses = cls._extract_sql_clauses(
            raw,
            "order by",
            ["limit", "offset", "union", "for update"],
        )
        limit_clauses = cls._extract_sql_clauses(
            raw,
            "limit",
            ["offset", "union", "for update"],
        )

        signature_parts = [f"stmt={statement_type}"]
        if raw.startswith("with "):
            signature_parts.append("cte=true")
        if tables:
            signature_parts.append(f"tables={','.join(tables)}")

        where_signatures: List[str] = []
        where_seen = set()
        for clause in where_clauses:
            for signature in cls._extract_sql_predicate_signatures(clause):
                if signature not in where_seen:
                    where_seen.add(signature)
                    where_signatures.append(signature)
        where_signatures.sort()
        if where_signatures:
            signature_parts.append(f"where={','.join(where_signatures)}")

        group_signatures: List[str] = []
        group_seen = set()
        for clause in group_clauses:
            for signature in cls._extract_sql_list_signatures(clause):
                if signature not in group_seen:
                    group_seen.add(signature)
                    group_signatures.append(signature)
        group_signatures.sort()
        if group_signatures:
            signature_parts.append(f"group={','.join(group_signatures)}")

        having_signatures: List[str] = []
        having_seen = set()
        for clause in having_clauses:
            for signature in cls._extract_sql_predicate_signatures(clause):
                if signature not in having_seen:
                    having_seen.add(signature)
                    having_signatures.append(signature)
        having_signatures.sort()
        if having_signatures:
            signature_parts.append(f"having={','.join(having_signatures)}")

        order_signatures: List[str] = []
        order_seen = set()
        for clause in order_clauses:
            for signature in cls._extract_sql_list_signatures(clause):
                if signature not in order_seen:
                    order_seen.add(signature)
                    order_signatures.append(signature)
        order_signatures.sort()
        if order_signatures:
            signature_parts.append(f"order={','.join(order_signatures)}")

        limit_signatures: List[str] = []
        limit_seen = set()
        for clause in limit_clauses:
            signature = cls._normalize_sql_expression_signature(clause)
            if signature and signature not in limit_seen:
                limit_seen.add(signature)
                limit_signatures.append(signature)
        limit_signatures.sort()
        if limit_signatures:
            signature_parts.append(f"limit={','.join(limit_signatures)}")

        return "|".join(signature_parts)

    @staticmethod
    def _sd_step_query_preview(text: str, limit: int = 420) -> str:
        """Single-line preview of the step query for DAC_PROGRESS (sd_expert)."""
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[: limit - 3] + "..."

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
            "layer": "sd_expert",
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
            run_id=(self.metadata or {}).get("run_id", ""),
            user_id=(self.metadata or {}).get("user_id", ""),
            agent_id=self.agent_id,
            task_id=task_id,
            extra=extra,
        ))

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR
            raise e
        finally:
            self.state = previous_state

    async def stream(self, knowledge) -> AsyncIterable[dict[str, Any]]:
        enhanced_query = f"user question: {self.query}\n\n Background knowledge: {knowledge} \n\n{NEXT_STEP_PROMPT_ZH}"

        messages = [
        SystemMessage(content=INSTRUCTIONS),
        HumanMessage(content=enhanced_query)
        ]

        async for chunk in self.llm.astream(messages):
            if hasattr(chunk, 'content') and chunk.content:
                yield {'content': chunk.content, 'is_task_complete': False}
        yield {'content': '', 'is_task_complete': True}

    def format_llm_output(self, answer) -> dict:
        """Parse the planner LLM output into a dict with heavy tolerance.

        See ``orchestrator_agent_semantic_group.PlannerAgent.format_llm_output``
        for the detailed recovery strategy — this implementation mirrors it.
        """
        raw = _llm_output_text_from_message(answer)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        cleaned_content = _strip_markdown_code_fences(raw)

        try:
            return json.loads(cleaned_content)
        except json.JSONDecodeError as e2:
            logger.error(f" === format_llm_output, Parsing failed after cleanup.: {e2}")

        escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                parsed = json.loads(escaped_content)
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
                    parsed = json.loads(repaired)
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
            parsed = json.loads(cleaned_content.replace("'", '"'))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e4:
            logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")

        coerced = _coerce_standalone_sql_to_llm_dict(cleaned_content)
        if coerced is not None:
            logger.info(" === format_llm_output, recovered standalone SQL (fenced or non-JSON)")

        return coerced

    async def invoke_structured_with_table_selector(self, knowledge, db_type) -> (str, str, str):
        system_template = TABLE_SELECTOR_NEXT_STEP_PROMPT_ZH

        human_template = "question：{query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-tableselector",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_with_table_selector, llm answer = {answer}")

        tables = self._coerce_table_name_list(self.format_llm_output(answer))

        logger.info(f" === ExpertAgent.invoke_structured_with_table_selector , invoke_structured_with_table_selector, tables = {tables}")

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        source_metadata = self.analyze_descriptor_source_metadata()
        db_connect_config = source_metadata[ddname]
        available_tables = await self._get_available_table_names(db_connect_config, db_type)
        # Cache for SQL-stage self-heal: if the SQL generator later picks a
        # table the selector skipped but is still in the DD's own DB, the
        # validator can auto-expand the selected whitelist instead of
        # bouncing through a is_stuck / non-retryable cycle.
        self._cached_available_tables = list(available_tables or [])
        valid_tables, invalid_tables = self._filter_tables_by_whitelist(tables, available_tables)
        self._selected_table_whitelist = valid_tables
        # Stash selector-stage drops as structured "unfulfilled_needs" candidates
        # so the SQL-failure path can include them in structured_control even
        # when the LLM does not re-emit those table names in the SQL itself.
        intent_hint = (self.original_query or self.query or "").strip()
        self._selector_invalid_tables_with_intent = [
            {
                "missing_table": str(t or "").strip(),
                "reason": "selector_filtered",
                "intent_fragment": intent_hint,
                "stage": "table_selection",
            }
            for t in (invalid_tables or [])
            if str(t or "").strip()
        ]

        if invalid_tables:
            logger.warning(
                "Table selector produced non-existent tables, invalid=%s, valid=%s",
                invalid_tables,
                valid_tables,
            )

        sql_schema = ""
        sql_relationship = ""
        sql_sample_data = ""

        if not valid_tables:
            logger.warning(
                "Table selector whitelist left no valid tables, original=%s invalid=%s",
                tables,
                invalid_tables,
            )
            sql_schema = "No schema information available"
            sql_relationship = "[]"
            sql_sample_data = "[]"
        elif db_type == "mysql":
            sql_schema = await get_mysql_tables_schema(db_connect_config, valid_tables)
            sql_relationship = await get_mysql_tables_relationship(db_connect_config, valid_tables)
            sql_sample_data = await get_mysql_tables_sampledata(db_connect_config, valid_tables)

        if valid_tables and db_type == "postgres":
            sql_schema = await get_postgres_tables_schema(db_connect_config, valid_tables)
            sql_relationship = await get_postgres_tables_relationship(db_connect_config, valid_tables)
            sql_sample_data = await get_postgres_tables_sampledata(db_connect_config, valid_tables)

        logger.debug(f"ExpertAgent.invoke_structured_with_table_selector, sql_schema={sql_schema}")

        return sql_schema, sql_relationship, sql_sample_data

    async def execute_db_query(
        self, db_connect_config: dict, dbtype: str, sql: str
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        try:
            if not db_connect_config:
                raise ValueError("Database connection configuration cannot be empty.")
            
            if not sql or not sql.strip():
                raise ValueError("SQL statement cannot be empty.")
            
            if not dbtype:
                raise ValueError("Database type cannot be empty.")
            
            dbtype_lower = dbtype.lower()
            statements = self._split_sql_statements(sql)
            if not statements:
                raise ValueError("SQL statement cannot be empty.")

            async def _run_one(stmt: str) -> List[Dict[str, Any]]:
                if dbtype_lower == "mysql":
                    return await execute_mysql(db_connect_config, stmt)
                if dbtype_lower == "postgres":
                    return await execute_postgres(db_connect_config, stmt)
                raise ValueError(f"Unsupported database type: {dbtype}")

            if len(statements) == 1:
                return await _run_one(statements[0])

            batches: List[Dict[str, Any]] = []
            for idx, stmt in enumerate(statements):
                rows = await _run_one(stmt)
                batches.append({"statement_index": idx, "sql": stmt, "rows": rows})
            return {
                "multi_statement": True,
                "statement_count": len(statements),
                "batches": batches,
            }
                
        except ValueError as ve:
            raise ve
            
        except ConnectionError as ce:
            logging.error(f"Database connection failed.: {str(ce)}")
            raise ConnectionError(f"Unable to connect to the database.: {str(ce)}")
            
        except Exception as e:
            logging.error(f"An error occurred while executing the database query: {str(e)}")
            raise Exception(f"Query execution failed.: {str(e)}")

    async def process_dimensions(self, db_connect_config, dbtype: str = 'mysql', dimensions: Dimensions = None) -> str:

        if not dimensions or not dimensions.dimensions:
            return "No dimension configuration available"
        
        supported_dbtypes = ['mysql', 'postgres']
        if dbtype.lower() not in supported_dbtypes:
            return f"Unsupported database type: {dbtype}"
        
        results = []
        
        for dimension in dimensions.dimensions:
            try:
                query_results = await self.execute_db_query(db_connect_config, dbtype, dimension.sql)
                row_list = self._flatten_query_result_rows(query_results)
                
                values = set()
                for row in row_list:
                    for value in row.values():
                        if value is not None and str(value).strip():
                            if isinstance(value, bool):
                                display_value = '是' if value else '否'
                            else:
                                display_value = str(value).strip()
                            values.add(display_value)
                
                sorted_values = sorted(list(values))
                
                if sorted_values:
                    result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）包括：{', '.join(sorted_values)}"
                    results.append(result_line)
                else:
                    result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）：无数据"
                    results.append(result_line)
                    
            except Exception as e:
                result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）查询失败：{str(e)}"
                results.append(result_line)
        
        return "\n\n".join(results)

    async def invoke_structured_with_dimension_selector(self, knowledge, db_type) -> (str, str):

        system_template = ""

        if db_type == "mysql":
            system_template = DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH

        human_template = "question：{query}"

        dimension_selector_json_prompt_instructions_zh = {
          "dimensions": [
            {
              "name": "性别",
              "column": "gender",
              "table": "user_profile", 
              "sql": "SELECT DISTINCT `gender` FROM `user_profile`"
            },
            {
              "name": "产品分类",
              "column": "category",
              "table": "product_catalog",
              "sql": "SELECT DISTINCT `category` FROM `product_catalog`"
            },
            {
              "name": "城市", 
              "column": "city",
              "table": "customer_profile",
              "sql": "SELECT DISTINCT `city` FROM `customer_profile`"
            }
          ],
          "reason": "table 字段和 sql 中的表名必须来自当前 Tables Schema 中已经出现的真实物理表名，不能猜测或改写表名。"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
            partial_variables={"dimension_selector": dimension_selector_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-dimensionselector",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_with_dimension_selector, llm answer = {answer}")

        dimensions = self.format_llm_output(answer)

        dimensions_llm_parsed = Dimensions(**dimensions)

        logger.info(f"-------------------- ExpertAgent.invoke_structured_with_dimension_selector , invoke_structured_with_dimension_selector, dimensions = {dimensions_llm_parsed}")

        dimensions_result = ""

        if dimensions_llm_parsed.dimensions:
            ddname, agent_type, db_type = self.analyze_descriptor_types()

            source_metadata = self.analyze_descriptor_source_metadata()
            db_connect_config = source_metadata[ddname]

            dimensions_result = await self.process_dimensions(db_connect_config, db_type, dimensions_llm_parsed)
            logger.info(f"ExpertAgent.invoke_structured_with_dimension_selector, dimensions_result={dimensions_result}")
        else:
            logger.debug(f"ExpertAgent.invoke_structured_with_dimension_selector, reason={dimensions_llm_parsed.reason}")

        return dimensions_result, dimensions_llm_parsed.reason

    
    def _get_agent_domain_description(self) -> str:
        """Return a domain description based on the agent's descriptor_type."""
        ddname, agent_type, db_type = self.analyze_descriptor_types()
        if agent_type == "structured":
            return (
                f"你是数据库领域的专家（{db_type or 'SQL'}）。"
                f"你的专业知识范围仅限于：数据库表结构、字段含义、数据关系、数据查询和SQL相关的问题。"
                f"对于API接口、源代码实现、文档内容等超出数据库领域的问题，你不应该回答。"
            )
        elif agent_type == "code":
            return (
                "你是源代码分析领域的专家。"
                "你的专业知识范围仅限于：源代码的业务逻辑、函数实现、调用关系、代码结构等。"
                "对于数据库查询、API文档描述等超出源代码分析领域的问题，你不应该回答。"
            )
        elif agent_type == "unstructured":
            return (
                "你是文档分析领域的专家。"
                "你的专业知识范围仅限于：API文档、设计文档、技术手册等非结构化文档中的信息。"
                "对于数据库查询、源代码实现等超出文档领域的问题，你不应该回答。"
            )
        return "你是一个通用的智能专家。请基于提供的背景知识来回答问题。"

    async def invoke_common(self, knowledge: str = "") -> LLMResult:

        current_task = self.metadata.get('current_task', '')

        system_template = COMMON_NEXT_STEP_PROMPT_ZH
        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": "",
            "reason_code": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？",
            "reason_code": ""
        }

        agent_domain = self._get_agent_domain_description()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_task","current_time","knowledge","agent_domain"],
            partial_variables={"current_tasks_status":self.current_tasks_status.tasks, "terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_task": self.query, "current_time":current_time, "knowledge": knowledge, "agent_domain": agent_domain},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_common, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": "",
                "reason_code": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_common , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result


    async def invoke_structured_task_analyze(self) -> TaskAnalyze:

        logger.debug(f"##################### ExpertAgent.invoke_structured_task_analyze, current_tasks_status = {self.current_tasks_status}")

        current_task = self.metadata.get('current_task', '')

        system_template = TASK_ANALYZE_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "task": "从数据库中获取每个商品分类及其对应的商品价格数据",
            "conclusion": "sql",
        }

        continue_json_prompt_instructions_zh: dict = {
            "task": "整理并输出各分类的平均商品价格结果",
            "conclusion": "nosql",
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_task","current_time"],
            partial_variables={"current_tasks_status":self.current_tasks_status.tasks, "terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-task_analyze",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_task": self.query, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_task_analyze, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "task": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = TaskAnalyze(**data_dict)

        logger.info(f"##################### ExpertAgent.invoke_structured_task_analyze, current task = {current_task}, query:{self.query}, action:{llm_result.conclusion}")

        return llm_result


    async def invoke_structured_dictionary_mode(self, knowledge, db_type) -> (LLMResult, str, str):

        memory = self.metadata.get('memory', '')
        logger.info(
            "[MemoryUse][SD-Expert][invoke_structured_dictionary_mode] query_chars=%d memory_chars=%d memory_non_empty=%s",
            len(str(self.query or "")),
            len(str(memory or "")),
            bool(str(memory or "").strip()),
        )

        logger.debug(f" === ExpertAgent.invoke_structured_dictionary_mode, memory = {memory}")

        sql_schema, sql_relationship, sql_sample_data = await self.invoke_structured_with_table_selector(knowledge, db_type)

        tables_knowledge = f"\n\nTables Schema:\n {sql_schema}\n\nTables Relationshp:\n{sql_relationship}\n\nSample SQL Data:\n{sql_sample_data}\n\n"

        # 将数据源中的 Key Information（background_knowledge）和 Fewshots 一并传入 SQL 生成 prompt，否则 ConfigMap 中的年末值规则等无法生效
        if knowledge and isinstance(knowledge, str) and knowledge.strip():
            tables_knowledge += f"\n\n--- 数据源背景知识与示例（必须遵守） ---\n\n{knowledge}\n\n"

        dimensions, dimensions_reason = await self.invoke_structured_with_dimension_selector(tables_knowledge, db_type)

        system_template = ""

        if db_type == "mysql":
            system_template = MYSQL_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = POSTGRES_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？"
        }

        step_history = self.get_step_history_for_requery()

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","original_query","history_querys","memory", "dimensions","current_time", "step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-sql_generate",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": tables_knowledge,"original_query": self.original_query,"history_querys": history_querys,"memory": memory, "dimensions":dimensions, "current_time":current_time, "step_history": step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_structured_dictionary_mode, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_structured_dictionary_mode , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result, dimensions, dimensions_reason

    async def invoke_structured(self, knowledge, db_type) -> LLMResult:

        memory = self.metadata.get('memory', '')
        logger.info(
            "[MemoryUse][SD-Expert][invoke_structured] query_chars=%d memory_chars=%d memory_non_empty=%s",
            len(str(self.query or "")),
            len(str(memory or "")),
            bool(str(memory or "").strip()),
        )

        logger.info(f" === ExpertAgent.invoke_structured, memory = {memory}")

        tables_knowledge = knowledge

        system_template = ""

        if db_type == "mysql":
            system_template = MYSQL_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = POSTGRES_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？"
        }


        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","original_query","history_querys","memory","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-sql_nodict",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": tables_knowledge,"original_query": self.original_query,"history_querys": history_querys,"memory": memory, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_structured, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_structured , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result


    async def invoke_requery(self) -> RequeryResult:

        step_history = self.get_step_history_for_requery()

        system_template = REQUERY_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "requery": "新生成的问题...",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "requery": "",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["original_query","history_querys","current_time","step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-requery",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "original_query": self.original_query,"history_querys": history_querys, "current_time":current_time, "step_history":step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_requery, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {}

        # Ensure required fields exist with defaults (json_repair may return incomplete dicts).
        if 'requery' not in data_dict and 'query' in data_dict:
            data_dict['requery'] = data_dict.pop('query')
        data_dict.setdefault('requery', None)
        data_dict.setdefault('conclusion', None)

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery , llm_result = {llm_result}")

        return llm_result

    async def invoke_requery_sql(self, sql, information, knowledge) -> RequeryResult:

        step_history = self.get_step_history_for_requery()

        system_template = REQUERY_SQL_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "requery": "新生成的问题...",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "requery": "",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["sql","information","knowledge","original_query","history_querys","current_time","step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-requery_sql",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "sql":sql, "information":information, "knowledge":knowledge, "original_query": self.original_query,"history_querys": history_querys, "current_time":current_time, "step_history":step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_requery_sql, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {}

        # Ensure required fields exist with defaults (json_repair may return incomplete dicts).
        if 'requery' not in data_dict and 'query' in data_dict:
            data_dict['requery'] = data_dict.pop('query')
        data_dict.setdefault('requery', None)
        data_dict.setdefault('conclusion', None)

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery_sql , llm_result = {llm_result}")

        return llm_result

    async def observe_sql(self, query, sql, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_SQL_ZH

        human_template = "question: {query}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "满足问题的原因",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "不满足问题的原因",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time", "sql", "answer"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        llm_answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-observe_sql",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time, "sql":sql},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.observe_sql, answer = {llm_answer}")

        data_dict = self.format_llm_output(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_sql , llm_result = {llm_result}")

        return llm_result

    async def invoke_sql_execution_failure_kind(
        self,
        *,
        user_query: str,
        generated_sql: str,
        error_text: str,
        db_type: str,
    ) -> str:
        """Classify SQL execution failure: syntax_issue vs other (for is_stuck / repeated-failure)."""
        sql_failure_kind_example_syntax = json.dumps(
            {
                "sql_failure_kind": "syntax_issue",
                "reason": "引擎指出 SQL 不合法，预期可通过改写 SQL 解决。",
            },
            ensure_ascii=False,
        )
        sql_failure_kind_example_other = json.dumps(
            {
                "sql_failure_kind": "other",
                "reason": "表或列在当前库中不存在，属环境/元数据问题而非 SQL 写法笔误。",
            },
            ensure_ascii=False,
        )
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=SQL_EXEC_FAILURE_KIND_PROMPT_ZH,
            input_variables=["current_time", "db_type"],
            partial_variables={
                "sql_failure_kind_example_syntax": sql_failure_kind_example_syntax,
                "sql_failure_kind_example_other": sql_failure_kind_example_other,
            },
        )
        human_prompt = HumanMessagePromptTemplate.from_template(SQL_EXEC_FAILURE_KIND_HUMAN_ZH)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
        user_id = self.metadata["user_id"]
        run_id = self.metadata["run_id"]
        trace_id = self.metadata["trace_id"]
        chain = chat_prompt | self.llm
        try:
            with langfuse.start_as_current_span(
                name="expert-sql_exec_failure_kind",
                trace_context={"trace_id": trace_id},
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": user_query},
                )
                llm_answer = await chain.ainvoke(
                    {
                        "current_time": current_time,
                        "db_type": str(db_type or "unknown"),
                        "user_query": str(user_query or ""),
                        "generated_sql": str(generated_sql or ""),
                        "error_text": str(error_text or ""),
                    },
                    config={"callbacks": [langfuse_handler]},
                )
                span.update_trace(output={"answer": llm_answer})
            langfuse.flush()
        except Exception as e:
            logger.warning("invoke_sql_execution_failure_kind failed | %s", e)
            return "other"

        logger.info(" === ExpertAgent.invoke_sql_execution_failure_kind, answer = %s", llm_answer)
        data_dict = self.format_llm_output(llm_answer)
        if data_dict is None:
            return "other"
        try:
            parsed = SqlFailureKindResult(**data_dict)
        except Exception as e:
            logger.warning("invoke_sql_execution_failure_kind parse failed | %s | data=%s", e, data_dict)
            return "other"
        kind = str(parsed.sql_failure_kind or "").strip().lower()
        if kind == "syntax_issue":
            return "syntax_issue"
        return "other"

    async def observe_common(self, query, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_COMMON_ZH

        human_template = "question: {query};\n\nanswer:{answer}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "满足问题的原因",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "不满足问题的原因",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        llm_answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-observe_common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.observe_common, answer = {llm_answer}")

        data_dict = self.format_llm_output(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_common , llm_result = {llm_result}")

        return llm_result

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

    async def get_all_knowledge_blocks(self) -> Optional[MetadataValuesResult]:
        """
        从 dataservices 获取所有知识块数据（包含 id, text, metadata_value）。
        用于两阶段知识检索的第一阶段数据源。
        """
        logger.info(f"=========get_all_knowledge_blocks, data_descriptors: {self.data_descriptors}")
        try:
            collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]
            logger.info(f"get_all_knowledge_blocks collection_names: {collection_names}")

            await self.data_services_client._create_session()
            result = await self.data_services_client.find_metadata_values_in_collections(
                collection_names=collection_names
            )

            if result.status != "success":
                logger.error(f"find_metadata_values_in_collections failed: {result.errors}")
                return None

            logger.info(f"get_all_knowledge_blocks success, items count: {len(result.get_all_items())}")
            return result

        except Exception as e:
            logger.error(f'An error occurred during get_all_knowledge_blocks: {e}')
            return None
        finally:
            await self.data_services_client.close()

    async def select_relevant_knowledge(self, knowledge_summaries: str) -> KnowledgeSelectionResult:
        """Stage 1 核心: 使用 LLM 从知识摘要中筛选与用户问题相关的 knowledge_id。

        将一个批次的摘要文本 + 用户问题发给 LLM (LOCATE_DB_KNOWLEDGE_PROMPT_ZH)，
        LLM 返回 JSON: { knowledge_ids: [...], intent_analysis, reasoning }。
        当知识块较多时，会被 get_knowledge() 拆成多个批次并行调用本方法。
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_template = LOCATE_DB_KNOWLEDGE_PROMPT_ZH
        human_template = "{query}"

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge", "current_time"],
        )
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        chain = chat_prompt | self.llm

        with langfuse.start_as_current_span(
            name="expert-select-db-knowledge",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge_summaries, "current_time": current_time},
                config={"callbacks": [langfuse_handler]}
            )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.select_relevant_knowledge, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            logger.error("select_relevant_knowledge: LLM output parsing failed, returning empty result")
            return KnowledgeSelectionResult(knowledge_ids=[], intent_analysis="", reasoning="parsing failed")

        return KnowledgeSelectionResult(**data_dict)

    async def get_knowledge(self) -> str:
        """
        两阶段知识检索：
        第一阶段（粗筛）：获取所有知识块的摘要（metadata_value），LLM 根据用户问题筛选出相关的 knowledge_ids
        第二阶段（精取）：根据筛选出的 knowledge_ids，获取对应的完整知识内容（text 字段）

        粗筛为空时：回退为“全部模块摘要再让 LLM 选”，最多重试 3 次。
        """
        logger.info(f"=========get_knowledge (two-stage), query: {self.query}, data_descriptors: {self.data_descriptors}")

        knowledge_str = ""
        max_empty_retries = 3

        try:
            # ── Stage 1: 粗筛 ──────────────────────────────────────────
            # 从 data-services 获取所有知识块（含 摘要 + 全文）
            knowledge_blocks = await self.get_all_knowledge_blocks()

            if knowledge_blocks is None or not knowledge_blocks.get_all_items():
                logger.warning("get_knowledge: No knowledge blocks found, falling back to empty knowledge")
            else:
                unique_ids: List[str] = []
                domain_fit_votes = {"fit": 0, "mismatch": 0, "uncertain": 0}
                mismatch_evidences: List[str] = []

                async def _collect_selection_results(batch_results):
                    selected_ids = []
                    local_votes = {"fit": 0, "mismatch": 0, "uncertain": 0}
                    local_evidences: List[str] = []
                    for idx, result in enumerate(batch_results):
                        if isinstance(result, Exception):
                            logger.error(f"get_knowledge: Batch {idx + 1} failed with error: {result}")
                            continue
                        if result.knowledge_ids:
                            selected_ids.extend(result.knowledge_ids)
                        fit = str(getattr(result, "domain_fit", "uncertain") or "uncertain").strip().lower()
                        if fit not in local_votes:
                            fit = "uncertain"
                        local_votes[fit] += 1
                        evidence = str(getattr(result, "mismatch_evidence", "") or "").strip()
                        if evidence:
                            local_evidences.append(evidence)
                    # 去重（保留首次出现顺序）
                    seen = set()
                    deduped = [kid for kid in selected_ids if not (kid in seen or seen.add(kid))]
                    return deduped, local_votes, local_evidences

                # 首次：按 60000 字符上限分批粗筛
                metadata_batches = knowledge_blocks.extract_metadata_as_batches(max_chars_per_batch=60000)
                logger.info(
                    f"get_knowledge: {len(knowledge_blocks.get_all_items())} knowledge blocks "
                    f"split into {len(metadata_batches)} batches"
                )

                async def _process_batch(batch_idx, batch, total_batches, attempt_label):
                    logger.info(
                        f"get_knowledge[{attempt_label}]: Processing batch {batch_idx + 1}/{total_batches}, "
                        f"chars: {len(batch)}"
                    )
                    selection_result = await self.select_relevant_knowledge(batch)
                    if selection_result.knowledge_ids:
                        logger.info(
                            f"get_knowledge[{attempt_label}]: Batch {batch_idx + 1} selected "
                            f"{len(selection_result.knowledge_ids)} knowledge IDs: {selection_result.knowledge_ids}"
                        )
                        logger.info(
                            f"get_knowledge[{attempt_label}]: Batch {batch_idx + 1} intent: "
                            f"{selection_result.intent_analysis}"
                        )
                    else:
                        logger.info(
                            f"get_knowledge[{attempt_label}]: Batch {batch_idx + 1} selected 0 knowledge IDs"
                        )
                    return selection_result

                batch_results = await asyncio.gather(
                    *[
                        _process_batch(idx, batch, len(metadata_batches), "initial")
                        for idx, batch in enumerate(metadata_batches)
                    ],
                    return_exceptions=True,
                )
                unique_ids, domain_fit_votes, mismatch_evidences = await _collect_selection_results(batch_results)
                logger.info(f"get_knowledge: Initial unique selected knowledge IDs: {len(unique_ids)}")

                # 粗筛为空：返回全部模块摘要再让 LLM 选，最多重试 3 次
                if not unique_ids:
                    all_summaries = knowledge_blocks.extract_metadata_as_string()
                    # 若全文摘要过大，仍按边界分批，但每次重试都覆盖全部模块
                    retry_batches = knowledge_blocks.extract_metadata_as_batches(max_chars_per_batch=60000)
                    if not retry_batches and all_summaries:
                        retry_batches = [all_summaries]

                    for retry_idx in range(1, max_empty_retries + 1):
                        logger.warning(
                            "get_knowledge: coarse filter empty, retry %d/%d with ALL module summaries "
                            "(batches=%d, total_chars=%d)",
                            retry_idx,
                            max_empty_retries,
                            len(retry_batches),
                            len(all_summaries or ""),
                        )
                        retry_results = await asyncio.gather(
                            *[
                                _process_batch(
                                    idx,
                                    batch,
                                    len(retry_batches),
                                    f"retry-{retry_idx}",
                                )
                                for idx, batch in enumerate(retry_batches)
                            ],
                            return_exceptions=True,
                        )
                        unique_ids, domain_fit_votes, mismatch_evidences = await _collect_selection_results(
                            retry_results
                        )
                        logger.info(
                            "get_knowledge: Retry %d/%d selected knowledge IDs: %d",
                            retry_idx,
                            max_empty_retries,
                            len(unique_ids),
                        )
                        if unique_ids:
                            break

                logger.info(f"get_knowledge: Total unique selected knowledge IDs: {len(unique_ids)}")

                # ── Stage 2: 精取 ──────────────────────────────────────
                # 按选中的 ID 从同一个 MetadataValuesResult 中提取 text 全文，无需额外网络请求
                if unique_ids:
                    knowledge_str = knowledge_blocks.get_text_by_ids(unique_ids)
                    logger.info(f"get_knowledge: Retrieved full knowledge content, length: {len(knowledge_str)}")

                if unique_ids:
                    self._consecutive_empty_knowledge_rounds = 0
                    self._last_selection_domain_fit = "fit"
                    self._last_selection_mismatch_evidence = ""
                else:
                    self._consecutive_empty_knowledge_rounds += 1
                    # Majority vote from batch-level domain_fit signal
                    if domain_fit_votes["mismatch"] > max(domain_fit_votes["fit"], domain_fit_votes["uncertain"]):
                        self._last_selection_domain_fit = "mismatch"
                    elif domain_fit_votes["fit"] > max(domain_fit_votes["mismatch"], domain_fit_votes["uncertain"]):
                        self._last_selection_domain_fit = "fit"
                    else:
                        self._last_selection_domain_fit = "uncertain"
                    self._last_selection_mismatch_evidence = " | ".join(mismatch_evidences[:3])
                logger.info(
                    "[DomainMismatchHeuristic][Expert] step=%d empty_rounds=%d domain_fit=%s selected_ids=%d",
                    self.current_step,
                    self._consecutive_empty_knowledge_rounds,
                    self._last_selection_domain_fit,
                    len(unique_ids),
                )

        except Exception as e:
            logger.error(f'An error occurred during two-stage knowledge retrieval: {e}')
            raise

        # 合并来自 semantic group 其他 agent 的额外上下文（如代码分析结果、文档片段）
        extra_context = (self.metadata or {}).get('extra_context', '')
        if extra_context:
            logger.info(f"get_knowledge: 发现 extra_context ({len(extra_context)} 字)，合并到 knowledge")
            if knowledge_str:
                knowledge_str = (
                    f"========================================\n"
                    f"【参考上下文 — 仅供理解数据结构与业务逻辑，不作为事实数据】\n"
                    f"========================================\n"
                    f"重要提示：以下内容来自上游其他智能体的分析结果，可能是相关的业务逻辑的代码、"
                    f"接口文档或设计文档等参考材料。其中的示例数据（如示例用户名、示例邮箱、"
                    f"示例订单号等）仅用于说明接口格式和字段含义，不代表数据库中真实存在的数据。\n"
                    f"生成 SQL 时，WHERE 条件中的具体值必须严格来自用户问题原文或维度数据，"
                    f"严禁将以下参考上下文中的示例数据作为查询条件。\n"
                    f"========================================\n\n"
                    f"{extra_context}"
                )
            else:
                knowledge_str = extra_context

        # 合并 code_contexts（代码业务逻辑，作为理解数据含义的重要参考）
        code_contexts = (self.metadata or {}).get('code_contexts', [])
        if code_contexts and isinstance(code_contexts, list):
            code_text = "\n\n".join(code_contexts)
            logger.info(f"get_knowledge: 发现 code_contexts (共{len(code_contexts)}个, {len(code_text)}字)，合并到 knowledge")
            if knowledge_str:
                knowledge_str = f"{knowledge_str}\n\n{code_text}"
            else:
                knowledge_str = code_text

        # doc_contexts（文档内容，含示例数据，可能导致幻觉，不合并到 knowledge）
        doc_contexts = (self.metadata or {}).get('doc_contexts', [])
        if doc_contexts and isinstance(doc_contexts, list):
            doc_total = len(doc_contexts)
            doc_chars = sum(len(str(d)) for d in doc_contexts)
            logger.info(
                "get_knowledge: 忽略 doc_contexts (共%d个, %d字)，"
                "文档内容含示例数据可能导致 SQL 生成幻觉，已跳过",
                doc_total, doc_chars,
            )

        logger.debug(f"get knowledge: {knowledge_str}")
        logger.info(f"get knowledge: {knowledge_str[:100] if knowledge_str else 'None'}")
        return knowledge_str

    def analyze_descriptor_types(self):
        """
        Parse descriptor_types from JSON format.
        Returns: (ddname, agent_type, db_type)

        Expected input: self.descriptor_types is a list with one element that is a
        JSON array string, e.g. ['[{"name":"dd","descriptorType":"structured-mysql","dbType":"mysql",...}]']
        """
        if not self.descriptor_types or not isinstance(self.descriptor_types, list) or len(self.descriptor_types) == 0:
            logger.error(f"analyze_descriptor_types: invalid descriptor_types={self.descriptor_types}")
            return "", "unknown", ""

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

            return name, descriptor_type, db_type
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"analyze_descriptor_types: failed to parse JSON: {e}, raw={first_item[:200]}")
            return "", "unknown", ""

    def _should_fast_fail_out_of_scope(self, llm_result: LLMResult, knowledge: str) -> bool:
        # Preserve AI flexibility: allow one exploratory step first.
        if self.current_step <= 1:
            return False
        if str(getattr(llm_result, "reason_code", "") or "").strip():
            return False
        if str(getattr(llm_result, "conclusion", "") or "").strip() != "continue":
            return False
        if str(knowledge or "").strip():
            return False
        if self._consecutive_empty_knowledge_rounds < 2:
            return False
        return self._last_selection_domain_fit == "mismatch"

    def analyze_descriptor_source_metadata(self):
        """
        Parse source metadata from JSON config field.
        Returns: {
            'dd1name': {'host': 'mysql-server', 'port': 3306, 'user': 'root', ...},
            'dd2name': {'host': 'postgres-server', 'port': 5432, ...}
        }
        """
        source_metadatas = {}
        if not self.descriptor_types or not isinstance(self.descriptor_types, list) or len(self.descriptor_types) == 0:
            return source_metadatas

        first_item = self.descriptor_types[0].strip()
        try:
            data_list = json.loads(first_item)
            if not isinstance(data_list, list):
                data_list = [data_list]
            for cfg in data_list:
                name = cfg.get("name", "")
                config = cfg.get("config", {})
                if not name or not config:
                    continue
                parsed = {}
                for k, v in config.items():
                    if k == 'port':
                        try:
                            parsed[k] = int(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                    else:
                        parsed[k] = v
                source_metadatas[name] = parsed
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"analyze_descriptor_source_metadata: failed to parse JSON: {e}")
        return source_metadatas

    def custom_json_serializer(self, obj):

        if obj is None:
            return None
        
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        
        elif isinstance(obj, Decimal):
            return float(obj)
        
        elif isinstance(obj, uuid.UUID):
            return str(obj)
        
        elif isinstance(obj, (bytes, bytearray)):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return obj.hex()

        elif isinstance(obj, Enum):
            return obj.value

        elif isinstance(obj, Path):
            return str(obj)
        
        elif isinstance(obj, (set, frozenset)):
            return list(obj)
        
        elif hasattr(obj, 'dtype'):
            if hasattr(obj, 'tolist'):
                return obj.tolist()
            elif hasattr(obj, 'item'):
                return obj.item()
        
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    async def step(self) -> str:
        """Execute a single step with streaming support."""

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        if agent_type not in ["structured"]:
            raise ValueError(f"Unsupported descriptor type: {agent_type}. ")
        
        if agent_type == "structured" and db_type not in SUPPORTED_DATABASE_TYPES:
            raise ValueError(f"Unsupported db type: {db_type}. ")

        llm_result = None
        dimensions = ""
        dimensions_reason = ""
        self._last_sql_execution_error = False
        try:
            if agent_type == "structured":
                # Determine whether the current query needs to execute SQL or should be analyzed based on the large model itself.
                task_analyze = await self.invoke_structured_task_analyze()
                if task_analyze.conclusion == "sql":
                    knowledge = await self.get_knowledge()
                    if SQL_PROCESS_MODE == "dictionary":
                        llm_result, dimensions, dimensions_reason = await self.invoke_structured_dictionary_mode(knowledge, db_type)
                    else:
                        llm_result = await self.invoke_structured(knowledge, db_type)

                    if llm_result:
                        # if llm result to say terminate, this agent will end
                        if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                            self.state = AgentState.FINISHED
                            source_metadata = self.analyze_descriptor_source_metadata()
                            db_connect_config = source_metadata[ddname]
                            sql_result: Union[List[Dict[str, Any]], Dict[str, Any]] = []
                            # Execute the SQL statement generated by the large model.
                            unfulfilled_needs_for_error: List[Dict[str, Any]] = []
                            try:
                                sql_tables_valid, unknown_tables = self._validate_sql_table_whitelist(
                                    llm_result.answer,
                                    self._selected_table_whitelist,
                                )
                                if not sql_tables_valid:
                                    intent_hint = (self.original_query or self.query or "").strip()
                                    normalized_available = {
                                        self._normalize_db_object_name(t)
                                        for t in (self._cached_available_tables or [])
                                        if str(t or "").strip()
                                    }
                                    recoverable = [
                                        t for t in (unknown_tables or [])
                                        if t in normalized_available
                                    ]
                                    truly_missing = [
                                        t for t in (unknown_tables or [])
                                        if t not in normalized_available
                                    ]
                                    auto_expand_enabled = os.getenv(
                                        "ENABLE_SELECTOR_AUTO_EXPAND", "true"
                                    ).strip().lower() not in ("false", "0", "no")
                                    if auto_expand_enabled and recoverable and not truly_missing:
                                        current_normalized = {
                                            self._normalize_db_object_name(t)
                                            for t in (self._selected_table_whitelist or [])
                                        }
                                        expanded = list(self._selected_table_whitelist or [])
                                        added: List[str] = []
                                        for t in recoverable:
                                            if t in current_normalized:
                                                continue
                                            expanded.append(t)
                                            current_normalized.add(t)
                                            added.append(t)
                                        logger.warning(
                                            "[SelectorAutoExpand] selector dropped same-DB tables that the SQL generator needs — "
                                            "expanding _selected_table_whitelist | added=%s before=%s after=%s sql_preview=%s",
                                            added,
                                            self._selected_table_whitelist,
                                            expanded,
                                            str(llm_result.answer or "")[:200],
                                        )
                                        self._selected_table_whitelist = expanded
                                        sql_tables_valid, unknown_tables = self._validate_sql_table_whitelist(
                                            llm_result.answer,
                                            self._selected_table_whitelist,
                                        )
                                    if not sql_tables_valid:
                                        unfulfilled_needs_for_error = []
                                        for t in (unknown_tables or []):
                                            tt = str(t or "").strip()
                                            if not tt:
                                                continue
                                            in_db = tt in normalized_available
                                            unfulfilled_needs_for_error.append({
                                                "missing_table": tt,
                                                "reason": (
                                                    "selector_filtered_recoverable"
                                                    if in_db
                                                    else "outside_whitelist"
                                                ),
                                                "intent_fragment": intent_hint,
                                                "stage": "sql_validation",
                                            })
                                        raise ValueError(
                                            "SQL references table(s) outside the selected whitelist: "
                                            f"{', '.join(unknown_tables)}. allowed_tables={self._selected_table_whitelist}"
                                        )
                                sql_result = await self.execute_db_query(db_connect_config, db_type, llm_result.answer)
                                logger.info(f"sql execute sql: {llm_result.answer}")
                            except Exception as e:
                                # SQL execution errors should short-circuit this step.
                                logger.error(f"execute_db_query error : {e}")
                                error_message = f"Execution error: sql error: {e}"
                                error_code = self._extract_db_error_code(str(e))
                                if not error_code and "selected whitelist" in str(e):
                                    error_code = "SQL_WHITELIST"
                                sql_failure_kind = await self.invoke_sql_execution_failure_kind(
                                    user_query=self.query,
                                    generated_sql=str(llm_result.answer or ""),
                                    error_text=error_message,
                                    db_type=db_type,
                                )
                                selector_unfulfilled = getattr(
                                    self, "_selector_invalid_tables_with_intent", []
                                )
                                if selector_unfulfilled:
                                    existing_tables = {
                                        n["missing_table"] for n in unfulfilled_needs_for_error
                                    }
                                    for need in selector_unfulfilled:
                                        if need.get("missing_table") not in existing_tables:
                                            unfulfilled_needs_for_error.append(need)
                                structured_control = self._build_structured_control(
                                    reason_code="execution_error",
                                    non_retryable=False,
                                    error_type="execution_error",
                                    error_code=error_code,
                                    error_stage="execute_db_query",
                                    retryable=True,
                                    sql_failure_kind=sql_failure_kind,
                                    unfulfilled_needs=unfulfilled_needs_for_error or None,
                                )
                                self._last_sql_execution_error = True
                                llm_result.reason_code = "execution_error"
                                llm_result.conclusion = "continue"
                                self.state = AgentState.IDLE
                                requery = await self.invoke_requery_sql(llm_result.answer, error_message, knowledge)
                                if requery.conclusion == "terminate" and requery.requery:
                                    llm_result.requery = requery.requery
                                llm_result.answer = (
                                    f"{error_message}, sql: {llm_result.answer}\n"
                                    f"structured_control: {json.dumps(structured_control, ensure_ascii=False)}"
                                )

                            if self._last_sql_execution_error:
                                logger.warning(
                                    "Skip observe_sql due to structured sql_execution_error flag"
                                )
                                # Keep failure snapshots available for repeated-failure detection.
                                self.save_step_status(self.query, llm_result.answer)
                                # Preserve existing requery behavior for next step when available.
                                if hasattr(llm_result, "requery") and llm_result.requery:
                                    self.query = llm_result.requery
                                    self._update_task_description(llm_result.requery)
                                return llm_result.answer, dimensions, dimensions_reason

                            if sql_result:
                                # Case: The large model successfully generated SQL, and data was retrieved.
                                # observe llm result meet question.
                                sql_result_str = json.dumps(sql_result, indent=2, ensure_ascii=False, default=self.custom_json_serializer)
                                logger.debug(f"sql execute sql_result_str: {sql_result_str}")
                                observe_result = await self.observe_sql(self.query, llm_result.answer, sql_result_str, knowledge)
                                if observe_result.conclusion == "terminate":
                                    # Case: The large model successfully generated SQL, data was retrieved, and it is evaluated that the question has been successfully answered. This indicates that the current step has completed its own task and will return directly.
                                    self.state = AgentState.FINISHED
                                    step_status_llm_check_success = "The current answer addresses the question very well."
                                    observe_message = f"\nsql: {llm_result.answer}, \n\nsql query result: {sql_result_str}, \n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"
                                    llm_result.answer = observe_message
                                else:
                                    # Case: The large model successfully generated SQL and data was retrieved, but the evaluation indicates that the data does not match the question, meaning the generated SQL is incorrect. In this case, the question needs to be rephrased to proceed to the next step for generating new SQL.
                                    llm_result.conclusion = "continue"
                                    requery = await self.invoke_requery_sql(llm_result.answer, "searched records do not meet query", knowledge)
                                    if requery.conclusion == "terminate" and requery.requery:
                                        llm_result.requery = requery.requery
                                        self.state = AgentState.IDLE
                                        llm_result.answer = f"searched records do not meet query, sql: {llm_result.answer}, \n\nsql query result: {sql_result_str}, \n\nreason: {observe_result.reason}"
                            else:
                                # Case: The large model successfully generated SQL, but no data was retrieved. It is necessary to review whether the result is genuinely empty. If it is determined that the SQL is problematic, the question should be rephrased to proceed to the next step for generating new SQL.
                                # if sql no result, will requery and enter next loop
                                sql_result_str = "not found records"
                                observe_result = await self.observe_sql(self.query, llm_result.answer, sql_result_str, knowledge)
                                if observe_result.conclusion == "terminate":
                                    # Case: The large model successfully generated SQL, but no data was retrieved. The evaluation confirms that the SQL is correct, yet there is simply no data. This situation also indicates that the current step has completed its task and will return directly.
                                    self.state = AgentState.FINISHED
                                    step_status_llm_check_success = "The current answer addresses the question very well."
                                    observe_message = f"\nsql: {llm_result.answer} \n\nsql query result: {sql_result_str}\n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"
                                    llm_result.answer = observe_message
                                else:
                                    # Case: The large model successfully generated SQL, but no data was retrieved. The evaluation indicates a mismatch between the data and the question, meaning the generated SQL is incorrect. In this case, the question needs to be rephrased to proceed to the next step for generating new SQL.
                                    llm_result.conclusion = "continue"
                                    requery = await self.invoke_requery_sql(llm_result.answer, "not found records", knowledge)
                                    if requery.conclusion == "terminate" and requery.requery:
                                        llm_result.requery = requery.requery
                                        self.state = AgentState.IDLE
                                        llm_result.answer = f"not found records, sql: {llm_result.answer}, \n reason: {observe_result.reason}"

                else:
                    # If analysis determines the query does not require SQL execution, use the large model for general question answering. If the LLM returns "continue", it indicates the question is unrelated to the context and cannot be answered. No further processing is done here, as the "continue" response will be handled by subsequent logic, proceeding to the next step loop.  
                    # If the LLM can process the query normally (returning "terminate"), but evaluation reveals the question hasn't been fully resolved, the question should be regenerated to enter the next step loop.
                    knowledge = await self.get_knowledge()
                    llm_result = await self.invoke_common(knowledge)
                    if llm_result:
                        if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                            current_tasks_status_str =  self.format_tasks_status(self.current_tasks_status.tasks)
                            observe_result = await self.observe_common(self.query, llm_result.answer, current_tasks_status_str)
                            observe_message = f"\nquery: {self.query} \n\nreason:{observe_result.reason}"
                            if observe_result.conclusion == "continue":
                                llm_result.conclusion = "continue"
                                self.state = AgentState.IDLE
                                requery = await self.invoke_requery()
                                if requery.conclusion == "terminate" and requery.requery:
                                    llm_result.requery = requery.requery
                                llm_result.answer = f"knowledge can do not meet query, \n\nreason: {observe_result.reason}"
                            else:
                                step_status_llm_check_success = "The current answer addresses the question very well."
                                llm_result.answer = f"{llm_result.answer}, \n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"

            else:
                raise ValueError(f"Unknown agent type: {agent_type}")
        except Exception as e:
            # If any issues are encountered during execution, regenerate the question and proceed to the next step loop, including SQL execution errors and re-querying.
            logger.error(f"step error : {e}")
            self.state = AgentState.IDLE
            self.save_step_status(self.query, f"step error : {e}")
            requery = await self.invoke_requery()
            if requery.conclusion == "terminate":
                self.query = requery.requery
                self._update_task_description(requery.requery)
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!", dimensions, dimensions_reason

        # 1. SQL is normally generated and its direct results are judged correct
        # 2. SQL returns no results, trigger re-query
        # 3. NoSQL execution is judged correct
        # 4. NoSQL execution is judged incorrect, trigger re-query
        if llm_result:
            # if llm result to say terminate, this agent will end
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                self.state = AgentState.FINISHED
                self.memory.add_message(Message.assistant_message(llm_result.answer))
                self.save_step_status(self.query, llm_result.answer)

            # if need to re-query, reset query to self.query for next loop
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "continue":
                if self._should_fast_fail_out_of_scope(llm_result, knowledge):
                    llm_result.reason_code = "out_of_scope_non_retryable"
                    logger.warning(
                        "[NonRetryablePropagation][Expert] task_id=%s fast_fail_domain_mismatch=true empty_rounds=%d domain_fit=%s",
                        self.current_task_id,
                        self._consecutive_empty_knowledge_rounds,
                        self._last_selection_domain_fit,
                    )
                # Structured non-retryable signal from model output.
                if str(getattr(llm_result, 'reason_code', '') or '').strip() == "out_of_scope_non_retryable":
                    base_answer = str(llm_result.answer or "").strip()
                    if not base_answer:
                        base_answer = "当前任务超出本领域能力范围，无法提供有效答案。"
                    evidence = str(self._last_selection_mismatch_evidence or "").strip()
                    if evidence and evidence not in base_answer:
                        base_answer = f"{base_answer}\n\nDomain mismatch evidence: {evidence}"
                    if NON_RETRYABLE_MARKER not in base_answer:
                        llm_result.answer = f"{NON_RETRYABLE_MARKER} | {base_answer}"
                    else:
                        llm_result.answer = base_answer
                    llm_result.answer = (
                        f"{llm_result.answer}\n"
                        f"structured_control: {json.dumps(self._build_structured_control(reason_code='out_of_scope_non_retryable', non_retryable=True, retryable=False), ensure_ascii=False)}"
                    )
                    logger.warning(
                        "[NonRetryablePropagation][Expert] task_id=%s marker_emitted=%s source=reason_code action=finish_no_requery answer_chars=%d",
                        self.current_task_id,
                        NON_RETRYABLE_MARKER,
                        len(str(llm_result.answer or "")),
                    )
                    llm_result.requery = ""
                    self.state = AgentState.FINISHED
                self.save_step_status(self.query, llm_result.answer)
                if self.state != AgentState.FINISHED and hasattr(llm_result, 'requery') and llm_result.requery:
                    self.query = llm_result.requery
                    self._update_task_description(llm_result.requery)

            if not llm_result.answer:
                answer = f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"
                return answer, dimensions, dimensions_reason
            else:
                return llm_result.answer, dimensions, dimensions_reason
        else:
            raise ValueError("step can not handle normal!")

    def save_step_status(self, query:str, answer: str):
        step_status = StepStatus(
            id=self.current_step,
            query=query,
            answer=answer
        )
        self.step_status_list.append(step_status)
        logger.info(f"Saved step {self.current_step} status: query='{query}'")

    def get_step_history_for_requery(self) -> str:
        if not self.step_status_list:
            return "No historical step records"
        
        history_lines = []
        for step in self.step_status_list:
            history_lines.append(f"Step {step.id}:")
            history_lines.append(f"  Query: {step.query}")
            history_lines.append(f"  Answer: {step.answer}")
            history_lines.append("")
        
        return "\n".join(history_lines)

    def format_tasks_status(self, tasks):
        if not tasks:
            return "No tasks available"
        
        lines = []
        for task in tasks:
            lines.append(f"Task {task.id}: {task.description}")
            lines.append(f"  Agent: {task.agent}")
            lines.append(f"  Status: {task.status}")
            lines.append(f"  Answer: {task.answer}\n")
        
        return "\n".join(lines)

    def _update_task_description(self, new_task_description: str):
        if self.current_tasks_status and self.current_tasks_status.tasks and self.current_task_id is not None:
            for task in self.current_tasks_status.tasks:
                if task.id == self.current_task_id:
                    task.description = new_task_description
                    logger.info(f"Updated task {self.current_task_id} description to: {new_task_description}")
                    break

    def _build_failure_snapshot(self, step_status: StepStatus) -> Optional[FailureSnapshot]:
        answer = str(getattr(step_status, "answer", "") or "")
        structured = self._extract_structured_control_from_text(answer)
        if not structured:
            structured = self._extract_structured_error_from_text(answer)
        error_type = str(structured.get("error_type") or "").strip().lower()
        error_code = str(structured.get("error_code") or "").strip()
        error_stage = str(structured.get("error_stage") or "").strip().lower()
        if not error_type and "execution error:" in answer.lower():
            error_type = "execution_error"
        if not error_code:
            error_code = self._extract_db_error_code(answer)
        if not error_type:
            return None
        sql_text = self._extract_sql_from_answer(answer)
        root_cause = self._extract_db_root_cause(answer, error_code)
        return FailureSnapshot(
            step_id=int(getattr(step_status, "id", 0) or 0),
            query=str(getattr(step_status, "query", "") or ""),
            sql=sql_text,
            sql_signature=self._normalize_sql_signature(sql_text),
            error_type=error_type,
            error_code=error_code,
            error_stage=error_stage,
            root_cause_type=str(root_cause.get("root_cause_type") or ""),
            root_cause_target=str(root_cause.get("root_cause_target") or ""),
            root_cause_signature=str(root_cause.get("root_cause_signature") or ""),
            answer_excerpt=answer[:500],
        )

    def _rule_based_same_failure(self, previous: FailureSnapshot, current: FailureSnapshot) -> tuple[Optional[bool], str]:
        # Triage stage 1: rules only handle deterministic cases.
        # Return True for hard matches, False for hard non-matches, and None for gray areas
        # that should be delegated to the LLM judge.
        same_error_code = bool(previous.error_code and current.error_code and previous.error_code == current.error_code)
        conflicting_error_code = bool(
            previous.error_code and current.error_code and previous.error_code != current.error_code
        )
        same_error_type = bool(previous.error_type and current.error_type and previous.error_type == current.error_type)
        same_error_stage = bool(
            previous.error_stage and current.error_stage and previous.error_stage == current.error_stage
        )
        same_sql = bool(
            previous.sql_signature and current.sql_signature and previous.sql_signature == current.sql_signature
        )
        both_missing_sql = bool(not previous.sql_signature and not current.sql_signature)
        same_root_cause_signature = bool(
            previous.root_cause_signature
            and current.root_cause_signature
            and previous.root_cause_signature == current.root_cause_signature
        )

        if same_error_code and same_sql:
            return True, f"same_error_code={previous.error_code} with same_sql_signature"
        if same_error_code and same_error_stage and same_root_cause_signature:
            return True, (
                f"same_error_code={previous.error_code}, "
                f"same_error_stage={previous.error_stage}, "
                f"same_root_cause_signature={previous.root_cause_signature}"
            )
        if conflicting_error_code:
            return False, (
                f"conflicting_error_code={previous.error_code}!={current.error_code}"
            )
        if previous.sql_signature and current.sql_signature and not same_sql:
            return None, "different_sql_signature"
        if same_error_type and same_error_stage and same_sql and not conflicting_error_code:
            return True, (
                f"same_error_type={previous.error_type}, "
                f"same_error_stage={previous.error_stage} with same_sql_signature"
            )
        if both_missing_sql and same_error_code and same_error_stage and same_error_type:
            return True, (
                f"same_error_code={previous.error_code}, "
                f"same_error_stage={previous.error_stage}, "
                f"same_error_type={previous.error_type} without_sql_signature"
            )
        return None, ""

    async def _llm_judge_similar_failure(
        self,
        previous: FailureSnapshot,
        current: FailureSnapshot,
    ) -> FailureSimilarityResult:
        prompt = (
            "你是一个失败归因判断器。请比较下面两次失败是否本质上是同一个失败模式。"
            "如果它们只是 query 表述略有不同，但错误类型、错误码、SQL 模板或失败根因基本一致，"
            "请判断 same_failure=true。只输出 JSON，不要输出任何额外文本。\n\n"
            "输出格式："
            "{\"same_failure\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"简短原因\"}\n\n"
            f"previous={json.dumps(previous.model_dump(), ensure_ascii=False)}\n"
            f"current={json.dumps(current.model_dump(), ensure_ascii=False)}"
        )
        answer = await self.llm.ainvoke([HumanMessage(content=prompt)])
        data = self.format_llm_output(answer)
        if not isinstance(data, dict):
            return FailureSimilarityResult()
        return FailureSimilarityResult(**{
            "same_failure": bool(data.get("same_failure", False)),
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "reason": str(data.get("reason", "") or ""),
        })

    @staticmethod
    def _failure_snapshot_for_log(snapshot: FailureSnapshot) -> Dict[str, Any]:
        return {
            "step_id": snapshot.step_id,
            "error_code": snapshot.error_code,
            "error_stage": snapshot.error_stage,
            "root_cause_signature": snapshot.root_cause_signature,
            "sql_signature": snapshot.sql_signature[:240],
            "query": snapshot.query[:120],
        }

    async def _decide_same_failure(self, previous: FailureSnapshot, current: FailureSnapshot) -> tuple[bool, str]:
        # Triage stage 2:
        # 1. short-circuit on high-confidence rule results
        # 2. use the LLM only for ambiguous comparisons
        # This keeps repeated-failure aborts conservative and explainable.
        task_id = getattr(self, "current_task_id", None)
        step_no = getattr(self, "current_step", 0)
        same_by_rule, rule_reason = self._rule_based_same_failure(previous, current)
        if same_by_rule is True:
            logger.warning(
                "Repeated failure triage hard-match | task_id=%s current_step=%s reason=%s previous=%s current=%s",
                task_id,
                step_no,
                rule_reason,
                self._failure_snapshot_for_log(previous),
                self._failure_snapshot_for_log(current),
            )
            await self.emit_progress(
                "sd_same_failure_hard_match",
                message="detected repeated failure by deterministic rule",
                status="running",
                task_id=task_id,
                extra={
                    "reason": rule_reason,
                    "previous": self._failure_snapshot_for_log(previous),
                    "current": self._failure_snapshot_for_log(current),
                },
            )
            return True, f"rule:{rule_reason}"
        if same_by_rule is False:
            logger.info(
                "Repeated failure triage hard-non-match | task_id=%s current_step=%s reason=%s previous=%s current=%s",
                task_id,
                step_no,
                rule_reason,
                self._failure_snapshot_for_log(previous),
                self._failure_snapshot_for_log(current),
            )
            await self.emit_progress(
                "sd_same_failure_hard_non_match",
                message="determined failures are different by deterministic rule",
                status="running",
                task_id=task_id,
                extra={
                    "reason": rule_reason or "hard_non_match",
                    "previous": self._failure_snapshot_for_log(previous),
                    "current": self._failure_snapshot_for_log(current),
                },
            )
            return False, f"rule:{rule_reason}" if rule_reason else "rule:hard_non_match"

        logger.info(
            "Repeated failure triage enters llm judge | task_id=%s current_step=%s pre_rule_reason=%s previous=%s current=%s",
            task_id,
            step_no,
            rule_reason,
            self._failure_snapshot_for_log(previous),
            self._failure_snapshot_for_log(current),
        )
        await self.emit_progress(
            "sd_same_failure_llm_judging",
            message="using LLM to compare ambiguous failure patterns",
            status="running",
            task_id=task_id,
            extra={
                "pre_rule_reason": rule_reason,
                "previous": self._failure_snapshot_for_log(previous),
                "current": self._failure_snapshot_for_log(current),
            },
        )
        llm_result = await self._llm_judge_similar_failure(previous, current)
        logger.info(
            "Repeated failure triage llm result | task_id=%s current_step=%s same_failure=%s confidence=%.2f threshold=%.2f reason=%s",
            task_id,
            step_no,
            llm_result.same_failure,
            llm_result.confidence,
            STUCK_SIMILARITY_CONFIDENCE_THRESHOLD,
            llm_result.reason,
        )
        await self.emit_progress(
            "sd_same_failure_llm_result",
            message="received LLM same-failure judgment",
            status="running",
            task_id=task_id,
            extra={
                "same_failure": llm_result.same_failure,
                "confidence": llm_result.confidence,
                "threshold": STUCK_SIMILARITY_CONFIDENCE_THRESHOLD,
                "reason": llm_result.reason,
            },
        )
        if llm_result.same_failure and llm_result.confidence >= STUCK_SIMILARITY_CONFIDENCE_THRESHOLD:
            return True, (
                f"llm(confidence={llm_result.confidence:.2f}, "
                f"threshold={STUCK_SIMILARITY_CONFIDENCE_THRESHOLD:.2f}): {llm_result.reason}"
            )
        return False, ""

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt_en = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."

        stuck_prompt_zh = "\
        观察到重复的响应。请考虑采用新的策略，避免重复已经尝试过的无效路径。"

        self.next_step_prompt = f"{stuck_prompt_zh}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt_zh}")

    async def is_stuck(self) -> bool:
        """Unified stuck detection: deterministic rules first, LLM fallback second."""
        self._last_stuck_reason = ""

        if len(self.step_status_list) >= STUCK_MIN_SIMILAR_FAILURES:
            snapshots: List[FailureSnapshot] = []
            for step in reversed(self.step_status_list):
                snap = self._build_failure_snapshot(step)
                if not snap:
                    break
                snapshots.append(snap)
                if len(snapshots) >= STUCK_MIN_SIMILAR_FAILURES:
                    break

            if len(snapshots) >= STUCK_MIN_SIMILAR_FAILURES:
                current = snapshots[0]
                matched_reasons: List[str] = []
                consecutive_matches = 1
                for previous in snapshots[1:]:
                    same_failure, same_reason = await self._decide_same_failure(previous, current)
                    if not same_failure:
                        break
                    consecutive_matches += 1
                    if same_reason:
                        matched_reasons.append(same_reason)
                    current = previous

                if consecutive_matches >= STUCK_MIN_SIMILAR_FAILURES:
                    joined_reason = " | ".join(matched_reasons) if matched_reasons else "similar failures detected"
                    self._last_stuck_reason = (
                        f"consecutive_similar_failures={consecutive_matches}"
                        f"/threshold={STUCK_MIN_SIMILAR_FAILURES}: {joined_reason}"
                    )
                    latest_step_id = snapshots[0].step_id
                    latest_answer = ""
                    for st in self.step_status_list:
                        if int(getattr(st, "id", 0) or 0) == int(latest_step_id):
                            latest_answer = str(getattr(st, "answer", "") or "")
                            break
                    latest_sc = self._last_structured_control_from_text(latest_answer)
                    latest_kind = str(latest_sc.get("sql_failure_kind") or "").strip().lower()
                    if latest_kind == "syntax_issue":
                        logger.info(
                            "Repeated failure threshold met but latest step sql_failure_kind=syntax_issue (step_id=%s); not stuck",
                            latest_step_id,
                        )
                        return False
                    task_id = getattr(self, "current_task_id", None)
                    step_no = getattr(self, "current_step", 0)
                    logger.warning(
                        "Repeated failure threshold reached | task_id=%s current_step=%s consecutive=%s threshold=%s reason=%s",
                        task_id,
                        step_no,
                        consecutive_matches,
                        STUCK_MIN_SIMILAR_FAILURES,
                        self._last_stuck_reason,
                    )
                    await self.emit_progress(
                        "sd_repeated_failure_detected",
                        message="detected repeated failure and will stop local retries",
                        status="running",
                        task_id=task_id,
                        extra={
                            "consecutive_matches": consecutive_matches,
                            "threshold": STUCK_MIN_SIMILAR_FAILURES,
                            "reason": self._last_stuck_reason,
                        },
                    )
                    return True

        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )
        if duplicate_count >= self.duplicate_threshold:
            self._last_stuck_reason = "duplicate assistant responses detected"
            return True
        return False

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {**(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    async def run(self) -> AsyncIterable[str]:
        """Run the agent with streaming support."""
        logger.debug(f"************** agent run, query: {self.query}, data_descriptors: {self.data_descriptors} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if self.query:
            self.update_memory("user", self.query)

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1

                current_task = self.metadata.get('current_task', '')
                # Snapshot before step() — step() may update self.query (requery).
                step_query_snapshot = (self.query or "").strip()

                logger.info(f"******************** {current_task}, current query: {self.query}, Executing step {self.current_step}/{self.max_steps}")
                step_query_preview = self._sd_step_query_preview(step_query_snapshot)
                # agent_name is already on the progress frame (agent_id); keep message minimal.
                step_started_msg = (
                    f"executing step {self.current_step}/{self.max_steps}"
                    f" | query: {step_query_preview}"
                )
                step_extra: Dict[str, Any] = {
                    "step": self.current_step,
                    "max_steps": self.max_steps,
                    "step_query": step_query_preview,
                }
                ct = (current_task or "").strip()
                if ct and ct != step_query_snapshot:
                    step_extra["current_task"] = self._sd_step_query_preview(ct, 260)
                    step_started_msg += f" | task: {step_extra['current_task']}"
                await self.emit_progress(
                    "sd_step_started",
                    message=step_started_msg,
                    status="running",
                    task_id=self.current_task_id,
                    extra=step_extra,
                )

                step_result_str = f"step {self.current_step}/{self.max_steps}: query: {step_query_snapshot}"

                step_result ,dimensions, dimensions_reason = await self.step()

                steps_status = self.get_step_history_for_requery()

                logger.debug(f"******************** steps status: \n\n {steps_status}")
                
                step_answer_raw = step_result
                dac_progress_message = ""

                if not dimensions and not dimensions_reason:
                    dac_progress_message = f"answer: {step_answer_raw}\n"
                    step_result = f"{step_result_str}\n\nanswer: {step_answer_raw}\n"

                elif dimensions and not dimensions_reason:
                    dac_progress_message = f"conditions:{dimensions} \n\nanswer: {step_answer_raw}\n"
                    step_result = f"{step_result_str} \n\nconditions:{dimensions} \n\nanswer: {step_answer_raw} \n"

                elif dimensions_reason and not dimensions:
                    dac_progress_message = f"conditions:{dimensions_reason} \n\nanswer: {step_answer_raw}\n"
                    step_result = f"{step_result_str} \n\nconditions:{dimensions_reason} \n\nanswer: {step_answer_raw} \n"

                elif dimensions_reason and dimensions:
                    dac_progress_message = (
                        f"conditions: {dimensions}, {dimensions_reason} \n\nanswer: {step_answer_raw}\n"
                    )
                    step_result = (
                        f"{step_result_str} \n\nconditions: {dimensions}, {dimensions_reason} "
                        f"\n\nanswer: {step_answer_raw} \n"
                    )

                stuck = await self.is_stuck()
                if stuck:
                    stuck_reason = self._last_stuck_reason or "repeated failure detected"
                    stop_notice = (
                        f"{NON_RETRYABLE_REPEAT_MARKER} | repeated_failure_non_retryable | {stuck_reason}"
                    )
                    # Carry forward the last-seen unfulfilled_needs (P3): when
                    # repeated SQL_WHITELIST failures are what triggered
                    # is_stuck, this is exactly the signal upstream needs to
                    # delegate to a different SG that owns the missing tables.
                    repeat_unfulfilled = self._collect_recent_unfulfilled_needs()
                    structured_control = json.dumps(
                        self._build_structured_control(
                            reason_code="repeated_failure_non_retryable",
                            non_retryable=True,
                            retryable=False,
                            unfulfilled_needs=repeat_unfulfilled or None,
                        ),
                        ensure_ascii=False,
                    )
                    step_result = f"{step_result}\n{stop_notice}\n"
                    if self.step_status_list:
                        self.step_status_list[-1].answer = (
                            f"{self.step_status_list[-1].answer}\n{stop_notice}\nstructured_control: {structured_control}"
                        )
                    step_result = f"{step_result}structured_control: {structured_control}\n"
                    self.state = AgentState.FINISHED
                    logger.warning(
                        "Expert detected repeated failure and stopped local retries | task_id=%s step=%s reason=%s",
                        self.current_task_id,
                        self.current_step,
                        stuck_reason,
                    )

                finished_query_preview = self._sd_step_query_preview(step_query_snapshot)
                await self.emit_progress(
                    "sd_step_finished",
                    message=(
                        f"completed step {self.current_step}/{self.max_steps}"
                        f" | query: {finished_query_preview}" 
                        f" | {dac_progress_message}" 
                    ),
                    status="done",
                    task_id=self.current_task_id,
                    extra={
                        "step": self.current_step,
                        "max_steps": self.max_steps,
                        "step_query": finished_query_preview,
                        "result_chars": len(str(step_result or "")),
                    },
                )
                yield step_result

                # Backward compatible soft hint when not hard-stopped but duplicate content is detected.
                if not stuck and self._last_stuck_reason == "duplicate assistant responses detected":
                    self.handle_stuck_state()

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class ExpertAgentExecutorSemanticDomain(AgentExecutor):
    """
    A Expert Agent answer user question.
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
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        max_steps:int = 5,
        agent_id: str = None,

    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.data_descriptors=data_descriptors
        self.dd_namespace=dd_namespace
        self.descriptor_types=descriptor_types
        self.data_services_url=data_services_url
        self.stream_enabled = stream
        self.max_steps = max_steps
        self.agent_id = agent_id

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()
        logger.info(f"=====user query is {query}.")

        metadata = context.metadata
        logger.info(f"=====user request metadata is {metadata}.")

        current_tasks_status = None
        current_tasks_status_str = metadata.get('current_tasks_status', '')
        if current_tasks_status_str:
            current_tasks_status_json = json.loads(current_tasks_status_str)
            current_tasks_status = TaskStatusList(tasks=current_tasks_status_json)
        else:
            current_tasks_status = TaskStatusList(tasks=[])
        
        current_task_id = None
        current_task_id_str = metadata.get('current_task_id')
        if current_task_id_str:
            current_task_id = int(current_task_id_str)

        agent = ExpertAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            dd_namespace=self.dd_namespace,
            descriptor_types=self.descriptor_types,
            data_services_url=self.data_services_url,
            query=query,
            metadata=metadata,
            max_steps=self.max_steps,
            current_tasks_status=current_tasks_status,
            current_task_id=current_task_id,
            agent_id=self.agent_id,
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if self.stream_enabled:
            async def _progress_callback(text: str) -> None:
                await updater.add_artifact(
                    [TextPart(text=text)],
                    name=f'{agent.agent_name}-result',
                )

            agent.progress_callback = _progress_callback
            async for chunk in agent.run():
                if chunk:
                    part = TextPart(text=chunk)
                    await updater.add_artifact(
                        [part],
                        name=f'{agent.agent_name}-result',
                    )
                            
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')