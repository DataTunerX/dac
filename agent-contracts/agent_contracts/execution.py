"""DAG nodes, participant tasks/results, and execution events."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifacts import ArtifactReference, EvidenceReference, ExpectedOutput, TaskOutput
from .base import ContractModel
from .limits import (
    MAX_BEST_DRAFT_BYTES,
    MAX_INLINE_RESULT_BYTES,
    MAX_INLINE_TASK_CONTEXT_BYTES,
    json_size_bytes,
)


class InputSource(str, Enum):
    USER = "user"
    ATTACHMENT = "attachment"
    TASK_OUTPUT = "task_output"
    LITERAL = "literal"


class InputBinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    source: InputSource
    source_task_id: Optional[str] = None
    source_output_name: Optional[str] = None
    schema_id: Optional[str] = None
    value: Any = None

    @model_validator(mode="after")
    def _valid_source(self) -> "InputBinding":
        if self.source == InputSource.TASK_OUTPUT:
            if not self.source_task_id or not self.source_output_name:
                raise ValueError(
                    "task_output bindings require source_task_id and source_output_name"
                )
        return self


class TaskNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    assigned_agent_id: str = Field(min_length=1)
    assigned_agent_name: Optional[str] = None
    execution_target: Literal["local", "participant"]
    depends_on: List[str] = Field(default_factory=list)
    required_inputs: List[InputBinding] = Field(default_factory=list)
    expected_outputs: List[ExpectedOutput] = Field(min_length=1)
    evidence_requirements: List[str] = Field(default_factory=list)
    produces_answer_components: List[str] = Field(default_factory=list)
    mandatory: bool = True
    status: Literal[
        "planned",
        "ready",
        "running",
        "success",
        "partial",
        "blocked",
        "failed",
        "cancelled",
    ] = "planned"
    attempt: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _unique_outputs(self) -> "TaskNode":
        names = [item.name for item in self.expected_outputs]
        if len(names) != len(set(names)):
            raise ValueError("task expected output names must be unique")
        return self


class ParticipantConstraints(BaseModel):
    model_config = ConfigDict(extra="allow")

    do_not_delegate: Literal[True] = True
    deadline_ms: int = Field(default=120000, ge=1)
    max_local_steps: int = Field(default=12, ge=1)
    required_skill: Optional[str] = None


class TaskTrace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    parent_task_id: Optional[str] = None
    run_id: str = ""
    trace_id: str = ""


class ParticipantTask(ContractModel):
    protocol_version: str = Field(...)
    execution_mode: Literal["participant"] = "participant"
    collaboration_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    input_artifacts: List[ArtifactReference] = Field(default_factory=list)
    expected_outputs: List[ExpectedOutput] = Field(min_length=1)
    evidence_requirements: List[str] = Field(default_factory=list)
    constraints: ParticipantConstraints = Field(default_factory=ParticipantConstraints)
    trace: TaskTrace = Field(default_factory=TaskTrace)

    @model_validator(mode="after")
    def _unique_output_names(self) -> "ParticipantTask":
        names = [item.name for item in self.expected_outputs]
        if len(names) != len(set(names)):
            raise ValueError("expected output names must be unique")
        context_size = json_size_bytes(
            {
                "objective": self.objective,
                "inputs": self.inputs,
                "evidence_requirements": self.evidence_requirements,
            }
        )
        if context_size > MAX_INLINE_TASK_CONTEXT_BYTES:
            raise ValueError(
                f"inline task context is {context_size} bytes; maximum is "
                f"{MAX_INLINE_TASK_CONTEXT_BYTES}; use ArtifactReference inputs"
            )
        return self


class TaskResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration_ms: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    local_steps: int = Field(default=0, ge=0)
    attempted_skills: List[str] = Field(default_factory=list)


class TaskError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: Dict[str, Any] = Field(default_factory=dict)


class TaskResult(ContractModel):
    protocol_version: str = Field(...)
    collaboration_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    status: TaskResultStatus
    outputs: List[TaskOutput] = Field(default_factory=list)
    artifacts: List[ArtifactReference] = Field(default_factory=list)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)
    missing_capabilities: List[str] = Field(default_factory=list)
    invalid_outputs: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    best_draft: Optional[str] = None
    error: Optional[TaskError] = None
    retryable: bool = False
    metrics: TaskMetrics = Field(default_factory=TaskMetrics)

    @model_validator(mode="after")
    def _status_shape(self) -> "TaskResult":
        if self.status == TaskResultStatus.SUCCESS and self.error is not None:
            raise ValueError("successful TaskResult cannot contain an error")
        if self.status == TaskResultStatus.BLOCKED and not (
            self.missing_inputs or self.missing_capabilities or self.error
        ):
            raise ValueError("blocked TaskResult must explain what is missing")
        if (
            self.status
            in {
                TaskResultStatus.FAILED,
                TaskResultStatus.CANCELLED,
            }
            and self.error is None
        ):
            raise ValueError(
                "failed or cancelled TaskResult must include an error code"
            )
        if self.status == TaskResultStatus.PARTIAL and not (
            self.outputs or self.artifacts or self.evidence or self.best_draft
        ):
            raise ValueError(
                "partial TaskResult must preserve useful output, evidence, or a best draft"
            )
        output_size = json_size_bytes(
            [output.model_dump(mode="json") for output in self.outputs]
        )
        if output_size > MAX_INLINE_RESULT_BYTES:
            raise ValueError(
                f"inline task outputs are {output_size} bytes; maximum is "
                f"{MAX_INLINE_RESULT_BYTES}; return an ArtifactReference"
            )
        if (
            self.best_draft
            and len(self.best_draft.encode("utf-8")) > MAX_BEST_DRAFT_BYTES
        ):
            raise ValueError(f"best_draft exceeds {MAX_BEST_DRAFT_BYTES} bytes")
        return self


class ExecutionState(str, Enum):
    RECEIVED = "received"
    CONTRACT_DEFINED = "contract_defined"
    DAG_PLANNED = "dag_planned"
    DAG_VALIDATED = "dag_validated"
    EXECUTING = "executing"
    VALIDATING_RESULTS = "validating_results"
    REPLANNING = "replanning"
    SYNTHESIZING = "synthesizing"
    FINAL_VALIDATION = "final_validation"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionEventV2(ContractModel):
    protocol_version: str = Field(...)
    collaboration_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1)
    previous_state: Optional[ExecutionState] = None
    current_state: ExecutionState
    task_id: Optional[str] = None
    reason_code: Optional[str] = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)
