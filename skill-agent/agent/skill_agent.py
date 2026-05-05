"""SkillAgent — standalone A2A agent backed by a process-wide SkillRunner.

This port mirrors the "route B" LocalSkill pattern used by
``orchestrator_agent/orchestrator_agent_semantic_domain.py``:

  * the ``SkillAgentExecutor`` owns a single ``skill_sdk.skill.runner.SkillRunner``
    (eagerly preloaded at server startup via :meth:`preload_skill_runner` so the
    full skill inventory is logged before the first request arrives);
  * each A2A request is dispatched to :meth:`SkillRunner.plan_and_run`, which
    picks a skill from the loaded inventory and drives it through its ReAct
    loop;
  * runner status codes are mapped to the same ``local_skill_*`` reason codes
    the orchestrator emits, so downstream observers see a consistent taxonomy;
  * DAC_PROGRESS frames (``layer=sd_skill``) are streamed back as A2A artifacts
    when streaming is enabled.

Environment variables (all optional, share names with the orchestrator so the
same runtime config works for both):

  ENABLE_LOCAL_SKILLS         "true" to enable SkillRunner init (default: true)
  LOCAL_SKILLS_DIR            directory holding skill *.zip packs (default: /app/skills/)
  LOCAL_SKILL_MAX_STEPS       per-call ReAct step budget (default: 20)
  LOCAL_SKILL_CMD_TIMEOUT_SEC subprocess timeout in seconds (default: 30)
  LOCAL_SKILL_MAX_CONCURRENCY max concurrent plan_cmd executions, 0 = unlimited (default: 8)
  ENABLE_THINKING_PARAM       forward ``enable_thinking=false`` to the LLM (default: true)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from abc import ABC
from typing import Any, AsyncIterable, Dict, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, AgentSkill, TextPart
from a2a.utils import new_agent_text_message, new_task
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from model_sdk import ModelManager
from pydantic import BaseModel, Field
from typing_extensions import override
from langchain_core.messages import HumanMessage

try:
    from skill_sdk.skill.runner import SkillRunner  # noqa: F401  (gated by ENABLE_LOCAL_SKILLS)
except ImportError:  # pragma: no cover - skill_sdk is an optional runtime dep
    SkillRunner = None  # type: ignore[assignment]

try:
    from skill_sdk.tool.code_execution import CodeExecution
except ImportError:  # pragma: no cover
    CodeExecution = None  # type: ignore[assignment,misc]


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

PROGRESS_FRAME_PREFIX = "[[DAC_PROGRESS]] "
DAC_PROGRESS_LAYER = "sd_skill"

# Langfuse is optional — keep the callback handler available so skill_sdk's
# runner can pick it up if it wants to trace the LLM calls.
langfuse = get_client()
if os.getenv("LANGFUSE_AUTH_CHECK", "disable") == "enable":
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Langfuse authentication failed. Please check your credentials and host.")
langfuse_handler = CallbackHandler()


# ---------------------------------------------------------------------------
# Skill runner configuration (mirrors orchestrator route B LocalSkill knobs)
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

# 与 skill_sdk/test.py 一致：注入 CodeExecution 后 ReAct 才会出现 ``code_exec`` 工具。
ENABLE_CODE_EXEC = os.getenv("ENABLE_CODE_EXEC", "true").strip().lower() in ("1", "true", "yes")
try:
    CODE_EXEC_MAX_RETRIES = int(os.getenv("CODE_EXEC_MAX_RETRIES", "3"))
except (TypeError, ValueError):
    CODE_EXEC_MAX_RETRIES = 3


def _short(text: Any, limit: int = 200) -> str:
    """Single-line preview for log/progress payloads."""
    s = str(text or "").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _map_skill_runner_status(raw_status: Any) -> tuple[str, str]:
    """Map ``SkillRunner.plan_and_run`` status -> (task_status, failure_reason_code).

    Mirrors ``OrchestratorAgent._map_skill_runner_status`` so observers see the
    same taxonomy whether the skill is run through the orchestrator's synthetic
    ``LocalSkill`` agent or directly against this standalone agent.
    """
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


class CapabilityCheckResponse(BaseModel):
    """与 routing-agent 广播探测约定的结构化响应（model_dump_json 写入 artifact）。"""

    can_handle: bool = Field(description="Whether this agent can handle the given query.")
    confidence: float = Field(default=0.0, description="Confidence level from 0.0 to 1.0.")
    reason: str = Field(default="", description="Brief explanation for the capability assessment.")
    agent_name: str = Field(default="", description="Name of the responding agent.")
    agent_url: str = Field(default="", description="URL of the responding agent.")
    route_path: list[str] = Field(default_factory=list, description="Best path (single-node for SkillAgent).")
    route_paths: list[dict] = Field(
        default_factory=list,
        description='Top-K paths: [{"path": [...], "confidence": float, "alias": str}, ...].',
    )
    can_contribute: bool = Field(
        default=False,
        description="Whether this agent can partially contribute even if cannot fully handle.",
    )
    contribution: str = Field(default="", description="Brief description when can_contribute=true.")
    execution_strategy: str = Field(default="single", description="Capability response strategy.")


SKILL_CAPABILITY_CHECK_PROMPT = """# Role：本地技能与通用工具任务判定器

请按以下步骤**逐步思考**，将推理过程写入 reason 字段，最后**只输出一个 JSON 对象**（不要用 Markdown 代码块包裹）。

## 思考步骤

**步骤 1 - 任务类型**：用户问题是否适合通过**代码执行**（数值/统计/聚合/清洗/小型数据处理）、**联网检索**、或下方「技能参考」中已加载技能所覆盖的工具能力来解决？还是明确只需要某一**垂直业务库**的专属 SQL/行业报表（应由该领域 Agent 端到端完成）？

**步骤 2 - 技能匹配**：对照技能参考：是否存在合理匹配（如数学计算、脚本式数据处理、tavily 检索等）。skills 仅作参考，不限定边界；明显可用代码或检索解决的通用任务，即使未逐字列举也可判为可处理。

**步骤 3 - 边界**：用户**主要诉求**是产出 ECharts/Mermaid 等可视化图表时，可倾向交由专用图表 Agent（本 Agent 可 can_contribute 说明分工）。纯闲聊、与计算/检索/代码无关的长文本且无需工具 → can_handle=false。

**步骤 4 - 反思**：① 纯数学、小规模数据处理、格式化、算法与脚本类任务 → 通常可由本 Agent 技能处理 → can_handle=true。② 必须访问用户未提供且无法通过通用检索补全的**专有业务数据表** → 倾向 can_handle=false。③ 不确定时，若存在典型 code/search/本地技能路径 → 倾向 can_handle=true。

**步骤 5 - 结论**：给出 can_handle 与 confidence（0.0～1.0）。

**步骤 6 - 可贡献性（仅当 can_handle=false）**：仅当能给出**具体、可验证**的补充说明（如缺少的字段、需确认的表名）时设 can_contribute=true；禁止「补充相关信息」等空泛表述。

---
**本智能体信息：**
- 名称：{agent_name}
- 描述：{agent_description}
- 技能参考（已加载技能摘要；仅供参考）：
{agent_skills}

**历史对话：**
{history}

**用户问题：**
{query}

---
## 输出格式
{{"can_handle": true 或 false, "can_contribute": true 或 false, "contribution": "（仅当 can_contribute=true）", "confidence": 0.0 到 1.0, "reason": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：... 步骤6：... 结论：..."}}
"""


class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "allow",
    }

    agent_name: str = Field(description="The name of the agent.")
    description: str = Field(description="A brief description of the agent's purpose.")
    content_types: list[str] = Field(description="Supported content types.")


class SkillAgent(BaseAgent):
    """Per-request wrapper that runs one :meth:`SkillRunner.plan_and_run` call."""

    def __init__(
        self,
        *,
        skill_runner: "SkillRunner | None" = None,
        query: str | None = None,
        metadata: dict | None = None,
        current_task_id: int | None = None,
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
        self.agent_id = "SkillAgent"

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
        """Invoke ``plan_and_run`` once and yield the final answer text."""
        query = (self.query or "").strip()
        query_preview = _short(query)

        if self.skill_runner is None or SkillRunner is None:
            reason = (
                "SkillRunner unavailable: ENABLE_LOCAL_SKILLS is disabled or "
                "skill_sdk could not be imported."
            )
            logger.warning("[LocalSkill][Run] %s", reason)
            await self.emit_progress(
                "sd_skill_finished",
                message=reason,
                status="fail",
                task_id=self.current_task_id,
                extra={"reason_code": "local_skill_error"},
            )
            yield reason
            return

        trace_id = self.metadata.get("trace_id")
        user_id = self.metadata.get("user_id")
        run_id = self.metadata.get("run_id")

        await self.emit_progress(
            "sd_skill_started",
            message=f"running local skill | query: {query_preview}",
            status="running",
            task_id=self.current_task_id,
            extra={"skill_query": query_preview},
        )

        logger.info(
            "[LocalSkill][RunStart] query=%r user_id=%s run_id=%s trace_id=%s",
            query_preview, user_id, run_id, trace_id,
        )
        t0 = _time.perf_counter()

        try:
            result = await self.skill_runner.plan_and_run(
                query=query,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
        except asyncio.CancelledError:
            logger.warning("[LocalSkill][RunCancel] query=%r cancelled", query_preview)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LocalSkill][RunError] plan_and_run raised")
            result = {
                "status": "local_skill_error",
                "skill": "",
                "final_answer": f"LocalSkill execution error: {exc}",
                "attempts": [],
            }

        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        status_code, reason_code = _map_skill_runner_status(result.get("status"))
        final_answer = str(result.get("final_answer") or "").strip()
        skill_name_used = str(result.get("skill") or "")
        attempts = result.get("attempts") or []

        try:
            _result_dump = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception:  # noqa: BLE001
            _result_dump = repr(result)
        logger.info(
            "[LocalSkill][RunResult] skill=%s status=%s elapsed_ms=%d result:\n%s",
            skill_name_used or "(unknown)",
            result.get("status"),
            elapsed_ms,
            _result_dump,
        )

        answer_preview = _short(final_answer)
        if status_code == "complete":
            logger.info(
                "[LocalSkill][RunOK] skill=%s attempts=%d elapsed_ms=%d answer=%r",
                skill_name_used or "(unknown)", len(attempts), elapsed_ms, answer_preview,
            )
        else:
            logger.warning(
                "[LocalSkill][RunFail] skill=%s status=%s reason=%s attempts=%d "
                "elapsed_ms=%d answer=%r",
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

        await self.emit_progress(
            "sd_skill_finished",
            message=(
                f"completed skill {skill_name_used or '(unknown)'}"
                if status_code == "complete"
                else f"skill failed ({reason_code or 'error'})"
            ),
            status="done" if status_code == "complete" else "fail",
            task_id=self.current_task_id,
            extra={
                "skill_name": skill_name_used,
                "skill_status": str(result.get("status") or ""),
                "skill_attempts": len(attempts),
                "reason_code": reason_code,
                "elapsed_ms": elapsed_ms,
            },
        )

        yield display_answer


class SkillAgentExecutor(AgentExecutor):
    """A2A executor that owns a process-wide SkillRunner."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        max_steps: int = 20,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.stream = stream
        self.stream_enabled = stream
        self.temperature = temperature
        self.max_steps = max_steps
        self.agent_card: AgentCard | None = None

        # Lazily-constructed process-wide runner. :meth:`preload_skill_runner`
        # builds it synchronously at server bootstrap; :meth:`_ensure_skill_runner`
        # is the async fallback for code paths that skipped preload.
        self._skill_runner: "SkillRunner | None" = None
        self._skill_runner_initialised = False
        self._skill_runner_lock = asyncio.Lock()
        self._log_skill_executor_config()

    # ------------------------------------------------------------------
    # SkillRunner lifecycle (ported from orchestrator route B executor)
    # ------------------------------------------------------------------

    @staticmethod
    def _log_skill_executor_config() -> None:
        """One-shot snapshot at executor construction."""
        logger.info(
            "[LocalSkill][Config] env snapshot (effective on first request that needs skills): "
            "ENABLE_LOCAL_SKILLS=%s LOCAL_SKILLS_DIR=%r "
            "LOCAL_SKILL_MAX_STEPS=%d LOCAL_SKILL_CMD_TIMEOUT_SEC=%d "
            "LOCAL_SKILL_MAX_CONCURRENCY=%d ENABLE_CODE_EXEC=%s code_execution_importable=%s "
            "skill_sdk_importable=%s",
            LOCAL_SKILLS_ENABLED,
            LOCAL_SKILLS_DIR,
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
            LOCAL_SKILL_MAX_CONCURRENCY,
            ENABLE_CODE_EXEC,
            CodeExecution is not None,
            SkillRunner is not None,
        )

    def _build_skill_runner_llm(self):
        """Build a dedicated LLM for SkillRunner.

        ``stream=False`` on purpose — SkillRunner drives the LLM synchronously
        over multi-turn tool calls and never needs the streaming interface.
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
        """构造 ``CodeExecution`` 并与 SkillRunner **共用**同一 ``llm``（见 skill_sdk/test.py）。"""
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
        """Build SkillRunner + load skills synchronously.

        Logs the full skill inventory so operators can immediately see what
        this agent advertises.
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
            "cmd_timeout_sec=%d max_concurrency=%d",
            LOCAL_SKILLS_DIR or "(unset)",
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
            LOCAL_SKILL_MAX_CONCURRENCY,
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
                loaded = runner.load_from_dir(LOCAL_SKILLS_DIR) or []
                load_ms = int((_time.perf_counter() - load_t0) * 1000)
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
                            idx, nm, ver, desc,
                        )
                    logger.info("[LocalSkill][Init] ---- end skill inventory ----")
                else:
                    logger.warning(
                        "[LocalSkill][Init] no skills loaded from %s — expected *.zip skill packs; "
                        "LocalSkill will advertise an empty capability until packs appear",
                        LOCAL_SKILLS_DIR,
                    )
            else:
                logger.warning(
                    "[LocalSkill][Init] ENABLE_LOCAL_SKILLS=true but LOCAL_SKILLS_DIR is empty; "
                    "no skills were loaded — LocalSkill will advertise an empty capability."
                )
            logger.info(
                "[LocalSkill][Init] ready in %dms (provider=%s model=%s)",
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
        inventory is printed **before** the first A2A request arrives. Safe to
        call multiple times — the second call is a no-op.
        """
        if self._skill_runner_initialised:
            return self._skill_runner
        self._skill_runner = self._init_skill_runner_sync()
        self._skill_runner_initialised = True
        return self._skill_runner

    async def _ensure_skill_runner(self) -> "SkillRunner | None":
        """Return the process-wide SkillRunner, constructing it on first use."""
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

        Safe to call repeatedly; only the first call has an effect. Intended
        to be wired into process shutdown hooks (``atexit`` / signal handlers).
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

    # ------------------------------------------------------------------
    # Dynamic AgentCard composition
    # ------------------------------------------------------------------
    #
    # Mirrors ``OrchestratorAgent._build_local_skill_card`` in
    # ``orchestrator_agent_semantic_domain.py``: the card's description is
    # composed from ``name: description`` lines of every loaded skill so that
    # the registry / planner sees the current capability surface rather than a
    # hand-written blurb. Unlike the orchestrator (which wraps LocalSkill as a
    # synthetic card with ``skills=[]``), this agent is a real A2A target, so
    # we also materialise one ``AgentSkill`` entry per loaded skill.

    _EMPTY_SKILL_DESCRIPTION = (
        "本地技能执行器。当前未加载任何技能；若被选中，将回退为不可用。"
    )
    _SKILL_LIST_HEADER = "本地技能执行器，可在本进程内直接运行以下技能："
    _MAX_SKILL_DESC_CHARS = 140
    _MAX_DESC_PREVIEW_LINES = 30

    def build_dynamic_agent_card_fields(self) -> tuple[str, list[AgentSkill]]:
        """Render ``(description, skills)`` overrides from the loaded inventory.

        Must be called after :meth:`preload_skill_runner` (or ``_ensure_skill_runner``).
        The returned ``description`` always carries the full skill list summary;
        the returned ``skills`` list has one ``AgentSkill`` per loaded skill so
        registries see individual capabilities rather than an umbrella entry.

        Fails soft: if the runner is not available or has no skills, returns a
        sentinel description and an empty skills list so the server can decide
        whether to fall back to the ``agent_card.json`` values.
        """
        runner = self._skill_runner
        lister = getattr(runner, "lister", None) if runner is not None else None
        try:
            skills = list(getattr(lister, "skills", None) or []) if lister is not None else []
        except Exception:  # noqa: BLE001
            logger.exception("[LocalSkill][CardBuild] failed to read skill list from lister")
            skills = []

        lines: list[str] = []
        agent_skills: list[AgentSkill] = []
        for s in skills:
            name = str(getattr(s, "name", "") or "").strip()
            desc_raw = str(getattr(s, "description", "") or "").strip()
            desc_inline = desc_raw.replace("\n", " ").strip()
            if not name:
                continue
            preview = (
                desc_inline
                if len(desc_inline) <= self._MAX_SKILL_DESC_CHARS
                else desc_inline[: self._MAX_SKILL_DESC_CHARS] + "..."
            )
            lines.append(f"- {name}: {preview}")
            try:
                agent_skills.append(
                    AgentSkill(
                        id=name,
                        name=name,
                        description=desc_raw or preview,
                        tags=[name, "local skill", "skill sdk"],
                        examples=[],
                        input_modes=["text", "text/plain"],
                        output_modes=["text", "text/plain"],
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[LocalSkill][CardBuild] failed to build AgentSkill entry for name=%r", name,
                )

        if not lines:
            logger.warning(
                "[LocalSkill][CardBuild] rendering empty card (no skills loaded); "
                "agent will advertise a no-op capability"
            )
            return self._EMPTY_SKILL_DESCRIPTION, []

        preview_lines = lines[: self._MAX_DESC_PREVIEW_LINES]
        description = self._SKILL_LIST_HEADER + "\n" + "\n".join(preview_lines)
        hidden = max(0, len(lines) - self._MAX_DESC_PREVIEW_LINES)
        if hidden:
            description += f"\n（另有 {hidden} 个技能未列出）"
        logger.info(
            "[LocalSkill][CardBuild] rendered AgentCard overrides: skills_count=%d (shown=%d, hidden=%d)",
            len(lines),
            len(preview_lines),
            hidden,
        )
        return description, agent_skills

    # ------------------------------------------------------------------
    # A2A hooks
    # ------------------------------------------------------------------

    async def handle_capability_check(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        query: str,
    ) -> None:
        """routing-agent 广播探测：返回 CapabilityCheckResponse JSON（与 chart-agent / SG orchestrator 一致）。"""
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        request_metadata = context.metadata if isinstance(context.metadata, dict) else {}
        md = request_metadata

        card = self.agent_card
        agent_name = card.name if card else "SkillAgent"
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
            mgr = ModelManager()
            _extra_body = (
                {"enable_thinking": False}
                if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no")
                else {}
            )
            llm = mgr.get_llm(
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=0.01,
                stream=False,
                extra_body=_extra_body,
            )
            prompt = SKILL_CAPABILITY_CHECK_PROMPT.format(
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
                name="skill-capability-check-llm",
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
            "[Capability] SkillAgent result | can_handle=%s | confidence=%.2f | agent=%s",
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

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        metadata = context.metadata or {}
        logger.info(f"===== SkillAgentExecutor, user request metadata is {metadata}.")

        if isinstance(metadata, dict) and metadata.get("message_type") == CAPABILITY_CHECK_MESSAGE_TYPE:
            logger.info("[Capability] Received capability check request, query: %s...", (query or "")[:100])
            await self.handle_capability_check(context, event_queue, query)
            return

        current_task_id: Optional[int] = None
        current_task_id_str = metadata.get("current_task_id")
        if current_task_id_str:
            try:
                current_task_id = int(current_task_id_str)
            except (TypeError, ValueError):
                current_task_id = None

        skill_runner = await self._ensure_skill_runner()

        agent = SkillAgent(
            skill_runner=skill_runner,
            query=query,
            metadata=metadata,
            current_task_id=current_task_id,
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        direct_return = metadata.get("direct_return", "disable")

        try:
            if direct_return == "enable":
                await updater.add_artifact(
                    [TextPart(text="")],
                    name=f"{agent.agent_name}-result",
                )
                await updater.complete(
                    message=new_agent_text_message("", context_id=task.context_id)
                )
                return

            if self.stream_enabled:
                async def _progress_callback(text: str) -> None:
                    await updater.add_artifact(
                        [TextPart(text=text)],
                        name=f"{agent.agent_name}-result",
                    )

                agent.progress_callback = _progress_callback

            async for chunk in agent.run():
                if chunk:
                    await updater.add_artifact(
                        [TextPart(text=chunk)],
                        name=f"{agent.agent_name}-result",
                    )

            await updater.complete(
                message=new_agent_text_message("", context_id=task.context_id)
            )
        finally:
            pass

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception("cancel not supported")
