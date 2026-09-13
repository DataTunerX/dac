"""Local-only execution adapter used by participant mode."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from agent_contracts import (
    MAX_BEST_DRAFT_BYTES,
    MAX_INLINE_RESULT_BYTES,
    PROTOCOL_VERSION,
    ParticipantTask,
    SchemaRegistry,
    TaskError,
    TaskMetrics,
    TaskOutput,
    TaskResult,
    TaskResultStatus,
    json_size_bytes,
    truncate_utf8,
)

ProgressCallback = Callable[..., Awaitable[None]]

_TOOL_ENV_REQUIREMENTS = {
    "tavily_search": ("TAVILY_API_KEY",),
    "tavily_extract": ("TAVILY_API_KEY",),
}


class LocalTaskExecutor:
    """Run exactly one assigned task through the process-local SkillRunner."""

    def __init__(
        self,
        *,
        skill_runner: Any,
        agent_name: str,
        schema_registry: SchemaRegistry,
    ) -> None:
        self.skill_runner = skill_runner
        self.agent_name = agent_name
        self.schema_registry = schema_registry

    @staticmethod
    def _task_query(task: ParticipantTask) -> str:
        contract = [
            {
                "name": output.name,
                "schema_id": output.schema_id,
                "mandatory": output.mandatory,
            }
            for output in task.expected_outputs
        ]
        return (
            f"Assigned participant task:\n{task.objective}\n\n"
            f"Required operation:\n{task.operation}\n\n"
            f"Task inputs:\n{json.dumps(task.inputs, ensure_ascii=False, default=str)}\n\n"
            f"Required output contract:\n{json.dumps(contract, ensure_ascii=False)}\n\n"
            "Do only this assigned task. Do not delegate, discover agents, or answer "
            "a broader user request. Return the requested structured data as JSON."
        )

    @classmethod
    def runtime_tool_inventory(cls, skill_runner: Any) -> tuple[list[str], list[str]]:
        """Return tools that are actually usable and tools missing prerequisites."""

        names = {
            str(getattr(tool, "name", "") or "").strip()
            for tool in (getattr(skill_runner, "_runner_tools", None) or [])
        }
        names.discard("")
        unavailable = {
            name
            for name, required_env in _TOOL_ENV_REQUIREMENTS.items()
            if name in names
            and any(not os.getenv(key, "").strip() for key in required_env)
        }
        return sorted(names - unavailable), sorted(unavailable)

    @classmethod
    def _without_unavailable_tools(cls, skill_runner: Any) -> Any:
        runner = copy.copy(skill_runner)
        ready, _ = cls.runtime_tool_inventory(skill_runner)
        ready_set = set(ready)
        if hasattr(runner, "_runner_tools"):
            runner._runner_tools = [
                tool
                for tool in (getattr(skill_runner, "_runner_tools", None) or [])
                if getattr(tool, "name", None) in ready_set
            ]
        return runner

    def _outputs_from_answer(
        self,
        task: ParticipantTask,
        answer: str,
    ) -> list[TaskOutput]:
        if not answer.strip():
            return []
        candidate = answer.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            first_newline = candidate.find("\n")
            if first_newline >= 0:
                candidate = candidate[first_newline + 1 : -3].strip()
        try:
            parsed: Any = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = answer

        if isinstance(parsed, dict) and isinstance(parsed.get("outputs"), list):
            outputs = []
            for raw in parsed["outputs"]:
                if isinstance(raw, dict):
                    try:
                        output = TaskOutput.model_validate(raw)
                    except Exception:
                        continue
                    if not output.schema_digest:
                        try:
                            descriptor = self.schema_registry.resolve(output.schema_id)
                            output = output.model_copy(
                                update={"schema_digest": descriptor.schema_digest}
                            )
                        except LookupError:
                            pass
                    outputs.append(output)
            return outputs

        expected_by_name = {item.name: item for item in task.expected_outputs}
        if isinstance(parsed, dict) and set(parsed) & set(expected_by_name):
            return [
                TaskOutput(
                    name=name,
                    schema_id=expected_by_name[name].schema_id,
                    schema_digest=expected_by_name[name].schema_digest
                    or self.schema_registry.resolve(
                        expected_by_name[name].schema_id
                    ).schema_digest,
                    data=value,
                )
                for name, value in parsed.items()
                if name in expected_by_name
            ]

        if len(task.expected_outputs) == 1:
            expected = task.expected_outputs[0]
            return [
                TaskOutput(
                    name=expected.name,
                    schema_id=expected.schema_id,
                    schema_digest=expected.schema_digest
                    or self.schema_registry.resolve(expected.schema_id).schema_digest,
                    data=parsed,
                )
            ]
        return []

    async def execute(
        self,
        task: ParticipantTask,
        *,
        user_id: str = "",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TaskResult:
        started = time.perf_counter()
        required_skill = (task.constraints.required_skill or "").strip()
        attempted_skills: list[str] = []
        task_runner = self._without_unavailable_tools(self.skill_runner)
        configured_steps = int(getattr(self.skill_runner, "max_steps", 0) or 0)
        task_runner.max_steps = (
            min(configured_steps, task.constraints.max_local_steps)
            if configured_steps > 0
            else task.constraints.max_local_steps
        )

        async def run_local() -> Dict[str, Any]:
            if required_skill:
                matches = task_runner.lister.find_by_name(
                    required_skill, match="exact", case_insensitive=True
                )
                if not matches:
                    return {
                        "status": "skill_not_found",
                        "skill": required_skill,
                        "final_answer": "",
                        "tool_history": [],
                    }
                attempted_skills.append(matches[0].name)
                return await task_runner.run(
                    self._task_query(task),
                    matches[0],
                    user_id=user_id,
                    run_id=task.trace.run_id,
                    trace_id=task.trace.trace_id,
                    progress_callback=progress_callback,
                )

            result = await task_runner.plan_and_run(
                query=self._task_query(task),
                user_id=user_id,
                run_id=task.trace.run_id,
                trace_id=task.trace.trace_id,
                progress_callback=progress_callback,
            )
            skill = str(result.get("skill") or "").strip()
            if skill:
                attempted_skills.append(skill)
            return result

        try:
            runner_result = await asyncio.wait_for(
                run_local(), timeout=task.constraints.deadline_ms / 1000
            )
        except asyncio.TimeoutError:
            return TaskResult(
                protocol_version=PROTOCOL_VERSION,
                collaboration_id=task.collaboration_id,
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=TaskResultStatus.FAILED,
                error=TaskError(
                    code="deadline_exceeded",
                    message=f"participant deadline exceeded after {task.constraints.deadline_ms}ms",
                ),
                retryable=True,
                metrics=TaskMetrics(
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    attempted_skills=attempted_skills,
                ),
            )
        except asyncio.CancelledError:
            return TaskResult(
                protocol_version=PROTOCOL_VERSION,
                collaboration_id=task.collaboration_id,
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=TaskResultStatus.CANCELLED,
                error=TaskError(code="cancelled", message="participant task cancelled"),
                retryable=False,
                metrics=TaskMetrics(
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    attempted_skills=attempted_skills,
                ),
            )
        except Exception as exc:
            return TaskResult(
                protocol_version=PROTOCOL_VERSION,
                collaboration_id=task.collaboration_id,
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=TaskResultStatus.FAILED,
                error=TaskError(
                    code="local_execution_error", message=str(exc) or type(exc).__name__
                ),
                retryable=True,
                metrics=TaskMetrics(
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    attempted_skills=attempted_skills,
                ),
            )

        raw_status = str(runner_result.get("status") or "").strip().lower()
        answer = str(runner_result.get("final_answer") or "").strip()
        tool_history = runner_result.get("tool_history") or []
        outputs = self._outputs_from_answer(task, answer)
        duration_ms = int((time.perf_counter() - started) * 1000)
        metrics = TaskMetrics(
            duration_ms=duration_ms,
            tool_calls=sum(
                1
                for item in tool_history
                if isinstance(item, dict) and item.get("tool")
            ),
            local_steps=min(len(tool_history), task.constraints.max_local_steps),
            attempted_skills=attempted_skills,
        )

        if raw_status in {"no_suitable_skill", "skill_not_found"}:
            return TaskResult(
                protocol_version=PROTOCOL_VERSION,
                collaboration_id=task.collaboration_id,
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=TaskResultStatus.BLOCKED,
                missing_capabilities=[required_skill or "suitable local skill"],
                error=TaskError(
                    code=raw_status,
                    message=answer or "required local skill is unavailable",
                ),
                retryable=False,
                metrics=metrics,
            )

        if raw_status == "completed" and answer:
            status = TaskResultStatus.SUCCESS
            limitations: list[str] = []
        elif answer:
            status = TaskResultStatus.PARTIAL
            limitations = [
                f"best available draft preserved after runner status {raw_status or 'unknown'}"
            ]
        else:
            return TaskResult(
                protocol_version=PROTOCOL_VERSION,
                collaboration_id=task.collaboration_id,
                task_id=task.task_id,
                agent_name=self.agent_name,
                status=TaskResultStatus.FAILED,
                error=TaskError(
                    code=raw_status or "empty_result",
                    message="local skill produced no usable output",
                ),
                retryable=raw_status not in {"blocked", "policy_blocked"},
                metrics=metrics,
            )

        output_size = json_size_bytes(
            [output.model_dump(mode="json") for output in outputs]
        )
        best_draft = (
            truncate_utf8(answer, MAX_BEST_DRAFT_BYTES) if not outputs else None
        )
        if output_size > MAX_INLINE_RESULT_BYTES:
            outputs = []
            status = TaskResultStatus.PARTIAL
            best_draft = truncate_utf8(answer, MAX_BEST_DRAFT_BYTES)
            limitations.append(
                "structured result exceeded the inline size limit and must be "
                "returned by artifact reference"
            )

        return TaskResult(
            protocol_version=PROTOCOL_VERSION,
            collaboration_id=task.collaboration_id,
            task_id=task.task_id,
            agent_name=self.agent_name,
            status=status,
            outputs=outputs,
            limitations=limitations,
            best_draft=best_draft,
            retryable=status == TaskResultStatus.PARTIAL,
            metrics=metrics,
        )
