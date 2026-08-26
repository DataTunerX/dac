import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator_agent.orchestrator_agent_semantic_group as sg


class _Updater:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.artifacts = []
        self.completed = False
        self.__class__.instances.append(self)

    async def add_artifact(self, parts, name):
        self.artifacts.append((parts, name))

    async def complete(self, message):
        self.completed = True


class _Queue:
    async def enqueue_event(self, _event):
        raise AssertionError("existing task should be reused")


def _response(**overrides):
    values = {
        "can_handle": True,
        "confidence": 0.9,
        "reason": "capable",
        "agent_name": "group-a",
        "agent_url": "http://group-a",
        "route_path": ["group-a"],
        "route_paths": [{"path": ["group-a"], "confidence": 0.9}],
    }
    values.update(overrides)
    return sg.CapabilityCheckResponse(**values)


def _executor(monkeypatch):
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(
        name="group-a",
        url="http://group-a",
        description="group",
        skills=[],
    )
    executor.agent_id = "group-a"
    executor.semantic_group_id = "sg-a"
    executor.metadata = {}
    monkeypatch.setattr(sg, "TaskUpdater", _Updater)
    monkeypatch.setattr(sg, "new_agent_text_message", lambda *_args, **_kwargs: object())
    _Updater.instances.clear()
    return executor


def _run(executor):
    task = SimpleNamespace(context_id="context-1")
    context = SimpleNamespace(
        current_task=task,
        task_id="task-1",
        context_id="context-1",
        metadata={
            "user_id": "user-1",
            "run_id": "run-1",
            "trace_id": "trace-1",
            sg.PROPAGATED_HISTORY_KEY: {
                "turns": [{"role": "user", "content": "earlier"}]
            },
        },
    )
    asyncio.run(executor.handle_capability_check(context, _Queue(), "query"))
    updater = _Updater.instances[-1]
    assert updater.completed
    parts, name = updater.artifacts[-1]
    assert name == "capability-check-response"
    return json.loads(parts[0].text)


def test_disabled_uses_legacy_only(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "false")
    executor = _executor(monkeypatch)
    legacy = _response(reason="legacy")
    executor._legacy_capability_check = AsyncMock(return_value=legacy)
    executor._delegated_member_capability_check = AsyncMock()

    result = _run(executor)

    assert result["reason"] == "legacy"
    executor._legacy_capability_check.assert_awaited_once()
    executor._delegated_member_capability_check.assert_not_awaited()


def test_default_uses_delegated_member_capability(monkeypatch):
    monkeypatch.delenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", raising=False)
    monkeypatch.delenv("SG_MEMBER_CAPABILITY_CHECK_SHADOW", raising=False)
    executor = _executor(monkeypatch)
    executor._legacy_capability_check = AsyncMock()
    executor._delegated_member_capability_check = AsyncMock(
        return_value=_response(reason="default delegated")
    )

    result = _run(executor)

    assert result["reason"] == "default delegated"
    executor._delegated_member_capability_check.assert_awaited_once()
    executor._legacy_capability_check.assert_not_awaited()


def test_delegated_check_parses_sidecar_artifact_in_executor(monkeypatch):
    payload = {
        "can_handle": True,
        "can_contribute": True,
        "confidence": 0.91,
        "reason": "store member covers the request",
        "agent_name": "group-a",
        "execution_strategy": "single",
        "collaboration_agents": ["store-agent"],
        "member_results": [{"agent_name": "store-agent", "can_handle": True}],
    }

    class _Chunk:
        def model_dump(self, **_kwargs):
            return {
                "result": {
                    "kind": "artifact-update",
                    "artifact": {
                        "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]
                    },
                }
            }

    class _HTTPClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _A2AClient:
        def __init__(self, **_kwargs):
            pass

        async def send_message_streaming(self, _request):
            yield _Chunk()

    executor = _executor(monkeypatch)
    monkeypatch.setattr(executor, "_member_capability_sidecar_card", lambda: object())
    monkeypatch.setattr(sg.httpx, "AsyncClient", _HTTPClient)
    monkeypatch.setattr(sg, "A2AClient", _A2AClient)

    result = asyncio.run(executor._delegated_member_capability_check("query", {}))

    assert result.can_handle is True
    assert result.collaboration_agents == ["store-agent"]
    assert result.member_results[0]["agent_name"] == "store-agent"


def test_enabled_returns_delegated_fields(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "true")
    executor = _executor(monkeypatch)
    delegated = _response(
        execution_strategy="collaboration",
        collaboration_agents=["member-a", "member-b"],
        collaboration_roles={"member-a": "handle", "member-b": "contribute"},
        collaboration_paths=[{"agent": "member-a", "path": ["member-a"]}],
        member_results=[{"agent_name": "member-a", "can_handle": True}],
        missing_requirements=["optional context"],
    )
    executor._legacy_capability_check = AsyncMock()
    executor._delegated_member_capability_check = AsyncMock(return_value=delegated)

    result = _run(executor)

    assert result["execution_strategy"] == "collaboration"
    assert result["collaboration_agents"] == ["member-a", "member-b"]
    assert result["member_results"][0]["agent_name"] == "member-a"
    assert result["missing_requirements"] == ["optional context"]
    executor._legacy_capability_check.assert_not_awaited()


def test_sidecar_failure_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "1")
    executor = _executor(monkeypatch)
    executor._delegated_member_capability_check = AsyncMock(
        side_effect=ConnectionError("sidecar unavailable")
    )
    executor._legacy_capability_check = AsyncMock(
        return_value=_response(reason="legacy fallback")
    )

    result = _run(executor)

    assert result["reason"] == "legacy fallback"
    executor._legacy_capability_check.assert_awaited_once()


def test_degraded_delegated_result_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "yes")
    executor = _executor(monkeypatch)
    executor._delegated_member_capability_check = AsyncMock(
        return_value=_response(degraded=True, unavailable_count=2)
    )
    executor._legacy_capability_check = AsyncMock(
        return_value=_response(reason="legacy degraded fallback")
    )

    result = _run(executor)

    assert result["reason"] == "legacy degraded fallback"
    executor._legacy_capability_check.assert_awaited_once()


def test_shadow_executes_both_and_returns_legacy(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "true")
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_SHADOW", "true")
    executor = _executor(monkeypatch)
    executor._legacy_capability_check = AsyncMock(
        return_value=_response(can_handle=False, reason="legacy")
    )
    executor._delegated_member_capability_check = AsyncMock(
        return_value=_response(can_handle=True, reason="delegated")
    )

    result = _run(executor)

    assert result["can_handle"] is False
    assert result["reason"] == "legacy"
    executor._legacy_capability_check.assert_awaited_once()
    executor._delegated_member_capability_check.assert_awaited_once()


def test_capability_result_issues_request_scoped_execution_hint(monkeypatch):
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_CHECK_ENABLED", "true")
    executor = _executor(monkeypatch)
    executor._delegated_member_capability_check = AsyncMock(
        return_value=_response(
            can_handle=True,
            collaboration_agents=["store-agent"],
            reason="member covers stores",
        )
    )
    executor._legacy_capability_check = AsyncMock()

    result = _run(executor)

    hint = result["execution_hint"]
    assert hint["version"] == "v1"
    assert hint["semantic_group_id"] == "sg-a"
    assert hint["run_id"] == "run-1"
    assert hint["can_handle"] is True
    assert hint["selected_members"] == ["store-agent"]
    assert executor._validated_execution_hint(
        {
            "run_id": "run-1",
            sg.SG_EXECUTION_HINT_KEY: hint,
        },
        "query",
    ) == hint
    assert executor._validated_execution_hint(
        {
            "run_id": "run-1",
            sg.SG_EXECUTION_HINT_KEY: hint,
        },
        "different query",
    ) is None


def test_valid_execution_hint_builds_authoritative_own_expert_plan():
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    plan = executor._build_authoritative_execution_plan(
        query="上海有哪些门店？给出门店编码和名称。",
        own_names={"EcommerceTransactionAgent-sg-x", "LocalSkill"},
        preferred_own_agent="EcommerceTransactionAgent-sg-x",
        execution_hint={
            "can_handle": True,
            "selected_members": [
                "OmnichannelRetailEcommercePlatformAgent-dd-x"
            ],
        },
    )

    assert plan is not None
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "EcommerceTransactionAgent-sg-x"
    assert "门店" in plan.tasks[0].description


def test_response_preserves_old_fields_and_defaults_new_fields():
    response = sg.CapabilityCheckResponse(
        can_handle=True,
        confidence=0.8,
        reason="legacy shape",
        agent_name="group-a",
    )
    payload = response.model_dump()

    assert payload["can_handle"] is True
    assert payload["execution_strategy"] == "single"
    assert payload["collaboration_agents"] == []
    assert payload["collaboration_roles"] == {}
    assert payload["collaboration_paths"] == []
    assert payload["member_results"] == []
    assert payload["degraded"] is False
    assert payload["unavailable_count"] == 0
    assert payload["missing_requirements"] == []
    assert payload["execution_hint"] == {}
