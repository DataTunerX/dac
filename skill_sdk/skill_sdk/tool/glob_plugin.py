"""Filesystem glob search as a ToolPlugin (aligned with Claude Code GlobTool + glob.ts)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)

GLOB_TOOL_NAME = "glob"

DESCRIPTION = """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead"""

DEFAULT_MAX_RESULTS = 100


def _working_directory() -> str:
    """Return a usable cwd for ``relpath``; survives deleted cwd (Unix)."""
    try:
        return os.getcwd()
    except FileNotFoundError:
        pwd = os.environ.get("PWD", "")
        if pwd and os.path.isdir(pwd):
            return pwd
        home = os.path.expanduser("~")
        return home if os.path.isdir(home) else "/"


_FILE_NOT_FOUND_HINT = (
    "If the path is relative, it is resolved against the process current working directory."
)


class GlobInput(BaseModel):
    pattern: str = Field(description="The glob pattern to match files against")
    path: str | None = Field(
        default=None,
        description=(
            "The directory to search in. If not specified, the current working directory "
            "will be used. IMPORTANT: Omit this field to use the default directory. "
            "DO NOT enter \"undefined\" or \"null\" — omit it for the default behavior. "
            "Must be a valid directory path if provided."
        ),
    )


def extract_glob_base_directory(pattern: str) -> tuple[str, str]:
    """Split an absolute glob into (base_dir, relative_pattern)."""
    if not pattern:
        return ("", "")
    match = re.search(r"[*?[{]", pattern)
    if not match:
        parent = os.path.dirname(pattern)
        base = os.path.basename(pattern)
        return (parent, base)

    idx = match.start()
    static_prefix = pattern[:idx]
    last_sep = max(static_prefix.rfind("/"), static_prefix.rfind(os.sep))
    if last_sep == -1:
        return ("", pattern)

    base_dir = static_prefix[:last_sep]
    relative_pattern = pattern[last_sep + 1 :]

    if base_dir == "" and last_sep == 0:
        base_dir = "/"

    if os.name == "nt" and re.fullmatch(r"[A-Za-z]:", base_dir):
        base_dir = base_dir + os.sep

    return (base_dir, relative_pattern)


def _safe_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return float("-inf")


def run_file_glob(
    pattern: str,
    search_root: str,
    *,
    cwd_for_relative: str,
    limit: int = DEFAULT_MAX_RESULTS,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute glob under ``search_root``; return structured result.

    Paths in ``filenames`` are relative to ``cwd_for_relative`` when possible.
    """
    start = time.perf_counter()
    pattern = pattern.strip()
    root_path = Path(search_root).expanduser().resolve()
    search_pattern = pattern

    if os.path.isabs(pattern):
        base_dir, relative_pattern = extract_glob_base_directory(pattern)
        if base_dir:
            root_path = Path(base_dir).expanduser().resolve()
            search_pattern = relative_pattern

    if not search_pattern:
        paths = []
    else:
        paths = [
            p
            for p in root_path.glob(search_pattern)
            if p.exists() and p.is_file()
        ]
        paths = sorted(paths, key=_safe_mtime)

    abs_paths = [p.resolve() for p in paths]
    truncated = len(abs_paths) > offset + limit
    selected = abs_paths[offset : offset + limit]

    cwd_resolved = Path(cwd_for_relative).expanduser().resolve()
    filenames: list[str] = []
    for p in selected:
        try:
            filenames.append(os.path.relpath(p, cwd_resolved))
        except ValueError:
            filenames.append(str(p))

    duration_ms = int((time.perf_counter() - start) * 1000)
    return {
        "durationMs": duration_ms,
        "numFiles": len(filenames),
        "filenames": filenames,
        "truncated": truncated,
    }


class GlobPlugin(ToolPlugin):
    """Find files under a directory using pathlib glob semantics."""

    name = GLOB_TOOL_NAME
    description = DESCRIPTION.strip()
    args_schema = GlobInput

    def execute(self, **kwargs: Any) -> str:
        pattern_raw = kwargs.get("pattern", "")
        pattern = str(pattern_raw).strip() if pattern_raw is not None else ""
        path_raw = kwargs.get("path")
        path_opt = None if path_raw is None else str(path_raw).strip()
        if path_opt in ("", "undefined", "null"):
            path_opt = None

        if not pattern:
            return self._format_error("pattern is required", error_code=1)

        cwd = _working_directory()
        search_root = cwd
        if path_opt is not None:
            expanded = os.path.expanduser(path_opt)
            abs_path = os.path.abspath(expanded)

            if abs_path.startswith("\\\\") or abs_path.startswith("//"):
                search_root = abs_path
            else:
                p = Path(abs_path)
                if not p.exists():
                    msg = (
                        f"Directory does not exist: {path_opt}. {_FILE_NOT_FOUND_HINT} "
                        f"CWD is {cwd}."
                    )
                    return self._format_error(msg, error_code=1)
                if not p.is_dir():
                    return self._format_error(f"Path is not a directory: {path_opt}", error_code=2)
                search_root = str(p.resolve())

        limit_env = os.environ.get("SKILL_SDK_GLOB_MAX_RESULTS", "").strip()
        limit = DEFAULT_MAX_RESULTS
        if limit_env.isdigit():
            limit = max(1, min(int(limit_env), 10_000))

        try:
            out = run_file_glob(
                pattern,
                search_root,
                cwd_for_relative=cwd,
                limit=limit,
                offset=0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("glob failed")
            return self._format_error(f"Glob failed: {exc}", error_code=3)

        return json.dumps(out, ensure_ascii=False)
