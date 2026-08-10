"""Pydantic models exposed by the skill-hub HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_NAMESPACE = "default"


class SkillInfo(BaseModel):
    """Public-facing metadata for a single skill (latest version)."""

    name: str = Field(..., description="Skill display name (from SKILL.md)")
    namespace: str = Field(
        default=DEFAULT_NAMESPACE,
        description="Namespace the skill belongs to (default=default)",
    )
    description: str = Field(..., description="Short summary of the skill")
    version: str = Field(
        ..., description="Latest version string parsed from _meta.json"
    )
    filename: str = Field(
        ..., description="Actual zip filename on disk for the latest version"
    )
    download_url: str = Field(
        ..., description="Relative URL that serves the latest version"
    )
    available_versions: list[str] = Field(
        default_factory=list,
        description="All known versions for this skill, newest first",
    )


class SkillListResponse(BaseModel):
    count: int = Field(..., description="Number of distinct skills")
    skills_dir: str = Field(..., description="Directory scanned on the server")
    skills: list[SkillInfo] = Field(default_factory=list)


class NamespaceInfo(BaseModel):
    """Metadata for a single namespace."""

    id: str = Field(..., description="Namespace identifier")
    visibility: str = Field(
        default="public",
        description=(
            "Namespace visibility (always 'public' for now; 'private' reserved)"
        ),
    )


class NamespaceExistsResponse(BaseModel):
    """Result of an explicit namespace existence check."""

    namespace: str = Field(..., description="Namespace identifier that was queried")
    exists: bool = Field(..., description="Whether the namespace currently exists")


class NamespaceListResponse(BaseModel):
    count: int = Field(..., description="Number of namespaces")
    namespaces: list[NamespaceInfo] = Field(default_factory=list)
