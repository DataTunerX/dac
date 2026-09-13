"""Immutable output-schema descriptors and an in-memory resolver."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .artifacts import ClaimEvidence
from .json_schema import (
    JsonSchemaDefinitionError,
    JsonSchemaValueError,
    check_schema,
    validate,
)
from .limits import MAX_SCHEMA_BYTES

CLAIM_EVIDENCE_SCHEMA_ID = "dac.claim-evidence/v1"
_SCHEMA_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*/v[1-9][0-9]*$"
)


def canonical_schema_json(schema: Dict[str, Any]) -> str:
    return json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def schema_digest(schema: Dict[str, Any]) -> str:
    payload = canonical_schema_json(schema).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class SchemaDescriptor(BaseModel):
    model_config = ConfigDict(
        extra="ignore", frozen=True, populate_by_name=True, serialize_by_alias=True
    )

    schema_id: str = Field(min_length=1)
    schema_digest: Optional[str] = None
    schema_body: Dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    owner: str = Field(min_length=1)
    description: str = ""
    media_type: str = "application/json"

    @field_validator("schema_id")
    @classmethod
    def _valid_schema_id(cls, value: str) -> str:
        value = value.strip()
        if not _SCHEMA_ID_RE.fullmatch(value):
            raise ValueError(
                "schema_id must be a lowercase namespaced identifier ending in /vN"
            )
        return value

    @model_validator(mode="after")
    def _validate_digest_and_schema(self) -> "SchemaDescriptor":
        size = len(canonical_schema_json(self.schema_body).encode("utf-8"))
        if size > MAX_SCHEMA_BYTES:
            raise ValueError(
                f"JSON Schema is {size} bytes; maximum is {MAX_SCHEMA_BYTES}"
            )
        try:
            check_schema(self.schema_body)
        except JsonSchemaDefinitionError as exc:
            raise ValueError(f"invalid JSON Schema: {exc}") from exc
        expected = schema_digest(self.schema_body)
        if self.schema_digest and self.schema_digest != expected:
            raise ValueError(
                f"schema_digest mismatch: declared {self.schema_digest}, computed {expected}"
            )
        object.__setattr__(self, "schema_digest", expected)
        return self


class SchemaReference(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_id: str = Field(min_length=1)
    schema_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    owner: str = Field(min_length=1)
    skill_name: Optional[str] = None


class SchemaConflictError(ValueError):
    """Raised when an immutable schema ID is reused with different content."""


class UnknownSchemaError(LookupError):
    """Raised when a typed dependency references an unregistered schema."""


class SchemaDataValidationError(ValueError):
    """Raised when output data does not satisfy its registered JSON Schema."""


class SchemaRegistry:
    """Small resolver used by validators and mirrored by the registry service."""

    def __init__(self, descriptors: Iterable[SchemaDescriptor] = ()) -> None:
        self._descriptors: Dict[str, SchemaDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: SchemaDescriptor) -> SchemaDescriptor:
        snapshot = SchemaDescriptor.model_validate_json(
            descriptor.model_dump_json(by_alias=True)
        )
        existing = self._descriptors.get(snapshot.schema_id)
        if existing and existing.schema_digest != snapshot.schema_digest:
            raise SchemaConflictError(
                f"immutable schema conflict for {snapshot.schema_id}: "
                f"{existing.schema_digest} != {snapshot.schema_digest}"
            )
        self._descriptors[snapshot.schema_id] = snapshot
        return self.resolve(snapshot.schema_id)

    def resolve(
        self, schema_id: str, *, schema_digest_value: Optional[str] = None
    ) -> SchemaDescriptor:
        descriptor = self._descriptors.get(schema_id)
        if descriptor is None:
            raise UnknownSchemaError(f"unknown schema_id: {schema_id}")
        if schema_digest_value and descriptor.schema_digest != schema_digest_value:
            raise UnknownSchemaError(
                f"schema digest mismatch for {schema_id}: expected "
                f"{schema_digest_value}, registry has {descriptor.schema_digest}"
            )
        return SchemaDescriptor.model_validate_json(
            descriptor.model_dump_json(by_alias=True)
        )

    def validate_data(
        self,
        schema_id: str,
        data: Any,
        *,
        schema_digest_value: Optional[str] = None,
    ) -> None:
        descriptor = self.resolve(schema_id, schema_digest_value=schema_digest_value)
        try:
            validate(data, descriptor.schema_body)
        except JsonSchemaValueError as exc:
            location = ".".join(str(part) for part in exc.path) or "$"
            raise SchemaDataValidationError(
                f"{schema_id} validation failed at {location}: {exc.message}"
            ) from exc

    def descriptors(self) -> list[SchemaDescriptor]:
        return [self.resolve(key) for key in sorted(self._descriptors)]


def _claim_evidence_schema() -> Dict[str, Any]:
    item_schema = ClaimEvidence.model_json_schema()
    definitions = item_schema.pop("$defs", {})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DAC Claim Evidence List",
        "type": "array",
        "$defs": definitions,
        "items": item_schema,
    }


CORE_SCHEMA_DESCRIPTORS = (
    SchemaDescriptor(
        schema_id=CLAIM_EVIDENCE_SCHEMA_ID,
        owner="dac",
        description="Evidence-grounded claims with provenance and epistemic status.",
        schema=_claim_evidence_schema(),
    ),
)


def core_schema_registry() -> SchemaRegistry:
    return SchemaRegistry(CORE_SCHEMA_DESCRIPTORS)
