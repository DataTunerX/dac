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
    Dict,
    List,
    Literal,
    Optional,
    Union,
)
from collections import OrderedDict
from collections.abc import Awaitable
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
from langchain_core.tools import StructuredTool
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from model_sdk import ModelManager
from pydantic import BaseModel, Field, ValidationError, field_validator
from typing_extensions import override

from . import broadcast_capability_check as sg_broadcast
from . import capability_chain
from .capability_chain import CapabilityChainResult
from .agent_card_resolve import resolve_agent_card_by_planner_name
from .agentregistry_client import AgentRegistryClient
from .execution_flow import (
    ExecutionTask,
    is_execution_flow_frame,
    render_execution_flow_md,
    strip_execution_flow_lines,
)
from .dataservices_client import (
    CreateHistoryRequest,
    DataServicesClient,
    HistoryMessage,
    SearchHistoryRequest,
)
from .tool_call_utils import invoke_llm_with_tool, safe_langfuse_flush

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
DAC_PROGRESS_LAYER = "skill"
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
NONE_TASK_REASON_CODE = "no_capable_agent"
NONE_TASK_UNASSIGNED_RESULT = "未派发：当前可用智能体中无人可执行此任务。"
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


# One GetHistory dump per run_id. Planner + Executor both call get_history()
# in the same request; repeating the banner looks like two fetches.
_HISTORY_LOG_SEEN: OrderedDict[str, None] = OrderedDict()
_HISTORY_LOG_SEEN_MAX = 256


def _log_history_turns(
    turns: list[dict],
    source: str,
    max_content_len: int = 600,
    run_id: str = "",
) -> bool:
    """Log formatted history turns at INFO level for debugging/tracing.

    Returns True if this call printed the dump. Same ``run_id`` is printed
    at most once so later get_history() reads do not look like a second fetch.
    """
    if not turns:
        return False
    key = (run_id or "").strip()
    if key:
        if key in _HISTORY_LOG_SEEN:
            return False
        _HISTORY_LOG_SEEN[key] = None
        _HISTORY_LOG_SEEN.move_to_end(key)
        while len(_HISTORY_LOG_SEEN) > _HISTORY_LOG_SEEN_MAX:
            _HISTORY_LOG_SEEN.popitem(last=False)
    body_parts: list[str] = []
    for i, item in enumerate(turns, start=1):
        prefix = "用户" if item["role"] == "user" else "助手"
        content = item.get("content", "")
        content_display = content[:max_content_len]
        if len(content) > max_content_len:
            content_display += f"...（截断，共 {len(content)} 字符）"
        body_parts.append(f"── 第 {i} 轮 ({prefix}) ──")
        body_parts.append(content_display)
        body_parts.append("")
    _log_boxed_document(
        f"[GetHistory] {source}",
        meta_lines=[f"turns={len(turns)}"],
        body_label="history",
        body="\n".join(body_parts).rstrip(),
    )
    return True


def _log_add_history(
    agent_id: str,
    user_id: str,
    run_id: str,
    skip_history_write: str,
    is_delegated: str,
    delegator: str,
    query: str,
    answer: str,
    max_content_len: int = 800,
) -> None:
    """Log formatted add-history detail at INFO level for debugging/tracing.

    Mirrors the visual style of ``_log_history_turns`` so operators can
    quickly compare which history entries are being written vs. read.
    """
    query_display = query[:max_content_len]
    if len(query) > max_content_len:
        query_display += f"...（截断，共 {len(query)} 字符）"
    answer_display = answer[:max_content_len]
    if len(answer) > max_content_len:
        answer_display += f"...（截断，共 {len(answer)} 字符）"

    _log_boxed_document(
        "[AddHistory] 写入明细",
        meta_lines=[
            f"agent_id={agent_id}    user_id={user_id}",
            f"run_id={run_id}",
            f"skip_history_write={skip_history_write}    "
            f"is_delegated={is_delegated}    delegator={delegator}",
        ],
        body_label="payload",
        body=(
            f"── 请求 (query) ──\n{query_display}\n\n"
            f"── 回答 (answer) ──\n{answer_display}"
        ),
    )


# ---------------------------------------------------------------------------
# JSON repair for LLM output
# ---------------------------------------------------------------------------

_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query", "description", "thought_process", "reason", "rationale", "final_answer",
    "contribution",
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


def _parse_json_output(answer) -> Optional[dict]:
    """Parse LLM plain-text output into a dict.

    Tries in order: direct JSON parse, strip markdown fences, escape inner
    quotes, json_repair, ast.literal_eval, single-quote-to-double-quote.
    Returns the parsed dict, or None if all attempts fail.
    """
    raw = "".join(
        [
            str(p.get("text", "")) if isinstance(p, dict) else (getattr(p, "text", None) or str(p))
            for p in (getattr(answer, "content", None) or [])
        ]
    ) if isinstance(getattr(answer, "content", None), list) else ""
    if not raw:
        raw = getattr(answer, "content", None)
    if not isinstance(raw, str):
        raw = str(answer or "")
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw, strict=False)
        return parsed if isinstance(parsed, dict) else None
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
        parsed = json.loads(cleaned_content, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
    if escaped_content != cleaned_content:
        try:
            parsed = json.loads(escaped_content, strict=False)
            return parsed if isinstance(parsed, dict) else None
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
        parsed = json.loads(cleaned_content.replace("'", '"'), strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BaseAgent(BaseModel, ABC):
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}
    agent_name: str = Field(description="The name of the agent.")
    description: str = Field(description="A brief description of the agent's purpose.")
    content_types: list[str] = Field(description="Supported content types.")


def _non_empty_str(value: Any, fallback: str = "(未提供)") -> str:
    """把任意值收敛为非空字符串。

    ``TaskList.original_query`` / ``thought_process`` 已改为必填且 ``min_length=1``，
    若调用方传入空串会让 pydantic 直接校验失败并触发无意义的重试。这里统一兜底。
    """
    text = str(value if value is not None else "").strip()
    return text or fallback


def _require_non_blank(value: Any, field_name: str) -> str:
    """Strip and reject empty / whitespace-only strings. ``depends_on`` is exempt."""
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


class PlannerTask(BaseModel):
    id: int = Field(description="Sequential ID for the task, starting from 1.")
    description: str = Field(
        description=(
            "Description of the subtask handed to the agent. Must not be empty. "
            "If this task consumes data produced by an upstream task, state here "
            "which concrete fields/keys are needed from that upstream task."
        ),
    )
    agent: str = Field(
        description=(
            "Exact agent name of the task to be executed. Must match one of the "
            'available agent names verbatim, or be "NONE".'
        ),
    )
    depends_on: List[int] = Field(
        description=(
            "REQUIRED — always provide this field. List of task IDs that must complete "
            "before this task can run. Write [] explicitly when, and only when, this "
            "task has no upstream dependency (it is the first task, or runs "
            "independently of the others). Never omit it."
        ),
    )

    @field_validator("description", "agent", mode="before")
    @classmethod
    def _reject_blank_task_str(cls, value: Any, info) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("id", mode="before")
    @classmethod
    def _reject_missing_id(cls, value: Any) -> int:
        if value is None or (isinstance(value, str) and not str(value).strip()):
            raise ValueError("id must not be empty")
        return value


class TaskList(BaseModel):
    # 除 tasks[].depends_on 允许 [] 外，其余字段均不允许空。
    thought_process: str = Field(
        description=(
            "REQUIRED, must not be empty. The internal step-by-step reasoning of the "
            "planner (Step1 data need -> Step2 ontology -> Step3 capability match -> "
            "Step4 self-check -> Step5 context/history -> Step6 cross-domain split)."
        ),
    )
    original_query: str = Field(
        description="REQUIRED, must not be empty. Verbatim original user query.",
    )
    tasks: List[PlannerTask] = Field(
        description=(
            "REQUIRED, must contain at least one task and must never be an empty list. "
            "Tasks to be executed sequentially. If no available agent can handle the "
            'query, return exactly one task with agent="NONE".'
        ),
    )

    @field_validator("thought_process", "original_query", mode="before")
    @classmethod
    def _reject_blank_plan_str(cls, value: Any, info) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("tasks")
    @classmethod
    def _reject_empty_tasks(cls, value: List[PlannerTask]) -> List[PlannerTask]:
        if not value:
            raise ValueError("tasks must not be empty")
        return value


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


# ── Chain-driven planning models ──────────────────────────────────────

class CapabilityChainStep(BaseModel):
    """Planner output: one step in the operation chain decomposition."""
    model_config = {"extra": "ignore"}
    step_id: int = Field(description="步骤编号，从 1 开始")
    description: str = Field(description="一步一句话：输入→操作→产出")
    operation: str = Field(description="操作类别，建议从常用类别中选择，若无匹配可用自定义文本")
    input_source: Literal["query", "upstream"] = Field(description="输入来源")
    input_desc: str = Field(description="输入描述")
    output_desc: str = Field(description="期望产出")
    is_final: bool = Field(description="是否最终结果的步骤")
    matched_agent: str = Field(description="匹配的 Agent 名称或 NONE")
    match_reason: str = Field(description="为什么选这个 Agent（或为什么 NONE）")


class ChainPlanResult(BaseModel):
    """LLM output for chain-driven planning."""
    model_config = {"extra": "ignore"}
    thought_process: str = Field(description="完整推理过程")
    original_query: str = Field(description="用户原始问题")
    capability_chain: list[CapabilityChainStep] = Field(description="操作链分解")
    tasks: list[PlannerTask] = Field(description="可执行任务列表")


# ── Recommended operations for chain planning (soft hint, not hard enum) ──

_RECOMMENDED_OPERATIONS: frozenset[str] = frozenset({
    "lookup", "filter", "aggregate", "retrieve", "extract",
    "summarize", "classify", "compare", "translate", "generate", "modify",
})


# Capability check LLM schema: the LLM outputs per-step, per-dimension
# checklists and ratios (see agent/capability_chain.py and
# CAPABILITY_EVALUATION_SCORING_DESIGN.md); can_handle / can_contribute /
# confidence are derived arithmetically by ``capability_chain.aggregate``.
CapabilityCheckToolResult = CapabilityChainResult


def _normalize_capability_result(result_data: dict[str, Any]) -> tuple[bool, bool]:
    """Normalize a (can_handle, can_contribute) pair, aligned with SD orchestrator
    _normalize_member_capability_judgment.

    When can_handle=True, can_contribute is also True.
    """
    can_handle = bool(result_data.get("can_handle", False))
    can_contribute = bool(result_data.get("can_contribute", False))
    if can_handle:
        can_contribute = True
    return can_handle, can_contribute


def _format_skills_for_capability_check(skills: Optional[List[Any]]) -> str:
    """Render loaded skills as ``### name`` blocks with the full SKILL.md body.

    The capability judge scores against the skill body (field lists, command
    examples, coverage statements, exclusions), so nothing is truncated.
    """
    if not skills:
        return "（无）"
    blocks: List[str] = []
    for skill in skills:
        name = str(getattr(skill, "name", "") or "").strip() or "unnamed"
        body = str(getattr(skill, "description", "") or "").strip() or "（无正文）"
        tags = getattr(skill, "tags", None) or []
        header = f"### 技能：{name}"
        if tags:
            header += f"  (tags: {', '.join(str(t) for t in tags)})"
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


class DelegationDetectionResult(BaseModel):
    model_config = {"extra": "ignore"}
    task_type: Literal["structured", "unstructured"] = Field(description="Task type classification. structured=数据库查询、表字段检索、记录查找等有明确字段边界的数据操作；unstructured=文档总结、文本分析、代码审查、翻译、内容生成等无标准答案的分析性任务")
    needs_help: bool = Field(description="Whether another SG's help is needed")
    synthesized_query: str = Field(description="Scoped sub-query for the downstream SG. Required for structured tasks. For unstructured tasks it is also a NECESSARY CONDITION of needs_help=true: if you cannot write an executable sub-query, there is no clear gap and needs_help must be false.")
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
    gap_obtainable: bool = Field(
        default=True,
        description=(
            "Only meaningful when satisfactory=false. Whether the missing information could "
            "plausibly be obtained by executing further steps. "
            "true = the gap is retrievable by more work (another agent holds the data, a query can fetch it, "
            "a missing join key can be resolved). "
            "false = the gap lies outside the capability boundary and no amount of re-execution can produce it "
            "(e.g. the result explicitly states it lacks that ability and no agent in the collaboration pool "
            "declares it; or it requires real-time/external data that is unavailable). "
            "Note: a bare mention in the result that it lacks an ability is NOT by itself reason to set false — "
            "if another agent could supply it, set true. Set true when satisfactory=true."
        ),
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
     - `depends_on`：**必填**整数列表，标明此任务依赖哪些 task id 必须先完成；没有上游依赖时也必须显式写 `[]`，严禁省略该字段。

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

## ⚠ 工具参数必填性（强制，缺字段即为无效输出）
`make_plan_cmd` 的所有参数均为**必填**，且**没有任何默认值**。省略或留空都视为无效输出。

- `thought_process`：必填、非空。写入 Step1–Step6 的完整推理过程。
- `original_query`：必填、非空。逐字复制用户原始输入。
- `tasks`：必填、非空数组，至少包含 1 个任务。
- 每个 task 的字段：
  - `id`：必填，整数，从 1 开始递增。
  - `description`：必填、非空，转述给智能体的子任务。
  - `agent`：必填、非空，必须与[可用智能体]中的名称完全一致，或为 `NONE`。
  - `depends_on`：**必填**。即使该任务没有任何上游依赖，也**必须显式写 `depends_on: []`**；
    若该任务需要上游任务的产出，则**必须**写入对应的上游 task id（如 `depends_on: [1]`）。
    ⚠ 严禁省略 `depends_on` 字段本身——省略会导致跨域依赖丢失、下游误按并行执行。

---

问题：

"""


PLANNER_COT_INSTRUCTIONS_ZH_HISTORY_JSONSTRING = """
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

## JSON 输出要求（强制，缺字段即为无效输出）

你必须输出 **一个** JSON 对象，字段全部必填、没有任何默认值。省略或留空都视为无效输出。

根对象必须恰好包含以下三个键（不要增删键名）：

- `thought_process`：字符串，必填、非空。写入 Step1–Step6 的完整推理过程。
- `original_query`：字符串，必填、非空。逐字复制用户原始输入。
- `tasks`：数组，必填、非空，至少包含 1 个任务对象。

`tasks` 中每个元素必须是对象，且必须包含：

- `id`：整数，从 1 开始递增。
- `description`：非空字符串，转述给智能体的子任务。
- `agent`：非空字符串，必须与[可用智能体]中的名称完全一致，或为 `NONE`。
- `depends_on`：**必填数组**。即使该任务没有任何上游依赖，也**必须显式写 `[]`**；若该任务需要上游任务的产出，则必须写入对应的上游 task id（如 `[1]`）。严禁省略 `depends_on`。

合法 JSON 形状如下（这是格式模板，不是可执行答案；花括号必须成对出现）。

**例 A — 执行上下文已有关联键（必须复用，禁止再查 user-agent）：**

```json
{{
  "thought_process": "Step5 执行上下文已给出张三的用户ID=U003。禁止再创建 user-agent 解析任务。购买商品是订单流水，直接派 order-agent，description 写入 U003，depends_on=[]。",
  "original_query": "查询用户张三购买的商品",
  "tasks": [
    {{
      "id": 1,
      "description": "按用户ID U003 查询该用户购买的商品",
      "agent": "order-agent",
      "depends_on": []
    }}
  ]
}}
```

**例 B — 尚无关联键、需要跨域串联：**

```json
{{
  "thought_process": "Step1 ... Step6 ...",
  "original_query": "用户的原始问题原文",
  "tasks": [
    {{
      "id": 1,
      "description": "先查需要产出关联键的子任务",
      "agent": "user-agent",
      "depends_on": []
    }},
    {{
      "id": 2,
      "description": "再查需要消费上游关联键的子任务，并写明需要哪些上游字段",
      "agent": "order-agent",
      "depends_on": [1]
    }}
  ]
}}
```

无可用智能体时的 JSON 形状：

```json
{{
  "thought_process": "所有可用 Agent 均无法覆盖该问题。",
  "original_query": "用户的原始问题原文",
  "tasks": [
    {{
      "id": 1,
      "description": "No available agent can do this task. ",
      "agent": "NONE",
      "depends_on": []
    }}
  ]
}}
```

输出前自检：
1. 文本可以被 `json.loads` 解析为对象。
2. 根键只有 `thought_process`、`original_query`、`tasks`。
3. 每个 task 都有 `id`、`description`、`agent`、`depends_on`，且 `depends_on` 是数组。
4. 除 JSON 外没有其它字符（或仅有一对 json 代码围栏）。
5. 若 [执行上下文] 或 [组级记忆] 已包含可用关联键（如用户ID），tasks 中不得再出现仅为解析该键的任务；下游 description 必须写明该键值，且 `depends_on` 为 `[]`。

---

问题：

"""
# 2026-09-11 更新：此模板已废弃，请使用链驱动的 PLANNER_CHAIN_INSTRUCTIONS_ZH 模板
# 如需回退，将 USE_CHAIN_PLANNING 设置为 false


# ── 链驱动规划提示词 ─────────────────────────────────────────────────
PLANNER_CHAIN_INSTRUCTIONS_ZH = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
先将用户查询分解为**操作步骤链**，再对链上每一步做数据归属路由，最终输出可执行任务列表。

## 步骤方法论

### Step 0：操作链分解（先拆链，再路由）

把用户 query 分解为操作步骤链："已知输入 → 访问数据/资源 → 执行操作 → 产出结果"。

**拆分规则：**
1. 一步只做**一种操作**、访问**一类数据**。上一步的产出是下一步的输入时拆开，否则不拆。
2. 单一简单问题就是一步。复杂问题是多段链串联。
3. 拆分依据是**问题本身需要什么**，不考虑 Agent 能不能做。Agent 做不了的操作也必须出现在链上（最终会标记 agent=NONE）。
4. 为每个步骤标注：
   - `operation`：操作类别。优先从常用类别中选择，若无匹配可用简短自定义文本。
     常用类别：lookup（按键/条件查询）│ filter（条件筛选）│ aggregate（统计/分组/排序）│
     retrieve（文档/知识库检索）│ extract（从文本/图片/音频抽取）│ summarize（归纳/摘要）│
     classify（分类/打标签/判定）│ compare（对比）│ translate（格式/语言转换）│
     generate（创作新内容）│ modify（写入/更新/删除）
   - `input_source`：`query`（问题文本/附件已给出）或 `upstream`（需由上一步产出）
   - `input_desc`：输入是什么（简洁短语）
   - `output_desc`：期望产出什么（简洁短语）
   - `is_final`：该步骤的产出是否就是用户要的最终结果（之一）

**示例 1**：「张三买了哪些东西」
```
链（2 步）：
  步骤1：用户名(query) → 用户表 → lookup → user_id  [is_final=false]
  步骤2：user_id(upstream) → 订单表 → lookup → 商品列表  [is_final=true]
```

**示例 2**：「北京明天天气怎么样，并且帮我把这句话翻译成英文」
```
链（2 步，独立）：
  步骤1：地点+时间(query) → 天气数据 → lookup → 天气信息  [is_final=true]
  步骤2：文本(query) → 无外部数据 → translate → 英文翻译  [is_final=true]
```

**示例 3**：「对数据库做一次全面体检并给出优化建议」
```
链（4 步）：
  步骤1：时间范围(query) → 慢查询日志 → lookup → 慢查询列表  [is_final=false]
  步骤2：时间范围(query) → 性能指标数据 → lookup → QPS/CPU/内存  [is_final=false]
  步骤3：连接池名(query) → 连接池状态 → lookup → 连接池快照  [is_final=false]
  步骤4：慢查询列表+性能时序+连接池快照(upstream) → 汇总分析 → summarize → 优化建议  [is_final=true]
```

**示例 4**：「帮我查一下」（意图模糊）
```
链（1 步）：
  步骤1：意图(query) → 无外部数据 → classify → 确定查询意图  [is_final=true]
  注：无法匹配到 Agent，最终 agent=NONE
```


### Step 1：对链上每一步做数据归属判定

对 Step 0 产出的链上**每一个步骤**，独立判定该步骤所需数据的业务性质：

1. **静态本体数据**（实体的内在属性/自身状态）：归属于该实体生命周期的 Agent。
   例：商品名称/SKU/库存量 → 商品 Agent；用户昵称/注册时间 → 用户 Agent
2. **动态行为数据**（行为/事件/交互产生的流水或统计）：归属于**记录该行为本身**的 Agent。
   例：商品销量/成交额 → 订单/交易 Agent（不是商品 Agent）；用户登录记录 → 行为日志 Agent


### Step 2：对链上每一步做 Agent 匹配

逐个审视 [可用智能体]，对每一步：
- **读懂它的业务能力范围**，不是死扣描述里的字
- 自问：**该步骤需要的这份数据，是这个 Agent 业务能力的"自然产物/直接职责覆盖"吗？**
- 如果没有任何 Agent 覆盖该步骤的数据需求，则该步骤标记为 agent="NONE"


### Step 3：路由前自检（per-step）

对链上每一步（除 NONE 外），在 thought_process 中回答：
1. 该步骤产出数据的业务性质（静态/动态）
2. 选的 Agent 的业务能力是否天然产出这份数据
3. 是否仅因为"步骤描述里的名词"和"Agent 主体名词"同名就做了路由 → 如果是，必须纠正


### Step 4：执行上下文 + 对话历史闭环

- 若 [执行上下文] 中有已成功执行的步骤结果，复用其产出，从链上删除对应步骤
- 若上下文显示某些步骤已失败，链上对应步骤标记原因
- 对话历史仅用于解析指代


### Step 5：从链推导任务编排

将链上步骤转化为 task 列表：
- 链上每个步骤 → 一个 task，task.id = step_id
- `depends_on` 从链拓扑自然导出：当前步骤 input_source 为 `upstream` 时，depends_on 包含该上游步骤的 id
- `description` 从链信息组装：`{{input_desc}}→{{operation}}→{{output_desc}}`，并注入已知键值
- 链上标记为 NONE 的步骤 → task 的 agent="NONE"
- 如所有步骤均为 NONE → tasks 只输出一个 id=1、agent="NONE" 的 task


## ⚠ 反模式（必须避免）
1. **名词陷阱**：把动态行为数据当成被作用对象领域的数据。商品 Agent 不管销售量——那是交易行为的产物。
2. **关键词字面匹配**：不要因为 Agent 描述里有某个词就路由，要看业务本质。
3. **跳过链分解**：必须先拆链再做路由，不能直接从 query 跳到 agent。
4. **链步骤遗漏**：Agent 做不了的操作也必须出现在链上（agent=NONE）。


## 可用输入：

**[对话历史] (History):**
{history}

**[可用智能体] (Agents):**
{agents}

**[执行上下文] (Information):**
{information}

**[组级记忆] (Group Memory):**
{group_memory}


## 输出要求

只输出一个纯 JSON 对象（不要 ```json 围栏），字段全必填：

{{
  "thought_process": "Step0 链分解 → Step1 数据归属 → Step2 Agent匹配 → Step3 自检 → Step4 上下文 → Step5 任务编排，完整写出每步推理",
  "original_query": "用户问题原文",
  "capability_chain": [
    {{
      "step_id": 1,
      "description": "一步一句话：输入→操作→产出",
      "operation": "lookup 或自定义文本",
      "input_source": "query",
      "input_desc": "输入描述",
      "output_desc": "期望产出",
      "is_final": true,
      "matched_agent": "从可用智能体列表选择的 agent name 或 NONE",
      "match_reason": "为什么选这个 Agent（或为什么 NONE）"
    }}
  ],
  "tasks": [
    {{
      "id": 1,
      "description": "从链信息组装的完整任务描述，含具体键值",
      "agent": "与 capability_chain.matched_agent 一致",
      "depends_on": []
    }}
  ]
}}

输出前自检：
- capability_chain 中每个步骤的 matched_agent 必须映射到 tasks 中对应 id 的 agent 字段
- tasks 中的 depends_on 必须与 capability_chain 中的 input_source=upstream 一致（例：若步骤3的 input_source=upstream，则 depends_on 应包含步骤2的 id）
- 如所有步骤均为 NONE → tasks 只输出一个 agent="NONE" 的 task

---

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

DOMAIN_CHECK_PROMPT = """# 角色：领域相关判定员

本步只回答一件事：这个 skill 跟用户问题有没有关系，值不值得进入后续能力评估。

**相关 (`has`)**：本 skill 能独立处理整题，或只能处理其中一面 / 解析 join 键 / 作为相邻环节参与。单领域问题、跨领域问题用同一条规则。
**无关 (`none`)**：问题里的每一面都落在本 skill 声明之外，本 skill 也不是解题所需的身份或键解析环节。

本步不问、也不得用来改判：能不能一个人做完、是不是问题的「主域」、过滤键现在齐不齐、正文有没有「交给别人」。那些留给后续能力评估（can_handle / can_contribute）。

评估依据只有下面四类文本，按可信度从高到低：
1. 技能正文（skill inventory 中每个技能的完整说明：字段列表、数据格式、命令示例、处理流程、覆盖范围、排除项）
2. 技能短描述
3. Agent 描述
4. 用户问题原文与历史

本标准同时适用于结构化数据技能（表、字段、键）和非结构化技能（文档库、知识库、图片、音频、纯生成 / 转换）。判定必须基于正文声明，禁止靠 Agent/技能名称联想、行业常识或「通常应该有」补字段。

## 判定规程（四步，必须按顺序执行）

**第一步 — 拆面（强制完整）**
只依据问题原文与历史。下列每一项各自成面，禁止压成单一「问题核心」：
- 一类业务对象
- 一类要查的属性
- 一条要完成的动作
- 问句里的主体指称（人名、公司名、工号、业务单号等）
每个面写 L1 领域 / L2 对象 / L3 主题。口语、别称、上下位词按业务语义拆，不要求与技能正文逐字相同。

**第二步 — 逐面只问「能处理或能参与」，不问独占**
对本 Agent 正文声明的每一面，只选一个：
- 能独立给出该面的答案 → 该面相关
- 能提供键、字段、文档片段，或作为同一流程的相邻步骤参与 → 该面相关
- 正文对该面无对应声明 → 该面未命中

「必须先有某 ID」「不能按某键过滤」「输入不接收某形态」只说明参与方式或前置条件，**不是该面无关**。
同义、上下位、字段/主题对应、正文声明的相邻流程环节，都算能参与。

**第三步 — 排除项与分工句只作用于被点名的那一面**
正文中的「不包含 / 不支持 / 不覆盖 / 交给其他技能 / 属于某技能」只让**被点名的那一面**在本 skill 上记未命中。
问句里同时存在本域面时，不得据此宣称整题无关。
下列理由一律禁止，出现则视为判定无效、必须重判为该面相关（若正文对该面有声明）或保持未命中（若确无声明），但不得整题判死：
- 「问题核心是另一面」
- 「本 skill 不能走完全程」
- 「正文让我先交给别人 / 必须先有别人的输出」

**第四步 — 自洽收口**
先写命中面（能处理或能参与的面 + 正文依据），再写未命中面。
- 命中面非空 → `domain_verdict` **只能是 `has`**。其余未命中面留给后续能力评估。
- 命中面为空，且每一面都与声明无关 → `none`
- 只有 L1 对得上、正文覆盖表述模糊、既不能确认也不能否认能否参与 → `uncertain`。只要能判断「能参与」，不要用 uncertain 逃避。

## 禁止猜测

- 判 `has` 必须在 reason 中给出基于 skill 正文的依据（摘要、归纳、同义映射均可，不要求逐字引用）。
- 下列理由一律无效，不得据此判 has：「也许能搜到」；「大模型通用知识能回答」；「属于同一个行业 / 都涉及钱」；「文字部分重叠」；「通常应该有这类数据或字段」。
- 同一问题 + 同一 skill 正文，判定必须唯一；不得因「主域」措辞差异在 has/none 之间摇摆。

---
本 Agent 信息：
- name: {agent_name}
- description: {agent_description}
- skill inventory（技能名 + 完整正文；判定领域覆盖的主要依据）:
{agent_skills}

历史：
{history}

用户问题：
{query}

---
输出要求：
- 只输出一个纯 JSON 对象，**不要使用 ```json 代码块包裹**，直接输出 JSON 文本。
- domain_verdict 取值为 "has"（相关：能处理或能参与）、"none"（无关）或 "uncertain"（不确定）。
- reason 必须先列命中面、再列未命中面。命中面非空时 domain_verdict 必须为 has。

严格按照以下 JSON schema 输出：

{{
  "domain_verdict": "has",
  "reason": "领域交集：明确有 — 问题领域：[面1 L1/L2/L3；面2 …]；命中面：[能处理或能参与的面及正文依据]；未命中面：[…]"
}}

判例（命中面为空、整题无关时）：
{{
  "domain_verdict": "none",
  "reason": "领域交集：明确无 — 问题领域：…；命中面：无；未命中面：全部。Agent 声明：正文无对应声明。"
}}
"""


SKILL_CAPABILITY_CHECK_PROMPT = """# 角色：Skill-Agent 能力评估员

你要评估"本 Agent"能否解决或贡献用户问题。领域交集前置检查已由另一模块完成，你只需负责步骤拆分与逐维度打分。

你负责：拆分步骤、逐维度列清单并给出比例、给出证据等级、书写贡献说明与缺失项。
你不负责：判定 can_handle / can_contribute、计算 confidence。这些由程序按固定公式从你的比例中推导。
你不负责：判定领域交不交叠。这个问题已经回答过了，不要再做领域交集判定。

评估依据：
1. 技能正文（skill inventory 中每个技能的完整说明：字段列表、数据格式、命令示例、处理流程、覆盖范围、排除项）
2. 技能短描述
3. Agent 描述
4. 用户问题原文与历史
5. 领域交集前置检查结论（以 domain_info 形式提供，作为你拆分步骤时的背景参考）

本标准同时适用于结构化数据技能（表、字段、键）和非结构化技能（文档库、知识库、图片、音频、纯生成 / 转换）。

## 一、方法论：任务是一条步骤链

任何任务都是一条或多条这样的链：已知输入 → 访问数据/资源 → 执行操作 → 产出结果（在给定的限定条件下）。
复杂问题是多段链串起来，上一步的产出是下一步的输入。

- 能独立解决 = 本 Agent 能独立走完所有步骤。
- 能贡献 = 本 Agent 能独立走完某一步，且这一步的产出是后续步骤的输入，或本身就是用户要的结果之一。

示例（结构化）："张三买了哪些东西"
  步骤 1：用户名(query) → 用户表[用户名, 用户ID] → lookup → user_id                 is_final=false
  步骤 2：user_id(upstream) → 订单表[订单, 商品] → lookup → 商品列表                 is_final=true
示例（非结构化）："总结这份合同的风险点，并对比去年版本的变化"
  步骤 1：合同文件(query 附件) → 合同文本 → extract → 风险条款列表                    is_final=true
  步骤 2：合同名称(query) → 合同归档库 → retrieve → 去年版本文本                       is_final=false
  步骤 3：风险条款列表(upstream) + 去年版本文本(upstream) → 无外部数据 → compare → 变化说明   is_final=true

## 二、步骤拆分规则

- 一步只做一种操作、访问一类数据；上一步的输出必须是下一步的输入，否则不拆。单一简单问题就是一步。
- 拆分依据是问题本身需要什么，不是本 Agent 会什么。本 Agent 做不了的步骤也必须列出并打分。
- **严格禁止曲解问题**：不得因为本 Agent 只能处理某类问题而把问题的主题替换成自己能处理的领域。
  例如：问题="公司辞退员工的补偿标准（劳动法）"，skill 覆盖"商品退款政策"时，步骤不能写成"查询退款政策"——这是曲解。
  又例：问题="工伤认定流程"，skill 覆盖"请假审批"时，步骤不能写成"查询请假流程"——这是曲解。
  步骤描述必须忠实于问题原文的主题领域，不能偷换概念。
- 每个输入项标注来源：query（问题文本或用户附带的文件、图片等附件已给出）/ upstream（需由上一步产出）/ missing（都没有）。
- 操作类别只能取：lookup（按键或条件定位记录）、filter（按条件筛选）、aggregate（统计、分组、排序）、
  retrieve（在文档库 / 知识库检索）、extract（从文本、图片、音频抽取信息）、summarize（归纳、摘要）、
  classify（分类、打标签、判定）、compare（对比）、translate（语言或格式转换）、generate（基于输入创作新内容）、
  modify（写入、删除、更新外部状态）。
- is_final：该步骤的产出是否就是用户要的最终结果（之一）。多个并列子问题各自是一步且各自 is_final=true。
- 问候、闲聊、无法识别意图的问题：拆成一步，操作类别按最接近的选，五个维度按实际情况打分（通常 D 与 R 为 0）。

## 三、五个维度（每个步骤各评一次）

四个比例维度必须先写清单（required / matched）再给 ratio；只给数字不给清单视为无效。
操作维度为三档。

### I 输入匹配
- 定义：该步骤所需输入，问题或上一步给了多少。
- 打分：列出所需输入项；逐项判断是否已提供且类型 / 模态可用；I = 可用项 / 所需项。
- 来源为 upstream 的输入按可用计，但必须写入 missing_requirements（若本 Agent 的上一步能产出则不必）。
- 输入模态与技能不匹配（技能只处理文本，输入是图片）记为不可用。
- 该步骤不需要输入时 required 为空、ratio = 1.0。
- **时间表达式规则**："本月"、"今天"、"本周"、"最近"、"上月"等时间表达式是自包含输入，直接记为已匹配。系统知道当前日期，执行时自然会按时间筛选，不需要调用方补精确起止日期。
- evidence_strength：
  · solid：依据来自问题原文中的具体值（如"张三"）、用户附件中的具体文件、或技能正文中明确声明的输入条件与支持的输入格式
  · speculative：仅能根据 Agent 描述或问题上下文推断输入是否可用

### D 信息覆盖
- 定义：该步骤要读写的信息需求项，技能的数据源 / 知识源里有多少。
- 打分：列出所需信息项；逐项在技能正文声明的覆盖范围中核对；D = 命中项 / 所需项。
- 结构化：信息项 = 实体与字段；核对对象 = 字段列表、数据格式说明。
- 非结构化：信息项 = 主题、知识点、文档集、时间版本、模态；核对对象 = 正文的覆盖范围声明（主题清单、来源、版本、模态）。
- 特例 1：正文明确写"不包含 X / 不支持 X / 不覆盖 X / 请使用其他技能查询 X"，X 对应项直接记未命中。
- 特例 2：该步骤不需要访问任何外部数据 / 知识（纯生成、纯转换、对上游产物的加工），required 为空、ratio = 1.0。
- 特例 3：信息项属于正文声明主题的子项（"年假"属于"请假制度"），可记命中，但整体证据等级不得高于 B。
- D 判断的是"技能是否拥有这类信息源"，不判断"具体答案是否一定在里面"。记录可能不存在属于数据实例问题，写入 risks，不影响分值。
- evidence_strength：
  · solid：依据来自技能正文中的明确字段列表、数据格式说明、覆盖主题清单及明确的排除项声明；如果正文明确写"不包含 X"，X 记未命中的依据也是 solid
  · speculative：正文仅有概括描述（如"可查询订单信息"、"公司内部文档问答"）而无具体字段/主题清单；或完全依赖 Agent 描述做推断

### O 操作能力
- 定义：该步骤要做的变换，技能能不能做。
- 打分只能取三档：
  1.0 = 技能正文明确描述该操作或给出等价命令 / 流程；
  0.7 = 正文未明确描述，但技能允许的工具或已声明的能力可以直接组合完成；
  0   = 不能做、明确不支持、或需要技能没有的工具类别（如只读技能遇到 modify）。
- 摘要、翻译、生成类操作的质量不确定性由 0.7 档承担，不进 R。

### R 结果匹配
- 定义：该步骤要产出的项 / 形态，技能的输出能满足多少。
- 打分：列出期望产出项（含形态要求：列表、数量、图表、摘要、译文、标签）；逐项判断技能能否输出该项及该形态；R = 可产出项 / 期望项。
- R 只判"能不能产出这个形态的结果"，不判质量。
- **R 部分匹配规则**：当该步骤不是最终步骤（is_final=false）或 Agent 只在链中贡献部分步骤时，期望产出项只需匹配"步骤描述中的核心产出类型"，不要额外要求最终结果的完整语义。示例：query="Rust 电子产品周边"，step1 描述为"筛选电子类商品列表"，则 R 只需判"电子商品列表"，不要求产出项必须包含"Rust 相关"。
- evidence_strength：
  · solid：依据来自技能正文中明确的输出字段、返回格式、输出形态说明
  · speculative：正文仅有概括描述（如"返回查询结果"）而无具体输出格式；或完全依赖 Agent 描述

### C 约束满足
- 定义：问题里显式或隐含的限定条件，技能能满足多少。
- 打分：列出该步骤的约束项：时效（实时 / 快照）、权限与副作用（只读 / 可写）、数据范围（区域 / 租户 / 时间跨度）、规模、精度、合规、语言、文档版本；逐项对照技能正文；C = 满足项 / 约束项。
- 没有约束时 required 为空、ratio = 1.0。
- 正文没有声明能满足的约束（如未声明支持英文、未声明实时同步）记为不满足，不得推断。
- **时间约束不拆分**：问题中有"本月/今天/最近/实时"等时间限定，且技能有时间字段+筛选工具（如 grep、awk sort）时，约束视为可满足（ratio=1.0），仅在 risks 里提示"非实时/快照数据可能不是最新状态"。只有当技能明确说"不包含时间字段"或"不支持按时间筛选"时才记未命中。
- evidence_strength：
  · solid：依据来自技能正文明确声明的数据同步周期、读写权限、数据范围、支持的语言/版本等
  · speculative：未找到对应声明的约束判断（如正文未声明支持英文，仅因工具可处理文本就推测"英文可处理"）
  · 正文没有声明能满足的约束记为不满足，evidence_strength 仍可标 solid（不满足的依据是"正文未声明"这一事实而非推测）

## 四、打分总则

- 技能正文没写的能力视为没有。禁止根据 Agent 名称、行业常识或"通常应该有"推断。
  非结构化技能尤其如此：正文只写"公司内部文档问答"而没有主题清单时，任何具体主题都不能记命中，证据等级记 C。
- 正文明确"不包含 / 不支持 / 不覆盖"的内容，对应项直接记未命中或 0。
- 各维度独立核对各自的清单，不允许为了让总分好看而调整某个维度。
- 每条 evidence 必须注明来源类别（"技能正文："或"问题原文："），内容可以是技能正文或问题中的关键信息（摘要、归纳均可），如："技能正文：用户数据中不包含订单信息"、"问题原文：张三"。
- **evidence_strength 强制要求**：每个 RatioCheck 必须标注 evidence_strength = solid 或 speculative。不能所有维度都标 solid 或都标 speculative，必须逐个维度独立判断。
- **多维度/多子任务查询规则**：当 query 明确列出多个维度或子任务（"从 A、B、C 三个维度排查"），必须为每个维度各建至少一个步骤。本 Agent 不覆盖的维度同样建步骤，但对应的 D=0/1 或 O=0。不允许只建自己能做的维度然后判 h=true。

## 五、证据等级（整体一个，不进乘法）

- A：各维度依据全部来自技能正文中的明确内容（字段列表、数据格式、命令示例；主题清单、来源、版本、处理流程、排除项）。
- B：主要来自技能正文，个别维度只能依赖技能短描述，或使用了 D 特例 3 的子项推断。
- C：主要依赖技能短描述或 Agent 描述，正文无对应内容。
- D：缺乏文本依据，含推测成分。

## 六、contribution、missing_requirements、risks、reason

- contribution：本 Agent 至少能独立完成一个有用步骤时按三要素书写，否则留空。
  三要素：输入（使用问题中的哪个已知值，或需补齐哪个缺失值）；输出（产出哪个具体项）；用途（对应哪个后续步骤的输入，或最终结果的哪一部分）。
  合格："输入 username=张三，输出 user_id，供步骤 2 查询订单使用"。
  不合格："可以提供相关用户信息"、"可以补充辅助数据"。
  程序侧判断 can_contribute 的条件：有贡献步骤（步骤能力分≥阈值且产出被需要） 且 contribution 非空。
- missing_requirements：本 Agent 无法自行提供、需由请求方或其他 Agent 补齐的输入或数据，注明所属步骤，如 "user_id（步骤 2）"。
- risks：不影响分值的提示，如结果唯一性（"张三"可能对应多人）、记录可能不存在。
- reason：固定结构。第一句写领域模型比对结论，格式："领域交集：[明确有/明确无/不确定] — 问题领域：[L1/L2/L3]；Agent 声明：引用正文原文（或"正文无对应声明"）"。然后逐步骤一行："步骤 N（一句话）：I=a/b D=c/d O=x R=e/f C=g/h，依据要点"；最后一句给整体结论（能独立完成 / 只能贡献步骤 N / 都不能）。

## 七、程序侧公式（供你理解结果含义，不需要你计算）

  步骤能力分 = weighted-arithmetic-mean(I,D,O,R,C)
    solid 维度权重=1.0，speculative 维度权重=0.1
    O 维度始终 solid（三档评分有明确的声明或无声明依据）
  can_handle = 各步骤能力分的算术平均达到阈值，且没有本 Agent 无法自行产出的 upstream / missing 输入
  can_contribute = can_handle，或存在某一步能力分达到阈值且其产出被需要
  confidence = 能独立完成时取 step_score 均值；只能贡献时取贡献步骤能力分最大值；都不能时为 0

## 八、完整示例

本 Agent 技能正文关键内容：字段 用户ID|用户名|电话|邮箱；"按用户名查询：grep 张三 data/users.txt"；"用户数据中不包含订单信息，如需获取用户的订单数据，请使用 order_query 技能"。
用户问题："张三买了哪些东西"

步骤 1（用户名 → user_id，lookup，is_final=false）
  I: required=[用户名] matched=[用户名] ratio=1.0 evidence_strength=solid  依据：问题原文"张三"
  D: required=[用户名, 用户ID] matched=[用户名, 用户ID] ratio=1.0 evidence_strength=solid  依据：技能正文字段列表
  O: 1.0                                                                    依据：技能正文 grep 示例
  R: required=[user_id] matched=[user_id] ratio=1.0 evidence_strength=solid
  C: required=[] matched=[] ratio=1.0 evidence_strength=solid
步骤 2（user_id → 商品列表，lookup，is_final=true；inputs: user_id source=upstream）
  I: required=[user_id] matched=[user_id] ratio=1.0 evidence_strength=solid  上游产出，由本 Agent 步骤 1 提供
  D: required=[订单, 商品] matched=[] ratio=0.0 evidence_strength=solid      依据：技能正文"用户数据中不包含订单信息"
  O: 1.0
  R: required=[商品列表] matched=[] ratio=0.0 evidence_strength=solid
  C: required=[] matched=[] ratio=1.0 evidence_strength=solid
evidence_grade: A
contribution: "输入 username=张三，输出 user_id，供步骤 2 查询订单使用"
missing_requirements: ["订单 / 购买记录数据（步骤 2）"]
risks: ["用户名 张三 可能对应多个用户"]
reason: "领域交集：明确有 — 问题领域：L1 电商业务 / L2 用户 / L3 用户名；Agent 声明：技能正文『字段 用户ID|用户名|电话|邮箱』『按用户名查询：grep 张三 data/users.txt』。步骤 1（用户名→user_id）：I=1/1 D=2/2 O=1.0 R=1/1 C=1.0，字段列表与 grep 示例明确。步骤 2（user_id→商品列表）：I=1/1 D=0/2 O=1.0 R=0/1 C=1.0，正文明确不包含订单信息。不能独立完成；可贡献步骤 1。"

---
本 Agent 信息：
- name: {agent_name}
- description: {agent_description}
- skill inventory（技能名 + 完整正文；打分的主要依据）:
{agent_skills}

历史：
{history}

用户问题：
{query}

领域交集前置检查结论：
{domain_info}

---
输出要求：
- 只输出一个纯 JSON 对象，**不要使用 ```json 代码块包裹**，直接输出 JSON 文本。
- 每个 RatioCheck（input_match / data_coverage / result_match / constraint_satisfaction）必须同时给出 required（字符串数组）、matched（字符串数组）、ratio（数字，0~1）、evidence_strength（字符串，solid 或 speculative）。
- operation_capability 只能是 1.0、0.7 或 0。
- 不要输出 can_handle、can_contribute、confidence、domain_verdict。

严格按照以下 JSON schema 输出（示例，实际内容按评估结果填写）：

{{
  "steps": [
    {{
      "step_id": 1,
      "description": "从慢查询日志中检索并排序慢查询记录",
      "operation": "lookup",
      "is_final": true,
      "inputs": [
        {{"name": "时间范围", "source": "query"}}
      ],
      "outputs": ["慢查询TOP列表"],
      "constraints": ["只读"],
      "input_match": {{"required": ["时间范围"], "matched": ["时间范围"], "ratio": 1.0}},
      "data_coverage": {{"required": ["慢查询日志数据"], "matched": ["慢查询日志数据"], "ratio": 1.0}},
      "operation_capability": 1.0,
      "result_match": {{"required": ["慢查询列表"], "matched": ["慢查询列表"], "ratio": 1.0}},
      "constraint_satisfaction": {{"required": ["只读"], "matched": ["只读"], "ratio": 1.0}},
      "evidence": ["技能正文：grep 'slow_query' data/mysql-slow.log"]
    }}
  ],
  "evidence_grade": "A",
  "contribution": "输入时间范围，输出慢查询TOP列表",
  "missing_requirements": [],
  "risks": [],
  "reason": "步骤1（慢查询日志→慢查询列表）：I=1/1 D=1/1 O=1.0 R=1/1 C=1/1，依据技能正文grep示例。可独立完成。"
}}

注意要点：
- steps 是数组，每项中的 inputs 是对象数组（每个对象含 name 和 source），outputs 和 constraints 是字符串数组。
- input_match、data_coverage、result_match、constraint_satisfaction 是对象（含 required/matched/ratio），不是数组。
- operation_capability 是数字（1.0 / 0.7 / 0），必须是数字类型不是字符串。
- evidence 是字符串数组。
- 每个步骤的 step_id 从 1 开始连续递增。
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
        # make_plan 与 capability_check 已改用纯文本 JSON 字符串输出
        # （self.llm.ainvoke，不经 bind_tools），此 LLM 实例仅用于
        # _ainvoke_plain_plan 路径，不再参与 invoke_llm_with_tool。
        self.make_plan_max_attempts = int(os.getenv("MAKE_PLAN_MAX_ATTEMPTS", "3"))
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.agent_id = agent_id

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
        run_id = str(self.metadata.get("run_id", "") or "")
        propagated = parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        turns = _normalize_history_turns(propagated.get("turns"))
        if turns:
            _log_history_turns(turns, source="propagated", run_id=run_id)
            return history_text_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
            user_id=self.metadata.get("user_id", ""),
            run_id=run_id,
            limit=get_conversation_history_limit(),
        )
        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        payload = history_payload_from_search_items(search_items, source="skill_agent_planner_fallback")
        _log_history_turns(payload.get("turns", []), source="data-services API", run_id=run_id)
        return history_text_from_payload(payload)

    @staticmethod
    def _llm_answer_text(answer) -> str:
        """Normalize LangChain AIMessage content (str or multimodal list) to text."""
        raw = getattr(answer, "content", None)
        if raw is None:
            return str(answer or "")
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            parts: List[str] = []
            for item in raw:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                else:
                    text = getattr(item, "text", None)
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return str(raw)

    def format_llm_output(self, answer) -> Optional[dict]:
        """Parse LLM plain-text output into a dict (delegates to module-level helper)."""
        return _parse_json_output(answer)

    @staticmethod
    def _plan_information(
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
    ) -> str:
        if not (replan_context or replan_guidance):
            return ""
        info_parts: List[str] = []
        if replan_context:
            info_parts.append(
                "REPLAN_CONTEXT(JSON):\n" + json.dumps(replan_context, ensure_ascii=False)
            )
        if replan_guidance:
            info_parts.append(f"REPLAN_GUIDANCE:\n{replan_guidance}")
        return "\n\n".join(info_parts)

    @staticmethod
    def _valid_plan_agent_names(agent_cards) -> set[str]:
        names = {
            str(getattr(c, "name", "") or "").strip()
            for c in (agent_cards or [])
        }
        names.discard("")
        names.add("NONE")
        return names

    @staticmethod
    def _none_task_list(query: Any, reason: str) -> TaskList:
        return TaskList(
            thought_process=reason,
            original_query=str(query),
            tasks=[
                PlannerTask(
                    id=1,
                    description=NONE_TASK_DESCRIPTION,
                    agent="NONE",
                    depends_on=[],
                )
            ],
        )

    @staticmethod
    def _validate_chain_task_consistency(
        args: dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        """Validate that capability_chain ↔ tasks are consistent.

        Returns (error_msg, thought_process_validated).
        """
        chain_steps: list[dict] = args.get("capability_chain") or []
        tasks: list[dict] = args.get("tasks") or []

        if not chain_steps:
            return None, None  # No chain present — skip validation (legacy mode)

        # --- Validate chain steps themselves ---
        for i, s in enumerate(chain_steps):
            sid = s.get("step_id")
            if sid is None:
                return f"capability_chain[{i}].step_id 缺失", None
            if not isinstance(sid, int) or sid < 1:
                return f"capability_chain[{i}].step_id 必须是正整数，实际: {sid}", None
            if not str(s.get("description") or "").strip():
                return f"capability_chain[{i}].description 为空", None
            if not str(s.get("matched_agent") or "").strip():
                return f"capability_chain[{i}].matched_agent 为空（链步骤不允许没有 agent 标记）", None

        # --- Build lookup maps ---
        chain_by_id: dict[int, dict] = {}
        task_by_id: dict[int, dict] = {}
        for s in chain_steps:
            chain_by_id[s["step_id"]] = s
        for t in tasks:
            tid = t.get("id")
            if tid is not None:
                task_by_id[tid] = t

        # --- Cross-check: chain ↔ tasks ---
        # Every chain step must have a corresponding task
        for sid, s in chain_by_id.items():
            if sid not in task_by_id:
                return (
                    f"capability_chain 中步骤 {sid} ({s.get('description','')[:60]}) "
                    f"在 tasks 中没有对应的 task（期望 task.id={sid}）",
                    None,
                )
            chain_agent = str(s.get("matched_agent", "")).strip()
            task_agent = str(task_by_id[sid].get("agent", "")).strip()
            if chain_agent.upper() != task_agent.upper():
                return (
                    f"capability_chain 步骤 {sid} 的 matched_agent='{chain_agent}' "
                    f"与 task[{sid}] 的 agent='{task_agent}' 不一致",
                    None,
                )

        # Check if extra tasks not in chain
        for tid in task_by_id:
            if tid not in chain_by_id:
                return (
                    f"task[{tid}] ('{task_by_id[tid].get('description','')[:60]}') "
                    f"在 capability_chain 中没有对应步骤",
                    None,
                )

        # --- Cross-check depends_on ---
        for _, s in chain_by_id.items():
            if str(s.get("input_source", "")).lower() == "upstream":
                sid = s["step_id"]
                task_deps = task_by_id.get(sid, {}).get("depends_on") or []
                if not task_deps:
                    return (
                        f"capability_chain 步骤 {sid} input_source=upstream，"
                        f"但 task[{sid}].depends_on 为空（必须包含上游步骤 id）",
                        None,
                    )

        # All good — return the valid thought_process
        tp = str(args.get("thought_process") or "").strip()
        return None, tp

    def _hydrate_chain_plan(
        self,
        args: dict[str, Any],
        query: Any,
        valid_agent_names: set[str],
    ) -> tuple[Optional[TaskList], Optional[str]]:
        """Parse chain-driven planner output into TaskList.

        Steps:
        1. Validate capability_chain ↔ tasks consistency
        2. Run standard field completeness checks
        3. Build TaskList
        """
        # --- Step 1: chain-task consistency ---
        err, thought_process = self._validate_chain_task_consistency(args)
        if err:
            return None, err

        # --- Step 2: standard field checks ---
        omitted: list[str] = []
        if not (thought_process or "").strip():
            omitted.append("thought_process")
        if not str(args.get("original_query") or query or "").strip():
            omitted.append("original_query")

        raw_tasks: list[dict] = args.get("tasks") or []
        if not raw_tasks:
            omitted.append("tasks(必须是非空数组)")
        else:
            for idx, rt in enumerate(raw_tasks):
                if not isinstance(rt, dict):
                    omitted.append(f"tasks[{idx}](必须是对象)")
                    continue
                if rt.get("id") is None:
                    omitted.append(f"tasks[{idx}].id")
                if not str(rt.get("description") or "").strip():
                    omitted.append(f"tasks[{idx}].description")
                if not str(rt.get("agent") or "").strip():
                    omitted.append(f"tasks[{idx}].agent")
                if "depends_on" not in rt or rt.get("depends_on") is None:
                    omitted.append(f"tasks[{idx}].depends_on")

        if omitted:
            return None, (
                f"缺少必填字段: {omitted}。"
                f"`thought_process`、`original_query`、`capability_chain`、`tasks` 以及每个 task 的 "
                f"`id`、`description`、`agent`、`depends_on` 全部为必填，不允许省略或留空。"
                f"特别注意 `depends_on`：即使该任务没有上游依赖，也必须显式写成 `depends_on: []`；"
                f"若该任务需要上游任务的产出，则必须写入对应的上游 task id。"
            )

        # --- Step 3: build TaskList ---
        try:
            tasks = TaskList(
                thought_process=thought_process or str(args.get("thought_process")),
                original_query=_non_empty_str(query),
                tasks=raw_tasks,
            )
        except Exception as exc:
            return None, f"规划结果解析失败: {exc}."

        if not tasks.tasks:
            return None, (
                f"`tasks` 列表为空。如果确实没有合适的智能体，请使用 agent='NONE' "
                f"和 description='{NONE_TASK_DESCRIPTION}'。"
            )

        unknown = [
            (t.id, (t.agent or "").strip())
            for t in tasks.tasks
            if (t.agent or "").strip() not in valid_agent_names
            and (t.agent or "").strip().upper() != "NONE"
        ]
        if unknown:
            return None, (
                f"agent 名称不存在于可用智能体列表中: "
                f"{[a for _, a in unknown]}。"
                f"`agent` 字段必须与可用智能体的名称完全一致，可选值为: "
                f"{sorted(n for n in valid_agent_names if n != 'NONE')}。"
                f"如果确实没有合适的智能体，请使用 agent='NONE' 和 "
                f"description='{NONE_TASK_DESCRIPTION}'。"
            )

        return tasks, None

    def _hydrate_task_list(
        self,
        args: Any,
        query: Any,
        valid_agent_names: set[str],
    ) -> tuple[Optional[TaskList], Optional[str]]:
        """Parse planner dict into TaskList. Returns (plan, error_nudge)."""
        if not isinstance(args, dict):
            return None, "输出无法解析为包含规划结果的 JSON 对象。"

        omitted: List[str] = []
        if not str(args.get("thought_process") or "").strip():
            omitted.append("thought_process")
        if not str(args.get("original_query") or query or "").strip():
            omitted.append("original_query")
        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list):
            omitted.append("tasks(必须是数组)")
            raw_tasks = []
        else:
            for idx, rt in enumerate(raw_tasks):
                if not isinstance(rt, dict):
                    omitted.append(f"tasks[{idx}](必须是对象)")
                    continue
                if rt.get("id") is None or (
                    isinstance(rt.get("id"), str) and not str(rt.get("id")).strip()
                ):
                    omitted.append(f"tasks[{idx}].id")
                if not str(rt.get("description") or "").strip():
                    omitted.append(f"tasks[{idx}].description")
                if not str(rt.get("agent") or "").strip():
                    omitted.append(f"tasks[{idx}].agent")
                # depends_on 允许 []，只禁止缺省 / null
                if "depends_on" not in rt or rt.get("depends_on") is None:
                    omitted.append(f"tasks[{idx}].depends_on")
        if omitted:
            return None, (
                f"缺少必填字段: {omitted}。"
                f"`thought_process`、`original_query`、`tasks` 以及每个 task 的 "
                f"`id`、`description`、`agent`、`depends_on` 全部为必填，不允许省略或留空。"
                f"特别注意 `depends_on`：即使该任务没有上游依赖，也必须显式写成 `depends_on: []`；"
                f"若该任务需要上游任务的产出，则必须写入对应的上游 task id。"
            )

        try:
            tasks = TaskList(
                thought_process=str(args.get("thought_process")),
                original_query=_non_empty_str(query),
                tasks=raw_tasks,
            )
        except Exception as exc:
            return None, f"规划结果解析失败: {exc}。"

        if not tasks.tasks:
            return None, (
                f"`tasks` 列表为空。如果确实没有合适的智能体，请使用 agent='NONE' "
                f"和 description='{NONE_TASK_DESCRIPTION}'。"
            )

        unknown = [
            (t.id, (t.agent or "").strip())
            for t in tasks.tasks
            if (t.agent or "").strip() not in valid_agent_names
            and (t.agent or "").strip().upper() != "NONE"
        ]
        if unknown:
            return None, (
                f"agent 名称不存在于可用智能体列表中: "
                f"{[a for _, a in unknown]}。"
                f"`agent` 字段必须与可用智能体的名称完全一致，可选值为: "
                f"{sorted(n for n in valid_agent_names if n != 'NONE')}。"
                f"如果确实没有合适的智能体，请使用 agent='NONE' 和 "
                f"description='{NONE_TASK_DESCRIPTION}'。"
            )
        return tasks, None

    def _format_plan_messages(
        self,
        *,
        system_template: str,
        query: Any,
        agent_cards,
        group_memory: str,
        information: str,
        history: Any,
    ) -> list:
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["history", "agents", "information", "group_memory"],
        )
        human_prompt = HumanMessagePromptTemplate.from_template("{query}")
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
        return chat_prompt.format_messages(
            query=query,
            agents=self.generate_system_prompt_agents(agent_cards),
            information=information,
            group_memory=group_memory,
            history=history,
        )

    async def _ainvoke_plain_plan(
        self,
        messages: list,
        *,
        span_name: str,
        query: Any,
        agent_name: str,
    ):
        """Plain-text LLM invoke (no bind_tools) for make_plan_jsonstring."""
        _t0 = _time.monotonic()
        answer = None
        preview = ""
        try:
            from langfuse.langchain import CallbackHandler as _LangfuseCb
            from langfuse import get_client as _get_langfuse_client

            _handler = _LangfuseCb()
            _langfuse_client = _get_langfuse_client()
            user_id = self.metadata.get("user_id", "")
            run_id = self.metadata.get("run_id", "")
            trace_id = self.metadata.get("trace_id", "")
            _span_name = f"{span_name} [{agent_name}]" if agent_name else span_name
            with _langfuse_client.start_as_current_span(
                name=_span_name,
                trace_context={"trace_id": trace_id} if trace_id else {},
                input={"query": str(query)[:500]},
            ) as span:
                if user_id or run_id:
                    span.update_trace(
                        user_id=user_id or None,
                        session_id=run_id or None,
                    )
                answer = await self.llm.ainvoke(
                    messages,
                    config={"callbacks": [_handler]},
                )
                preview = self._llm_answer_text(answer)[:2000]
                span.update(output={"answer": preview})
            await safe_langfuse_flush(_langfuse_client)
        except Exception as exc:
            if answer is None:
                logger.warning(
                    "make_plan_jsonstring tracing/invoke wrapper failed (%s: %s); "
                    "retrying plain ainvoke",
                    type(exc).__name__,
                    exc,
                )
                answer = await self.llm.ainvoke(messages)
            preview = self._llm_answer_text(answer)[:2000]
        elapsed_ms = round((_time.monotonic() - _t0) * 1000)
        logger.info(
            " === PlannerAgent._ainvoke_plain_plan (%s) elapsed_ms=%s preview=%s",
            span_name,
            elapsed_ms,
            preview[:300],
        )
        return answer

    async def make_plan(
        self,
        query,
        agent_cards,
        group_memory: str = "",
        replan_context: Optional[Dict[str, Any]] = None,
        replan_guidance: str = "",
        plan_stage: str = "pre_exec",
    ) -> TaskList:
        """planner: LLM emits a JSON object as text (no nested tool schema).

        Feature flag: set USE_CHAIN_PLANNING=true to enable chain-driven planning
        (operation chain decomposition → agent matching → task generation).
        """
        use_chain = os.getenv("USE_CHAIN_PLANNING", "true").strip().lower() in ("true", "1", "yes")
        plan_mode = "chain" if use_chain else "legacy"

        system_template = (
            PLANNER_CHAIN_INSTRUCTIONS_ZH
            if use_chain
            else PLANNER_COT_INSTRUCTIONS_ZH_HISTORY_JSONSTRING
        )
        information = self._plan_information(replan_context, replan_guidance)
        history = await self.get_history()
        messages = self._format_plan_messages(
            system_template=system_template,
            query=query,
            agent_cards=agent_cards,
            group_memory=group_memory,
            information=information,
            history=history,
        )
        valid_agent_names = self._valid_plan_agent_names(agent_cards)
        agent_name = self.agent_id or self.agent_name or "PlannerAgent"
        span_prefix = (
            "skill-agent-make_plan_jsonstring-mid-exec"
            if plan_stage == "mid_exec"
            else "skill-agent-make_plan_jsonstring"
        )
        span_prefix = f"{span_prefix}-{plan_mode}"
        max_attempts = self.make_plan_max_attempts
        nudge: Optional[HumanMessage] = None
        tasks: Optional[TaskList] = None

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "make_plan_jsonstring llm_invoke stage=%s mode=%s attempt=%d/%d",
                plan_stage, plan_mode, attempt, max_attempts,
            )
            attempt_messages = (
                messages + [AIMessage(content=""), nudge] if nudge is not None else messages
            )
            try:
                answer = await self._ainvoke_plain_plan(
                    attempt_messages,
                    span_name=f"{span_prefix}-attempt-{attempt}",
                    query=query,
                    agent_name=agent_name,
                )
            except Exception as exc:
                logger.warning(
                    "make_plan_jsonstring attempt %s: LLM invoke failed: %s: %s",
                    attempt, type(exc).__name__, exc,
                )
                nudge = HumanMessage(
                    content=(
                        "上一次调用失败。请重新输出一个完整的 JSON 对象，"
                        "包含 thought_process、original_query、tasks；"
                        "每个 task 必须有 id、description、agent、depends_on。"
                    )
                )
                continue

            args = self.format_llm_output(answer)

            if use_chain:
                tasks, err = self._hydrate_chain_plan(args, query, valid_agent_names)
            else:
                tasks, err = self._hydrate_task_list(args, query, valid_agent_names)

            if tasks is not None:
                logger.info(
                    "make_plan_jsonstring SELECTED mode=%s attempt=%d tasks_count=%d",
                    plan_mode, attempt, len(tasks.tasks),
                )
                break
            preview = self._llm_answer_text(answer)[:400]
            logger.warning(
                "make_plan_jsonstring attempt %s: invalid JSON plan, nudging: %s preview=%s",
                attempt, err, preview,
            )
            nudge = HumanMessage(
                content=(
                    (err or "输出无法解析为合法规划 JSON。")
                    + " 请只输出一个 JSON 对象，字段为 thought_process、original_query、tasks；"
                    "每个 task 必须包含 id、description、agent、depends_on；"
                    "无依赖时 depends_on 必须写成 []。"
                )
            )
            tasks = None

        if tasks is None:
            logger.warning(
                "make_plan_jsonstring EXIT no_valid_selection mode=%s after %s attempts.",
                plan_mode, max_attempts,
            )
            tasks = self._none_task_list(
                query,
                f"Planner failed to produce a valid plan after "
                f"{self.make_plan_max_attempts} tool-call attempts and "
                f"{max_attempts} jsonstring attempts.",
            )

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
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
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
        self.progress_callback = progress_callback

    def _log_propagated_history(self) -> None:
        payload = _parse_propagated_history(self.metadata.get(PROPAGATED_HISTORY_KEY))
        turns = _normalize_history_turns(payload.get("turns"))
        if not turns:
            return
        body_parts: list[str] = []
        for i, item in enumerate(turns, start=1):
            prefix = "用户" if item["role"] == "user" else "助手"
            content_display = item["content"][:600]
            if len(item["content"]) > 600:
                content_display += "...（截断）"
            body_parts.append(f"── 第 {i} 轮 ({prefix}) ──")
            body_parts.append(content_display)
            body_parts.append("")
        _log_boxed_document(
            "[GetHistory] propagated",
            meta_lines=[f"turns={len(turns)}"],
            body_label="history",
            body="\n".join(body_parts).rstrip(),
        )

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
            "skill_started",
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
                progress_callback=self.emit_progress,
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
            "skill_finished",
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
# Summary prompt builders
# Analogous to ``_build_turn_context_md``: one document, Execution Flow as
# the single source of truth.  Do not dump ``upstream_context`` as JSON and
# do not repeat own/delegate results when EF is present.
# ---------------------------------------------------------------------------

SUMMARIZE_CORE_PRINCIPLES = (
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

SUMMARIZE_EVAL_SYSTEM_PROMPT = (
    SUMMARIZE_CORE_PRINCIPLES
    + "\n"
    "**你需要做的事情**\n"
    "1. 撰写回答正文（填入 answer 字段）。\n"
    "2. 判断当前信息是否足以完整回答用户问题（填入 satisfactory 字段）：\n"
    "   - 如果足以回答 → satisfactory=true，missing_info 设为空字符串，gap_obtainable 设为 true。\n"
    "   - 如果不足以回答 → satisfactory=false，missing_info 中说明缺少什么信息，"
    "需要在下轮执行中补充获取（例如：'缺少模块 X 的运行日志'、'数据库 Y 的配置信息未返回'）。\n"
    "3. 【当 satisfactory=false 时必须做】判断缺失信息是否「可通过再执行获得」（填入 gap_obtainable 字段）：\n"
    "   - gap_obtainable=true：该缺口可以靠继续执行拿到——例如数据在某个其他 agent 手里、"
    "缺少关联键但可先查询得到、需要补充某个可查的数据源。\n"
    "   - gap_obtainable=false：该缺口超出当前能力边界，再执行也拿不到——例如结果已明确声明不具备该能力"
    "且协作池中没有 agent 声明可提供该能力；或该数据需要实时/外部来源而不可能取得。\n"
    "   自检方法：「如果让执行方再做一轮，它真的能拿到这个信息吗？」\n"
    "   → 能 → true；→ 不能（明知再跑也没用）→ false。\n"
    "   ⚠ 重要：结果里仅凭一句「本 skill 不具备 X 能力」不足以判 false；"
    "若其他 agent 有可能提供 X，仍应判 true。只有确认「无人能提供」时才判 false。\n"
    "   ⚠ 若一轮重试已完成且有充分证据表明该缺口不可获得，应判 false，避免无意义的反复重试。\n"
    "4. 简要说明本次评估的决策理由（填入 rationale 字段，一句话即可）。\n\n"
    "**判断 satisfactory 的核心原则**\n"
    "你需要严格区分两类信息：\n"
    "- 实质性结果：用户请求的数据、分析结论、操作产出等。\n"
    "- 执行过程描述：执行过程中发生了什么，以及为什么没有拿到实质性结果。\n\n"
    "判断规则：\n"
    "- 只有当用户请求的实质性结果已完整获取时，satisfactory 才为 true。\n"
    "- 如果实质性结果缺失，即使执行过程描述得很详细，satisfactory 也必须为 false。\n"
    "- 执行过程描述（包括失败原因、错误说明、状态报告等）不能替代实质性结果。\n\n"
    "**特别注意：以下情况必须判定 satisfactory=false**\n"
    "1. 下游结果中出现「没有找到」「未查询到」「不存在」「无法确定」「请提供」「您可以」「建议您」等表示未完成或需要用户补充输入的表述，且原始问题并非确认某事物是否存在。\n"
    "2. 下游仅返回全量兜底数据，而没有直接回答用户的具体问题（例如用户问“王五买了哪些商品”，下游却列出所有用户的购买记录）。\n"
    "3. 下游结果以反问用户结束（如“请问您知道……吗？”），说明信息不足以独立完成回答。\n"
    "4. 下游结果中明确说明缺少某些关键信息，导致无法完成最终答案。\n\n"
    "**Few-shot 示例**\n"
    "示例1：\n"
    "用户问题：王五买了哪些商品，要显示商品名字\n"
    "下游结果：订单数据中没有找到用户名为“王五”的记录，数据中只有用户ID，没有姓名。以下是所有用户的购买概览：U001买了A、B，U002买了C……请问您知道王五对应的用户ID吗？\n"
    "正确输出：\n"
    "answer: 当前订单数据中没有用户名为“王五”的记录，且数据中只有用户ID，无法确定王五对应的用户，因此无法回答王五购买了哪些商品。\n"
    "satisfactory: false\n"
    "missing_info: 缺少用户名“王五”到用户ID的映射信息，需要先通过用户查询能力获取王五对应的用户ID，再查询该用户的订单商品。\n"
    "rationale: 下游未提供王五的实质购买记录，仅给出全量数据并反问用户，实质结果缺失。\n\n"
    "示例2：\n"
    "用户问题：查询2024年1月的销售总额\n"
    "下游结果：已查询数据库，2024年1月销售总额为123456元。\n"
    "正确输出：\n"
    "answer: 2024年1月的销售总额为123456元。\n"
    "satisfactory: true\n"
    "missing_info: \"\"\n"
    "rationale: 已获得明确的销售总额数据，足以回答。\n\n"
    "**重要**：你必须调用 evaluate_summary 工具来输出结果，不要直接输出文本。"
)

AGENT_SUMMARIZE_SYSTEM_PROMPT = SUMMARIZE_CORE_PRINCIPLES


def _format_own_and_delegate_text(
    task_results: dict[int, str] | None,
    delegate_results: dict[str, str] | None,
) -> tuple[str, str]:
    """Format own / delegate result slices (fallback and error messages only)."""
    own_text = "\n".join(
        f"[Task#{tid}] {res}" for tid, res in (task_results or {}).items() if res
    )
    del_text = "\n".join(
        f"[{name}]: {res or '[EMPTY — 该 SG 未返回任何数据]'}"
        for name, res in (delegate_results or {}).items()
    )
    return own_text, del_text


def _render_summary_execution_context(
    original_query: str,
    *,
    execution_flow_tasks: list | None = None,
    task_results: dict[int, str] | None = None,
    delegate_results: dict[str, str] | None = None,
    current_agent: str = "",
    agent_role: str = "initiator",
) -> str:
    """Build the factual context block shared by both summary prompts.

    Prefers Execution Flow markdown (same source of truth as
    ``_build_turn_context_md``).  Falls back to own/delegate slices only
    when no EF records are available — never dumps ``upstream_context`` JSON.
    """
    sections: list[str] = [f"原始问题：{original_query}"]

    ef_md = ""
    if execution_flow_tasks:
        ef_md = render_execution_flow_md(
            execution_flow_tasks,
            agent=current_agent,
            role=agent_role,
            current_agent=current_agent,
            show_children=False,
        )
    if ef_md and ef_md.strip():
        sections.append(ef_md)
    else:
        own_text, del_text = _format_own_and_delegate_text(
            task_results, delegate_results,
        )
        if own_text:
            sections.append(f"## 本层执行结果\n{own_text}")
        if del_text:
            sections.append(f"## 下游返回结果\n{del_text}")
        if not own_text and not del_text:
            sections.append("（暂无执行结果）")

    return "\n\n".join(sections)


_SUMMARY_PROMPT_RULE_WIDTH = 72


def _summary_prompt_rule(corner: str, label: str = "") -> str:
    """Single-line box rule (─), never double-line (═)."""
    fill = _SUMMARY_PROMPT_RULE_WIDTH - len(corner) - len(label)
    if fill < 0:
        fill = 0
    return f"{corner}{label}{'─' * fill}"


def _turn_round_label(*, turn: int | None = None, mid_exec_round: int | None = None) -> str:
    """Title suffix like `` ─ 第1轮 ─ Round 1``."""
    parts: list[str] = []
    if turn is not None:
        parts.append(f"第{turn}轮")
    if mid_exec_round is not None:
        parts.append(f"Round {mid_exec_round}")
    return (" ─ " + " ─ ".join(parts)) if parts else ""


def _turn_round_meta(*, turn: int | None = None, mid_exec_round: int | None = None) -> str:
    """Meta prefix like ``turn=1    round=1``."""
    parts: list[str] = []
    if turn is not None:
        parts.append(f"turn={turn}")
    if mid_exec_round is not None:
        parts.append(f"round={mid_exec_round}")
    return "    ".join(parts)


def _log_boxed_document(
    title: str,
    *,
    meta_lines: list[str],
    body_label: str,
    body: str,
    log: logging.Logger | None = None,
    level: str = "info",
) -> None:
    """Print a document in a readable single-line box (┌─ / ├─ / └─)."""
    header = _summary_prompt_rule("┌", f"─ {title} ")
    mid = _summary_prompt_rule("├", f"─ {body_label} ")
    footer = _summary_prompt_rule("└")
    meta = "\n".join(f"│ {line}" for line in meta_lines)
    text = (body or "").rstrip() or "(空)"
    body_block = "\n".join(
        f"│ {line}" if line else "│" for line in text.splitlines()
    )
    target = log or logger
    log_fn = getattr(target, level, target.info)
    log_fn(
        "\n%s\n%s\n%s\n%s\n%s",
        header,
        meta,
        mid,
        body_block,
        footer,
    )


def _log_built_summary_prompt(
    kind: str,
    *,
    system_prompt: str,
    human_prompt: str,
    current_agent: str = "",
    agent_role: str = "",
    turn: int | None = None,
) -> None:
    """Print the constructed summary prompt in a readable single-line box."""
    title = f"[SummaryPrompt] {kind}"
    if turn is not None:
        title = f"{title} ─ 第{turn}轮"
    meta_head = f"agent={current_agent or '-'}    role={agent_role or '-'}"
    if turn is not None:
        meta_head = f"{meta_head}    turn={turn}"
    _log_boxed_document(
        title,
        meta_lines=[
            meta_head,
            f"system={len(system_prompt or '')} chars    "
            f"human={len(human_prompt or '')} chars",
        ],
        body_label="human prompt",
        body=human_prompt,
    )


def _build_summarize_eval_prompt(
    original_query: str,
    *,
    execution_flow_tasks: list | None = None,
    task_results: dict[int, str] | None = None,
    delegate_results: dict[str, str] | None = None,
    current_agent: str = "",
    agent_role: str = "initiator",
    turn: int = 1,
) -> tuple[str, str]:
    """Build (system, human) prompts for ``_summarize_with_evaluation``.

    Mirrors ``_build_turn_context_md``: one Execution Flow document plus the
    original question.  The human message ends by requiring ``evaluate_summary``.
    """
    context = _render_summary_execution_context(
        original_query,
        execution_flow_tasks=execution_flow_tasks,
        task_results=task_results,
        delegate_results=delegate_results,
        current_agent=current_agent,
        agent_role=agent_role,
    )
    human_prompt = context + "\n\n请调用 evaluate_summary 工具输出结果。"
    _log_built_summary_prompt(
        "skill-summarize-eval",
        system_prompt=SUMMARIZE_EVAL_SYSTEM_PROMPT,
        human_prompt=human_prompt,
        current_agent=current_agent,
        agent_role=agent_role,
        turn=turn,
    )
    return SUMMARIZE_EVAL_SYSTEM_PROMPT, human_prompt


def _build_agent_summarize_prompt(
    original_query: str,
    *,
    execution_flow_tasks: list | None = None,
    task_results: dict[int, str] | None = None,
    delegate_results: dict[str, str] | None = None,
    current_agent: str = "",
    agent_role: str = "initiator",
    custom_system_prompt: str | None = None,
) -> tuple[str, str]:
    """Build (system, human) prompts for ``_summarize``.

    Same factual context as ``_build_summarize_eval_prompt``; the human
    message asks for a direct answer instead of a tool call.

    When *custom_system_prompt* is provided, it replaces the default
    ``AGENT_SUMMARIZE_SYSTEM_PROMPT``.
    """
    context = _render_summary_execution_context(
        original_query,
        execution_flow_tasks=execution_flow_tasks,
        task_results=task_results,
        delegate_results=delegate_results,
        current_agent=current_agent,
        agent_role=agent_role,
    )
    human_prompt = context + "\n\n请直接输出答案："
    system_prompt = custom_system_prompt or AGENT_SUMMARIZE_SYSTEM_PROMPT
    _log_built_summary_prompt(
        "skill-agent-summarize",
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        current_agent=current_agent,
        agent_role=agent_role,
    )
    return system_prompt, human_prompt


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

        # Summarize configuration (from env vars, see _summarize decision tree)
        self.summarize_enabled: bool = (
            os.getenv("SUMMARIZE_ENABLED", "true").strip().lower()
            in ("true", "1", "yes")
        )
        self.summarize_prompt: str | None = (
            os.getenv("SUMMARIZE_CUSTOM_PROMPT", "").strip() or None
        )
        logger.info(
            "[Summarize] config loaded | enabled=%s custom_prompt_chars=%s",
            self.summarize_enabled,
            len(self.summarize_prompt) if self.summarize_prompt else 0,
        )

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
    # DAG (Directed Acyclic Graph) enforcement for delegation chains
    # ------------------------------------------------------------------

    def _dag_enforcement_enabled(self) -> bool:
        """Whether to enforce DAG constraint on delegation chains.

        Controlled by env ``CROSS_SG_ENFORCE_DAG`` (default ``"false"``).
        When enabled, any agent that already appears in the delegation chain
        is excluded from planner pools, mid-exec candidate cards, detection
        LLM prompts, and dispatch target lists. Default off so A→B→A
        callback is allowed.
        """
        return os.getenv("CROSS_SG_ENFORCE_DAG", "false").strip().lower() in ("true", "1", "yes")

    @staticmethod
    def _format_dag_chain(chain: list[str], *, highlight: str = "") -> str:
        """Format a delegation chain as a visual DAG edge trail.

        Returns a string like ``agent1 ──▶ agent2 ──▶ agent3``.
        If *highlight* is provided, that node is wrapped in brackets.
        """
        if not chain:
            return "(empty)"
        arrow = " ──▶ "
        parts: list[str] = []
        for name in chain:
            if highlight and name == highlight:
                parts.append(f"【{name}】")
            else:
                parts.append(name)
        return arrow.join(parts)

    @staticmethod
    def _log_dag_event(
        event: str,
        chain: list[str],
        *,
        self_name: str = "",
        detail: str = "",
        level: str = "info",
    ) -> None:
        """Log a DAG-related event with a visual chain representation.

        Produces output like::

            ┌─ [DAG] CYCLE_DETECTED ────────────────────────────────────
            │ self=agent2
            │ 链路: agent1 ──▶ 【agent2】
            ├─ detail ──────────────────────────────────────────────────
            │ self=agent2 已存在于委派链中！
            └───────────────────────────────────────────────────────────
        """
        chain_str = SkillAgentExecutor._format_dag_chain(chain, highlight=self_name)
        meta_lines = [f"链路: {chain_str}"]
        if self_name:
            meta_lines.insert(0, f"self={self_name}")
        _log_boxed_document(
            f"[DAG] {event}",
            meta_lines=meta_lines,
            body_label="detail",
            body=detail,
            level=level,
        )

    @staticmethod
    def _log_dag_filter(
        reason: str,
        chain: list[str],
        *,
        before: int = 0,
        after: int = 0,
        removed: list[str] | None = None,
        kept: list[str] | None = None,
    ) -> None:
        """Log a DAG filter event showing what was removed from a pool.

        Produces output like::

            ┌─ [DAG] PLANNER_POOL ──────────────────────────────────────
            │ 链路: agent1 ──▶ agent2
            │ 池大小: 6 → 3
            ├─ filter ──────────────────────────────────────────────────
            │ 剔除: agent1, agent2
            │ 保留: agent3, agent4
            └───────────────────────────────────────────────────────────
        """
        chain_str = SkillAgentExecutor._format_dag_chain(chain)
        meta_lines = [f"链路: {chain_str}"]
        if before or after:
            meta_lines.append(f"池大小: {before} → {after}")
        body_parts: list[str] = []
        if removed:
            body_parts.append(f"剔除: {', '.join(sorted(removed))}")
        if kept:
            body_parts.append(f"保留: {', '.join(sorted(kept))}")
        _log_boxed_document(
            f"[DAG] {reason}",
            meta_lines=meta_lines,
            body_label="filter",
            body="\n".join(body_parts),
        )

    def _log_dag_startup(
        self,
        *,
        is_delegated: bool,
        self_name: str,
        chain: list[str],
    ) -> None:
        """Log DAG enforcement status at collaboration entry."""
        status = "ENABLED" if is_delegated else "ENABLED (root, no chain yet)"
        self_label = (
            self_name if self_name not in chain else f"【{self_name}】⚠️"
        )
        _log_boxed_document(
            "[DAG] STARTUP",
            meta_lines=[
                "DAG 委派链路约束已开启",
                f"状态={status}",
                f"当前 agent={self_label}",
            ],
            body_label="chain",
            body=self._format_dag_chain(chain),
        )

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
            description = "\n" + "\n".join(lines)
            logger.info(
                "[LocalSkill][CardBuild] rendered AgentCard: skills_count=%d",
                len(lines),
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

                found_count = len(search_items)
                total_chars = len(memory_texts_str)
                hit = "yes" if memory_texts_str.strip() else "no"
                if memory_texts:
                    mem_parts: list[str] = []
                    for i, text in enumerate(memory_texts, start=1):
                        display = text[:600]
                        if len(text) > 600:
                            display += f"...（截断，共 {len(text)} 字符）"
                        mem_parts.append(f"── 第 {i} 条 ──")
                        mem_parts.append(display)
                        mem_parts.append("")
                    mem_body = "\n".join(mem_parts).rstrip()
                else:
                    mem_body = "(无匹配记忆)"
                _log_boxed_document(
                    "[GetMemory] data-services",
                    meta_lines=[
                        f"memory_owner={memory_owner}",
                        f"found_count={found_count}    "
                        f"total_chars={total_chars}    hit={hit}",
                    ],
                    body_label="memories",
                    body=mem_body,
                )

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
    _SKILL_LIST_HEADER = ""

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
            detail_raw = str(getattr(s, "detail", "") or "").strip()
            if not name:
                continue
            lines.append(f"- {name}: {desc_inline}")
            try:
                # AgentSkill.description = skill 的 full detail（SKILL.md 正文），不截断
                agent_skills.append(
                    AgentSkill(
                        id=name,
                        name=name,
                        description=detail_raw or desc_raw or desc_inline,
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

        # agent_card.description = 所有 skill 的 name + short description 列表（不截断）
        description = self._SKILL_LIST_HEADER + "\n" + "\n".join(lines)
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

    async def _emit_execution_flow(
        self,
        updater: TaskUpdater,
        execution_task: ExecutionTask,
    ) -> None:
        """Emit an Execution Flow frame via A2A artifact.

        Mirrors ``_emit_progress`` but for Execution Flow frames.
        Frame is sent via artifact ``name="execution-flow"``.
        """
        frame = execution_task.to_frame()
        await updater.add_artifact([TextPart(text=frame)], name="execution-flow")
        logger.info(
            "[ExecutionFlow][Skill] emit execution_id=%s agent=%s stage=%s parent=%s",
            execution_task.execution_id,
            execution_task.agent,
            execution_task.stage,
            execution_task.parent_execution_id,
        )

    async def _reemit_parented_peer_execution_flow(
        self,
        updater: Optional[TaskUpdater],
        peer_tasks: list["ExecutionTask"],
    ) -> None:
        """Re-send peer EF frames after ``parent_execution_id`` is attached.

        The peer already streamed the same ``execution_id`` with ``parent=null``.
        Frontend upserts by id, so this rewrite hangs those nodes under the
        wrapper in the execution tree.
        """
        if updater is None:
            return
        for pt in peer_tasks:
            await self._emit_execution_flow(updater, pt)

    async def _record_none_execution_task(
        self,
        *,
        task_id: int,
        description: str,
        updater: Optional[TaskUpdater],
        turn: int,
        stage: str,
        run_id: str,
        trace_id: str,
        user_id: str,
        execution_flow_tasks: list["ExecutionTask"],
        all_task_results: Optional[dict[int, str]] = None,
        extra_reason: str = "",
    ) -> ExecutionTask:
        """Record ``agent=NONE`` as a first-class ExecutionTask.

        NONE is a planner protocol meaning "no capable agent in the current
        pool", not a silent no-op.  The task is not dispatched (no skill run,
        no A2A), but it must appear in the execution ledger so later turns
        and the final flow markdown can see that this round concluded with
        an unassigned gap.
        """
        reason = (extra_reason or "").strip() or (
            f"{NONE_TASK_REASON_CODE}: 当前可用智能体中无人可执行此任务"
        )
        none_ef = ExecutionTask(
            execution_id=f"none-{task_id}-t{turn}-{stage}",
            turn=turn,
            stage=stage,
            agent="NONE",
            role="initiator",
            task=description or "",
            result=NONE_TASK_UNASSIGNED_RESULT,
            reason=reason,
            parent_execution_id=None,
            delegated_by=None,
            run_id=run_id,
            trace_id=trace_id,
            user_id=user_id,
        )
        execution_flow_tasks.append(none_ef)
        if all_task_results is not None:
            all_task_results[task_id] = NONE_TASK_UNASSIGNED_RESULT
            status_list = getattr(self, "_tasks_status_list", None)
            if isinstance(status_list, list):
                status_list.append({
                    "id": task_id,
                    "description": description,
                    "agent": "NONE",
                    "status": "fail",
                    "failure_reason_code": NONE_TASK_REASON_CODE,
                    "answer": NONE_TASK_UNASSIGNED_RESULT,
                })
        self._log_data_flow(
            direction="TASK_UNASSIGNED",
            description=f"Task #{task_id} agent=NONE, not dispatched",
            source_id=self._self_planner_agent_name(),
            target_id="NONE",
            payload_chars=len(description or ""),
            payload_preview=(description or "")[:1000],
            metadata_extra={
                "task_id": task_id,
                "reason": NONE_TASK_REASON_CODE,
                "stage": stage,
                "turn": turn,
            },
        )
        logger.info(
            "[Orchestration] task #%d agent=NONE recorded as ExecutionTask | "
            "turn=%d stage=%s reason=%s",
            task_id,
            turn,
            stage,
            NONE_TASK_REASON_CODE,
        )
        if updater is not None:
            await self._emit_progress(
                updater,
                "task_unassigned",
                message=(
                    f"Task #{task_id} agent=NONE, not dispatched: "
                    f"{_short(description or '')}"
                ),
                status="done",
                task_id=task_id,
                extra={
                    "task_id": task_id,
                    "agent": "NONE",
                    "reason": NONE_TASK_REASON_CODE,
                    "stage": stage,
                },
            )
            await self._emit_execution_flow(updater, none_ef)
        return none_ef

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

    @staticmethod
    def _is_execution_flow_frame(text: str) -> bool:
        """Check if a text line is a [[DAC_EXECUTION_FLOW]] frame."""
        return is_execution_flow_frame(text)

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
        delegation_chain: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Mid-execution Step 1: detect whether a data gap still exists via LLM reasoning.

        Includes task-type classification (structured vs unstructured) to apply
        domain-appropriate gap detection rules.  Structured tasks follow strict
        field-level gap rules; unstructured tasks use a higher bar for delegation."""
        # ── Log entry context ──
        _collab_names = [getattr(c, "name", "?") for c in (collaborator_cards or [])]
        _chain_preview = SkillAgentExecutor._format_dag_chain(delegation_chain or [])
        logger.info(
            "[DetectDelegation] entry | query=%s collaborator_cards=%s delegation_chain=%s",
            (query or "")[:200],
            _collab_names,
            _chain_preview,
        )
        own_text = "\n".join(
            f"[Task#{tid}]: {res}" for tid, res in own_results.items() if res
        )
        del_text = "\n".join(
            f"[{name}]: {res or '[EMPTY — 该 SG 未返回任何数据]'}"
            for name, res in delegated_results.items()
        )
        if collaborator_cards:
            sg_options = "\n".join(
                f"- {c.name}（{str(c.description or '')[:200]}）"
                for c in collaborator_cards
            )
            # Build skill-level info for each collaborator so the detection LLM
            # can write synthesized_query from the downstream SG's perspective.
            sg_skills_lines: list[str] = []
            for c in collaborator_cards:
                skills = c.skills or []
                skill_names = [s.name for s in skills if getattr(s, "name", "")]
                if skill_names:
                    sg_skills_lines.append(
                        f"- {c.name} 技能: {', '.join(skill_names)}"
                    )
            sg_skills_info = "\n".join(sg_skills_lines) if sg_skills_lines else "(无技能信息)"
        else:
            sg_options = (
                "(当前 Routing peer 池为空；不要据此判定无法委派。"
                "最终远程 SG 由后续全量 capability_check 广播决定，target_sgs 可留空。)"
            )
            sg_skills_info = "(无可用 SG 技能信息)"

        prompt = (
            "你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，"
            "判断是否还需要其他领域的补充数据。\n\n"
            # ═══════════════════════════════════════════════════════════════
            "## 步骤 0：任务类型分类（必须在所有判断之前完成）\n\n"
            "根据原始问题和本层执行结果的特征，将任务归类为 structured 或 unstructured。\n\n"
            "**structured（结构化数据查询）的判断特征：**\n"
            "- 问题涉及数据库表、SQL 查询、字段查找、记录检索、ID 关联\n"
            "- 期望的答案是有限数据集（如某人的订单列表、某商品的统计值、某条件的筛选结果）\n"
            "- 执行结果以字段-值对、表格、记录列表或统计数字呈现\n"
            "- 有明确的数据边界：「查到了哪些字段」vs「还缺哪些字段」\n"
            "- 典型关键词：查询、查找、列表、多少、哪些、统计、汇总、筛选、关联\n\n"
            "**unstructured（非结构化处理）的判断特征：**\n"
            "- 问题涉及文档总结、文本分析、代码审查、翻译、内容生成、知识问答\n"
            "- 期望的答案是开放性叙述（段落式分析、评判性结论、描述性总结）\n"
            "- 执行结果以描述性段落文本呈现，而非字段-值行列表\n"
            "- 答案没有「穷尽」的概念——始终可以从不同角度、不同深度做补充，但这不代表「有缺口」\n"
            "- 典型关键词：分析、总结、审查、解释、翻译、评估、建议、判断\n\n"
            "**分类方法（按此程序执行，不要靠关键词或题型印象判断）：**\n"
            "只看原始问题那一段（分类时不要读「本层自身执行结果」）。执行下面这个判定程序：\n\n"
            "第1步：写出答案模板。\n"
            "   把原始问题改写成一句带空白的回答句，例如"
            "「这个任务的答案是：____」或「结论是：____」。\n\n"
            "第2步：问一句——「这个答案本身，是不是已经存在、只等取回？」\n"
            "   → 是：答案是一个值 / 列表 / 记录集，本来就记在某处，取回即可 → **structured**\n"
            "   → 否：答案谁都没有记录过，必须由人依据取回的数据推导、权衡、下结论 → **unstructured**\n\n"
            "判别示范（只看判断过程，不要记题型）：\n"
            "   · 「A 的供应商是谁、库存多少」→ 答案「供应商__、库存__」"
            "→ 这两个值本来就记在系统里 → structured\n"
            "   · 「这份代码有哪些安全风险」→ 答案「存在__风险」"
            "→ 没有任何地方记录过这个结论，要靠人判定 → unstructured\n\n"
            "⚠ 最关键的陷阱（此处判错最多，务必执行）：\n"
            "   本层如果声明「缺少 XX 数据 / 某个字段没拿到」，这只说明 **XX 数据存在**，"
            "**不等于答案存在**。二者必须分开问：\n"
            "     数据存在？ → 多数情况都是「是」（否则没法查），但这不决定分类。\n"
            "     答案存在？ → 只有这个问题决定分类。\n"
            "   自检：把所有声明缺失的数据也都拿到手之后，答案是不是就自动成型了？\n"
            "     → 是 → structured；→ 否（还要人下判断）→ unstructured。\n\n"
            "⚠ 另一条禁令：禁止用「本层结果里有没有字段/记录/日志」当依据。"
            "能力缺失导致中断时，中间结果必然只剩已核实的数据片段，"
            "这是中断的副产物，与任务类型无关。\n\n"
            "**分类自检方法：**\n"
            "问自己：「这个任务的执行结果，有没有一个客观的标准来判断它是否'完整'？」\n"
            "→ 如果答案是「有」→ structured（比如：缺了某个字段、缺了某张表的数据）\n"
            "→ 如果答案是「没有」→ unstructured（比如：一个文档分析永远可以更深入，但已有的分析已经是对原始问题的充分回答）\n\n"
            "请先确定 task_type，然后根据类型选择下面的判定规则。\n\n"
            # ═══════════════════════════════════════════════════════════════
            "## 步骤 1a：结构化数据缺口的判定规则（仅当 task_type=structured 时适用）\n\n"
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
            "6）needs_help=false 的条件：当本层结果已覆盖原始问题所有必需的域，"
            "且参考下方的 SG 技能列表，没有其他 agent 声明的技能范围能补充本层缺失的数据时，"
            "才返回 needs_help=false。注意：不需要证明「绝对没有 agent 有」，只需判断列表中没有匹配的即可。\n\n"
            "**structured synthesized_query 书写规则（强制）：**\n"
            "- 只写下游 SG 本轮需要交付的子问题：关联键 + 缺失字段；\n"
            "- 当没有关联键时，传递原始问题中的实体信息（姓名、ID、关键词等）作为查询线索；\n"
            "- 禁止复述完整原题；禁止写入其它域目标或整题扩写；\n"
            "- 禁止要求下游去计算本层已有或本层负责的指标；\n"
            "- 下游拿到这句话应能直接执行并结束，无需理解整题其它部分。\n"
            "- 【关键】synthesized_query 必须从下游 SG 的视角编写，而非本层视角：\n"
            "  本层（delegator）的视角是「我需要什么数据」，下游 SG 的视角是「我能用自己的技能回答什么问题」。\n"
            "  synthesized_query 必须采用下游 SG 的视角：描述一个下游 SG 能用自己的技能独立完成的子问题。\n"
            "  自检方法：如果本层自己就能回答 synthesized_query 描述的问题，\n"
            "  → 说明写错了域，这是本层域内的问题，下游 SG 没有对应的技能。\n"
            "  正确做法：先看下方「SG 技能列表」中 target_sgs 的技能，确认它们能处理什么类型的问题，\n"
            "  然后 synthesized_query 只写这些技能能直接处理的内容。\n\n"
            # ═══════════════════════════════════════════════════════════════
            "## 步骤 1b：非结构化任务缺口的判定规则（仅当 task_type=unstructured 时适用）\n\n"
            "核心原则：非结构化任务（文档总结、文本分析、代码审查、翻译等）没有「标准答案」，"
            "「完成」意味着给出了对原始问题的实质性、有结构的回答，而非穷尽了所有可能的角度。\n\n"
            "**前置条件（在判定任何缺口之前必须先通过）：**\n"
            "非结构化任务只承认「明确数据缺口」。要判定 needs_help=true，"
            "你必须先能写出一个下游 SG 用其自身技能可直接执行的具体子问题。\n"
            "自检方法：先在心里写出 synthesized_query，再问「这句话能让下游 SG 直接开工吗？」\n"
            "→ 写得出来 → 这是明确缺口，继续用下面的 A/B 条件判定；\n"
            "→ 写不出来，只能说「可以更深入」「可以补充某方面的分析」→ 这是开放式思考方向，"
            "不是数据缺口，直接返回 needs_help=false。\n"
            "⚠ 非结构化任务不存在「无限可补充」意义上的缺口：任何分析在理论上都能做得更深，"
            "但这不构成委派理由。写不出明确子问题，就等于没有缺口。\n\n"
            "**触发 needs_help=true 的条件（较严格，只有以下情况才委派）：**\n"
            "A）本层结果明确声明了具体的、可查证的缺失项，"
            "且下方 SG 技能列表中确有 agent 能填补该项。\n"
            "   示例：执行结果说「代码审查完成了安全部分，但缺少合规性审计」，"
            "且下方有 compliance-agent → 可委派。\n"
            "   反例：执行结果是一个完整的产品描述翻译，但「术语库 agent 可能有更精确译法」"
            "→ 这不是明确的缺失项，不委派。\n"
            "   ⚠ 但请注意区分「泛指」与「已点名具体缺失项」——后者是明确缺口：\n"
            "   · 泛指（不委派）：翻译已完整交付，只是笼统认为「术语库也许有更准的说法」，"
            "说不出具体是哪个词有问题 → needs_help=false。\n"
            "   · 已点名（委派）：结果明确指出「术语 X、Y 的确切译法未能确定」，"
            "且下方有 terminology-agent 可查证这些具体术语 → needs_help=true，"
            "因为 gap 已被收敛成可执行的子问题。\n\n"
            "B）本层结果明确表示「不具备该能力」或「能力域错误」，"
            "且原始问题中的实体或概念在它域可能存在。\n"
            "   示例：order-agent 收到了「审查 payment_service.py 的安全漏洞」，"
            "返回「不具备代码审查能力」→ 应委派给 code-agent。\n\n"
            "**触发 needs_help=false 的条件（以下任一成立就不委派）：**\n"
            "I）本层已经返回了一个成文的、有逻辑结构的分析/总结/审查/翻译结论。\n"
            "   「成文」指结果中包含实质性的内容（不是空壳、不是纯报错、不是仅声明能力不足）。\n"
            "   「有逻辑结构」指结果有完整的叙事或分析框架（不是零散片段）。\n"
            "   这时即使理论上「可以更深入」，也应返回 needs_help=false。\n\n"
            "II）原始问题是一个不需要外部数据的自包含任务（如纯翻译、纯格式化、纯生成）。\n"
            "   示例：「把这段文字翻译成英文」—— 翻译已完成即 needs_help=false。\n\n"
            "III）本层结果对原始问题的核心诉求已给出充分回答，只是缺少次要补充信息。\n"
            "    示例：「分析这份报告的核心内容」→ 本层已提取并归纳了全文要点。\n"
            "    即使「报告中提到的某法规的精确引用条款」没有展开，也不属于必须委派的缺口。\n\n"
            "**unstructured 场景下 outcome=partial 的含义不同：**\n"
            "- 非结构化任务中 outcome=partial 是常态（任何分析都是'部分'的），不是强制委派信号。\n"
            "- 只有当 partial 的原因是一个具体的、可查证的能力缺失时（见条件 A），才委派。\n\n"
            "**unstructured 场景下的 synthesized_query（强制）：**\n"
            "- synthesized_query 是 needs_help=true 的**必要条件**：写不出它，就不算明确缺口，"
            "needs_help 必须为 false。\n"
            "- 判定顺序固定为：先写 synthesized_query，再据此决定 needs_help。"
            "禁止先判 needs_help=true 再回头补一个空泛的描述。\n"
            "- 上文「前置条件」中的反例（「术语库 agent 可能有更精确译法」）就是典型："
            "这类说法写不出可执行子问题，因此不构成缺口，needs_help=false。\n"
            "- synthesized_query 必须从下游 SG 视角编写，描述一个下游 SG 能用自己的技能独立完成的子问题。\n"
            "- 【严禁】用「补充某方面的分析」「进一步深入」「完善相关评估」这类开放式表述充数——"
            "它们不是可执行子问题，等同于没写；此时应返回 needs_help=false。\n\n"
            # ═══════════════════════════════════════════════════════════════
            "## 通用重要约束（两种类型均适用）\n\n"
            "- 不要依据 SG 的自描述文案选择目标；最终远程 SG 由后续标准 "
            "capability_check 全量广播（成员能力证据）决定；\n"
            "- 当 needs_help=true 时，target_sgs 应填写你认为可补充数据的 SG 名称。\n"
            "  最终远程 SG 由后续标准 capability_check 全量广播决定，此处的 target_sgs 用于辅助性提示。\n"
            "- target_sgs 中的名称必须从上方列表中的 SG 名称中精确选取，不得编造不存在的 SG 名称。\n"
            "- 【关键】如果「已完成委托结果」中显示某个 SG 返回了空结果或标记为 EMPTY，"
            "说明该 SG 无法为此问题提供数据。此时 target_sgs 不要再次包含该 SG 名称，"
            "应尝试委托给列表中其他不同的 SG（agent）。\n\n"
            # ═══════════════════════════════════════════════════════════════
            f"原始问题：{query}\n\n"
            f"本层自身执行结果：\n{own_text}\n\n"
            f"已完成委托结果：\n{del_text}\n\n"
            f"可委托的 SG 名称列表（仅供参考，非选人依据）：\n{sg_options}\n\n"
            f"SG 技能列表（用于判断缺口和编写 synthesized_query）：\n{sg_skills_info}\n\n"
            "请调用 detect_delegation_needs 工具来输出结果。\n"
            "注意：task_type 字段必须首先填写，且必须选择 structured 或 unstructured 之一。\n"
            "当 needs_help=true 时，reason 字段必须说明具体缺了什么数据、为什么需要补充。"
        )

        # ── Self-execution hint: if self is in the collaborator pool, remind the
        # detection LLM that it can recommend self when the local agent itself
        # can now handle the data gap (e.g. after acquiring a user-id mapping).
        self_name = self._self_planner_agent_name()
        _collab_names = {getattr(c, "name", "") for c in (collaborator_cards or [])}
        if self_name and self_name in _collab_names:
            prompt += (
                f"\n\n"
                f"────────── 本层自执行提示 ──────────\n"
                f"本层（{self_name}）已出现在可委派列表中。\n"
                f"如果本层通过委托已获取到新的关键数据（如关联键、ID映射），"
                f"且本层自身的技能可以基于这些新数据完成补充查询，"
                f"target_sgs 应优先包含本层名称（{self_name}），"
                f"让本层自行完成查询，无需再次委托给外部 SG。\n"
                f"──────────────────────────────────\n"
            )

        # ── DAG Layer 4: inject chain info into detection LLM prompt ──
        if self._dag_enforcement_enabled() and delegation_chain:
            chain_text = self._format_dag_chain(delegation_chain)
            prompt += (
                f"\n\n"
                f"────────── DAG 约束（有向无环图） ──────────\n"
                f"当前委派链路: {chain_text}\n"
                f"────────────────────────────────────────\n"
                f"⚠️ 上述链路中的 SG 已经参与了本次协作，严禁再次推荐为目标！\n"
                f"target_sgs 中不得包含链路中的任何 SG 名称。\n"
                f"──────────────────────────────────────────\n"
            )
            self._log_dag_event(
                "DETECT_PROMPT",
                chain=delegation_chain,
                detail="已将委派链路注入检测 LLM prompt",
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
                agent_name=self._self_planner_agent_name(),
            )
            if data_dict is None or not isinstance(data_dict, dict):
                return None
            wants_help = data_dict.get("needs_help", False)
            if not wants_help:
                logger.info(
                    "[MidExec][Detect] LLM verdict: no help needed | task_type=%s reason=%s",
                    (data_dict.get("task_type") or "?"),
                    (data_dict.get("reason") or "")[:120],
                )
                return None
            result = {
                "needs_help": True,
                "task_type": data_dict.get("task_type") or "unstructured",
                "synthesized_query": data_dict.get("synthesized_query", ""),
                "target_sgs": data_dict.get("target_sgs", []),
                "reason": data_dict.get("reason", ""),
                "source": "llm_detection",
            }
            logger.info(
                "[MidExec][Detect] LLM verdict: needs help | task_type=%s target_sgs=%s reason=%s",
                (data_dict.get("task_type") or "?"),
                (data_dict.get("target_sgs") or [])[:5],
                (data_dict.get("reason") or "")[:120],
            )
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

        Injects the upstream's executed_tasks and (in mid-exec rounds)
        already_delegated / synthesized_query / detection_reason into the
        group_memory string so the Planner can produce more precise task
        descriptions that reference prior work.
        """
        parts: list[str] = []
        if base_group_memory:
            parts.append(base_group_memory)

        exec_tasks = upstream_context.get("executed_tasks")
        upstream_inner = upstream_context.get("upstream_context")

        upstream_info_parts: list[str] = []
        if exec_tasks:
            tasks_text = json.dumps(exec_tasks, ensure_ascii=False)
            upstream_info_parts.append(f"上游已执行任务及结果: {tasks_text}")
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
        if exec_tasks:
            _exec_descs = ", ".join(
                f"#{t.get('task_id', '?')}:{str(t.get('result', ''))}"
                for t in (exec_tasks if isinstance(exec_tasks, list) else [])
            )
            _preview_parts.append(f"executed=[{_exec_descs}]")
        if upstream_inner:
            _preview_parts.append("hasUpstreamChain")
        _preview = " | ".join(_preview_parts) if _preview_parts else "(none)"
        logger.info(
            "[Cross-SG][CollabEnrichMem] upstream_context injection | base_chars=%d enriched_chars=%d fields=%s preview=%s",
            len(base_group_memory or ""),
            len(result),
            [
                k
                for k in ("executed_tasks", "upstream_context")
                if upstream_context.get(k)
            ],
            _preview,
        )
        return result

    @staticmethod
    def _format_upstream_context_summary(upstream_context: dict | None) -> str:
        """Produce a compact, human-readable summary of upstream_context for logging.

        Example output: ``executed=2tasks chain=1``
        If upstream_context is empty or None, returns ``(none)``.
        """
        if not upstream_context:
            return "(none)"
        parts: list[str] = []
        _exec = upstream_context.get("executed_tasks")
        _inner = upstream_context.get("upstream_context")
        if _exec:
            parts.append(f"executed={len(_exec)}tasks")
        if _inner:
            parts.append(f"upstreamChain=depth+1")
        return " ".join(parts) if parts else "(empty)"

    def _mid_delegate_capability_select_enabled(self) -> bool:
        return os.getenv("SG_MID_DELEGATE_CAPABILITY_SELECT_ENABLED", "true").strip().lower() not in ("false", "0", "no")

    def _mid_delegate_detect_direct_enabled(self) -> bool:
        """When enabled, skip broadcast capability check and use detection LLM
        results directly.  The detection LLM already has full context (original
        query, own results, delegated results, agent skills, DAG chain) and
        produces well-reasoned target_sgs recommendations.  Broadcasting a
        bare query to all agents can override the detection LLM's choice with
        a higher-confidence but less-informed agent.
        """
        return os.getenv("SG_MID_DELEGATE_DETECT_DIRECT_ENABLED", "false").strip().lower() not in ("false", "0", "no")

    def _mid_delegate_max_targets(self) -> int:
        try:
            return max(1, int(os.getenv("SG_MID_DELEGATE_MAX_TARGETS", "3") or 3))
        except ValueError:
            return 3

    def _mid_exec_confidence_threshold(self) -> float:
        """Minimum confidence score for mid-exec delegation target selection.

        Agents with capability_check confidence below this threshold are
        excluded from the target pool.  Default 0.5; controlled by the
        ``SG_MID_DELEGATE_CONFIDENCE_THRESHOLD`` env var.
        """
        try:
            return float(os.getenv("SG_MID_DELEGATE_CONFIDENCE_THRESHOLD", "0.5") or 0.5)
        except ValueError:
            return 0.8

    @staticmethod
    def _mid_exec_capability_probe_query(
        synthesized_query: str,
        *,
        original_query: str = "",
        executed_tasks: list[dict] | None = None,
        detection_reason: str = "",
    ) -> str:
        """Build a probe query for remote SG capability check.

        Uses the same structured ``executed_tasks`` format as
        :meth:`_build_mid_exec_planner_context` so the remote SG sees
        a clean, consistent view of what has already been done.
        """
        scoped = (synthesized_query or "").strip()
        if not scoped:
            return scoped

        lines: list[str] = []
        lines.append("请根据下面提供的信息和自身的skill的能力，分析是否可以解答或处理信息中提到的问题。")
        lines.append("")

        # ── Section 1: Core Task ──
        if original_query:
            lines.append(f"**原始问题**：{original_query}")
        if detection_reason:
            lines.append(f"**委派原因**：{detection_reason}")
        lines.append("")

        # ── Section 2: Executed Tasks ──
        if executed_tasks:
            lines.append("## 已执行任务")
            lines.append("")
            lines.append("| Task ID | Agent | 描述 | 状态 | 结果 |")
            lines.append("|---------|-------|------|------|------|")
            for t in executed_tasks:
                tid = str(t.get("task_id", t.get("id", "?")))
                agent = str(t.get("agent", "") or "")
                desc = (str(t.get("description", "") or ""))[:200]
                status = str(t.get("status", "?"))
                result = (str(t.get("result", "") or ""))[:500]
                status_icon = "✅" if status == "completed" else "❌"
                lines.append(f"| {tid} | {agent} | {desc} | {status_icon} | {result} |")
            lines.append("")

        # ── Section 3: Sub-Task ──
        lines.append(f"**子任务**：{scoped}")

        return "\n".join(lines)

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
        original_query: str = "",
        executed_tasks: list[dict] | None = None,
        detection_reason: str = "",
    ) -> dict[str, Any]:
        """Select mid-delegate peer SGs via concurrent standard capability_check.

        When *original_query*, *executed_tasks*, or *detection_reason* are
        provided they are injected into the probe query so the
        capability-check LLM receives the same context as the detection LLM.
        """
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

        probe_query = self._mid_exec_capability_probe_query(
            synthesized_query,
            original_query=original_query,
            executed_tasks=executed_tasks,
            detection_reason=detection_reason,
        )

        logger.info("[MidExec][CapSelect] _select_mid_delegate_targets_via_capability probe_query=%s", probe_query)

        capable_pairs = await sg_broadcast.probe_agents_capability_concurrent(
            probe_query, candidates, user_id, run_id, trace_id,
        )
        probed_names = [c.name for c in candidates]
        if capable_pairs:
            capable_pairs = self._rank_mid_exec_capable_pairs(capable_pairs, hint_names)

        # ── Confidence threshold ──
        # Filter out agents whose capability_check confidence is below the
        # minimum threshold.  This prevents irrelevant agents (e.g. an LLM
        # fine-tuning agent for a purchase-history query) from being selected
        # just because they happened to be the only candidate in the pool.
        #
        # IMPORTANT: the threshold ONLY applies to agents that claim
        # ``can_handle=True``.  Agents that are ``can_handle=False`` but
        # ``can_contribute=True`` (e.g. a product-agent that can supplement
        # product details once order-agent returns product IDs) are NOT
        # filtered — they are genuinely useful contributors even if their
        # confidence is below the threshold.
        _threshold = self._mid_exec_confidence_threshold()
        if capable_pairs and _threshold > 0:
            _before = len(capable_pairs)
            _filtered: list[tuple[AgentCard, Any]] = []
            _dropped: list[str] = []
            _skipped_contributors: list[str] = []
            for card, resp in capable_pairs:
                conf = float(getattr(resp, "confidence", 0.0) or 0.0)
                can_handle = bool(getattr(resp, "can_handle", False))
                can_contribute = bool(getattr(resp, "can_contribute", False))
                if can_handle:
                    # can_handle=True: must pass confidence threshold
                    if conf >= _threshold:
                        _filtered.append((card, resp))
                    else:
                        _dropped.append(f"{card.name}({conf:.2f})")
                elif can_contribute:
                    # can_handle=False but can_contribute=True: skip threshold,
                    # keep as a contributor
                    _filtered.append((card, resp))
                    _skipped_contributors.append(f"{card.name}({conf:.2f})")
                else:
                    # neither can_handle nor can_contribute: drop
                    _dropped.append(f"{card.name}({conf:.2f})")
            if len(_filtered) < _before:
                if _dropped:
                    logger.info(
                        "[MidExec][CapSelect] confidence threshold filtered | "
                        "threshold=%.2f before=%d after=%d dropped=%s",
                        _threshold, _before, len(_filtered), _dropped,
                    )
            if _skipped_contributors:
                logger.info(
                    "[MidExec][CapSelect] confidence threshold bypassed for contributors | "
                    "threshold=%.2f kept=%s",
                    _threshold, _skipped_contributors,
                )
            capable_pairs = _filtered

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

    @staticmethod
    def _build_mid_exec_planner_context(
        *,
        synthesized_query: str,
        target_cards: list,
        original_query: str = "",
        detection_reason: str = "",
        executed_tasks: list[dict] | None = None,
        delegation_chain: list[str] | None = None,
        turn: int = 1,
        mid_exec_round: int = 1,
    ) -> str:
        """Build a clean, markdown-formatted context for the mid-exec Planner.

        Produces a structured, human-readable context block that avoids JSON
        blobs and confusing separators, making it easy for the Planner LLM
        to parse and call ``make_plan_cmd`` reliably.

        Returns a string to be used as the Planner's ``group_memory``.
        """
        lines: list[str] = []

        # ── Section 1: Core Task ──
        lines.append("## 1. 本轮子任务")
        lines.append(f"**子任务**：{synthesized_query}")
        if original_query:
            lines.append(f"**原始用户问题**：{original_query}")
        if detection_reason:
            lines.append(f"**委派原因**：{detection_reason}")
        lines.append("")

        # ── Section 2: Available Agents ──
        if target_cards:
            lines.append("## 2. 可用智能体")
            lines.append("")
            for c in target_cards:
                name = getattr(c, "name", "?")
                desc = (getattr(c, "description", "") or "")[:300]
                skills = getattr(c, "skills", None) or []
                skill_names = [s.name for s in skills if getattr(s, "name", "")]
                lines.append(f"### {name}")
                lines.append(f"- **描述**：{desc}")
                if skill_names:
                    lines.append(f"- **技能**：{', '.join(skill_names)}")
                lines.append("")

        # ── Section 3: Executed Tasks (unified table) ──
        if executed_tasks:
            lines.append("## 3. 已执行任务")
            lines.append("")
            lines.append("| Task ID | Agent | 描述 | 状态 | 结果 |")
            lines.append("|---------|-------|------|------|------|")
            for t in executed_tasks:
                tid = str(t.get("task_id", t.get("id", "?")))
                agent = str(t.get("agent", "") or "")
                desc = (str(t.get("description", "") or ""))[:200]
                status = str(t.get("status", "?"))
                result = (str(t.get("result", "") or ""))[:500]
                status_icon = "✅" if status == "completed" else "❌"
                lines.append(f"| {tid} | {agent} | {desc} | {status_icon} | {result} |")
            lines.append("")

        # ── Section 4: DAG Chain ──
        if delegation_chain:
            chain_str = " → ".join(delegation_chain)
            lines.append("## 4. DAG 委派链路")
            lines.append(f"当前链路：{chain_str}")
            lines.append("⚠️ 上述链路中的 Agent 已参与本轮协作，不可再次分配任务。")
            lines.append("")

        # ── Section 5: Planning Rules ──
        lines.append("## 5. 规划规则")
        lines.append("1. `description` 必须忠实于**本轮子任务**，禁止扩写为完整原题")
        lines.append("2. 每个 task 的 `agent` 必须从「可用智能体」中选取")
        lines.append("3. 如果所有可用智能体都无法处理该子任务，`agent` 填 `NONE`")
        lines.append("4. 已执行任务的结果只用于理解上下文，不得重复执行")
        lines.append("5. 只输出一个纯 JSON 对象，不要 ```json 围栏，字段全必填")

        result = "\n".join(lines)
        agent_names = [
            str(getattr(c, "name", "") or "").strip() or "?"
            for c in (target_cards or [])
        ]
        tr_meta = _turn_round_meta(turn=turn, mid_exec_round=mid_exec_round)
        _log_boxed_document(
            f"[MidExec][Plan] planner context{_turn_round_label(turn=turn, mid_exec_round=mid_exec_round)}",
            meta_lines=[
                f"{tr_meta}    chars={len(result)}    "
                f"agents={', '.join(agent_names) or '-'}",
                f"subtask={_short(synthesized_query, 160)}",
            ],
            body_label="group_memory",
            body=result,
        )
        return result

    async def _plan_mid_exec_delegation(
        self,
        synthesized_query: str,
        target_cards: list[AgentCard],
        *,
        original_query: str = "",
        executed_tasks: list[dict] | None = None,
        detection_reason: str = "",
        delegation_chain: list[str] | None = None,
        turn: int = 1,
        mid_exec_round: int = 1,
    ) -> Optional[TaskList]:
        """Mid-execution Step 2: plan tasks against capability-selected peers.

        Builds a clean, markdown-formatted planner context via
        :meth:`_build_mid_exec_planner_context`.
        """
        if not target_cards or not synthesized_query:
            return None
        try:
            planner_ctx = self._build_mid_exec_planner_context(
                original_query=original_query,
                synthesized_query=synthesized_query,
                target_cards=target_cards,
                detection_reason=detection_reason,
                executed_tasks=executed_tasks,
                delegation_chain=delegation_chain,
                turn=turn,
                mid_exec_round=mid_exec_round,
            )
            planner = self._get_planner()
            plan = await planner.make_plan(
                synthesized_query, target_cards, group_memory=planner_ctx, plan_stage="mid_exec",
            )
            return self._apply_scoped_mid_exec_task_descriptions(plan, synthesized_query)
        except Exception as e:
            logger.warning("[MidExec][Plan] mid-exec plan failed: %s", e)
            return None

    async def _plan_mid_exec_delegation_with_full_context(
        self,
        synthesized_query: str,
        target_cards: list[AgentCard],
        *,
        original_query: str,
        executed_tasks: list[dict],
        detection_reason: str = "",
        delegation_chain: list[str] | None = None,
        turn: int = 1,
        mid_exec_round: int = 1,
    ) -> Optional[TaskList]:
        """Mid-execution Step 2 (detect-direct path): plan tasks with full detection context.

        Builds a clean, markdown-formatted planner context via
        :meth:`_build_mid_exec_planner_context` that includes the original
        query, executed tasks, target agent skills, detection reason,
        DAG chain, and upstream context — the same information the
        detection LLM had.
        """
        if not target_cards or not synthesized_query:
            return None
        try:
            planner_ctx = self._build_mid_exec_planner_context(
                original_query=original_query,
                synthesized_query=synthesized_query,
                target_cards=target_cards,
                detection_reason=detection_reason,
                executed_tasks=executed_tasks,
                delegation_chain=delegation_chain,
                turn=turn,
                mid_exec_round=mid_exec_round,
            )
            planner = self._get_planner()
            plan = await planner.make_plan(
                synthesized_query, target_cards, group_memory=planner_ctx, plan_stage="mid_exec",
            )
            return self._apply_scoped_mid_exec_task_descriptions(plan, synthesized_query)
        except Exception as e:
            logger.warning("[MidExec][Plan][DetectDirect] mid-exec plan failed: %s", e)
            return None

    @staticmethod
    def compose_mid_exec_self_query(
        task_description: str,
        execution_flow: list | None = None,
        *,
        current_agent: str = "",
    ) -> str:
        """Build the SkillAgent query for a mid-exec local (self) task.

        The current-round ``synthesized_query`` stays in front so skill
        selection still keys off the actual ask. Prior-round Execution Flow
        is appended as a factual ledger (same snapshot dispatched to remote
        delegatees). Empty EF → return the task description unchanged.
        """
        task = (task_description or "").strip()
        ef_md = ""
        if execution_flow:
            try:
                ef_md = (
                    render_execution_flow_md(
                        execution_flow,
                        agent=current_agent,
                        current_agent=current_agent,
                        show_children=False,
                    )
                    or ""
                ).strip()
            except Exception:
                logger.warning(
                    "[MidExec][SelfExec] failed to render execution_flow for local query",
                    exc_info=True,
                )
                ef_md = ""
        if not ef_md:
            return task
        if not task:
            return ef_md
        return (
            f"当前任务: {task}\n\n"
            "【执行流水账】\n"
            "以下为截至本轮之前已发生的执行事实，仅用于理解关联键和已查到的值；"
            "不是本轮要回答的问题。\n\n"
            f"{ef_md}"
        )

    async def _execute_mid_exec_self_task(
        self,
        task_description: str,
        task_id: int,
        skill_runner: "SkillRunner | None",
        metadata: dict,
        updater: Optional[Any] = None,
        execution_flow: list | None = None,
    ) -> str:
        """Execute a task locally as self during mid-exec delegation.

        Reuses the same :class:`SkillAgent` local execution path as the main
        task loop, but does not consume a hop or build a delegation chain.

        ``execution_flow`` is the dispatch-time snapshot (prior rounds only).
        It is rendered into the SkillAgent query so local skills can read
        join keys from earlier mid-exec rounds — the same facts a remote
        delegatee sees via ``upstream_context["execution_flow"]``.
        """
        self_name = self._self_planner_agent_name()
        query = self.compose_mid_exec_self_query(
            task_description,
            execution_flow,
            current_agent=self_name,
        )

        # --- Data Flow: self-exec task start ---
        self._log_data_flow(
            direction="MID_SELF_EXEC",
            description=f"Mid-exec self-execution Task #{task_id} → 本地 {self_name} 执行",
            source_id=self.agent_id,
            target_id=f"{self_name} (in-process)",
            payload_chars=len(query or ""),
            payload_preview=(query or "")[:1000],
            metadata_extra={
                "task_id": task_id,
                "task_desc_chars": len(task_description or ""),
                "query_chars": len(query or ""),
                "ef_injected": bool(execution_flow) and query != (task_description or "").strip(),
            },
        )

        local_agent = SkillAgent(
            skill_runner=skill_runner,
            query=query,
            metadata=metadata,
            current_task_id=task_id,
            agent_id=self.agent_id,
            progress_callback=(
                (lambda frame: updater.add_artifact(
                    [TextPart(text=frame)], name="progress"
                ))
                if updater is not None
                else None
            ),
        )
        result_parts: list[str] = []
        async for chunk in local_agent.run():
            if chunk:
                result_parts.append(chunk)
        result = "\n".join(result_parts)

        # --- Data Flow: self-exec task result ---
        is_fail = result.startswith("Delegation failed:") or result.startswith("Execution error:") or not result.strip()
        self._log_data_flow(
            direction="MID_SELF_RESULT",
            description=f"Mid-exec self-execution Task #{task_id} 执行完毕",
            source_id=self_name,
            target_id=self.agent_id,
            payload_chars=len(result or ""),
            payload_preview=(result or "")[:1000],
            metadata_extra={
                "task_id": task_id,
                "status": "fail" if is_fail else "complete",
            },
        )

        return result

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
        skill_runner: "SkillRunner | None" = None,
        metadata: dict | None = None,
        turn: int = 1,
        detection_reason: str = "",
    ) -> tuple[dict[str, str], dict[str, str], int, list["ExecutionTask"]]:
        """Mid-execution Step 3: dispatch plan tasks to target SGs.

        Forward progress frames from delegated agents via ``updater`` so the
        delegated agent's DAC progress is visible to the end user.

        When *skill_runner* is provided and the task's agent is self, the
        task is executed locally (in-process) instead of delegated via A2A.

        Returns:
            Tuple of ``(delegate_results, self_results, remaining_hop, execution_flow_tasks)``.
            delegate_results       — remote delegation results (key: SG name)
            self_results           — in-process self-execution results (key: self agent name)
            remaining_hop          — reflects the hop count after all dispatches in this
                                     call, accounting for each delegation edge consumed.
            execution_flow_tasks   — list of ExecutionTask for this dispatch call.
        """
        delegate_results: dict[str, str] = {}
        self_results: dict[str, str] = {}
        execution_flow_tasks: list[ExecutionTask] = []
        name_to_card = {c.name: c for c in target_cards}
        hints = dict(hints_by_sg or {})
        mid_exec_round = int((upstream_context or {}).get("mid_exec_round") or 0)

        for task in plan.tasks:
            agent_name = (task.agent or "").strip()
            if agent_name.upper() == "NONE":
                await self._record_none_execution_task(
                    task_id=task.id,
                    description=task.description or "",
                    updater=updater,
                    turn=turn,
                    stage=f"mid_exec_round_{mid_exec_round}",
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                    execution_flow_tasks=execution_flow_tasks,
                    extra_reason=(
                        detection_reason
                        or f"{NONE_TASK_REASON_CODE}: mid-exec 无可用智能体"
                    ),
                )
                continue
            target_card = name_to_card.get(agent_name)
            if target_card is None:
                logger.warning("[MidExec][Dispatch] no card for agent=%s", agent_name)
                continue
            # ── Self-execution: run locally when agent is self ──
            if agent_name == self._self_planner_agent_name() and skill_runner is not None:
                _mid_self_desc = _short(task.description or "", 120)
                if updater is not None:
                    await self._emit_progress(
                        updater,
                        "mid_exec_self_executing",
                        message=(
                            f"Mid-exec self-executing Task #{task.id} "
                            f"(round {mid_exec_round or '?'}): {_mid_self_desc}"
                        ),
                        status="running",
                        task_id=task.id,
                        extra={
                            "target_sg": agent_name,
                            "task_id": task.id,
                            "mid_exec_round": mid_exec_round,
                            "desc_preview": _mid_self_desc,
                        },
                    )
                logger.info(
                    "[MidExec][SelfExec] executing self task | task=%s round=%s",
                    _mid_self_desc,
                    mid_exec_round,
                )
                result = await self._execute_mid_exec_self_task(
                    task_description=task.description or "",
                    task_id=task.id,
                    skill_runner=skill_runner,
                    metadata=metadata,
                    updater=updater,
                    execution_flow=(upstream_context or {}).get("execution_flow"),
                )
                self_results[agent_name] = result
                # Point F: mid-exec self task Execution Flow emit
                mid_self_ef = ExecutionTask(
                    execution_id=f"mid-self-{task.id}-{agent_name}-t{turn}-r{mid_exec_round}",
                    turn=turn,
                    stage=f"mid_exec_round_{mid_exec_round}",
                    agent=agent_name,
                    role="initiator",
                    task=task.description or "",
                    result=result,
                    reason=detection_reason,
                    parent_execution_id=None,
                    delegated_by=None,
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                execution_flow_tasks.append(mid_self_ef)
                if updater is not None:
                    await self._emit_progress(
                        updater,
                        "mid_exec_self_done",
                        message=(
                            f"Mid-exec self Task #{task.id} done: "
                            f"{_mid_self_desc} ({len(result or '')} chars)"
                        ),
                        status="done",
                        task_id=task.id,
                        extra={
                            "target_sg": agent_name,
                            "task_id": task.id,
                            "mid_exec_round": mid_exec_round,
                            "result_chars": len(result or ""),
                        },
                    )
                    await self._emit_execution_flow(updater, mid_self_ef)
                continue
            if current_hop <= 1:
                delegate_results[agent_name] = NONE_TASK_DESCRIPTION
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

            result, peer_ef_tasks = await self._delegate_to_peer(
                task.description or "",
                target_card,
                user_id, run_id, trace_id,
                hop_remaining=next_hop,
                delegation_chain=new_chain,
                upstream_context=upstream_context,
                execution_hint=peer_hint,
                updater=updater,
            )
            delegate_results[agent_name] = result

            # Point G: mid-exec delegate task Execution Flow emit
            mg_ef_id = f"mid-del-{task.id}-{agent_name}-t{turn}-r{mid_exec_round}"
            parented_peer: list[ExecutionTask] = []
            for pt in peer_ef_tasks:
                if pt.parent_execution_id is None:
                    pt.parent_execution_id = mg_ef_id
                    pt.delegated_by = self._self_planner_agent_name()
                    parented_peer.append(pt)
            mg_ef_task = ExecutionTask(
                execution_id=mg_ef_id,
                turn=turn,
                stage=f"mid_exec_round_{mid_exec_round}",
                agent=agent_name,
                role="delegatee",
                task=task.description or "",
                result=result,
                reason=detection_reason,
                parent_execution_id=None,
                delegated_by=self._self_planner_agent_name(),
                run_id=run_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            execution_flow_tasks.append(mg_ef_task)
            execution_flow_tasks.extend(peer_ef_tasks)
            if updater is not None:
                await self._emit_execution_flow(updater, mg_ef_task)
                await self._reemit_parented_peer_execution_flow(updater, parented_peer)

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
        return delegate_results, self_results, current_hop, execution_flow_tasks

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
    ) -> tuple[str, list["ExecutionTask"]]:
        """Delegate a task to a peer agent via A2A streaming.

        Consume A2A streaming chunks with line-buffering (frames may be split
        across chunk boundaries), relay ``[[DAC_PROGRESS]]`` / ``[[DAC_ANSWER]]``
        frames to ``updater``, and return body text with progress lines stripped.
        Also collects ``[[DAC_EXECUTION_FLOW]]`` frames from the peer and returns
        them as a list of ``ExecutionTask`` objects.

        Returns
        -------
        tuple[str, list[ExecutionTask]]
            ``(response_text, peer_execution_flow_tasks)``.
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
                peer_execution_flow_tasks: list[ExecutionTask] = []

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
                    # Collect peer's Execution Flow frames. Never keep them in body text
                    # that later goes to the LLM or the user-facing answer.
                    if self._is_execution_flow_frame(s):
                        ef_task = ExecutionTask.from_frame(s)
                        if ef_task is not None:
                            peer_execution_flow_tasks.append(ef_task)
                        # Also forward to updater under "execution-flow" artifact
                        if updater is not None:
                            await updater.add_artifact(
                                [TextPart(text=s + "\n")],
                                name="execution-flow",
                            )
                            logger.info(
                                "[ExecutionFlow][Skill] forward peer frame execution_id=%s agent=%s stage=%s",
                                getattr(ef_task, "execution_id", None),
                                getattr(ef_task, "agent", None),
                                getattr(ef_task, "stage", None),
                            )
                        return
                    ef_idx = s.find("[[DAC_EXECUTION_FLOW]] ")
                    if ef_idx >= 0:
                        ef_line = s[ef_idx:]
                        ef_task = ExecutionTask.from_frame(ef_line)
                        if ef_task is not None:
                            peer_execution_flow_tasks.append(ef_task)
                        if updater is not None:
                            await updater.add_artifact(
                                [TextPart(text=ef_line if ef_line.endswith("\n") else ef_line + "\n")],
                                name="execution-flow",
                            )
                            logger.info(
                                "[ExecutionFlow][Skill] forward inline peer frame execution_id=%s agent=%s stage=%s",
                                getattr(ef_task, "execution_id", None),
                                getattr(ef_task, "agent", None),
                                getattr(ef_task, "stage", None),
                            )
                        clean_text = s[:ef_idx].strip()
                        if clean_text:
                            result_segments.append(clean_text)
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
                # Strip any remaining progress / EF lines from the body (belt-and-suspenders)
                full_response = strip_execution_flow_lines(self._strip_progress_lines(full_response))
                logger.info(
                    "[Cross-SG][Delegate] result from %s | chars=%d",
                    target_card.name,
                    len(full_response),
                )
                return full_response, peer_execution_flow_tasks
        except Exception as e:
            logger.error("[Cross-SG][Delegate] failed to delegate to %s: %s", target_card.name, e)
            return f"Delegation failed: {e}", []

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
                agent_name=self._self_planner_agent_name(),
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
                agent_name=self._self_planner_agent_name(),
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

        # ── Detailed add-history trace log ──────────────────────────────
        md = self.metadata if isinstance(self.metadata, dict) else {}
        _log_add_history(
            agent_id=self.agent_id,
            user_id=str(md.get("user_id", "")),
            run_id=str(md.get("run_id", "")),
            skip_history_write=str(md.get("skip_history_write", "")),
            is_delegated=str(md.get("collaboration_delegation", "")),
            delegator=str(md.get("delegator_name", "")),
            query=str(query or ""),
            answer=final_answer_str,
        )
        # ─────────────────────────────────────────────────────────────────

        logger.info(
            "[HistoryFlow] skill-agent add_history user_id=%s agent_id=%s run_id=%s "
            "query_chars=%d answer_chars=%d",
            md.get("user_id", ""),
            self.agent_id,
            md.get("run_id", ""),
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
        run_id = str(md.get("run_id", "") or "")
        propagated = parse_propagated_history(md.get(PROPAGATED_HISTORY_KEY))
        if _normalize_history_turns(propagated.get("turns")):
            if _log_history_turns(propagated.get("turns", []), source="propagated", run_id=run_id):
                logger.info(
                    "[HistoryFlow] skill-agent get_history from propagated | turns=%d",
                    len(propagated.get("turns", [])),
                )
            return history_messages_from_payload(propagated)

        search_items = []
        search_request = SearchHistoryRequest(
            user_id=md.get("user_id", ""),
            run_id=run_id,
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
        if _log_history_turns(payload.get("turns", []), source="data-services API", run_id=run_id):
            logger.info(
                "[HistoryFlow] skill-agent get_history from API | turns=%d",
                payload.get("turn_count", 0),
            )
        return history_messages_from_payload(payload)

    # ------------------------------------------------------------------
    # Summary LLM
    # ------------------------------------------------------------------

    # _summarize_with_evaluation uses the top-level SummaryEvaluationResult
    # Pydantic model (defined near the other tool-call schemas above) as
    # the args_schema for the evaluate_summary StructuredTool.

    def _summary_prompt_agent_meta(self) -> tuple[str, str]:
        """Return (current_agent, agent_role) for summary prompt builders."""
        try:
            current_agent = self._self_planner_agent_name()
        except Exception:
            current_agent = str(getattr(self, "agent_id", "") or "")
        return current_agent, "initiator"

    def _resolve_execution_flow_for_summary(
        self,
        execution_flow_tasks: list | None,
        upstream_context: dict | None,
    ) -> list | None:
        """Prefer explicit EF; fall back to ``upstream_context['execution_flow']``."""
        if execution_flow_tasks:
            return execution_flow_tasks
        if isinstance(upstream_context, dict):
            upstream_ef = upstream_context.get("execution_flow")
            if upstream_ef:
                return upstream_ef
        return None

    async def _summarize_with_evaluation(
        self,
        original_query: str,
        task_results: dict[int, str],
        delegate_results: dict[str, str],
        upstream_context: dict | None = None,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        execution_flow_tasks: list | None = None,
        agent_role: str = "",
        turn: int = 1,
    ) -> SummaryEvaluationResult:
        """Summarize task results AND evaluate whether the answer is sufficient.

        Uses the same ``bind_tools`` / ``invoke_llm_with_tool`` mechanism
        as PlannerAgent and other orchestration methods.  The LLM is
        forced to call ``evaluate_summary``, whose ``args_schema`` is
        :class:`SummaryEvaluationResult`.  This guarantees the output is
        always valid structured data — no regex parsing of free-text
        markers.

        Prompt context is built by :func:`_build_summarize_eval_prompt`
        (Execution Flow markdown, not a JSON dump of ``upstream_context``).

        Returns a :class:`SummaryEvaluationResult` with the answer text
        and the evaluation outcome.
        """
        own_text, del_text = _format_own_and_delegate_text(
            task_results, delegate_results,
        )
        current_agent, default_role = self._summary_prompt_agent_meta()
        system_prompt, human_prompt = _build_summarize_eval_prompt(
            original_query,
            execution_flow_tasks=self._resolve_execution_flow_for_summary(
                execution_flow_tasks, upstream_context,
            ),
            task_results=task_results,
            delegate_results=delegate_results,
            current_agent=current_agent,
            agent_role=agent_role or default_role,
            turn=turn,
        )

        try:
            llm = self._get_orchestration_llm()
            history_messages = await self.get_history()

            messages = [SystemMessage(content=system_prompt)]
            if history_messages:
                messages.extend(history_messages)
            messages.append(HumanMessage(content=human_prompt))

            eval_tool = StructuredTool(
                name="evaluate_summary",
                description=(
                    "输出汇总回答及其充分性评估。"
                    "answer: 回答正文。"
                    "satisfactory: 当前信息是否足以回答问题。"
                    "missing_info: 信息不足时，说明缺少什么信息。"
                    "rationale: 评估决策的一句话理由。"
                    "cot_analysis: 思维链分析过程，包含对问题诉求的拆解、答案覆盖度的逐条核验、"
                    "实质性结果 vs 解释说明的区分、以及最终的客观判断结论。"
                    "gap_obtainable: satisfactory=false 时，缺失信息是否可通过再执行获得。"
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
                agent_name=current_agent,
                query=original_query,
                span_input={
                    "query": original_query,
                    "turn": turn,
                    "system_chars": len(system_prompt or ""),
                    "human_chars": len(human_prompt or ""),
                },
            )

            # 处理 LLM 未调用工具的情况（结构性兜底，不基于内容判断）
            if result_data is None:
                logger.warning(
                    "[SummaryEval] LLM did not call evaluate_summary — falling back to "
                    "satisfactory=False"
                )
                return SummaryEvaluationResult(
                    answer="汇总阶段：LLM 未调用评估工具，无法生成有效回答，请重试。",
                    satisfactory=False,
                    missing_info="LLM 未调用 evaluate_summary 工具，需要重新执行汇总。",
                    rationale="LLM did not call evaluate_summary tool",
                    cot_analysis="LLM 未调用 evaluate_summary 工具，无法进行思维链分析。",
                )

            # 提取字段，仅做空值处理，不做任何基于内容的规则判断
            answer = result_data.get("answer", "").strip()
            satisfactory = bool(result_data.get("satisfactory", False))
            missing_info = result_data.get("missing_info", "").strip()
            rationale = result_data.get("rationale", "").strip()
            # gap_obtainable: only meaningful when satisfactory=False.
            # Default True (assume retryable) so a missing/failed field never
            # silently suppresses a legitimate retry.
            try:
                gap_obtainable = bool(result_data.get("gap_obtainable", True))
            except (TypeError, ValueError):
                gap_obtainable = True
            if satisfactory:
                gap_obtainable = True

            # 结构兜底：若 answer 为空，即使 LLM 判为 true 也无法使用，强制改为不充分
            if not answer:
                satisfactory = False
                missing_info = missing_info or "汇总结果为空，缺少实质回答内容。"
                rationale = rationale or "answer 为空，无法提供有效回答"

            # 结构兜底：若 satisfactory=False 但 missing_info 为空，补充默认说明
            if not satisfactory and not missing_info:
                missing_info = "当前信息不足以完整回答用户问题，需要补充获取相关数据。"

            # 直接返回 LLM 的评估结果，不再进行任何一致性修正或内容检查
            return SummaryEvaluationResult(
                answer=answer,
                satisfactory=satisfactory,
                missing_info=missing_info,
                rationale=rationale,
                gap_obtainable=gap_obtainable,
                cot_analysis=result_data.get("cot_analysis", ""),
            )

        except Exception as e:
            logger.error("[SummaryEval] LLM summarization failed: %s", e)
            return SummaryEvaluationResult(
                answer=(
                    "由于汇总阶段出错，未能生成综合答案。以下为各协作 SG 返回的原始结果：\n\n"
                    f"{own_text}\n\n"
                    f"{del_text}"
                ),
                satisfactory=False,
                missing_info=f"汇总阶段发生异常：{e}，需要重试或人工介入。",
                rationale=f"LLM call failed: {e}",
                cot_analysis=f"LLM 调用失败，无法进行思维链分析：{e}",
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
        execution_flow_tasks: list | None = None,
        agent_role: str = "",
    ) -> str:
        """Use LLM to summarize all task results into a final answer.

        Behaviour is governed by a 3-layer decision tree (highest priority first):

        1. ``SUMMARIZE_ENABLED=false`` → **passthrough** (force-off for all agents)
        2. ``agent_role == "delegatee"`` → **passthrough** (delegated never summarizes)
        3. initiator (summarization enabled) → **LLM summarization**
           - ``SUMMARIZE_CUSTOM_PROMPT`` non-empty → custom system prompt
           - ``SUMMARIZE_CUSTOM_PROMPT`` empty → default ``SUMMARIZE_CORE_PRINCIPLES``

        Prompt context is built by :func:`_build_agent_summarize_prompt`
        (Execution Flow markdown, not a JSON dump of ``upstream_context``).
        """
        own_text, del_text = _format_own_and_delegate_text(
            task_results, delegate_results,
        )
        # Passthrough uses raw results *without* [Task#N] prefix (which is
        # only intended as LLM-context scaffolding, never user-facing output).
        # Also filter out system placeholder values (NONE tasks, skipped
        # dependent tasks) so they don't leak to users.
        _SYS_PLACEHOLDERS = {NONE_TASK_UNASSIGNED_RESULT, DEPENDENT_TASK_SKIP_DESCRIPTION}
        passthrough = "\n\n".join(
            r for r in (task_results or {}).values()
            if r and r not in _SYS_PLACEHOLDERS
        )
        if delegate_results:
            del_passthrough = "\n\n".join(
                r for r in delegate_results.values()
                if r and r not in _SYS_PLACEHOLDERS
            )
            if del_passthrough:
                passthrough += "\n\n" + del_passthrough

        # ── Debug: log every result value being joined into passthrough ──
        _tr_values = [v for v in (task_results or {}).values() if v]
        _tr_keys = list((task_results or {}).keys())
        _dr_values = [v for v in (delegate_results or {}).values() if v]
        _dr_keys = list((delegate_results or {}).keys())
        logger.info(
            "[Summary] PASSTHROUGH-DEBUG | "
            "enabled=%s role=%s tr_count=%d tr_keys=%s "
            "dr_count=%d dr_keys=%s passthrough_len=%d",
            self.summarize_enabled,
            agent_role,
            len(_tr_values),
            _tr_keys,
            len(_dr_values),
            _dr_keys,
            len(passthrough),
        )
        for i, v in enumerate(_tr_values):
            _dup = ""
            if _tr_values.count(v) > 1:
                _dup = " (DUPLICATE — same value appears %d times total)" % _tr_values.count(v)
            logger.info(
                "[Summary] PASSTHROUGH-DEBUG tr[%d/%d] len=%d hash=%s%s preview=%s",
                i + 1,
                len(_tr_values),
                len(v),
                hash(v),
                _dup,
                v[:300],
            )
        if _tr_values and len(set(_tr_values)) < len(_tr_values):
            logger.warning(
                "[Summary] PASSTHROUGH-DEBUG DUPLICATE DETECTED | "
                "unique=%d total=%d — passthrough will contain repeated content",
                len(set(_tr_values)),
                len(_tr_values),
            )

        # ── Rule 1: SUMMARIZE_ENABLED force-off → passthrough ──
        if not self.summarize_enabled:
            logger.info(
                "[Summary] passthrough (SUMMARIZE_ENABLED=false) | "
                "own_chars=%d del_chars=%d agent_role=%s",
                len(own_text), len(del_text), agent_role,
            )
            return passthrough

        # ── Rule 2: delegatee never summarizes ──
        if agent_role == "delegatee":
            logger.info(
                "[Summary] passthrough (delegatee) | "
                "own_chars=%d del_chars=%d",
                len(own_text), len(del_text),
            )
            return passthrough

        # ── Rule 3: initiator (summarization enabled) → LLM summarization ──
        # Summarize regardless of whether delegation actually occurred.
        logger.info(
            "[Summary] LLM summarize (initiator) | "
            "own_chars=%d del_chars=%d custom_prompt=%s",
            len(own_text), len(del_text),
            bool(self.summarize_prompt),
        )

        current_agent, default_role = self._summary_prompt_agent_meta()
        system_prompt, human_prompt = _build_agent_summarize_prompt(
            original_query,
            execution_flow_tasks=self._resolve_execution_flow_for_summary(
                execution_flow_tasks, upstream_context,
            ),
            task_results=task_results,
            delegate_results=delegate_results,
            current_agent=current_agent,
            agent_role=agent_role or default_role,
            custom_system_prompt=self.summarize_prompt,
        )

        try:
            llm = self._get_orchestration_llm()
            history_messages = await self.get_history()

            messages = [SystemMessage(content=system_prompt)]
            if history_messages:
                messages.extend(history_messages)
            messages.append(HumanMessage(content=human_prompt))

            # Same Langfuse path as invoke_llm_with_tool / _ainvoke_plain_plan:
            # get_client() + a fresh CallbackHandler at call time. The module-level
            # ``langfuse`` / ``langfuse_handler`` are created at import and do not
            # attach LangChain generations to the current span.
            from langfuse.langchain import CallbackHandler as _LangfuseCb
            from langfuse import get_client as _get_langfuse_client

            _handler = _LangfuseCb()
            _langfuse_client = _get_langfuse_client()
            _span_name = (
                f"skill-agent-summarize [{current_agent}]"
                if current_agent else "skill-agent-summarize"
            )
            _t0 = _time.monotonic()
            answer = None
            final_text = ""
            try:
                with _langfuse_client.start_as_current_span(
                    name=_span_name,
                    trace_context={"trace_id": trace_id} if trace_id else {},
                    input={
                        "query": original_query,
                        "system_chars": len(system_prompt or ""),
                        "human_chars": len(human_prompt or ""),
                    },
                ) as span:
                    if user_id or run_id:
                        span.update_trace(
                            user_id=user_id or None,
                            session_id=run_id or None,
                        )
                    answer = await llm.ainvoke(
                        messages,
                        config={"callbacks": [_handler]},
                    )
                    final_text = str(getattr(answer, "content", "") or "").strip()
                    span.update(output={"answer": final_text[:2000]})
                await safe_langfuse_flush(_langfuse_client)
            except Exception as exc:
                logger.warning(
                    "[Summary] Langfuse tracing/invoke failed (%s: %s); "
                    "retrying plain ainvoke",
                    type(exc).__name__,
                    exc,
                )
                if answer is None:
                    answer = await llm.ainvoke(messages)
                    final_text = str(getattr(answer, "content", "") or "").strip()
            logger.info(
                " === skill-agent-summarize elapsed_ms=%s answer_chars=%s",
                round((_time.monotonic() - _t0) * 1000),
                len(final_text),
            )
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
        _md = context.metadata if isinstance(context.metadata, dict) else {}
        logger.info(
            "[Capability] request received | agent=%s run_id=%s query=%s",
            self.agent_id,
            _md.get("run_id") or "",
            (query or "")[:150],
        )
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        md = _md

        card = self.agent_card
        agent_name = card.name if card else "SkillAgent"
        agent_description = (card.description if card else "") or ""
        agent_url = (card.url if card else "") or ""

        agent_skills_text = _format_skills_for_capability_check(card.skills if card else None)

        history_text = _history_text_from_metadata(md)
        _cc_start = _time.monotonic()
        leaf_path = [agent_name]
        threshold = capability_chain.get_threshold()

        if not (card and card.skills):
            # Runtime fact, not a capability judgement: nothing is loaded, so
            # there is nothing to evaluate. Skip the LLM entirely.
            check_response = sg_broadcast.CapabilityCheckResponse(
                can_handle=False,
                confidence=0.0,
                reason="No skills loaded; nothing to evaluate.",
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": 0.0, "alias": _path_to_alias(leaf_path)}],
                can_contribute=False,
                contribution="",
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
                score_version=capability_chain.SCORE_VERSION,
                evidence_grade="D",
                threshold=threshold,
                handle_score=0.0,
                steps=[],
                contributing_steps=[],
            )
            await self._emit_capability_check_response(updater, task, md, query, check_response)
            return

        try:
            max_attempts = int(os.getenv("CAPABILITY_CHECK_MAX_ATTEMPTS", "3"))
            llm = self._get_orchestration_llm()

            # ═══ Phase 1: Domain overlap check ═══
            domain_prompt = DOMAIN_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                history=history_text,
                query=query,
            )
            domain_result: Optional[capability_chain.DomainCheckResult] = None
            nudge: Optional[HumanMessage] = None

            for attempt in range(1, max_attempts + 1):
                logger.info(
                    "[Capability][Domain] llm_invoke attempt=%d/%d agent=%s",
                    attempt, max_attempts, agent_name,
                )
                attempt_messages = (
                    [HumanMessage(content=domain_prompt)]
                    if nudge is None
                    else [HumanMessage(content=domain_prompt), AIMessage(content=""), nudge]
                )
                try:
                    answer = await llm.ainvoke(attempt_messages)
                except Exception as exc:
                    logger.warning(
                        "[Capability][Domain] attempt %d: LLM invoke failed: %s: %s",
                        attempt, type(exc).__name__, exc,
                    )
                    nudge = HumanMessage(content="上一次调用失败。请只输出包含 domain_verdict 和 reason 的 JSON。")
                    continue

                result_data = _parse_json_output(answer)
                if result_data is None:
                    raw_text = (
                        "".join(
                            [str(p.get("text", "")) if isinstance(p, dict) else str(p)
                             for p in (getattr(answer, "content", None) or [])]
                        ) if isinstance(getattr(answer, "content", None), list)
                        else getattr(answer, "content", "") or ""
                    )
                    preview = (raw_text or str(answer))[:400]
                    logger.warning(
                        "[Capability][Domain] attempt %d: invalid JSON, nudging | preview=%s",
                        attempt, preview,
                    )
                    nudge = HumanMessage(
                        content='输出无法解析。请只输出 JSON：{"domain_verdict": "...", "reason": "..."}'
                    )
                    continue

                try:
                    domain_result = capability_chain.DomainCheckResult.model_validate(result_data)
                except Exception as exc:
                    logger.warning(
                        "[Capability][Domain] attempt %d: parse failed: %s", attempt, exc,
                    )
                    nudge = HumanMessage(
                        content=f"JSON 解析成功但字段类型不符合 schema：{exc}。请修正后重新输出。"
                    )
                    continue

                logger.info(
                    "[Capability][Domain] verdict=%s agent=%s",
                    domain_result.domain_verdict, agent_name,
                )
                break

            if domain_result is None:
                raise ValueError(
                    f"Domain check failed to produce valid JSON after {max_attempts} attempts."
                )

            # ── Domain mismatch → return cannot_handle immediately ──
            if domain_result.domain_verdict == "none":
                _latency = int((_time.monotonic() - _cc_start) * 1000)
                cap_log = capability_chain.format_capability_chain_md(
                    result=capability_chain.CapabilityChainResult(
                        steps=[],
                        evidence_grade="D",
                        contribution="",
                        missing_requirements=[],
                        risks=[],
                        reason=domain_result.reason,
                    ),
                    agg=capability_chain.AggregatedCapability(
                        can_handle=False,
                        can_contribute=False,
                        confidence=0.0,
                        handle_score=0.0,
                        threshold=threshold,
                    ),
                    agent_name=agent_name,
                    query=query,
                    domain_verdict=domain_result.domain_verdict,
                    latency_ms=_latency,
                )
                logger.info("\n%s", cap_log)
                check_response = sg_broadcast.CapabilityCheckResponse(
                    can_handle=False,
                    confidence=0.0,
                    reason=domain_result.reason,
                    agent_name=agent_name,
                    agent_url=agent_url,
                    route_path=leaf_path,
                    route_paths=[{"path": leaf_path, "confidence": 0.0, "alias": _path_to_alias(leaf_path)}],
                    can_contribute=False,
                    contribution="",
                    execution_strategy="single",
                    collaboration_agents=[],
                    collaboration_roles={},
                    collaboration_paths=[],
                    member_results=[],
                    degraded=False,
                    unavailable_count=0,
                    missing_requirements=[],
                    execution_hint={},
                    latency_ms=_latency,
                    score_version=capability_chain.SCORE_VERSION,
                    evidence_grade="D",
                    threshold=threshold,
                    handle_score=0.0,
                    steps=[],
                    contributing_steps=[],
                    risks=[],
                    domain_verdict=domain_result.domain_verdict,
                    has_external_dependency=False,
                )
                await self._emit_capability_check_response(updater, task, md, query, check_response)
                return

            # ═══ Phase 2: Capability chain decomposition ═══
            domain_info = (
                f"domain_verdict: {domain_result.domain_verdict}\n"
                f"reason: {domain_result.reason}"
            )
            chain_prompt = SKILL_CAPABILITY_CHECK_PROMPT.format(
                agent_name=agent_name,
                agent_description=agent_description,
                agent_skills=agent_skills_text,
                history=history_text,
                query=query,
                domain_info=domain_info,
            )
            chain_result: Optional[CapabilityChainResult] = None
            nudge = None

            for attempt in range(1, max_attempts + 1):
                logger.info(
                    "[Capability][JSON] llm_invoke attempt=%d/%d agent=%s",
                    attempt, max_attempts, agent_name,
                )
                attempt_messages = (
                    [HumanMessage(content=chain_prompt)]
                    if nudge is None
                    else [HumanMessage(content=chain_prompt), AIMessage(content=""), nudge]
                )
                try:
                    answer = await llm.ainvoke(attempt_messages)
                except Exception as exc:
                    logger.warning(
                        "[Capability][JSON] attempt %d: LLM invoke failed: %s: %s",
                        attempt, type(exc).__name__, exc,
                    )
                    nudge = HumanMessage(
                        content=(
                            "上一次调用失败。请重新输出一个完整的 JSON 对象，"
                            "字段必须包含 steps、evidence_grade、contribution、"
                            "missing_requirements、risks、reason。"
                        )
                    )
                    continue

                result_data = _parse_json_output(answer)
                if result_data is None:
                    raw_text = (
                        "".join(
                            [
                                str(p.get("text", "")) if isinstance(p, dict) else str(p)
                                for p in (getattr(answer, "content", None) or [])
                            ]
                        ) if isinstance(getattr(answer, "content", None), list) else getattr(answer, "content", "") or ""
                    )
                    preview = (raw_text or str(answer))[:400]
                    logger.warning(
                        "[Capability][JSON] attempt %d: invalid JSON, nudging | preview=%s",
                        attempt, preview,
                    )
                    nudge = HumanMessage(
                        content=(
                            "输出无法解析为合法 JSON。请只输出一个 JSON 对象，"
                            "字段包含 steps（步骤数组）、evidence_grade（A/B/C/D）、"
                            "contribution（贡献说明，不能贡献时为空字符串）、"
                            "missing_requirements（缺失项列表，无缺失时为 []）、"
                            "risks（风险列表，无风险时为 []）、"
                            "reason（结构化理由）。"
                            "每个步骤的 RatioCheck 必须同时给出 required、matched、ratio、evidence_strength。"
                        )
                    )
                    continue

                # Strip domain_verdict if LLM still injects it (Phase 2 prompt says not to)
                result_data.pop("domain_verdict", None)

                try:
                    chain_result = capability_chain.parse_chain_result(result_data)
                except Exception as exc:
                    preview = json.dumps(result_data, ensure_ascii=False, default=str)[:400]
                    logger.warning(
                        "[Capability][JSON] attempt %d: parse_chain_result failed: %s | data=%s",
                        attempt, exc, preview,
                    )
                    nudge = HumanMessage(
                        content=(
                            f"JSON 解析成功，但字段类型不符合 schema：{exc}。\n"
                            "请严格按照以下 schema 修正后重新输出：\n"
                            '- steps 是数组，每项的 inputs 是对象数组 [{"name":"...","source":"..."}]，不能是单个对象\n'
                            '- outputs 是字符串数组 ["..."]，不能是对象\n'
                            '- constraints 是字符串数组 ["..."]，不能是对象\n'
                            "- input_match/data_coverage/result_match/constraint_satisfaction 是对象 "
                            '{"required":["..."],"matched":["..."],"ratio":0.0}，不是数组\n'
                            "- operation_capability 必须是数字 1.0、0.7 或 0\n"
                        )
                    )
                    continue

                logger.info(
                    "[Capability][JSON] SELECTED attempt=%d steps=%d",
                    attempt, len(chain_result.steps),
                )
                break

            if chain_result is None:
                raise ValueError(
                    f"Capability check failed to produce valid JSON after {max_attempts} attempts."
                )

            agg = capability_chain.aggregate(chain_result, threshold=threshold)
            can_handle, can_contribute = _normalize_capability_result(
                {"can_handle": agg.can_handle, "can_contribute": agg.can_contribute}
            )
            conf = agg.confidence
            reason = str(chain_result.reason or "").strip()[:2000]

            _latency = int((_time.monotonic() - _cc_start) * 1000)
            cap_log = capability_chain.format_capability_chain_md(
                result=chain_result,
                agg=agg,
                agent_name=agent_name,
                query=query,
                domain_verdict=domain_result.domain_verdict,
                latency_ms=_latency,
            )
            logger.info("\n%s", cap_log)

            check_response = sg_broadcast.CapabilityCheckResponse(
                can_handle=can_handle,
                confidence=conf,
                reason=reason,
                agent_name=agent_name,
                agent_url=agent_url,
                route_path=leaf_path,
                route_paths=[{"path": leaf_path, "confidence": conf, "alias": _path_to_alias(leaf_path)}],
                can_contribute=can_contribute,
                contribution=agg.contribution,
                execution_strategy="single",
                collaboration_agents=[],
                collaboration_roles={},
                collaboration_paths=[],
                member_results=[],
                degraded=False,
                unavailable_count=0,
                missing_requirements=agg.missing_requirements,
                execution_hint={},
                latency_ms=_latency,
                score_version=capability_chain.SCORE_VERSION,
                evidence_grade=chain_result.evidence_grade,
                threshold=agg.threshold,
                handle_score=agg.handle_score,
                steps=agg.steps_payload(chain_result),
                contributing_steps=agg.contributing_steps,
                risks=list(chain_result.risks or []),
                domain_verdict=domain_result.domain_verdict,
                has_external_dependency=agg.has_external_dependency,
            )
        except Exception as e:
            logger.error("Capability check failed: %s", e, exc_info=True)
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
                score_version=capability_chain.SCORE_VERSION,
                threshold=threshold,
            )

        await self._emit_capability_check_response(updater, task, md, query, check_response)

    async def _emit_capability_check_response(
        self,
        updater: TaskUpdater,
        task: Any,
        md: dict,
        query: str,
        check_response: "sg_broadcast.CapabilityCheckResponse",
    ) -> None:
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
        final routing decision.  The agent runs :meth:`make_plan` against
        **this agent only** (own AgentCard + optional LocalSkill).  Peer
        SGs are not loaded: routing already filtered candidates, and
        PreMakePlan is a self-capability probe, not a collaboration plan.
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
            await self._ensure_skill_runner()
            local_card = self.agent_card
            all_cards = [local_card] if local_card else []
            all_cards = self._maybe_append_local_skill_card(all_cards)
            logger.info(
                "[PreMakePlan] local-only planner pool | agent=%s cards=%s",
                self.agent_id,
                [getattr(c, "name", "") for c in all_cards],
            )

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

        # ── Debug: print full metadata on execute entry (after fast-paths) ──
        logger.info(
            "[ExecuteEntry] metadata dump | agent_id=%s skip_history_write=%s "
            "collaboration_delegation=%s delegator_name=%s hop_remaining=%s "
            "delegation_chain=%s history_owner_agent_id=%s run_id=%s "
            "user_id=%s full_metadata=%s",
            self.agent_id,
            metadata.get("skip_history_write"),
            metadata.get("collaboration_delegation"),
            metadata.get("delegator_name"),
            metadata.get("hop_remaining"),
            metadata.get("delegation_chain"),
            metadata.get("history_owner_agent_id"),
            metadata.get("run_id"),
            metadata.get("user_id"),
            json.dumps(metadata, ensure_ascii=False, default=str),
        )
        # ─────────────────────────────────────────────────────────────────

        user_id = str(metadata.get("user_id", ""))
        run_id = str(metadata.get("run_id", ""))
        trace_id = str(metadata.get("trace_id", ""))
        skip_history_write = bool(metadata.get("skip_history_write", False))
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

        # ── DAG banner: log enforcement status at collaboration entry ──
        _dag_enabled = self._dag_enforcement_enabled()
        self_name = self._self_planner_agent_name()
        if _dag_enabled:
            self._log_dag_startup(
                is_delegated=is_delegated,
                self_name=self_name,
                chain=delegation_chain,
            )
        else:
            logger.info(
                "[DAG] DAG enforcement DISABLED (CROSS_SG_ENFORCE_DAG=false) | "
                "chain=%s self=%s",
                delegation_chain,
                self_name,
            )

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

        # ── DAG Layer 1: cycle detection — abort if self already in chain ──
        if _dag_enabled and self_name in delegation_chain:
            self._log_dag_event(
                "CYCLE_DETECTED",
                chain=delegation_chain,
                self_name=self_name,
                detail=f"self={self_name} 已存在于委派链中！",
            )
            logger.warning(
                "[Cross-SG][DAG] cycle detected! self=%s already in chain=%s, aborting collaboration",
                self_name,
                delegation_chain,
            )
            return {
                "answer": "",
                "tasks": [],
                "reason": "dag_cycle_detected",
                "status": "fail",
            }

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
        all_task_results, delegate_results, _remaining_hop, _plan_meta, execution_flow_tasks = await self._execute_plan_and_mid_exec(
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
            execution_flow_tasks=execution_flow_tasks,
            agent_role="delegatee" if is_delegated else "initiator",
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
        if skip_history_write:
            logger.info(
                "[HistoryFlow] skill-agent history-skip skip_history_write=%s "
                "self=%s run_id=%s",
                skip_history_write,
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

        # ── Log Execution Flow ──
        # 将上游 EF 和本层 EF 分开渲染，避免混合导致层级混淆。
        if execution_flow_tasks:
            role = "delegatee" if is_delegated else "initiator"
            local_ef = list(execution_flow_tasks[upstream_ef_count:])
            upstream_ef_for_log = list(execution_flow_tasks[:upstream_ef_count])

            if upstream_ef_for_log:
                _upstream_agent = upstream_ef_for_log[0].agent if isinstance(upstream_ef_for_log[0], ExecutionTask) else ""
                upstream_md = render_execution_flow_md(
                    upstream_ef_for_log,
                    agent=_upstream_agent,
                    role="initiator",
                )
                logger.info(
                    "[ExecutionFlow] run_id=%s trace_id=%s user_id=%s\n"
                    "─── 上游执行流水账 ───\n%s",
                    run_id, trace_id, user_id, upstream_md,
                )

            if local_ef:
                local_md = render_execution_flow_md(
                    local_ef,
                    agent=self._self_planner_agent_name(),
                    role=role,
                    current_agent=self._self_planner_agent_name(),
                )
                logger.info(
                    "[ExecutionFlow] run_id=%s trace_id=%s user_id=%s\n"
                    "─── 本层执行流水账 ───\n%s",
                    run_id, trace_id, user_id, local_md,
                )

            if not upstream_ef_for_log and not local_ef:
                logger.info("[ExecutionFlow] no execution flow tasks recorded (run_id=%s)", run_id)

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
        prior_delegate_results: dict[str, str] | None = None,
        group_memory: str | None = None,
        turn: int = 1,
    ) -> tuple[dict[int, str], dict[str, str], int, list[dict], list["ExecutionTask"]]:
        """Execute Steps 3-5 (plan → execute tasks → mid-exec loop).

        Extracted from :meth:`execute` so that subclasses can wrap this in a
        turn-based retry loop.  When *failure_context* is non-empty it is
        injected into the planner's ``group_memory`` so the next turn can
        adjust its decomposition strategy.  When *prior_delegate_results* is
        provided, it is merged into the mid-exec detection ``delegated_results``
        so the detection LLM is aware of previous-turn delegation failures.

        Returns
        -------
        tuple[dict[int, str], dict[str, str], int, list[dict], list[ExecutionTask]]
            ``(all_task_results, delegate_results, remaining_hop, plan_task_meta, execution_flow_tasks)``.
        """
        # ------------------------------------------------------------------
        # 0.  Execution Flow tracking
        # ------------------------------------------------------------------
        execution_flow_tasks: list[ExecutionTask] = []

        # ── 接收上游 Execution Flow ──
        # 被委派 Agent 需要看到上游的完整执行流水账，以便理解上下文
        # 和关联键来源。上游的 Execution Flow 以 dict 列表形式通过
        # upstream_context["execution_flow"] 传入。
        upstream_ef_count = 0  # 记录上游 EF 数量，用于最终日志分离渲染
        upstream_ef = upstream_context.get("execution_flow")
        if upstream_ef and isinstance(upstream_ef, list):
            for ef_dict in upstream_ef:
                if isinstance(ef_dict, dict):
                    try:
                        execution_flow_tasks.append(ExecutionTask.from_dict(ef_dict))
                    except Exception:
                        logger.warning(
                            "[ExecutionFlow] failed to parse upstream EF task: %s",
                            ef_dict.get("execution_id", "?"),
                        )
            if execution_flow_tasks:
                upstream_ef_count = len(execution_flow_tasks)
                logger.info(
                    "[ExecutionFlow] received upstream EF | agent=%s turn=%d count=%d",
                    self._self_planner_agent_name(), turn, upstream_ef_count,
                )
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

        execution_hint = self._validated_execution_hint(metadata, query)

        if group_memory is None:
            # Legacy path (single-shot executor): build group_memory from
            # upstream_context via _enrich_group_memory_with_upstream.
            base_group_memory = await self._get_memory(query)
            group_memory = self._enrich_group_memory_with_upstream(
                upstream_context=upstream_context,
                base_group_memory=base_group_memory,
            )
            if execution_hint:
                note = self._execution_hint_memory_note(execution_hint)
                group_memory = f"{group_memory}\n\n{note}".strip() if group_memory else note
            if failure_context:
                group_memory = f"{group_memory}\n\n{failure_context}" if group_memory else failure_context
        else:
            # Turn loop path: caller already assembled group_memory
            # (including base_group_memory, turn context, failure_context).
            # Append execution_hint if available.
            if execution_hint:
                note = self._execution_hint_memory_note(execution_hint)
                group_memory = f"{group_memory}\n\n{note}".strip()

        logger.info(
            "[Orchestration] group_memory prepared | total_chars=%d",
            len(group_memory or ""),
        )

        # ── DAG Layer 2: filter planner agent pool to exclude chain agents ──
        if self._dag_enforcement_enabled() and delegation_chain:
            chain_set = set(delegation_chain)
            _orig_peer_count = len(collab_names)
            _orig_card_count = len(all_cards)
            _removed_cards = sorted(
                getattr(c, "name", "") for c in all_cards
                if getattr(c, "name", "") in chain_set
            )
            all_cards = [
                c for c in all_cards
                if getattr(c, "name", "") not in chain_set
            ]
            collab_names = {n for n in collab_names if n not in chain_set}
            if len(collab_names) < _orig_peer_count:
                self._log_dag_filter(
                    "PLANNER_POOL",
                    chain=delegation_chain,
                    before=_orig_card_count,
                    after=len(all_cards),
                    removed=_removed_cards,
                    kept=sorted(collab_names),
                )

        planner = self._get_planner()
        plan = await planner.make_plan(query, all_cards, group_memory=group_memory)

        # Count local vs delegate tasks for display
        own_tasks = [t for t in plan.tasks if (t.agent or "").strip() in own_names]
        delegation_tasks = [t for t in plan.tasks if (t.agent or "").strip() in collab_names]

        plan_lines = [
            f"Plan ready: {len(own_tasks)} local tasks, {len(delegation_tasks)} delegate tasks"
        ]
        for t in plan.tasks:
            agent_nm = (t.agent or "").strip() or "?"
            desc = ((t.description or "").replace("\n", " ").strip())[:140]
            deps = (
                f"(depends on: [{', '.join(str(d) for d in t.depends_on)}]) "
                if t.depends_on
                else ""
            )
            plan_lines.append(f"  • #{t.id} {deps}agent='{agent_nm}' | {desc}")

        await self._emit_progress(
            updater,
            "plan_ready",
            message="\n".join(plan_lines),
            status="running",
            extra={
                "task_count": len(plan.tasks),
                "own_task_count": len(own_tasks),
                "delegation_count": len(delegation_tasks),
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
        # Extract task metadata for the caller (turn loop) to build
        # meaningful executed_tasks entries for the next turn's planner.
        plan_task_meta: list[dict] = [
            {
                "id": t.id,
                "description": t.description or "",
                "agent": t.agent or "",
            }
            for t in plan.tasks
        ]
        own_results: dict[int, str] = {}
        delegate_results: dict[str, str] = {}
        all_task_results: dict[int, str] = {}
        self._tasks_status_list: list[dict] = []

        for task_item in plan.tasks:
            agent_name = (task_item.agent or "").strip()

            # NONE is a planner protocol ("no capable agent"), not a silent skip.
            if agent_name.upper() == "NONE":
                await self._record_none_execution_task(
                    task_id=task_item.id,
                    description=task_item.description or "",
                    updater=updater,
                    turn=turn,
                    stage="pre_exec",
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                    execution_flow_tasks=execution_flow_tasks,
                    all_task_results=all_task_results,
                )
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
                    progress_callback=lambda frame: updater.add_artifact(
                        [TextPart(text=frame)], name="progress"
                    ),
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

                # Point A: own task Execution Flow emit
                own_ef_task = ExecutionTask(
                    execution_id=f"own-{task_item.id}-{agent_name}-t{turn}",
                    turn=turn,
                    stage="pre_exec",
                    agent=agent_name,
                    role="initiator",
                    task=task_query,
                    result=result,
                    reason="" if not is_fail else f"Local execution failed",
                    parent_execution_id=None,
                    delegated_by=None,
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                execution_flow_tasks.append(own_ef_task)
                await self._emit_execution_flow(updater, own_ef_task)

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
                # ── 传递 Execution Flow 到下游 Agent ──
                # 将被委派方需要看到上游的完整执行流水账，以便理解上下文。
                _ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
                               for t in execution_flow_tasks]
                _ctx: dict[str, Any] = {
                    "executed_tasks": _completed_tasks_context,
                    "upstream_context": upstream_context,
                    "execution_flow": _ef_for_ctx,
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
                    "[Cross-SG][PreExecDelegation] delegating | task_id=%d target_sg=%s hop=%d chain=%s desc_preview=%s ef_tasks=%d",
                    task_item.id,
                    agent_name,
                    _next_hop,
                    _new_chain,
                    (task_query or "")[:100],
                    len(_ef_for_ctx),
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
                        f"executed_tasks (count={len(_completed_tasks_context)})"
                    ),
                    metadata_extra={
                        "delegation_chain": _new_chain,
                        "hop_remaining": _next_hop,
                        "task_description": (task_query or "")[:200],
                    },
                )

                result, peer_ef_tasks = await self._delegate_to_peer(
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
                # Merge peer's Execution Flow — only set parent_execution_id
                # on the peer's root tasks (those without a parent already).
                pre_ef_id = f"pre-{task_item.id}-{agent_name}-t{turn}"
                parented_peer: list[ExecutionTask] = []
                for pt in peer_ef_tasks:
                    if pt.parent_execution_id is None:
                        pt.parent_execution_id = pre_ef_id
                        pt.delegated_by = self._self_planner_agent_name()
                        parented_peer.append(pt)
                pre_ef_task = ExecutionTask(
                    execution_id=pre_ef_id,
                    turn=turn,
                    stage="pre_exec",
                    agent=agent_name,
                    role="delegatee",
                    task=task_query,
                    result=result,
                    reason="Pre-exec delegation",
                    parent_execution_id=None,
                    delegated_by=self._self_planner_agent_name(),
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                execution_flow_tasks.append(pre_ef_task)
                execution_flow_tasks.extend(peer_ef_tasks)
                # Emit wrapper first, then rewrite parented peer roots so the UI
                # tree is wrapper → nested internal execution (not two flat roots).
                await self._emit_execution_flow(updater, pre_ef_task)
                await self._reemit_parented_peer_execution_flow(updater, parented_peer)
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
            return all_task_results, delegate_results, current_hop, plan_task_meta, execution_flow_tasks

        await self._emit_progress(
            updater,
            "mid_exec_started",
            message="Checking if local results are sufficient...",
            status="running",
        )

        max_mid_exec_rounds = int(os.getenv("CROSS_SG_MID_EXEC_ROUNDS", "5"))
        mid_exec_round = 0
        collaborator_cards_list = [
            c for c in all_cards if getattr(c, "name", "") in collab_names
        ]

        # ── DAG Layer 3a: filter initial collaborator cards to exclude chain agents ──
        if self._dag_enforcement_enabled() and delegation_chain and collaborator_cards_list:
            _dag_before = len(collaborator_cards_list)
            _dag_chain_set = set(delegation_chain)
            _dag_removed = sorted(
                getattr(c, "name", "") for c in collaborator_cards_list
                if getattr(c, "name", "") in _dag_chain_set
            )
            collaborator_cards_list = [
                c for c in collaborator_cards_list
                if getattr(c, "name", "") not in _dag_chain_set
            ]
            if _dag_removed:
                self._log_dag_filter(
                    "MIDEXEC_CARDS",
                    chain=delegation_chain,
                    before=_dag_before,
                    after=len(collaborator_cards_list),
                    removed=_dag_removed,
                    kept=sorted(getattr(c, "name", "") for c in collaborator_cards_list),
                )

        # Track SGs that returned empty/bad results — exclude them from
        # re-delegation in subsequent rounds to avoid infinite ping-pong
        # between the same pair of agents.
        _exhausted_sgs: set[str] = set()

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
                # ── DAG Layer 3b: filter broadcast-loaded cards to exclude chain agents ──
                if self._dag_enforcement_enabled() and delegation_chain and collaborator_cards_list:
                    _dag_before = len(collaborator_cards_list)
                    _dag_chain_set = set(delegation_chain)
                    _dag_removed = sorted(
                        getattr(c, "name", "") for c in collaborator_cards_list
                        if getattr(c, "name", "") in _dag_chain_set
                    )
                    collaborator_cards_list = [
                        c for c in collaborator_cards_list
                        if getattr(c, "name", "") not in _dag_chain_set
                    ]
                    if _dag_removed:
                        self._log_dag_filter(
                            "MIDEXEC_BROADCAST",
                            chain=delegation_chain,
                            before=_dag_before,
                            after=len(collaborator_cards_list),
                            removed=_dag_removed,
                            kept=sorted(getattr(c, "name", "") for c in collaborator_cards_list),
                        )
                if not collaborator_cards_list:
                    logger.info("[MidExec] no broadcast SG candidates, exiting loop")
                    await self._emit_progress(
                        updater,
                        "mid_exec_no_candidates",
                        message="Mid-exec: 未找到可用的远程智能体，无法委派补充数据",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "no_broadcast_candidates",
                        },
                    )
                    break

            # ── Include self in collaborator pool so detection LLM can recommend
            # self-execution when new data (e.g. user-id mapping) is acquired via
            # delegation, avoiding unnecessary extra rounds/turns.
            # IMPORTANT: must be AFTER the broadcast-reload block (line ~5593)
            # so that `if not collaborator_cards_list` correctly triggers the
            # broadcast to load other agents before self is appended.
            self_name = self._self_planner_agent_name()
            _existing_collab_names = {getattr(c, "name", "") for c in collaborator_cards_list}
            if self_name not in _existing_collab_names:
                self_card = next(
                    (c for c in all_cards if getattr(c, "name", "") == self_name), None
                )
                if self_card is None:
                    self_card = self.agent_card
                if self_card:
                    collaborator_cards_list.append(self_card)
                    logger.info(
                        "[MidExec][SelfInclude] added self to collaborator pool | "
                        "self=%s pool=%s",
                        self_name,
                        [getattr(c, "name", "") for c in collaborator_cards_list],
                    )

            logger.info("[MidExec] round %d / %d started", mid_exec_round + 1, max_mid_exec_rounds)

            # Step 1: Detect
            # Merge prior-turn delegate results into the detection context
            # so that the detection LLM knows which SGs already failed in
            # previous turns and does not recommend them again.
            _detect_delegate_results: dict[str, str] = dict(delegate_results)
            if prior_delegate_results:
                _detect_delegate_results.update(prior_delegate_results)

            detection = await self._detect_delegation_needs(
                query=query,
                own_results=own_results,
                delegated_results=_detect_delegate_results,
                collaborator_cards=collaborator_cards_list,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                delegation_chain=delegation_chain,
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
            detected_task_type = detection.get("task_type") or "unknown"
            target_sgs = list(detection.get("target_sgs") or [])
            # Filter out LLM-hallucinated agent names that don't exist in collaborator pool
            if target_sgs and collaborator_cards_list:
                valid_names = {c.name for c in collaborator_cards_list if getattr(c, "name", "")}
                target_sgs = [n for n in target_sgs if n in valid_names]
            detection_source = detection.get("source") or "llm_detection"
            target_label = ", ".join(target_sgs)
            reason_part = f"原因：{_short(reason_text, 300)}" if reason_text.strip() else ""
            message_parts = ["检测到数据缺口：需要补充数据。"]
            if reason_part:
                message_parts.append(reason_part)
            await self._emit_progress(
                updater,
                "mid_exec_detect_result",
                message=" ".join(message_parts),
                status="running",
                extra={
                    "needs_help": True,
                    "task_type": detected_task_type,
                    "reason": reason_text,
                    "target_sgs": target_sgs,
                    "round": mid_exec_round + 1,
                    "detection_source": detection_source,
                },
            )

            synthesized_query = detection.get("synthesized_query", "")
            soft_target_hints = list(detection.get("target_sgs") or [])
            if not synthesized_query:
                if detected_task_type == "unstructured":
                    # 非结构化任务：写不出可执行子问题 ⇒ 不构成明确缺口。
                    # 提示词已把「能写出 synthesized_query」设为 needs_help=true 的
                    # 必要条件；此处做防御性收敛：按「无明确缺口」正常结束，
                    # 不再进入下游选人/规划（它们均以非空 query 为前提）。
                    # 非结构化任务在理论上永远可以「更深入」，因此不允许以
                    # 开放式理由继续委派，否则会无限追数据。
                    logger.info(
                        "[MidExec] unstructured task with empty synthesized_query "
                        "→ treated as no clear gap, exiting mid-exec loop"
                    )
                    await self._emit_progress(
                        updater,
                        "mid_exec_no_clear_gap",
                        message=(
                            "Mid-exec: 非结构化任务未发现明确数据缺口，"
                            "无需补充数据"
                        ),
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "no_clear_gap_unstructured",
                            "task_type": detected_task_type,
                        },
                    )
                    break
                await self._emit_progress(
                    updater,
                    "mid_exec_empty_query",
                    message="Mid-exec: 检测到数据缺口但未能生成有效的子问题，无法委派",
                    status="done",
                    extra={
                        "round": mid_exec_round + 1,
                        "reason": "empty_synthesized_query",
                    },
                )
                break

            # Step 1.5: Build executed tasks context for capability check and planner.
            # Must be built BEFORE target selection so the capability check
            # LLM sees the same context as the planner.
            _round_executed_tasks: list[dict] = [
                {
                    "task_id": tid,
                    "description": (task_item.description or ""),
                    "agent": (task_item.agent or ""),
                    "status": "completed",
                    "result": res,
                }
                for task_item in plan.tasks
                for tid, res in all_task_results.items()
                if tid == task_item.id and res
            ]
            _upstream_executed = (upstream_context or {}).get("executed_tasks")
            if _upstream_executed:
                _round_executed_tasks = list(_upstream_executed) + _round_executed_tasks

            # Step 1.6: Select targets via concurrent capability_check
            target_sg_names: list[str] = []
            target_cards_list: list[AgentCard] = []
            hints_by_sg: dict[str, dict] = {}
            if self._mid_delegate_detect_direct_enabled():
                # ── Detect-Direct path: use detection LLM results directly ──
                # The detection LLM already has full context (original query,
                # own results, delegated results, agent skills, DAG chain) and
                # produced well-reasoned target_sgs recommendations.  We skip
                # the broadcast capability check entirely and trust the
                # detection LLM's choice.
                target_sg_names = list(target_sgs)
                target_cards_list = [
                    c for c in collaborator_cards_list
                    if getattr(c, "name", "") in target_sg_names
                ]
                logger.info(
                    "[MidExec][DetectDirect] using detection LLM targets directly | "
                    "round=%d targets=%s matched_cards=%d",
                    mid_exec_round + 1,
                    target_sg_names,
                    len(target_cards_list),
                )
                if not target_cards_list:
                    logger.info(
                        "[MidExec][DetectDirect] no matching cards for detection targets, "
                        "exiting loop"
                    )
                    await self._emit_progress(
                        updater,
                        "mid_exec_no_targets",
                        message="Mid-exec: 检测到数据缺口但未找到匹配的目标智能体",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "detect_direct_no_matching_targets",
                            "target_sgs": target_sg_names,
                        },
                    )
                    break

                # ── Re-delegation guard: filter exhausted SGs ──
                if _exhausted_sgs and target_cards_list:
                    _before = len(target_cards_list)
                    _filtered_cards = [
                        c for c in target_cards_list
                        if getattr(c, "name", "") not in _exhausted_sgs
                    ]
                    if len(_filtered_cards) < _before:
                        _filtered_names = [
                            getattr(c, "name", "") for c in _filtered_cards
                        ]
                        logger.info(
                            "[MidExec][DetectDirect] re-delegation guard filtered | "
                            "round=%d exhausted=%s before=%d after=%d kept=%s",
                            mid_exec_round + 1,
                            sorted(_exhausted_sgs),
                            _before,
                            len(_filtered_cards),
                            _filtered_names,
                        )
                        target_cards_list = _filtered_cards
                        target_sg_names = _filtered_names

                if not target_cards_list:
                    logger.info(
                        "[MidExec][DetectDirect] all targets exhausted, exiting loop"
                    )
                    await self._emit_progress(
                        updater,
                        "mid_exec_all_exhausted",
                        message="Mid-exec: 所有候选智能体均已尝试且返回空结果，无法继续委派",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "all_targets_exhausted",
                            "exhausted_sgs": sorted(_exhausted_sgs),
                        },
                    )
                    break

            elif self._mid_delegate_capability_select_enabled():
                selection = await self._select_mid_delegate_targets_via_capability(
                    synthesized_query=synthesized_query,
                    collaborator_cards=collaborator_cards_list,
                    soft_target_hints=soft_target_hints,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    original_query=query,
                    executed_tasks=_round_executed_tasks,
                    detection_reason=reason_text,
                )
                target_cards_list = list(selection.get("target_cards") or [])
                target_sg_names = list(selection.get("target_sg_names") or [])
                hints_by_sg = dict(selection.get("hints_by_sg") or {})

                # ── Re-delegation guard: filter exhausted SGs ──
                if _exhausted_sgs and target_cards_list:
                    _before = len(target_cards_list)
                    _filtered_cards = [
                        c for c in target_cards_list
                        if getattr(c, "name", "") not in _exhausted_sgs
                    ]
                    if len(_filtered_cards) < _before:
                        _filtered_names = [
                            getattr(c, "name", "") for c in _filtered_cards
                        ]
                        logger.info(
                            "[MidExec] re-delegation guard filtered | "
                            "round=%d exhausted=%s before=%d after=%d kept=%s",
                            mid_exec_round + 1,
                            sorted(_exhausted_sgs),
                            _before,
                            len(_filtered_cards),
                            _filtered_names,
                        )
                        target_cards_list = _filtered_cards
                        target_sg_names = _filtered_names

                if not target_cards_list:
                    logger.info("[MidExec] no capable remote SG, exiting loop")
                    await self._emit_progress(
                        updater,
                        "mid_exec_no_capable_sg",
                        message="Mid-exec: 能力检测未找到可处理该子任务的智能体，无法委派",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "no_capable_remote_sg",
                            "synthesized_query": (synthesized_query or "")[:200],
                        },
                    )
                    break
            else:
                target_sg_names = soft_target_hints
                target_cards_list = [c for c in collaborator_cards_list if c.name in target_sg_names]
                if not target_cards_list:
                    await self._emit_progress(
                        updater,
                        "mid_exec_no_targets",
                        message="Mid-exec: 检测到数据缺口但未找到匹配的目标智能体",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "no_matching_targets",
                            "target_sgs": target_sg_names,
                        },
                    )
                    break

                # ── Re-delegation guard: filter exhausted SGs (non-capability path) ──
                if _exhausted_sgs and target_cards_list:
                    _before = len(target_cards_list)
                    target_cards_list = [
                        c for c in target_cards_list
                        if getattr(c, "name", "") not in _exhausted_sgs
                    ]
                    if len(target_cards_list) < _before:
                        target_sg_names = [
                            getattr(c, "name", "") for c in target_cards_list
                        ]
                        logger.info(
                            "[MidExec] re-delegation guard filtered (fallback path) | "
                            "round=%d exhausted=%s before=%d after=%d kept=%s",
                            mid_exec_round + 1,
                            sorted(_exhausted_sgs),
                            _before,
                            len(target_cards_list),
                            target_sg_names,
                        )
                if not target_cards_list:
                    logger.info(
                        "[MidExec] all targets exhausted (fallback path), exiting loop"
                    )
                    await self._emit_progress(
                        updater,
                        "mid_exec_all_exhausted",
                        message="Mid-exec: 所有候选智能体均已尝试且返回空结果，无法继续委派",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "all_targets_exhausted",
                            "exhausted_sgs": sorted(_exhausted_sgs),
                        },
                    )
                    break

            # ── DAG Layer 5: safety net — filter target_cards against delegation chain ──
            # This runs after both the capability path and non-capability path have
            # finalized target_cards_list.  Even if the detection LLM ignored the
            # DAG prompt (Layer 4) or the capability check returned chain agents,
            # this hard filter ensures they never reach dispatch.
            if self._dag_enforcement_enabled() and delegation_chain and target_cards_list:
                _dag_before = len(target_cards_list)
                _dag_chain_set = set(delegation_chain)
                _dag_removed = sorted(
                    getattr(c, "name", "") for c in target_cards_list
                    if getattr(c, "name", "") in _dag_chain_set
                )
                target_cards_list = [
                    c for c in target_cards_list
                    if getattr(c, "name", "") not in _dag_chain_set
                ]
                if _dag_removed:
                    target_sg_names = [getattr(c, "name", "") for c in target_cards_list]
                    self._log_dag_event(
                        "SAFETY_NET",
                        chain=delegation_chain,
                        self_name="",
                        detail=f"安全网拦截！剔除链上 agent: {', '.join(_dag_removed)}",
                        level="warning",
                    )
                    logger.warning(
                        "[MidExec][DAG] safety net fired! removed chain agents from dispatch targets | "
                        "chain=%s removed=%s before=%d after=%d",
                        delegation_chain,
                        _dag_removed,
                        _dag_before,
                        len(target_cards_list),
                    )
                if not target_cards_list:
                    logger.warning(
                        "[MidExec][DAG] all targets were chain agents, exiting mid-exec loop"
                    )
                    await self._emit_progress(
                        updater,
                        "mid_exec_dag_blocked",
                        message="Mid-exec: DAG 约束拦截 — 所有候选智能体均在委派链路中，无法继续委派",
                        status="done",
                        extra={
                            "round": mid_exec_round + 1,
                            "reason": "dag_chain_blocked",
                            "delegation_chain": delegation_chain,
                        },
                    )
                    break

            # Step 2: Plan
            if self._mid_delegate_detect_direct_enabled():
                mid_plan = await self._plan_mid_exec_delegation_with_full_context(
                    synthesized_query=synthesized_query,
                    target_cards=target_cards_list,
                    original_query=query,
                    executed_tasks=_round_executed_tasks,
                    detection_reason=detection.get("reason", ""),
                    delegation_chain=delegation_chain,
                    turn=turn,
                    mid_exec_round=mid_exec_round + 1,
                )
            else:
                mid_plan = await self._plan_mid_exec_delegation(
                    synthesized_query=synthesized_query,
                    target_cards=target_cards_list,
                    original_query=query,
                    executed_tasks=_round_executed_tasks,
                    detection_reason=detection.get("reason", ""),
                    delegation_chain=delegation_chain,
                    turn=turn,
                    mid_exec_round=mid_exec_round + 1,
                )
            if mid_plan is None:
                logger.warning("[MidExec] plan returned None, exiting loop")
                await self._emit_progress(
                    updater,
                    "mid_exec_plan_failed",
                    message="Mid-exec: 委派规划失败，无法生成委派任务",
                    status="done",
                    extra={
                        "round": mid_exec_round + 1,
                        "reason": "plan_returned_none",
                    },
                )
                break

            # If planner returned all-NONE tasks, no capable agent was found — exit
            if mid_plan.tasks and all(
                (t.agent or "").strip().upper() == "NONE" for t in mid_plan.tasks
            ):
                logger.warning(
                    "[MidExec][Plan] planner returned all-NONE, "
                    "no capable agent available — exiting mid-exec loop"
                )
                for none_task in mid_plan.tasks:
                    await self._record_none_execution_task(
                        task_id=none_task.id,
                        description=none_task.description or "",
                        updater=updater,
                        turn=turn,
                        stage=f"mid_exec_round_{mid_exec_round + 1}",
                        run_id=run_id,
                        trace_id=trace_id,
                        user_id=user_id,
                        execution_flow_tasks=execution_flow_tasks,
                        extra_reason=(
                            detection.get("reason", "")
                            or f"{NONE_TASK_REASON_CODE}: mid-exec 无可用智能体"
                        ),
                    )
                await self._emit_progress(
                    updater,
                    "mid_exec_all_none",
                    message="Mid-exec: Planner 确认所有可用智能体均无法处理该子任务，无法委派",
                    status="done",
                    extra={
                        "round": mid_exec_round + 1,
                        "reason": "planner_all_none",
                        "synthesized_query": (synthesized_query or "")[:200],
                    },
                )
                break

            # Step 3: Dispatch
            # Build enriched upstream context for dispatch
            dispatch_ctx: dict[str, Any] = dict(upstream_context)
            # ── 传递 Execution Flow 到下游 Agent ──
            # 下游 Agent 需要看到上游完整的执行流水账，以便理解上下文。
            _ef_for_ctx = [t.to_dict() if isinstance(t, ExecutionTask) else t
                           for t in execution_flow_tasks]
            dispatch_ctx.update({
                "executed_tasks": _round_executed_tasks,
                "already_delegated": [
                    {
                        "target_sg": name,
                        "result": result or "",
                        "status": "empty" if not result or result == NONE_TASK_DESCRIPTION else "ok",
                    }
                    for name, result in delegate_results.items()
                ],
                "mid_exec_round": mid_exec_round + 1,
                "synthesized_query": synthesized_query,
                "detection_reason": detection.get("reason", ""),
                "execution_flow": _ef_for_ctx,
            })
            # --- Data Flow: mid-exec round dispatch ---
            _mid_ctx_chars = len(json.dumps(dispatch_ctx, ensure_ascii=False))
            # Use planner's actual dispatched agents, not capability check's candidate pool
            _dispatch_agent_names = sorted(set(
                (t.agent or "").strip() for t in (mid_plan.tasks or [])
                if (t.agent or "").strip().upper() != "NONE"
            ))
            self._log_data_flow(
                direction="MID_DISPATCH_SEND",
                description=(
                    f"Mid-exec R{mid_exec_round+1} planner dispatched → "
                    f"目标 SGs {_dispatch_agent_names}"
                ),
                source_id=self._self_planner_agent_name(),
                target_id=", ".join(_dispatch_agent_names) or "?",
                payload_chars=_mid_ctx_chars,
                payload_preview=(
                    f"已委托: {len(delegate_results)} 条, "
                    f"synthesized_query: {(synthesized_query or '')[:200]}, "
                    f"ef_tasks: {len(_ef_for_ctx)}"
                ),
                metadata_extra={
                    "mid_exec_round": mid_exec_round + 1,
                    "delegation_chain": delegation_chain,
                    "ef_tasks": len(_ef_for_ctx),
                },
            )
            mid_delegate, mid_self, current_hop, mid_ef_tasks = await self._dispatch_mid_exec_delegation(
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
                skill_runner=skill_runner,
                metadata=metadata,
                turn=turn,
                detection_reason=detection.get("reason", ""),
            )
            delegate_results.update(mid_delegate)
            # Merge mid-exec execution flow tasks
            execution_flow_tasks.extend(mid_ef_tasks)

            # Hop is consumed inside _dispatch_mid_exec_delegation;
            # current_hop has already been updated by the returned value.

            # ── Re-delegation guard ──
            # Mark SGs that returned NONE or empty results as exhausted so
            # they are excluded from subsequent mid-exec rounds.  This
            # prevents infinite ping-pong between the same agent pair when
            # the delegated SG cannot contribute meaningful data.
            for sg_name, result in mid_delegate.items():
                if not result or result == NONE_TASK_DESCRIPTION:
                    _exhausted_sgs.add(sg_name)
                    logger.info(
                        "[MidExec] exhausted SG marked | sg=%s round=%d "
                        "reason=empty_or_none_result",
                        sg_name, mid_exec_round + 1,
                    )

            # Merge self-execution results into own_results for next round detection.
            # Delegated results are already in delegate_results — do NOT duplicate
            # them into own_results to avoid redundant data.
            self_name = self._self_planner_agent_name()
            if self_name in mid_self:
                self._log_data_flow(
                    direction="MID_SELF_RECV",
                    description=f"Mid-exec self-exec [{self_name}] 结果 → own_results",
                    source_id=self_name or "?",
                    target_id=self._self_planner_agent_name(),
                    payload_chars=len(mid_self[self_name] or ""),
                    payload_preview=(mid_self[self_name] or "")[:1000],
                )
                fake_task_id = 10000 + mid_exec_round * 100 + len(delegate_results)
                own_results[fake_task_id] = f"[Self-exec {self_name}]: {mid_self[self_name]}"
                all_task_results[fake_task_id] = f"[Self-exec {self_name}]: {mid_self[self_name]}"

            mid_exec_round += 1

        await self._emit_progress(
            updater,
            "mid_exec_done",
            message=f"Mid-execution complete ({len(delegate_results)} total delegations)",
            status="done",
            extra={"mid_delegate_count": len(delegate_results), "rounds": mid_exec_round},
        )

        return all_task_results, delegate_results, current_hop, plan_task_meta, execution_flow_tasks

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception("cancel not supported")