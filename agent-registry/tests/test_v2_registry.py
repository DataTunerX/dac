from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_contracts import (  # noqa: E402
    PROTOCOL_VERSION,
    AgentRuntimeStatus,
    HealthState,
    IndexState,
    SchemaConflictError,
    SchemaDescriptor,
)

from agent_registry.redis_registry import RedisRegistry  # noqa: E402
from agent_registry.server import (  # noqa: E402
    create_fastapi_app,
    sync_existing_agents_to_vector_db,
)


def _registry() -> RedisRegistry:
    registry = object.__new__(RedisRegistry)
    registry.registry_key = "expert_agents"
    registry.heartbeat_key = "agent_heartbeats"
    registry.runtime_status_key = "agent_runtime_status:v2"
    registry.index_status_key = "agent_index_status:v2"
    registry.index_generation_key = "agent_index_generation:v2"
    registry.schema_registry_key = "agent_output_schemas:v2"
    registry.alias_key = "agent_aliases:v2"
    registry.aliases_by_id_key = "agent_aliases_by_id:v2"
    registry.alias_conflicts_key = "agent_alias_conflicts:v2"
    registry.lock = threading.RLock()
    registry.agents = []
    registry.redis = MagicMock()
    return registry


def _install_hash(registry: RedisRegistry) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}

    def hsetnx(key, field, value):
        pair = (key, field)
        if pair in values:
            return 0
        values[pair] = value
        return 1

    def hset(key, field, value):
        values[(key, field)] = value
        return 1

    registry.redis.hsetnx.side_effect = hsetnx
    registry.redis.hset.side_effect = hset
    registry.redis.hget.side_effect = lambda key, field: values.get((key, field))
    registry.redis.hvals.side_effect = lambda key: [
        value for (stored_key, _), value in values.items() if stored_key == key
    ]
    return values


def _card(url: str = "http://museum.default:10100"):
    payload = {
        "name": "Museum-Agent",
        "description": "Museum records",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [],
    }
    return SimpleNamespace(
        name=payload["name"],
        url=url,
        model_dump=lambda **_kwargs: payload,
    )


def test_schema_registration_is_atomic_and_immutable() -> None:
    registry = _registry()
    _install_hash(registry)
    first = SchemaDescriptor(
        schema_id="museum.record/v1",
        owner="skill:museum",
        schema={"type": "object", "required": ["id"]},
    )
    registry.register_schema(first)
    assert registry.register_schema(first).schema_digest == first.schema_digest
    with pytest.raises(SchemaConflictError):
        registry.register_schema(
            SchemaDescriptor(
                schema_id="museum.record/v1",
                owner="skill:museum",
                schema={"type": "string"},
            )
        )


def test_registry_derives_case_insensitive_aliases_atomically() -> None:
    registry = _registry()
    registry.agents = [_card()]
    pipe = MagicMock()
    registry.redis.pipeline.return_value = pipe
    registry._reconcile_aliases()

    pipe.execute.assert_called_once()
    pipe.delete.assert_called_once_with(
        registry.alias_key,
        registry.aliases_by_id_key,
        registry.alias_conflicts_key,
    )
    pipe.hset.assert_any_call(
        registry.alias_key, "museum-agent", "http://museum.default:10100"
    )


def test_registry_keeps_conflicting_cards_and_marks_alias_ambiguous() -> None:
    registry = _registry()
    registry.agents = [_card("http://museum-a"), _card("http://museum-b")]
    pipe = MagicMock()
    registry.redis.pipeline.return_value = pipe

    registry._reconcile_aliases()

    pipe.hset.assert_called_once_with(
        registry.alias_conflicts_key,
        "museum-agent",
        json.dumps(["http://museum-a", "http://museum-b"]),
    )
    assert [card.url for card in registry.agents] == [
        "http://museum-a",
        "http://museum-b",
    ]


def test_discovery_synthesizes_unknown_health_for_legacy_card(monkeypatch) -> None:
    registry = _registry()
    card = _card()
    registry.get_agents = MagicMock(return_value=[card])
    registry.redis.zmscore.return_value = [None]
    registry.redis.hmget.return_value = [None]
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SEC", "30")

    record = registry.discovery_records()[0]
    assert record.runtime_status.agent_id == card.url
    assert record.runtime_status.agent_ready == "unknown"
    assert record.runtime_status.supported_protocol_versions == ["legacy"]
    assert record.heartbeat_fresh is False
    assert record.heartbeat_age_ms is None


def test_discovery_keeps_heartbeat_and_index_health_independent(monkeypatch) -> None:
    registry = _registry()
    values = _install_hash(registry)
    card = _card()
    registry.get_agents = MagicMock(return_value=[card])
    status = AgentRuntimeStatus(
        protocol_version=PROTOCOL_VERSION,
        agent_id=card.url,
        agent_url=card.url,
        card_revision="sha256:card",
        capability_manifest_version="sha256:manifest",
        agent_ready=HealthState.READY,
        readiness_generation=7,
    )
    registry.put_runtime_status(status)
    registry.redis.zmscore.return_value = [
        datetime.now(timezone.utc).timestamp() - 3
    ]
    registry.redis.incr.return_value = 11
    registry.set_agent_index_status(card.url, "failed", error="embedding unavailable")
    registry.redis.hmget.side_effect = lambda key, _urls: {
        registry.runtime_status_key: [
            values[(registry.runtime_status_key, card.url)]
        ],
        registry.aliases_by_id_key: [json.dumps([card.name])],
        registry.index_status_key: [values[(registry.index_status_key, card.url)]],
    }[key]
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SEC", "30")

    record = registry.discovery_records()[0]
    assert record.heartbeat_fresh is True
    assert 2000 <= record.heartbeat_age_ms <= 5000
    assert record.runtime_status.agent_ready == "ready"
    assert record.runtime_status.readiness_generation == 7
    assert record.index_status.state == "failed"
    assert record.index_status.generation == 11
    assert record.index_status.error == "embedding unavailable"


def test_ordinary_runtime_heartbeat_does_not_change_generation() -> None:
    registry = _registry()
    values = _install_hash(registry)
    status = AgentRuntimeStatus(
        protocol_version=PROTOCOL_VERSION,
        agent_id="http://museum",
        agent_url="http://museum",
        card_revision="card-1",
        capability_manifest_version="manifest-1",
        readiness_generation=4,
    )
    registry.put_runtime_status(status)
    stored = json.loads(values[(registry.runtime_status_key, "http://museum")])
    assert stored["readiness_generation"] == 4
    assert registry.redis.incr.call_count == 0


def test_card_refresh_replaces_stale_in_memory_card() -> None:
    registry = _registry()
    old = _card()
    refreshed = _card()
    refreshed.name = "Museum-Agent-v2"
    registry.agents = [old]
    registry._reconcile_aliases = MagicMock()

    assert registry._update_agents_on_event("add", refreshed.url, refreshed) is True
    assert registry.agents == [refreshed]
    registry._reconcile_aliases.assert_called_once_with()


def test_watcher_side_alias_conflict_never_purges_card() -> None:
    registry = _registry()
    old = _card("http://museum-old")
    card = _card("http://museum-new")
    registry.agents = [old]
    registry._reconcile_aliases = MagicMock()
    registry.remove_agent = MagicMock(return_value=True)

    assert registry._update_agents_on_event("add", card.url, card) is True
    assert registry.agents == [old, card]
    registry.remove_agent.assert_not_called()
    registry._reconcile_aliases.assert_called_once_with()


def test_startup_alias_conflict_is_order_independent_and_non_destructive() -> None:
    registry = _registry()
    cards = [_card("http://museum-b"), _card("http://museum-a")]
    registry.list_agents = MagicMock(return_value=cards)
    registry._reconcile_aliases = MagicMock()
    registry.remove_agent = MagicMock(return_value=True)

    registry._load_initial_agents()

    assert registry.agents == cards
    registry.remove_agent.assert_not_called()
    registry._reconcile_aliases.assert_called_once_with()


def test_startup_vector_reconciliation_marks_existing_document_indexed(
    monkeypatch,
) -> None:
    registry = MagicMock()
    card = _card()
    registry.redis.hkeys.return_value = [card.url]
    registry.get_agent.return_value = card
    monkeypatch.setattr(
        "agent_registry.server._agent_exists_in_vector_db",
        lambda _url: True,
    )

    sync_existing_agents_to_vector_db(registry)

    registry.set_agent_index_status.assert_called_once_with(
        card.url, IndexState.INDEXED
    )


def test_schema_api_resolves_and_rejects_immutable_conflict(monkeypatch) -> None:
    descriptor = SchemaDescriptor(
        schema_id="museum.record/v1",
        owner="tests",
        schema={"type": "object"},
    )
    registry = MagicMock()
    registry.get_schema.return_value = descriptor
    registry.list_schemas.return_value = [descriptor]
    registry.register_schema.side_effect = SchemaConflictError("immutable conflict")
    registry.alias_conflicts_for.return_value = []
    client = TestClient(create_fastapi_app(registry))
    monkeypatch.setenv("AGENT_SCHEMA_REGISTRY_WRITE_TOKEN", "schema-writer")

    resolved = client.get(
        "/schemas/resolve", params={"schema_id": descriptor.schema_id}
    )
    assert resolved.status_code == 200
    assert resolved.json()["schema_digest"] == descriptor.schema_digest
    schemas = client.get("/schemas").json()["schemas"]
    assert schemas[0]["schema_id"] == descriptor.schema_id

    conflict = client.post(
        "/schemas",
        json=descriptor.model_dump(mode="json", by_alias=True),
        headers={"Authorization": "Bearer schema-writer"},
    )
    assert conflict.status_code == 409


def test_schema_api_rejects_unauthenticated_writes(monkeypatch) -> None:
    descriptor = SchemaDescriptor(
        schema_id="museum.record/v1",
        owner="tests",
        schema={"type": "object"},
    )
    registry = MagicMock()
    client = TestClient(create_fastapi_app(registry))
    body = descriptor.model_dump(mode="json", by_alias=True)

    monkeypatch.delenv("AGENT_SCHEMA_REGISTRY_WRITE_TOKEN", raising=False)
    assert client.post("/schemas", json=body).status_code == 503

    monkeypatch.setenv("AGENT_SCHEMA_REGISTRY_WRITE_TOKEN", "schema-writer")
    assert client.post("/schemas", json=body).status_code == 401
    registry.register_schema.assert_not_called()


def test_legacy_agent_listing_does_not_load_discovery_metadata() -> None:
    registry = MagicMock()
    registry.get_agents.return_value = []
    client = TestClient(create_fastapi_app(registry))

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json() == {"agent_cards": []}
    registry.discovery_records.assert_not_called()


def test_alias_endpoint_reports_ambiguity_without_selecting_a_winner() -> None:
    registry = MagicMock()
    registry.alias_conflicts_for.return_value = ["http://a", "http://b"]
    client = TestClient(create_fastapi_app(registry))

    response = client.get(
        "/agents/resolve-alias", params={"alias": "Museum-Agent"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["canonical_agent_ids"] == [
        "http://a",
        "http://b",
    ]
    registry.resolve_agent_alias.assert_not_called()
