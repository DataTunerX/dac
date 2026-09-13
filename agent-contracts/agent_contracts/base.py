"""Base models shared by every multi-agent V2 contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from .version import PROTOCOL_VERSION, ensure_supported_protocol


class ContractModel(BaseModel):
    """Strictly versioned envelope with forward-compatible optional fields."""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    protocol_version: str = PROTOCOL_VERSION

    @field_validator("protocol_version")
    @classmethod
    def _supported_protocol(cls, value: str) -> str:
        return ensure_supported_protocol(value)
