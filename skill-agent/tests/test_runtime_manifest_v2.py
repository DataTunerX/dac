from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT.parent / "agent-contracts"
for path in (ROOT, CONTRACTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from a2a.types import AgentCard  # noqa: E402
from agent_contracts import (  # noqa: E402
    PROTOCOL_VERSION,
    ExpectedOutput,
    ParticipantConstraints,
    ParticipantTask,
    SchemaDescriptor,
    core_schema_registry,
)

from agent.redis_registry import RedisRegistry  # noqa: E402
from agent.skill_agent import SkillAgentExecutor  # noqa: E402


def _executor(tmp_path: Path) -> SkillAgentExecutor:
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
    }
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "lookup.json").write_text(json.dumps(schema))
    (tmp_path / "_meta.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "output_schemas": [
                    {
                        "schema_id": "museum.lookup/v1",
                        "path": "schemas/lookup.json",
                    }
                ],
            }
        )
    )
    skill = SimpleNamespace(
        name="museum-lookup",
        version="1.0.0",
        description="lookup",
        base_dir=str(tmp_path),
    )
    executor = object.__new__(SkillAgentExecutor)
    executor._skill_runner = SimpleNamespace(
        lister=SimpleNamespace(skills=[skill]),
        _runner_tools=[SimpleNamespace(name="tdb_query")],
    )
    return executor


def _card() -> AgentCard:
    return AgentCard(
        name="Museum-Agent",
        description="museum",
        url="http://museum.default:10100",
        version="1.0.0",
        capabilities={"streaming": True},
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        skills=[],
    )


def test_only_exact_registry_schema_is_advertised(tmp_path, monkeypatch) -> None:
    executor = _executor(tmp_path)
    declared = executor.get_declared_output_schemas()
    descriptor = declared["museum-lookup"][0]

    monkeypatch.setattr(
        "agent.skill_agent.AgentRegistryClient.resolve_schema",
        lambda _self, _schema_id: descriptor.model_dump(by_alias=True),
    )
    registered = executor.resolve_registered_output_schemas()
    assert registered["museum-lookup"][0].schema_digest == descriptor.schema_digest

    _description, skills = executor.build_dynamic_agent_card_fields(registered)
    assert any(
        tag.startswith("output-schema:museum.lookup/v1@sha256:")
        for tag in skills[0].tags
    )


def test_digest_mismatch_is_not_advertised(tmp_path, monkeypatch) -> None:
    executor = _executor(tmp_path)
    other = SchemaDescriptor(
        schema_id="museum.lookup/v1",
        owner="other",
        schema={"type": "string"},
    )
    monkeypatch.setattr(
        "agent.skill_agent.AgentRegistryClient.resolve_schema",
        lambda _self, _schema_id: other.model_dump(by_alias=True),
    )
    assert executor.resolve_registered_output_schemas() == {}


def test_runtime_status_is_truthful_until_model_health_exists(
    tmp_path, monkeypatch
) -> None:
    executor = _executor(tmp_path)
    descriptor = executor.get_declared_output_schemas()["museum-lookup"][0]
    monkeypatch.setattr(
        "agent.skill_agent.AgentRegistryClient.resolve_schema",
        lambda _self, _schema_id: descriptor.model_dump(by_alias=True),
    )
    registered = executor.resolve_registered_output_schemas()
    status = executor.build_runtime_status(
        _card(), readiness_generation=3, registered_schemas=registered
    )
    assert status.agent_id == "http://museum.default:10100"
    assert status.agent_id == status.agent_url
    assert status.skills_state == "ready"
    assert status.tools_state == "ready"
    assert status.model_state == "unknown"
    assert status.agent_ready == "degraded"
    assert status.readiness_generation == 3
    assert status.registered_output_schemas[0].schema_id == "museum.lookup/v1"


def test_direct_registration_leaves_aliases_to_registry_service() -> None:
    registry = object.__new__(RedisRegistry)
    registry.registry_key = "expert_agents"
    registry.heartbeat_key = "agent_heartbeats"
    registry.runtime_status_key = "agent_runtime_status:v2"
    registry.redis = MagicMock()
    pipe = MagicMock()
    pipe.execute.return_value = [1, 1, 1]
    registry.redis.pipeline.return_value = pipe
    card = _card()
    card.name = "New-Agent"

    assert registry.register_agent(card) is True
    pipe.hset.assert_called_once_with(
        registry.registry_key,
        "http://museum.default:10100",
        card.model_dump_json(),
    )
    pipe.hdel.assert_not_called()


def _participant_task(schema_id: str, *, deadline_ms: int = 1000) -> ParticipantTask:
    return ParticipantTask(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id="collab-cache",
        task_id="task-cache",
        objective="return one cached result",
        operation="lookup",
        expected_outputs=[ExpectedOutput(name="result", schema_id=schema_id)],
        constraints=ParticipantConstraints(deadline_ms=deadline_ms),
    )


def test_participant_schema_resolution_is_cached(monkeypatch) -> None:
    executor = object.__new__(SkillAgentExecutor)
    executor._participant_schema_registry = core_schema_registry()
    executor._participant_schema_lock = asyncio.Lock()
    descriptor = SchemaDescriptor(
        schema_id="museum.cached/v1",
        owner="tests",
        schema={"type": "object"},
    )
    calls = 0

    async def resolve_schema(_client, _schema_id):
        nonlocal calls
        calls += 1
        return descriptor.model_dump(by_alias=True)

    monkeypatch.setattr(
        "agent.skill_agent.AgentRegistryClient.aresolve_schema", resolve_schema
    )

    async def resolve_twice() -> None:
        task = _participant_task(descriptor.schema_id)
        first, first_missing = await executor._resolve_participant_schemas(task)
        second, second_missing = await executor._resolve_participant_schemas(task)
        assert first is second
        assert first_missing == second_missing == []

    asyncio.run(resolve_twice())
    assert calls == 1


def test_schema_fetch_is_bounded_by_participant_deadline() -> None:
    executor = object.__new__(SkillAgentExecutor)
    executor.agent_id = "Fixture-Agent"
    executor.agent_card = None

    async def runner():
        return object()

    async def slow_schema_fetch(_task):
        await asyncio.sleep(1)
        return core_schema_registry(), []

    async def progress(*_args, **_kwargs):
        return None

    executor._ensure_skill_runner = runner
    executor._resolve_participant_schemas = slow_schema_fetch
    task = _participant_task("museum.slow/v1", deadline_ms=5)
    result = asyncio.run(
        executor._execute_participant_contract(
            task,
            user_id="test-user",
            progress_callback=progress,
        )
    )
    assert result.status == "failed"
    assert result.error.code == "deadline_exceeded"
