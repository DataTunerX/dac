"""Deterministic capability, DAG, result, and event validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set

from .capability import CapabilityManifest, CapabilityReportV2
from .collaboration import AnswerContract, ContributorDescriptor, ExecutionBudget
from .execution import (
    ExecutionEventV2,
    ExecutionState,
    InputSource,
    ParticipantTask,
    TaskNode,
    TaskResult,
    TaskResultStatus,
)
from .schemas import SchemaRegistry, UnknownSchemaError


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""


class ContractValidationError(ValueError):
    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = list(issues)
        summary = "; ".join(
            f"{issue.code}{f' at {issue.path}' if issue.path else ''}: {issue.message}"
            for issue in self.issues
        )
        super().__init__(summary or "contract validation failed")


def require_valid(issues: Sequence[ValidationIssue]) -> None:
    if issues:
        raise ContractValidationError(issues)


def validate_capability_report(
    report: CapabilityReportV2,
    manifest: CapabilityManifest,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if report.agent_id != manifest.agent_id:
        issues.append(
            ValidationIssue("agent_id_mismatch", "report and manifest agent IDs differ")
        )
    if report.capability_manifest_version != manifest.manifest_version:
        issues.append(
            ValidationIssue(
                "manifest_version_mismatch",
                "report does not reference the exact loaded capability manifest",
            )
        )
    if report.lead.eligible and not manifest.lead_supported:
        issues.append(
            ValidationIssue("lead_not_supported", "manifest does not permit lead mode")
        )

    declared = {
        "operations": set(manifest.operations),
        "output_schemas": set(manifest.output_schemas),
        "data_domains": set(manifest.data_domains),
        "required_tools": set(manifest.ready_tools),
        "side_effects": set(manifest.side_effects),
    }
    for index, contribution in enumerate(report.contributions):
        claims = {
            "operations": set(contribution.operations),
            "output_schemas": set(contribution.produced_output_schemas),
            "data_domains": set(contribution.data_domains),
            "required_tools": set(contribution.required_tools),
            "side_effects": set(contribution.side_effects),
        }
        for field, values in claims.items():
            undeclared = values - declared[field]
            if undeclared:
                issues.append(
                    ValidationIssue(
                        "undeclared_capability",
                        f"{field} not present in manifest: {sorted(undeclared)}",
                        f"contributions[{index}].{field}",
                    )
                )
    return issues


def _find_cycle(nodes: Dict[str, TaskNode]) -> Optional[List[str]]:
    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def visit(task_id: str) -> Optional[List[str]]:
        if task_id in visiting:
            start = stack.index(task_id)
            return stack[start:] + [task_id]
        if task_id in visited:
            return None
        visiting.add(task_id)
        stack.append(task_id)
        for dependency in nodes[task_id].depends_on:
            if dependency in nodes:
                cycle = visit(dependency)
                if cycle:
                    return cycle
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)
        return None

    for task_id in nodes:
        cycle = visit(task_id)
        if cycle:
            return cycle
    return None


def validate_dag(
    tasks: Sequence[TaskNode],
    *,
    contributors: Sequence[ContributorDescriptor],
    schema_registry: SchemaRegistry,
    budget: ExecutionBudget,
    answer_contract: Optional[AnswerContract] = None,
    lead_agent_id: Optional[str] = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if len(tasks) > budget.max_tasks:
        issues.append(
            ValidationIssue(
                "task_budget_exceeded",
                f"{len(tasks)} tasks exceed max_tasks={budget.max_tasks}",
            )
        )
    if budget.deadline_at is not None:
        deadline = budget.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline <= datetime.now(timezone.utc):
            issues.append(
                ValidationIssue(
                    "deadline_expired",
                    "execution budget deadline has already elapsed",
                )
            )

    nodes: Dict[str, TaskNode] = {}
    for index, task in enumerate(tasks):
        if task.task_id in nodes:
            issues.append(
                ValidationIssue(
                    "duplicate_task_id", task.task_id, f"tasks[{index}].task_id"
                )
            )
        nodes[task.task_id] = task
        for output_index, output in enumerate(task.expected_outputs):
            try:
                schema_registry.resolve(
                    output.schema_id, schema_digest_value=output.schema_digest
                )
            except UnknownSchemaError as exc:
                issues.append(
                    ValidationIssue(
                        "unknown_output_schema",
                        str(exc),
                        f"tasks[{index}].expected_outputs[{output_index}]",
                    )
                )

    contributor_by_id = {item.agent_id: item for item in contributors}
    for index, task in enumerate(tasks):
        if task.attempt >= budget.max_attempts_per_task:
            issues.append(
                ValidationIssue(
                    "attempt_budget_exhausted",
                    f"attempt={task.attempt} reaches max_attempts_per_task="
                    f"{budget.max_attempts_per_task}",
                    f"tasks[{index}].attempt",
                )
            )
        for dependency in task.depends_on:
            if dependency not in nodes:
                issues.append(
                    ValidationIssue(
                        "missing_dependency", dependency, f"tasks[{index}].depends_on"
                    )
                )
        if task.execution_target == "participant":
            contributor = contributor_by_id.get(task.assigned_agent_id)
            if contributor is None:
                issues.append(
                    ValidationIssue(
                        "agent_out_of_scope",
                        task.assigned_agent_id,
                        f"tasks[{index}].assigned_agent_id",
                    )
                )
            else:
                if task.operation not in set(contributor.allowed_operations):
                    issues.append(
                        ValidationIssue(
                            "participant_operation_not_advertised",
                            f"operation not in contributor scope: {task.operation}",
                            f"tasks[{index}].operation",
                        )
                    )
                allowed = set(contributor.allowed_output_schemas)
                undeclared = {
                    item.schema_id for item in task.expected_outputs
                } - allowed
                if undeclared:
                    issues.append(
                        ValidationIssue(
                            "participant_schema_not_advertised",
                            f"schemas not in contributor scope: {sorted(undeclared)}",
                            f"tasks[{index}].expected_outputs",
                        )
                    )
        elif lead_agent_id and task.assigned_agent_id != lead_agent_id:
            issues.append(
                ValidationIssue(
                    "invalid_local_assignment",
                    "local task must be assigned to the lead",
                    f"tasks[{index}].assigned_agent_id",
                )
            )

        for binding_index, binding in enumerate(task.required_inputs):
            if binding.schema_id:
                try:
                    schema_registry.resolve(binding.schema_id)
                except UnknownSchemaError as exc:
                    issues.append(
                        ValidationIssue(
                            "unknown_input_schema",
                            str(exc),
                            f"tasks[{index}].required_inputs[{binding_index}]",
                        )
                    )
            if binding.source != InputSource.TASK_OUTPUT:
                continue
            upstream = nodes.get(binding.source_task_id or "")
            if upstream is None:
                issues.append(
                    ValidationIssue(
                        "missing_input_source_task",
                        f"input references unknown task {binding.source_task_id}",
                        f"tasks[{index}].required_inputs[{binding_index}]",
                    )
                )
                continue
            if binding.source_task_id not in task.depends_on:
                issues.append(
                    ValidationIssue(
                        "input_dependency_not_declared",
                        f"input uses {binding.source_task_id} but depends_on omits it",
                        f"tasks[{index}].required_inputs[{binding_index}]",
                    )
                )
            produced = {item.name: item for item in upstream.expected_outputs}
            output = produced.get(binding.source_output_name or "")
            if output is None:
                issues.append(
                    ValidationIssue(
                        "missing_upstream_output",
                        f"{binding.source_task_id}.{binding.source_output_name}",
                        f"tasks[{index}].required_inputs[{binding_index}]",
                    )
                )
            elif binding.schema_id and output.schema_id != binding.schema_id:
                issues.append(
                    ValidationIssue(
                        "incompatible_input_schema",
                        f"requires {binding.schema_id}, upstream produces {output.schema_id}",
                        f"tasks[{index}].required_inputs[{binding_index}]",
                    )
                )

    cycle = _find_cycle(nodes)
    if cycle:
        issues.append(ValidationIssue("dag_cycle", " -> ".join(cycle)))

    if answer_contract is not None:
        for requirement_index, requirement in enumerate(answer_contract.requirements):
            for schema_index, schema_id in enumerate(requirement.required_schema_ids):
                try:
                    schema_registry.resolve(schema_id)
                except UnknownSchemaError as exc:
                    issues.append(
                        ValidationIssue(
                            "unknown_answer_schema",
                            str(exc),
                            "answer_contract.requirements"
                            f"[{requirement_index}].required_schema_ids[{schema_index}]",
                        )
                    )
        produced_components = {
            component for task in tasks for component in task.produces_answer_components
        }
        for requirement in answer_contract.requirements:
            if (
                requirement.mandatory
                and requirement.component_id not in produced_components
            ):
                issues.append(
                    ValidationIssue("missing_answer_producer", requirement.component_id)
                )
    return issues


def validate_task_result(
    result: TaskResult,
    task: ParticipantTask,
    schema_registry: SchemaRegistry,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if result.collaboration_id != task.collaboration_id:
        issues.append(
            ValidationIssue(
                "collaboration_id_mismatch", "result belongs to another collaboration"
            )
        )
    if result.task_id != task.task_id:
        issues.append(
            ValidationIssue("task_id_mismatch", "result belongs to another task")
        )

    expected = {item.name: item for item in task.expected_outputs}
    actual = {item.name: item for item in result.outputs}
    if len(actual) != len(result.outputs):
        issues.append(
            ValidationIssue(
                "duplicate_output_name", "TaskResult output names must be unique"
            )
        )
    for name, output in actual.items():
        contract = expected.get(name)
        if contract is None:
            issues.append(ValidationIssue("unexpected_output", name, f"outputs.{name}"))
            continue
        if output.schema_id != contract.schema_id:
            issues.append(
                ValidationIssue(
                    "output_schema_mismatch",
                    f"expected {contract.schema_id}, got {output.schema_id}",
                    f"outputs.{name}",
                )
            )
            continue
        if not output.schema_digest:
            issues.append(
                ValidationIssue(
                    "missing_output_digest",
                    "typed TaskResult outputs must carry the registered schema digest",
                    f"outputs.{name}",
                )
            )
        if (
            output.schema_digest
            and contract.schema_digest
            and output.schema_digest != contract.schema_digest
        ):
            issues.append(
                ValidationIssue(
                    "output_digest_mismatch",
                    f"expected {contract.schema_digest}, got {output.schema_digest}",
                    f"outputs.{name}",
                )
            )
            continue
        try:
            schema_registry.validate_data(
                output.schema_id,
                output.data,
                schema_digest_value=output.schema_digest or contract.schema_digest,
            )
        except (ValueError, LookupError) as exc:
            issues.append(
                ValidationIssue("invalid_output_data", str(exc), f"outputs.{name}")
            )

    missing = [
        name for name, item in expected.items() if item.mandatory and name not in actual
    ]
    if result.status == TaskResultStatus.SUCCESS and missing:
        issues.append(
            ValidationIssue("missing_mandatory_output", f"missing outputs: {missing}")
        )
    if result.status == TaskResultStatus.SUCCESS and result.invalid_outputs:
        issues.append(
            ValidationIssue(
                "success_with_invalid_outputs",
                "successful result reports invalid outputs",
            )
        )
    return issues


_ALLOWED_TRANSITIONS = {
    ExecutionState.RECEIVED: {
        ExecutionState.CONTRACT_DEFINED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.CONTRACT_DEFINED: {
        ExecutionState.DAG_PLANNED,
        ExecutionState.EXECUTING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.DAG_PLANNED: {
        ExecutionState.DAG_VALIDATED,
        ExecutionState.REPLANNING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.DAG_VALIDATED: {
        ExecutionState.EXECUTING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.EXECUTING: {
        ExecutionState.VALIDATING_RESULTS,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.VALIDATING_RESULTS: {
        ExecutionState.REPLANNING,
        ExecutionState.SYNTHESIZING,
        ExecutionState.PARTIAL,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.REPLANNING: {
        ExecutionState.DAG_PLANNED,
        ExecutionState.EXECUTING,
        ExecutionState.PARTIAL,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.SYNTHESIZING: {
        ExecutionState.FINAL_VALIDATION,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.FINAL_VALIDATION: {
        ExecutionState.COMPLETED,
        ExecutionState.PARTIAL,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.COMPLETED: set(),
    ExecutionState.PARTIAL: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.CANCELLED: set(),
}


def validate_event_transition(event: ExecutionEventV2) -> List[ValidationIssue]:
    if event.previous_state is None:
        if event.current_state != ExecutionState.RECEIVED:
            return [
                ValidationIssue(
                    "invalid_initial_state", "first event must enter received"
                )
            ]
        return []
    allowed = _ALLOWED_TRANSITIONS[event.previous_state]
    if event.current_state not in allowed:
        return [
            ValidationIssue(
                "invalid_state_transition",
                f"{event.previous_state} -> {event.current_state}",
            )
        ]
    return []
