"""ReadlineInRange ToolPlugin — read a range of lines from a file with line numbers."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)

TOOL_NAME = "readline_in_range"

DESCRIPTION = """Read a range of lines from a file.

Use this tool to read specific line ranges from a file. The output includes
line numbers (like `cat -n`), making it easy to reference exact locations.

- `file_path` must be an absolute or relative path to the file.
- `start` is the 1-based starting line number (default 1).
- `end` is the inclusive ending line number (default: read to end of file).
- If `start` is beyond the file length, returns empty content.
- Supports UTF-8 and latin-1 encoded files.
"""


class ReadlineInRangeInput(BaseModel):
    file_path: str = Field(description="Path to the file to read (absolute or relative).")
    start: int = Field(
        default=1,
        ge=1,
        description="Starting line number (1-based, default 1).",
    )
    end: Optional[int] = Field(
        default=None,
        description="Ending line number (inclusive, default None = read to end).",
    )
    include_line_numbers: bool = Field(
        default=True,
        description="Whether to prefix each line with its line number (default True).",
    )


def readline_in_range(
    file_path: str,
    start: int = 1,
    end: Optional[int] = None,
    include_line_numbers: bool = True,
) -> tuple[str, int, int]:
    """Read a range of lines from a file.

    Args:
        file_path: Absolute or relative path to the file.
        start: Starting line number (1-based, default 1).
        end: Ending line number (inclusive, default None = read to end of file).
        include_line_numbers: Whether to prefix each line with its line number (default True).

    Returns:
        Tuple[str, int, int]: (file content with line numbers, actual start line, actual end line).
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

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="latin-1") as f:
            all_lines = f.readlines()

    total_lines = len(all_lines)

    if total_lines == 0:
        return "", 0, 0

    if start > total_lines:
        return "", 0, 0

    actual_start = start
    actual_end = min(end, total_lines) if end else total_lines

    selected_lines = all_lines[actual_start - 1 : actual_end]

    if include_line_numbers:
        max_width = len(str(actual_end))
        result_lines = []
        for i, line in enumerate(selected_lines):
            line_num = actual_start + i
            content = line.rstrip("\n\r")
            result_lines.append(f"{line_num:>{max_width}}| {content}")
        content = "\n".join(result_lines)
    else:
        content = "".join(selected_lines)

    return content, actual_start, actual_end


class ReadlineInRangePlugin(ToolPlugin):
    """Read a range of lines from a file."""

    name = TOOL_NAME
    description = DESCRIPTION.strip()
    args_schema = ReadlineInRangeInput

    def execute(self, **kwargs: Any) -> str:
        from pydantic import ValidationError

        try:
            inp = ReadlineInRangeInput.model_validate(kwargs)
        except ValidationError as exc:
            return json.dumps(
                {"error": f"Invalid input: {exc}", "error_code": 400},
                ensure_ascii=False,
            )

        try:
            content, actual_start, actual_end = readline_in_range(
                file_path=inp.file_path,
                start=inp.start,
                end=inp.end,
                include_line_numbers=inp.include_line_numbers,
            )
        except FileNotFoundError as exc:
            return json.dumps(
                {"error": str(exc), "error_code": 404}, ensure_ascii=False
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

        return json.dumps(
            {
                "content": content,
                "start": actual_start,
                "end": actual_end,
                "total_lines": (
                    actual_end - actual_start + 1 if actual_end > 0 else 0
                ),
            },
            ensure_ascii=False,
        )
