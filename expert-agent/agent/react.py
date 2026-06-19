import asyncio
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
from uuid import uuid4
import httpx
from a2a.types import AgentCard
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field
from .dataservices_client import SemanticDomainInfo, SemanticGroupInfo

try:
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _json_repair = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

langfuse = get_client()
_langfuse_handler = CallbackHandler()

MemberInfo = Union[SemanticDomainInfo, SemanticGroupInfo]
InvokeContext = Dict[str, List[str]]
ProgressEmitter = Callable[..., Awaitable[None]]

_LLM_MAX_RETRIES = max(0, int(os.getenv("SG_REACT_LLM_MAX_RETRIES", "3")))
_LLM_RETRY_BASE_DELAY_SEC = float(os.getenv("SG_REACT_LLM_RETRY_BASE_DELAY", "1.0"))
_LLM_RETRY_MAX_DELAY_SEC = float(os.getenv("SG_REACT_LLM_RETRY_MAX_DELAY", "30.0"))
_REACT_LOG_PREVIEW_CHARS = max(200, int(os.getenv("SG_REACT_LOG_PREVIEW_CHARS", "1200")))
_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _extract_http_status_code(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _is_llm_retryable(exc: BaseException) -> bool:
    """Transient LLM failures: timeout, network, 429, 5xx. No retry for other 4xx."""
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
    )):
        return True

    status = _extract_http_status_code(exc)
    if status is not None:
        if status in _TRANSIENT_HTTP_STATUS_CODES:
            return True
        if 400 <= status < 500:
            return False
        if status >= 500:
            return True

    msg = str(exc).lower()
    transient_hints = (
        "rate limit", "ratelimit", "too many requests", "timeout", "timed out",
        "connection reset", "connection refused", "temporarily unavailable",
        "service unavailable", "overloaded", " 429", " 502", " 503", " 504",
    )
    if any(h in msg for h in transient_hints):
        return True

    cause = exc.__cause__ or exc.__context__
    if cause and cause is not exc:
        return _is_llm_retryable(cause)
    return False


def _valid_langfuse_trace_id(trace_id: str) -> bool:
    if not trace_id or len(trace_id) != 32:
        return False
    try:
        int(trace_id, 16)
        return True
    except ValueError:
        return False


def _normalize_descriptor_type(member: MemberInfo) -> str:
    return (getattr(member, "descriptor_type", "") or "").strip().lower() or "unknown"


def _is_structured_type(dt: str) -> bool:
    return dt == "structured" or dt.startswith("structured-")


def _tool_type_prefix(dt: str) -> str:
    if dt == "code":
        return "code"
    if dt == "unstructured" or "unstructured" in dt:
        return "doc"
    if _is_structured_type(dt):
        return "structured"
    if dt == "group":
        return "group"
    return "agent"


_REACT_SYSTEM_PROMPT_TEMPLATE = """\
You are {sg_name}, a **Semantic Group (SG) orchestrator**. You route questions to specialized agents and synthesize their answers. You do NOT decompose tasks into implementation steps — that is the job of each **Semantic Domain (SD) Expert** behind every tool.

## SG vs SD Boundary (CRITICAL)

- Each tool is a **black-box SD Expert** with full access to its domain (code repo, docs, database, etc.).
- **Your job**: (1) choose which agent tool(s) to call, (2) decide call order when the user implies sequence (e.g. "先看代码再查数"), (3) synthesize the final answer.
- **NOT your job**: writing SQL, naming tables/columns, DESCRIBE/SELECT statements, "show entity class", API paths, or other implementation-level sub-tasks. The SD Expert does that internally.
- When calling a tool, pass the **user's question with original semantics preserved**. Default: use the **User Question** below as the tool `query` verbatim or with minimal trimming — do NOT rewrite into technical instructions.
- Do NOT split one user question into micro-tasks like "查询 users 表结构" or "搜索 User 实体类 created_at 字段" unless the user explicitly asked for only that narrow slice.

## Execution Protocol (Layered ReAct)

Every turn follow this loop:

1. **Action**: Call one or more agent tools, OR call `finish` when you have enough evidence. Pass preserved semantic queries to tools.

2. **Observation**: Read tool results and decide the next action.

3. **Structured Thought** (optional but recommended): When helpful, include a JSON hint in your message `content` to track progress:
```json
{{
  "sub_goals": ["distinct information needs from the user question"],
  "satisfied": ["sub-goals already met, with brief evidence"],
  "gaps": ["sub-goals still missing"],
  "planned_action": "finish | call:<tool_name> | ...",
  "confidence": "high | medium | low"
}}
```
This hint helps planning and debugging; missing it does NOT block tool calls or `finish`.

4. **Execution Analysis** (on-demand): When the process is stuck, you may receive an **Execution Analysis** block with deep diagnosis. Follow its `next_action` — do NOT blindly retry the same tool/query.

## Critical Rules

- NEVER guess or fabricate data. Query agent tools when you need domain-specific information.
- Route to **structured** tools when the user needs live data/statistics; route to **code** or **doc** when they need rules/implementation/documentation — but always pass **user wording**, not your own SQL/code rewrite.
- If a tool returns the same summary regardless of your query, update gaps and `planned_action` to use a **different-capability** tool; set confidence to `low` if unsure.
- Prefer **sequential** calls (e.g. code then structured) when the user asks to learn rules first then query data; avoid parallel calls that duplicate the same semantic question across agents.
- Call `finish` before exceeding {max_steps} turns.

## Evidence priority (CRITICAL — applies to `finish` and all synthesis)

When the user asks for **entity-specific facts** (e.g. which user bought order ORD-*, a user's profile, payment records for a named order/user):

1. **Structured tool results are authoritative** for whether that entity exists and what live data says.
2. If **any structured** observation states **无法确认 / 无法回答 / task fail / cannot confirm** the user’s business identifier (order number, user for that order, etc.), you **MUST NOT** override that with doc or code observations — even if doc/code mentioned example users, sample `order_id`, or schema hints.
3. **Doc** and **code** tools provide **reference only**: field meanings, API shapes, example payloads, table lists, “no payment module” architecture facts. They do **NOT** resolve “order ORD-X → user Y” unless structured has successfully confirmed the same entity.
4. **Never map** the user’s business key (e.g. string order number `ORD-2025-00001`) to an example integer `order_id` or sample user from docs/code and present it as the answer to the user’s question.
5. When calling `finish` after structured failure on entity resolution: state clearly that the entity could not be confirmed; you may add non-entity facts from doc/code (e.g. no payment table exists) **without** inventing order→user linkage.

If structured succeeded and doc/code only add口径 or supplementary fields, merge normally with structured as the factual core.

## Context Routing: When code/doc should accompany SQL (SG-level analysis)

Before routing to a **structured** (SQL) agent, analyze whether accurate data retrieval depends on **business rules or field semantics** from code or docs. This is SG-level **capability routing** — you decide **whether** code/doc context is needed, not **how** to implement SQL.

**Usually call code and/or doc BEFORE structured** (sequential, same user semantics) when the question involves:
- Business rules affecting data: valid/invalid records, soft delete, status filters, "有效订单/用户", eligibility
- Metric definitions: 销售额/退费率/注册数 的统计口径、计算公式
- Unclear field meaning: which column represents "registration time", "sales amount", etc.
- User explicitly asks: 先看代码/文档、根据业务规则、结合实现/口径
- Prior structured result looks incomplete, inconsistent, or missing rule-based filters

**Structured alone is often enough** when:
- The question is a straightforward aggregate/list with no business-rule nuance (e.g. "count all rows" with no filter semantics)
- Upstream prior context or a prior code/doc observation already established the rules
- The user only wants raw data and did not mention rules, code, docs, or definitions

**Cooperation pattern (preserve user wording at each step):**
1. If foundation needed → call **code** and/or **doc** first with the **same user question** (or the rule-related part in user wording).
2. Then call **structured** with the **same user question** for the data part. The system automatically attaches prior code/doc observations to the structured agent (`code_contexts` / `doc_contexts`).
3. Do NOT parallel-call structured together with code/doc when structured depends on that foundation — code/doc must complete first.

In Structured Thought (optional), you may track: `"needs_code_or_doc_for_sql": true/false` and `"foundation_satisfied": true/false` to guide routing.

## Available Agent Tools

Each tool accepts a natural language `query` (user semantics preserved) and returns that SD Expert's answer.

{agent_tools_description}

## Upstream Prior Context (from orchestrator)

{prior_context}

## User Question

{user_query}
"""

_REACT_NUDGE_MESSAGE = (
    "You did not call any tool. Call at least one agent tool with the user's question (preserve original semantics), "
    "or call `finish` if you already have sufficient evidence to answer."
)

_REACT_FORCE_FINISH_MESSAGE = (
    "Stop writing plain text or JSON planning blocks. "
    "You MUST call the `finish` tool now with `final_answer` set to the complete user-facing answer "
    "synthesized from all prior tool observations in this conversation."
)

_REACT_STEP_ANALYSIS_PROMPT = """\
You are an execution analyst for a multi-agent ReAct orchestrator. Your job is to **intelligently diagnose the execution process** — not to blindly suggest "try another agent".

## User Question
{user_query}

## This Step (Step {step_no})
Thought: {thought}

Tool calls and results:
{step_observations}

## Prior Step Analyses
{prior_analyses}

## Observations accumulated so far
{accumulated_summary}

## Available Agent Tools
{tool_summaries}

## Your Analysis Task

Think step by step:

1. **Sub-goals**: Break the user question into distinct information needs (e.g. "top 10 sales", "return rates").
2. **Coverage**: Which sub-goals are already satisfied? Quote specific evidence from observations.
3. **Gaps**: What is still missing?
4. **Process diagnosis** (most important): For EACH tool call this step:
   - Did the query match this tool's described capability?
   - Did the result actually answer the query, or return unrelated/cached/fixed-summary data?
   - If the same tool returned identical output despite a different query, what does that imply about the tool's scope?
   - Was retrying this tool rational, or a dead loop?
5. **Context routing for accurate SQL** (SG-level, NOT SQL authoring):
   - Does the user question require business rules, metric definitions, or field semantics from **code** or **doc** before structured data is trustworthy?
   - Was structured called **without** prior code/doc when foundation was needed? If yes → recommend `call:code_*` or `call:doc_*` first, then structured again with same user semantics.
   - Was structured called in parallel before code/doc finished? If foundation was needed → recommend sequential retry: code/doc → structured.
   - If code/doc already ran and structured still fails → diagnose whether wrong agent, wrong semantic gap, or SD internal issue — do NOT rewrite into SQL/table micro-tasks.
6. **Next action** — pick exactly ONE:
   - `finish` — all sub-goals satisfied with evidence; explain why
   - `call:<tool_name>` — route to a different SD Expert; **next_query must preserve user semantics**, NOT implementation rewrite
   - `reformulate:<tool_name>` — retry same agent only if prior query diverged from user intent; still preserve semantics
   - `stop_retry:<tool_name>` — do NOT call this tool again; explain why and what to use instead

IMPORTANT: SG orchestrator must NOT invent SQL, schema commands, or code-search micro-tasks in next_query. Pass the user's question; let the SD Expert decompose.

Output ONLY valid JSON (no markdown):
{{"sub_goals": ["..."], "satisfied": ["..."], "gaps": ["..."], "needs_code_or_doc_for_sql": true|false, "foundation_satisfied": true|false, "diagnosis": "...", "next_action": "finish|call:xxx|reformulate:xxx|stop_retry:xxx", "next_tool": "tool_name or empty", "next_query": "query or empty", "reasoning": "..."}}
"""

_REACT_SUCCESS_STATUSES = frozenset({"completed", "forced_finish"})

_FINISH_TOOL_DESCRIPTION = (
    "Submit the final answer when ready. "
    "For entity facts (order owner, user profile, payments for a named order/user): "
    "if structured tools reported 无法确认/cannot confirm/task fail, you MUST say the entity "
    "could not be confirmed — do NOT override with doc/code sample data (e.g. example order_id or 张三). "
    "Doc/code may only supplement non-entity facts (field types, no payment module, etc.)."
)


class _FinishArgs(BaseModel):
    final_answer: str = Field(
        description=(
            "Complete final answer. Entity-specific facts (who owns order X, user details for that order) "
            "must come from structured tools unless structured confirmed them; if structured failed or "
            "said 无法确认, do not use doc/code examples as substitute. Reference-only doc/code may explain "
            "schema or missing modules without inventing order→user mappings."
        )
    )


class _AgentQueryArgs(BaseModel):
    query: str = Field(
        description=(
            "User-facing question for this SD Expert agent. Preserve the original user semantics; "
            "do NOT rewrite into SQL, DESCRIBE/SELECT, table/column names, or code-search instructions."
        )
    )


class ReActRunner:
    """ReAct tool-calling loop for all SG member agents."""

    def __init__(
        self,
        llm: Any,
        *,
        invoke_agent: Callable[
            [MemberInfo, AgentCard, str, Optional[httpx.AsyncClient], Optional[InvokeContext]],
            Awaitable[str],
        ],
        build_tool_description: Callable[
            [MemberInfo, AgentCard, Dict[str, Tuple[MemberInfo, AgentCard]]],
            str,
        ],
        agent_name: str = "SGExpert",
    ):
        self.llm = llm
        self.invoke_agent = invoke_agent
        self.build_tool_description = build_tool_description
        self.agent_name = agent_name
        self.last_run_trace: Dict[str, Any] = {}
        self._llm_retry_events: List[Dict[str, Any]] = []

    def _snapshot_run_trace(self, **fields: Any) -> Dict[str, Any]:
        trace = {"llm_retry_events": list(self._llm_retry_events)}
        trace.update(fields)
        return trace

    @staticmethod
    def _truncate_progress_message(text: str, limit: int = 480) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if len(raw) <= limit:
            return raw
        return raw[: limit - 3] + "..."

    @staticmethod
    async def _emit_progress(
        emitter: Optional[ProgressEmitter],
        event: str,
        *,
        message: str,
        status: str = "running",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if emitter is None:
            return
        try:
            await emitter(event, message=message, status=status, extra=extra or {})
        except Exception as exc:
            logger.debug("[ReAct] progress emit failed event=%s: %s", event, exc)

    @staticmethod
    def sanitize_tool_name(raw_name: str) -> str:
        sanitized: List[str] = []
        for ch in raw_name.strip():
            if ch.isalnum() or ch in ("_", "-"):
                sanitized.append(ch.lower())
            else:
                sanitized.append("_")
        name = "".join(sanitized)
        if name and not name[0].isalpha():
            name = "agent_" + name
        name = re.sub(r"_+", "_", name).strip("_")
        return name or "unknown_agent"

    @classmethod
    def make_tool_name(cls, member: MemberInfo, agent_card: AgentCard) -> str:
        dt = _normalize_descriptor_type(member)
        prefix = _tool_type_prefix(dt)
        raw = getattr(agent_card, "name", "") or ""
        short = raw.split("-dd-")[0] if "-dd-" in raw else raw
        base = cls.sanitize_tool_name(short or raw or "unknown")
        return f"{prefix}_{base}"

    async def _ainvoke_ai_message(
        self,
        llm: Any,
        messages: List[Any],
        *,
        config: Optional[Dict[str, Any]] = None,
        timeout: float = 120.0,
        max_retries: Optional[int] = None,
        call_label: str = "react",
    ) -> Any:
        retries = _LLM_MAX_RETRIES if max_retries is None else max(0, max_retries)
        invoke_config = config or {"callbacks": [_langfuse_handler]}
        last_exc: Optional[BaseException] = None

        for attempt in range(retries + 1):
            try:
                resp = await asyncio.wait_for(
                    llm.ainvoke(messages, config=invoke_config, stream=False),
                    timeout=timeout,
                )
                if hasattr(resp, "__aiter__"):
                    aggregated = None
                    async for chunk in resp:
                        aggregated = chunk if aggregated is None else aggregated + chunk
                    resp = aggregated
                if attempt > 0:
                    logger.info(
                        "[ReAct] LLM invoke succeeded after %d retries label=%s",
                        attempt, call_label,
                    )
                return resp
            except Exception as exc:
                last_exc = exc
                retryable = _is_llm_retryable(exc)
                if attempt >= retries or not retryable:
                    logger.warning(
                        "[ReAct] LLM invoke failed label=%s attempt=%d/%d retryable=%s error=%s",
                        call_label, attempt + 1, retries + 1, retryable, exc,
                    )
                    raise

                delay = min(
                    _LLM_RETRY_BASE_DELAY_SEC * (2 ** attempt),
                    _LLM_RETRY_MAX_DELAY_SEC,
                )
                event = {
                    "label": call_label,
                    "attempt": attempt + 1,
                    "max_attempts": retries + 1,
                    "delay_sec": delay,
                    "error": str(exc)[:500],
                    "retryable": True,
                }
                self._llm_retry_events.append(event)
                logger.warning(
                    "[ReAct] LLM invoke retry label=%s attempt=%d/%d in %.1fs: %s",
                    call_label, attempt + 1, retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM invoke failed without exception")

    def _build_agent_tools(
        self,
        agents: List[Tuple[MemberInfo, AgentCard]],
        name_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]],
    ) -> Tuple[List[StructuredTool], Dict[str, Tuple[MemberInfo, AgentCard]]]:
        tools: List[StructuredTool] = []
        tool_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]] = {}
        used_names: set[str] = set()

        for member, ac in agents:
            tool_name = self.make_tool_name(member, ac)
            suffix = 2
            while tool_name in used_names:
                tool_name = f"{self.make_tool_name(member, ac)}_{suffix}"
                suffix += 1
            used_names.add(tool_name)

            tool_description = self.build_tool_description(member, ac, name_to_agent)
            tool = StructuredTool(
                name=tool_name,
                description=tool_description,
                func=None,
                coroutine=None,
                args_schema=_AgentQueryArgs,
            )
            tools.append(tool)
            tool_to_agent[tool_name] = (member, ac)

        finish_tool = StructuredTool(
            name="finish",
            description=_FINISH_TOOL_DESCRIPTION,
            func=None,
            coroutine=None,
            args_schema=_FinishArgs,
        )
        tools.append(finish_tool)
        return tools, tool_to_agent

    @staticmethod
    def _extract_finish_answer(raw_args: Any, thought_fallback: str = "") -> str:
        """Parse final_answer from a finish tool call."""
        args = raw_args
        if isinstance(args, dict):
            inner = args.get("args")
            if isinstance(inner, dict):
                args = inner
            elif isinstance(inner, list) and inner:
                args = {"final_answer": str(inner[0])}
        final_answer = (
            str(args.get("final_answer", "") if isinstance(args, dict) else "").strip()
            or str(args).strip()
            or (thought_fallback or "").strip()
            or "Task completed"
        )
        if final_answer.startswith("{") and ("args" in final_answer or "config" in final_answer):
            final_answer = (thought_fallback or "").strip() or "Task completed"
        return final_answer

    async def _invoke_forced_finish(
        self,
        llm_non_stream: Any,
        messages: List[Any],
        finish_tool: StructuredTool,
        *,
        call_label: str = "react_force_finish",
    ) -> Optional[str]:
        """One LLM turn with only finish available (tool_choice=finish when supported)."""
        force_messages = list(messages) + [HumanMessage(content=_REACT_FORCE_FINISH_MESSAGE)]
        try:
            finish_llm = llm_non_stream.bind_tools([finish_tool], tool_choice="finish")
        except TypeError:
            finish_llm = llm_non_stream.bind_tools([finish_tool])
        ai_msg = await self._ainvoke_ai_message(
            finish_llm,
            force_messages,
            timeout=120.0,
            call_label=call_label,
        )
        thought = str(getattr(ai_msg, "content", "") or "").strip()
        for call in getattr(ai_msg, "tool_calls", None) or []:
            if call.get("name") == "finish":
                return self._extract_finish_answer(call.get("args") or {}, thought)
        return None

    async def _complete_via_finish(
        self,
        *,
        final_answer: str,
        run_status: str,
        step_no: int,
        log_reason: str,
        progress_emitter: Optional[ProgressEmitter],
        span: Any,
        tool_history: List[Dict[str, Any]],
        structured_thoughts: List[Dict[str, Any]],
        step_analyses: List[Dict[str, Any]],
        analysis_triggers: List[str],
    ) -> str:
        logger.info(
            "[ReAct] 结束 · %s；第%d步提交最终答案（共 %d 字）：%s",
            log_reason,
            step_no,
            len(final_answer),
            self._log_text_preview(final_answer),
        )
        await self._emit_progress(
            progress_emitter,
            "sg_react_finished",
            message=self._truncate_progress_message(
                f"ReAct done ({run_status}): {final_answer}",
                480,
            ),
            status="done" if run_status in _REACT_SUCCESS_STATUSES else "fail",
            extra={
                "status": run_status,
                "steps": step_no,
                "result_chars": len(final_answer),
            },
        )
        span.update_trace(output={
            "status": run_status,
            "answer": final_answer,
            "steps": step_no,
            "tool_history": tool_history,
            "step_analyses": step_analyses,
        })
        self.last_run_trace = self._snapshot_run_trace(
            status=run_status,
            steps=step_no,
            tool_history=tool_history,
            structured_thoughts=structured_thoughts,
            step_analyses=step_analyses,
            analysis_triggers=analysis_triggers,
        )
        langfuse.flush()
        return final_answer

    @staticmethod
    def _accumulate_observation(
        accumulator: InvokeContext,
        member: MemberInfo,
        result: str,
    ) -> None:
        if not result:
            return
        dt = _normalize_descriptor_type(member)
        if dt == "code":
            accumulator.setdefault("code_contexts", []).append(result)
        elif dt == "unstructured" or "unstructured" in dt:
            accumulator.setdefault("doc_contexts", []).append(result)

    @staticmethod
    def _extract_agent_query(tool_args: Any) -> str:
        raw_args = tool_args
        if isinstance(raw_args, dict) and "args" in raw_args:
            args_val = raw_args.get("args")
            if isinstance(args_val, list) and len(args_val) > 0:
                raw_args = {"query": str(args_val[0])}
            elif isinstance(args_val, dict):
                raw_args = args_val
        return str(
            raw_args.get("query", "") if isinstance(raw_args, dict) else ""
        ).strip() or str(raw_args).strip()

    @staticmethod
    def _build_accumulated_summary(tool_history: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for entry in tool_history:
            tool = entry.get("tool")
            if not tool or tool == "finish":
                continue
            query = entry.get("query", "")
            result = str(entry.get("result", ""))
            preview = result[:400] + ("..." if len(result) > 400 else "")
            parts.append(f"- [{tool}] query={query!r} → {preview}")
        return "\n".join(parts) if parts else "(No observations yet.)"

    @staticmethod
    def _loads_json_object(text: str) -> Dict[str, Any]:
        snippet = (text or "").strip()
        if not snippet:
            return {}
        try:
            parsed = json.loads(snippet)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        if _json_repair is not None:
            try:
                repaired = _json_repair(snippet, return_objects=True)
                if isinstance(repaired, dict):
                    return repaired
                if isinstance(repaired, str):
                    parsed = json.loads(repaired)
                    return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass
        return {}

    @classmethod
    def _parse_json_from_text(cls, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        parsed = cls._loads_json_object(text)
        if parsed:
            return parsed
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            parsed = cls._loads_json_object(match.group(1))
            if parsed:
                return parsed
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            parsed = cls._loads_json_object(match.group(0))
            if parsed:
                return parsed
        return {}

    @classmethod
    def _parse_structured_thought(cls, thought_text: str) -> Dict[str, Any]:
        parsed = cls._parse_json_from_text(thought_text)
        if parsed.get("sub_goals") is not None or parsed.get("gaps") is not None or parsed.get("planned_action"):
            parsed.setdefault("sub_goals", [])
            parsed.setdefault("satisfied", [])
            parsed.setdefault("gaps", [])
            parsed.setdefault("planned_action", "unknown")
            parsed.setdefault("confidence", "medium")
            parsed["valid"] = True
            return parsed
        return {
            "sub_goals": [],
            "satisfied": [],
            "gaps": [],
            "planned_action": "unknown",
            "confidence": "medium",
            "valid": False,
            "raw_thought": thought_text,
        }

    @staticmethod
    def _parse_step_analysis(raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        parsed = ReActRunner._parse_json_from_text(text)
        if parsed:
            return parsed
        return {"diagnosis": text, "next_action": "unknown", "reasoning": text}

    @staticmethod
    def _gaps_signature(gaps: List[Any]) -> Tuple[str, ...]:
        return tuple(sorted(str(g).strip().lower() for g in gaps if str(g).strip()))

    @staticmethod
    def _log_text_preview(text: str, *, max_chars: Optional[int] = None) -> str:
        limit = _REACT_LOG_PREVIEW_CHARS if max_chars is None else max(1, max_chars)
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= limit:
            return normalized or "(empty)"
        return f"{normalized[:limit]}… (+{len(normalized) - limit} chars)"

    @classmethod
    def _format_log_list(cls, values: Any, *, empty_label: str = "无") -> str:
        if not values:
            return empty_label
        if isinstance(values, list):
            if not values:
                return empty_label
            return "；".join(str(v).strip() for v in values if str(v).strip()) or empty_label
        return str(values)

    @staticmethod
    def _describe_agent_type(descriptor_type: str) -> str:
        dt = (descriptor_type or "").strip().lower()
        if _is_structured_type(dt):
            return f"结构化数据/SQL ({dt})"
        if dt == "code":
            return "代码库"
        if dt == "unstructured" or "unstructured" in dt:
            return "文档/知识库"
        if dt == "group":
            return "语义组"
        return dt or "未知类型"

    @staticmethod
    def _explain_analysis_triggers(trigger_reason: str) -> str:
        labels = {
            "repeat_same_result": "同一工具重复返回相同结果",
            "tool_error_or_empty": "工具报错或返回空",
            "low_confidence": "规划置信度低且仍有信息缺口",
            "gaps_stagnant": "信息缺口多轮未推进",
            "uncertain_planned_action": "有缺口但下一步计划不明确",
            "approaching_max_steps": "接近最大推理步数",
            "accumulated_failures": "工具调用累计失败过多",
            "structured_without_foundation": "问题可能需要 code/doc 业务上下文，但尚未获取就调用了 structured",
        }
        parts = [p.strip() for p in (trigger_reason or "").split(",") if p.strip()]
        if not parts:
            return "未知原因"
        return "；".join(labels.get(p, p) for p in parts)

    @classmethod
    def _log_step_banner(cls, step_no: int, react_max_steps: int, *, title: str) -> None:
        logger.info("[ReAct] ── 第 %d/%d 步 · %s ──", step_no, react_max_steps, title)

    @classmethod
    def _log_tool_catalog(
        cls,
        tools: List[StructuredTool],
        tool_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]],
    ) -> None:
        agent_tools = [t for t in tools if t.name != "finish"]
        logger.info(
            "[ReAct] 可用工具清单：共 %d 个（%d 个 agent 工具 + 1 个 finish 结束工具）",
            len(tools), len(agent_tools),
        )
        for i, tool in enumerate(tools, 1):
            if tool.name == "finish":
                logger.info(
                    "[ReAct]   [%d] finish（结束工具，用于提交最终答案，不调用 agent）",
                    i,
                )
                continue
            member, ac = tool_to_agent.get(tool.name, (None, None))
            dt = _normalize_descriptor_type(member) if member else "unknown"
            agent_name = getattr(ac, "name", "") or "(unknown)" if ac else "(unknown)"
            logger.info(
                "[ReAct]   [%d] %s → agent=%s，能力=%s",
                i, tool.name, agent_name, cls._describe_agent_type(dt),
            )

    @classmethod
    def _log_llm_step_decision(
        cls,
        step_no: int,
        thought_text: str,
        structured_thought: Dict[str, Any],
        tool_calls: List[Dict[str, Any]],
    ) -> None:
        tool_names = [c.get("name", "?") for c in tool_calls]

        # 1) LLM 自然语言说明（content 字段，不是 JSON）
        if thought_text:
            logger.info(
                "[ReAct] 第%d步 · LLM 推理的过程：%s",
                step_no, cls._log_text_preview(thought_text),
            )
        else:
            logger.info(
                "[ReAct] 第%d步 · LLM 推理的过程：（空，模型未写推理文字，直接调用了工具）",
                step_no,
            )

        # 2) 可选规划 JSON（从 content 里解析）
        if structured_thought.get("valid"):
            logger.info(
                "[ReAct] 第%d步 · 规划 JSON（已解析）：子目标=%s；已满足=%s；仍缺=%s；"
                "下一步计划=%s；置信度=%s",
                step_no,
                cls._format_log_list(structured_thought.get("sub_goals")),
                cls._format_log_list(structured_thought.get("satisfied")),
                cls._format_log_list(structured_thought.get("gaps")),
                structured_thought.get("planned_action"),
                structured_thought.get("confidence"),
            )
        else:
            logger.info(
                "[ReAct] 第%d步 · 规划 JSON：无（模型未在回复中附带 JSON 规划块；"
                "这是可选 hint，不影响调工具和 finish）",
                step_no,
            )

        # 3) 实际 tool 决策
        if tool_names:
            if tool_names == ["finish"]:
                logger.info("[ReAct] 第%d步 · LLM 决定：结束推理，提交最终答案（finish）", step_no)
            else:
                logger.info(
                    "[ReAct] 第%d步 · LLM 决定：调用 %d 个工具 → %s",
                    step_no, len(tool_names), "、".join(tool_names),
                )
        else:
            logger.info("[ReAct] 第%d步 · LLM 决定：未调用任何工具", step_no)

    @staticmethod
    def _tool_index_label(tool_idx: int, tool_total: int) -> str:
        if tool_total <= 1:
            return "本步唯一工具"
        return f"本步第 {tool_idx}/{tool_total} 个工具"

    @classmethod
    def _log_tool_roundtrip(
        cls,
        step_no: int,
        tool_idx: int,
        tool_total: int,
        *,
        tool_name: str,
        agent_query: str,
        result_str: str,
        repeat_of_previous: bool,
        agent_name: str = "",
        descriptor_type: str = "",
        code_ctx_count: int = 0,
        doc_ctx_count: int = 0,
    ) -> None:
        tool_label = cls._tool_index_label(tool_idx, tool_total)
        lines = [
            f"[ReAct] 第{step_no}步 · {tool_label} · 执行完成",
            f"  ├─ 工具名：{tool_name}",
            f"  ├─ Agent：{agent_name or '-'}",
            f"  ├─ 能力：{cls._describe_agent_type(descriptor_type) or '-'}",
        ]
        if code_ctx_count or doc_ctx_count:
            lines.append(
                f"  ├─ 附带上下文：code {code_ctx_count} 条，doc {doc_ctx_count} 条"
            )
        lines.extend([
            f"  ├─ 发送问题：{cls._log_text_preview(agent_query, max_chars=800)}",
            f"  ├─ 返回长度：{len(result_str)} 字",
            f"  ├─ 是否重复：{'是（与上次调用该工具结果相同，可能无效重试）' if repeat_of_previous else '否'}",
            f"  └─ 返回内容：{cls._log_text_preview(result_str)}",
        ])
        message = "\n".join(lines)
        if repeat_of_previous:
            logger.warning(message)
        else:
            logger.info(message)

    @classmethod
    def _log_execution_analysis_detail(
        cls,
        step_no: int,
        trigger_reason: str,
        analysis: Dict[str, Any],
    ) -> None:
        logger.info(
            "[ReAct] 第%d步 · 触发深度分析，原因：%s",
            step_no, cls._explain_analysis_triggers(trigger_reason),
        )
        logger.info(
            "[ReAct] 第%d步 · 分析结论 · 建议下一步=%s；建议工具=%s",
            step_no,
            analysis.get("next_action") or "未知",
            analysis.get("next_tool") or "无",
        )
        logger.info(
            "[ReAct] 第%d步 · 分析结论 · 子目标=%s；已满足=%s；仍缺=%s",
            step_no,
            cls._format_log_list(analysis.get("sub_goals")),
            cls._format_log_list(analysis.get("satisfied")),
            cls._format_log_list(analysis.get("gaps")),
        )
        diagnosis = str(analysis.get("diagnosis") or "").strip()
        reasoning = str(analysis.get("reasoning") or "").strip()
        next_query = str(analysis.get("next_query") or "").strip()
        if diagnosis:
            logger.info(
                "[ReAct] 第%d步 · 分析诊断：%s",
                step_no, cls._log_text_preview(diagnosis),
            )
        if reasoning:
            logger.info(
                "[ReAct] 第%d步 · 分析理由：%s",
                step_no, cls._log_text_preview(reasoning),
            )
        if analysis.get("needs_code_or_doc_for_sql") is not None:
            logger.info(
                "[ReAct] 第%d步 · 上下文路由 · 需要 code/doc 配合 SQL=%s · 基础上下文已满足=%s",
                step_no,
                analysis.get("needs_code_or_doc_for_sql"),
                analysis.get("foundation_satisfied"),
            )
        if next_query:
            logger.info(
                "[ReAct] 第%d步 · 分析建议查询：%s",
                step_no, cls._log_text_preview(next_query, max_chars=800),
            )

    @classmethod
    def _log_step_summary(
        cls,
        step_no: int,
        *,
        tool_calls: List[Dict[str, Any]],
        step_observations: List[Dict[str, Any]],
        analysis_ran: bool,
        analysis_trigger: str = "",
    ) -> None:
        tool_names = [c.get("name", "?") for c in tool_calls]
        if analysis_ran:
            logger.info(
                "[ReAct] 第%d步 · 本步结束：已调用 %s；已收到 agent 回复；已做深度分析（%s）",
                step_no, "、".join(tool_names) or "无",
                cls._explain_analysis_triggers(analysis_trigger),
            )
        else:
            logger.info(
                "[ReAct] 第%d步 · 本步结束：已调用 %s；已收到 agent 回复；未触发深度分析（流程正常）",
                step_no, "、".join(tool_names) or "无",
            )

    @staticmethod
    def _query_likely_needs_foundation_context(user_query: str) -> bool:
        """Heuristic: user wording suggests SQL may need code/doc business context first."""
        q = (user_query or "").lower()
        hints = (
            "代码", "文档", "规则", "业务", "口径", "有效", "软删除", "is_deleted",
            "根据", "先看", "再结合", "实现", "逻辑", "定义", "公式", "统计口径",
            "return rate", "business rule", "code rule", "based on", "before query",
            "valid order", "eligible", "metric", "definition",
        )
        return any(h in q for h in hints)

    @staticmethod
    def _tool_descriptor_kind(tool_name: str, tool_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]]) -> str:
        if tool_name not in tool_to_agent:
            return "other"
        member, _ = tool_to_agent[tool_name]
        dt = _normalize_descriptor_type(member)
        if dt == "code":
            return "code"
        if dt == "unstructured" or "unstructured" in dt:
            return "doc"
        if _is_structured_type(dt):
            return "structured"
        return "other"

    @classmethod
    def _reorder_tool_calls_for_foundation(
        cls,
        tool_calls: List[Dict[str, Any]],
        tool_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]],
    ) -> List[Dict[str, Any]]:
        """Run code/doc before structured in the same step so context can flow downstream."""
        if len(tool_calls) <= 1:
            return tool_calls

        def _rank(name: str) -> int:
            kind = cls._tool_descriptor_kind(name, tool_to_agent)
            if kind in ("code", "doc"):
                return 0
            if kind == "structured":
                return 1
            if name == "finish":
                return 2
            return 1

        ordered = sorted(
            enumerate(tool_calls),
            key=lambda ic: (_rank(ic[1].get("name", "")), ic[0]),
        )
        return [call for _, call in ordered]

    @staticmethod
    def _had_foundation_tools_before_step(
        tool_history: List[Dict[str, Any]],
        step_no: int,
        tool_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]],
    ) -> bool:
        for entry in tool_history:
            if entry.get("step", 0) >= step_no:
                continue
            tool = entry.get("tool") or ""
            if tool == "finish":
                continue
            kind = ReActRunner._tool_descriptor_kind(tool, tool_to_agent)
            if kind in ("code", "doc"):
                return True
        return False

    def _should_run_step_analysis(
        self,
        *,
        step_no: int,
        react_max_steps: int,
        step_observations: List[Dict[str, Any]],
        structured_thought: Dict[str, Any],
        previous_gaps_sig: Optional[Tuple[str, ...]],
        total_fails: int,
        user_query: str = "",
        tool_history: Optional[List[Dict[str, Any]]] = None,
        tool_to_agent: Optional[Dict[str, Tuple[MemberInfo, AgentCard]]] = None,
        context_accumulator: Optional[InvokeContext] = None,
    ) -> Tuple[bool, str]:
        reasons: List[str] = []

        if any(obs.get("repeat_of_previous") for obs in step_observations):
            reasons.append("repeat_same_result")

        for obs in step_observations:
            result = str(obs.get("result", "")).strip()
            if not result or result.startswith("(error") or result.startswith("(unknown"):
                reasons.append("tool_error_or_empty")
                break

        confidence = str(structured_thought.get("confidence", "")).lower()
        gaps = structured_thought.get("gaps") or []
        if confidence == "low" and gaps:
            reasons.append("low_confidence")

        current_sig = self._gaps_signature(gaps)
        if previous_gaps_sig and current_sig and previous_gaps_sig == current_sig:
            reasons.append("gaps_stagnant")

        planned = str(structured_thought.get("planned_action", "")).lower().strip()
        if gaps and planned in ("unknown", "", "none"):
            reasons.append("uncertain_planned_action")

        if step_no >= max(3, react_max_steps - 3):
            reasons.append("approaching_max_steps")

        if total_fails >= 2:
            reasons.append("accumulated_failures")

        tool_to_agent = tool_to_agent or {}
        tool_history = tool_history or []
        context_accumulator = context_accumulator or {}
        structured_this_step = any(
            self._tool_descriptor_kind(str(o.get("tool", "")), tool_to_agent) == "structured"
            for o in step_observations
        )
        foundation_this_step = any(
            self._tool_descriptor_kind(str(o.get("tool", "")), tool_to_agent) in ("code", "doc")
            for o in step_observations
        )
        has_code_ctx = bool(context_accumulator.get("code_contexts"))
        has_doc_ctx = bool(context_accumulator.get("doc_contexts"))
        had_foundation_before = self._had_foundation_tools_before_step(
            tool_history, step_no, tool_to_agent,
        )

        if (
            structured_this_step
            and self._query_likely_needs_foundation_context(user_query)
            and not foundation_this_step
            and not had_foundation_before
            and not has_code_ctx
            and not has_doc_ctx
        ):
            reasons.append("structured_without_foundation")

        return bool(reasons), ",".join(reasons)

    def _format_step_analysis_message(self, step_no: int, analysis: Dict[str, Any]) -> str:
        sub_goals = analysis.get("sub_goals") or []
        satisfied = analysis.get("satisfied") or []
        gaps = analysis.get("gaps") or []
        diagnosis = analysis.get("diagnosis") or ""
        next_action = analysis.get("next_action") or "unknown"
        next_tool = analysis.get("next_tool") or ""
        next_query = analysis.get("next_query") or ""
        reasoning = analysis.get("reasoning") or ""

        sub_goal_lines = [f"- {g}" for g in sub_goals] or ["- (not identified)"]
        satisfied_lines = [f"- {s}" for s in satisfied] or ["- (none yet)"]
        gap_lines = [f"- {g}" for g in gaps] or ["- (none)"]

        lines = [
            f"## Execution Analysis (after Step {step_no})",
            "",
            "### Sub-goals",
            *sub_goal_lines,
            "",
            "### Satisfied",
            *satisfied_lines,
            "",
            "### Gaps",
            *gap_lines,
            "",
            f"### Diagnosis\n{diagnosis}",
            "",
            f"### Recommended next_action: `{next_action}`",
        ]
        if next_tool:
            lines.append(f"- next_tool: `{next_tool}`")
        if next_query:
            lines.append(f"- next_query: {next_query}")
        if reasoning:
            lines.append(f"\n### Reasoning\n{reasoning}")
        lines.append(
            "\nThis is an **on-demand deep analysis** triggered because the process may be stuck. "
            "Follow next_action. If `finish`, call finish. If `stop_retry:<tool>`, do NOT call that tool again."
        )
        return "\n".join(lines)

    async def _run_step_analysis(
        self,
        llm: Any,
        *,
        user_query: str,
        step_no: int,
        thought: str,
        step_observations: List[Dict[str, Any]],
        tool_history: List[Dict[str, Any]],
        step_analyses: List[Dict[str, Any]],
        tool_summaries: str,
    ) -> Dict[str, Any]:
        obs_lines: List[str] = []
        for obs in step_observations:
            tool = obs.get("tool", "?")
            query = obs.get("query", "")
            result = str(obs.get("result", ""))
            repeat_note = ""
            if obs.get("repeat_of_previous"):
                repeat_note = " [SAME RESULT AS PREVIOUS CALL TO THIS TOOL]"
            obs_lines.append(
                f"Tool: {tool}\nQuery: {query}\nResult ({len(result)} chars){repeat_note}:\n{result}\n"
            )

        prior_lines = [
            f"Step {a.get('step', '?')}: {a.get('next_action', '?')} — {a.get('diagnosis', '')[:200]}"
            for a in step_analyses
        ]

        prompt = _REACT_STEP_ANALYSIS_PROMPT.format(
            user_query=user_query,
            step_no=step_no,
            thought=thought or "(none)",
            step_observations="\n---\n".join(obs_lines) or "(no tool calls)",
            prior_analyses="\n".join(prior_lines) if prior_lines else "(first analysis)",
            accumulated_summary=self._build_accumulated_summary(tool_history),
            tool_summaries=tool_summaries,
        )

        try:
            resp = await self._ainvoke_ai_message(
                llm, [HumanMessage(content=prompt)], timeout=60.0, call_label=f"analysis_step_{step_no}",
            )
            raw = str(getattr(resp, "content", "") or "").strip()
            analysis = self._parse_step_analysis(raw)
            analysis.setdefault("raw", raw)
            analysis.setdefault("step", step_no)
            return analysis
        except Exception as e:
            logger.warning("[ReAct] STEP=%d step analysis failed: %s", step_no, e)
            return {
                "step": step_no,
                "diagnosis": f"(analysis failed: {e})",
                "next_action": "unknown",
                "reasoning": "Continue based on observations.",
            }

    async def run(
        self,
        user_query: str,
        prior_context: str,
        agents: List[Tuple[MemberInfo, AgentCard]],
        name_to_agent: Dict[str, Tuple[MemberInfo, AgentCard]],
        *,
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        httpx_client: Optional[httpx.AsyncClient] = None,
        react_max_steps: int = 20,
        nudge_retries: int = 2,
        progress_emitter: Optional[ProgressEmitter] = None,
    ) -> str:
        tools, tool_to_agent = self._build_agent_tools(agents, name_to_agent)

        if not agents:
            logger.info("[ReAct] no agents configured, returning prior_context")
            return prior_context or ""

        tool_desc_lines = [f"- **{t.name}**: {t.description}" for t in tools]
        agent_tools_description = "\n\n".join(tool_desc_lines)
        prior_context_str = prior_context.strip() or "(No upstream prior context.)"

        system_text = _REACT_SYSTEM_PROMPT_TEMPLATE.format(
            sg_name=self.agent_name,
            max_steps=react_max_steps,
            agent_tools_description=agent_tools_description,
            prior_context=prior_context_str,
            user_query=user_query,
        )

        messages: List[Any] = [
            SystemMessage(content=system_text),
            HumanMessage(content=user_query),
        ]

        llm_non_stream = self.llm.bind(stream=False) if hasattr(self.llm, "bind") else self.llm
        llm_with_tools = llm_non_stream.bind_tools(tools)
        finish_tool = next(t for t in tools if t.name == "finish")
        tool_history: List[Dict[str, Any]] = []
        structured_thoughts: List[Dict[str, Any]] = []
        step_analyses: List[Dict[str, Any]] = []
        context_accumulator: InvokeContext = {"code_contexts": [], "doc_contexts": []}
        fail_counts: Dict[str, int] = {}
        total_fails = 0
        total_fail_budget = 6
        nudge_retries_left = nudge_retries
        last_result_by_tool: Dict[str, str] = {}
        previous_gaps_sig: Optional[Tuple[str, ...]] = None
        run_status = "max_steps_exceeded"
        final_step = 0
        analysis_triggers: List[str] = []
        self._llm_retry_events = []

        tool_summaries = "\n".join(
            f"- {t.name}: {(t.description or '')[:300]}" for t in tools if t.name != "finish"
        )

        tool_name_list = [t.name for t in tools]
        logger.info(
            "[ReAct] 开始 ReAct 推理：%d 个 agent，%d 个工具（含 finish），最多 %d 步",
            len(agents), len(tools), react_max_steps,
        )
        logger.info("[ReAct] 用户问题：%s", self._log_text_preview(user_query, max_chars=800))
        if prior_context_str and prior_context_str != "(No upstream prior context.)":
            logger.info(
                "[ReAct] 上游已有上下文：%d 字",
                len(prior_context_str),
            )
        self._log_tool_catalog(tools, tool_to_agent)

        with langfuse.start_as_current_span(
            name="sg-expert-react",
            trace_context={"trace_id": trace_id} if _valid_langfuse_trace_id(trace_id) else None,
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "user_query": user_query,
                    "prior_context_len": len(prior_context_str),
                    "agents": [getattr(ac, "name", "") for _, ac in agents],
                    "max_steps": react_max_steps,
                },
            )

            for step_idx in range(react_max_steps):
                step_no = step_idx + 1
                final_step = step_no
                self._log_step_banner(step_no, react_max_steps, title="调用 LLM 决策")
                logger.info(
                    "[ReAct] 第%d步 · 请求 LLM（当前对话 %d 条消息）",
                    step_no, len(messages),
                )
                await self._emit_progress(
                    progress_emitter,
                    "sg_react_step_start",
                    message=self._truncate_progress_message(
                        f"ReAct step {step_no}/{react_max_steps} · calling LLM",
                        320,
                    ),
                    status="running",
                    extra={
                        "step": step_no,
                        "max_steps": react_max_steps,
                        "message_count": len(messages),
                    },
                )

                try:
                    ai_msg = await self._ainvoke_ai_message(
                        llm_with_tools, messages, timeout=120.0, call_label=f"react_step_{step_no}",
                    )
                except asyncio.TimeoutError:
                    logger.warning("[ReAct] 第%d步 · LLM 调用超时，停止推理", step_no)
                    run_status = "llm_timeout"
                    await self._emit_progress(
                        progress_emitter,
                        "sg_react_finished",
                        message=f"ReAct stopped: LLM timeout at step {step_no}",
                        status="fail",
                        extra={"status": run_status, "steps": step_no, "result_chars": 0},
                    )
                    break
                except Exception as e:
                    logger.warning("[ReAct] 第%d步 · LLM 调用失败：%s", step_no, e)
                    run_status = "llm_error"
                    await self._emit_progress(
                        progress_emitter,
                        "sg_react_finished",
                        message=self._truncate_progress_message(
                            f"ReAct stopped: LLM error at step {step_no}: {e}",
                            480,
                        ),
                        status="fail",
                        extra={"status": run_status, "steps": step_no, "result_chars": 0},
                    )
                    break

                messages.append(ai_msg)

                thought_text = str(getattr(ai_msg, "content", "") or "").strip()
                structured_thought = self._parse_structured_thought(thought_text)
                structured_thoughts.append({"step": step_no, **structured_thought})
                if thought_text:
                    tool_history.append({
                        "step": step_no,
                        "thought": thought_text,
                        "structured_thought": structured_thought,
                    })

                tool_calls = getattr(ai_msg, "tool_calls", None) or []
                self._log_llm_step_decision(step_no, thought_text, structured_thought, tool_calls)
                tool_names = [str(c.get("name") or "") for c in tool_calls if c.get("name")]
                thought_preview = self._log_text_preview(thought_text)
                tools_label = ", ".join(tool_names) or "(none)"
                await self._emit_progress(
                    progress_emitter,
                    "sg_react_llm_decision",
                    message=self._truncate_progress_message(
                        f"step {step_no}: tools={tools_label} | thought: {thought_preview}",
                        720,
                    ),
                    status="running",
                    extra={
                        "step": step_no,
                        "max_steps": react_max_steps,
                        "thought_preview": thought_preview,
                        "thought_full": thought_text,
                        "tool_names": tool_names,
                        "tool_count": len(tool_names),
                    },
                )

                if not tool_calls:
                    if nudge_retries_left > 0:
                        nudge_retries_left -= 1
                        logger.info(
                            "[ReAct] 第%d步 · LLM 未调工具，发送提醒（剩余 %d 次）",
                            step_no, nudge_retries_left,
                        )
                        messages.append(HumanMessage(content=_REACT_NUDGE_MESSAGE))
                        continue

                    final_answer = await self._invoke_forced_finish(
                        llm_non_stream,
                        messages,
                        finish_tool,
                        call_label=f"react_force_finish_step_{step_no}",
                    )
                    if final_answer:
                        return await self._complete_via_finish(
                            final_answer=final_answer,
                            run_status="forced_finish",
                            step_no=step_no,
                            log_reason="原因=LLM 未调工具，强制 finish 成功",
                            progress_emitter=progress_emitter,
                            span=span,
                            tool_history=tool_history,
                            structured_thoughts=structured_thoughts,
                            step_analyses=step_analyses,
                            analysis_triggers=analysis_triggers,
                        )

                    final_text = "任务未能通过 finish 工具提交最终答案。"
                    run_status = "forced_finish_failed"
                    logger.warning(
                        "[ReAct] 结束 · 原因=LLM 未调工具且强制 finish 仍失败；第%d步",
                        step_no,
                    )
                    return await self._complete_via_finish(
                        final_answer=final_text,
                        run_status=run_status,
                        step_no=step_no,
                        log_reason="原因=强制 finish 失败",
                        progress_emitter=progress_emitter,
                        span=span,
                        tool_history=tool_history,
                        structured_thoughts=structured_thoughts,
                        step_analyses=step_analyses,
                        analysis_triggers=analysis_triggers,
                    )

                step_observations: List[Dict[str, Any]] = []
                finished_this_step = False
                tool_calls = self._reorder_tool_calls_for_foundation(tool_calls, tool_to_agent)
                tool_total = len(tool_calls)
                all_tool_names = [
                    c.get("name", "") for c in tool_calls
                    if c.get("name") and c.get("name") != "finish"
                ]

                for idx, call in enumerate(tool_calls):
                    tool_name = call.get("name", "")
                    tool_args = call.get("args", {}) or {}
                    tool_id = call.get("id") or f"tc_{uuid4().hex[:12]}"
                    if not call.get("id"):
                        call["id"] = tool_id

                    if tool_name == "finish":
                        final_answer = self._extract_finish_answer(tool_args, thought_text)
                        return await self._complete_via_finish(
                            final_answer=final_answer,
                            run_status="completed",
                            step_no=step_no,
                            log_reason="原因=LLM 调用 finish",
                            progress_emitter=progress_emitter,
                            span=span,
                            tool_history=tool_history,
                            structured_thoughts=structured_thoughts,
                            step_analyses=step_analyses,
                            analysis_triggers=analysis_triggers,
                        )

                    if tool_name in tool_to_agent:
                        member, ac = tool_to_agent[tool_name]
                        dt = _normalize_descriptor_type(member)
                        agent_display_name = getattr(ac, "name", "") or "(unknown)"
                        agent_query = self._extract_agent_query(tool_args)
                        code_ctx_count = 0
                        doc_ctx_count = 0
                        try:
                            invoke_ctx: Optional[InvokeContext] = None
                            if _is_structured_type(dt):
                                invoke_ctx = {
                                    "code_contexts": list(context_accumulator.get("code_contexts", [])),
                                    "doc_contexts": list(context_accumulator.get("doc_contexts", [])),
                                }
                                code_ctx_count = len(invoke_ctx.get("code_contexts", []))
                                doc_ctx_count = len(invoke_ctx.get("doc_contexts", []))

                            await self._emit_progress(
                                progress_emitter,
                                "sg_react_tool_start",
                                message=self._truncate_progress_message(
                                    f"step {step_no}: {tool_name} → {agent_display_name}",
                                    320,
                                ),
                                status="running",
                                extra={
                                    "step": step_no,
                                    "tool_index": idx + 1,
                                    "tool_total": tool_total,
                                    "tool_name": tool_name,
                                    "step_tool_names": all_tool_names,
                                    "agent_name": agent_display_name,
                                    "descriptor_type": dt,
                                    "query_preview": self._truncate_progress_message(agent_query, 320),
                                    "query_full": agent_query,
                                    "code_ctx_count": code_ctx_count,
                                    "doc_ctx_count": doc_ctx_count,
                                },
                            )

                            agent_result = await self.invoke_agent(
                                member, ac, agent_query, httpx_client, invoke_ctx,
                            )
                        except Exception as e:
                            logger.warning(
                                "[ReAct] 第%d步 · 调用 %s 失败：%s",
                                step_no, tool_name, e,
                            )
                            fail_counts[tool_name] = fail_counts.get(tool_name, 0) + 1
                            total_fails += 1
                            agent_result = f"(error: {e})"
                            agent_query = self._extract_agent_query(tool_args)
                            agent_display_name = getattr(ac, "name", "") or "(unknown)"
                            dt = _normalize_descriptor_type(member)
                    else:
                        agent_result = f"(unknown tool: {tool_name})"
                        agent_query = self._extract_agent_query(tool_args)
                        agent_display_name = ""
                        dt = ""
                        code_ctx_count = 0
                        doc_ctx_count = 0

                    result_str = str(agent_result)
                    repeat_of_previous = (
                        tool_name in last_result_by_tool
                        and last_result_by_tool[tool_name] == result_str
                    )
                    if tool_name in tool_to_agent:
                        self._accumulate_observation(
                            context_accumulator,
                            tool_to_agent[tool_name][0],
                            result_str,
                        )
                        last_result_by_tool[tool_name] = result_str

                    obs_entry = {
                        "tool": tool_name,
                        "query": agent_query,
                        "args": tool_args,
                        "result": result_str,
                        "repeat_of_previous": repeat_of_previous,
                    }
                    step_observations.append(obs_entry)
                    tool_history.append({"step": step_no, **obs_entry})
                    messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                    if tool_name != "finish":
                        self._log_tool_roundtrip(
                            step_no, idx + 1, tool_total,
                            tool_name=tool_name,
                            agent_query=agent_query,
                            result_str=result_str,
                            repeat_of_previous=repeat_of_previous,
                            agent_name=agent_display_name if tool_name in tool_to_agent else "",
                            descriptor_type=dt if tool_name in tool_to_agent else "",
                            code_ctx_count=code_ctx_count if tool_name in tool_to_agent else 0,
                            doc_ctx_count=doc_ctx_count if tool_name in tool_to_agent else 0,
                        )
                        await self._emit_progress(
                            progress_emitter,
                            "sg_react_tool_done",
                            message=self._truncate_progress_message(
                                f"step {step_no}: {tool_name} done ({len(result_str)} chars)",
                                320,
                            ),
                            status="done" if not str(result_str).startswith("(error:") else "fail",
                            extra={
                                "step": step_no,
                                "tool_index": idx + 1,
                                "tool_total": tool_total,
                                "tool_name": tool_name,
                                "step_tool_names": all_tool_names,
                                "agent_name": agent_display_name if tool_name in tool_to_agent else "",
                                "result_chars": len(result_str),
                                "result_preview": self._truncate_progress_message(result_str, 480),
                                "repeat_of_previous": repeat_of_previous,
                                "error": str(result_str).startswith("(error:"),
                            },
                        )

                    if total_fails >= total_fail_budget:
                        logger.warning(
                            "[ReAct] 第%d步 · 工具累计失败 %d 次，已达上限 %d",
                            step_no, total_fails, total_fail_budget,
                        )
                        break

                if total_fails >= total_fail_budget:
                    run_status = "fail_budget_exceeded"
                    logger.warning(
                        "[ReAct] 停止推理 · 原因=工具失败次数过多（%d 次）",
                        total_fails,
                    )
                    await self._emit_progress(
                        progress_emitter,
                        "sg_react_finished",
                        message=f"ReAct stopped: tool fail budget exceeded ({total_fails})",
                        status="fail",
                        extra={
                            "status": run_status,
                            "steps": step_no,
                            "result_chars": 0,
                        },
                    )
                    break

                analysis_ran = False
                analysis_trigger = ""
                if not finished_this_step and step_observations:
                    should_analyze, trigger_reason = self._should_run_step_analysis(
                        step_no=step_no,
                        react_max_steps=react_max_steps,
                        step_observations=step_observations,
                        structured_thought=structured_thought,
                        previous_gaps_sig=previous_gaps_sig,
                        total_fails=total_fails,
                        user_query=user_query,
                        tool_history=tool_history,
                        tool_to_agent=tool_to_agent,
                        context_accumulator=context_accumulator,
                    )
                    current_gaps_sig = self._gaps_signature(structured_thought.get("gaps") or [])
                    if current_gaps_sig:
                        previous_gaps_sig = current_gaps_sig

                    if should_analyze:
                        analysis_trigger = trigger_reason
                        analysis_ran = True
                        analysis_triggers.append(f"step{step_no}:{trigger_reason}")
                        analysis = await self._run_step_analysis(
                            llm_non_stream,
                            user_query=user_query,
                            step_no=step_no,
                            thought=thought_text,
                            step_observations=step_observations,
                            tool_history=tool_history,
                            step_analyses=step_analyses,
                            tool_summaries=tool_summaries,
                        )
                        analysis["trigger"] = trigger_reason
                        step_analyses.append(analysis)
                        self._log_execution_analysis_detail(step_no, trigger_reason, analysis)
                        await self._emit_progress(
                            progress_emitter,
                            "sg_react_step_analysis",
                            message=self._truncate_progress_message(
                                f"step {step_no} analysis: next={analysis.get('next_action') or '?'}",
                                320,
                            ),
                            status="running",
                            extra={
                                "step": step_no,
                                "trigger": trigger_reason,
                                "next_action": str(analysis.get("next_action") or ""),
                                "next_tool": str(analysis.get("next_tool") or ""),
                                "diagnosis_preview": self._truncate_progress_message(
                                    str(analysis.get("diagnosis") or ""), 480,
                                ),
                            },
                        )
                        analysis_msg = self._format_step_analysis_message(step_no, analysis)
                        messages.append(HumanMessage(content=analysis_msg))
                        tool_history.append({
                            "step": step_no,
                            "analysis": analysis_msg,
                            "next_action": analysis.get("next_action"),
                            "trigger": trigger_reason,
                        })
                    else:
                        logger.info(
                            "[ReAct] 第%d步 · 未触发深度分析（流程正常，无需介入）",
                            step_no,
                        )

                if not finished_this_step:
                    self._log_step_summary(
                        step_no,
                        tool_calls=tool_calls,
                        step_observations=step_observations,
                        analysis_ran=analysis_ran,
                        analysis_trigger=analysis_trigger,
                    )
                    step_tool_names_done = [
                        o.get("tool", "") for o in step_observations
                        if o.get("tool") and o.get("tool") != "finish"
                    ]
                    tool_names_label = " + ".join(step_tool_names_done) if step_tool_names_done else "(none)"
                    await self._emit_progress(
                        progress_emitter,
                        "sg_react_step_done",
                        message=self._truncate_progress_message(
                            f"step {step_no}/{react_max_steps} done · {len(step_observations)} tool(s): {tool_names_label}",
                            320,
                        ),
                        status="done",
                        extra={
                            "step": step_no,
                            "max_steps": react_max_steps,
                            "observation_count": len(step_observations),
                            "step_tool_names": step_tool_names_done,
                            "analysis_ran": analysis_ran,
                        },
                    )

            logger.warning("[ReAct] 已达最大步数 %d，尝试强制 finish", react_max_steps)
            forced_answer = await self._invoke_forced_finish(
                llm_non_stream,
                messages,
                finish_tool,
                call_label="react_max_steps_force_finish",
            )
            if forced_answer:
                return await self._complete_via_finish(
                    final_answer=forced_answer,
                    run_status="forced_finish",
                    step_no=final_step or react_max_steps,
                    log_reason="原因=超过最大步数，强制 finish 成功",
                    progress_emitter=progress_emitter,
                    span=span,
                    tool_history=tool_history,
                    structured_thoughts=structured_thoughts,
                    step_analyses=step_analyses,
                    analysis_triggers=analysis_triggers,
                )

            logger.warning("[ReAct] 强制 finish 失败，finish-only 策略下不再做 transcript 汇总")
            final_text = (
                "推理步数已用尽，且未能通过 finish 工具提交最终答案；请重试或简化问题。"
            )
            return await self._complete_via_finish(
                final_answer=final_text,
                run_status="max_steps_no_result",
                step_no=final_step or react_max_steps,
                log_reason="原因=超过最大步数且强制 finish 失败",
                progress_emitter=progress_emitter,
                span=span,
                tool_history=tool_history,
                structured_thoughts=structured_thoughts,
                step_analyses=step_analyses,
                analysis_triggers=analysis_triggers,
            )
