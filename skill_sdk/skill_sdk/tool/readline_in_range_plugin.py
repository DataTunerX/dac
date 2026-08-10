"""ReadlineInRange ToolPlugin — read a range of lines from a file with line numbers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)

TOOL_NAME = "readline_in_range"

DEFAULT_MAX_READ_LINES = 1000
DEFAULT_MAX_READ_CHARS = 64_000

# Source files: block exploratory whole-file / unfocused large dumps.
# Docs/config (md/toml/yaml/...) are exempt.
_SOURCE_EXTENSIONS = frozenset(
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
        ".java",
        ".rs",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".hxx",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".vue",
        ".svelte",
        ".m",
        ".mm",
        ".zig",
        ".lua",
        ".dart",
        ".r",
    }
)

# Near-whole-file gate (source only): span ≥ ratio * file_lines when file is large.
NEAR_WHOLE_FILE_MIN_LINES = 120
NEAR_WHOLE_FILE_RATIO = 0.8
# Unfocused exploratory dump from line 1 (source only).
UNFOCUSED_FROM_START_MAX_LINES = 150


def get_max_read_lines() -> int:
    raw = os.environ.get("SKILL_SDK_READLINE_MAX_LINES", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_MAX_READ_LINES


def get_max_read_chars() -> int:
    raw = os.environ.get("SKILL_SDK_READLINE_MAX_CHARS", "").strip()
    if raw.isdigit():
        return max(1024, int(raw))
    return DEFAULT_MAX_READ_CHARS


DESCRIPTION = """Read a range of lines from a file.

Use this tool to read specific line ranges from a file. The output includes
line numbers (like `cat -n`), making it easy to reference exact locations.

- `file_path` must be an absolute or relative path to the file.
- `start` is the 1-based starting line number (default 1).
- `end` is the inclusive ending line number. If omitted, reads one window from
  `start` (default max 1000 lines; see max_lines / next_start in the result).
- Requested windows larger than max_lines are rejected — then split into multiple
  calls with each window close to max_lines.
- CRITICAL: If documentSymbol already gave a **symbol** Lines X-Y and
  (Y - X + 1) ≤ max_lines, call once with start=X and end=Y. Do NOT preview the
  head (e.g. only first ~100–200 lines) and then page; that wastes steps.
  Example: method Lines 4676-5124 (449 lines) → one call end=5124.
  Do NOT treat “read the whole source file (1..EOF)” as that rule — for source
  files, near-whole-file and unfocused large windows from line 1 are rejected;
  prefer grep / documentSymbol(symbol_name=...) then read that symbol span.
- If `start` is beyond the file length, returns empty content.
- Supports UTF-8 and latin-1 encoded files.
"""


def is_source_path(file_path: str) -> bool:
    ext = Path(file_path or "").suffix.lower()
    return bool(ext) and ext in _SOURCE_EXTENSIONS


def count_file_lines(file_path: str) -> int:
    """Count lines without loading the whole file into memory."""
    n = 0
    try:
        with open(file_path, "rb") as f:
            for _ in f:
                n += 1
    except OSError:
        return 0
    return n


class SourceReadPolicyError(ValueError):
    """Source readline refused (near-whole-file or unfocused large window)."""


def check_source_readline_policy(
    file_path: str,
    start: int,
    end: Optional[int],
    *,
    focused: bool = False,
    max_lines: Optional[int] = None,
    file_lines: Optional[int] = None,
) -> None:
    """Reject exploratory whole-file / unfocused large source reads.

    - Near-whole-file: ``file_lines > 120`` and span ≥ 80% of the file
      (even with focus — prefer method/function spans, not the whole module).
    - Unfocused from start: ``start==1``, span > 150, and no prior focused
      ``documentSymbol`` (``focused=False``).

    Non-source paths (md/toml/yaml/json/...) are exempt. Files ≤ 120 lines may
    be read in full.
    """
    if not is_source_path(file_path):
        return
    if start < 1:
        return

    total = file_lines if file_lines is not None else count_file_lines(file_path)
    if total <= 0:
        return

    limit = max_lines if max_lines is not None else get_max_read_lines()
    if end is None:
        effective_end = min(start + limit - 1, total)
    else:
        effective_end = min(int(end), total)
    if effective_end < start:
        return
    span = effective_end - start + 1

    if total > NEAR_WHOLE_FILE_MIN_LINES:
        threshold = max(1, int(total * NEAR_WHOLE_FILE_RATIO))
        if span >= threshold:
            raise SourceReadPolicyError(
                "Refusing near-whole-file source read: "
                f"requested {span} lines (start={start} end={effective_end}) "
                f"covers ≥{int(NEAR_WHOLE_FILE_RATIO * 100)}% of "
                f"{total}-line file (threshold {threshold}). "
                "Do not dump the whole module. Prefer grep for keywords "
                "(routes/MCP/HTTP/handlers), then "
                "lsp documentSymbol(symbol_name=...) and readline only that "
                "symbol's Lines X-Y (usually a function/method, not the file)."
            )

    if (
        not focused
        and start == 1
        and span > UNFOCUSED_FROM_START_MAX_LINES
        and total > UNFOCUSED_FROM_START_MAX_LINES
    ):
        raise SourceReadPolicyError(
            "Refusing unfocused large source read from line 1: "
            f"requested {span} lines (end≈{effective_end}), "
            f"max without focus is {UNFOCUSED_FROM_START_MAX_LINES}. "
            "First call lsp documentSymbol with symbol_name and/or line for "
            "this file, then readline that symbol's Lines X-Y; or grep to "
            "locate the symbol first."
        )


class ReadlineInRangeInput(BaseModel):
    file_path: str = Field(description="Path to the file to read (absolute or relative).")
    start: int = Field(
        default=1,
        ge=1,
        description="Starting line number (1-based, default 1).",
    )
    end: Optional[int] = Field(
        default=None,
        description=(
            "Ending line number (inclusive). Prefer the full known symbol end when "
            f"(end - start + 1) ≤ max_lines (default {DEFAULT_MAX_READ_LINES}). "
            "If omitted, reads one window from start. "
            "Windows larger than max_lines are rejected."
        ),
    )
    include_line_numbers: bool = Field(
        default=True,
        description="Whether to prefix each line with its line number (default True).",
    )


@dataclass
class ReadWindowResult:
    content: str
    start: int
    end: int
    window_lines: int
    truncated: bool
    truncated_to_window: bool
    next_start: Optional[int]
    max_lines: int
    max_chars: int


class WindowTooLargeError(ValueError):
    """Requested line window exceeds the configured max_lines cap."""


def readline_in_range(
    file_path: str,
    start: int = 1,
    end: Optional[int] = None,
    include_line_numbers: bool = True,
    *,
    max_lines: Optional[int] = None,
    max_chars: Optional[int] = None,
    focused: bool = False,
    skip_source_policy: bool = False,
) -> ReadWindowResult:
    """Stream-read a line window from a file (no full-file ``readlines``).

    When ``end`` is omitted, reads at most ``max_lines`` from ``start``.
    Explicit windows with ``end - start + 1 > max_lines`` raise ``WindowTooLargeError``.

    ``focused=True`` relaxes the unfocused-from-start gate (caller already did a
    focused documentSymbol). Near-whole-file rejects still apply.
    ``skip_source_policy=True`` disables both gates (tests / special callers).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    if not os.path.isfile(file_path):
        raise ValueError(f"Path is not a file: {file_path}")

    if start < 1:
        raise ValueError(f"start line must be >= 1, got: {start}")

    if end is not None and end < start:
        raise ValueError(
            f"end line must be >= start line, got: start={start}, end={end}"
        )

    limit_lines = max_lines if max_lines is not None else get_max_read_lines()
    limit_chars = max_chars if max_chars is not None else get_max_read_chars()
    auto_window = end is None

    if not skip_source_policy:
        check_source_readline_policy(
            file_path,
            start,
            end,
            focused=focused,
            max_lines=limit_lines,
        )

    if end is not None:
        requested = end - start + 1
        if requested > limit_lines:
            suggested_end = start + limit_lines - 1
            raise WindowTooLargeError(
                f"Read window too large: requested {requested} lines "
                f"(start={start} end={end}), max_lines={limit_lines}. "
                f"Retry with end={suggested_end}, then start={suggested_end + 1}, etc. "
                f"If documentSymbol Lines span more than {limit_lines} lines, "
                f"split into multiple readline_in_range calls."
            )
        effective_end = end
    else:
        effective_end = start + limit_lines - 1

    selected: list[str] = []
    actual_start = 0
    actual_end = 0
    truncated = False
    has_more = False
    line_no = 0
    total_chars = 0

    def _consume(encoding: str) -> None:
        nonlocal selected, actual_start, actual_end, truncated, has_more, line_no, total_chars
        selected = []
        actual_start = 0
        actual_end = 0
        truncated = False
        has_more = False
        line_no = 0
        total_chars = 0
        with open(file_path, "r", encoding=encoding) as f:
            for raw_line in f:
                line_no += 1
                if line_no < start:
                    continue
                if line_no > effective_end:
                    has_more = True
                    break

                if actual_start == 0:
                    actual_start = line_no

                line_body = raw_line.rstrip("\n\r")
                # Rough size check before formatting (line numbers add a few chars).
                projected = total_chars + len(line_body) + 8
                if selected and projected > limit_chars:
                    truncated = True
                    has_more = True
                    break

                selected.append(raw_line if not include_line_numbers else line_body)
                actual_end = line_no
                total_chars = projected

                if len(selected) >= limit_lines:
                    try:
                        next(f)
                    except StopIteration:
                        has_more = False
                    else:
                        has_more = True
                    break

    try:
        _consume("utf-8")
    except UnicodeDecodeError:
        _consume("latin-1")

    if not selected:
        return ReadWindowResult(
            content="",
            start=0,
            end=0,
            window_lines=0,
            truncated=False,
            truncated_to_window=False,
            next_start=None,
            max_lines=limit_lines,
            max_chars=limit_chars,
        )

    if include_line_numbers:
        max_width = len(str(actual_end))
        result_lines = [
            f"{actual_start + i:>{max_width}}| {line}"
            for i, line in enumerate(selected)
        ]
        content = "\n".join(result_lines)
    else:
        content = "".join(selected)

    if len(content) > limit_chars:
        # Absolute char cap (e.g. pathological single line).
        content = content[:limit_chars]
        truncated = True
        has_more = True

    truncated_to_window = bool(auto_window and has_more and not truncated)
    next_start = actual_end + 1 if has_more else None

    return ReadWindowResult(
        content=content,
        start=actual_start,
        end=actual_end,
        window_lines=actual_end - actual_start + 1,
        truncated=truncated,
        truncated_to_window=truncated_to_window,
        next_start=next_start,
        max_lines=limit_lines,
        max_chars=limit_chars,
    )


class ReadlineInRangePlugin(ToolPlugin):
    """Read a range of lines from a file."""

    name = TOOL_NAME
    description = DESCRIPTION.strip()
    args_schema = ReadlineInRangeInput

    def execute(self, **kwargs: Any) -> str:
        from pydantic import ValidationError

        # Internal: runner may inject focused=True after focused documentSymbol.
        # Not part of the public schema so models cannot freely bypass the gate.
        focused = bool(kwargs.pop("focused", False))

        try:
            inp = ReadlineInRangeInput.model_validate(kwargs)
        except ValidationError as exc:
            return json.dumps(
                {"error": f"Invalid input: {exc}", "error_code": 400},
                ensure_ascii=False,
            )

        try:
            result = readline_in_range(
                file_path=inp.file_path,
                start=inp.start,
                end=inp.end,
                include_line_numbers=inp.include_line_numbers,
                focused=focused,
            )
        except FileNotFoundError as exc:
            return json.dumps(
                {"error": str(exc), "error_code": 404}, ensure_ascii=False
            )
        except WindowTooLargeError as exc:
            return json.dumps(
                {"error": str(exc), "error_code": 400}, ensure_ascii=False
            )
        except SourceReadPolicyError as exc:
            return json.dumps(
                {
                    "error": str(exc),
                    "error_code": 400,
                    "blocked_by_policy": True,
                },
                ensure_ascii=False,
            )
        except ValueError as exc:
            return json.dumps(
                {"error": str(exc), "error_code": 400}, ensure_ascii=False
            )
        except Exception as exc:
            logger.exception("readline_in_range failed")
            return json.dumps(
                {"error": f"read failed: {exc}", "error_code": 500},
                ensure_ascii=False,
            )

        payload: dict[str, Any] = {
            "content": result.content,
            "start": result.start,
            "end": result.end,
            "total_lines": result.window_lines,
            "window_lines": result.window_lines,
            "truncated": result.truncated,
            "truncated_to_window": result.truncated_to_window,
            "next_start": result.next_start,
            "max_lines": result.max_lines,
            "max_chars": result.max_chars,
        }
        # Nudge models that over-split known spans into tiny preview windows.
        if (
            inp.end is not None
            and not result.truncated_to_window
            and result.window_lines * 2 < result.max_lines
        ):
            payload["hint"] = (
                f"window_lines={result.window_lines} is well below "
                f"max_lines={result.max_lines}. If documentSymbol already gave "
                "a symbol Lines X-Y with (Y-X+1)≤max_lines, read start=X end=Y "
                "in one call instead of previewing the head and paging. "
                "Do not use that to justify reading 1..EOF of a large source file."
            )
        return json.dumps(payload, ensure_ascii=False)
