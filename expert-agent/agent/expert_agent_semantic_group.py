import json
import hashlib
import logging
import sys
import copy
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
from typing import Any, AsyncIterable, Awaitable, Callable, Dict, Literal, List, Optional, Tuple, Union
from uuid import uuid4
from pydantic import BaseModel, Field
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.types import MessageSendParams, SendStreamingMessageRequest
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from a2a.client import A2AClient
from typing_extensions import override
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import StructuredTool
from .react import ReActRunner
from .dataservices_client import DataServicesClient, SemanticDomainInfo, SemanticGroupInfo
from .agentregistry_client import AgentRegistryClient
from .schema import ROLE_TYPE, AgentState, Memory, Message
from .prompts import NEXT_STEP_PROMPT_ZH
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .tool_call_utils import invoke_llm_with_tool

try:
    # json_repair is a tolerant JSON parser designed specifically for LLM output.
    # It handles common failure modes such as unescaped inner double quotes,
    # trailing commas, missing quotes, python-style single quotes, etc.
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]


# String keys for ``format_llm_output`` in this file:
# - Next-step / observe: ``answer``, ``requery``, ``reason`` (same shape as domain expert).
# - Execution planning LLM: top-level ``reasoning``; ``excluded_agents[].reason`` also matches
#   the ``reason`` key. Shared planner / upstream keys kept for embedded or propagated JSON.
# - ``execution_plan`` is an array, not whitelisted (nested repair via json_repair).
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


_EMBEDDED_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def _extract_embedded_json_fence(text: str) -> Optional[str]:
    """Extract JSON content from a markdown code fence embedded in the middle of text."""
    match = _EMBEDDED_JSON_FENCE_RE.search(text)
    if not match:
        return None
    inner = match.group(1).strip()
    if not inner:
        return None
    return inner


_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _extract_json_object_from_text(text: str) -> Optional[str]:
    """Try to extract a balanced JSON object from free-form text (no fence)."""
    for match in _JSON_OBJECT_RE.finditer(text):
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

PROGRESS_SCHEMA_VERSION = "v1"
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
    "group_members_resolved": {"agent_count", "downstream_agents"},
    "execution_plan_ready": {
        "phase_count",
        "query_preview",
        "execution_order",
        "dependency_summary",
        "plan_outline",
        "phase_order_hint",
    },
    "phase_started": {
        "phase",
        "total_phases",
        "agent_count",
        "query_preview",
        "parallel_agents",
        "context_from",
    },
    "phase_context_ready": {
        "phase",
        "total_phases",
        "context_count",
        "query_preview",
        "context_from",
    },
    "phase_finished": {
        "phase",
        "total_phases",
        "ok_count",
        "agent_count",
        "query_preview",
        "parallel_agents",
        "react_status",
        "react_steps",
    },
    "agent_answer": {"target_agent"},
    "sg_react_step_start": {"step", "max_steps", "message_count"},
    "sg_react_llm_decision": {
        "step",
        "max_steps",
        "thought_preview",
        "thought_full",
        "tool_names",
        "tool_count",
    },
    "sg_react_tool_start": {
        "step",
        "tool_index",
        "tool_total",
        "tool_name",
        "step_tool_names",
        "agent_name",
        "descriptor_type",
        "query_preview",
        "query_full",
        "code_ctx_count",
        "doc_ctx_count",
    },
    "sg_react_tool_done": {
        "step",
        "tool_index",
        "tool_total",
        "tool_name",
        "step_tool_names",
        "agent_name",
        "result_chars",
        "result_preview",
        "repeat_of_previous",
        "error",
    },
    "sg_react_step_analysis": {
        "step",
        "trigger",
        "next_action",
        "next_tool",
        "diagnosis_preview",
    },
    "sg_react_step_done": {
        "step",
        "max_steps",
        "observation_count",
        "step_tool_names",
        "analysis_ran",
    },
    "sg_react_finished": {"status", "steps", "result_chars"},
}

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

class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class ExecutionPlanPhase(BaseModel):
    """Execution plan phase for LLM output."""
    phase: int = Field(description="Phase number")
    agents: List[str] = Field(default_factory=list, description="Agent names in this phase")
    context_from: List[str] = Field(default_factory=list, description="Agent names whose context is used")


class ExcludedAgent(BaseModel):
    """Agent intentionally omitted from an execution plan."""
    name: str = Field(description="Exact name of the excluded agent")
    reason: str = Field(description="Brief reason why the agent is not needed")


class ExecutionPlanResult(BaseModel):
    """LLM output for execution plan."""
    model_config = {"extra": "ignore"}
    reasoning: str = Field(default="", description="Step-by-step reasoning")
    execution_plan: List[ExecutionPlanPhase] = Field(default_factory=list, description="Ordered execution phases")
    excluded_agents: List[ExcludedAgent] = Field(
        default_factory=list,
        description="Excluded agents with their exact names and reasons",
    )


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
        semantic_group_id:str = None,
        data_services_url: str = None,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None,
        resolve_intersection_mode: Optional[str] = None,
        agent_id: str = "",
    ):
        logger.info('Initializing ExpertAgent')
        super().__init__(
            agent_name=((agent_id or semantic_group_id or "ExpertAgent").strip()),
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
        # Tool calls require non-streaming LLM. When stream=True, the LLM returns
        # AsyncStream instead of AIMessage. Create a separate non-streaming instance.
        self.llm_non_stream = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=False,
            extra_body=_extra_body,
        )
        self.query=query
        self.original_query=query
        self.semantic_group_id = semantic_group_id
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.parent_registry_base_url = (
            os.getenv("AgentRegistryURL")
            or os.getenv("AgentRegistry")
            or "http://orchestrator-registry.dac.svc.cluster.local:8000"
        )
        self.leaf_registry_base_url = (
            os.getenv("LeafAgentRegistry")
            or os.getenv("AgentRegistryURL")
            or os.getenv("AgentRegistry")
            or "http://orchestrator-registry.dac.svc.cluster.local:8000"
        )
        logger.info(
            "[VersionMarker][ExpertSGInit] build_marker=%s, app_version=%s, image_tag=%s, git_sha=%s, "
            "parent_registry_base_url=%s, leaf_registry_base_url=%s, semantic_group_id=%s",
            os.getenv("BUILD_MARKER", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
            self.parent_registry_base_url,
            self.leaf_registry_base_url,
            semantic_group_id or "",
        )
        # Resolve intersection mode: "one" = pick one from intersection, "all" = use all in intersection.
        # Default from env SEMANTIC_GROUP_RESOLVE_INTERSECTION_MODE (one | all).
        self.resolve_intersection_mode = (
            resolve_intersection_mode
            or os.getenv("SEMANTIC_GROUP_RESOLVE_INTERSECTION_MODE", "all")
        ).strip().lower()
        if self.resolve_intersection_mode not in ("one", "all"):
            self.resolve_intersection_mode = "one"
        # Resolved (member_info, agent_card) for A2A calls; filled by resolve_agents_for_semantic_group()
        # member_info is SemanticDomainInfo for leaf groups, SemanticGroupInfo for parent groups.
        self.group_agent_cards: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]] = []
        self.current_step = 0
        self.state: AgentState = AgentState.IDLE
        self.memory = Memory()
        self.metadata = metadata
        self.max_steps=max_steps
        self.current_tasks_status = current_tasks_status
        # Agent identity should come from DAC instance wiring, not request metadata.
        self.agent_id = (agent_id or semantic_group_id or "").strip()

        self.react_runner = ReActRunner(
            llm=self.llm,
            invoke_agent=self._react_invoke_agent_callback,
            build_tool_description=self._build_react_tool_description,
            agent_name=self.agent_name,
        )

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
            "layer": "sg_expert",
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

    def current_agent_label(self) -> str:
        return (self.agent_id or self.semantic_group_id or self.agent_name or "sg_expert").strip()

    @staticmethod
    def is_progress_frame(text: str) -> bool:
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_PROGRESS]] ")

    @staticmethod
    def is_summary_artifact(text: str) -> bool:
        """检测 text 是否是 DAC_SUMMARY 协议帧（SD Orchestrator → SG Expert）。"""
        return isinstance(text, str) and text.lstrip().startswith("[[DAC_SUMMARY]] ")

    @staticmethod
    def parse_summary_artifact(text: str) -> Optional[str]:
        """解析 DAC_SUMMARY 帧，返回 summary 文本；若非 summary 帧则返回 None。"""
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        if not stripped.startswith("[[DAC_SUMMARY]] "):
            return None
        json_str = stripped[len("[[DAC_SUMMARY]] "):]
        try:
            payload = json.loads(json_str)
            return payload.get("summary", "")
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 320) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit - 3] + "..."

    def _query_preview_for_progress(self, query: str, limit: int = 200) -> str:
        """Short, single-line user query for DAC_PROGRESS (message + structured extra)."""
        return self._truncate_progress_message(query or "", limit)

    def _format_progress_plan_bundle(
        self,
        query: str,
        execution_plan: List[Dict[str, Any]],
        name_to_agent: Dict[str, Tuple[Union["SemanticDomainInfo", "SemanticGroupInfo"], "AgentCard"]],
    ) -> Dict[str, Any]:
        """Structured summary: phase order, dependencies, per-phase parallel agents + context_from."""
        total = len(execution_plan)
        qp = self._query_preview_for_progress(query)
        phase_order = " → ".join(str(p.get("phase", "?")) for p in execution_plan)
        dep_bits: List[str] = []
        phase_one_liners: List[str] = []
        for p in execution_plan:
            pn = p.get("phase", "?")
            agents = p.get("agents", []) or []
            ctx = p.get("context_from", []) or []
            ag_l = [self._agent_display_name(a, name_to_agent) for a in agents]
            ctx_l = [self._agent_display_name(c, name_to_agent) for c in ctx]
            agents_bit = ", ".join(ag_l) or "—"
            if ctx_l:
                dep_bits.append(
                    f"phase {pn} uses outputs from earlier phase(s), agents: {', '.join(ctx_l)}"
                )
                phase_one_liners.append(
                    f"phase {pn}: agents run in parallel — {agents_bit} "
                    f"(input includes prior outputs from: {', '.join(ctx_l)})"
                )
            else:
                phase_one_liners.append(
                    f"phase {pn}: agents run in parallel — {agents_bit} "
                    f"(input is the user query only; no prior-phase outputs)"
                )

        dep_summary = (
            "; ".join(dep_bits)
            if dep_bits
            else "No dependency between phases; each phase only needs the user query."
        )
        plan_outline = " | ".join(phase_one_liners)
        if total <= 1:
            phase_order_hint = (
                "Only phase 1 exists: the listed agents all run at the same time (in parallel)."
            )
        else:
            phase_order_hint = (
                f"Phases run strictly in order ({phase_order}): finish an earlier phase before the next starts. "
                "Within one phase, agents always run in parallel; later phases may merge earlier phases' results."
            )

        return {
            "query_preview": qp,
            "phase_count": total,
            "execution_order": phase_order,
            "dependency_summary": self._truncate_progress_message(dep_summary, 450),
            "plan_outline": self._truncate_progress_message(plan_outline, 900),
            "phase_order_hint": self._truncate_progress_message(phase_order_hint, 280),
        }

    def summarize_execution_plan(
        self,
        execution_plan: List[Dict[str, Any]],
        name_to_agent: Optional[Dict[str, Tuple[Union["SemanticDomainInfo", "SemanticGroupInfo"], "AgentCard"]]] = None,
    ) -> str:
        if not execution_plan:
            return "no phases"
        chunks: List[str] = []
        for phase_info in execution_plan[:5]:
            phase_num = phase_info.get("phase", "?")
            agents = phase_info.get("agents", []) or []
            ctx = phase_info.get("context_from", []) or []
            if name_to_agent:
                agents_display = [self._agent_display_name(a, name_to_agent) for a in agents]
                ctx_display = [self._agent_display_name(c, name_to_agent) for c in ctx]
            else:
                agents_display = [str(a) for a in agents]
                ctx_display = [str(c) for c in ctx]
            piece = f"phase {phase_num}: agents={', '.join(agents_display) or '-'}"
            if ctx_display:
                piece += f"; context_from={', '.join(ctx_display)}"
            chunks.append(self._truncate_progress_message(piece, 180))
        if len(execution_plan) > 5:
            chunks.append(f"... total={len(execution_plan)}")
        return " | ".join(chunks)

    async def emit_progress(
        self,
        event: str,
        *,
        message: str,
        status: str = "running",
        task_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if os.getenv("ENABLE_SG_PROGRESS_STREAM", "true").strip().lower() in ("false", "0", "no"):
            return
        callback = getattr(self, "progress_callback", None)
        if callback is None:
            return
        await callback(self.build_progress_frame(
            event,
            message=message,
            status=status,
            run_id=(self.metadata or {}).get("run_id", ""),
            user_id=(self.metadata or {}).get("user_id", ""),
            agent_id=self.current_agent_label(),
            task_id=task_id,
            extra=extra,
        ))

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

        # ── Extract embedded JSON fence from mixed text (e.g. "解释 + ```json\n{...}\n```") ──
        embedded_json = _extract_embedded_json_fence(cleaned_content)
        if embedded_json is not None:
            try:
                parsed = json.loads(embedded_json)
                if isinstance(parsed, dict):
                    logger.info(" === format_llm_output, recovered via embedded JSON fence extraction")
                    return parsed
            except json.JSONDecodeError:
                pass

        # ── Extract bare JSON object from free-form text (no fence) ──
        bare_json = _extract_json_object_from_text(cleaned_content)
        if bare_json is not None:
            try:
                parsed = json.loads(bare_json)
                if isinstance(parsed, dict):
                    logger.info(" === format_llm_output, recovered via embedded bare JSON extraction")
                    return parsed
            except json.JSONDecodeError:
                pass

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


    def _agent_url_from_semantic_domain(self, dd_namespace: str, dd_name: str) -> str:
        """
        Build A2A agent URL from semantic domain's dd_namespace and dd_name (K8s internal).
        DAC Service 名称为 dac-<dac.Name>，与 execution-engine 约定一致。
        """
        service_name = f"dac-{dd_name}"
        return f"http://{service_name}.{dd_namespace}.svc.cluster.local:10100"

    def _get_member_name(self, sd: SemanticDomainInfo) -> Optional[str]:
        """
        Get agent name from semantic domain for matching with registry.
        Prefer name from agent_card (JSON), else dd_name, else semantic_domain_id.
        """
        if not sd:
            return None
        if sd.agent_card and isinstance(sd.agent_card, str):
            s = sd.agent_card.strip()
            if s:
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        n = data.get("name")
                        if n and isinstance(n, str):
                            return n.strip()
                except (json.JSONDecodeError, TypeError):
                    pass
        if sd.dd_name and isinstance(sd.dd_name, str):
            return sd.dd_name.strip()
        if sd.semantic_domain_id and isinstance(sd.semantic_domain_id, str):
            return sd.semantic_domain_id.strip()
        return None

    async def resolve_agents_for_semantic_group(self) -> None:
        """
        Load semantic group + member semantic domains (or child groups) from data services.
        For leaf groups: find intersection of SD members with registered agents.
        For non-leaf groups: find child group expert-agent instances in registry.
        """
        if not self.semantic_group_id:
            return
        self.group_agent_cards = []
        try:
            async with self.data_services_client.session_context() as client:
                result = await client.get_semantic_group_with_members(self.semantic_group_id)
            if not result:
                logger.info("get_semantic_group_with_members returned None for group_id=%s", self.semantic_group_id)
                return

            is_non_leaf = bool(result.child_groups)
            selected_registry = self.parent_registry_base_url if is_non_leaf else self.leaf_registry_base_url
            logger.info(
                "[RegistrySelect] semantic_group_id=%s, is_non_leaf=%s, selected_registry=%s",
                self.semantic_group_id,
                is_non_leaf,
                selected_registry,
            )
            registry_client = AgentRegistryClient(base_url=selected_registry)
            registered_cards = await registry_client.get_registered_agent_cards()
            registered_by_name: Dict[str, AgentCard] = {}
            for ac in registered_cards:
                n = (getattr(ac, "name", None) or "").strip()
                if n:
                    registered_by_name[n] = ac

            if result.child_groups:
                await self._resolve_child_group_agents(result.child_groups, registered_by_name)
                return

            if not result.members:
                logger.info("get_semantic_group_with_members returned no members for group_id=%s", self.semantic_group_id)
                return

            # --- Below is the existing leaf-group resolution logic (unchanged) ---
            logger.info("Semantic group has %s members; registry has %s agent(s) (by name): %s", len(result.members), len(registered_by_name), list(registered_by_name.keys()))
            # Intersection: (sd, agent_card) for each member that matches a registered agent.
            #
            # Two-pass matching to prevent prefix-fallback from stealing deterministic-hash agents:
            #   Pass 1: Exact match (Priority 1) + deterministic hash match (Priority 2)
            #           — locks in agents whose names are predictable from dd_namespace/dd_name
            #   Pass 2: Prefix fallback (Priority 3) for remaining unmatched members
            #           — handles old agents with random suffixes (e.g., created from UI)
            intersection: List[Tuple[SemanticDomainInfo, AgentCard]] = []
            assigned_reg_names: set = set()

            # Collect valid members with parsed attributes
            parsed_members: List[Tuple[int, SemanticDomainInfo, str, str, str, str]] = []
            for i, member in enumerate(result.members):
                if not member.semantic_domain:
                    continue
                sd = member.semantic_domain
                member_name = self._get_member_name(sd)
                ns, dd_name = (sd.dd_namespace or "").strip(), (sd.dd_name or "").strip()
                dt = (sd.descriptor_type or "").strip()
                logger.info("Group member [%s]: name=%s dd_namespace=%s dd_name=%s descriptor_type=%s", i + 1, member_name or "(none)", ns, dd_name, dt or "(none)")
                if not member_name:
                    logger.info("Skip group member: no name from sd_id=%s", sd.semantic_domain_id)
                    continue
                parsed_members.append((i, sd, member_name, ns, dd_name, dt))

            # Pass 1: exact match + deterministic hash match
            pass1_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                agent_card = registered_by_name.get(member_name)
                match_type = "exact"
                if agent_card:
                    assigned_reg_names.add(member_name)
                elif ns and dd_name:
                    dd_suffix = hashlib.sha256(f"{ns}/{dd_name}".encode()).hexdigest()[:8]
                    expected_name = f"{member_name}-dd-{dd_suffix}"
                    agent_card = registered_by_name.get(expected_name)
                    if agent_card:
                        match_type = "dd-hash"
                        assigned_reg_names.add(expected_name)
                        logger.info("Deterministic hash match: member name=%s dd=%s/%s -> registry agent name=%s", member_name, ns, dd_name, expected_name)
                if agent_card:
                    pass1_matched[idx] = (sd, agent_card, match_type)

            # Pass 1.5: description-based matching for members not matched in Pass 1.
            # When multiple members share the same base name (e.g., both from
            # agent_card JSON "name": "EcommerceTransactionAgent") but correspond
            # to different data descriptors, the description field — generated by
            # the data-sinker LLM for each data source — is typically unique and
            # preserved unchanged through DAC creation into the registered AgentCard.
            pass15_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            unmatched_after_pass1 = [
                (idx, sd, member_name, ns, dd_name, dt)
                for idx, sd, member_name, ns, dd_name, dt in parsed_members
                if idx not in pass1_matched
            ]
            if unmatched_after_pass1:
                for idx, sd, member_name, ns, dd_name, dt in unmatched_after_pass1:
                    sd_desc = self._get_agent_description(sd).lower()
                    if not sd_desc:
                        continue
                    suffix_pattern = f"{member_name}-dd-"
                    for reg_name, reg_card in registered_by_name.items():
                        if reg_name in assigned_reg_names:
                            continue
                        if not reg_name.startswith(suffix_pattern):
                            continue
                        reg_desc = (getattr(reg_card, "description", None) or "").strip().lower()
                        if reg_desc and reg_desc == sd_desc:
                            pass15_matched[idx] = (sd, reg_card, "description")
                            assigned_reg_names.add(reg_name)
                            logger.info("Description match: member dd_name=%s -> registry agent name=%s", dd_name, reg_name)
                            break

            # Pass 2: prefix fallback for members not matched in Pass 1 or Pass 1.5
            pass2_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            # Detect base-name ambiguity for warning
            unmatched_base_names: Dict[str, int] = {}
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                if idx in pass1_matched or idx in pass15_matched:
                    continue
                unmatched_base_names[member_name] = unmatched_base_names.get(member_name, 0) + 1
            ambiguous_base_names = {n for n, c in unmatched_base_names.items() if c > 1}

            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                if idx in pass1_matched or idx in pass15_matched:
                    continue
                suffix_pattern = f"{member_name}-dd-"
                agent_card = None
                for reg_name, reg_card in registered_by_name.items():
                    if reg_name in assigned_reg_names:
                        continue
                    if reg_name.startswith(suffix_pattern):
                        agent_card = reg_card
                        assigned_reg_names.add(reg_name)
                        if member_name in ambiguous_base_names:
                            logger.warning(
                                "AMBIGUOUS prefix fallback: member dd_name=%s (base name=%s) has %d unmatched members with same base name. "
                                "Pairing with registry agent %s may be INCORRECT — consider updating agent_card in semantic domain to include full agent name.",
                                dd_name, member_name, unmatched_base_names[member_name], reg_name)
                        else:
                            logger.info("Prefix fallback match: member name=%s -> registry agent name=%s", member_name, reg_name)
                        break
                if agent_card:
                    pass2_matched[idx] = (sd, agent_card, "dd-prefix-fallback")
                else:
                    logger.info("Skip group member: name=%s not in registry (tried exact, dd-hash, description, prefix-fallback)", member_name)

            # Merge results in original member order
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                entry = pass1_matched.get(idx) or pass15_matched.get(idx) or pass2_matched.get(idx)
                if entry:
                    sd_val, agent_card, match_type = entry
                    intersection.append((sd_val, agent_card))
                    logger.info("In intersection (%s match): member name=%s -> registry agent name=%s url=%s", match_type, member_name, getattr(agent_card, "name", ""), getattr(agent_card, "url", ""))
            # Branch: pick one or use all according to resolve_intersection_mode
            if intersection:
                if self.resolve_intersection_mode == "all":
                    # Deduplicate by agent URL so the same agent is not called multiple times
                    seen_urls: set = set()
                    deduped: List[Tuple[SemanticDomainInfo, AgentCard]] = []
                    for sd, ac in intersection:
                        url = (getattr(ac, "url", None) or "").strip().rstrip("/")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            deduped.append((sd, ac))
                        else:
                            logger.debug("Skip duplicate agent url in intersection (mode=all): %s", url or "(empty)")
                    self.group_agent_cards = deduped
                    logger.info("Using all from intersection (mode=all, %s unique agent(s) after dedup by URL): %s", len(self.group_agent_cards), "; ".join(getattr(ac, "url", "") or "" for _, ac in self.group_agent_cards))
                else:
                    self.group_agent_cards = [intersection[0]]
                    sd0, ac0 = intersection[0]
                    logger.info("Picked one from intersection (mode=one, %s total): name=%s url=%s", len(intersection), getattr(ac0, "name", ""), getattr(ac0, "url", ""))
            else:
                logger.info("Resolved 0 of %s group members (no name match with registry).", len(result.members))
        except Exception as e:
            logger.error("resolve_agents_for_semantic_group failed: %s", e)

    async def _resolve_child_group_agents(
        self,
        child_groups: List[SemanticGroupInfo],
        registered_by_name: Dict[str, "AgentCard"],
    ) -> None:
        """
        For non-leaf groups: resolve child group expert-agent SG instances in the registry.
        Each child group has its own DAC/Pod registered as an agent with a name pattern:
        {baseName}-sg-{suffix}. We match using the agent_card JSON name from the child group.
        """
        logger.info("Resolving %d child group(s) as composite agents", len(child_groups))
        for child in child_groups:
            child_name = self._get_child_group_agent_name(child)
            if not child_name:
                logger.info("Skip child group %s: no agent name", child.id)
                continue

            agent_card = None
            sg_prefix = f"{child_name}-sg-"

            if child_name in registered_by_name:
                agent_card = registered_by_name[child_name]
            else:
                for reg_name, reg_card in registered_by_name.items():
                    if reg_name.startswith(sg_prefix):
                        agent_card = reg_card
                        logger.info("Child group '%s' matched registry agent '%s' by -sg- prefix",
                                    child_name, reg_name)
                        break

            if agent_card:
                self.group_agent_cards.append((child, agent_card))
                logger.info("Resolved child group '%s' -> agent '%s' (url=%s)",
                            child.group_name,
                            getattr(agent_card, 'name', ''),
                            getattr(agent_card, 'url', ''))
            else:
                logger.warning("Child group '%s' (name=%s) not found in registry",
                               child.group_name, child_name)

        logger.info("Resolved %d child group agent(s)", len(self.group_agent_cards))

    @staticmethod
    def _get_child_group_agent_name(child) -> str:
        """Extract the agent name from a SemanticGroupInfo's agent_card JSON."""
        agent_card_str = getattr(child, 'agent_card', None) or ""
        if agent_card_str and isinstance(agent_card_str, str):
            try:
                data = json.loads(agent_card_str.strip())
                if isinstance(data, dict):
                    name = data.get("name", "")
                    if name and isinstance(name, str):
                        return name.strip()
            except (json.JSONDecodeError, TypeError):
                pass
        return getattr(child, 'group_name', '') or ""

    def _get_response_text_from_chunk(self, chunk: Any) -> str:
        """
        Extract artifact text from A2A streaming chunk (artifact-update).
        Matches orchestrator-agent and routing-agent: result.kind == 'artifact-update', artifact.parts[0].text.
        """
        data = chunk.model_dump(mode='json', exclude_none=True) if hasattr(chunk, 'model_dump') else (chunk if isinstance(chunk, dict) else {})
        result = data.get('result')
        if result is None or result.get('kind') != 'artifact-update':
            return ""
        artifact = result.get('artifact')
        if not artifact:
            return ""
        parts = artifact.get('parts')
        if not parts or len(parts) == 0 or not isinstance(parts[0], dict):
            return ""
        text = parts[0].get('text')
        return text if text else ""

    async def _fetch_knowledge_from_agent(
        self,
        httpx_client: httpx.AsyncClient,
        send_message_payload: Dict[str, Any],
        sd: SemanticDomainInfo,
        agent_card: AgentCard,
    ) -> Tuple[SemanticDomainInfo, str]:
        """
        Call one domain agent via A2A and return (sd, aggregated_text). On error returns (sd, "").
        Per-agent answer_model override: structured and unstructured (doc) → summarized; code/group → original.
        """
        try:
            # Clone payload per agent so concurrent gather calls don't share the same dict
            per_agent_payload: Dict[str, Any] = copy.deepcopy(send_message_payload)
            dt = (getattr(sd, 'descriptor_type', '') or "").strip().lower()
            meta: Dict[str, Any] = per_agent_payload.setdefault('metadata', {})
            meta['answer_model'] = self._answer_model_for_descriptor_type(dt)
            agent_name = getattr(agent_card, "name", "") or "(unknown)"
            logger.info(
                "[SGExpert] dispatch to agent=%s descriptor_type=%s answer_model=%s",
                agent_name, dt, meta['answer_model'],
            )

            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            streaming_request = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**per_agent_payload),
            )
            stream_response = client.send_message_streaming(streaming_request)
            agent_texts: List[str] = []
            summary_text: Optional[str] = None
            async for chunk in stream_response:
                result = self._get_response_text_from_chunk(chunk)
                if result != "":
                    if self.is_progress_frame(result):
                        logger.info(
                            "[DACProgress][SG-Expert] relay progress from downstream agent=%s",
                            getattr(agent_card, "name", "") or "(unknown)",
                        )
                        callback = getattr(self, "progress_callback", None)
                        if callback is not None:
                            await callback(result)
                        continue
                    if self.is_summary_artifact(result):
                        summary_text = self.parse_summary_artifact(result)
                        logger.info(
                            "[DACSummary][SG-Expert] received summary frame from agent=%s (%d chars)",
                            getattr(agent_card, "name", "") or "(unknown)",
                            len(summary_text) if summary_text else 0,
                        )
                        continue
                    agent_texts.append(result)
            if summary_text is not None:
                # 优先使用 DAC_SUMMARY 协议携带的 LLM 总结答案，丢弃中间 step 的冗余数据
                text = summary_text
                logger.info(
                    "[DACSummary][SG-Expert] using summary text (%d chars) from agent=%s, "
                    "discarded %d raw text chunks",
                    len(text),
                    getattr(agent_card, "name", "") or "(unknown)",
                    len(agent_texts),
                )
            else:
                text = " ".join(agent_texts) if agent_texts else ""
            return (sd, text)
        except Exception as e:
            logger.warning("A2A call failed for agent %s: %s", getattr(agent_card, 'url', ''), e)
            return (sd, "")

    def _get_agent_description(self, sd: SemanticDomainInfo) -> str:
        """从 agent_card JSON 中提取 agent 的 description 字段。"""
        if sd.agent_card and isinstance(sd.agent_card, str):
            s = sd.agent_card.strip()
            if s:
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        desc = data.get("description", "")
                        if desc and isinstance(desc, str):
                            return desc.strip()
                except (json.JSONDecodeError, TypeError):
                    pass
        return ""

    _DESCRIPTOR_TYPE_ROLE: Dict[str, str] = {
        "code": "Retrieves and analyzes source code from code repositories. Contains business logic, data models, "
                "field mappings, and table relationships.",
        "unstructured": "A semantic domain's document knowledge base. Retrieves and analyzes all documents "
            "within the domain — API specs, design docs, data dictionaries, business rules, "
            "field descriptions, manuals, etc.",
        "structured": "Queries structured data (SQL, ChatBI, data analysis, charts). Can use code/doc context when available.",
        "group": "A composite child group agent that encapsulates an entire sub-domain. It has its own internal agents "
                 "and planning. Treat it as a black-box expert for its domain.",
    }

    _DESCRIPTOR_TYPE_USE_WHEN: Dict[str, str] = {
        "code": "User needs business logic, field semantics, or implementation rules that may affect accurate SQL/data queries. Call BEFORE structured when rules define filters, valid records, or metric meaning.",
        "unstructured": "User needs documentation, API specs, data dictionaries, or business口径 that may affect accurate SQL/data queries. Call BEFORE structured when docs define statistics rules or field meaning.",
        "structured": "User needs live data, statistics, or reports. Receives code/doc context automatically when SG orchestrator gathered foundation first — use for final accurate data retrieval.",
        "group": "User question overlaps with this sub-domain and a composite expert is the right entry point.",
    }

    _DESCRIPTOR_TYPE_DO_NOT_USE: Dict[str, str] = {
        "code": "Never as a substitute for structured when the user only needs final numbers and rules are already known from prior context.",
        "unstructured": "Never as a substitute for structured when the user only needs final numbers and口径 are already known from prior context.",
        "structured": "Not as the first and only call when the question depends on unknown business rules/field semantics and no code/doc context exists yet.",
        "group": "A more specific code, doc, or structured agent in this group already covers the question.",
    }

    def _get_full_agent_description(
        self,
        member: Union[SemanticDomainInfo, SemanticGroupInfo],
        agent_card: AgentCard,
    ) -> str:
        card_desc = (getattr(agent_card, "description", None) or "").strip()
        if card_desc:
            return card_desc
        if isinstance(member, SemanticDomainInfo):
            return self._get_agent_description(member)
        agent_card_str = getattr(member, "agent_card", None) or ""
        if agent_card_str and isinstance(agent_card_str, str):
            try:
                data = json.loads(agent_card_str.strip())
                if isinstance(data, dict):
                    desc = data.get("description", "")
                    if desc and isinstance(desc, str):
                        return desc.strip()
            except (json.JSONDecodeError, TypeError):
                pass
        return (getattr(member, "group_name", "") or "").strip()

    @staticmethod
    def _answer_model_for_descriptor_type(descriptor_type: str) -> str:
        """A2A metadata answer_model: structured and unstructured (doc SD) → summarized at SD execute();

        Unstructured SD reads descriptorType from DescriptorTypes env; utility a2a uses original.
        """
        dt = (descriptor_type or "").strip().lower()
        if dt == "structured" or dt.startswith("structured-"):
            return "summarized"
        if dt == "unstructured" or "unstructured" in dt:
            return "summarized"
        return "original"

    def _build_react_tool_description(
        self,
        member: Union[SemanticDomainInfo, SemanticGroupInfo],
        agent_card: AgentCard,
        name_to_agent: Dict[str, Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]],
    ) -> str:
        dt = (getattr(member, "descriptor_type", "") or "").strip().lower() or "unknown"
        role_key = dt if dt in self._DESCRIPTOR_TYPE_ROLE else (
            "structured" if dt.startswith("structured-") else (
                "unstructured" if "unstructured" in dt else dt
            )
        )
        role = self._get_role_by_descriptor_type(member)
        use_when = self._DESCRIPTOR_TYPE_USE_WHEN.get(
            role_key,
            "When this agent's domain capability matches the current information need.",
        )
        do_not_use = self._DESCRIPTOR_TYPE_DO_NOT_USE.get(
            role_key,
            "When another agent type is a better fit for the current step.",
        )
        full_desc = self._get_full_agent_description(member, agent_card)
        agent_name = getattr(agent_card, "name", "") or "(unknown)"
        display = self._agent_display_name(agent_name, name_to_agent)

        lines = [
            f"Agent: {display}",
            f"descriptor_type: {dt}",
            f"Role: {role}",
            f"Use when: {use_when}",
            f"Do NOT use when: {do_not_use}",
            "SG routing: pass the user's question with original semantics; this SD Expert decomposes and executes internally.",
            "Cooperation: when SQL accuracy depends on rules/口径, SG should route code/doc first, then structured with context attached.",
        ]
        if full_desc:
            lines.append(f"Description: {full_desc}")
        return "\n".join(lines)

    def _get_role_by_descriptor_type(self, member: Union[SemanticDomainInfo, SemanticGroupInfo]) -> str:
        """
        根据 member 的 descriptor_type 明确 agent 角色。
        member 可以是 SemanticDomainInfo（叶子组成员）或 SemanticGroupInfo（子组）。
        AgentCard 不会具体说明 agent 是擅长代码分析等，因此 planner 必须以 descriptor_type 为权威来源。
        structured-xxx（如 structured-mysql）归为 structured 角色。
        """
        dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or ""
        if dt in self._DESCRIPTOR_TYPE_ROLE:
            return self._DESCRIPTOR_TYPE_ROLE[dt]
        if dt.startswith("structured-"):
            return self._DESCRIPTOR_TYPE_ROLE["structured"]
        if "unstructured" in dt:
            return self._DESCRIPTOR_TYPE_ROLE["unstructured"]
        return f"Capability: {dt or 'unknown'}. Role not predefined."

    def _build_name_to_agent_map(self) -> Dict[str, Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
        """构建 agent_name -> (member_info, AgentCard) 的映射。"""
        name_to_agent: Dict[str, Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]] = {}
        for sd, ac in self.group_agent_cards:
            agent_name = getattr(ac, "name", "") or ""
            if agent_name:
                name_to_agent[agent_name] = (sd, ac)
        return name_to_agent

    async def _react_invoke_agent_callback(
        self,
        sd: Union[SemanticDomainInfo, SemanticGroupInfo],
        agent_card: AgentCard,
        query_text: str,
        httpx_client: Optional[httpx.AsyncClient] = None,
        invoke_context: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """ReActRunner callback: invoke a single agent via A2A with proper answer_model."""
        try:
            dt = (getattr(sd, 'descriptor_type', '') or "").strip().lower()
            meta_answer_model = self._answer_model_for_descriptor_type(dt)
            agent_name = getattr(agent_card, "name", "") or "(unknown)"
            logger.info(
                "[SGExpert][ReAct] dispatch to agent=%s descriptor_type=%s query_preview=%s code_ctx=%d doc_ctx=%d",
                agent_name, dt, query_text[:120],
                len((invoke_context or {}).get("code_contexts", [])),
                len((invoke_context or {}).get("doc_contexts", [])),
            )
            code_contexts = (invoke_context or {}).get("code_contexts") or None
            doc_contexts = (invoke_context or {}).get("doc_contexts") or None
            payload = self._build_send_message_payload(
                query_text,
                code_contexts=code_contexts,
                doc_contexts=doc_contexts,
            )
            payload.setdefault('metadata', {})['answer_model'] = meta_answer_model
            if httpx_client is not None:
                result = await self._fetch_knowledge_from_agent(httpx_client, payload, sd, agent_card)
            else:
                async with httpx.AsyncClient(timeout=120.0) as _client:
                    result = await self._fetch_knowledge_from_agent(_client, payload, sd, agent_card)
            _, text = result
            return text or "(agent returned empty result)"
        except Exception as e:
            logger.warning("[SGExpert][ReAct] agent call failed: %s", e)
            return f"(error calling agent: {e})"

    @staticmethod
    def _agent_display_name(full_name: str, name_to_agent: Dict[str, Tuple[Union["SemanticDomainInfo", "SemanticGroupInfo"], "AgentCard"]]) -> str:
        """Return a human-readable label: BaseName(ns/dd_name:type) or BaseName(group:name) for logging."""
        short = full_name.split("-dd-")[0] if "-dd-" in full_name else full_name
        entry = name_to_agent.get(full_name)
        if not entry:
            return short
        member = entry[0]
        dt = (getattr(member, 'descriptor_type', '') or "").strip()
        if dt == "group":
            gname = (getattr(member, 'group_name', '') or "").strip()
            return f"{short}(group:{gname})" if gname else f"{short}(group)"
        ns = (getattr(member, 'dd_namespace', '') or "").strip()
        dd = (getattr(member, 'dd_name', '') or "").strip()
        return f"{short}({ns}/{dd}:{dt})" if ns and dd else short

    async def _plan_execution_order(self) -> List[Dict[str, Any]]:
        """
        使用 LLM 分析所有 agent 的能力描述，动态决定执行顺序和上下文传递关系。

        返回执行计划列表，每个元素代表一个执行阶段：
        [
            {"phase": 1, "agents": ["CodeAgent", "DocAgent"], "context_from": []},
            {"phase": 2, "agents": ["ChatBIAgent"], "context_from": ["CodeAgent", "DocAgent"]}
        ]

        如果 LLM 调用失败或返回无效 JSON，回退到默认策略：所有 agent 在 Phase 1 并行执行。
        """
        all_names = [getattr(ac, "name", "") or "(unknown)" for _, ac in self.group_agent_cards]
        fallback_plan = [{"phase": 1, "agents": all_names, "context_from": []}]

        # 只有 1 个 agent 时无需 LLM 规划
        if len(self.group_agent_cards) <= 1:
            logger.info("[ExecutionPlanner] Only %d agent(s), skip LLM planning", len(self.group_agent_cards))
            return fallback_plan

        # 收集每个 agent 的元数据。以 descriptor_type 为权威来源明确每个 agent 适合干什么，
        # AgentCard.description 通常不会说明这些，故不依赖。
        agent_info_lines: List[str] = []
        for i, (member, ac) in enumerate(self.group_agent_cards, 1):
            agent_name = getattr(ac, "name", "") or "(unknown)"
            dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or "unknown"
            role = self._get_role_by_descriptor_type(member)
            agent_info_lines.append(
                f"{i}. Name: {agent_name}\n"
                f"   descriptor_type: {dt}\n"
                f"   Suitable for: {role}"
            )

        agent_list_str = "\n\n".join(agent_info_lines)

        system_prompt = (
            "You are an intelligent orchestrator that plans the execution order of multiple AI agents.\n"
            "Each agent's role is defined by its descriptor_type (from semantic domain). Use this as the authoritative source.\n\n"
            "descriptor_type reference:\n"
            "- code: Retrieves/analyzes source code from repositories. Contains business logic, field mappings, "
            "validation rules, data models, and table relationships that are NOT in the database schema. "
            "Useful when: (1) user wants to see code/implementation, OR (2) a structured agent also exists and "
            "the code context can help it generate more accurate SQL (business logic lives in code, not in DB).\n"
            "- unstructured: A semantic domain's document knowledge base. "
            "Retrieves and analyzes all documents within the domain — API specs, design docs, "
            "data dictionaries, business rules, field descriptions, manuals, etc. "
            "If this domain is relevant to the user query, the unstructured agent MUST be included "
            "in Phase 1 as foundational knowledge context. It is NOT limited to documentation lookup; "
            "it is the domain's knowledge backbone that provides context for ALL downstream agents.\n"
            "- structured (including structured-mysql, structured-postgres, etc.): Queries databases, generates SQL, "
            "data analysis, charts. ONLY useful when the user wants to query actual data, get statistics, or generate reports.\n"
            "- group: A composite child-group agent that encapsulates an entire sub-domain with its own internal agents. "
            "Treat it as a black-box domain expert. INCLUDE if the user query overlaps with its domain description. "
            "It runs independently — no context_from is typically needed unless multiple group agents produce "
            "complementary results.\n\n"
            "You MUST think step by step (Chain-of-Thought) and write your reasoning into the \"reasoning\" field.\n\n"
            "## Thinking Steps (write into the \"reasoning\" field)\n\n"
            "Step 1 — Extract Intent: What is the user's core intent? Strip away filler words and identify "
            "the key action (query data? view code? read docs? mixed?).\n\n"
            "Step 2 — Match Capabilities: For each available agent, does its descriptor_type match the intent? "
            "Write out your judgment for EVERY agent (include or exclude, with a brief reason).\n\n"
            "Step 3 — Apply Co-existence Rule:\n"
            "  A) unstructured agent is the DOMAIN KNOWLEDGE BASE. If the domain contains an unstructured "
            "agent and the domain is relevant to the query, ALWAYS include it in Phase 1. "
            "Do NOT guess what documents it contains — it holds all of the domain's documentation "
            "(API specs, design docs, field descriptions, business rules, etc.). "
            "It provides foundational context for ALL other agents in the domain.\n"
            "  B) If BOTH code and structured agents exist:\n"
            "  - If the query involves data querying (SQL, statistics, reports, data analysis), "
            "INCLUDE BOTH: code agent in Phase 1 (provides business logic context), "
            "structured agent in Phase 2 with context_from code agent (generates more accurate SQL). "
            "Business logic (soft-delete flags, status filters, computed fields, table joins) lives in code, not in DB schema.\n"
            "  - If the query is ONLY about code/implementation with NO data query intent, EXCLUDE structured agent.\n"
            "  - Only EXCLUDE code agent from a data query if NO structured agent exists in the group.\n"
            "  C) When code, unstructured, AND structured all coexist and the domain is relevant: "
            "INCLUDE all three — code and unstructured in Phase 1 as foundational context providers, "
            "structured in Phase 2 with context_from both.\n\n"
            "Step 4 — Determine Exclusions:\n"
            "  - API docs/parameters/error codes (no data query intent) → EXCLUDE structured agents\n"
            "  - Deployment/installation manuals → EXCLUDE code and structured agents\n"
            "  - Pure code questions (no data intent) → EXCLUDE structured agents\n"
            "  - unstructured agents: DO NOT try to guess what documents they contain. "
            "They are domain knowledge bases. EXCLUDE them ONLY when the entire domain is irrelevant "
            "to the query — not when you think the docs \"might not be helpful.\"\n"
            "  - The query spans multiple domains (e.g., \"check the code AND query the data\") → INCLUDE all relevant\n"
            "  - The query is genuinely ambiguous → INCLUDE rather than exclude\n\n"
            "Step 5 — Plan Phases: For included agents, determine execution order:\n"
            "  - Foundational context providers (code, documents) → earlier phases\n"
            "  - Context consumers (SQL generation, data analysis) → later phases with context_from\n"
            "  - Independent agents within the same phase run in parallel\n"
            "  - context_from must only reference agents from earlier phases\n\n"
            "## Output Format\n"
            "Call the plan_execution tool with your execution plan.\n\n"
            "Important:\n"
            "- The \"reasoning\" field MUST contain your step-by-step thinking following all 5 steps. Do NOT skip it.\n"
            "- Every agent MUST appear either in execution_plan or in excluded_agents, not both.\n"
            "- Every excluded_agents item MUST contain the exact agent name in \"name\" and a brief explanation in \"reason\".\n"
            "- excluded_agents can be an empty list if all agents are relevant.\n"
            "- Only keep excluded_agents empty when the query genuinely needs ALL agent types.\n"
            "- Including unnecessary agents wastes resources and slows down response time. Be precise."
        )

        human_content = f"User Query: {self.query}\n\nAvailable Agents:\n{agent_list_str}"
        upstream_k = (self.metadata or {}).get("upstream_prior_knowledge", "") or ""
        upstream_k = str(upstream_k).strip()
        if upstream_k:
            human_content = (
                "【来自上游编排的前序任务结果】（供分解代理与阶段执行参考；用户需求以 User Query 为准）\n"
                f"{upstream_k}\n\n"
                + human_content
            )

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content),
            ]
            logger.info("[ExecutionPlanner] LLM 规划开始 | agent 数: %d", len(self.group_agent_cards))

            plan_execution_tool = StructuredTool(
                name="plan_execution",
                description="Plan the execution order of agents with phase-level parallelism and context routing.",
                args_schema=ExecutionPlanResult,
                func=None,
                coroutine=None,
            )

            result = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                metadata=self.metadata,
                fallback_formatter=self.format_llm_output,
                tool=plan_execution_tool,
                messages=messages,
                tool_choice="plan_execution",
                span_name="expert-plan-execution",
                span_input={"query": self.query},
            )

            if result is None:
                logger.warning("[ExecutionPlanner] tool call 返回 None，使用 fallback")
                return fallback_plan

            plan_data = result
            if not isinstance(plan_data, dict):
                logger.warning("[ExecutionPlanner] plan_data 不是 dict，使用 fallback")
                return fallback_plan

            reasoning = plan_data.get("reasoning", "")
            self._last_planning_reasoning = reasoning
            if reasoning:
                logger.info("[ExecutionPlanner] LLM reasoning: %s", reasoning)

            execution_plan = plan_data.get("execution_plan", [])

            if not isinstance(execution_plan, list) or len(execution_plan) == 0:
                logger.warning("[ExecutionPlanner] execution_plan 为空或无效，使用 fallback")
                return fallback_plan

            # 解析 excluded_agents：LLM 判定与用户问题不相关的 agent
            excluded_agents_raw = plan_data.get("excluded_agents", [])
            excluded_names: set = set()
            excluded_reasons: Dict[str, str] = {}
            if isinstance(excluded_agents_raw, list):
                for item in excluded_agents_raw:
                    if isinstance(item, dict):
                        name = (item.get("name") or "").strip()
                        reason = (item.get("reason") or "").strip()
                        if name:
                            excluded_names.add(name)
                            excluded_reasons[name] = reason

            # 验证计划：区分"被排除"和"被遗漏"的 agent
            planned_names: set = set()
            for phase_info in execution_plan:
                for name in phase_info.get("agents", []):
                    planned_names.add(name)

            all_names_set = set(all_names)
            not_in_plan = all_names_set - planned_names
            truly_missing = not_in_plan - excluded_names
            if truly_missing:
                logger.warning("[ExecutionPlanner] 计划遗漏 agent（非排除）: %s，已补入 Phase 1", truly_missing)
                phase1_found = False
                for phase_info in execution_plan:
                    if phase_info.get("phase") == 1:
                        phase_info["agents"].extend(list(truly_missing))
                        phase1_found = True
                        break
                if not phase1_found:
                    execution_plan.insert(0, {"phase": 0, "agents": list(truly_missing), "context_from": []})

            # 按 phase 排序
            execution_plan.sort(key=lambda x: x.get("phase", 1))

            # 输出直观的执行计划（包含 dd 信息以区分同名 agent）
            _nta = self._build_name_to_agent_map()
            plan_lines = ["[ExecutionPlanner] 执行计划:"]
            for phase_info in execution_plan:
                p = phase_info.get("phase", 0)
                agents = phase_info.get("agents", [])
                ctx = phase_info.get("context_from", [])
                agents_display = [self._agent_display_name(a, _nta) for a in agents]
                if ctx:
                    ctx_display = [self._agent_display_name(c, _nta) for c in ctx]
                    plan_lines.append(f"  Phase {p}: {', '.join(agents_display)} (上下文来自: {', '.join(ctx_display)})")
                else:
                    plan_lines.append(f"  Phase {p}: {', '.join(agents_display)}")
            if excluded_names:
                plan_lines.append("  排除的 agent:")
                for name in excluded_names:
                    display = self._agent_display_name(name, _nta)
                    reason = excluded_reasons.get(name, "(未提供原因)")
                    plan_lines.append(f"    - {display}: {reason}")
            logger.info("\n".join(plan_lines))

            return execution_plan

        except Exception as e:
            logger.warning("[ExecutionPlanner] LLM 规划失败: %s，使用 fallback (全部 Phase 1 并行)", e)
            return fallback_plan

    def _build_send_message_payload(self, query_text: str, extra_context: str = "",
                                     code_contexts: Optional[List[str]] = None,
                                     doc_contexts: Optional[List[str]] = None) -> Dict[str, Any]:
        """构建 A2A 发送消息的 payload。extra_context 通过 metadata 传递，不污染 query。"""
        upstream_metadata = self.metadata if isinstance(self.metadata, dict) else {}
        metadata: Dict[str, Any] = {
            'user_id': upstream_metadata.get('user_id', ''),
            'run_id': upstream_metadata.get('run_id', ''),
            'trace_id': upstream_metadata.get('trace_id', ''),
            'answer_model': 'original',
        }
        if upstream_metadata.get('propagated_history'):
            metadata['propagated_history'] = upstream_metadata.get('propagated_history')
        if extra_context:
            metadata['extra_context'] = extra_context
        if code_contexts:
            metadata['code_contexts'] = code_contexts
        if doc_contexts:
            metadata['doc_contexts'] = doc_contexts
        logger.debug(
            "[SGExpert] downstream metadata ready: user_id=%s run_id=%s extra_context_len=%d code_contexts=%d doc_contexts=%d",
            metadata.get('user_id', ''),
            metadata.get('run_id', ''),
            len(extra_context or ""),
            len(code_contexts or []),
            len(doc_contexts or []),
        )
        return {
            'message': {
                'role': 'user',
                'parts': [{'type': 'text', 'text': query_text}],
                'messageId': uuid4().hex,
            },
            'metadata': metadata,
        }

    def _format_agent_results(
        self,
        agents: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]],
        results: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], str]],
        start_idx: int = 1,
    ) -> List[str]:
        """
        将 agent 返回的结果格式化为结构化的知识块列表，并打印日志。
        返回 knowledge_parts 列表。
        """
        knowledge_parts: List[str] = []
        for i, ((member, agent_card), (_, text)) in enumerate(zip(agents, results)):
            idx = start_idx + i
            agent_name = getattr(agent_card, "name", "") or "(no name)"
            agent_short = agent_name.split("-dd-")[0] if "-dd-" in agent_name else agent_name
            dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or "(unknown)"
            if dt == "group":
                member_label = f"group/{getattr(member, 'group_name', '') or 'unknown'}"
            else:
                ns = getattr(member, 'dd_namespace', '') or ''
                dd = getattr(member, 'dd_name', '') or getattr(member, 'semantic_domain_id', '') or 'sd'
                member_label = f"{ns}/{dd}"
            char_len = len(text) if text else 0
            preview = text if text else "(空)"
            preview = preview.replace("\n", " ").strip()

            logger.info("[知识块 %s] %s (%s) | %d 字符 | %s", idx, agent_short, member_label, char_len, preview)

            if text:
                block = (
                    f"【智能体 {idx}】\n"
                    f"名称: {agent_name}\n"
                    f"领域: {member_label}\n"
                    f"类型: {dt}\n"
                    f"知识/回答:\n{text}"
                )
                knowledge_parts.append(block)
        return knowledge_parts

    async def get_knowledge(self) -> str:
        """
        统一 ReAct 知识获取：所有 member agent（code / doc / structured / group）均为工具，
        LLM 在循环内按需调用；向上游仅返回 ReAct 综合答案。
        """
        if not self.group_agent_cards:
            return ""

        query = self.query
        prior_context = str(
            (self.metadata or {}).get("upstream_prior_knowledge", "") or ""
        ).strip()
        name_to_agent = self._build_name_to_agent_map()
        qp = self._query_preview_for_progress(query)
        agent_names = [getattr(ac, "name", "") or "(unknown)" for _, ac in self.group_agent_cards]
        agents_display = ", ".join(
            self._agent_display_name(n, name_to_agent) for n in agent_names
        ) or "-"

        logger.info(
            "[SemanticGroup] get_knowledge 开始 (unified ReAct) | agents=%d | %s",
            len(self.group_agent_cards), agents_display,
        )

        await self.emit_progress(
            "phase_started",
            message=self._truncate_progress_message(
                f"ReAct START | query: {qp} | {len(self.group_agent_cards)} agent tool(s): {agents_display}",
                560,
            ),
            status="running",
            extra={
                "phase": 1,
                "total_phases": 1,
                "agent_count": len(self.group_agent_cards),
                "query_preview": qp,
                "parallel_agents": self._truncate_progress_message(agents_display, 500),
                "context_from": "upstream_prior_knowledge" if prior_context else "",
            },
        )

        async def _react_progress_emitter(
            event: str,
            *,
            message: str,
            status: str = "running",
            extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            await self.emit_progress(
                event,
                message=message,
                status=status,
                extra=extra,
            )

        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        async with httpx.AsyncClient(timeout=120.0) as httpx_client:
            react_result = await self.react_runner.run(
                user_query=query,
                prior_context=prior_context,
                agents=self.group_agent_cards,
                name_to_agent=name_to_agent,
                user_id=metadata.get("user_id", ""),
                run_id=metadata.get("run_id", ""),
                trace_id=metadata.get("trace_id", ""),
                httpx_client=httpx_client,
                react_max_steps=20,
                nudge_retries=2,
                progress_emitter=_react_progress_emitter,
            )

        react_trace = getattr(self.react_runner, "last_run_trace", None) or {}
        await self.emit_progress(
            "phase_finished",
            message=self._truncate_progress_message(
                f"ReAct DONE | query: {qp} | result: {len(react_result)} chars",
                560,
            ),
            status="done",
            extra={
                "phase": 1,
                "total_phases": 1,
                "ok_count": 1,
                "agent_count": len(self.group_agent_cards),
                "query_preview": qp,
                "parallel_agents": self._truncate_progress_message(agents_display, 500),
                "react_status": react_trace.get("status", ""),
                "react_steps": react_trace.get("steps", 0),
            },
        )

        logger.info(
            "[SemanticGroup] get_knowledge 完成 | 返回 ReAct 综合答案 (%d chars)",
            len(react_result),
        )
        return react_result

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
            knowledge = await self.get_knowledge()
            return knowledge
        except Exception as e:
            logger.error(f"step error : {e}")
            return f"No relevant knowledge available to answer the question: {self.original_query}"


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

        logger.debug(f"************** agent run, query: {self.query} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if self.query:
            self.update_memory("user", self.query)

        # Resolve semantic group members -> agent registry for A2A (get_knowledge will use group_agent_cards)
        if self.semantic_group_id:
            await self.resolve_agents_for_semantic_group()
            downstream_agents = [
                getattr(ac, "name", "") or str(getattr(member, "group_name", "") or getattr(member, "dd_name", "") or "")
                for member, ac in self.group_agent_cards[:5]
            ]
            downstream_list = [x for x in downstream_agents if x]
            await self.emit_progress(
                "group_members_resolved",
                message=f"discovered {len(self.group_agent_cards)} downstream agent(s)",
                status="done",
                extra={
                    "agent_count": len(self.group_agent_cards),
                    "downstream_agents": downstream_list,
                },
            )

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1

                current_task = self.metadata.get('current_task', '')

                logger.info(f"******************** {current_task}, current query: {self.query}, Executing step {self.current_step}/{self.max_steps}")

                step_result = await self.step()

                step_result = f"step {self.current_step}/{self.max_steps}: query: {self.query}\n\nanswer:\n{step_result}\n"

                yield step_result

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class ExpertAgentExecutorSemanticGroup(AgentExecutor):
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
        semantic_group_id:str = None,
        agent_id: str = None,
        data_services_url: str = None,
        max_steps:int = 5

    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.semantic_group_id=semantic_group_id
        self.agent_id = agent_id
        self.data_services_url=data_services_url
        self.stream_enabled = stream
        self.max_steps = max_steps

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()

        metadata = context.metadata
        logger.info(f"=====user request metadata is {metadata}.")
        _upk = (metadata or {}).get("upstream_prior_knowledge") if isinstance(metadata, dict) else None
        _upk_s = str(_upk or "").strip()
        if _upk_s:
            logger.info(
                "[Execute][SemanticGroupExpert] upstream_prior_knowledge (%d chars):\n%s",
                len(_upk_s),
                _upk_s,
            )
        else:
            logger.info(
                "[Execute][SemanticGroupExpert] upstream_prior_knowledge: (absent or empty) raw=%r",
                _upk,
            )

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
            semantic_group_id=self.semantic_group_id,
            data_services_url=self.data_services_url,
            query=query,
            metadata=metadata,
            max_steps=self.max_steps,
            current_tasks_status=current_tasks_status,
            current_task_id=current_task_id,
            agent_id=self.agent_id or self.semantic_group_id,
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        try:
            async def _progress_callback(text: str) -> None:
                await updater.add_artifact(
                    [TextPart(text=text)],
                    name=f'{agent.agent_name}-result',
                )

            agent.progress_callback = _progress_callback
            if self.stream_enabled:
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
            await agent.data_services_client.close()

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')