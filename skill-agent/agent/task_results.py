"""Task-keyed, append-only ledger for cross-agent dispatch outcomes.

Phase 0.5 of ``docs/MULTI_AGENT_V2_DESIGN.md``.

Delegation results used to live in a ``dict[agent_name, str]``. When one
planning round assigned several tasks to the same agent, the last write won —
including writes made by tasks that never ran. A task blocked before dispatch
stored the ``NONE_TASK_DESCRIPTION`` placeholder under the agent's name and
silently replaced a completed result from the same agent.

This module keeps outcomes keyed by ``task_id``, append-only, and derives the
``dict[agent_name, str]`` view that existing consumers still expect. A blocked
or empty outcome can never remove a usable one because the view is rebuilt from
usable outcomes only.

The ledger holds no orchestration policy: it records what happened and answers
questions about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# ── Outcome statuses ────────────────────────────────────────────────────────

STATUS_SUCCESS = "success"
"""Dispatched and returned a non-empty result."""

STATUS_EMPTY = "empty"
"""Dispatched and returned nothing usable (the agent had no data to give)."""

STATUS_FAILED = "failed"
"""Dispatched and errored. The error text is evidence about the run, not about
the question, so it is kept on the outcome and excluded from synthesis."""

STATUS_BLOCKED = "blocked"
"""Never dispatched — a budget, routing, or scope condition stopped it."""

TERMINAL_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_EMPTY, STATUS_FAILED, STATUS_BLOCKED}
)

DISPATCHED_STATUSES = frozenset({STATUS_SUCCESS, STATUS_EMPTY, STATUS_FAILED})

# ── Stages ──────────────────────────────────────────────────────────────────

STAGE_LOCAL = "local"
"""Executed in-process during pre-execution."""

STAGE_PRE_EXEC = "pre_exec"
"""Delegated to a peer during pre-execution."""

STAGE_MID_EXEC = "mid_exec"
"""Delegated to a peer during a mid-execution round."""

STAGE_MID_EXEC_SELF = "mid_exec_self"
"""Executed in-process during a mid-execution round."""

REMOTE_STAGES = frozenset({STAGE_PRE_EXEC, STAGE_MID_EXEC})
"""Stages whose results belong in the delegated-results view. Local work is
this agent's own output and must not also be presented as a peer's answer."""

# Prefixes the delegation and local-execution paths use for error returns.
# A transport or executor failure must never be mistaken for domain evidence.
DEFAULT_FAILURE_PREFIXES = ("Delegation failed:", "Execution error:")

# ── Blocked reason codes ────────────────────────────────────────────────────

REASON_HOP_EXHAUSTED = "hop_exhausted"
REASON_NO_AGENT_CARD = "no_agent_card"
REASON_NOT_IN_SCOPE = "not_in_scope"
REASON_CANCELLED = "cancelled"
REASON_DEPENDENCY_UNMET = "dependency_unmet"
REASON_UPSTREAM_INVALID = "upstream_invalid"

# ── Cross-turn task identity ────────────────────────────────────────────────

TURN_KEY_STRIDE = 100000
"""Each turn's planner numbers its tasks from 1, so turn 2 task #1 would
overwrite turn 1 task #1 in any dict keyed by the raw task id."""

ROUND_KEY_STRIDE = 1000
"""Mid-execution rounds re-number from 1 as well, so the round must take part
in the key or a mid-exec task collides with a pre-exec task in the same turn.
Assumes fewer than ``ROUND_KEY_STRIDE`` tasks per round, which the planner
budgets enforce."""


def turn_scoped_id(task_id: int, turn: int = 1, round_index: int = 0) -> int:
    """A task id that stays unique across turns and mid-exec rounds.

    Turn 1 pre-execution keeps its natural ids so existing single-turn logs and
    fixtures are unchanged.
    """
    if turn <= 1 and round_index <= 0:
        return int(task_id)
    return (
        int(turn) * TURN_KEY_STRIDE
        + int(round_index) * ROUND_KEY_STRIDE
        + int(task_id)
    )


@dataclass(frozen=True)
class TaskOutcome:
    """One terminal outcome for one planned task."""

    task_id: int
    agent: str
    status: str
    result: str = ""
    reason_code: str = ""
    stage: str = ""
    round_index: int = 0
    turn: int = 1
    error: str = ""

    @property
    def usable(self) -> bool:
        """Whether this outcome carries content worth sending to synthesis."""
        return self.status == STATUS_SUCCESS and bool((self.result or "").strip())

    @property
    def dispatched(self) -> bool:
        """Whether the agent was actually asked to do the work."""
        return self.status in DISPATCHED_STATUSES

    @property
    def scoped_task_id(self) -> int:
        return turn_scoped_id(self.task_id, self.turn, self.round_index)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "scoped_task_id": self.scoped_task_id,
            "turn": self.turn,
            "agent": self.agent,
            "status": self.status,
            "reason_code": self.reason_code,
            "stage": self.stage,
            "round_index": self.round_index,
            "result_chars": len(self.result or ""),
            "error": self.error[:200],
        }


def _is_placeholder(text: str, placeholders: Iterable[str]) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    return any(stripped == (p or "").strip() for p in placeholders if p)


def is_execution_error(
    text: str, prefixes: Iterable[str] = DEFAULT_FAILURE_PREFIXES
) -> bool:
    """Whether *text* is an execution error rather than an answer."""
    return bool(_failure_prefix(text, prefixes))


def _failure_prefix(text: str, prefixes: Iterable[str]) -> str:
    stripped = (text or "").strip()
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            return prefix
    return ""


@dataclass
class DispatchLedger:
    """Append-only record of every planned task's terminal outcome.

    ``placeholders`` are strings that mean "no result" even though they are
    non-empty text, such as the legacy ``No available agent can do this task.``
    marker. They are recorded as :data:`STATUS_EMPTY`, never as content.
    """

    placeholders: tuple[str, ...] = ()
    failure_prefixes: tuple[str, ...] = DEFAULT_FAILURE_PREFIXES
    _outcomes: list[TaskOutcome] = field(default_factory=list)

    # ── Recording ───────────────────────────────────────────────────────────

    def record_result(
        self,
        *,
        task_id: int,
        agent: str,
        result: str,
        stage: str,
        round_index: int = 0,
        turn: int = 1,
    ) -> TaskOutcome:
        """Record a dispatched task's return value.

        Three outcomes are distinguished because they mean different things
        downstream: content to synthesize, a genuine "I have nothing", and an
        execution error that must not be quoted back to the user as evidence.
        """
        failure = _failure_prefix(result, self.failure_prefixes)
        if failure:
            status, content, error = STATUS_FAILED, "", (result or "").strip()
        elif _is_placeholder(result, self.placeholders):
            status, content, error = STATUS_EMPTY, "", ""
        else:
            status, content, error = STATUS_SUCCESS, (result or ""), ""

        outcome = TaskOutcome(
            task_id=int(task_id),
            agent=(agent or "").strip(),
            status=status,
            result=content,
            reason_code=failure.rstrip(":").lower().replace(" ", "_") if failure else "",
            stage=stage,
            round_index=int(round_index),
            turn=int(turn),
            error=error,
        )
        self._outcomes.append(outcome)
        return outcome

    def record_blocked(
        self,
        *,
        task_id: int,
        agent: str,
        reason_code: str,
        stage: str,
        round_index: int = 0,
        turn: int = 1,
        detail: str = "",
    ) -> TaskOutcome:
        """Record a task that reached a terminal state without being dispatched."""
        outcome = TaskOutcome(
            task_id=int(task_id),
            agent=(agent or "").strip(),
            status=STATUS_BLOCKED,
            reason_code=reason_code,
            stage=stage,
            round_index=int(round_index),
            turn=int(turn),
            error=detail,
        )
        self._outcomes.append(outcome)
        return outcome

    # ── Queries ─────────────────────────────────────────────────────────────

    def outcomes(
        self,
        *,
        round_index: Optional[int] = None,
        turn: Optional[int] = None,
        stages: Optional[Iterable[str]] = None,
    ) -> list[TaskOutcome]:
        """Filtered view of recorded outcomes.

        ``turn`` matters because one ledger now spans the whole run: filtering
        by ``round_index`` alone would mix turn 1's round 1 with turn 2's
        round 1, since each turn re-numbers its rounds.
        """
        stage_set = frozenset(stages) if stages is not None else None
        return [
            o
            for o in self._outcomes
            if (round_index is None or o.round_index == round_index)
            and (turn is None or o.turn == turn)
            and (stage_set is None or o.stage in stage_set)
        ]

    def blocked(self, **filters) -> list[TaskOutcome]:
        return [o for o in self.outcomes(**filters) if o.status == STATUS_BLOCKED]

    def failed(self, **filters) -> list[TaskOutcome]:
        return [o for o in self.outcomes(**filters) if o.status == STATUS_FAILED]

    def usable(self, **filters) -> list[TaskOutcome]:
        return [o for o in self.outcomes(**filters) if o.usable]

    def results_by_agent(
        self, *, stages: Optional[Iterable[str]] = REMOTE_STAGES
    ) -> dict[str, str]:
        """Agent-keyed view of *delegated* results for existing consumers.

        Every usable result is preserved. When one agent produced results for
        several tasks they are concatenated in dispatch order under task
        headers rather than one replacing the other.

        Only remote stages are included by default: local execution is this
        agent's own work, and presenting it as a peer's contribution would
        double-count the same evidence. Pass ``stages=None`` for every stage.
        """
        stage_set = frozenset(stages) if stages is not None else None
        ordered: dict[str, list[TaskOutcome]] = {}
        for outcome in self._outcomes:
            if not outcome.usable or not outcome.agent:
                continue
            if stage_set is not None and outcome.stage not in stage_set:
                continue
            ordered.setdefault(outcome.agent, []).append(outcome)

        merged: dict[str, str] = {}
        for agent, items in ordered.items():
            if len(items) == 1:
                merged[agent] = items[0].result
                continue
            merged[agent] = "\n\n".join(
                f"[Task #{item.task_id}] {item.result}"
                if item.turn <= 1
                else f"[Turn {item.turn} Task #{item.task_id}] {item.result}"
                for item in items
            )
        return merged

    def task_results_by_scoped_id(self) -> dict[int, str]:
        """Task-keyed view that stays unique across turns.

        Turn 2's task #1 does not replace turn 1's task #1.
        """
        results: dict[int, str] = {}
        for outcome in self._outcomes:
            if outcome.usable:
                results[outcome.scoped_task_id] = outcome.result
        return results

    def agents_without_usable_result(
        self,
        *,
        round_index: Optional[int] = None,
        turn: Optional[int] = None,
    ) -> set[str]:
        """Agents that were dispatched in this scope and returned nothing.

        Scope by ``turn`` as well as ``round_index``: the ledger spans the run,
        so a success in turn 1 round 1 would otherwise mask a failure in turn 2
        round 1 and the agent would never be marked exhausted.

        A task blocked before dispatch does not count: the agent was never
        asked, so it has not demonstrated that it has nothing to contribute and
        must not be excluded from later rounds.
        """
        scoped = self.outcomes(round_index=round_index, turn=turn)
        dispatched = {o.agent for o in scoped if o.dispatched}
        produced = {o.agent for o in scoped if o.usable}
        return {a for a in (dispatched - produced) if a}

    def summary(self) -> dict:
        """Counts for one log line / progress payload."""
        counts: dict[str, int] = {}
        for outcome in self._outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        return {
            "tasks": len(self._outcomes),
            "success": counts.get(STATUS_SUCCESS, 0),
            "empty": counts.get(STATUS_EMPTY, 0),
            "failed": counts.get(STATUS_FAILED, 0),
            "blocked": counts.get(STATUS_BLOCKED, 0),
            "result_chars": sum(len(o.result or "") for o in self._outcomes),
        }
