"""Capability request/report contracts and legacy adaptation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifacts import ArtifactReference
from .base import ContractModel
from .health import RuntimeStatusRef


class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirement_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_output_schemas: List[str] = Field(default_factory=list)
    required_operations: List[str] = Field(default_factory=list)
    required_data_domains: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    required_side_effects: List[str] = Field(default_factory=list)


class CapabilityConstraints(BaseModel):
    model_config = ConfigDict(extra="allow")

    language: Optional[str] = None
    evidence_required: bool = False


class CapabilityCheckRequestV2(ContractModel):
    protocol_version: str = Field(...)
    message_type: Literal["capability_check"] = "capability_check"
    query: str = Field(min_length=1)
    explicit_target: Optional[str] = None
    requirements: List[CapabilityRequirement] = Field(default_factory=list)
    attachments: List[ArtifactReference] = Field(default_factory=list)
    constraints: CapabilityConstraints = Field(default_factory=CapabilityConstraints)


class LeadCapability(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eligible: bool = False
    ownership: Literal["primary", "secondary", "explicit", "none"] = "none"
    owned_requirements: List[str] = Field(default_factory=list)
    missing_requirements: List[str] = Field(default_factory=list)
    reason: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> "LeadCapability":
        overlap = set(self.owned_requirements) & set(self.missing_requirements)
        if overlap:
            raise ValueError(
                f"requirements cannot be both owned and missing: {sorted(overlap)}"
            )
        if self.eligible and self.ownership not in {"primary", "explicit"}:
            raise ValueError("eligible lead must have primary or explicit ownership")
        return self


class ContributionCapability(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contribution_id: str = Field(min_length=1)
    requirement_ids: List[str] = Field(min_length=1)
    operations: List[str] = Field(min_length=1)
    required_inputs: List[str] = Field(default_factory=list)
    produced_output_schemas: List[str] = Field(min_length=1)
    data_domains: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    side_effects: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)


class CapabilityRuntimeMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recent_success_rate: Optional[float] = Field(default=None, ge=0, le=1)
    recent_p95_latency_ms: Optional[int] = Field(default=None, ge=0)


class CapabilityReportV2(ContractModel):
    protocol_version: str = Field(...)
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    capability_manifest_version: str = Field(min_length=1)
    runtime_status_ref: RuntimeStatusRef
    lead: LeadCapability
    contributions: List[ContributionCapability] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    runtime_metrics: CapabilityRuntimeMetrics = Field(
        default_factory=CapabilityRuntimeMetrics
    )
    fit_score: Optional[float] = Field(default=None, ge=0, le=1)
    degraded_legacy_adapter: bool = False

    @model_validator(mode="after")
    def _unique_contributions(self) -> "CapabilityReportV2":
        ids = [item.contribution_id for item in self.contributions]
        if len(ids) != len(set(ids)):
            raise ValueError("contribution_id values must be unique")
        return self


class CapabilityManifest(BaseModel):
    """Authoritative, runtime-loaded capabilities used to gate self-reports."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    agent_id: str = Field(min_length=1)
    manifest_version: str = Field(min_length=1)
    lead_supported: bool = False
    operations: List[str] = Field(default_factory=list)
    input_types: List[str] = Field(default_factory=list)
    output_schemas: List[str] = Field(default_factory=list)
    data_domains: List[str] = Field(default_factory=list)
    ready_tools: List[str] = Field(default_factory=list)
    side_effects: List[str] = Field(default_factory=list)


def adapt_legacy_capability_response(
    response: Dict[str, Any],
    *,
    agent_id: str,
    agent_name: str,
) -> CapabilityReportV2:
    """Represent a V1 capability response without pretending it is V2 authority."""

    canonical = json.dumps(response, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    can_handle = bool(response.get("can_handle"))
    can_contribute = bool(response.get("can_contribute")) or can_handle
    contribution_text = str(response.get("contribution") or "legacy contribution")
    contributions = []
    if can_contribute:
        contributions.append(
            ContributionCapability(
                contribution_id="legacy-contribution",
                requirement_ids=["legacy-unscoped"],
                operations=["legacy-unknown"],
                produced_output_schemas=["legacy.opaque/v1"],
                constraints=["not valid for automatic V2 executability"],
                evidence=[contribution_text],
            )
        )
    return CapabilityReportV2(
        protocol_version="multi-agent-v2",
        agent_id=agent_id,
        agent_name=agent_name,
        capability_manifest_version=f"legacy:{digest}",
        runtime_status_ref=RuntimeStatusRef(readiness_generation=0),
        lead=LeadCapability(
            eligible=can_handle,
            ownership="explicit" if can_handle else "none",
            owned_requirements=["legacy-unscoped"] if can_handle else [],
            reason=str(response.get("reason") or "legacy capability response"),
        ),
        contributions=contributions,
        limitations=[
            "Adapted from a legacy capability response; manifest intersection unavailable."
        ],
        fit_score=response.get("confidence"),
        degraded_legacy_adapter=True,
    )


def capability_report_legacy_view(report: CapabilityReportV2) -> Dict[str, Any]:
    """Project a validated V2 report into fields used by legacy selectors."""

    contribution_lines = [
        f"{item.contribution_id}: {', '.join(item.operations)}"
        for item in report.contributions
    ]
    return {
        "can_handle": report.lead.eligible,
        "confidence": report.fit_score or 0.0,
        "reason": report.lead.reason,
        "agent_name": report.agent_name,
        "can_contribute": bool(report.contributions),
        "contribution": "; ".join(contribution_lines),
        "execution_hint": {
            "protocol_version": report.protocol_version,
            "capability_report": report.model_dump(mode="json"),
        },
    }
