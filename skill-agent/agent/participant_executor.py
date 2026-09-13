"""Strict one-task participant execution for multi-agent V2."""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from agent_contracts import (
    ParticipantTask,
    TaskError,
    TaskResult,
    TaskResultStatus,
    validate_task_result,
)

from .local_task_executor import LocalTaskExecutor

ProgressCallback = Callable[..., Awaitable[None]]


class ParticipantExecutor:
    """Validate, execute, and validate one task without collaboration powers."""

    def __init__(self, local_executor: LocalTaskExecutor) -> None:
        self.local_executor = local_executor

    async def execute(
        self,
        task: ParticipantTask,
        *,
        user_id: str = "",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TaskResult:
        result = await self.local_executor.execute(
            task,
            user_id=user_id,
            progress_callback=progress_callback,
        )
        issues = validate_task_result(
            result,
            task,
            self.local_executor.schema_registry,
        )
        if not issues:
            return result

        invalid = [f"{issue.code}: {issue.message}" for issue in issues]
        if result.outputs or result.artifacts or result.evidence or result.best_draft:
            return result.model_copy(
                update={
                    "status": TaskResultStatus.PARTIAL,
                    "invalid_outputs": result.invalid_outputs + invalid,
                    "limitations": result.limitations
                    + ["one or more outputs failed contract validation"],
                    "retryable": True,
                }
            )
        return result.model_copy(
            update={
                "status": TaskResultStatus.FAILED,
                "invalid_outputs": result.invalid_outputs + invalid,
                "error": result.error
                or TaskError(
                    code="result_contract_invalid",
                    message="; ".join(invalid),
                ),
                "retryable": True,
            }
        )
