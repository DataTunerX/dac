import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.expert_agent_semantic_group as sg_module
from agent.expert_agent_semantic_group import ExpertAgent, ExpertAgentExecutorSemanticGroup
from a2a.types import AgentCard


def _card(name: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=name,
        url=f"http://{name}",
        version="1",
        capabilities={"streaming": True},
        skills=[],
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
    )


def _agent() -> ExpertAgent:
    return ExpertAgent.model_construct(
        agent_name="SalesGroup",
        description="",
        content_types=["text"],
        agent_id="SalesGroup",
        semantic_group_id="sg-sales",
        query="sales query",
        metadata={"propagated_history": {"turns": [{"role": "user", "content": "prior"}]}},
        group_agent_cards=[],
    )


def _result(
    name: str,
    *,
    can_handle: bool = False,
    can_contribute: bool = False,
    confidence: float = 0.0,
    entities=None,
    tables=None,
    metrics=None,
    missing=None,
    available: bool = True,
    status: str = "",
):
    return {
        "can_handle": can_handle,
        "can_contribute": can_contribute,
        "confidence": confidence,
        "reason": f"{name} reason",
        "agent_name": name,
        "agent_url": f"http://{name}",
        "matched_entities": entities or [],
        "matched_tables": tables or [],
        "matched_metrics": metrics or [],
        "missing_requirements": missing or [],
        "descriptor_type": "structured",
        "available": available,
        "timed_out": status == "timeout",
        "status": status or (
            "handler" if can_handle else "contributor" if can_contribute else "unsupported"
        ),
    }


def test_single_handler_uses_highest_confidence_deterministically():
    result = _agent()._aggregate_member_capabilities([
        _result("B", can_handle=True, confidence=0.7),
        _result("A", can_handle=True, confidence=0.9),
        _result("C", can_contribute=True, confidence=0.95),
    ])

    assert result["can_handle"] is True
    assert result["execution_strategy"] == "single"
    assert result["confidence"] == 0.9
    assert result["collaboration_agents"] == ["A"]
    assert result["degraded"] is False


def test_contributors_with_cross_covered_evidence_collaborate():
    result = _agent()._aggregate_member_capabilities([
        _result(
            "Orders",
            can_contribute=True,
            confidence=0.75,
            entities=["orders"],
            missing=["refund_rate"],
        ),
        _result(
            "Refunds",
            can_contribute=True,
            confidence=0.8,
            metrics=["refund_rate"],
            missing=["orders"],
        ),
    ])

    assert result["can_handle"] is True
    assert result["can_contribute"] is True
    assert result["execution_strategy"] == "collaboration"
    assert result["collaboration_agents"] == ["Refunds", "Orders"]
    assert result["missing_requirements"] == []


def test_partial_contributors_preserve_missing_requirements():
    result = _agent()._aggregate_member_capabilities([
        _result(
            "Orders",
            can_contribute=True,
            confidence=0.6,
            tables=["orders"],
            missing=["customer_profile"],
        ),
        _result("No", confidence=0.2),
    ])

    assert result["can_handle"] is False
    assert result["can_contribute"] is True
    assert result["execution_strategy"] == "single"
    assert result["missing_requirements"] == ["customer_profile"]


def test_all_explicit_no_is_not_degraded():
    result = _agent()._aggregate_member_capabilities([
        _result("A", confidence=0.1),
        _result("B", confidence=0.2),
    ])

    assert result["can_handle"] is False
    assert result["can_contribute"] is False
    assert result["execution_strategy"] == "single"
    assert result["degraded"] is False
    assert result["unavailable_count"] == 0
    assert "explicitly" in result["reason"]


def test_positive_member_result_stays_conclusive_when_peer_is_unavailable():
    result = _agent()._aggregate_member_capabilities([
        _result("Orders", can_handle=True, confidence=0.9, tables=["orders"]),
        _result("Offline", available=False, status="unavailable"),
    ])

    assert result["can_handle"] is True
    assert result["degraded"] is False
    assert result["unavailable_count"] == 1
    assert result["collaboration_agents"] == ["Orders"]


@pytest.mark.asyncio
async def test_timeout_is_unavailable_and_degraded(monkeypatch):
    agent = _agent()
    members = [
        (SimpleNamespace(descriptor_type="structured"), _card("fast")),
        (SimpleNamespace(descriptor_type="code"), _card("slow")),
    ]
    agent.group_agent_cards = members

    async def fake_request(_client, member, card):
        if card.name == "slow":
            await asyncio.sleep(0.1)
        return _result(card.name)

    agent._request_member_capability = fake_request
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_PER_MEMBER_TIMEOUT", "0.01")
    monkeypatch.setenv("SG_MEMBER_CAPABILITY_TOTAL_TIMEOUT", "0.2")

    member_results = await agent._fan_out_member_capabilities()
    result = agent._aggregate_member_capabilities(member_results)

    assert member_results[0]["status"] == "unsupported"
    assert member_results[1]["status"] == "timeout"
    assert result["degraded"] is True
    assert result["unavailable_count"] == 1
    assert "explicitly" not in result["reason"]


def test_zero_members_is_degraded_not_unsupported():
    result = _agent()._aggregate_member_capabilities([])

    assert result["can_handle"] is False
    assert result["degraded"] is True
    assert result["unavailable_count"] == 0
    assert result["member_results"] == []
    assert "available" in result["reason"]


def test_execution_hint_loads_soft_preference_without_hard_filter():
    agent = _agent()
    agent.query = "上海有哪些门店？给出门店编码和名称。"
    normalized = " ".join(agent.query.strip().casefold().split())
    fingerprint = sg_module.hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    agent.metadata = {
        sg_module.SG_EXECUTION_HINT_KEY: {
            "version": "v1",
            "semantic_group_id": "sg-sales",
            "query_fingerprint": fingerprint,
            "created_at_epoch": int(sg_module.datetime.now().timestamp()),
            "ttl_seconds": 300,
            "can_handle": True,
            "degraded": False,
            "execution_strategy": "single",
            "selected_members": ["StoreAgent"],
            "member_roles": {"StoreAgent": "handle"},
            "member_evidence": [
                {
                    "agent_name": "StoreAgent",
                    "role": "handle",
                    "confidence": 0.94,
                    "matched_evidence": ["门店", "store_code"],
                    "reason": "store metadata covers the query",
                }
            ],
            "reason": "StoreAgent can handle store lookup",
        }
    }
    agent.group_agent_cards = [
        (SimpleNamespace(descriptor_type="structured"), _card("OrdersAgent")),
        (SimpleNamespace(descriptor_type="structured"), _card("StoreAgent")),
    ]

    assert agent._apply_sg_execution_hint() is True
    # Soft preference: preferred first, full pool retained.
    assert [card.name for _, card in agent.group_agent_cards] == [
        "StoreAgent",
        "OrdersAgent",
    ]
    assert agent.capability_preference["preferred_handlers"] == ["StoreAgent"]
    assert agent.capability_preference["enabled"] is True


def test_execution_hint_resolves_dd_suffix_aliases():
    agent = _agent()
    agent.query = "查询库存"
    normalized = " ".join(agent.query.strip().casefold().split())
    fingerprint = sg_module.hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    agent.metadata = {
        sg_module.SG_EXECUTION_HINT_KEY: {
            "version": "v1",
            "semantic_group_id": "sg-sales",
            "query_fingerprint": fingerprint,
            "created_at_epoch": int(sg_module.datetime.now().timestamp()),
            "ttl_seconds": 300,
            "can_handle": True,
            "degraded": False,
            "selected_members": ["InventoryAgent"],
            "member_roles": {"InventoryAgent": "handle"},
        }
    }
    agent.group_agent_cards = [
        (SimpleNamespace(descriptor_type="structured"), _card("OrdersAgent-dd-aaa")),
        (SimpleNamespace(descriptor_type="structured"), _card("InventoryAgent-dd-bbb")),
    ]

    assert agent._apply_sg_execution_hint() is True
    assert agent.capability_preference["preferred_handlers"] == [
        "InventoryAgent-dd-bbb"
    ]
    assert len(agent.group_agent_cards) == 2


@pytest.mark.asyncio
async def test_executor_fast_path_completes_without_normal_run(monkeypatch):
    capability_result = {
        "can_handle": True,
        "confidence": 0.9,
        "execution_strategy": "single",
    }

    class FakeDataClient:
        close = AsyncMock()

    class FakeAgent:
        def __init__(self, **_kwargs):
            self.data_services_client = FakeDataClient()

        async def check_group_member_capability(self):
            return capability_result

        async def run(self):
            raise AssertionError("normal answer execution must not run")
            yield

    updater = SimpleNamespace(
        add_artifact=AsyncMock(),
        complete=AsyncMock(),
    )
    monkeypatch.setattr(sg_module, "ExpertAgent", FakeAgent)
    monkeypatch.setattr(sg_module, "TaskUpdater", lambda *_args, **_kwargs: updater)

    task = SimpleNamespace(id="task-1", context_id="ctx-1")
    context = SimpleNamespace(
        metadata={"message_type": "group_member_capability_check"},
        current_task=task,
        message=SimpleNamespace(),
        get_user_input=lambda: "Can the group answer?",
    )
    executor = ExpertAgentExecutorSemanticGroup(
        semantic_group_id="sg-sales",
        agent_id="SalesGroup",
    )

    await executor.execute(context, SimpleNamespace())

    updater.add_artifact.assert_awaited_once()
    updater.complete.assert_awaited_once()
    artifact_text = updater.add_artifact.await_args.args[0][0].text
    assert json.loads(artifact_text) == capability_result

