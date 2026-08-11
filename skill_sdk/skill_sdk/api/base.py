from pydantic import BaseModel, Field


class SkillScript(BaseModel):
    """Reference to an executable script bundled with a skill."""

    script_name: str = Field(..., description="Logical name of the script")
    script_path: str = Field(..., description="Filesystem path to the executable script")
    interpreter: str = Field(
        default="",
        description=(
            "Recommended interpreter for running this script (e.g. 'python3', 'bash', 'node'). "
            "Empty when the loader cannot detect one and the caller should decide."
        ),
    )

    @property
    def invocation(self) -> str:
        """Suggested command line to run this script.

        - If ``interpreter`` is known, returns ``"<interpreter> <script_path>"``.
        - Otherwise returns the absolute path (caller may rely on shebang / chmod).
        """
        return f"{self.interpreter} {self.script_path}" if self.interpreter else self.script_path


class Skill(BaseModel):
    """A skill record with display metadata and full detail text."""

    name: str = Field(..., description="Skill display name")
    description: str = Field(..., description="Short summary of what the skill does")
    detail: str = Field(..., description="Full instructions or body, often Markdown")
    version: str = Field(..., description="Semantic or opaque version string")
    scripts: list[SkillScript] = Field(
        default_factory=list,
        description="Executable scripts associated with this skill",
    )
    base_dir: str = Field(
        default="",
        description=(
            "Absolute path to the extracted skill root (directory containing "
            "``_meta.json`` / ``SKILL.md``). Empty when the skill is built in-memory."
        ),
    )
    resource_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Relative names of non-empty top-level directories (e.g. ``assets``, "
            "``hooks``, ``references``) that live alongside ``scripts/``. Useful for "
            "pointing an LLM runtime at bundled docs / configs."
        ),
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Optional allow-list of tool names declared in ``_meta.json``. "
            "When non-empty, the runner only binds/allows these tools "
            "(plus the always-available ``finish`` tool). "
            "Empty list means unrestricted (backward compatible)."
        ),
    )

    def to_json(self, *, indent: int = 2, ensure_ascii: bool = False) -> str:
        """
        Serialize to a JSON object string with keys
        ``name``, ``description``, ``detail``, ``version``, ``scripts``,
        ``base_dir``, ``resource_dirs``, ``allowed_tools``
        (same shape as skill pack exports).
        """
        return self.model_dump_json(indent=indent, ensure_ascii=ensure_ascii)
