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
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Tuple, Union
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .schema import ROLE_TYPE, AgentState, Message
from .prompts import (
    OBSERVE_PROMPT_COMMON_ZH,
    CHART_GENERATION_SYSTEM_ZH,
    CHART_RELATED_QUERY,
    MERMAID_GENERATION_SYSTEM_ZH,
    OBSERVE_MERMAID_ZH,
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

# Top-level JSON string fields: chart config / Mermaid / ECharts option JSON
# in ``answer``, plus reason / data_summary / requery from chart prompts.
_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "rationale",
    "final_answer",
    "answer",
    "requery",
    "reason",
    "data_summary",
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "
DAC_PROGRESS_LAYER = "sd_chart"

# System Instructions to Agent
INSTRUCTIONS = """
You are an intelligent chart expert to draw graph based on data.

"""

# 前端用于识别并渲染图表的 code 块标识（渲染时查找 ```chart ... ```）
CHART_CODE_BLOCK_FENCE = "chart"

# 前端用于识别并渲染 Mermaid 图表的 code 块标识（渲染时查找 ```mermaid ... ```）
MERMAID_CODE_BLOCK_FENCE = "mermaid"

# Mermaid 图表类型集合：suggested_chart 值在此集合中时走 Mermaid 生成流程
MERMAID_CHART_TYPES = {
    "mermaid_flowchart",
    "mermaid_sequence",
    "mermaid_class",
    "mermaid_state",
    "mermaid_er",
    "mermaid_gantt",
    "mermaid_mindmap",
    "mermaid_timeline",
    "mermaid_journey",
}

# 大模型调用失败时的默认最大重试次数（可通过环境变量 LLM_MAX_RETRIES 覆盖）
DEFAULT_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))

# LLM 在「数据不适合画图」时输出的前缀，下游直接展示说明，不解析为 JSON
CHART_UNAVAILABLE_PREFIX = "【无法生成图表】"

# ==================== Capability Check Protocol (broadcast routing) ====================
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"
PROPAGATED_HISTORY_KEY = "propagated_history"


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


def _normalize_history_turns(turns: Any) -> List[dict]:
    normalized: List[dict] = []
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
    lines: List[str] = []
    for item in turns:
        prefix = "human" if item["role"] == "user" else "assistant"
        lines.append(f"{prefix}：{item['content']}")
    return "\n".join(lines) if lines else "（无）"


def _path_to_alias(path: List[str]) -> str:
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
    """与 routing-agent 广播探测约定的结构化响应（model_dump_json 写入 artifact）。"""

    can_handle: bool = Field(description="Whether this agent can handle the given query.")
    confidence: float = Field(default=0.0, description="Confidence level from 0.0 to 1.0.")
    reason: str = Field(default="", description="Brief explanation for the capability assessment.")
    agent_name: str = Field(default="", description="Name of the responding agent.")
    agent_url: str = Field(default="", description="URL of the responding agent.")
    route_path: List[str] = Field(default_factory=list, description="Best path (single-node for ChartAgent).")
    route_paths: List[dict] = Field(
        default_factory=list,
        description='Top-K paths: [{"path": [...], "confidence": float, "alias": str}, ...].',
    )
    can_contribute: bool = Field(
        default=False,
        description="Whether this agent can partially contribute even if cannot fully handle.",
    )
    contribution: str = Field(default="", description="Brief description when can_contribute=true.")
    execution_strategy: str = Field(default="single", description="Capability response strategy.")


CHART_CAPABILITY_CHECK_PROMPT = """# Role：图表与可视化需求判定器

请按以下步骤**逐步思考**，将推理过程写入 reason 字段，最后**只输出一个 JSON 对象**（不要用 Markdown 代码块包裹）。

## 思考步骤

**步骤 1 - 用户意图**：用户是否在请求绘制/展示图表、可视化、趋势、占比、对比图、统计图、流程图/架构图（适合 Mermaid）等？还是仅要求纯数值计算、翻译、与作图无关的文本问答？

**步骤 2 - 数据可得性**：问题或历史对话中是否包含可用于作图的结构化或半结构化数据（数字列表、表格、分类与取值、时间序列等）？若完全没有数据且需要编造数据才能画图，应倾向 can_handle=false。

**步骤 3 - 本智能体匹配**：本智能体根据**用户提供的真实数据或描述**生成 ECharts 或 Mermaid。不承担业务库 SQL 查询职责；纯闭式数学计算且无「画图/可视化」诉求时，通常不归本智能体处理。

**步骤 4 - 反思**：① 纯数学/逻辑题且无可视化诉求 → 通常 can_handle=false。② 有可视化诉求但关键数据缺失 → can_handle=false。③ 数据与可视化意图均清晰 → can_handle=true。

**步骤 5 - 结论**：综合判定 can_handle 与 confidence（0.0～1.0）。

**步骤 6 - 可贡献性（仅当 can_handle=false）**：仅当能给出**具体、可验证**的补充要求（例如需要哪些字段或表格）时设 can_contribute=true；禁止「补充相关信息」等空泛表述。

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
{{"can_handle": true 或 false, "can_contribute": true 或 false, "contribution": "（仅当 can_contribute=true）", "confidence": 0.0 到 1.0, "reason": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：... 步骤6：... 结论：..."}}
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


def _strip_js_functions_in_json(s: str) -> str:
    """将 JSON 字符串中的 JavaScript 函数（如 \"color\": function (params) { ... }）替换为 null，以便 json.loads 能解析。"""
    out = []
    i = 0
    while i < len(s):
        idx = s.find("function", i)
        if idx == -1:
            out.append(s[i:])
            break
        out.append(s[i:idx])
        paren = s.find("(", idx)
        if paren == -1:
            out.append(s[idx:])
            break
        brace = s.find("{", paren)
        if brace == -1:
            out.append(s[idx:])
            break
        depth = 1
        j = brace + 1
        while j < len(s) and depth > 0:
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
            j += 1
        out.append("null")
        i = j
    return "".join(out)


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


class LLMResult(BaseModel):

    answer: Optional[str] = Field(
        description='The answer of llm for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

    reason: Optional[str] = Field(default=None, description='The reason.')

class ChartRelatedResult(BaseModel):
    """分析查询与图表生成的关联性"""

    can_generate: bool = Field(
        description='Whether a chart can be generated from the data.'
    )

    reason: str = Field(
        description='Brief reason explaining the decision.'
    )

    suggested_chart: Optional[str] = Field(
        default=None,
        description='Suggested ECharts chart type (e.g. pie, bar, line, scatter, radar, heatmap, treemap, sunburst, funnel, gauge, boxplot, candlestick, graph, sankey, parallel, themeRiver, wordCloud, map, etc.) if can_generate is true, otherwise null.'
    )

    data_summary: Optional[str] = Field(
        default=None,
        description='Brief description of extractable data, null if can_generate is false.'
    )

    @field_validator('suggested_chart', 'data_summary', mode='before')
    @classmethod
    def _coerce_null_string(cls, v: Any) -> Any:
        """LLM 常返回 JSON 字符串 "null" 或 "none"，需在校验前转为 Python None。"""
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ('null', 'none'):
            return None
        return v

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

class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class ChartAgent(BaseAgent):
    """Expert Agent"""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None,
    ):
        logger.info('Initializing ChartAgent')
        super().__init__(
            agent_name='ChartAgent',
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
        self.current_step = 0
        self.state: AgentState = AgentState.IDLE
        self.duplicate_threshold: int = 2
        self.old_querys = []
        self.metadata = metadata
        self.max_steps=max_steps
        self.current_tasks_status = current_tasks_status
        self.current_task_id = current_task_id
        self.step_status_list: List[StepStatus] = []
        self._observe_reason_history: List[str] = []  # 多轮审核不通过的意见列表，下一轮生成时全部带入
        # LLM 模式：global=审核通过时仅返回 answer（默认）；agent=审核通过时带 reason 前缀
        self.start_mode: str = (os.getenv("CHART_AGENT_START_MODE", "global").strip().lower() or "global")
        self.agent_id = "ChartAgent"

    @staticmethod
    def _step_query_preview(text: str, limit: int = 420) -> str:
        """Single-line preview of the step query for DAC_PROGRESS."""
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
        exception_occurred = False
        try:
            yield
        except Exception as e:
            exception_occurred = True
            self.state = AgentState.ERROR
            raise e
        finally:
            if not exception_occurred:
                self.state = previous_state

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

    def _get_trace_id(self) -> str:
        """返回 Langfuse 要求的 32 位小写十六进制 trace_id，缺失或非法时生成新 ID。"""
        t = self.metadata.get("trace_id")
        if (
            t
            and isinstance(t, str)
            and len(t) == 32
            and all(c in "0123456789abcdef" for c in t.lower())
        ):
            return t.lower()
        return uuid4().hex

    def format_task_status_list(self) -> str:
        """将 current_tasks_status 格式化为易读字符串，供大模型上下文使用。"""
        if not self.current_tasks_status or not self.current_tasks_status.tasks:
            return "（当前无其他任务状态信息）"
        status_text = {
            "not_started": "未开始",
            "start": "进行中",
            "complete": "已完成",
            "fail": "失败",
        }
        lines = ["## 当前规划中的任务状态\n"]
        for t in self.current_tasks_status.tasks:
            st = status_text.get((t.status or "").strip().lower(), t.status or "未知")
            lines.append(f"### 任务 {t.id}")
            lines.append(f"- **描述**: {t.description}")
            lines.append(f"- **执行 Agent**: {t.agent}")
            lines.append(f"- **状态**: {st}")
            if (t.answer or "").strip():
                lines.append(f"- **结果/回答**:\n{t.answer.strip()}")
            else:
                lines.append("- **结果/回答**: （暂无）")
            lines.append("")  # 空行分隔
        return "\n".join(lines).strip()


    def agent_mode_query(self) -> str:
        """Agent 模式下生成带任务上下文的 query，供大模型使用。"""
        all_tasks_status = self.format_task_status_list()
        return (
            f"所有任务及其状态：\n{all_tasks_status}\n\n"
            f"当前任务编号：{self.current_task_id}\n\n"
            f"当前任务描述（需要据此画图或回答）：\n{self.query}"
        )

    async def is_chart_related_query(self, query: str) -> ChartRelatedResult:

        system_template = CHART_RELATED_QUERY

        human_template = "需要分析的数据: {query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self._get_trace_id()

        chain = chat_prompt | self.llm
        max_retries = DEFAULT_LLM_MAX_RETRIES

        with langfuse.start_as_current_span(
            name="is_chart_related_query",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            for attempt in range(max_retries):
                try:
                    llm_answer = await chain.ainvoke(
                        {"query": query},
                        config={"callbacks": [langfuse_handler]},
                    )
                    span.update_trace(output={"answer": llm_answer})
                    langfuse.flush()
                    data_dict = self.format_llm_output(llm_answer)
                    if not data_dict:
                        raise ValueError("format_llm_output returned None")
                    # LLM 可能返回 suggested_chart/data_summary 为 JSON 的 "null" 字符串，需转为 Python None 以通过校验
                    _sc = data_dict.get("suggested_chart")
                    if _sc is None or (isinstance(_sc, str) and _sc.strip().lower() in ("null", "none")):
                        data_dict["suggested_chart"] = None
                    _ds = data_dict.get("data_summary")
                    if _ds is None or (isinstance(_ds, str) and _ds.strip().lower() in ("null", "none")):
                        data_dict["data_summary"] = None
                    llm_result = ChartRelatedResult(**data_dict)
                    logger.info(" === ChartAgent.is_chart_related_query , llm_result = %s", llm_result)
                    return llm_result
                except Exception as e:
                    logger.warning(
                        "is_chart_related_query attempt %s/%s failed (call or parse/validate): %s",
                        attempt + 1,
                        max_retries,
                        e,
                        exc_info=False,
                    )
                    if attempt == max_retries - 1:
                        break
                    await asyncio.sleep(1)

        logger.warning("is_chart_related_query all %s attempts failed, using fallback", max_retries)
        return ChartRelatedResult(
            can_generate=False,
            reason="无法判断是否可绘图（模型调用或解析失败），请重试或检查输入",
            suggested_chart=None,
            data_summary=None,
        )


    async def invoke_common(self, feedback: Optional[str] = None) -> LLMResult:
        """
        Invoke LLM for one step。画图时仅用 query 内数据。
        feedback: 历轮审核不通过的意见（可多轮拼接），本轮会拼入 prompt 以便调整生成（如改图表类型）。
        """

        system_template = CHART_GENERATION_SYSTEM_ZH
        human_template = "需要分析的数据: {query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 非 global 模式时使用 agent_mode_query 作为基础 query
        base_query = self.agent_mode_query() if self.start_mode != "global" else self.query
        effective_query = base_query
        if feedback:
            effective_query = base_query + "\n\n【以下为历轮审核未通过的意见，请综合调整后重新生成图表】\n\n" + feedback
            logger.info("invoke_common 使用历轮审核意见（共 %s 轮）: %s", feedback.count("【第"), feedback[:300] + "..." if len(feedback) > 300 else feedback)

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time"],
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self._get_trace_id()

        chain = chat_prompt | self.llm
        max_retries = DEFAULT_LLM_MAX_RETRIES

        with langfuse.start_as_current_span(
            name="chart_invoke_common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": effective_query}
            )
            for attempt in range(max_retries):
                try:
                    answer = await chain.ainvoke(
                        {"query": effective_query, "current_time": current_time},
                        config={"callbacks": [langfuse_handler]},
                    )
                    span.update_trace(output={"answer": answer})
                    langfuse.flush()
                    logger.info(" === ChartAgent.invoke_common, answer = %s", answer)
                    data_dict = self.format_llm_output(answer)
                    if data_dict is None:
                        raise ValueError("format_llm_output returned None")
                    # 若 LLM 返回的是 ECharts option 对象，校验并包装成前端可识别的 chart 代码块
                    raw_answer = data_dict.get("answer")
                    if isinstance(raw_answer, dict):
                        if self._is_valid_echarts_option(raw_answer):
                            option_str = json.dumps(raw_answer, ensure_ascii=False, indent=2)
                            code_block = f"```{CHART_CODE_BLOCK_FENCE}\n{option_str}\n```"
                            data_dict["answer"] = code_block
                        else:
                            logger.warning(
                                "chart option missing series/data: keys=%s", list(raw_answer.keys())
                            )
                            data_dict["answer"] = (
                                "生成的图表配置不完整（缺少 series 或数据），当前数据或描述可能不适合画图，"
                                "请补充结构化数据或换一种描述。"
                            )
                    llm_result = LLMResult(**data_dict)
                    logger.info(" === ChartAgent.invoke_common , llm_result = %s", llm_result)
                    return llm_result
                except Exception as e:
                    logger.warning(
                        "invoke_common attempt %s/%s failed (call or parse/validate): %s",
                        attempt + 1,
                        max_retries,
                        e,
                        exc_info=False,
                    )
                    if attempt == max_retries - 1:
                        break
                    await asyncio.sleep(1)

        logger.warning("invoke_common all %s attempts failed, using fallback", max_retries)
        data_dict = {
            "answer": "System error: Unable to process model response",
            "conclusion": "error",
            "reason": "解析或校验失败，请重试。",
            "requery": ""
        }
        return LLMResult(**data_dict)

    async def observe_common(self, query, answer) -> ObserveResult:

        system_template = OBSERVE_PROMPT_COMMON_ZH

        human_template = "需要分析的原始数据: {query};\n\n 需要审查的图表的结果:{answer}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "【格式/类型/数据/逻辑】均符合要求。例如：折线图准确反映了时间序列趋势，JSON 字段完备。",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "【错误维度】具体问题描述。例如：【类型错误】用户要求查看占比，但模型生成了柱状图；建议改为 pie 图。",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self._get_trace_id()

        chain = chat_prompt | self.llm
        max_retries = DEFAULT_LLM_MAX_RETRIES

        with langfuse.start_as_current_span(
            name="chart-observe",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            for attempt in range(max_retries):
                try:
                    llm_answer = await chain.ainvoke(
                        {"query": query, "answer": answer, "current_time": current_time},
                        config={"callbacks": [langfuse_handler]},
                    )
                    span.update_trace(output={"answer": llm_answer})
                    langfuse.flush()
                    logger.info(" === ChartAgent.observe_common, answer = %s", llm_answer)
                    data_dict = self.format_llm_output(llm_answer)
                    if data_dict is None:
                        raise ValueError("format_llm_output returned None")
                    llm_result = ObserveResult(**data_dict)
                    logger.info(" === ChartAgent.observe_common , llm_result = %s", llm_result)
                    return llm_result
                except Exception as e:
                    logger.warning(
                        "observe_common attempt %s/%s failed (call or parse/validate): %s",
                        attempt + 1,
                        max_retries,
                        e,
                        exc_info=False,
                    )
                    if attempt == max_retries - 1:
                        break
                    await asyncio.sleep(1)

        logger.warning("observe_common all %s attempts failed, using fallback", max_retries)
        return ObserveResult(
            reason="System error: Unable to process model response",
            conclusion="error",
        )

    async def invoke_mermaid(self, feedback: Optional[str] = None) -> LLMResult:
        """
        调用 LLM 生成 Mermaid 图表代码。
        feedback: 历轮审核不通过的意见。
        """

        system_template = MERMAID_GENERATION_SYSTEM_ZH
        human_template = "需要分析的内容: {query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base_query = self.agent_mode_query() if self.start_mode != "global" else self.query
        effective_query = base_query
        if feedback:
            effective_query = base_query + "\n\n【以下为历轮审核未通过的意见，请综合调整后重新生成图表】\n\n" + feedback
            logger.info("invoke_mermaid 使用历轮审核意见: %s", feedback[:300] + "..." if len(feedback) > 300 else feedback)

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time"],
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self._get_trace_id()

        chain = chat_prompt | self.llm
        max_retries = DEFAULT_LLM_MAX_RETRIES

        with langfuse.start_as_current_span(
            name="mermaid_invoke",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": effective_query}
            )
            for attempt in range(max_retries):
                try:
                    answer = await chain.ainvoke(
                        {"query": effective_query, "current_time": current_time},
                        config={"callbacks": [langfuse_handler]},
                    )
                    span.update_trace(output={"answer": answer})
                    langfuse.flush()
                    logger.info(" === ChartAgent.invoke_mermaid, answer = %s", answer)
                    data_dict = self.format_llm_output(answer)
                    if data_dict is None:
                        raise ValueError("format_llm_output returned None")
                    # Mermaid 的 answer 是纯字符串（Mermaid 代码），包装成 ```mermaid 代码块
                    raw_answer = data_dict.get("answer")
                    if isinstance(raw_answer, str) and raw_answer.strip() and data_dict.get("conclusion") == "terminate":
                        mermaid_code = raw_answer.strip()
                        # 去掉 LLM 可能多加的 ```mermaid 标记
                        if mermaid_code.startswith("```mermaid"):
                            mermaid_code = mermaid_code[len("```mermaid"):].strip()
                        if mermaid_code.startswith("```"):
                            mermaid_code = mermaid_code[3:].strip()
                        if mermaid_code.endswith("```"):
                            mermaid_code = mermaid_code[:-3].strip()
                        code_block = f"```{MERMAID_CODE_BLOCK_FENCE}\n{mermaid_code}\n```"
                        data_dict["answer"] = code_block
                    llm_result = LLMResult(**data_dict)
                    logger.info(" === ChartAgent.invoke_mermaid , llm_result = %s", llm_result)
                    return llm_result
                except Exception as e:
                    logger.warning(
                        "invoke_mermaid attempt %s/%s failed (call or parse/validate): %s",
                        attempt + 1,
                        max_retries,
                        e,
                        exc_info=False,
                    )
                    if attempt == max_retries - 1:
                        break
                    await asyncio.sleep(1)

        logger.warning("invoke_mermaid all %s attempts failed, using fallback", max_retries)
        data_dict = {
            "answer": "System error: Unable to process model response",
            "conclusion": "error",
            "reason": "Mermaid 图表生成失败，请重试。",
        }
        return LLMResult(**data_dict)

    async def observe_mermaid(self, query, answer) -> ObserveResult:
        """审核 Mermaid 图表代码的正确性和完整性。"""

        system_template = OBSERVE_MERMAID_ZH

        human_template = "需要分析的原始描述: {query};\n\n 需要审查的 Mermaid 图表代码:{answer}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "Mermaid 语法正确，核心节点和关系完整，图表类型与用户意图匹配。",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "【错误维度】具体问题描述。例如：【结构缺失】用户描述了5个步骤，但图表只包含3个节点。",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata.get("user_id", "")
        run_id = self.metadata.get("run_id", "")
        trace_id = self._get_trace_id()

        chain = chat_prompt | self.llm
        max_retries = DEFAULT_LLM_MAX_RETRIES

        with langfuse.start_as_current_span(
            name="mermaid-observe",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            for attempt in range(max_retries):
                try:
                    llm_answer = await chain.ainvoke(
                        {"query": query, "answer": answer, "current_time": current_time},
                        config={"callbacks": [langfuse_handler]},
                    )
                    span.update_trace(output={"answer": llm_answer})
                    langfuse.flush()
                    logger.info(" === ChartAgent.observe_mermaid, answer = %s", llm_answer)
                    data_dict = self.format_llm_output(llm_answer)
                    if data_dict is None:
                        raise ValueError("format_llm_output returned None")
                    llm_result = ObserveResult(**data_dict)
                    logger.info(" === ChartAgent.observe_mermaid , llm_result = %s", llm_result)
                    return llm_result
                except Exception as e:
                    logger.warning(
                        "observe_mermaid attempt %s/%s failed (call or parse/validate): %s",
                        attempt + 1,
                        max_retries,
                        e,
                        exc_info=False,
                    )
                    if attempt == max_retries - 1:
                        break
                    await asyncio.sleep(1)

        logger.warning("observe_mermaid all %s attempts failed, using fallback", max_retries)
        return ObserveResult(
            reason="System error: Unable to process model response",
            conclusion="error",
        )

    def _is_valid_echarts_option(self, option: dict) -> bool:
        """校验 ECharts option 至少包含可渲染的 series。

        支持所有 ECharts 图表类型：
        - 常规图表（bar/line/pie/scatter/radar/funnel/gauge/boxplot/candlestick/heatmap/treemap/sunburst/themeRiver/parallel/wordCloud）：series[].data 非空即可。
        - 关系图（graph）：series 中含 nodes/data + links/edges。
        - 桑基图（sankey）：series 中含 nodes/data + links。
        - 地图（map）：series 中含 data 或 mapType/map。
        """
        if not option or not isinstance(option, dict):
            return False
        series = option.get("series")
        if not series:
            return False
        # ECharts 支持 series 为 dict（单系列）或 list（多系列），统一转 list 处理
        if isinstance(series, dict):
            series = [series]
        if not isinstance(series, list):
            return False
        for s in series:
            if not isinstance(s, dict):
                continue
            chart_type = s.get("type", "")

            # graph 类型：需要 nodes/data + links/edges
            if chart_type == "graph":
                nodes = s.get("nodes") or s.get("data")
                links = s.get("links") or s.get("edges")
                if isinstance(nodes, list) and len(nodes) > 0 and isinstance(links, list):
                    return True
                continue

            # sankey 类型：需要 nodes/data + links
            if chart_type == "sankey":
                nodes = s.get("nodes") or s.get("data")
                links = s.get("links")
                if isinstance(nodes, list) and len(nodes) > 0 and isinstance(links, list) and len(links) > 0:
                    return True
                continue

            # map 类型：有 data 或 mapType/map 即可
            if chart_type == "map":
                if s.get("map") or s.get("mapType"):
                    return True
                data = s.get("data")
                if isinstance(data, list) and len(data) > 0:
                    return True
                continue

            # 通用检查：series[].data 非空
            data = s.get("data")
            if data is None:
                continue
            if isinstance(data, list) and len(data) > 0:
                return True
            if isinstance(data, (int, float)) and not isinstance(data, bool):
                return True
        return False

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

        try:
            # 非 global 模式时使用 agent_mode_query 生成带任务上下文的 query
            query_for_llm = self.agent_mode_query() if self.start_mode != "global" else self.query
            # 每次 step 都调用大模型做「是否可画图」判定，不复用缓存；retry 中任一次成功则走生成流程，不会给客户展示「无法生成图表」
            chart_related = await self.is_chart_related_query(query_for_llm)
            if not chart_related.can_generate:
                msg = f"无法生成图表：{chart_related.reason}"
                self.save_step_status(self.query, msg)
                # 仅在本轮最后一次 step 时把「无法生成图表」返回给客户，避免多步重复展示；非最后一步返回空串不展示
                if self.current_step >= self.max_steps:
                    self.state = AgentState.FINISHED
                    return msg
                return ""
            # 可以生成图则根据 suggested_chart 类型分流：Mermaid 或 ECharts
            is_mermaid = (chart_related.suggested_chart or "") in MERMAID_CHART_TYPES
            # 若有历轮审核不通过的意见，本轮生成时全部带入以便调整
            feedback = None
            if self._observe_reason_history:
                feedback = "\n\n".join(
                    f"【第{i + 1}轮审核未通过】{r}" for i, r in enumerate(self._observe_reason_history)
                )
            # 根据类型调用不同的生成和审核方法
            if is_mermaid:
                llm_result = await self.invoke_mermaid(feedback=feedback)
            else:
                llm_result = await self.invoke_common(feedback=feedback)
            if llm_result:
                if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                    if is_mermaid:
                        observe_result = await self.observe_mermaid(query_for_llm, llm_result.answer)
                    else:
                        observe_result = await self.observe_common(query_for_llm, llm_result.answer)
                    if observe_result.conclusion == "continue":
                        llm_result.conclusion = "continue"
                        self.state = AgentState.IDLE
                        chart_label = "Mermaid 图表" if is_mermaid else "图表"
                        llm_result.answer = f"当前数据不足以生成符合要求的{chart_label}。\n\n原因：{observe_result.reason}"
                        self._observe_reason_history.append(observe_result.reason)  # 追加到多轮历史
                    else:
                        if self.start_mode == "global":
                            llm_result.answer = f"{llm_result.answer}"
                        else:
                            step_status_llm_check_success = "The current answer addresses the question very well."
                            llm_result.answer = f"reason:{step_status_llm_check_success}\n\n{llm_result.answer}"
                        self._observe_reason_history.clear()  # 审核通过，清空历史以便下次请求从头开始
        except Exception as e:
            # 记录完整堆栈便于排查；任何异常都回退为“无相关知识”提示
            logger.exception("step error: %s", e)
            self.state = AgentState.IDLE
            self.save_step_status(self.query, f"step error : {e}")
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"

        if llm_result:
            # if llm result to say terminate, this agent will end
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                self.state = AgentState.FINISHED
                self.save_step_status(self.query, llm_result.answer)

            # if need to re-query, reset query to self.query for next loop
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "continue":
                self.state = AgentState.IDLE
                self.save_step_status(self.query, llm_result.answer)
                # 若本轮未走 observe（invoke 直接返回 continue），且已有历轮审核意见，给用户一条带上下文的反馈，避免重复多段「抱歉」
                if self._observe_reason_history and not (llm_result.answer or "").strip().startswith("当前数据不足以生成符合要求的图表"):
                    final_answer = (
                        "根据历轮审核意见重试后，生成端反馈：\n\n" + (llm_result.answer or "").strip()
                    )
                    return final_answer

            if not llm_result.answer:
                answer = "No relevant data to draw the graph"
                return answer
            else:
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

    async def run(self) -> AsyncIterable[str]:
        """Run the agent with streaming support."""

        # 在 orchestrate.py 文件的第 613-631 行：
        # send_message_payload: dict[str, Any] = {
        #     'message': {
        #         'role': 'user',
        #         'parts': [
        #             {'type': 'text', 'text': query}
        #         ],
        #         'messageId': uuid4().hex,
        #     },
        #     'metadata': {
        #         'user_id': self.metadata['user_id'],
        #         'agent_id': self.metadata['agent_id'],
        #         'run_id': self.metadata['run_id'],
        #         'trace_id': self.metadata['trace_id'],
        #         'memory': memory,
        #         'current_tasks_status': current_tasks_status,
        #         'current_task': f"current task id: [{task_id}], task description: {query} ",
        #         'current_task_id': f"{task_id}",
        #     },
        # }



        # logger.info(f"************** agent run, query: {self.query} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1

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
                    "sd_step_started",
                    message=step_started_msg,
                    status="running",
                    task_id=self.current_task_id,
                    extra=step_extra,
                )

                step_result_str = f"step {self.current_step}/{self.max_steps}: query: {self.query}"

                step_result = await self.step()

                # step_result = f"{step_result_str}\n\nanswer: {step_result}\n"

                finished_query_preview = self._step_query_preview(step_query_snapshot)
                await self.emit_progress(
                    "sd_step_finished",
                    message=(
                        f"completed step {self.current_step}/{self.max_steps}"
                        f" | query: {finished_query_preview}"
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

                step_result = f"{step_result}\n"

                yield step_result

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class ChartAgentExecutor(AgentExecutor):
    """
    A Chart Agent draw graph.
    """

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        max_steps:int = 5,
        agent_card: Optional[AgentCard] = None,
    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.stream_enabled = stream
        self.max_steps = max_steps
        self.agent_card = agent_card

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """routing-agent 广播探测：返回 CapabilityCheckResponse JSON（与 orchestrator_agent_semantic_group 一致）。"""
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        request_metadata = context.metadata if isinstance(context.metadata, dict) else {}
        md = request_metadata

        card = self.agent_card
        agent_name = card.name if card else "ChartAgent"
        agent_description = (card.description if card else "") or ""
        agent_url = (card.url if card else "") or ""

        logger.info(
            "[RoutePlan] ----- %s | capability_check start | query: %s -----",
            agent_name,
            (query[:80] + "..." if len(query) > 80 else query),
        )

        agent_skills_text = "（无）"
        if card and card.skills:
            skills_lines = []
            for skill in card.skills:
                skill_desc = f"- {skill.name}: {skill.description}"
                if hasattr(skill, "tags") and skill.tags:
                    skill_desc += f" (tags: {', '.join(skill.tags)})"
                if hasattr(skill, "examples") and skill.examples:
                    skill_desc += f" (examples: {', '.join(skill.examples)})"
                skills_lines.append(skill_desc)
            agent_skills_text = "\n".join(skills_lines)

        history_text = _history_text_from_metadata(md)

        try:
            manager = ModelManager()
            _extra_body = (
                {"enable_thinking": False}
                if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
                else {}
            )
            llm = manager.get_llm(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=0.01,
                stream=False,
                extra_body=_extra_body,
            )
            prompt = CHART_CAPABILITY_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                history=history_text,
                query=query,
            )
            trace_id = md.get("trace_id", "") or ""
            user_id = md.get("user_id", "") or ""
            run_id = md.get("run_id", "") or ""
            with langfuse.start_as_current_span(
                name="chart-capability-check-llm",
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

            response_text = (response.content or "").strip()
            for p, s in [("```json", "```"), ("```", "```")]:
                if response_text.startswith(p):
                    response_text = response_text[len(p) :]
                if response_text.endswith(s):
                    response_text = response_text[: -len(s)]
            response_text = response_text.strip()
            result_data = json.loads(response_text)
            conf = float(result_data.get("confidence", 0.0))
            leaf_path = [agent_name]
            check_response = CapabilityCheckResponse(
                can_handle=bool(result_data.get("can_handle", False)),
                confidence=conf,
                reason=str(result_data.get("reason", "")),
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[
                    {"path": leaf_path, "confidence": conf, "alias": _path_to_alias(leaf_path)}
                ],
                can_contribute=bool(result_data.get("can_contribute", False)),
                contribution=str(result_data.get("contribution", "")),
            )
        except Exception as e:
            logger.error("Capability check analysis failed: %s", e, exc_info=True)
            leaf_path = [agent_name]
            check_response = CapabilityCheckResponse(
                can_handle=False,
                confidence=0.0,
                reason=f"Analysis failed: {str(e)}",
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[
                    {"path": leaf_path, "confidence": 0.0, "alias": _path_to_alias(leaf_path)}
                ],
            )

        logger.info(
            "[Capability] ChartAgent result | can_handle=%s | confidence=%.2f | agent=%s",
            check_response.can_handle,
            check_response.confidence,
            agent_name,
        )
        response_json = check_response.model_dump_json()
        await updater.add_artifact(
            [TextPart(text=response_json)],
            name="capability-check-response",
        )
        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()

        metadata = context.metadata
        logger.info(f"=====user request metadata is {metadata}.")

        if isinstance(metadata, dict) and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            logger.info("[Capability] Received capability check request, query: %s...", (query or "")[:100])
            await self.handle_capability_check(context, event_queue, query)
            return

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

        agent = ChartAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            query=query,
            metadata=metadata,
            max_steps=self.max_steps,
            current_tasks_status=current_tasks_status,
            current_task_id=current_task_id,
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        direct_return = metadata.get('direct_return', 'disable')

        try:
            if direct_return == "enable":
                # 直接返回时无画图数据可单独返回，返回空或由主流程处理
                part = TextPart(text="")
                await updater.add_artifact(
                    [part],
                    name=f'{agent.agent_name}-result',
                )
                    
                await updater.complete(
                    message=new_agent_text_message(
                        "", context_id=task.context_id
                    )
                )
            else:
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
        finally:
            pass

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')