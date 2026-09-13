"""Lead assignment, contributor scope, budgets, and answer contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import ContractModel
from .capability import CapabilityReportV2
from .limits import MAX_INLINE_RESULT_BYTES, MAX_INLINE_TASK_CONTEXT_BYTES
from .version import PROTOCOL_VERSION


class ExecutionBudget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deadline_ms: int = Field(default=600000, ge=1)
    max_tasks: int = Field(default=10, ge=1)
    max_rounds: int = Field(default=3, ge=1)
    max_concurrency: int = Field(default=3, ge=1)
    max_attempts_per_task: int = Field(default=2, ge=1)
    max_pool_expansions: int = Field(default=1, ge=0)
    max_model_calls: int = Field(default=20, ge=1)
    max_total_tokens: int = Field(default=120000, ge=1)
    max_a2a_calls: int = Field(default=20, ge=1)
    deadline_at: Optional[datetime] = None


class AnswerRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    component_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_schema_ids: List[str] = Field(default_factory=list)
    mandatory: bool = True


class AnswerContract(ContractModel):
    protocol_version: str = Field(...)
    requirements: List[AnswerRequirement] = Field(default_factory=list)
    language: Optional[str] = None
    evidence_required: bool = False
    formatting_constraints: Dict[str, Any] = Field(default_factory=dict)
    distinctions: List[str] = Field(default_factory=list)
    prohibited_claims: List[str] = Field(default_factory=list)


class ContributorDescriptor(ContractModel):
    model_config = ConfigDict(extra="ignore")

    protocol_version: str = PROTOCOL_VERSION
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    agent_url: str = Field(min_length=1)
    capability_manifest_version: str = Field(min_length=1)
    readiness_generation: int = Field(ge=0)
    allowed_contribution_ids: List[str] = Field(default_factory=list)
    allowed_operations: List[str] = Field(default_factory=list)
    accepted_input_schemas: List[str] = Field(default_factory=list)
    allowed_output_schemas: List[str] = Field(default_factory=list)
    allowed_data_domains: List[str] = Field(default_factory=list)
    ready_tools: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    request_timeout_ms: int = Field(default=120000, ge=1)
    max_inline_context_bytes: int = Field(default=MAX_INLINE_TASK_CONTEXT_BYTES, ge=1)
    max_inline_result_bytes: int = Field(default=MAX_INLINE_RESULT_BYTES, ge=1)

    @model_validator(mode="after")
    def _canonical_identity(self) -> "ContributorDescriptor":
        if self.agent_id != self.agent_url:
            raise ValueError(
                "contributor agent_id must equal its canonical AgentCard URL"
            )
        return self


class RoutingIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    explicit_agent: Optional[str] = None
    collaboration_allowed: bool = True


class AssignmentTrace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str = ""
    trace_id: str = ""
    user_id: str = ""


class LeadAssignment(ContractModel):
    protocol_version: str = Field(...)
    execution_mode: Literal["lead"] = "lead"
    collaboration_id: str = Field(min_length=1)
    scope_revision: str = Field(min_length=1)
    query: str = Field(min_length=1)
    routing_intent: RoutingIntent = Field(default_factory=RoutingIntent)
    lead: ContributorDescriptor
    contributors: List[ContributorDescriptor] = Field(default_factory=list)
    capability_reports: List[CapabilityReportV2] = Field(default_factory=list)
    answer_contract: Optional[AnswerContract] = None
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    trace: AssignmentTrace = Field(default_factory=AssignmentTrace)
    routing_evidence: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_scope(self) -> "LeadAssignment":
        contributor_ids = [item.agent_id for item in self.contributors]
        if self.lead.agent_id in contributor_ids:
            raise ValueError("lead cannot also appear in the contributor pool")
        if len(contributor_ids) != len(set(contributor_ids)):
            raise ValueError("contributor agent IDs must be unique")
        return self


class ContributorExpansionRequest(ContractModel):
    protocol_version: str = Field(...)
    collaboration_id: str = Field(min_length=1)
    lead_agent_id: str = Field(min_length=1)
    requirement_description: str = Field(min_length=1)
    required_output_schemas: List[str] = Field(default_factory=list)
    existing_contributor_ids: List[str] = Field(default_factory=list)


class ContributorExpansionResponse(ContractModel):
    protocol_version: str = Field(...)
    collaboration_id: str = Field(min_length=1)
    approved: bool
    contributors: List[ContributorDescriptor] = Field(default_factory=list)
    reason: str = ""
