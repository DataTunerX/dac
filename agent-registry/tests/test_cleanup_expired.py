"""Unit tests for registry heartbeat cleanup + reachability purge."""

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_registry.redis_registry import CleanupService, RedisRegistry


def _registry_with_fake_redis():
    reg = object.__new__(RedisRegistry)
    reg.registry_key = "expert_agents"
    reg.heartbeat_key = "agent_heartbeats"
    reg.agents = []
    reg.redis = MagicMock()
    return reg


def test_cleanup_expired_purges_missing_heartbeat_score(monkeypatch):
    """Hash-only orphans must be cleaned (previously crashed on fromtimestamp(None))."""
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SEC", "30")
    reg = _registry_with_fake_redis()
    orphan = "http://ghost.default.svc.cluster.local:10100"
    alive = "http://alive.default.svc.cluster.local:10100"
    now = datetime.now().timestamp()

    reg.redis.hkeys.return_value = [orphan, alive]
    reg.redis.zrange.return_value = [alive]

    def _zscore(_key, url):
        if url == alive:
            return now
        return None

    reg.redis.zscore.side_effect = _zscore
    pipe = MagicMock()
    reg.redis.pipeline.return_value = pipe
    pipe.execute.return_value = [1, 1, 1]
    reg.agents = [
        SimpleNamespace(url=orphan),
        SimpleNamespace(url=alive),
    ]

    cleaned = reg.cleanup_expired()
    assert cleaned == 1
    pipe.hdel.assert_any_call(reg.registry_key, orphan)
    assert [a.url for a in reg.agents] == [alive]


def test_cleanup_expired_purges_stale_heartbeat(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SEC", "30")
    reg = _registry_with_fake_redis()
    stale = "http://stale.default.svc.cluster.local:10100"
    now = datetime.now().timestamp()

    reg.redis.hkeys.return_value = [stale]
    reg.redis.zrange.return_value = [stale]
    reg.redis.zscore.return_value = now - 120  # > 30s
    pipe = MagicMock()
    reg.redis.pipeline.return_value = pipe
    pipe.execute.return_value = [1, 1, 1]
    reg.agents = [SimpleNamespace(url=stale)]

    assert reg.cleanup_expired() == 1
    pipe.hdel.assert_any_call(reg.registry_key, stale)


def test_probe_agent_reachable_dns_failure(monkeypatch):
    import socket

    def _boom(*_a, **_k):
        raise socket.gaierror(-2, "Name does not resolve")

    monkeypatch.setattr(socket, "create_connection", _boom)
    ok, reason = RedisRegistry.probe_agent_reachable(
        "http://missing.default.svc.cluster.local:10100"
    )
    assert ok is False
    assert reason.startswith("dns:")


def test_purge_unreachable_dns_deletes_immediately(monkeypatch):
    service = CleanupService(registry=_registry_with_fake_redis(), interval=60)
    url = "http://ghost.default.svc.cluster.local:10100"
    service.registry.redis.hkeys.return_value = [url]
    service.registry.remove_agent = MagicMock(return_value=True)
    monkeypatch.setattr(
        service.registry,
        "probe_agent_reachable",
        staticmethod(lambda *_a, **_k: (False, "dns:Name does not resolve")),
    )
    monkeypatch.setenv("REGISTRY_REACHABILITY_CHECK", "true")
    monkeypatch.setenv("REGISTRY_REACHABILITY_FAILS", "3")

    purged = service._purge_unreachable()
    assert purged == 1
    service.registry.remove_agent.assert_called_once()
