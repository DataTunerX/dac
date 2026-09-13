"""Typed task outputs, artifacts, and evidence references."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceStatus(str, Enum):
    ESTABLISHED = "Established"
    INFERENCE = "Inference"
    NOT_ESTABLISHED = "Not established"


class CharacterSpan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "CharacterSpan":
        if self.end <= self.start:
            raise ValueError("char_span.end must be greater than char_span.start")
        return self


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str = Field(min_length=1)
    statement_id: Optional[str] = None
    char_span: Optional[CharacterSpan] = None
    description: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifact_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    media_type: str = "application/octet-stream"
    digest: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("uri")
    @classmethod
    def _reference_only(cls, value: str) -> str:
        value = value.strip()
        if value.lower().startswith("data:"):
            raise ValueError(
                "binary artifacts must be referenced, not embedded as data URIs"
            )
        return value


class ClaimEvidence(BaseModel):
    """Canonical item in the ``dac.claim-evidence/v1`` output schema."""

    model_config = ConfigDict(extra="ignore")

    claim: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    status: EvidenceStatus
    domain: Optional[str] = None
    statement_id: Optional[str] = None
    predicate: Optional[str] = None
    char_span: Optional[CharacterSpan] = None
    supporting_evidence: List[str] = Field(default_factory=list)
    conflicting_evidence: List[str] = Field(default_factory=list)
    unresolved_limitations: List[str] = Field(default_factory=list)


class ExpectedOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    schema_id: str = Field(min_length=1)
    schema_digest: Optional[str] = None
    mandatory: bool = True


class TaskOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    schema_id: str = Field(min_length=1)
    schema_digest: Optional[str] = None
    data: Any
