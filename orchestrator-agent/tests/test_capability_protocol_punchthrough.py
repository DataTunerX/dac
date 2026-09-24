"""End-to-end protocol punch-through: SD two-phase → Expert → SG → routing shape.

Does not start live agents. It feeds a fake LLM into the real SD mapper, then
the real Expert normalize/aggregate, then the real SG payload mapper, then
asserts the JSON routing already knows how to parse.
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

ORCH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERT_ROOT = os.path.abspath(os.path.join(ORCH_ROOT, "..", "expert-agent"))
sys.path.insert(0, ORCH_ROOT)
sys.path.insert(0, EXPERT_ROOT)

from a2a.types import AgentCard  # noqa: E402

from agent.expert_agent_semantic_group import ExpertAgent  # noqa: E402
from orchestrator_agent import capability_chain  # noqa: E402
from orchestrator_agent import orchestrator_agent_semantic_domain as domain  # noqa: E402
from orchestrator_agent import orchestrator_agent_semantic_group as sg  # noqa: E402
from orchestrator_agent import skill_capability_two_phase as skill_cc  # noqa: E402

ROUTING_ROOT = os.path.abspath(os.path.join(ORCH_ROOT, "..", "routing-agent"))
if ROUTING_ROOT not in sys.path:
    sys.path.insert(0, ROUTING_ROOT)


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def ainvoke(self, _messages):
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        return SimpleNamespace(content=self.responses.pop(0))


def _domain_json(verdict: str, reason: str) -> str:
    return json.dumps({"domain_verdict": verdict, "reason": reason}, ensure_ascii=False)


def _chain_json(*, matched: list[str], required: list[str] | None = None) -> str:
    required = list(required if required is not None else matched)
    ratio = (len(matched) / len(required)) if required else 1.0
    return json.dumps(
        {
            "steps": [
                {
                    "step_id": 1,
                    "description": "查询订单列表",
                    "operation": "lookup",
                    "is_final": True,
                    "inputs": [{"name": "用户名", "source": "query"}],
                    "outputs": ["订单列表"],
                    "constraints": ["只读"],
                    "input_match": {
                        "required": ["用户名"],
                        "matched": ["用户名"],
                        "ratio": 1.0,
                        "evidence_strength": "solid",
                    },
                    "data_coverage": {
                        "required": required,
                        "matched": matched,
                        "ratio": round(ratio, 3),
                        "evidence_strength": "solid",
                    },
                    "operation_capability": 1.0,
                    "result_match": {
                        "required": ["订单列表"],
                        "matched": ["订单列表"] if ratio >= 1.0 else [],
                        "ratio": 1.0 if ratio >= 1.0 else 0.0,
                        "evidence_strength": "solid",
                    },
                    "constraint_satisfaction": {
                        "required": ["只读"],
                        "matched": ["只读"],
                        "ratio": 1.0,
                        "evidence_strength": "solid",
                    },
                    "evidence": ["技能正文：订单表"],
                }
            ],
            "evidence_grade": "A",
            "contribution": "输入用户名，输出订单列表",
            "missing_requirements": [] if ratio >= 1.0 else ["外部数据"],
            "risks": [],
            "reason": "步骤1：测试链打分",
        },
        ensure_ascii=False,
    )


def _expert() -> ExpertAgent:
    return ExpertAgent.model_construct(
        agent_name="SalesGroup",
        description="",
        content_types=["text"],
        agent_id="SalesGroup",
        semantic_group_id="sg-sales",
        query="查订单",
        metadata={},
        group_agent_cards=[],
    )


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


def _sg_mapper():
    return object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)


def _routing_required(dumped: dict) -> None:
    for key in (
        "can_handle",
        "can_contribute",
        "confidence",
        "reason",
        "contribution",
        "score_version",
        "evidence_grade",
        "threshold",
        "handle_score",
        "steps",
        "contributing_steps",
        "risks",
        "domain_verdict",
        "has_external_dependency",
        "member_results",
        "collaboration_agents",
        "missing_requirements",
    ):
        assert key in dumped, f"routing field missing: {key}"


def _parse_with_routing(dumped: dict):
    """Parse the SG JSON with the real routing mapper (same as broadcast ingest)."""
    from routing_agent.server import _capability_response_from_payload

    return _capability_response_from_payload(
        dumped,
        default_name=str(dumped.get("agent_name") or "SalesGroup"),
        default_url=str(dumped.get("agent_url") or "http://sales-group"),
        route_path=dumped.get("route_path") or ["SalesGroup"],
        route_paths=dumped.get("route_paths") or [],
        latency_ms=int(dumped.get("latency_ms") or 0),
    )


@pytest.mark.asyncio
async def test_handle_path_sd_expert_sg_json_keeps_chain_protocol():
    llm = _FakeLLM(
        [
            _domain_json("has", "领域交集：明确有 — 订单"),
            _chain_json(matched=["订单表"], required=["订单表"]),
        ]
    )
    two_phase = await skill_cc.run_two_phase_capability_check(
        llm,
        query="查一下订单 ORD-001 的状态",
        agent_name="OrdersAgent",
        agent_description="订单域",
        agent_skills="1. table name: orders(订单)",
    )
    sd_payload = domain._member_response_from_two_phase(
        two_phase,
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert sd_payload["score_version"] == capability_chain.SCORE_VERSION
    assert sd_payload["domain_verdict"] == "has"
    assert sd_payload["can_handle"] is True
    assert sd_payload["steps"]
    assert "订单表" in sd_payload["matched_evidence"]

    expert = _expert()
    normalized = expert._normalize_member_capability(
        SimpleNamespace(descriptor_type="structured-mysql"),
        _card("OrdersAgent"),
        sd_payload,
    )
    assert normalized["score_version"] == capability_chain.SCORE_VERSION
    assert normalized["steps"][0]["checklists"]["D"]["matched"] == ["订单表"]
    assert normalized["contributing_steps"] == [1]
    assert normalized["matched_evidence"] == ["订单表"]

    group = expert._aggregate_member_capabilities(
        [
            normalized,
            {
                "can_handle": False,
                "can_contribute": False,
                "confidence": 0.0,
                "reason": "out of domain",
                "agent_name": "InventoryAgent",
                "agent_url": "http://inventory",
                "matched_entities": [],
                "matched_tables": [],
                "matched_metrics": [],
                "missing_requirements": [],
                "descriptor_type": "structured",
                "available": True,
                "timed_out": False,
                "status": "unsupported",
                "domain_verdict": "none",
                "score_version": capability_chain.SCORE_VERSION,
                "steps": [],
            },
        ]
    )
    assert group["can_handle"] is True
    assert group["domain_verdict"] == "has"
    assert group["score_version"] == capability_chain.SCORE_VERSION
    assert group["collaboration_agents"] == ["OrdersAgent"]
    assert group["member_results"][0]["steps"]

    artifact = json.dumps(group, ensure_ascii=False, separators=(",", ":"))
    parsed = sg.OrchestratorAgentExecutorSemanticGroup._parse_capability_json(artifact)
    sg_resp = _sg_mapper()._capability_response_from_expert_payload(
        parsed,
        agent_name="SalesGroup",
        agent_url="http://sales-group",
        latency_ms=40,
    )
    assert sg_resp.is_chain_scored is True
    assert sg_resp.domain_verdict == "has"
    assert sg_resp.score_version == capability_chain.SCORE_VERSION
    assert sg_resp.steps[0]["step_id"] == 1
    assert sg_resp.contributing_steps == [1]
    assert sg_resp.member_results[0]["agent_name"] == "OrdersAgent"
    assert sg_resp.contribution == "输入用户名，输出订单列表"
    dumped = json.loads(sg_resp.model_dump_json())
    _routing_required(dumped)
    assert dumped["score_version"] == capability_chain.SCORE_VERSION
    assert dumped["domain_verdict"] == "has"
    assert dumped["has_external_dependency"] is False
    routing_resp = _parse_with_routing(dumped)
    assert routing_resp.is_chain_scored is True
    assert routing_resp.domain_verdict == "has"
    assert routing_resp.contributing_steps == [1]
    assert routing_resp.steps[0]["step_id"] == 1
    assert routing_resp.member_results[0]["agent_name"] == "OrdersAgent"


@pytest.mark.asyncio
async def test_domain_none_path_still_marks_chain_scored():
    llm = _FakeLLM([_domain_json("none", "领域交集：明确无 — 工伤认定")])
    two_phase = await skill_cc.run_two_phase_capability_check(
        llm,
        query="工伤认定流程怎么办",
        agent_name="OrdersAgent",
        agent_description="电商订单域",
        agent_skills="tables_detail: orders(订单)",
    )
    sd_payload = domain._member_response_from_two_phase(
        two_phase,
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert sd_payload["domain_verdict"] == "none"
    assert sd_payload["can_handle"] is False
    assert two_phase.phase2_invoked is False
    assert sd_payload["score_version"] == capability_chain.SCORE_VERSION
    assert sd_payload["steps"] == []

    expert = _expert()
    normalized = expert._normalize_member_capability(
        SimpleNamespace(descriptor_type="structured-mysql"),
        _card("OrdersAgent"),
        sd_payload,
    )
    group = expert._aggregate_member_capabilities([normalized])
    assert group["can_handle"] is False
    assert group["domain_verdict"] == "none"
    assert group["score_version"] == capability_chain.SCORE_VERSION

    sg_resp = _sg_mapper()._capability_response_from_expert_payload(
        group,
        agent_name="SalesGroup",
        agent_url="http://sales-group",
    )
    assert sg_resp.is_chain_scored is True
    assert sg_resp.domain_verdict == "none"
    assert sg_resp.can_handle is False
    dumped = json.loads(sg_resp.model_dump_json())
    _routing_required(dumped)
    routing_resp = _parse_with_routing(dumped)
    assert routing_resp.is_chain_scored is True
    assert routing_resp.domain_verdict == "none"
    assert routing_resp.can_handle is False


def test_sg_mapper_coerces_string_step_ids_and_ignores_junk():
    resp = _sg_mapper()._capability_response_from_expert_payload(
        {
            "can_handle": True,
            "confidence": "0.91",
            "threshold": "0.6",
            "handle_score": "0.88",
            "score_version": "capability-chain-v1",
            "domain_verdict": "has",
            "contributing_steps": ["1", "x", 2],
            "steps": [{"step_id": 1}, "not-a-step"],
            "member_results": [{"agent_name": "sd-a"}, "skip"],
            "collaboration_roles": ["bad"],
            "unavailable_count": "3",
        },
        agent_name="group-a",
        agent_url="http://group-a",
    )
    assert resp.confidence == pytest.approx(0.91)
    assert resp.threshold == pytest.approx(0.6)
    assert resp.handle_score == pytest.approx(0.88)
    assert resp.contributing_steps == [1, 2]
    assert resp.steps == [{"step_id": 1}]
    assert resp.member_results == [{"agent_name": "sd-a"}]
    assert resp.collaboration_roles == {}
    assert resp.unavailable_count == 3


def test_sg_mapper_empty_payload_is_safe():
    resp = _sg_mapper()._capability_response_from_expert_payload(
        {},
        agent_name="group-a",
        agent_url="http://group-a",
    )
    assert resp.can_handle is False
    assert resp.is_chain_scored is False
    assert resp.domain_verdict == ""
    assert resp.member_results == []
    assert resp.route_path == ["group-a"]
