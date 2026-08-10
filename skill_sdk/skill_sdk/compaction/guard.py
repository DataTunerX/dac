"""Runtime guard that wraps LLM invokes with threshold and overflow compaction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from langchain_core.messages import BaseMessage

from skill_sdk.compaction.overflow import (
    is_context_overflow_message,
    is_overflow_exception,
    is_silent_overflow_success,
)
from skill_sdk.compaction.prepare import (
    CompactionBoundary,
    CompactionResult,
    boundary_from_result,
    compact,
    prepare_compaction,
)
from skill_sdk.compaction.settings import CompactionConfig
from skill_sdk.compaction.tokens import (
    calculate_context_tokens,
    estimate_context_tokens,
    should_compact,
    usage_from_ai_message,
)

logger = logging.getLogger("compaction")


def _pct_reduction(before: int, after: int) -> int:
    """Compute a safe percentage reduction, clamped to 0-100."""
    if before <= 0:
        return 0
    return max(0, min(100, round((before - after) / before * 100)))


@dataclass
class OverflowRecovery:
    """Result of handling an overflow during LLM invoke.

    Attributes:
        messages: Rebuilt messages after compaction (when recovery succeeded).
        will_retry: Whether the caller should re-invoke the LLM on the same step.
        failed: True when recovery already attempted once and must stop.
        result: Compaction result metadata when compaction ran.
        error_message: Human-readable failure detail when ``failed``.
    """

    messages: list[BaseMessage] | None = None
    will_retry: bool = False
    failed: bool = False
    result: CompactionResult | None = None
    error_message: str = ""


@dataclass
class AfterInvokeAction:
    """Optional post-invoke compaction for silent overflow.

    Attributes:
        compacted: Whether messages were rewritten.
        messages: New message list when compacted.
        will_retry: Always False for silent success (answer already completed).
        result: Compaction metadata.
    """

    compacted: bool = False
    messages: list[BaseMessage] | None = None
    will_retry: bool = False
    result: CompactionResult | None = None


class CompactionGuard:
    """Stateful helper that enforces context compaction around LLM calls.

    One guard instance should be created per ``SkillRunner.run()`` invocation so
    overflow-recovery and previous-summary state stay scoped to that run.
    """

    def __init__(self, config: CompactionConfig, llm: Any) -> None:
        """Create a guard bound to config and a summarizer LLM.

        Args:
            config: Compaction configuration (window + settings + hooks).
            llm: LLM used for summarization (typically unbound / without tools).
        """
        self.config = config
        self.llm = config.summarizer_llm if config.summarizer_llm is not None else llm
        self.overflow_recovery_attempted = False
        self.boundaries: list[CompactionBoundary] = []
        self.last_usage_tokens: int | None = None
        self.events: list[dict[str, Any]] = []
        self._compact_count = 0

    def _previous_boundary(self) -> CompactionBoundary | None:
        """Return the most recent compaction boundary, if any.

        Returns:
            Last ``CompactionBoundary`` or ``None``.
        """
        return self.boundaries[-1] if self.boundaries else None

    def _context_tokens(self, messages: Sequence[BaseMessage]) -> int:
        """Estimate current context tokens for threshold checks.

        Prefers the last recorded usage when available; otherwise estimates
        from the full message list.

        Args:
            messages: Current LLM context.

        Returns:
            Token count used for ``should_compact``.
        """
        estimate = estimate_context_tokens(list(messages))
        if estimate.last_usage_index is not None:
            return estimate.tokens
        if self.last_usage_tokens is not None:
            # No per-message usage: use last known usage plus trailing estimate.
            return max(self.last_usage_tokens, estimate.tokens)
        return estimate.tokens

    async def _run_compact(
        self,
        messages: Sequence[BaseMessage],
        *,
        reason: str,
        will_retry: bool,
        custom_instructions: str | None = None,
    ) -> CompactionResult | None:
        """Prepare and execute compaction, honoring optional hooks.

        Args:
            messages: Current context to compact.
            reason: ``threshold`` / ``overflow`` / ``manual``.
            will_retry: Whether the aborted turn will be retried after.
            custom_instructions: Optional summary focus.

        Returns:
            ``CompactionResult`` or ``None`` if cancelled / nothing to summarize.
        """
        settings = self.config.settings
        if not settings.enabled and reason != "manual":
            return None

        self._compact_count += 1
        logger.info(
            "compaction #%d REASON=%s will_retry=%s total_msgs=%d",
            self._compact_count,
            reason,
            will_retry,
            len(messages),
        )

        preparation = prepare_compaction(messages, settings, self._previous_boundary())
        if preparation is None:
            logger.warning(
                "compaction #%d SKIPPED reason=%s — nothing to summarize (dialog too short or already compacted)",
                self._compact_count,
                reason,
            )
            return None

        logger.info(
            "compaction #%d CUT msgs_to_summarize=%d turn_prefix=%d kept=%d split_turn=%s tokens_before=%d previous_summary=%s",
            self._compact_count,
            len(preparation.messages_to_summarize),
            len(preparation.turn_prefix_messages),
            len(preparation.kept_messages),
            preparation.is_split_turn,
            preparation.tokens_before,
            bool(preparation.previous_summary),
        )

        if self.config.on_before_compact is not None:
            hook_result = await self.config.on_before_compact(
                preparation=preparation,
                reason=reason,
                will_retry=will_retry,
            )
            if isinstance(hook_result, dict):
                if hook_result.get("cancel"):
                    logger.info("compaction #%d CANCELLED by on_before_compact hook", self._compact_count)
                    return None
                custom = hook_result.get("compaction")
                if isinstance(custom, dict) and custom.get("summary"):
                    from skill_sdk.compaction.prepare import rebuild_messages
                    from skill_sdk.compaction.tokens import estimate_messages_tokens

                    summary = str(custom["summary"])
                    details = custom.get("details") or preparation.previous_details or {}
                    new_messages = rebuild_messages(
                        preparation.system_messages,
                        summary,
                        preparation.kept_messages,
                    )
                    result = CompactionResult(
                        summary=summary,
                        messages=new_messages,
                        tokens_before=int(custom.get("tokens_before") or preparation.tokens_before),
                        estimated_tokens_after=estimate_messages_tokens(new_messages),
                        details=details if isinstance(details, dict) else {},
                        reason=reason,
                        from_hook=True,
                    )
                    self.boundaries.append(boundary_from_result(result, preparation))
                    self.events.append({"type": "compact", "reason": reason, "from_hook": True})
                    if self.config.on_compact is not None:
                        await self.config.on_compact(result=result, reason=reason, will_retry=will_retry)
                    logger.info(
                        "compaction #%d DONE from_hook=True tokens_before=%d tokens_after=%d summary_len=%d",
                        self._compact_count,
                        result.tokens_before,
                        result.estimated_tokens_after,
                        len(result.summary),
                    )
                    return result

        result = await compact(
            preparation,
            self.llm,
            reason=reason,
            custom_instructions=custom_instructions,
        )
        self.boundaries.append(boundary_from_result(result, preparation))
        self.events.append(
            {
                "type": "compact",
                "reason": reason,
                "tokens_before": result.tokens_before,
                "tokens_after": result.estimated_tokens_after,
            }
        )
        logger.info(
            "compaction #%d DONE reason=%s tokens_before=%d tokens_after=%d reduction=%d%% summary_len=%d readFiles=%d modifiedFiles=%d",
            self._compact_count,
            reason,
            result.tokens_before,
            result.estimated_tokens_after,
            _pct_reduction(result.tokens_before, result.estimated_tokens_after),
            len(result.summary),
            len(result.details.get("readFiles") or []),
            len(result.details.get("modifiedFiles") or []),
        )
        if self.config.on_compact is not None:
            await self.config.on_compact(result=result, reason=reason, will_retry=will_retry)
        return result

    async def before_invoke(self, messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        """Run threshold compaction before sending messages to the LLM.

        Args:
            messages: Current context.

        Returns:
            Possibly compacted message list (or the original list unchanged).
        """
        settings = self.config.settings
        if not settings.enabled:
            return list(messages)

        context_tokens = self._context_tokens(messages)
        if not should_compact(context_tokens, self.config.context_window, settings):
            return list(messages)

        logger.info(
            "compaction TRIGGER threshold tokens=%d window=%d reserve=%d threshold=%d msgs=%d",
            context_tokens,
            self.config.context_window,
            settings.reserve_tokens,
            self.config.context_window - settings.reserve_tokens,
            len(messages),
        )
        result = await self._run_compact(messages, reason="threshold", will_retry=False)
        if result is None:
            return list(messages)
        return list(result.messages)

    def note_usage(self, ai_message: BaseMessage) -> None:
        """Record usage from a successful assistant message.

        Args:
            ai_message: Assistant response from the main LLM call.
        """
        usage = usage_from_ai_message(ai_message)
        if usage is not None:
            self.last_usage_tokens = calculate_context_tokens(usage)

    async def after_invoke(
        self,
        messages: Sequence[BaseMessage],
        ai_message: BaseMessage,
    ) -> AfterInvokeAction:
        """Handle post-invoke silent overflow; update usage tracking.

        Args:
            messages: Context that was sent (before appending ``ai_message``).
            ai_message: Assistant response.

        Returns:
            ``AfterInvokeAction`` describing whether silent compaction ran.
        """
        self.note_usage(ai_message)
        settings = self.config.settings
        if not settings.enabled:
            return AfterInvokeAction()

        if not is_context_overflow_message(ai_message, self.config.context_window):
            return AfterInvokeAction()

        # Silent / completed overflow: compact but do not retry the turn.
        if is_silent_overflow_success(ai_message, self.config.context_window):
            logger.info(
                "compaction TRIGGER silent_overflow input_tokens=%d window=%d msgs=%d",
                self.last_usage_tokens,
                self.config.context_window,
                len(messages) + 1,
            )
            # Include the completed assistant message in the history being compacted.
            full = list(messages) + [ai_message]
            result = await self._run_compact(full, reason="overflow", will_retry=False)
            if result is None:
                return AfterInvokeAction()
            return AfterInvokeAction(
                compacted=True,
                messages=list(result.messages),
                will_retry=False,
                result=result,
            )

        return AfterInvokeAction()

    async def on_invoke_error(
        self,
        messages: Sequence[BaseMessage],
        exc: BaseException,
    ) -> OverflowRecovery | None:
        """Attempt overflow recovery when an LLM invoke raises.

        Args:
            messages: Context that was sent.
            exc: Raised exception.

        Returns:
            ``OverflowRecovery`` when the error is context overflow;
            ``None`` when the caller should re-raise the original exception.
        """
        settings = self.config.settings
        if not settings.enabled:
            return None
        if not is_overflow_exception(exc):
            return None

        if self.overflow_recovery_attempted:
            msg = (
                "Context overflow recovery failed after one compact-and-retry attempt. "
                "Try reducing context or switching to a larger-context model."
            )
            logger.error(
                "compaction TRIGGER overflow RETRY FAILED — %s window=%d msgs=%d",
                msg,
                self.config.context_window,
                len(messages),
            )
            self.events.append({"type": "overflow_failed", "error": msg})
            return OverflowRecovery(failed=True, error_message=msg)

        self.overflow_recovery_attempted = True
        error_snippet = str(exc)[:200]
        logger.warning(
            "compaction TRIGGER overflow error=%r window=%d msgs=%d — compacting and retrying once",
            error_snippet,
            self.config.context_window,
            len(messages),
        )
        result = await self._run_compact(messages, reason="overflow", will_retry=True)
        if result is None:
            msg = "Context overflow recovery failed: nothing to compact."
            logger.error("compaction TRIGGER overflow FAILED — %s", msg)
            return OverflowRecovery(failed=True, error_message=msg)

        return OverflowRecovery(
            messages=list(result.messages),
            will_retry=True,
            failed=False,
            result=result,
        )

    async def compact_manual(
        self,
        messages: Sequence[BaseMessage],
        custom_instructions: str | None = None,
    ) -> CompactionResult | None:
        """Run a manual compaction pass (ignores ``settings.enabled``).

        Args:
            messages: Current context.
            custom_instructions: Optional summary focus.

        Returns:
            Compaction result or ``None`` if there is nothing to summarize.
        """
        return await self._run_compact(
            messages,
            reason="manual",
            will_retry=False,
            custom_instructions=custom_instructions,
        )

    def new_run_guard(self) -> CompactionGuard:
        """Spawn a fresh guard sharing config/llm but resetting per-run state.

        Returns:
            New ``CompactionGuard`` instance for one ``run()`` call.
        """
        return CompactionGuard(self.config, self.llm)
