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


class CreateSkillRequest(BaseModel):
    """JSON body for creating a skill pack without uploading a pre-built zip.

    Fields map onto the skill_sdk pack layout:

    - ``name`` / ``description`` / ``detail`` → ``SKILL.md``
    - ``version`` / ``allowed_tools`` → ``_meta.json``
    - ``slug`` in ``_meta.json`` is always set to ``name`` (not a request field)
    """

    name: str = Field(..., description="Skill name (SKILL.md frontmatter)")
    description: str = Field(
        ..., description="Short summary (SKILL.md frontmatter)"
    )
    detail: str = Field(
        default="",
        description="Full instructions / markdown body after SKILL.md frontmatter",
    )
    version: str = Field(
        default="1.0.0",
        description="Version string written to _meta.json",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Optional tool allow-list for the skill runner. Empty means unrestricted."
        ),
    )


class SkillListResponse(BaseModel):
    count: int = Field(..., description="Number of distinct skills")
    skills_dir: str = Field(..., description="Directory scanned on the server")
    skills: list[SkillInfo] = Field(default_factory=list)


class SkillScriptInfo(BaseModel):
    """Script entry exposed in skill detail (paths relative / logical only)."""

    script_name: str = Field(..., description="Path relative to scripts/")
    interpreter: str = Field(
        default="",
        description="Recommended interpreter (e.g. python3, bash)",
    )


class SkillDetail(BaseModel):
    """Full skill pack metadata loaded from the zip via skill_sdk.

    Used by UI detail dialogs. List APIs stay lean (``SkillInfo``); this model
    adds pack internals that require opening the zip:

    - ``detail`` ← ``SKILL.md`` body after YAML frontmatter
    - ``allowed_tools`` ← ``_meta.json`` (empty list = unrestricted)
    - ``scripts`` / ``resource_dirs`` ← discovered under the pack root
    """

    name: str
    namespace: str = DEFAULT_NAMESPACE
    description: str
    detail: str = Field(
        default="",
        description="SKILL.md body (full instructions)",
    )
    version: str
    filename: str
    download_url: str = ""
    available_versions: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tool allow-list; empty means unrestricted",
    )
    scripts: list[SkillScriptInfo] = Field(default_factory=list)
    resource_dirs: list[str] = Field(default_factory=list)


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
