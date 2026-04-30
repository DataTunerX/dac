"""Content search ToolPlugin using ripgrep (aligned with Claude Code GrepTool)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)

GREP_TOOL_NAME = "grep"

DESCRIPTION = """Powerful content search using ripgrep (regex), same role as Claude Code Grep.

- Use this tool for searching file contents; prefer it over shell `grep` or raw `rg` in bash when the agent exposes this tool.
- Full regex (ripgrep syntax, not GNU grep). Literal `{}` in patterns often need escaping (e.g. Go `interface\\{\\}`).
- Filter paths with `glob` (e.g. "*.py", "**/*.ts") or `file_type` (maps to rg `--type`, e.g. py, js, rust).
- output_mode: "content" shows matching lines (with optional context / line numbers); "files_with_matches" lists paths only (default); "count" shows match counts per file.
- Default multiline is false; set multiline=true for patterns spanning lines (rg -U --multiline-dotall).
- For open-ended multi-round exploration, narrow path/glob or paginate with head_limit and offset.
"""

DEFAULT_HEAD_LIMIT = 250

VCS_DIRECTORIES_TO_EXCLUDE = (
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    ".jj",
    ".sl",
)


def _working_directory() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        pwd = os.environ.get("PWD", "")
        if pwd and os.path.isdir(pwd):
            return pwd
        home = os.path.expanduser("~")
        return home if os.path.isdir(home) else "/"


_T = TypeVar("_T")


def apply_head_limit(
    items: list[_T],
    limit: int | None,
    offset: int = 0,
) -> tuple[list[_T], int | None]:
    """Slice ``items`` with optional cap; limit 0 means unlimited."""
    if limit == 0:
        return items[offset:], None
    effective = DEFAULT_HEAD_LIMIT if limit is None else limit
    sliced = items[offset : offset + effective]
    truncated = len(items) - offset > effective
    return sliced, effective if truncated else None


def _expand_glob_patterns(glob: str) -> list[str]:
    patterns: list[str] = []
    for raw in glob.split():
        raw = raw.strip()
        if not raw:
            continue
        if "{" in raw and "}" in raw:
            patterns.append(raw)
        else:
            patterns.extend(p.strip() for p in raw.split(",") if p.strip())
    return patterns


def _rg_executable() -> str | None:
    override = os.environ.get("SKILL_SDK_RG_PATH", "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return str(p.resolve())
        found = shutil.which(override)
        if found:
            return found
    return shutil.which("rg")


def _grep_timeout_sec() -> float:
    raw = os.environ.get("SKILL_SDK_GREP_TIMEOUT_SECONDS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return float(int(raw))
    return 60.0 if _is_wslish() else 20.0


def _is_wslish() -> bool:
    return "WSL" in os.environ.get("WSL_DISTRO_NAME", "")


def _build_rg_args(params: dict[str, Any]) -> list[str]:
    pattern = params["pattern"]
    output_mode = params.get("output_mode") or "files_with_matches"
    glob = params.get("glob")
    file_type = params.get("file_type")
    case_insensitive = bool(params.get("case_insensitive"))
    multiline = bool(params.get("multiline"))
    context_before = params.get("context_before")
    context_after = params.get("context_after")
    context = params.get("context")
    context_union = params.get("context_c")
    line_numbers = params.get("line_numbers")
    if line_numbers is None:
        line_numbers = True

    args: list[str] = ["--hidden", "--max-columns", "500"]

    for d in VCS_DIRECTORIES_TO_EXCLUDE:
        args.extend(["--glob", f"!{d}"])

    if multiline:
        args.extend(["-U", "--multiline-dotall"])

    if case_insensitive:
        args.append("-i")

    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")
    elif output_mode == "content":
        pass
    else:
        raise ValueError(f"Invalid output_mode: {output_mode!r}")

    if output_mode == "content":
        if line_numbers:
            args.append("-n")
        ctx_val = context if context is not None else context_union
        if ctx_val is not None:
            args.extend(["-C", str(int(ctx_val))])
        else:
            if context_before is not None:
                args.extend(["-B", str(int(context_before))])
            if context_after is not None:
                args.extend(["-A", str(int(context_after))])

    if isinstance(pattern, str) and pattern.startswith("-"):
        args.extend(["-e", pattern])
    else:
        args.append(str(pattern))

    if file_type:
        args.extend(["--type", str(file_type)])

    if glob:
        for gp in _expand_glob_patterns(str(glob)):
            args.extend(["--glob", gp])

    return args


def _run_rg_stdout_lines(argv: list[str], target: str, timeout: float) -> tuple[list[str], str | None]:
    exe = _rg_executable()
    if not exe:
        return [], "ripgrep (rg) not found on PATH; install rg or set SKILL_SDK_RG_PATH"

    rg_argv = list(argv)
    if os.environ.get("SKILL_SDK_GREP_SINGLE_THREAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        rg_argv = ["-j", "1", *rg_argv]
    cmd = [exe, *rg_argv, target]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], (
            f"ripgrep timed out after {timeout:.0f}s; narrow path/glob/pattern or raise "
            "SKILL_SDK_GREP_TIMEOUT_SECONDS"
        )
    except OSError as exc:
        return [], f"failed to run ripgrep: {exc}"

    if proc.returncode not in (0, 1):
        err = (proc.stderr or proc.stdout or "").strip()
        return [], err or f"ripgrep exited with code {proc.returncode}"

    lines = proc.stdout.splitlines()
    return [ln.rstrip("\r") for ln in lines], None


_CONTENT_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$")


def _relativize_content_line(line: str, cwd: Path) -> str:
    m = _CONTENT_LINE_RE.match(line)
    if not m:
        return line
    fp, ln_no, rest = m.group(1), m.group(2), m.group(3)
    try:
        rp = os.path.relpath(Path(fp).resolve(), cwd.resolve())
    except ValueError:
        rp = fp
    return f"{rp}:{ln_no}:{rest}"


def _relativize_files_line(line: str, cwd: Path) -> str:
    line = line.rstrip("\r")
    try:
        return os.path.relpath(Path(line).resolve(), cwd.resolve())
    except ValueError:
        return line


def _relativize_count_line(line: str, cwd: Path) -> str:
    line = line.rstrip("\r")
    idx = line.rfind(":")
    if idx <= 0:
        return line
    fp, cnt = line[:idx], line[idx:]
    try:
        rp = os.path.relpath(Path(fp).resolve(), cwd.resolve())
    except ValueError:
        rp = fp
    return rp + cnt


def run_ripgrep_search(
    *,
    pattern: str,
    search_path: str,
    cwd_for_relative: str,
    output_mode: Literal["content", "files_with_matches", "count"] = "files_with_matches",
    glob: str | None = None,
    file_type: str | None = None,
    case_insensitive: bool = False,
    multiline: bool = False,
    context_before: int | None = None,
    context_after: int | None = None,
    context: int | None = None,
    context_c: int | None = None,
    line_numbers: bool | None = True,
    head_limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pattern": pattern,
        "output_mode": output_mode,
        "glob": glob,
        "file_type": file_type,
        "case_insensitive": case_insensitive,
        "multiline": multiline,
        "context_before": context_before,
        "context_after": context_after,
        "context": context,
        "context_c": context_c,
        "line_numbers": line_numbers,
    }
    argv = _build_rg_args(params)
    timeout = _grep_timeout_sec()
    lines, err = _run_rg_stdout_lines(argv, search_path, timeout)
    if err:
        return {"error": err}

    cwd = Path(cwd_for_relative).expanduser().resolve()

    if output_mode == "content":
        limited, applied_limit = apply_head_limit(lines, head_limit, offset)
        final = [_relativize_content_line(ln, cwd) for ln in limited]
        out: dict[str, Any] = {
            "mode": "content",
            "numFiles": 0,
            "filenames": [],
            "content": "\n".join(final),
            "numLines": len(final),
        }
        if applied_limit is not None:
            out["appliedLimit"] = applied_limit
        if offset:
            out["appliedOffset"] = offset
        return out

    if output_mode == "count":
        limited, applied_limit = apply_head_limit(lines, head_limit, offset)
        final_lines = [_relativize_count_line(ln, cwd) for ln in limited]
        total_matches = 0
        file_count = 0
        for ln in final_lines:
            colon = ln.rfind(":")
            if colon <= 0:
                continue
            tail = ln[colon + 1 :]
            try:
                n = int(tail)
            except ValueError:
                continue
            total_matches += n
            file_count += 1
        out = {
            "mode": "count",
            "numFiles": file_count,
            "filenames": [],
            "content": "\n".join(final_lines),
            "numMatches": total_matches,
        }
        if applied_limit is not None:
            out["appliedLimit"] = applied_limit
        if offset:
            out["appliedOffset"] = offset
        return out

    # files_with_matches: sort by mtime descending (then path)
    paths_abs = [ln.strip() for ln in lines if ln.strip()]
    scored: list[tuple[str, float]] = []
    for p in paths_abs:
        try:
            mt = Path(p).stat().st_mtime
        except OSError:
            mt = 0.0
        scored.append((p, mt))
    scored.sort(key=lambda t: (-t[1], t[0]))

    ordered = [p for p, _ in scored]
    limited_paths, applied_limit = apply_head_limit(ordered, head_limit, offset)
    rels = [_relativize_files_line(p, cwd) for p in limited_paths]
    out = {
        "mode": "files_with_matches",
        "filenames": rels,
        "numFiles": len(rels),
    }
    if applied_limit is not None:
        out["appliedLimit"] = applied_limit
    if offset:
        out["appliedOffset"] = offset
    return out


class GrepInput(BaseModel):
    pattern: str = Field(description="Regular expression to search for (ripgrep syntax)")
    path: str | None = Field(
        default=None,
        description='File or directory to search (rg PATH). Defaults to current working directory.',
    )
    glob: str | None = Field(
        default=None,
        description='Glob filter for paths (e.g. "*.py"); maps to multiple rg --glob when comma/space separated.',
    )
    output_mode: Literal["content", "files_with_matches", "count"] | None = Field(
        default="files_with_matches",
        description='Output mode: content | files_with_matches | count (default).',
    )
    context_before: int | None = Field(
        default=None,
        ge=0,
        description='Lines before each match (rg -B); only when output_mode is content.',
    )
    context_after: int | None = Field(
        default=None,
        ge=0,
        description='Lines after each match (rg -A); only when output_mode is content.',
    )
    context_c: int | None = Field(
        default=None,
        ge=0,
        description='Context lines before and after (rg -C); content mode. Overrides context_before/after when set.',
    )
    context: int | None = Field(
        default=None,
        ge=0,
        description='Same as context_c when set (content mode); if both set, prefer this field.',
    )
    line_numbers: bool | None = Field(
        default=True,
        description='Show line numbers (rg -n); content mode only. Defaults true.',
    )
    case_insensitive: bool | None = Field(default=False, description="Case insensitive (rg -i)")
    file_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_type", "type"),
        description='Restrict by rg --type (e.g. py, js, rust); TS tool field name was `type`.',
    )
    head_limit: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Cap output lines/paths/count rows after sorting (default 250 when omitted). "
            "Use 0 for unlimited."
        ),
    )
    offset: int | None = Field(default=0, ge=0, description="Skip first N rows before head_limit")
    multiline: bool | None = Field(default=False, description="rg -U --multiline-dotall")


class GrepPlugin(ToolPlugin):
    """Search file contents via ripgrep."""

    name = GREP_TOOL_NAME
    description = DESCRIPTION.strip()
    args_schema = GrepInput

    def execute(self, **kwargs: Any) -> str:
        inp = GrepInput.model_validate(kwargs)
        pattern = inp.pattern.strip()
        if not pattern:
            return json.dumps({"error": "pattern is required", "error_code": 1}, ensure_ascii=False)

        cwd = _working_directory()
        path_opt = inp.path
        if path_opt is not None:
            path_opt = str(path_opt).strip()
        if path_opt in ("", "undefined", "null"):
            path_opt = None

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
                        f"Path does not exist: {inp.path}. "
                        f"If the path is relative, it resolves against CWD ({cwd})."
                    )
                    return json.dumps({"error": msg, "error_code": 1}, ensure_ascii=False)
                search_root = str(p.resolve())

        om = inp.output_mode or "files_with_matches"
        offset = int(inp.offset or 0)
        head_limit = inp.head_limit
        # Allow env override for default cap
        if head_limit is None:
            env_cap = os.environ.get("SKILL_SDK_GREP_HEAD_LIMIT", "").strip()
            if env_cap.isdigit():
                head_limit = int(env_cap)

        t0 = time.perf_counter()
        try:
            out = run_ripgrep_search(
                pattern=pattern,
                search_path=search_root,
                cwd_for_relative=cwd,
                output_mode=om,
                glob=inp.glob,
                file_type=inp.file_type,
                case_insensitive=bool(inp.case_insensitive),
                multiline=bool(inp.multiline),
                context_before=inp.context_before,
                context_after=inp.context_after,
                context=inp.context,
                context_c=inp.context_c,
                line_numbers=inp.line_numbers,
                head_limit=head_limit,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("grep failed")
            return json.dumps({"error": f"grep failed: {exc}", "error_code": 3}, ensure_ascii=False)

        if "error" in out:
            return json.dumps({"error": out["error"], "error_code": 2}, ensure_ascii=False)

        out["durationMs"] = int((time.perf_counter() - t0) * 1000)
        return json.dumps(out, ensure_ascii=False)
