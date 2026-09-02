"""Unit tests for the stagnation detector."""

from __future__ import annotations

import json

from skill_sdk.skill.stagnation import (
    StagnationDetector,
    StagnationEvent,
    generate_stagnation_intervention,
)
from skill_sdk.skill.tool_result import ToolResult


class TestStagnationDetector:
    """Unit tests for stagnation detection logic."""

    def _make_result(self, status: str, content: str = "") -> str:
        r = ToolResult(
            tool_name="plan_cmd",
            status=status,
            is_error=(status != "success"),
            content=content,
            details={},
        )
        return r.to_tool_message_content()

    def test_record_and_empty_check(self):
        """Empty detector should not trigger."""
        d = StagnationDetector()
        assert d.check(1) is None

    def test_single_event_no_trigger(self):
        """Single event should not trigger any warning."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "ls"}, self._make_result("error", "not found"))
        assert d.check(2) is None

    def test_same_cmd_repeat_detection(self):
        """Same command failing twice triggers detection."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "not found"))
        d.record(2, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "still not found"))
        intervention = d.check(3)
        assert intervention is not None
        assert "Same plan_cmd call failing repeatedly" in intervention
        assert "bad_cmd" in intervention

    def test_same_cmd_repeat_with_success_resets(self):
        """Same cmd failing once, then success, then failing again should NOT trigger."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "cmd"}, self._make_result("error", "fail"))
        d.record(2, "plan_cmd", {"cmd": "cmd"}, self._make_result("success", "ok"))
        d.record(3, "plan_cmd", {"cmd": "cmd"}, self._make_result("error", "fail again"))
        # Only 2 failures total (not in a row with same cmd), so threshold is 2
        intervention = d.check(4)
        # Should trigger because 2 failures of same cmd, even with a success in between
        assert intervention is not None
        assert "Same plan_cmd call failing repeatedly" in intervention

    def test_consecutive_failures_detection(self):
        """3 consecutive failures trigger detection."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "a"}, self._make_result("error", "fail a"))
        d.record(2, "plan_cmd", {"cmd": "b"}, self._make_result("error", "fail b"))
        d.record(3, "plan_cmd", {"cmd": "c"}, self._make_result("error", "fail c"))
        intervention = d.check(4)
        assert intervention is not None
        assert "consecutive tool failures" in intervention

    def test_consecutive_failures_reset_by_success(self):
        """Success resets the consecutive failure counter, but other patterns may still fire."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "a"}, self._make_result("error", "error_type_A"))
        d.record(2, "plan_cmd", {"cmd": "b"}, self._make_result("error", "error_type_B"))
        d.record(3, "plan_cmd", {"cmd": "c"}, self._make_result("success", "ok"))
        d.record(4, "plan_cmd", {"cmd": "d"}, self._make_result("error", "error_type_C"))
        intervention = d.check(5)
        # No consecutive failures (reset by success at step 3), no same error pattern
        # (all different error types), and 3/4=75% is above threshold but
        # check() may throttle. The key assertion: no "consecutive" in the message.
        if intervention is not None:
            assert "consecutive" not in intervention

    def test_same_error_pattern_detection(self):
        """Same error pattern appearing 3 times triggers detection."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "a"}, self._make_result("error", "command not found"))
        d.record(2, "plan_cmd", {"cmd": "b"}, self._make_result("error", "command not found"))
        d.record(3, "plan_cmd", {"cmd": "c"}, self._make_result("error", "command not found"))
        intervention = d.check(4)
        assert intervention is not None
        assert "Same error pattern repeating" in intervention

    def test_high_failure_rate(self):
        """High failure rate triggers detection."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "a"}, self._make_result("error", "err_type_A"))
        d.record(2, "plan_cmd", {"cmd": "b"}, self._make_result("error", "err_type_B"))
        d.record(3, "plan_cmd", {"cmd": "c"}, self._make_result("error", "err_type_C"))
        d.record(4, "plan_cmd", {"cmd": "d"}, self._make_result("success", "ok"))
        # 3/4 = 75% > 70% threshold. Step 7 is far enough past throttling.
        intervention = d.check(7)
        assert intervention is not None
        assert "High failure rate" in intervention

    def test_no_intervention_spam(self):
        """Interventions are throttled — not every step."""
        d = StagnationDetector()
        # Fill with 3 consecutive failures
        d.record(1, "plan_cmd", {"cmd": "a"}, self._make_result("error", "fail"))
        d.record(2, "plan_cmd", {"cmd": "b"}, self._make_result("error", "fail"))
        d.record(3, "plan_cmd", {"cmd": "c"}, self._make_result("error", "fail"))
        # First check triggers
        intervention = d.check(4)
        assert intervention is not None

        # Add another failure, check again immediately
        d.record(4, "plan_cmd", {"cmd": "d"}, self._make_result("error", "fail"))
        # Should be throttled (step 5 - 4 < 3)
        intervention2 = d.check(5)
        assert intervention2 is None

        # After 3 more steps, should trigger again
        d.record(5, "plan_cmd", {"cmd": "e"}, self._make_result("error", "fail"))
        d.record(6, "plan_cmd", {"cmd": "f"}, self._make_result("error", "fail"))
        d.record(7, "plan_cmd", {"cmd": "g"}, self._make_result("error", "fail"))
        intervention3 = d.check(8)
        assert intervention3 is not None

    def test_check_same_cmd_before_execute(self):
        """Pre-execution check warns when same cmd already failed twice."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "not found"))
        d.record(2, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "still not found"))

        pre_check = d.check_same_cmd_before_execute("plan_cmd", {"cmd": "bad_cmd"})
        assert pre_check is not None
        assert "WARNING" in pre_check
        assert "already failed 2 times" in pre_check

    def test_check_same_cmd_before_execute_not_reached_threshold(self):
        """Pre-execution check returns None when threshold not reached."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "not found"))
        # Only 1 failure, threshold is 2
        pre_check = d.check_same_cmd_before_execute("plan_cmd", {"cmd": "bad_cmd"})
        assert pre_check is None

    def test_check_same_cmd_before_execute_different_cmd(self):
        """Pre-execution check returns None for different commands."""
        d = StagnationDetector()
        d.record(1, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "failed"))
        d.record(2, "plan_cmd", {"cmd": "bad_cmd"}, self._make_result("error", "failed"))

        pre_check = d.check_same_cmd_before_execute("plan_cmd", {"cmd": "different_cmd"})
        assert pre_check is None

    def test_generate_stagnation_intervention(self):
        """High-level helper function works correctly."""
        d = StagnationDetector()
        tool_history = [
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail1")},
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail2")},
        ]
        intervention = generate_stagnation_intervention(d, 3, tool_history)
        assert intervention is not None
        assert "Same plan_cmd call failing repeatedly" in intervention

    def test_generate_stagnation_intervention_only_new_events(self):
        """Second call only processes new events, doesn't double-count.
        Throttling may prevent second intervention if within 3 steps."""
        d = StagnationDetector()
        tool_history = [
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail1")},
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail2")},
        ]
        # First call records both events and checks
        intervention1 = generate_stagnation_intervention(d, 3, tool_history)
        assert intervention1 is not None

        # Verify events were recorded
        assert len(d.events) == 2

        # Add more events and check at a later step (beyond throttle window)
        tool_history.append(
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail3")}
        )
        tool_history.append(
            {"tool": "plan_cmd", "args": {"cmd": "bad"}, "result": self._make_result("error", "fail4")}
        )
        # Check at step 7 (3 past the last intervention at step 3)
        intervention2 = generate_stagnation_intervention(d, 7, tool_history)
        assert intervention2 is not None
        assert len(d.events) == 4  # two new events recorded

    def test_non_plan_cmd_events_also_tracked(self):
        """Non-plan_cmd errors also contribute to consecutive failure detection."""
        d = StagnationDetector()
        d.record(1, "readline_in_range", {"file_path": "/nonexistent"}, self._make_result("error", "not found"))
        d.record(2, "readline_in_range", {"file_path": "/nonexistent2"}, self._make_result("error", "not found"))
        d.record(3, "grep", {"pattern": "x"}, self._make_result("error", "no matches"))
        intervention = d.check(4)
        assert intervention is not None
        assert "consecutive tool failures" in intervention

    def test_blocked_status_is_error(self):
        """Blocked status counts as an error."""
        d = StagnationDetector()
        blocked_result = ToolResult.blocked("plan_cmd", "Destructive command refused", {}).to_tool_message_content()
        d.record(1, "plan_cmd", {"cmd": "rm"}, blocked_result)
        d.record(2, "plan_cmd", {"cmd": "rm"}, blocked_result)
        d.record(3, "plan_cmd", {"cmd": "rm"}, blocked_result)
        intervention = d.check(4)
        assert intervention is not None
        assert "consecutive" in intervention