"""Context compaction for long Semantic-Group ReAct runs.

When conversation context approaches or exceeds the model window, this package
summarizes older turns with an LLM, keeps a recent token budget verbatim, and
can compact-and-retry once after a provider context-overflow error.

Enabled by default.  Set ``SG_REACT_COMPACTION_ENABLED=false`` to opt out, or
``SG_REACT_CONTEXT_WINDOW=128000`` to override the default 200K window.
"""

from agent.compaction.guard import AfterInvokeAction, CompactionGuard, OverflowRecovery
from agent.compaction.messages import (
    COMPACTION_SUMMARY_PREFIX,
    COMPACTION_SUMMARY_SUFFIX,
    INTERNAL_MESSAGE_KEY,
    is_compaction_summary_message,
    is_internal_message,
    make_compaction_summary_message,
)
from agent.compaction.overflow import (
    is_context_overflow_message,
    is_overflow_exception,
    is_overflow_error_text,
)
from agent.compaction.prepare import CompactionBoundary, CompactionPreparation, CompactionResult
from agent.compaction.settings import (
    DEFAULT_COMPACTION_SETTINGS,
    DEFAULT_CONTEXT_WINDOW,
    CompactionConfig,
    CompactionSettings,
    context_window_from_env,
    default_compaction_config,
)
from agent.compaction.tokens import (
    calculate_context_tokens,
    estimate_context_tokens,
    estimate_tokens,
    should_compact,
)

__all__ = [
    "AfterInvokeAction",
    "COMPACTION_SUMMARY_PREFIX",
    "COMPACTION_SUMMARY_SUFFIX",
    "INTERNAL_MESSAGE_KEY",
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
    "is_internal_message",
    "is_overflow_error_text",
    "is_overflow_exception",
    "make_compaction_summary_message",
    "should_compact",
]