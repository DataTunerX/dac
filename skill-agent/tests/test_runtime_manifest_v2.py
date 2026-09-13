from __future__ import annotations

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
from agent_contracts import SchemaDescriptor  # noqa: E402

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


def test_direct_registration_removes_stale_name_alias() -> None:
    registry = object.__new__(RedisRegistry)
    registry.registry_key = "expert_agents"
    registry.heartbeat_key = "agent_heartbeats"
    registry.runtime_status_key = "agent_runtime_status:v2"
    registry.alias_key = "agent_aliases:v2"
    registry.aliases_by_id_key = "agent_aliases_by_id:v2"
    registry.redis = MagicMock()
    registry.redis.hget.side_effect = lambda key, field: {
        (registry.alias_key, "old-agent"): "http://museum.default:10100",
        (
            registry.aliases_by_id_key,
            "http://museum.default:10100",
        ): json.dumps(["Old-Agent"]),
    }.get((key, field))
    pipe = MagicMock()
    pipe.execute.return_value = [1, 1, 1, 1, 1, 1]
    registry.redis.pipeline.return_value = pipe
    card = _card()
    card.name = "New-Agent"

    assert registry.register_agent(card) is True
    pipe.hdel.assert_called_once_with(registry.alias_key, "old-agent")
    pipe.hset.assert_any_call(
        registry.alias_key,
        "new-agent",
        "http://museum.default:10100",
    )
