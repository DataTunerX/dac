from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT.parent / "agent-contracts"
for path in (ROOT, CONTRACTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_contracts import (  # noqa: E402
    PROTOCOL_VERSION,
    ExpectedOutput,
    ParticipantConstraints,
    ParticipantTask,
    SchemaDescriptor,
    SchemaRegistry,
)

from agent.local_task_executor import LocalTaskExecutor  # noqa: E402
from agent.participant_executor import ParticipantExecutor  # noqa: E402


@dataclass
class _Skill:
    name: str


class _Lister:
    def __init__(self, skills: list[str]) -> None:
        self.skills = [_Skill(name) for name in skills]

    def find_by_name(self, name: str, **_kwargs):
        return [skill for skill in self.skills if skill.name.lower() == name.lower()]


class _Runner:
    def __init__(self, result: dict, *, delay: float = 0) -> None:
        self.result = result
        self.delay = delay
        self.max_steps = 20
        self.lister = _Lister(["fixture-skill"])
        self._runner_tools = [
            SimpleNamespace(name="tdb_query"),
            SimpleNamespace(name="tavily_search"),
        ]
        self.observations: list[list[str]] = []
        self.tools_seen: list[str] = []
        self.queries: list[str] = []

    async def plan_and_run(self, *, query: str, **_kwargs):
        await asyncio.sleep(self.delay)
        self.queries.append(query)
        self.tools_seen = [tool.name for tool in self._runner_tools]
        self.observations.append(self.tools_seen)
        return self.result

    async def run(self, query: str, _skill: _Skill, **_kwargs):
        await asyncio.sleep(self.delay)
        self.queries.append(query)
        self.tools_seen = [tool.name for tool in self._runner_tools]
        self.observations.append(self.tools_seen)
        return self.result


def _registry() -> SchemaRegistry:
    return SchemaRegistry(
        [
            SchemaDescriptor(
                schema_id="test.fixture/v1",
                owner="tests",
                schema={
                    "type": "object",
                    "required": ["kind", "value"],
                    "properties": {
                        "kind": {"type": "string", "minLength": 1},
                        "value": {},
                    },
                    "additionalProperties": False,
                },
            )
        ]
    )


def _task(kind: str, **constraint_overrides) -> ParticipantTask:
    constraints = ParticipantConstraints(**constraint_overrides)
    return ParticipantTask(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id="collab-fixture",
        task_id=f"task-{kind}",
        objective=f"Perform deterministic {kind} work.",
        operation=kind,
        inputs={"kind": kind, "records": [1, 2, 3]},
        expected_outputs=[ExpectedOutput(name="result", schema_id="test.fixture/v1")],
        constraints=constraints,
    )


def _execute(runner: _Runner, task: ParticipantTask):
    local = LocalTaskExecutor(
        skill_runner=runner,
        agent_name="Fixture-Agent",
        schema_registry=_registry(),
    )
    return asyncio.run(ParticipantExecutor(local).execute(task))


@pytest.mark.parametrize(
    "kind,value",
    [
        ("lookup", {"id": "item-42"}),
        ("tdb-query", [{"source_id": "tdb:1", "predicate": "made_of"}]),
        ("summarization", "three records summarized"),
        ("extraction", {"fields": ["source_id", "char_span"]}),
        ("transformation", [3, 2, 1]),
    ],
)
def test_participant_completes_generic_local_fixtures(kind: str, value) -> None:
    runner = _Runner(
        {
            "status": "completed",
            "skill": "fixture-skill",
            "final_answer": json.dumps({"result": {"kind": kind, "value": value}}),
            "tool_history": [{"tool": "tdb_query"}],
        }
    )
    result = _execute(runner, _task(kind))
    assert result.status == "success"
    assert result.outputs[0].data == {"kind": kind, "value": value}
    assert result.metrics.tool_calls == 1
    assert result.metrics.attempted_skills == ["fixture-skill"]
    assert result.outputs[0].schema_digest.startswith("sha256:")
    assert "Do not delegate" in runner.queries[0]


def test_participant_preserves_best_draft_as_partial() -> None:
    runner = _Runner(
        {
            "status": "max_steps_reached",
            "skill": "fixture-skill",
            "final_answer": json.dumps(
                {"result": {"kind": "summarization", "value": "useful draft"}}
            ),
            "tool_history": [],
        }
    )
    result = _execute(runner, _task("summarization"))
    assert result.status == "partial"
    assert result.outputs[0].data["value"] == "useful draft"
    assert result.limitations


def test_invalid_structured_output_is_retained_and_marked_partial() -> None:
    runner = _Runner(
        {
            "status": "completed",
            "skill": "fixture-skill",
            "final_answer": json.dumps({"result": {"kind": "lookup"}}),
            "tool_history": [],
        }
    )
    result = _execute(runner, _task("lookup"))
    assert result.status == "partial"
    assert result.outputs[0].data == {"kind": "lookup"}
    assert any("invalid_output_data" in item for item in result.invalid_outputs)


def test_fenced_json_is_parsed() -> None:
    runner = _Runner(
        {
            "status": "completed",
            "skill": "fixture-skill",
            "final_answer": "```json\n"
            + json.dumps({"result": {"kind": "lookup", "value": "ok"}})
            + "\n```",
            "tool_history": [],
        }
    )
    result = _execute(runner, _task("lookup"))
    assert result.status == "success"
    assert result.outputs[0].data["value"] == "ok"


def test_unstructured_multi_output_draft_is_preserved() -> None:
    runner = _Runner(
        {
            "status": "max_steps_reached",
            "skill": "fixture-skill",
            "final_answer": "Useful evidence that did not reach the requested JSON shape.",
            "tool_history": [],
        }
    )
    task = _task("extraction")
    task.expected_outputs.append(
        ExpectedOutput(name="second", schema_id="test.fixture/v1")
    )
    result = _execute(runner, task)
    assert result.status == "partial"
    assert result.best_draft.startswith("Useful evidence")


def test_missing_required_skill_returns_blocked() -> None:
    runner = _Runner({"status": "completed", "final_answer": "not called"})
    result = _execute(
        runner,
        _task("lookup", required_skill="not-installed"),
    )
    assert result.status == "blocked"
    assert result.error.code == "skill_not_found"
    assert result.missing_capabilities == ["not-installed"]
    assert runner.queries == []


def test_deadline_is_propagated_to_local_execution() -> None:
    runner = _Runner(
        {"status": "completed", "final_answer": "too late"},
        delay=0.05,
    )
    result = _execute(runner, _task("lookup", deadline_ms=5))
    assert result.status == "failed"
    assert result.error.code == "deadline_exceeded"
    assert result.retryable is True


def test_unavailable_tool_is_removed_from_runtime_and_execution(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    runner = _Runner(
        {
            "status": "completed",
            "skill": "fixture-skill",
            "final_answer": json.dumps({"result": {"kind": "lookup", "value": "done"}}),
            "tool_history": [],
        }
    )
    ready, unavailable = LocalTaskExecutor.runtime_tool_inventory(runner)
    assert ready == ["tdb_query"]
    assert unavailable == ["tavily_search"]
    _execute(runner, _task("lookup"))
    assert runner.observations == [["tdb_query"]]


def test_participant_module_has_no_remote_collaboration_dependency() -> None:
    source = (ROOT / "agent" / "participant_executor.py").read_text(encoding="utf-8")
    source += (ROOT / "agent" / "local_task_executor.py").read_text(encoding="utf-8")
    for forbidden in (
        "AgentRegistryClient",
        "broadcast_capability_check",
        "A2AClient",
        "send_message_streaming",
        "delegate_to_agent",
    ):
        assert forbidden not in source


def test_both_server_executors_dispatch_participant_before_capability_paths() -> None:
    base = (ROOT / "agent" / "skill_agent.py").read_text(encoding="utf-8")
    turns = (ROOT / "agent" / "skill_agent_turn.py").read_text(encoding="utf-8")
    for source in (base, turns):
        participant = source.index('metadata.get("execution_mode") == "participant"')
        capability = source.index("handle_capability_check", participant)
        assert participant < capability
