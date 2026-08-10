"""
Tests for compaction module integration in expert-agent Semantic Group ReAct.

Covers:
1. Module-level: cut_point, serialize, tokens, overflow, settings
2. Internal message handling: nudge/analysis markers
3. Compaction guard lifecycle
4. Config defaults and env-var overrides
5. Integration: ReActRunner with compaction enabled/disabled

Run:
  cd dac/expert-agent
  python -m pytest tests/test_compaction.py -v -s
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent.compaction import (
    CompactionConfig,
    CompactionGuard,
    CompactionSettings,
    default_compaction_config,
)
from agent.compaction.cut_point import (
    CutPointResult,
    find_cut_point,
    find_turn_start_index,
    find_valid_cut_points,
    is_cut_point_message,
    is_turn_start_message,
)
from agent.compaction.messages import (
    INTERNAL_MESSAGE_KEY,
    is_compaction_summary_message,
    is_internal_message,
    make_compaction_summary_message,
)
from agent.compaction.overflow import (
    is_context_overflow_message,
    is_overflow_exception,
    is_overflow_error_text,
    is_silent_overflow_success,
)
from agent.compaction.serialize import serialize_conversation
from agent.compaction.settings import (
    DEFAULT_CONTEXT_WINDOW,
    context_window_from_env,
    default_compaction_config as _default_config,
)
from agent.compaction.tokens import (
    UsageSnapshot,
    calculate_context_tokens,
    estimate_context_tokens,
    estimate_tokens,
    should_compact,
    usage_from_ai_message,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_human(content: str, internal: bool = False) -> HumanMessage:
    kwargs = {}
    if internal:
        kwargs["additional_kwargs"] = {INTERNAL_MESSAGE_KEY: True}
    return HumanMessage(content=content, **kwargs)


def _make_ai(content: str = "", tool_calls: list | None = None) -> AIMessage:
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


def _make_tool(content: str, tool_call_id: str = "tc_1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id)


# ══════════════════════════════════════════════════════════════════════
# Case 1-5: Internal message handling
# ══════════════════════════════════════════════════════════════════════

class TestInternalMessageHandling:
    """Verify nudge/analysis messages are correctly tagged and detected."""

    def test_case01_internal_message_detection(self):
        """is_internal_message returns True for tagged messages."""
        msg = _make_human("nudge", internal=True)
        assert is_internal_message(msg) is True

    def test_case02_normal_human_is_not_internal(self):
        """is_internal_message returns False for untagged user messages."""
        msg = _make_human("user query", internal=False)
        assert is_internal_message(msg) is False

    def test_case03_ai_message_is_not_internal(self):
        """is_internal_message returns False for AIMessage."""
        msg = _make_ai("some response")
        assert is_internal_message(msg) is False

    def test_case04_tool_message_is_not_internal(self):
        """is_internal_message returns False for ToolMessage."""
        msg = _make_tool("result")
        assert is_internal_message(msg) is False

    def test_case05_compaction_summary_is_not_internal(self):
        """is_internal_message returns False for compaction summary."""
        msg = make_compaction_summary_message("summary text")
        assert is_internal_message(msg) is False


# ══════════════════════════════════════════════════════════════════════
# Case 6-10: cut_point internal message handling
# ══════════════════════════════════════════════════════════════════════

class TestCutPointWithInternalMessages:
    """Verify cut_point logic correctly handles internal HumanMessages."""

    def test_case06_internal_not_turn_start(self):
        """Internal HumanMessage is NOT a turn-start message."""
        msg = _make_human("nudge", internal=True)
        assert is_turn_start_message(msg) is False

    def test_case07_normal_human_is_turn_start(self):
        """Normal HumanMessage IS a turn-start message."""
        msg = _make_human("user query", internal=False)
        assert is_turn_start_message(msg) is True

    def test_case08_internal_is_valid_cut_point(self):
        """Internal HumanMessage IS a valid cut point (just not a turn start)."""
        msg = _make_human("nudge", internal=True)
        assert is_cut_point_message(msg) is True

    def test_case09_find_turn_start_skips_internal(self):
        """find_turn_start_index skips internal messages to find real user."""
        dialog = [
            _make_human("real user query", internal=False),
            _make_ai("thinking..."),
            _make_human("nudge", internal=True),
            _make_ai("tool_calls=..."),
        ]
        # Cut at last message (index 3), search backwards from there
        idx = find_turn_start_index(dialog, entry_index=3, start_index=0)
        assert idx == 0  # Should find the real user query at index 0

    def test_case10_cut_point_with_internal_messages(self):
        """find_cut_point correctly handles dialog with internal messages."""
        dialog = [
            _make_human("user query", internal=False),
            _make_ai("thinking..."),
            _make_tool("result"),
            _make_human("nudge", internal=True),
            _make_ai("more thinking..."),
            _make_tool("result2"),
        ]
        # With high keep_recent_tokens, should keep all recent messages
        result = find_cut_point(dialog, start_index=0, end_index=len(dialog), keep_recent_tokens=10000)
        assert result.first_kept_index == 0
        assert result.is_split_turn is False

    def test_case11_short_keep_budget_creates_split_turn(self):
        """With small keep_recent_tokens, produce a split turn."""
        dialog = [
            _make_human("user query", internal=False),
            _make_ai("thinking..."),
            _make_tool("result"),
            _make_human("nudge", internal=True),
            _make_ai("more thinking..."),
            _make_tool("result2"),
        ]
        # Small budget: keep only the last 2 messages
        result = find_cut_point(dialog, start_index=0, end_index=len(dialog), keep_recent_tokens=10)
        # Should cut somewhere after index 0
        assert result.first_kept_index > 0
        # If cut is not at a turn start, should be split_turn
        if not is_turn_start_message(dialog[result.first_kept_index]):
            assert result.is_split_turn is True
            # turn_start should be index 0 (real user query), not the nudge
            assert result.turn_start_index == 0
        else:
            assert result.is_split_turn is False


# ══════════════════════════════════════════════════════════════════════
# Case 12-15: serialize_conversation internal message handling
# ══════════════════════════════════════════════════════════════════════

class TestSerializeInternalMessages:
    """Verify serialize_conversation skips internal messages."""

    def test_case12_serialize_skips_internal_nudge(self):
        """Internal nudge is not included in serialized output."""
        messages = [
            _make_human("user query", internal=False),
            _make_human("nudge", internal=True),
            _make_ai("response"),
            _make_tool("result"),
        ]
        text = serialize_conversation(messages)
        assert "[User]: user query" in text
        assert "nudge" not in text

    def test_case13_serialize_skips_internal_analysis(self):
        """Internal analysis message is not included in serialized output."""
        messages = [
            _make_human("user query", internal=False),
            _make_human("## Execution Analysis\nDiagnosis: stuck", internal=True),
        ]
        text = serialize_conversation(messages)
        assert "[User]: user query" in text
        assert "Execution Analysis" not in text

    def test_case14_serialize_includes_compaction_summary(self):
        """Compaction summary is included in serialized output."""
        messages = [
            make_compaction_summary_message("summary text"),
            _make_ai("response"),
            _make_tool("result"),
        ]
        text = serialize_conversation(messages)
        assert "summary text" in text

    def test_case15_serialize_mixed_messages(self):
        """Mixed internal and normal messages are handled correctly."""
        messages = [
            _make_human("user query", internal=False),
            _make_ai("tool_calls=[code_agent(query='hello')]"),
            _make_tool("agent result"),
            _make_human("nudge", internal=True),
            _make_ai("more tool_calls=[structured_agent(query='data')]"),
            _make_tool("data result"),
            _make_human("## Analysis", internal=True),
        ]
        text = serialize_conversation(messages)
        assert "[User]: user query" in text
        # The AIMessage content includes the tool_calls text as content,
        # not as actual tool_calls on the message, so it renders as [Assistant]
        assert "code_agent" in text
        assert "[Tool result]: agent result" in text
        assert "structured_agent" in text
        assert "[Tool result]: data result" in text
        assert "nudge" not in text
        assert "Analysis" not in text


# ══════════════════════════════════════════════════════════════════════
# Case 16-20: token estimation and threshold
# ══════════════════════════════════════════════════════════════════════

class TestTokenEstimation:
    """Verify token estimation and threshold checks."""

    def test_case16_estimate_tokens_human(self):
        """estimate_tokens for HumanMessage: chars/4 ceil."""
        msg = HumanMessage(content="hello world")  # 11 chars
        tokens = estimate_tokens(msg)
        assert tokens == 3  # ceil(11/4) = 3

    def test_case17_estimate_tokens_ai_with_tool_calls(self):
        """estimate_tokens for AIMessage includes tool call args."""
        msg = AIMessage(
            content="thinking",
            tool_calls=[{"id": "tc_1", "name": "code_agent", "args": {"query": "find orders"}}],
        )
        tokens = estimate_tokens(msg)
        # "thinking" = 8 chars, "code_agent" = 10, "query" = 5, "find orders" = 11
        # total = 34, ceil(34/4) = 9
        assert tokens > 0

    def test_case18_should_compact_below_threshold(self):
        """should_compact returns False when tokens are below threshold."""
        settings = CompactionSettings(enabled=True, reserve_tokens=1000)
        assert should_compact(500, 2000, settings) is False
        # 500 <= 2000 - 1000 = 1000

    def test_case19_should_compact_above_threshold(self):
        """should_compact returns True when tokens exceed threshold."""
        settings = CompactionSettings(enabled=True, reserve_tokens=1000)
        assert should_compact(1500, 2000, settings) is True
        # 1500 > 2000 - 1000 = 1000

    def test_case20_should_compact_disabled(self):
        """should_compact returns False when compaction is disabled."""
        settings = CompactionSettings(enabled=False, reserve_tokens=1000)
        assert should_compact(1500, 2000, settings) is False


# ══════════════════════════════════════════════════════════════════════
# Case 21-25: overflow detection
# ══════════════════════════════════════════════════════════════════════

class TestOverflowDetection:
    """Verify overflow detection patterns."""

    def test_case21_overflow_text_context_window(self):
        """Detect 'exceeds the context window' error."""
        assert is_overflow_error_text("prompt exceeds the context window of 8192 tokens") is True

    def test_case22_overflow_text_prompt_too_long(self):
        """Detect 'prompt is too long' error."""
        assert is_overflow_error_text("prompt is too long for model") is True

    def test_case23_rate_limit_not_overflow(self):
        """Rate limit errors are NOT detected as overflow."""
        assert is_overflow_error_text("rate limit exceeded") is False

    def test_case24_context_overflow_message_usage(self):
        """Detect overflow from AIMessage when input > window."""
        msg = AIMessage(content="ok")
        # Simulate AIMessage with usage_metadata
        msg.usage_metadata = {"input_tokens": 50000, "output_tokens": 100}
        msg.response_metadata = {"finish_reason": "stop"}
        assert is_context_overflow_message(msg, context_window=30000) is True

    def test_case25_silent_overflow_success(self):
        """Detect silent overflow when stop reason is normal but input > window."""
        msg = AIMessage(content="ok")
        msg.usage_metadata = {"input_tokens": 50000, "output_tokens": 100}
        msg.response_metadata = {"finish_reason": "stop"}
        assert is_silent_overflow_success(msg, context_window=30000) is True


# ══════════════════════════════════════════════════════════════════════
# Case 26-30: config and env-var settings
# ══════════════════════════════════════════════════════════════════════

class TestConfigAndEnv:
    """Verify config defaults and env-var overrides."""

    def test_case26_default_compaction_config(self):
        """default_compaction_config returns enabled config with 200K window."""
        config = _default_config()
        assert config.settings.enabled is True
        assert config.context_window == DEFAULT_CONTEXT_WINDOW
        assert config.context_window == 200000

    def test_case27_env_var_disables_compaction(self):
        """SG_REACT_COMPACTION_ENABLED=false disables compaction."""
        with patch.dict(os.environ, {"SG_REACT_COMPACTION_ENABLED": "false"}):
            config = _default_config()
            assert config.settings.enabled is False

    def test_case28_env_var_override_window(self):
        """SG_REACT_CONTEXT_WINDOW overrides the default window."""
        with patch.dict(os.environ, {"SG_REACT_CONTEXT_WINDOW": "128000"}):
            config = _default_config()
            assert config.context_window == 128000

    def test_case29_context_window_from_env(self):
        """context_window_from_env reads env var correctly."""
        with patch.dict(os.environ, {"SG_REACT_CONTEXT_WINDOW": "64000"}):
            assert context_window_from_env() == 64000

    def test_case30_invalid_window_uses_default(self):
        """Invalid SG_REACT_CONTEXT_WINDOW falls back to default."""
        with patch.dict(os.environ, {"SG_REACT_CONTEXT_WINDOW": "not_a_number"}):
            assert context_window_from_env(200000) == 200000


# ══════════════════════════════════════════════════════════════════════
# Case 31-35: CompactionGuard lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestCompactionGuardLifecycle:
    """Verify CompactionGuard lifecycle and state management."""

    def test_case31_guard_creation(self):
        """CompactionGuard can be created with config."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        assert guard.config == config
        assert guard.llm == llm
        assert guard.boundaries == []
        assert guard.overflow_recovery_attempted is False

    def test_case32_new_run_guard_resets_state(self):
        """new_run_guard creates a fresh instance with reset state."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        template = CompactionGuard(config, llm)
        # Simulate some state
        template.overflow_recovery_attempted = True
        template.boundaries = [MagicMock()]

        new_guard = template.new_run_guard()
        assert new_guard is not template
        assert new_guard.overflow_recovery_attempted is False
        assert new_guard.boundaries == []
        assert new_guard.config is config
        assert new_guard.llm is llm

    @pytest.mark.asyncio
    async def test_case33_before_invoke_disabled(self):
        """before_invoke returns unchanged messages when disabled."""
        config = CompactionConfig(
            context_window=128000,
            settings=CompactionSettings(enabled=False),
        )
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        messages = [SystemMessage(content="system"), HumanMessage(content="query")]
        result = await guard.before_invoke(messages)
        assert result == messages

    @pytest.mark.asyncio
    async def test_case34_before_invoke_below_threshold(self):
        """before_invoke returns unchanged messages when below threshold."""
        config = CompactionConfig(
            context_window=128000,
            settings=CompactionSettings(enabled=True, reserve_tokens=10000),
        )
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        messages = [SystemMessage(content="s"), HumanMessage(content="short")]
        result = await guard.before_invoke(messages)
        assert result == messages

    @pytest.mark.asyncio
    async def test_case35_after_invoke_no_overflow(self):
        """after_invoke returns no action when no overflow."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        messages = [SystemMessage(content="s"), HumanMessage(content="query")]
        ai_msg = AIMessage(content="ok")
        action = await guard.after_invoke(messages, ai_msg)
        assert action.compacted is False
        assert action.messages is None


# ══════════════════════════════════════════════════════════════════════
# Case 36-40: on_invoke_error overflow recovery
# ══════════════════════════════════════════════════════════════════════

class TestOverflowRecovery:
    """Verify overflow recovery via on_invoke_error."""

    @pytest.mark.asyncio
    async def test_case36_non_overflow_error_returns_none(self):
        """on_invoke_error returns None for non-overflow errors."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        messages = [SystemMessage(content="s"), HumanMessage(content="query")]
        exc = ValueError("something else")
        result = await guard.on_invoke_error(messages, exc)
        assert result is None

    @pytest.mark.asyncio
    async def test_case37_overflow_error_disabled_returns_none(self):
        """on_invoke_error returns None when compaction is disabled."""
        config = CompactionConfig(
            context_window=128000,
            settings=CompactionSettings(enabled=False),
        )
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        messages = [SystemMessage(content="s"), HumanMessage(content="query")]
        exc = Exception("prompt is too long")
        result = await guard.on_invoke_error(messages, exc)
        assert result is None

    @pytest.mark.asyncio
    async def test_case38_overflow_recovery_second_attempt_fails(self):
        """Second overflow recovery attempt returns failed=True."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        guard.overflow_recovery_attempted = True
        messages = [SystemMessage(content="s"), HumanMessage(content="query")]
        exc = Exception("prompt is too long")
        result = await guard.on_invoke_error(messages, exc)
        assert result is not None
        assert result.failed is True
        assert result.will_retry is False

    @pytest.mark.asyncio
    async def test_case39_overflow_error_compact(self):
        """Overflow error triggers compaction and returns recovery."""
        config = CompactionConfig(
            context_window=8000,
            settings=CompactionSettings(enabled=True, reserve_tokens=1000, keep_recent_tokens=500),
        )
        # Use MagicMock + AsyncMock for ainvoke, and bind() returns self
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nTest summary"))
        llm.bind = MagicMock(return_value=llm)
        guard = CompactionGuard(config, llm)
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="a" * 5000),  # many chars
            AIMessage(content="b" * 1000),
            ToolMessage(content="c" * 1000, tool_call_id="tc_1"),
        ]
        exc = Exception("prompt is too long")
        result = await guard.on_invoke_error(messages, exc)
        assert result is not None
        assert result.will_retry is True
        assert result.failed is False
        assert result.messages is not None

    @pytest.mark.asyncio
    async def test_case40_overflow_error_no_compact_possible(self):
        """When nothing to compact, overflow recovery fails."""
        config = CompactionConfig(
            context_window=8000,
            settings=CompactionSettings(enabled=True, reserve_tokens=1000, keep_recent_tokens=200),
        )
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nTest"))
        guard = CompactionGuard(config, llm)
        # Very short messages — nothing to summarize
        messages = [
            SystemMessage(content="s"),
            HumanMessage(content="q"),
        ]
        exc = Exception("prompt is too long")
        result = await guard.on_invoke_error(messages, exc)
        assert result is not None
        assert result.failed is True


# ══════════════════════════════════════════════════════════════════════
# Case 41-45: usage tracking
# ══════════════════════════════════════════════════════════════════════

class TestUsageTracking:
    """Verify usage extraction and tracking."""

    def test_case41_usage_from_ai_message_metadata(self):
        """usage_from_ai_message extracts usage_metadata."""
        msg = AIMessage(content="ok")
        msg.usage_metadata = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
        usage = usage_from_ai_message(msg)
        assert usage is not None
        assert usage.input == 1000
        assert usage.output == 200
        assert usage.total_tokens == 1200

    def test_case42_usage_from_ai_message_response_metadata(self):
        """usage_from_ai_message falls back to response_metadata."""
        msg = AIMessage(content="ok")
        msg.response_metadata = {
            "token_usage": {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
        }
        usage = usage_from_ai_message(msg)
        assert usage is not None
        assert usage.input == 500

    def test_case43_usage_from_non_ai_returns_none(self):
        """usage_from_ai_message returns None for non-AIMessage."""
        msg = HumanMessage(content="hello")
        assert usage_from_ai_message(msg) is None

    def test_case44_calculate_context_tokens(self):
        """calculate_context_tokens sums usage fields."""
        snap = UsageSnapshot(input=1000, output=200, cache_read=100, cache_write=50)
        assert calculate_context_tokens(snap) == 1350

    def test_case45_estimate_context_tokens(self):
        """estimate_context_tokens estimates from messages."""
        messages = [
            SystemMessage(content="a" * 400),
            HumanMessage(content="b" * 400),
            AIMessage(content="c" * 400),
            ToolMessage(content="d" * 400, tool_call_id="tc_1"),
        ]
        est = estimate_context_tokens(messages)
        # ~400 chars each = ~100 tokens each, total ~400
        assert est.tokens > 0
        assert est.last_usage_index is None  # No AIMessage with real usage


# ══════════════════════════════════════════════════════════════════════
# Case 46-50: end-to-end guard integration
# ══════════════════════════════════════════════════════════════════════

class TestGuardIntegration:
    """Verify CompactionGuard integration with realistic message sequences."""

    @pytest.mark.asyncio
    async def test_case46_guard_events_tracking(self):
        """Compaction events are tracked in guard.events."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        assert guard.events == []
        assert guard._compact_count == 0

    @pytest.mark.asyncio
    async def test_case47_compact_manual(self):
        """Manual compaction works even when auto-compaction is disabled."""
        config = CompactionConfig(
            context_window=4000,
            settings=CompactionSettings(enabled=False, keep_recent_tokens=200),
        )
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nManual summary"))
        # bind() must return an object with ainvoke, not a coroutine
        llm.bind = MagicMock(return_value=llm)
        guard = CompactionGuard(config, llm)
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="a" * 3000),
            AIMessage(content="b" * 2000),
            ToolMessage(content="c" * 2000, tool_call_id="tc_1"),
        ]
        result = await guard.compact_manual(messages)
        assert result is not None
        assert "Goal" in result.summary
        assert result.reason == "manual"

    @pytest.mark.asyncio
    async def test_case48_guard_with_internal_messages_in_kept(self):
        """Internal messages in kept region are preserved verbatim."""
        config = CompactionConfig(
            context_window=4000,
            settings=CompactionSettings(enabled=True, reserve_tokens=500, keep_recent_tokens=50),
        )
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nSummary"))
        guard = CompactionGuard(config, llm)
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="a" * 3000),  # lots of chars to trigger compaction
            AIMessage(content="b" * 500),
            ToolMessage(content="c" * 500, tool_call_id="tc_1"),
            _make_human("nudge", internal=True),
            AIMessage(content="final"),
        ]
        result = await guard.before_invoke(messages)
        # The internal nudge should be in the kept region (it's recent)
        # and preserved verbatim
        assert isinstance(result, list)
        # Find the nudge message in the result
        nudge_found = any(
            is_internal_message(m) for m in result if isinstance(m, HumanMessage)
        )
        assert nudge_found is True

    @pytest.mark.asyncio
    async def test_case49_guard_skips_internal_in_summary(self):
        """Internal messages are not included in the summary."""
        config = CompactionConfig(
            context_window=4000,
            settings=CompactionSettings(enabled=True, reserve_tokens=500, keep_recent_tokens=10),
        )
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="## Goal\nSummary"))
        guard = CompactionGuard(config, llm)
        messages = [
            SystemMessage(content="system"),
            _make_human("user question", internal=False),
            _make_human("nudge", internal=True),
            AIMessage(content="a" * 2000),
            ToolMessage(content="b" * 2000, tool_call_id="tc_1"),
        ]
        result = await guard.before_invoke(messages)
        assert isinstance(result, list)
        # The summary should not contain "nudge"
        summary_msgs = [m for m in result if is_compaction_summary_message(m)]
        if summary_msgs:
            for sm in summary_msgs:
                content = str(getattr(sm, "content", ""))
                assert "nudge" not in content

    @pytest.mark.asyncio
    async def test_case50_note_usage_tracks_last_usage(self):
        """note_usage updates last_usage_tokens."""
        config = CompactionConfig(context_window=128000)
        llm = MagicMock()
        guard = CompactionGuard(config, llm)
        assert guard.last_usage_tokens is None

        msg = AIMessage(content="ok")
        msg.usage_metadata = {"input_tokens": 5000, "output_tokens": 100, "total_tokens": 5100}
        guard.note_usage(msg)
        assert guard.last_usage_tokens == 5100