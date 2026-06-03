"""Async utilities in a nested module (documentSymbol / nested path tests)."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core import finalize_result


async def buffered_lines(lines: list[str]) -> AsyncIterator[str]:
    """Yield each line with a trivial await to keep an async code path."""
    for item in lines:
        yield item
        await asyncio.sleep(0)


async def merge_batches(chunks: list[list[str]]) -> list[str]:
    """Flatten chunked string lists."""
    out: list[str] = []
    for chunk in chunks:
        out.extend(chunk)
    return out


def finalize_chunked(entries: list[str]) -> list[str]:
    """Map :func:`~core.finalize_result` across entries (nested package → core)."""
    return [finalize_result(entry) for entry in entries]
