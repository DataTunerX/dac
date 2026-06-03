"""Cross-file imports for goToDefinition / findReferences exercises.

``core`` and ``utils`` live alongside this file; Pyright resolves them as sibling
modules when analyzing this directory.
"""

from __future__ import annotations

from core import finalize_result
from utils import batch_process, format_output


def bridge_finalize(payload: str) -> str:
    """Compose utils + core (call site should jump to ``finalize_result``)."""
    cleaned = format_output(payload.strip())
    return finalize_result(cleaned)


def bridge_batch(items: list[str]) -> list[str]:
    """Uses :func:`batch_process` then wraps each row through :func:`bridge_finalize`."""
    staged = batch_process(items, batch_size=2)
    return [bridge_finalize(x) for x in staged]
