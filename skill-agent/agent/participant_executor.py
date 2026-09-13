"""Strict one-task participant execution for multi-agent V2."""

from __future__ import annotations

from collections import Counter
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

_NON_RETRYABLE_CONTRACT_ISSUES = {
    "collaboration_id_mismatch",
    "task_id_mismatch",
    "output_schema_mismatch",
    "output_digest_mismatch",
}


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
        invalid_names = {
            issue.path.removeprefix("outputs.").split(".", 1)[0]
            for issue in issues
            if issue.path.startswith("outputs.")
        }
        output_counts = Counter(output.name for output in result.outputs)
        invalid_names.update(
            name for name, count in output_counts.items() if count > 1
        )
        if any(
            issue.code in {"collaboration_id_mismatch", "task_id_mismatch"}
            for issue in issues
        ):
            invalid_names.update(output_counts)
        retryable = not any(
            issue.code in _NON_RETRYABLE_CONTRACT_ISSUES for issue in issues
        )
        valid_outputs = [
            output for output in result.outputs if output.name not in invalid_names
        ]
        if valid_outputs or result.artifacts or result.evidence or result.best_draft:
            return result.model_copy(
                update={
                    "status": TaskResultStatus.PARTIAL,
                    "outputs": valid_outputs,
                    "invalid_outputs": result.invalid_outputs + invalid,
                    "limitations": result.limitations
                    + ["one or more outputs failed contract validation"],
                    "retryable": retryable,
                }
            )
        return result.model_copy(
            update={
                "status": TaskResultStatus.FAILED,
                "outputs": [],
                "invalid_outputs": result.invalid_outputs + invalid,
                "error": result.error
                or TaskError(
                    code="result_contract_invalid",
                    message="; ".join(invalid),
                ),
                "retryable": retryable,
            }
        )
