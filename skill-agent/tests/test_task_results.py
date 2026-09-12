"""Phase 0.5: task-keyed result retention.

The golden case replayed here is the observed `fw-worker` run of 2026-09-11:
three mid-exec tasks targeted one agent, the first returned 3104 characters
after 176 seconds, and the two that were blocked by the hop budget replaced it
with the 37-character "No available agent can do this task. " placeholder.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.task_results import (  # noqa: E402
    REASON_HOP_EXHAUSTED,
    REASON_NO_AGENT_CARD,
    STAGE_LOCAL,
    STAGE_MID_EXEC,
    STAGE_MID_EXEC_SELF,
    STAGE_PRE_EXEC,
    STATUS_BLOCKED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_SUCCESS,
    DispatchLedger,
    turn_scoped_id,
)

NONE_TASK_DESCRIPTION = "No available agent can do this task. "
AGENT = "Paper-Answering-TDB-Agent"


def _ledger() -> DispatchLedger:
    return DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))


class ResultRetentionTest(unittest.TestCase):
    def test_blocked_task_cannot_overwrite_completed_result(self) -> None:
        real_result = "x" * 3104
        ledger = _ledger()

        ledger.record_result(task_id=1, agent=AGENT, result=real_result, round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_blocked(
            task_id=2, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, round_index=1,
            stage=STAGE_MID_EXEC,
        )
        ledger.record_blocked(
            task_id=3, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        view = ledger.results_by_agent()
        self.assertEqual(view[AGENT], real_result)
        self.assertEqual(len(view[AGENT]), 3104)

    def test_every_planned_task_reaches_a_terminal_state(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="ok", round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_blocked(
            task_id=2, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, round_index=1,
            stage=STAGE_MID_EXEC,
        )
        ledger.record_blocked(
            task_id=3, agent="Missing-Agent", reason_code=REASON_NO_AGENT_CARD, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual({o.task_id for o in ledger.outcomes()}, {1, 2, 3})
        self.assertEqual(
            [o.reason_code for o in ledger.blocked()],
            [REASON_HOP_EXHAUSTED, REASON_NO_AGENT_CARD],
        )
        self.assertEqual(ledger.summary()["blocked"], 2)

    def test_two_results_from_one_agent_are_both_kept(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="first", round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=2, agent=AGENT, result="second", round_index=1, stage=STAGE_MID_EXEC)

        merged = ledger.results_by_agent()[AGENT]
        self.assertIn("first", merged)
        self.assertIn("second", merged)
        self.assertIn("[Task #1]", merged)
        self.assertIn("[Task #2]", merged)

    def test_later_round_does_not_replace_earlier_round(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="round one", round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=9, agent=AGENT, result="round two", round_index=2, stage=STAGE_MID_EXEC)

        merged = ledger.results_by_agent()[AGENT]
        self.assertIn("round one", merged)
        self.assertIn("round two", merged)

    def test_placeholder_result_is_recorded_as_empty_not_content(self) -> None:
        ledger = _ledger()
        outcome = ledger.record_result(
            task_id=1, agent=AGENT, result=NONE_TASK_DESCRIPTION, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(outcome.status, STATUS_EMPTY)
        self.assertNotIn(AGENT, ledger.results_by_agent())

    def test_status_classification(self) -> None:
        ledger = _ledger()
        self.assertEqual(
            ledger.record_result(task_id=1, agent=AGENT, result="data", stage=STAGE_MID_EXEC).status,
            STATUS_SUCCESS,
        )
        self.assertEqual(
            ledger.record_result(task_id=2, agent=AGENT, result="   ", stage=STAGE_MID_EXEC).status,
            STATUS_EMPTY,
        )
        self.assertEqual(
            ledger.record_blocked(
                task_id=3, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED,
                stage=STAGE_MID_EXEC,
            ).status,
            STATUS_BLOCKED,
        )


class ExhaustedAgentMarkingTest(unittest.TestCase):
    def test_blocked_agent_is_not_marked_exhausted(self) -> None:
        """An agent that was never asked has not proven it has nothing to give."""
        ledger = _ledger()
        ledger.record_blocked(
            task_id=1, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(ledger.agents_without_usable_result(round_index=1), set())

    def test_dispatched_empty_agent_is_marked_exhausted(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="", round_index=1, stage=STAGE_MID_EXEC)

        self.assertEqual(ledger.agents_without_usable_result(round_index=1), {AGENT})

    def test_agent_with_one_good_and_one_empty_result_is_not_exhausted(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="useful", round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=2, agent=AGENT, result="", round_index=1, stage=STAGE_MID_EXEC)

        self.assertEqual(ledger.agents_without_usable_result(round_index=1), set())

    def test_round_scoping(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="", round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=2, agent="Other-Agent", result="", round_index=2, stage=STAGE_MID_EXEC)

        self.assertEqual(ledger.agents_without_usable_result(round_index=1), {AGENT})
        self.assertEqual(
            ledger.agents_without_usable_result(round_index=2), {"Other-Agent"}
        )


class DelegationErrorTest(unittest.TestCase):
    """An execution error is not domain evidence and must not reach synthesis."""

    def test_delegation_failure_is_not_success(self) -> None:
        ledger = _ledger()
        outcome = ledger.record_result(
            task_id=1,
            agent=AGENT,
            result="Delegation failed: ReadTimeout('peer did not respond')",
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertFalse(outcome.usable)
        self.assertNotIn(AGENT, ledger.results_by_agent())

    def test_execution_error_is_not_success(self) -> None:
        ledger = _ledger()
        outcome = ledger.record_result(
            task_id=1, agent=AGENT, result="Execution error: tool unavailable",
            stage=STAGE_MID_EXEC,
        )
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertNotIn(AGENT, ledger.results_by_agent())

    def test_error_text_is_retained_for_diagnosis(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="Delegation failed: boom",
            stage=STAGE_MID_EXEC,
        )
        failed = ledger.failed()
        self.assertEqual(len(failed), 1)
        self.assertIn("boom", failed[0].error)
        self.assertEqual(ledger.summary()["failed"], 1)

    def test_failed_agent_counts_as_having_no_usable_result(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="Delegation failed: boom", round_index=1,
            stage=STAGE_MID_EXEC,
        )
        self.assertEqual(ledger.agents_without_usable_result(round_index=1), {AGENT})

    def test_a_real_result_still_survives_a_sibling_failure(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="real evidence", stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=2, agent=AGENT, result="Delegation failed: boom", stage=STAGE_MID_EXEC)

        self.assertEqual(ledger.results_by_agent()[AGENT], "real evidence")

    def test_text_merely_containing_the_prefix_is_still_content(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1,
            agent=AGENT,
            result="The paper notes that delegation failed: in Tang practice...",
            stage=STAGE_MID_EXEC,
        )
        self.assertIn(AGENT, ledger.results_by_agent())


class CrossTurnRetentionTest(unittest.TestCase):
    """Each turn's planner numbers tasks from 1, so ids collide across turns."""

    def test_turn_scoped_ids_do_not_collide(self) -> None:
        self.assertEqual(turn_scoped_id(1, 1), 1)
        self.assertNotEqual(turn_scoped_id(1, 2), turn_scoped_id(1, 1))
        self.assertNotEqual(turn_scoped_id(1, 3), turn_scoped_id(1, 2))

    def test_mid_exec_round_does_not_collide_with_pre_exec(self) -> None:
        """Mid-exec plans re-number from 1 inside the same turn."""
        ids = {
            turn_scoped_id(1, turn=1, round_index=0),
            turn_scoped_id(1, turn=1, round_index=1),
            turn_scoped_id(1, turn=1, round_index=2),
            turn_scoped_id(1, turn=2, round_index=0),
            turn_scoped_id(1, turn=2, round_index=1),
        }
        self.assertEqual(len(ids), 5)

    def test_pre_exec_and_mid_exec_results_both_survive_in_one_turn(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="pre-exec finding", stage="pre_exec",
            turn=1, round_index=0,
        )
        ledger.record_result(
            task_id=1, agent=AGENT, result="mid-exec finding", stage="mid_exec",
            turn=1, round_index=1,
        )

        by_task = ledger.task_results_by_scoped_id()
        self.assertEqual(len(by_task), 2)
        self.assertIn("pre-exec finding", by_task.values())
        self.assertIn("mid-exec finding", by_task.values())

    def test_turn_two_does_not_replace_turn_one_for_the_same_task_id(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="turn one finding", turn=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=1, agent=AGENT, result="turn two finding", turn=2, stage=STAGE_MID_EXEC)

        by_task = ledger.task_results_by_scoped_id()
        self.assertEqual(len(by_task), 2)
        self.assertIn("turn one finding", by_task.values())
        self.assertIn("turn two finding", by_task.values())

    def test_turn_two_does_not_replace_turn_one_for_the_same_agent(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="turn one finding", turn=1, stage=STAGE_MID_EXEC)
        ledger.record_result(task_id=1, agent=AGENT, result="turn two finding", turn=2, stage=STAGE_MID_EXEC)

        merged = ledger.results_by_agent()[AGENT]
        self.assertIn("turn one finding", merged)
        self.assertIn("turn two finding", merged)
        self.assertIn("Turn 2", merged)

    def test_blocked_task_in_turn_two_does_not_erase_turn_one(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="turn one finding", turn=1, stage=STAGE_MID_EXEC)
        ledger.record_blocked(
            task_id=1, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, turn=2,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(ledger.results_by_agent()[AGENT], "turn one finding")


class TurnScopedExhaustionTest(unittest.TestCase):
    """The ledger spans the run, so round filtering alone mixes turns."""

    def test_turn_one_success_does_not_mask_turn_two_failure(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="found it", turn=1, round_index=1,
            stage=STAGE_MID_EXEC,
        )
        ledger.record_result(
            task_id=1, agent=AGENT, result="", turn=2, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(
            ledger.agents_without_usable_result(round_index=1, turn=2), {AGENT}
        )
        self.assertEqual(
            ledger.agents_without_usable_result(round_index=1, turn=1), set()
        )

    def test_turn_two_success_does_not_clear_turn_one_exhaustion(self) -> None:
        ledger = _ledger()
        ledger.record_result(task_id=1, agent=AGENT, result="", turn=1, round_index=1, stage=STAGE_MID_EXEC)
        ledger.record_result(
            task_id=1, agent=AGENT, result="found it", turn=2, round_index=1,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(
            ledger.agents_without_usable_result(round_index=1, turn=1), {AGENT}
        )

    def test_failed_and_blocked_can_be_scoped_to_one_turn(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="Delegation failed: boom", turn=1,
            stage=STAGE_MID_EXEC,
        )
        ledger.record_blocked(
            task_id=2, agent=AGENT, reason_code=REASON_HOP_EXHAUSTED, turn=2,
            stage=STAGE_MID_EXEC,
        )

        self.assertEqual(len(ledger.failed(turn=1)), 1)
        self.assertEqual(len(ledger.failed(turn=2)), 0)
        self.assertEqual(len(ledger.blocked(turn=2)), 1)


class StageSeparationTest(unittest.TestCase):
    """Local work is this agent's own output, not a peer's contribution."""

    def test_local_results_are_not_in_the_delegated_view(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent="Self-Agent", result="local finding", stage=STAGE_LOCAL
        )
        self.assertEqual(ledger.results_by_agent(), {})

    def test_mid_exec_self_results_are_not_in_the_delegated_view(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1,
            agent="Self-Agent",
            result="self finding",
            stage=STAGE_MID_EXEC_SELF,
        )
        self.assertEqual(ledger.results_by_agent(), {})

    def test_remote_results_are_in_the_delegated_view(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent=AGENT, result="peer finding", stage=STAGE_PRE_EXEC
        )
        ledger.record_result(
            task_id=2, agent=AGENT, result="peer finding 2", stage=STAGE_MID_EXEC
        )
        self.assertIn(AGENT, ledger.results_by_agent())

    def test_local_and_self_results_still_reach_the_task_view(self) -> None:
        """They are evidence — they just belong to this agent, not a peer."""
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent="Self-Agent", result="local finding", stage=STAGE_LOCAL
        )
        ledger.record_result(
            task_id=2,
            agent="Self-Agent",
            result="self finding",
            stage=STAGE_MID_EXEC_SELF,
            round_index=1,
        )
        values = list(ledger.task_results_by_scoped_id().values())
        self.assertIn("local finding", values)
        self.assertIn("self finding", values)

    def test_explicit_stage_none_returns_every_stage(self) -> None:
        ledger = _ledger()
        ledger.record_result(
            task_id=1, agent="Self-Agent", result="local finding", stage=STAGE_LOCAL
        )
        self.assertIn("Self-Agent", ledger.results_by_agent(stages=None))


if __name__ == "__main__":
    unittest.main()
