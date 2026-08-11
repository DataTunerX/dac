"""Compaction configuration and defaults.

Environment variables
---------------------
- ``SKILL_SDK_COMPACTION_ENABLED`` : ``"true"`` (default) or ``"false"``.
- ``SKILL_SDK_CONTEXT_WINDOW`` : model context window size (default 200000).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# Default model context window (200K tokens).
DEFAULT_CONTEXT_WINDOW = 200000


@dataclass(frozen=True)
class CompactionSettings:
    """Tunable knobs for automatic context compaction.

    Attributes:
        enabled: When False, threshold/overflow auto-compaction is skipped.
        reserve_tokens: Headroom reserved for the model response (and summary budget).
        keep_recent_tokens: Approximate recent tokens kept verbatim after a cut.
    """

    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000


DEFAULT_COMPACTION_SETTINGS = CompactionSettings()


# Optional hooks aligned with extension-style interception.
BeforeCompactHook = Callable[..., Awaitable[Optional[dict[str, Any]]]]
AfterCompactHook = Callable[..., Awaitable[None]]


@dataclass
class CompactionConfig:
    """Public config passed into ``SkillRunner(..., compaction=...)``.

    Attributes:
        context_window: Model context window size in tokens (required).
        settings: Compaction thresholds and feature flags.
        summarizer_llm: Optional LLM used only for summarization; defaults to runner llm.
        on_before_compact: Optional async hook; may cancel or supply a custom summary.
        on_compact: Optional async hook fired after a successful compaction.
    """

    context_window: int
    settings: CompactionSettings = field(default_factory=CompactionSettings)
    summarizer_llm: Any | None = None
    on_before_compact: BeforeCompactHook | None = None
    on_compact: AfterCompactHook | None = None

    def __post_init__(self) -> None:
        """Validate that ``context_window`` is a positive integer."""
        if int(self.context_window) <= 0:
            raise ValueError("context_window must be a positive integer")
        self.context_window = int(self.context_window)


def context_window_from_env(default: int | None = None) -> int | None:
    """Read ``SKILL_SDK_CONTEXT_WINDOW`` if set, otherwise return ``default``.

    Args:
        default: Fallback when the env var is missing or invalid.

    Returns:
        Parsed positive int, or ``default`` / ``None``.
    """
    raw = os.environ.get("SKILL_SDK_CONTEXT_WINDOW", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def default_compaction_config() -> CompactionConfig:
    """Build a ``CompactionConfig`` from environment variables.

    - ``SKILL_SDK_COMPACTION_ENABLED`` : ``"true"`` (default) or ``"false"``
      controls ``CompactionSettings.enabled``.
    - ``SKILL_SDK_CONTEXT_WINDOW`` : model context window (default 200000).

    Returns:
        ``CompactionConfig`` with defaults suitable for the runner.
    """
    raw_enabled = os.environ.get("SKILL_SDK_COMPACTION_ENABLED", "true").strip().lower()
    enabled = raw_enabled not in ("false", "0", "no", "off", "disabled")

    window = context_window_from_env(DEFAULT_CONTEXT_WINDOW)
    if window is None:
        window = DEFAULT_CONTEXT_WINDOW

    return CompactionConfig(
        context_window=window,
        settings=CompactionSettings(enabled=enabled),
    )
