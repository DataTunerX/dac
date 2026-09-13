"""Wire-size limits shared by producers and consumers."""

from __future__ import annotations

import json
from typing import Any

MAX_INLINE_TASK_CONTEXT_BYTES = 256 * 1024
MAX_INLINE_RESULT_BYTES = 1024 * 1024
MAX_BEST_DRAFT_BYTES = 64 * 1024
MAX_SCHEMA_BYTES = 256 * 1024


def json_size_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
