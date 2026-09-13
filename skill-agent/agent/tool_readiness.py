"""Single source of truth for environment-gated skill and tool readiness."""

from __future__ import annotations

import os
from typing import Iterable

_ENV_REQUIREMENTS = {
    "tavily-search": ("TAVILY_API_KEY",),
    "tavily_search": ("TAVILY_API_KEY",),
    "tavily_extract": ("TAVILY_API_KEY",),
}


def missing_environment(name: str) -> tuple[str, ...]:
    required = _ENV_REQUIREMENTS.get((name or "").strip().lower(), ())
    return tuple(key for key in required if not os.getenv(key, "").strip())


def partition_ready(names: Iterable[str]) -> tuple[list[str], list[str]]:
    clean = sorted({str(name).strip() for name in names if str(name).strip()})
    unavailable = [name for name in clean if missing_environment(name)]
    unavailable_set = set(unavailable)
    return [name for name in clean if name not in unavailable_set], unavailable
