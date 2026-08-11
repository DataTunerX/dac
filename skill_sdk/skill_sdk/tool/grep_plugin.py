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
- **Prefer omitting `glob` / `file_type` on the first search** unless you already know the repo language.
  Wrong filters (e.g. `**/*.go` on a Python tree) return 0 matches even when the pattern is correct.
  After you know the language from glob/listing, you may narrow with `glob="*.py"` or `file_type="py"`.
- Filter paths with `glob` (e.g. "*.py", "**/*.ts") or `file_type` (maps to rg `--type`, e.g. py, js, rust).
- output_mode: "content" shows matching lines (line numbers; no surrounding context); "files_with_matches" lists paths only (default); "count" shows match counts per file.
- For broad keyword exploration **always** start with output_mode=files_with_matches (or a single source file). Do **not** dump directory-wide content with kitchen-sink patterns like `http|serve|run|port|host`.
  Such directory content searches are auto-downgraded to files_with_matches.
- Prefer specific tokens: compound ids / unique symbol names / protocol strings — not bare short words, short `/paths`, or short `--flags`.
- **Pattern must stay narrow**: ≤6 `|` alternates. Over-broad content alts are auto-dropped by **shape heuristics** (short bare words, short path/CLI stubs, common ops vocab) — not by listing per-language keywords. Outline → `documentSymbol`; surrounding lines → `readline_in_range`.
- content mode: **always leave `context_c` at 0** (match lines only). Do **not** pass `context_c` / `context` / `context_before` / `context_after`. Need surrounding lines → use `readline_in_range` / LSP on the hit, not grep context.
- Default multiline is false; set multiline=true for patterns spanning lines (rg -U --multiline-dotall).
- For open-ended multi-round exploration, narrow path/glob or paginate with head_limit and offset.
"""

DEFAULT_HEAD_LIMIT = 250
# Match lines only; surrounding lines belong to readline/LSP, not grep context.
DEFAULT_CONTEXT_C = 0
MAX_CONTEXT_C = 0
# Soft cap on `|` alternates for content searches (auto-trim beyond this).
MAX_CONTENT_PATTERN_ALTS = 6
# Bare single-word alts at or below this length are treated as too broad
# (language-agnostic: catches def/class/func/var/let/type/… without listing them).
MAX_BARE_WORD_ALT_LEN = 5
# Path segment `/foo` at or below this length is treated as a stub (/api, /v1).
MAX_SHORT_PATH_SEG_LEN = 4
# CLI flag `--foo` / `--a-b`: banned when every hyphen segment is this short.
MAX_SHORT_CLI_SEG_LEN = 4

# Cross-domain ops vocabulary (not language keywords). Alone → usually noise.
_GENERIC_GREP_TOKENS = frozenset(
    {
        "http",
        "https",
        "serve",
        "server",
        "run",
        "port",
        "host",
        "start",
        "stop",
        "get",
        "set",
        "post",
        "put",
        "patch",
        "path",
        "file",
        "name",
        "type",
        "data",
        "id",
        "key",
        "value",
        "url",
        "api",
        "app",
        "main",
        "test",
        "config",
        "log",
        "user",
        "code",
        "time",
        "date",
        "json",
        "text",
        "true",
        "false",
        "null",
        "health",
        "status",
        "error",
        "info",
        "debug",
        "warn",
        "request",
        "response",
        "client",
        "service",
    }
)

# Source-code extensions we may auto-prefer for directory ``content`` searches.
_SOURCE_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".go",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".vue",
        ".svelte",
        ".zig",
        ".lua",
        ".dart",
    }
)

_FILE_TYPE_TO_EXT = {
    "py": "py",
    "python": "py",
    "go": "go",
    "rs": "rs",
    "rust": "rs",
    "js": "js",
    "javascript": "js",
    "ts": "ts",
    "typescript": "ts",
    "tsx": "tsx",
    "jsx": "jsx",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "ruby": "rb",
    "rb": "rb",
    "php": "php",
    "swift": "swift",
    "kotlin": "kt",
    "kt": "kt",
    "csharp": "cs",
    "cs": "cs",
}

_SKIP_WALK_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        ".jj",
        ".sl",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)

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


def _clamp_context_lines(value: int | None) -> int:
    """Clamp rg -C/-A/-B to ``[0, MAX_CONTEXT_C]``."""
    if value is None:
        return DEFAULT_CONTEXT_C
    return max(0, min(int(value), MAX_CONTEXT_C))


def _pattern_alt_parts(pattern: str) -> list[str]:
    """Split ``a|b|c`` into raw alternate pieces (best-effort; no nested-group parse)."""
    return [p.strip() for p in (pattern or "").split("|") if p.strip()]


def _pattern_alt_tokens(pattern: str) -> list[str]:
    """Rough identifier tokens from a ``a|b|c`` regex (best-effort)."""
    tokens: list[str] = []
    for raw in _pattern_alt_parts(pattern):
        cleaned = re.sub(r"\\[bBsSwWdD]", "", raw.strip())
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "", cleaned).lower()
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _alt_substance_words(alt: str) -> list[str]:
    """Identifier-like words left after stripping common regex noise."""
    s = re.sub(r"\\[bBsSwWdDAazZ]", "", alt or "")
    s = re.sub(r"\\s\+?", " ", s)
    s = re.sub(r"\\[.\-+*?\[\](){}|]", "", s)
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s)


def _alt_is_banned(alt: str, *, multi_alt: bool = True) -> str | None:
    """Language-agnostic: drop alts that are too short / shapeless to be useful.

    ``multi_alt``: when False (single-token pattern), bare short words are kept so
    intentional searches like ``MCP`` still work; path/CLI stubs still banned.
    """
    a = (alt or "").strip()
    if not a:
        return "empty"

    # Short / generic path stub: /api, /v1, /health — not /search (unless in generic set).
    m_path = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", a)
    if m_path:
        seg = m_path.group(1).lower()
        if len(seg) <= MAX_SHORT_PATH_SEG_LEN or seg in _GENERIC_GREP_TOKENS:
            return "short/generic path stub"

    # Short CLI flag(s): --host, --port, --api-host (every segment short).
    if a.startswith("--"):
        segs = [s for s in a[2:].split("-") if s]
        if segs and max(len(s) for s in segs) <= MAX_SHORT_CLI_SEG_LEN:
            return "short CLI flag"

    words = _alt_substance_words(a)
    token = "".join(w.lower() for w in words)

    # Distinctive shape → keep (even if a word looks common).
    distinctive = bool(
        "://" in a
        or a.startswith("@")
        or "(" in a
        or re.search(r"[A-Za-z0-9]-[A-Za-z0-9]", a)  # compound like mcp-server
        or (a.startswith("/") and words and len(words[0]) > MAX_SHORT_PATH_SEG_LEN
            and words[0].lower() not in _GENERIC_GREP_TOKENS)
        or (any(c.isupper() for c in a) and any(c.islower() for c in a)
            and len(token) > MAX_BARE_WORD_ALT_LEN)
    )
    if distinctive:
        return None

    # Bare short word — only strip inside multi-alt kitchen sinks.
    if multi_alt and len(words) <= 1 and token and len(token) <= MAX_BARE_WORD_ALT_LEN:
        return "bare short word (add a specific name, or use documentSymbol)"

    if multi_alt and token in _GENERIC_GREP_TOKENS and len(words) <= 1:
        return f"generic ops token {token!r}"

    return None


def _alt_specificity_score(alt: str) -> tuple[int, int, int, int]:
    """Higher is better when picking which alts to keep under the cap."""
    words = _alt_substance_words(alt)
    token_alnum = "".join(w.lower() for w in words)
    is_generic = token_alnum in _GENERIC_GREP_TOKENS or len(token_alnum) <= 3
    # Structural preference — not language-specific keywords.
    protocolish = 0
    if any(c.isupper() for c in alt) and re.search(r"[a-z]", alt) and len(token_alnum) > 4:
        protocolish = 4
    elif "://" in alt or re.search(r"[A-Za-z0-9]-[A-Za-z0-9]", alt) or alt.startswith("@"):
        protocolish = 3
    elif alt.startswith("/") and len(token_alnum) > MAX_SHORT_PATH_SEG_LEN:
        protocolish = 2
    elif alt.startswith("--") and len(token_alnum) > MAX_SHORT_CLI_SEG_LEN:
        protocolish = 1
    return (
        0 if is_generic else 3,
        protocolish,
        len(token_alnum),
        len(alt),
    )


def _narrow_content_pattern(pattern: str) -> tuple[str, list[str]]:
    """Drop over-broad alts and cap `|` count for content searches.

    Heuristics are language-agnostic (length / shape / common ops words),
    not a list of per-language keywords.

    Returns ``(pattern, notes)``. Notes empty when unchanged.
    """
    notes: list[str] = []
    parts = _pattern_alt_parts(pattern)
    if not parts:
        return pattern, notes

    multi = len(parts) >= 2
    kept: list[str] = []
    dropped: list[str] = []
    for alt in parts:
        reason = _alt_is_banned(alt, multi_alt=multi)
        if reason:
            dropped.append(f"{alt!r} ({reason})")
            continue
        kept.append(alt)

    if dropped:
        notes.append(
            "dropped over-broad pattern alts: "
            + "; ".join(dropped[:8])
            + (f" (+{len(dropped) - 8} more)" if len(dropped) > 8 else "")
            + ". Prefer specific symbol/protocol tokens; "
            "use documentSymbol for language outlines."
        )

    trimmed: list[str] = []
    while len(kept) > MAX_CONTENT_PATTERN_ALTS:
        # Equal score → drop later alts first (preserve model’s earlier tokens).
        worst_i = min(
            range(len(kept)),
            key=lambda i: (_alt_specificity_score(kept[i]), -i),
        )
        trimmed.append(kept.pop(worst_i))
    if trimmed:
        notes.append(
            f"capped pattern to {MAX_CONTENT_PATTERN_ALTS} alternates "
            f"(dropped {trimmed!r}); prefer ≤{MAX_CONTENT_PATTERN_ALTS} specific tokens"
        )

    if not kept:
        notes.append(
            "pattern had no usable alts after narrowing; "
            "retry with ≤6 longer/specific tokens "
            "(unique symbol names, compound ids, protocol strings) — "
            "not bare short words, short /paths, or short --flags"
        )
        return "", notes

    new_pat = "|".join(kept)
    if new_pat != pattern.strip():
        notes.append(f"narrowed pattern → {new_pat!r}")
    return new_pat, notes


def _is_broad_content_pattern(pattern: str) -> tuple[bool, str]:
    """True when pattern is too kitchen-sink for a directory ``content`` dump."""
    parts = _pattern_alt_parts(pattern)
    multi = len(parts) >= 2
    if multi:
        banned = [p for p in parts if _alt_is_banned(p, multi_alt=True)]
        if banned:
            return True, f"contains over-broad alts {banned[:6]!r}"
    tokens = _pattern_alt_tokens(pattern)
    if len(tokens) < 2:
        return False, ""
    generic = [t for t in tokens if t in _GENERIC_GREP_TOKENS or len(t) <= 3]
    # e.g. FastAPI|...|http|serve|run|port|host  → many generic alts
    if len(generic) >= 3:
        return (
            True,
            f"pattern has {len(generic)} generic alternates {generic[:8]} "
            f"(of {len(tokens)} parts)",
        )
    if len(tokens) >= 8:
        return True, f"pattern has {len(tokens)} alternates (too wide for content dump)"
    return False, ""


def _should_downgrade_dir_content(
    *,
    pattern: str,
    search_root: str,
    output_mode: str,
) -> tuple[bool, str]:
    """Directory-wide content with a kitchen-sink pattern → files_with_matches."""
    if output_mode != "content":
        return False, ""
    root = Path(search_root)
    if not root.is_dir():
        return False, ""
    broad, why = _is_broad_content_pattern(pattern)
    if not broad:
        return False, ""
    return True, why


def _normalize_one_glob(raw: str) -> str:
    """Turn bare ``py`` / ``.py`` into ``*.py``; leave real globs alone."""
    g = (raw or "").strip()
    if not g:
        return g
    if re.fullmatch(r"\.?[A-Za-z0-9]+", g):
        return f"*.{g.lstrip('.').lower()}"
    return g


def _normalize_glob_value(glob: str | None) -> str | None:
    if glob is None:
        return None
    parts = [_normalize_one_glob(p) for p in _expand_glob_patterns(str(glob))]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return " ".join(parts)


def _exts_from_glob(glob: str | None) -> set[str]:
    """Best-effort extensions referenced by a glob (``.py``, ``.go``, …)."""
    if not glob:
        return set()
    exts: set[str] = set()
    for piece in _expand_glob_patterns(glob):
        brace = re.search(r"\.\{([^}]+)\}", piece)
        if brace:
            for e in brace.group(1).split(","):
                e = e.strip().lstrip(".").lower()
                if e:
                    exts.add(f".{e}")
            continue
        # last .ext in the pattern (*.py / **/*.ts)
        m = re.search(r"\.([A-Za-z0-9]+)(?:$|\})", piece)
        if m:
            exts.add(f".{m.group(1).lower()}")
    return exts


def _detect_repo_source_exts(
    root: Path, *, max_files: int = 800
) -> list[tuple[str, int]]:
    """Count source-file extensions under ``root`` (capped walk)."""
    counts: dict[str, int] = {}
    seen = 0
    if not root.is_dir():
        return []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_WALK_DIRS and not d.startswith(".")]
        for name in filenames:
            seen += 1
            if seen > max_files:
                break
            ext = Path(name).suffix.lower()
            if ext in _SOURCE_EXTS:
                counts[ext] = counts.get(ext, 0) + 1
        if seen > max_files:
            break
    return sorted(counts.items(), key=lambda t: (-t[1], t[0]))


def _suggest_source_glob(ext_counts: list[tuple[str, int]]) -> str | None:
    if not ext_counts:
        return None
    tops = [e.lstrip(".") for e, _n in ext_counts[:4]]
    if len(tops) == 1:
        return f"*.{tops[0]}"
    return "*." + "{" + ",".join(tops) + "}"


def _resolve_grep_filters(
    *,
    glob: str | None,
    file_type: str | None,
    search_root: str,
    output_mode: str,
) -> tuple[str | None, str | None, list[str]]:
    """Normalize glob/file_type and fix filters that miss the repo language.

    Returns ``(glob, file_type, notes)``.
    """
    notes: list[str] = []
    root = Path(search_root)
    glob_n = _normalize_glob_value(glob)
    if glob and glob_n and glob_n != glob.strip():
        notes.append(f"normalized glob {glob!r} → {glob_n!r}")

    ft = (file_type or "").strip().lower() or None
    if ft and ft in _FILE_TYPE_TO_EXT and ft != _FILE_TYPE_TO_EXT[ft]:
        mapped = _FILE_TYPE_TO_EXT[ft]
        notes.append(f"normalized file_type {ft!r} → {mapped!r}")
        ft = mapped
    elif ft and ft not in _FILE_TYPE_TO_EXT and ft.isalpha():
        # keep unknown types for rg --type; no rewrite
        pass

    if not root.is_dir():
        return glob_n, ft, notes

    ext_counts = _detect_repo_source_exts(root)
    present = {e for e, _n in ext_counts}
    suggested = _suggest_source_glob(ext_counts)

    # Wrong language filter: **/*.go on a Python tree, etc.
    requested: set[str] = set(_exts_from_glob(glob_n))
    if ft and ft in _FILE_TYPE_TO_EXT:
        requested.add(f".{_FILE_TYPE_TO_EXT[ft]}")

    if requested and present and requested.isdisjoint(present) and suggested:
        notes.append(
            f"filter {sorted(requested)} matches no source files here "
            f"(repo has {sorted(present)[:6]}); using {suggested!r} instead"
        )
        return suggested, None, notes

    # Directory content with no filter → prefer source extensions (skip md/yaml/lock noise).
    if (
        output_mode == "content"
        and not glob_n
        and not ft
        and suggested
    ):
        notes.append(
            f"auto glob {suggested!r} for directory content "
            "(excludes md/yaml/lock noise; omit only if you need docs)"
        )
        return suggested, None, notes

    return glob_n, ft, notes


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
        # Always print path: when searching a single file rg omits the path
        # unless -H, and our parser / numMatches stats require path:line:text.
        args.append("--with-filename")
        if line_numbers:
            args.append("-n")
        ctx_val = context if context is not None else context_union
        if ctx_val is None and context_before is None and context_after is None:
            ctx_val = DEFAULT_CONTEXT_C
        if ctx_val is not None:
            args.extend(["-C", str(_clamp_context_lines(ctx_val))])
        else:
            if context_before is not None:
                args.extend(["-B", str(_clamp_context_lines(context_before))])
            if context_after is not None:
                args.extend(["-A", str(_clamp_context_lines(context_after))])

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


_CONTENT_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$")  # legacy; prefer _parse_rg_content_line

# ripgrep -n / -C lines use the SAME separator on both sides of the line number:
#   match:   path:line:text
#   context: path-line-text
# Body text often contains ":digits:" (timestamps, host:port). A naive
# path:digits:text match on the whole line invents fake paths like
#   file.md-63-        "timestamp": "2025-11-11T12"
_RG_CONTENT_LINE_RE = re.compile(r"^(.*?)([:\-])(\d+)\2(.*)$")
# Single-file rg without -H: ``9:text`` / ``7-text`` (no path prefix).
_RG_CONTENT_LINE_NO_PATH_RE = re.compile(r"^(\d+)([:\-])(.*)$")


def _parse_rg_content_line(line: str) -> tuple[str, str, str, str] | None:
    """Parse one rg content line.

    Returns ``(kind, path, line_no, text)`` where ``kind`` is ``"match"`` or
    ``"context"``. Returns ``None`` for separators / unparseable lines.
    ``path`` may be ``""`` for pathless single-file output.
    """
    if not line or line == "--":
        return None
    m = _RG_CONTENT_LINE_RE.match(line)
    if m and m.group(1) != "":
        path, sep, ln_no, text = m.group(1), m.group(2), m.group(3), m.group(4)
        kind = "match" if sep == ":" else "context"
        return kind, path, ln_no, text
    m2 = _RG_CONTENT_LINE_NO_PATH_RE.match(line)
    if not m2:
        return None
    ln_no, sep, text = m2.group(1), m2.group(2), m2.group(3)
    kind = "match" if sep == ":" else "context"
    return kind, "", ln_no, text


def _content_match_stats(lines: list[str]) -> tuple[int, list[str]]:
    """Count ripgrep **match** lines only; exclude context and ``--`` separators."""
    files: list[str] = []
    seen: set[str] = set()
    matches = 0
    for ln in lines:
        parsed = _parse_rg_content_line(ln)
        if parsed is None or parsed[0] != "match":
            continue
        matches += 1
        fp = parsed[1]
        if fp and fp not in seen:
            seen.add(fp)
            files.append(fp)
    return matches, files


def _relativize_content_line(line: str, cwd: Path) -> str:
    parsed = _parse_rg_content_line(line)
    if parsed is None:
        return line
    kind, fp, ln_no, rest = parsed
    sep = ":" if kind == "match" else "-"
    if not fp:
        return f"{ln_no}{sep}{rest}"
    try:
        rp = os.path.relpath(Path(fp).resolve(), cwd.resolve())
    except ValueError:
        rp = fp
    return f"{rp}{sep}{ln_no}{sep}{rest}"


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
        num_matches, match_files = _content_match_stats(final)
        content = "\n".join(final)
        # Put summary fields before content so logs/truncation still show counts.
        out: dict[str, Any] = {
            "mode": "content",
            "numMatches": num_matches,
            "numLines": len(final),
            "numFiles": len(match_files),
            "filenames": match_files,
            "resultLen": len(content),
        }
        if applied_limit is not None:
            out["appliedLimit"] = applied_limit
        if offset:
            out["appliedOffset"] = offset
        out["content"] = content
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
        content = "\n".join(final_lines)
        out = {
            "mode": "count",
            "numFiles": file_count,
            "filenames": [],
            "numMatches": total_matches,
            "resultLen": len(content),
            "content": content,
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
    payload = "\n".join(rels)
    out = {
        "mode": "files_with_matches",
        "filenames": rels,
        "numFiles": len(rels),
        "resultLen": len(payload),
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
        description=(
            'Optional path filter (e.g. "*.py"); maps to rg --glob. '
            "Bare values like py/.py are normalized to *.py. "
            "Prefer omitting on files_with_matches explore. "
            "Wrong-language filters (e.g. **/*.go on a Python tree) are rewritten "
            "to the repo's detected source glob when possible. "
            "Directory content searches without a filter auto-use detected source "
            "extensions (*.py / *.{py,ts,…}) to skip md/yaml noise."
        ),
    )
    output_mode: Literal["content", "files_with_matches", "count"] | None = Field(
        default="files_with_matches",
        description='Output mode: content | files_with_matches | count (default).',
    )
    context_before: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Unused: grep context is fixed at 0. "
            "Do not set; use readline_in_range for surrounding lines."
        ),
    )
    context_after: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Unused: grep context is fixed at 0. "
            "Do not set; use readline_in_range for surrounding lines."
        ),
    )
    context_c: int | None = Field(
        default=DEFAULT_CONTEXT_C,
        ge=0,
        description=(
            "Must stay 0 (match lines only). Do not raise this; "
            "surrounding lines → readline_in_range / LSP. "
            "Non-zero values are ignored."
        ),
    )
    context: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Unused alias of context_c. Leave unset; grep context is fixed at 0."
        ),
    )
    line_numbers: bool | None = Field(
        default=True,
        description='Show line numbers (rg -n); content mode only. Defaults true.',
    )
    case_insensitive: bool | None = Field(default=False, description="Case insensitive (rg -i)")
    file_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_type", "type"),
        description=(
            "Optional rg --type filter (e.g. py, js, rust). "
            "Omit on first search unless language is known; TS field name may be `type`."
        ),
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

        pattern_notes: list[str] = []
        downgrade_hint = ""
        # Decide directory kitchen-sink downgrade on the *original* pattern,
        # before shape-based narrowing (which may leave a tight leftover).
        downgrade, why = _should_downgrade_dir_content(
            pattern=pattern, search_root=search_root, output_mode=om
        )
        if downgrade:
            om = "files_with_matches"
            downgrade_hint = (
                "Directory-wide content search refused for a kitchen-sink pattern "
                f"({why}). Auto-downgraded to files_with_matches. "
                "Next: pick 1–3 source files (e.g. **/server.py) and grep content "
                "there with ≤6 specific tokens "
                "(unique symbols / compound ids / protocol strings; "
                "not bare short words, short /paths, or short --flags)."
            )
        elif om == "content":
            pattern, pattern_notes = _narrow_content_pattern(pattern)
            if not pattern:
                return json.dumps(
                    {
                        "error": (
                            "grep content pattern too broad after narrowing "
                            "(bare short words / short path stubs / short CLI flags). "
                            "Retry with ≤6 specific tokens: unique symbol names, "
                            "compound ids, protocol strings — "
                            "use documentSymbol for language outlines."
                        ),
                        "error_code": 1,
                        "hint": "; ".join(pattern_notes),
                    },
                    ensure_ascii=False,
                )

        glob_eff, file_type_eff, filter_notes = _resolve_grep_filters(
            glob=inp.glob,
            file_type=inp.file_type,
            search_root=search_root,
            output_mode=om,
        )

        t0 = time.perf_counter()
        try:
            out = run_ripgrep_search(
                pattern=pattern,
                search_path=search_root,
                cwd_for_relative=cwd,
                output_mode=om,
                glob=glob_eff,
                file_type=file_type_eff,
                case_insensitive=bool(inp.case_insensitive),
                multiline=bool(inp.multiline),
                # Policy: match lines only; ignore model-supplied context*.
                context_before=None,
                context_after=None,
                context=None,
                context_c=DEFAULT_CONTEXT_C,
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
        if pattern_notes:
            out["pattern"] = pattern
            filter_notes = list(filter_notes) + pattern_notes
        if glob_eff != (inp.glob or None) or file_type_eff != (inp.file_type or None):
            out["glob"] = glob_eff
            out["file_type"] = file_type_eff
        if filter_notes:
            out["filter_notes"] = filter_notes
        if downgrade_hint:
            out["downgraded_from"] = "content"
            out["hint"] = downgrade_hint
        elif filter_notes and "hint" not in out:
            # Surface filter rewrites so the model knows why results look different.
            out["hint"] = "; ".join(filter_notes)

        # Empty result with a language/path filter is usually a bad glob, not a bad pattern.
        empty = False
        if om == "content":
            empty = int(out.get("numMatches") or 0) == 0
        elif om == "count":
            empty = int(out.get("numMatches") or 0) == 0
        else:
            empty = int(out.get("numFiles") or 0) == 0
        if empty and (glob_eff or file_type_eff) and "hint" not in out:
            out["hint"] = (
                "0 matches with "
                f"glob={glob_eff!r} file_type={file_type_eff!r}. "
                "The pattern may be fine but the filter excluded this repo "
                "(e.g. **/*.go / file_type=go on a Python tree). "
                "Retry the same pattern without glob/file_type, or use a filter "
                "that matches the repo language (e.g. glob=*.py / file_type=py)."
            )
        elif (
            om == "content"
            and out.get("appliedLimit") is not None
            and Path(search_root).is_dir()
            and "hint" not in out
        ):
            out["hint"] = (
                "content results were truncated (appliedLimit). "
                "For directory search prefer files_with_matches first, then content "
                "on 1–3 source files, or tighten the pattern / add glob=*.py."
            )

        return json.dumps(out, ensure_ascii=False)
