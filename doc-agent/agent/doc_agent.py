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
from a2a.types import TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .dataservices_client import DataServicesClient, MetadataValuesResult
from .schema import ROLE_TYPE, Memory, Message
from .prompts import (  
    NEXT_STEP_PROMPT_ZH,
    REQUERY_PROMPT_ZH,
    OBSERVE_PROMPT_UNSTRUCTURED_ZH,
    LOCATE_KNOWLEDGE_PROMPT_ZH
)

from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
try:
    # json_repair is a tolerant JSON parser designed specifically for LLM output.
    # It handles common failure modes such as unescaped inner double quotes,
    # trailing commas, missing quotes, python-style single quotes, etc.
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]


# Top-level JSON string fields where the model often inlines user text, code,
# or nested JSON without escaping inner ``"`` (pre-pass before json_repair).
# Includes doc-agent shapes: answer / requery / observe / knowledge-selection.
_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "rationale",
    "final_answer",
    "answer",
    "requery",
    "reason",
    "intent_analysis",
    "reasoning",
)

# 粗筛阶段安全兜底上限（环境变量可调，默认值足够宽松，只在 LLM 异常多选时触发截断）。
_DOC_COARSE_MAX_IDS_PER_BATCH = int(os.getenv("DOC_COARSE_MAX_IDS_PER_BATCH", "60"))
_DOC_COARSE_MAX_TOTAL_IDS = int(os.getenv("DOC_COARSE_MAX_TOTAL_IDS", "150"))

# 向量/混合预检索配置（Step 0）。
# 在 LLM 粗筛之前，先用 data-services 的 hybrid/vector search 召回每个 collection 中
# 与 query 最相关的 top-N 块，大幅减少传入 LLM 的总块数。
_DOC_KNOWLEDGE_VECTOR_ENABLED = os.getenv("DOC_KNOWLEDGE_VECTOR_ENABLED", "true").lower() not in ("false", "0", "no")
_DOC_KNOWLEDGE_VECTOR_LIMIT = int(os.getenv("DOC_KNOWLEDGE_VECTOR_LIMIT", "10"))
_DOC_KNOWLEDGE_VECTOR_SEARCH_TYPE = os.getenv("DOC_KNOWLEDGE_VECTOR_SEARCH_TYPE", "hybrid")

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "
DAC_PROGRESS_LAYER = "sd_doc"


# System Instructions to Agent
INSTRUCTIONS = """
You are an intelligent expert who answers user questions based on relevant knowledge.

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

class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class DocAgent(BaseAgent):
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
        descriptor_types_json_string: str = None,
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
            agent_name='ExpertAgent',
            description='answer user question using yourself knowledge.',
            content_types=['text', 'text/plain'],
        )

        self._knowledge_selection_summary: str = ""  # 由 get_knowledge 填充，供 sd_doc_step_finished 使用

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
        self.descriptor_types_json_string = descriptor_types_json_string
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
        self.step_status_list: List[StepStatus] = []
        # agent_name 历史为 ExpertAgent；进度里的 id 用部署/请求显式值，否则回退 DocAgent
        self.agent_id = agent_id or (metadata or {}).get("agent_id") or "DocAgent"

    def _langfuse_trace_context(self):
        from .tools.knowledge_llm_score import LangfuseTraceContext

        md = self.metadata or {}
        return LangfuseTraceContext(
            user_id=md.get("user_id", ""),
            run_id=md.get("run_id", ""),
            trace_id=md.get("trace_id", ""),
            agent_id=self.agent_id,
        )

    @staticmethod
    def _step_query_preview(text: str, limit: int = 420) -> str:
        """Single-line preview of the step query for DAC_PROGRESS."""
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[: limit - 3] + "..."

    @staticmethod
    def _text_head_tail_preview(
        text: str,
        *,
        head: int = 1000,
        tail: int = 1000,
    ) -> str:
        """Log preview: keep head and tail; collapse middle with '...' when too long."""
        if not text:
            return "None"
        if len(text) <= head + tail + 5:
            return text
        return f"{text[:head]}\n...\n{text[-tail:]}"

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
            run_id=(self.metadata or {}).get("run_id", ""),
            user_id=(self.metadata or {}).get("user_id", ""),
            agent_id=self.agent_id,
            task_id=task_id,
            extra=extra,
        ))

    def _build_knowledge_selection_summary(self, score_meta: Dict[str, Any]) -> str:
        """构建选中知识块的摘要文本（供 sd_doc_step_finished message 拼接）。"""
        report = score_meta.get("score_select_report") or {}
        blocks: List[Dict[str, Any]] = report.get("blocks") or []
        if not blocks:
            return ""

        lines = [
            "",
            f"选中的知识块（共 {len(blocks)} 个）：",
        ]
        for i, b in enumerate(blocks):
            score = float(b.get("score", 0))
            summary = (b.get("summary") or "").strip()
            lines.append(f"  {i + 1}. [{score:.1f}] {summary}")
        return "\n".join(lines)

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
        raw = getattr(answer, "content", "") or ""

        try:
            return json.loads(raw)
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

        return None

    async def invoke_unstructured(self, knowledge) -> LLMResult:

        memory = self.metadata.get('memory', '')

        logger.info(f" === ExpertAgent.invoke_unstructured, memory = {memory}")

        system_template = self.next_step_prompt
        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "Java是一种高级、面向对象、跨平台的编程语言，由Sun公司推出，具有可移植性、安全性等特点，广泛应用于企业级应用和Android开发。",
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
            name="doc-agent-invoke",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": self.query,
                    "agent_id": self.agent_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "user_id": user_id,
                },
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "original_query":self.original_query, "history_querys":history_querys, "memory":memory, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_unstructured, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_unstructured , llm_result = {llm_result}")

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
            name="doc-agent-requery",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": self.query,
                    "agent_id": self.agent_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "user_id": user_id,
                },
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
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery , llm_result = {llm_result}")

        return llm_result

    async def observe_unstructured(self, query, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_UNSTRUCTURED_ZH

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
            name="doc-agent-observe",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": query,
                    "agent_id": self.agent_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "user_id": user_id,
                },
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.observe_unstructured, answer = {llm_answer}")

        data_dict = self.format_llm_output(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_unstructured , llm_result = {llm_result}")

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

    async def get_all_knowledge_blocks(self):
        """
        从 dataservices 获取所有知识块数据（包含 id, text, metadata_value）。
        用于两阶段知识检索的数据源。
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

    async def _retrieve_vector(self) -> Optional[MetadataValuesResult]:
        """
        向量/混合补充检索：利用 data-services 的 hybrid/vector/fulltext search
        召回与用户问题最相关的 top-N 块，转换为统一的 MetadataValuesResult 格式。
        与语义粗筛独立运行，结果在 get_knowledge 中合并。
        """
        collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]
        logger.info(
            "[VECTOR RETRIEVE] query=%r collections=%s search_type=%s limit=%d",
            self.query[:120] if self.query else "",
            collection_names,
            _DOC_KNOWLEDGE_VECTOR_SEARCH_TYPE,
            _DOC_KNOWLEDGE_VECTOR_LIMIT,
        )

        try:
            await self.data_services_client._create_session()
            result = await self.data_services_client.search_multiple_collections(
                collection_names=collection_names,
                query=self.query,
                search_type=_DOC_KNOWLEDGE_VECTOR_SEARCH_TYPE,
                limit=_DOC_KNOWLEDGE_VECTOR_LIMIT,
            )
        except Exception as e:
            logger.error(f"[VECTOR RETRIEVE] search failed: {e}")
            return None
        finally:
            await self.data_services_client.close()

        if not result or not result.results:
            logger.warning("[VECTOR RETRIEVE] returned empty results")
            return None

        # 将 VectorResult 列表转换为 MetadataValuesResult 的数据格式
        data: Dict[str, List[Dict[str, Any]]] = {}
        total_blocks = 0
        for coll_name, search_result in result.results.items():
            if search_result is None or not search_result.vector_result:
                logger.info("[VECTOR RETRIEVE] collection=%s returned 0 items", coll_name)
                continue

            blocks = []
            for vr in search_result.vector_result:
                meta = vr.metadata or {}
                # 使用 data-services 返回的 metadata.id（已有 id 字段）
                block_id = meta.get("id", "")
                blocks.append({
                    "id": block_id,
                    "text": vr.content,
                    # metadata_value 优先取 summary，其次取 metadata_value，最后取 content 前 200 字
                    "metadata_value": (
                        meta.get("summary")
                        or meta.get("metadata_value")
                        or vr.content[:200]
                    ),
                })
            if blocks:
                data[coll_name] = blocks
                total_blocks += len(blocks)
                logger.info(
                    "[VECTOR RETRIEVE] collection=%s returned %d items",
                    coll_name, len(blocks),
                )

        if not data:
            logger.warning("[VECTOR RETRIEVE] all collections returned 0 items")
            return None

        logger.info("[VECTOR RETRIEVE] total %d blocks from %d collections", total_blocks, len(data))
        return MetadataValuesResult(status="success", data=data, errors=None)

    async def select_relevant_knowledge(self, knowledge_summaries: str) -> KnowledgeSelectionResult:
        """
        使用 LLM 从知识摘要中筛选与用户问题相关的知识 ID。

        Args:
            knowledge_summaries: 格式化后的知识摘要字符串（包含 [Knowledge ID: xxx] 标记）

        Returns:
            KnowledgeSelectionResult: 包含相关知识 ID 列表
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_template = LOCATE_KNOWLEDGE_PROMPT_ZH
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
            name="doc-agent-select-knowledge",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": self.query,
                    "agent_id": self.agent_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "user_id": user_id,
                },
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge_summaries, "current_time": current_time},
                config={"callbacks": [langfuse_handler]}
            )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === DocAgent.select_relevant_knowledge, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            logger.error("select_relevant_knowledge: LLM output parsing failed, returning empty result")
            return KnowledgeSelectionResult(knowledge_ids=[], intent_analysis="", reasoning="parsing failed")

        result = KnowledgeSelectionResult(**data_dict)

        # 安全兜底：单批次返回 ID 数量异常时截断（防止 LLM 过度选择导致二阶拉取成本爆炸）
        n_ids = len(result.knowledge_ids)
        if n_ids > _DOC_COARSE_MAX_IDS_PER_BATCH:
            logger.warning(
                "select_relevant_knowledge: LLM returned %d ids (cap=%d), truncating",
                n_ids, _DOC_COARSE_MAX_IDS_PER_BATCH,
            )
            result.knowledge_ids = result.knowledge_ids[:_DOC_COARSE_MAX_IDS_PER_BATCH]

        return result

    async def get_knowledge(self) -> str:
        """
        两阶段知识检索：
        第一阶段（粗筛）：获取所有知识块的摘要（metadata_value），LLM 根据用户问题筛选出相关的 knowledge_ids
        第二阶段（精取）：根据筛选出的 knowledge_ids，获取对应的完整知识内容（text 字段），用换行符拼接
        """
        logger.info(f"=========get_knowledge (two-stage), query: {self.query}, data_descriptors: {self.data_descriptors}")

        knowledge_str = ""

        try:
            # 第一阶段：获取所有知识块
            knowledge_blocks = await self.get_all_knowledge_blocks()

            if knowledge_blocks is None or not knowledge_blocks.get_all_items():
                logger.warning("get_knowledge: No knowledge blocks found, falling back to empty knowledge")
            else:
                # 将摘要分批（避免超出 LLM 上下文限制）
                metadata_batches = knowledge_blocks.extract_metadata_as_batches(max_chars_per_batch=60000)
                logger.info(f"get_knowledge: {len(knowledge_blocks.get_all_items())} knowledge blocks split into {len(metadata_batches)} batches")

                all_selected_ids = []

                # 对每个批次让 LLM 筛选相关知识 ID（所有批次并行处理）
                async def _process_batch(batch_idx, batch):
                    logger.info(f"get_knowledge: Processing batch {batch_idx + 1}/{len(metadata_batches)}, chars: {len(batch)}")
                    selection_result = await self.select_relevant_knowledge(batch)
                    if selection_result.knowledge_ids:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected {len(selection_result.knowledge_ids)} knowledge IDs: {selection_result.knowledge_ids}")
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} intent: {selection_result.intent_analysis}")
                    else:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected 0 knowledge IDs")
                    return selection_result

                batch_results = await asyncio.gather(
                    *[_process_batch(idx, batch) for idx, batch in enumerate(metadata_batches)],
                    return_exceptions=True
                )

                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"get_knowledge: Batch {idx + 1} failed with error: {result}")
                        continue
                    if result.knowledge_ids:
                        all_selected_ids.extend(result.knowledge_ids)

                # 去重
                seen = set()
                unique_ids = [kid for kid in all_selected_ids if not (kid in seen or seen.add(kid))]
                # 安全兜底：多批次合并后总量超过上限时截断（控制二阶拉取与打分成本）
                if len(unique_ids) > _DOC_COARSE_MAX_TOTAL_IDS:
                    logger.warning(
                        "get_knowledge: total %d unique ids exceeds cap=%d, truncating",
                        len(unique_ids), _DOC_COARSE_MAX_TOTAL_IDS,
                    )
                    unique_ids = unique_ids[:_DOC_COARSE_MAX_TOTAL_IDS]
                logger.info(f"get_knowledge: Total unique selected knowledge IDs: {len(unique_ids)}")

                # Step 1b: 向量补充检索（独立一路，不参与 LLM 粗筛）。
                # 在语义粗筛完成后，用 data-services 的 hybrid search 补充召回语义粗筛可能遗漏的知识块。
                # 向量召回的块合并到 knowledge_blocks 中（确保 get_blocks_by_ids 能找到），ID 一并加入精取阶段。
                if _DOC_KNOWLEDGE_VECTOR_ENABLED and unique_ids:
                    vector_result = await self._retrieve_vector()
                    if vector_result is not None and vector_result.get_all_items():
                        n_before = len(unique_ids)
                        seen = set(unique_ids)
                        vector_new_ids = []
                        for coll_name, blocks in vector_result.data.items():
                            if not isinstance(blocks, list):
                                continue
                            # 将向量召回的块也注册到 knowledge_blocks.data 中，确保第二阶段能拉到全文
                            if coll_name not in knowledge_blocks.data:
                                knowledge_blocks.data[coll_name] = []
                            existing_ids = {b.get("id", "") for b in knowledge_blocks.data[coll_name]}
                            for block in blocks:
                                bid = block.get("id", "")
                                if bid and bid not in existing_ids:
                                    knowledge_blocks.data[coll_name].append(block)
                                    existing_ids.add(bid)
                                if bid and bid not in seen:
                                    seen.add(bid)
                                    vector_new_ids.append(bid)

                        if vector_new_ids:
                            unique_ids.extend(vector_new_ids)
                            logger.info(
                                "get_knowledge: vector supplement added %d new IDs (total %d → %d)",
                                len(vector_new_ids), n_before, len(unique_ids),
                            )
                        else:
                            logger.info("get_knowledge: vector supplement found 0 new IDs")

                # 第二阶段：根据 ID 获取完整知识内容；超长时 LLM 打分并按预算选取
                if unique_ids:
                    knowledge_str, score_meta = await knowledge_blocks.get_text_by_ids(
                        unique_ids,
                        query=self.query,
                        llm=self.llm,
                        parse_output=self.format_llm_output,
                        trace=self._langfuse_trace_context(),
                    )
                    logger.info(
                        "get_knowledge: Retrieved full knowledge content, length=%d, "
                        "score_select_applied=%s",
                        len(knowledge_str),
                        score_meta.get("score_select_applied"),
                    )
                    if score_meta.get("score_select_applied"):
                        logger.info(
                            "get_knowledge: score_select_report=%s",
                            score_meta.get("score_select_report"),
                        )
                        # 构建选块摘要，供 sd_doc_step_finished 的 message 使用
                        self._knowledge_selection_summary = self._build_knowledge_selection_summary(score_meta)

        except Exception as e:
            logger.error(f'An error occurred during two-stage knowledge retrieval: {e}')
            raise

        # 如果 metadata 中有 extra_context（来自 semantic group 的其他 agent 结果），合并到 knowledge 中
        extra_context = (self.metadata or {}).get('extra_context', '')
        if extra_context:
            logger.info(f"get_knowledge: 发现 extra_context ({len(extra_context)} 字)，合并到 knowledge")
            if knowledge_str:
                knowledge_str = (
                    f"{knowledge_str}\n\n"
                    f"--- 以下是来自其他智能体的额外上下文，可能是相关的业务逻辑的代码，也有可能是相关的文档 ---\n\n"
                    f"{extra_context}"
                )
            else:
                knowledge_str = extra_context

        preview = self._text_head_tail_preview(knowledge_str)
        logger.debug(f"get knowledge (full, len={len(knowledge_str)}): {knowledge_str}")
        logger.info("get knowledge: len=%d preview:\n%s", len(knowledge_str), preview)
        return knowledge_str

    def parse_descriptor_types_json(self, descriptor_types_json_string: str) -> List[Dict[str, Any]]:
        """
        解析 DescriptorTypes 环境变量（JSON 格式）为字典列表
        
        Args:
            descriptor_types_json_string: JSON 格式的配置字符串
        Returns:
            解析后的字典列表
        """
        if not descriptor_types_json_string:
            return []
        
        descriptor_types_json_string = descriptor_types_json_string.strip()
        
        if not descriptor_types_json_string.startswith('['):
            logger.warning(f"DescriptorTypes 不是 JSON 数组格式: {descriptor_types_json_string[:100]}...")
            return []
        
        try:
            return json.loads(descriptor_types_json_string)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {e}, 输入: {descriptor_types_json_string[:100]}...")
            return []

    async def step(self) -> str:
        """Execute a single step with streaming support."""

        configs = self.parse_descriptor_types_json(self.descriptor_types_json_string)

        agent_type = "unstructured"

        llm_result = None

        try:
            _success_marker_phrase = "The current answer addresses the question very well."
            # generate final sql for this step
            if agent_type == "unstructured":
                knowledge = await self.get_knowledge()

                # ========== answer_model=original: 直接返回知识内容，跳过 LLM 回答和验证 ==========
                answer_model = self.metadata.get('answer_model', '') if self.metadata else ''
                logger.info(f"[step] 检查 answer_model: '{answer_model}'")
                if answer_model == "original":
                    _orig_success_prefix = (
                        "reason:The current answer addresses the question very well.\n\n"
                    )
                    logger.info(f">>>>>> [answer_model=original] DocAgent.step() 直接返回知识内容，跳过 invoke_unstructured 和 observe <<<<<<")
                    logger.info(
                        "[step][llm-check-success] answer_model=original: prepending orchestrator success reason line "
                        "(same as observe-pass path)"
                    )
                    if knowledge and knowledge.strip():
                        self.state = AgentState.FINISHED
                        out = _orig_success_prefix + knowledge
                        self.save_step_status(self.query, out)
                        return out
                    else:
                        self.state = AgentState.FINISHED
                        no_knowledge_msg = f"未找到与问题 '{self.query}' 相关的知识"
                        out = _orig_success_prefix + no_knowledge_msg
                        self.save_step_status(self.query, out)
                        return out

                llm_result = await self.invoke_unstructured(knowledge)
                if llm_result:
                    _invoke_conc = getattr(llm_result, "conclusion", None)
                    logger.info(
                        "[step][llm-check-success] after invoke_unstructured: conclusion=%s "
                        "(marker only if terminate → observe_unstructured passes)",
                        _invoke_conc,
                    )
                    if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                        current_tasks_status_str =  self.format_tasks_status(self.current_tasks_status.tasks)
                        # observe 判断「answer」是否真正回答问题；第三参为任务状态（非原始 knowledge）
                        observe_result = await self.observe_unstructured(self.query, llm_result.answer, current_tasks_status_str)
                        observe_message = f"\nquery: {self.query} \n\nreason:{observe_result.reason}"
                        logger.info(
                            "[step][llm-check-success] observe_unstructured result: conclusion=%s reason_preview=%s",
                            getattr(observe_result, "conclusion", None),
                            ((observe_result.reason or "")[:240] + "…")
                            if observe_result and len(observe_result.reason or "") > 240
                            else (observe_result.reason if observe_result else ""),
                        )
                        if observe_result.conclusion == "continue":
                            llm_result.conclusion = "continue"
                            self.state = AgentState.IDLE
                            requery = await self.invoke_requery()
                            if requery.conclusion == "terminate" and requery.requery:
                                llm_result.requery = requery.requery
                            llm_result.answer = f"knowledge can do not meet query, \n\nreason: {observe_result.reason}"
                            logger.info(
                                "[step][llm-check-success] marker NOT added: observe conclusion=continue"
                            )
                        else:
                            step_status_llm_check_success = _success_marker_phrase
                            llm_result.answer = f"{llm_result.answer}, \n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"
                            logger.info(
                                "[step][llm-check-success] marker ADDED: appended reason:%s to answer (answer_len=%s)",
                                step_status_llm_check_success[:48] + "…",
                                len(llm_result.answer or ""),
                            )
                    else:
                        logger.info(
                            "[step][llm-check-success] observe_unstructured skipped: invoke conclusion=%s (not terminate), "
                            "no success phrase appended",
                            _invoke_conc,
                        )
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
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"

        # 1. Unstructured processing is correct
        # 2. Unstructured processing triggers re-query
        if llm_result:
            # if llm result to say terminate, this agent will end
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                self.state = AgentState.FINISHED
                self.memory.add_message(Message.assistant_message(llm_result.answer))
                self.save_step_status(self.query, llm_result.answer)

            # if need to re-query, reset query to self.query for next loop
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "continue":
                self.save_step_status(self.query, llm_result.answer)
                if hasattr(llm_result, 'requery') and llm_result.requery:
                    self.query = llm_result.requery
                    self._update_task_description(llm_result.requery)

            if not llm_result.answer:
                answer = f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"
                logger.info(
                    "[step][llm-check-success] final return: empty answer fallback, contains_marker=False"
                )
                return answer
            else:
                _final_has = _success_marker_phrase in (llm_result.answer or "")
                logger.info(
                    "[step][llm-check-success] final return: conclusion=%s answer_chars=%s contains_success_phrase=%s",
                    getattr(llm_result, "conclusion", None),
                    len(llm_result.answer or ""),
                    _final_has,
                )
                return llm_result.answer
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

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt_en = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."

        stuck_prompt_zh = "\
        观察到重复的响应。请考虑采用新的策略，避免重复已经尝试过的无效路径。"

        self.next_step_prompt = f"{stuck_prompt_zh}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt_zh}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

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
                self._knowledge_selection_summary = ""  # 每步开始前清空，避免残留

                current_task = self.metadata.get('current_task', '')

                logger.info(f"******************** {current_task}, current query: {self.query}, Executing step {self.current_step}/{self.max_steps}")

                step_query_snapshot = (self.query or "").strip()
                step_query_preview = self._step_query_preview(step_query_snapshot)
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
                    step_extra["current_task"] = self._step_query_preview(ct, 260)
                    step_started_msg += f" | task: {step_extra['current_task']}"
                await self.emit_progress(
                    "sd_doc_step_started",
                    message=step_started_msg,
                    status="running",
                    task_id=self.current_task_id,
                    extra=step_extra,
                )

                step_result_str = f"step {self.current_step}/{self.max_steps}: query: {self.query}"

                step_result = await self.step()

                steps_status = self.get_step_history_for_requery()

                logger.debug(f"******************** steps status: \n\n {steps_status}")

                finished_query_preview = self._step_query_preview(step_query_snapshot)
                finished_message = (
                    f"completed step {self.current_step}/{self.max_steps}"
                    f" | query: {finished_query_preview}"
                )
                if self._knowledge_selection_summary:
                    finished_message += self._knowledge_selection_summary
                await self.emit_progress(
                    "sd_doc_step_finished",
                    message=finished_message,
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

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class DocAgentExecutor(AgentExecutor):
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
        descriptor_types_json_string: str = None,
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
        self.descriptor_types_json_string=descriptor_types_json_string
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
        logger.info(f"=====answer_model={metadata.get('answer_model', '(not set)') if metadata else '(no metadata)'}")

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

        agent = DocAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            dd_namespace=self.dd_namespace,
            descriptor_types_json_string=self.descriptor_types_json_string,
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