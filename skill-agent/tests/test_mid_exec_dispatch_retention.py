"""Phase 0.5 golden cases against the real ``_dispatch_mid_exec_delegation``.

Replays the observed `fw-worker` mid-exec round of 2026-09-11: a plan with
three tasks all assigned to one agent, dispatched with ``current_hop=2`` so
only the first can run.

Run::

    cd /path/to/dac/skill-agent
    python -m pytest tests/test_mid_exec_dispatch_retention.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod in (
    "skill_sdk", "skill_sdk.skill", "skill_sdk.skill.runner",
    "skill_sdk.tool", "skill_sdk.tool.code_execution",
    "langfuse", "langfuse.langchain", "langfuse._client",
    "model_sdk", "model_sdk.api", "model_sdk.api.model_manager",
    "agent.broadcast_capability_check", "agent.agent_card_resolve",
    "agent.agentregistry_client", "agent.dataservices_client",
    "agent.tool_call_utils",
):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules["agent.broadcast_capability_check"].ROUTING_AGENT_POOL_KEY = "routing_agent_pool"

from agent.skill_agent import (  # noqa: E402
    NONE_TASK_DESCRIPTION,
    PlannerTask,
    SkillAgentExecutor,
    TaskList,
)
from agent.task_results import (  # noqa: E402
    REASON_HOP_EXHAUSTED,
    REASON_NO_AGENT_CARD,
    DispatchLedger,
)

AGENT = "Paper-Answering-TDB-Agent"
REAL_RESULT = "x" * 3104


class _CapturingUpdater:
    """Collects the progress frames the executor emits."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def add_artifact(self, parts, name: str = "") -> None:
        for part in parts:
            text = getattr(part, "text", "") or getattr(getattr(part, "root", None), "text", "")
            for line in str(text).splitlines():
                _, _, payload = line.partition("]] ")
                if payload:
                    try:
                        self.frames.append(json.loads(payload))
                    except json.JSONDecodeError:
                        pass

    def events(self, event: str) -> list[dict]:
        return [f for f in self.frames if f.get("event") == event]


def _executor(delegate_result: str = REAL_RESULT) -> SkillAgentExecutor:
    inst = object.__new__(SkillAgentExecutor)
    object.__setattr__(inst, "_progress_context", {
        "run_id": "run-1", "user_id": "user-1", "agent_id": "Art-history-TDB-Agent",
    })
    object.__setattr__(inst, "agent_card", MagicMock(name="Art-history-TDB-Agent"))
    inst._self_planner_agent_name = lambda: "Art-history-TDB-Agent"  # type: ignore[method-assign]
    inst._delegate_to_peer = AsyncMock(return_value=delegate_result)  # type: ignore[method-assign]
    return inst


def _plan(agents: list[str]) -> TaskList:
    return TaskList(
        original_query="q",
        tasks=[
            PlannerTask(id=i + 1, description=f"task {i + 1}", agent=agent)
            for i, agent in enumerate(agents)
        ],
    )


def _card(name: str) -> MagicMock:
    card = MagicMock()
    card.name = name
    return card


async def _dispatch(executor, plan, cards, *, hop: int, ledger=None, updater=None, turn: int = 1):
    return await executor._dispatch_mid_exec_delegation(
        plan=plan,
        target_cards=cards,
        user_id="user-1",
        run_id="run-1",
        trace_id="trace-1",
        current_hop=hop,
        delegation_chain=[],
        upstream_context={"mid_exec_round": 1},
        updater=updater,
        ledger=ledger,
        turn=turn,
    )


@pytest.mark.asyncio
async def test_blocked_siblings_do_not_destroy_the_completed_result():
    """The observed defect: 3104 chars replaced by a 37-char placeholder."""
    executor = _executor()
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    delegate_results, _self_results, remaining_hop = await _dispatch(
        executor, _plan([AGENT, AGENT, AGENT]), [_card(AGENT)], hop=2, ledger=ledger
    )

    # Exactly one dispatch was affordable.
    assert executor._delegate_to_peer.await_count == 1
    assert remaining_hop == 1

    # The result survives at full length, and no placeholder reaches synthesis.
    assert delegate_results[AGENT] == REAL_RESULT
    assert len(delegate_results[AGENT]) == 3104
    assert NONE_TASK_DESCRIPTION not in delegate_results[AGENT]

    # All three tasks reach a terminal state.
    assert {o.task_id for o in ledger.outcomes()} == {1, 2, 3}
    assert [o.reason_code for o in ledger.blocked()] == [
        REASON_HOP_EXHAUSTED,
        REASON_HOP_EXHAUSTED,
    ]


@pytest.mark.asyncio
async def test_blocked_tasks_emit_progress_events():
    executor = _executor()
    updater = _CapturingUpdater()

    await _dispatch(
        executor, _plan([AGENT, AGENT, AGENT]), [_card(AGENT)],
        hop=2, ledger=DispatchLedger(), updater=updater,
    )

    blocked = updater.events("mid_exec_task_blocked")
    assert len(blocked) == 2
    assert [f["task_id"] for f in blocked] == [2, 3]
    for frame in blocked:
        assert frame["status"] == "blocked"
        assert frame["extra"]["reason_code"] == REASON_HOP_EXHAUSTED
        assert frame["extra"]["dispatched"] is False


@pytest.mark.asyncio
async def test_task_for_unscoped_agent_is_recorded_and_reported():
    executor = _executor()
    updater = _CapturingUpdater()
    ledger = DispatchLedger()

    await _dispatch(
        executor, _plan(["Unknown-Agent"]), [_card(AGENT)],
        hop=5, ledger=ledger, updater=updater,
    )

    assert [o.reason_code for o in ledger.blocked()] == [REASON_NO_AGENT_CARD]
    assert updater.events("mid_exec_task_blocked")[0]["extra"]["reason_code"] == (
        REASON_NO_AGENT_CARD
    )


@pytest.mark.asyncio
async def test_two_dispatched_tasks_to_one_agent_both_survive():
    executor = _executor()
    executor._delegate_to_peer = AsyncMock(side_effect=["first result", "second result"])
    ledger = DispatchLedger()

    delegate_results, _self, _hop = await _dispatch(
        executor, _plan([AGENT, AGENT]), [_card(AGENT)], hop=5, ledger=ledger
    )

    assert "first result" in delegate_results[AGENT]
    assert "second result" in delegate_results[AGENT]


@pytest.mark.asyncio
async def test_empty_result_marks_agent_without_usable_result():
    executor = _executor(delegate_result="")
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    delegate_results, _self, _hop = await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=5, ledger=ledger
    )

    assert AGENT not in delegate_results
    assert ledger.agents_without_usable_result(round_index=1) == {AGENT}


@pytest.mark.asyncio
async def test_mid_exec_self_result_reaches_the_run_ledger():
    """Self-executed mid-exec work must survive to final synthesis."""
    executor = _executor()
    executor._execute_mid_exec_self_task = AsyncMock(return_value="self finding")
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))
    runner = MagicMock()

    _delegate, self_results, _hop = await executor._dispatch_mid_exec_delegation(
        plan=_plan(["Art-history-TDB-Agent"]),
        target_cards=[_card("Art-history-TDB-Agent")],
        user_id="u", run_id="r", trace_id="t",
        current_hop=5,
        delegation_chain=[],
        upstream_context={"mid_exec_round": 1},
        updater=None,
        ledger=ledger,
        skill_runner=runner,
        turn=1,
    )

    assert self_results["Art-history-TDB-Agent"] == "self finding"
    # Present as task evidence…
    assert "self finding" in ledger.task_results_by_scoped_id().values()
    # …but not attributed to a peer agent.
    assert ledger.results_by_agent() == {}


@pytest.mark.asyncio
async def test_turn_two_does_not_overwrite_turn_one():
    """Generated agents run two turns, each numbering its tasks from 1."""
    executor = _executor()
    run_ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    executor._delegate_to_peer = AsyncMock(return_value="turn one evidence")
    await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=5, ledger=run_ledger, turn=1
    )

    executor._delegate_to_peer = AsyncMock(return_value="turn two evidence")
    await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=5, ledger=run_ledger, turn=2
    )

    merged = run_ledger.results_by_agent()[AGENT]
    assert "turn one evidence" in merged
    assert "turn two evidence" in merged
    assert len(run_ledger.task_results_by_scoped_id()) == 2


@pytest.mark.asyncio
async def test_turn_two_block_does_not_erase_turn_one_result():
    executor = _executor()
    run_ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=5, ledger=run_ledger, turn=1
    )
    # Turn 2 plans the same task number but the budget is gone.
    await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=1, ledger=run_ledger, turn=2
    )

    assert run_ledger.results_by_agent()[AGENT] == REAL_RESULT


@pytest.mark.asyncio
async def test_delegation_error_is_not_forwarded_as_evidence():
    """`_delegate_to_peer` returns "Delegation failed: ..." on exception."""
    executor = _executor(delegate_result="Delegation failed: ReadTimeout()")
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    delegate_results, _self, _hop = await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=5, ledger=ledger
    )

    assert AGENT not in delegate_results
    assert len(ledger.failed()) == 1
    assert "ReadTimeout" in ledger.failed()[0].error
    assert ledger.agents_without_usable_result(round_index=1) == {AGENT}


@pytest.mark.asyncio
async def test_delegation_error_does_not_erase_a_sibling_result():
    executor = _executor()
    executor._delegate_to_peer = AsyncMock(
        side_effect=["real evidence", "Delegation failed: boom"]
    )
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    delegate_results, _self, _hop = await _dispatch(
        executor, _plan([AGENT, AGENT]), [_card(AGENT)], hop=5, ledger=ledger
    )

    assert delegate_results[AGENT] == "real evidence"


@pytest.mark.asyncio
async def test_hop_exhausted_agent_is_not_marked_without_usable_result():
    """A blocked agent must stay eligible for later rounds."""
    executor = _executor()
    ledger = DispatchLedger(placeholders=(NONE_TASK_DESCRIPTION,))

    await _dispatch(
        executor, _plan([AGENT]), [_card(AGENT)], hop=1, ledger=ledger
    )

    assert executor._delegate_to_peer.await_count == 0
    assert ledger.agents_without_usable_result(round_index=1) == set()
