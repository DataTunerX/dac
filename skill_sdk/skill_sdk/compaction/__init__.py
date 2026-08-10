"""Context compaction for long skill ReAct runs.

When conversation context approaches or exceeds the model window, this package
summarizes older turns with an LLM, keeps a recent token budget verbatim, and
can compact-and-retry once after a provider context-overflow error.

Enabled by default when ``SkillRunner`` is instantiated with no explicit
``compaction`` parameter.  Set ``SKILL_SDK_COMPACTION_ENABLED=false`` to
opt out, or ``SKILL_SDK_CONTEXT_WINDOW=128000`` to override the default
200K window.
"""

from skill_sdk.compaction.guard import AfterInvokeAction, CompactionGuard, OverflowRecovery
from skill_sdk.compaction.messages import (
    COMPACTION_SUMMARY_PREFIX,
    COMPACTION_SUMMARY_SUFFIX,
    is_compaction_summary_message,
    make_compaction_summary_message,
)
from skill_sdk.compaction.overflow import (
    is_context_overflow_message,
    is_overflow_exception,
    is_overflow_error_text,
)
from skill_sdk.compaction.prepare import CompactionBoundary, CompactionPreparation, CompactionResult
from skill_sdk.compaction.settings import (
    DEFAULT_COMPACTION_SETTINGS,
    DEFAULT_CONTEXT_WINDOW,
    CompactionConfig,
    CompactionSettings,
    context_window_from_env,
    default_compaction_config,
)
from skill_sdk.compaction.tokens import (
    calculate_context_tokens,
    estimate_context_tokens,
    estimate_tokens,
    should_compact,
)

__all__ = [
    "AfterInvokeAction",
    "COMPACTION_SUMMARY_PREFIX",
    "COMPACTION_SUMMARY_SUFFIX",
    "CompactionBoundary",
    "CompactionConfig",
    "CompactionGuard",
    "CompactionPreparation",
    "CompactionResult",
    "CompactionSettings",
    "DEFAULT_COMPACTION_SETTINGS",
    "DEFAULT_CONTEXT_WINDOW",
    "OverflowRecovery",
    "calculate_context_tokens",
    "context_window_from_env",
    "default_compaction_config",
    "estimate_context_tokens",
    "estimate_tokens",
    "is_compaction_summary_message",
    "is_context_overflow_message",
    "is_overflow_error_text",
    "is_overflow_exception",
    "make_compaction_summary_message",
    "should_compact",
]
