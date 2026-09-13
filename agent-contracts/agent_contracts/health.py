"""Runtime readiness and registry discovery contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import ContractModel
from .schemas import SchemaReference
from .version import PROTOCOL_VERSION


class HealthState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class IndexState(str, Enum):
    INDEXED = "indexed"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AgentRuntimeStatus(ContractModel):
    protocol_version: str = Field(...)
    agent_id: str = Field(min_length=1)
    agent_url: str = Field(min_length=1)
    card_revision: str = Field(min_length=1)
    capability_manifest_version: str = Field(min_length=1)
    supported_protocol_versions: List[str] = Field(
        default_factory=lambda: [PROTOCOL_VERSION]
    )
    agent_ready: HealthState = HealthState.UNKNOWN
    skills_state: HealthState = HealthState.UNKNOWN
    tools_state: HealthState = HealthState.UNKNOWN
    model_state: HealthState = HealthState.UNKNOWN
    loaded_skills: List[str] = Field(default_factory=list)
    ready_tools: List[str] = Field(default_factory=list)
    unavailable_tools: List[str] = Field(default_factory=list)
    registered_output_schemas: List[SchemaReference] = Field(default_factory=list)
    recent_execution_health: HealthState = HealthState.UNKNOWN
    readiness_generation: int = Field(default=0, ge=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("supported_protocol_versions")
    @classmethod
    def _nonempty_protocols(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("supported_protocol_versions must not be empty")
        return value

    @model_validator(mode="after")
    def _canonical_identity(self) -> "AgentRuntimeStatus":
        if self.agent_id != self.agent_url:
            raise ValueError("agent_id must equal the canonical AgentCard URL")
        return self


class RuntimeStatusRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    readiness_generation: int = Field(ge=0)


class AgentIndexStatus(ContractModel):
    protocol_version: str = Field(...)
    agent_url: str = Field(min_length=1)
    state: IndexState = IndexState.UNKNOWN
    generation: int = Field(default=0, ge=0)
    error: Optional[str] = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentDiscoveryRecord(ContractModel):
    """Consistent discovery view over a card and its independent health records."""

    protocol_version: str = Field(...)

    canonical_agent_id: str = Field(min_length=1)
    aliases: List[str] = Field(default_factory=list)
    agent_card: Dict[str, Any]
    runtime_status: AgentRuntimeStatus
    heartbeat_fresh: bool
    heartbeat_age_ms: Optional[int] = Field(default=None, ge=0)
    index_status: AgentIndexStatus

    @model_validator(mode="after")
    def _joined_identity(self) -> "AgentDiscoveryRecord":
        if self.runtime_status.agent_id != self.canonical_agent_id:
            raise ValueError("runtime status belongs to another canonical agent")
        if self.index_status.agent_url != self.canonical_agent_id:
            raise ValueError("index status belongs to another canonical agent")
        return self
