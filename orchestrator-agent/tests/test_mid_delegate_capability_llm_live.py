"""Live LLM tests for mid-delegate capability-based remote SG selection.

Simulates the production path:

  mid-exec detect (LLM)
    → concurrent peer capability_check
    → each peer's member capability judgment (SD LLM)
    → select by can_handle / can_contribute

Network A2A is stubbed; the LLM judges are real DashScope calls.

Requires:
  DASHSCOPE_API_KEY
  DASHSCOPE_MODEL (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    python -m pytest tests/test_mid_delegate_capability_llm_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator_agent.broadcast_capability_check as bcc
import orchestrator_agent.orchestrator_agent_semantic_domain as domain
import orchestrator_agent.orchestrator_agent_semantic_group as sg


pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live LLM mid-delegate tests",
)

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")


PEER_DOMAINS: Dict[str, Dict[str, Any]] = {
    "MembershipSG": {
        "descriptor_type": "structured-mysql",
        "signatures": [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "会员体系与会员等级折扣管理",
                "agent_card": {
                    "description": "覆盖会员等级、折扣率、积分与会员权益"
                },
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: member_level(会员等级)，"
                        "key fields: level_code(等级编码)、discount_rate(折扣率)"
                    )
                },
            }
        ],
    },
    "OrderSG": {
        "descriptor_type": "structured-mysql",
        "signatures": [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "电商订单与交易履约",
                "agent_card": {"description": "订单、支付、发货与售后主数据"},
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: orders(订单)，"
                        "key fields: order_id(订单号)、user_id(用户)、amount(金额)"
                    )
                },
            }
        ],
    },
    "RocketSG": {
        "descriptor_type": "structured-mysql",
        "signatures": [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "航天推进与发动机试验",
                "agent_card": {"description": "火箭发动机推力与试验曲线"},
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: engine_thrust(推力曲线)，"
                        "key fields: engine_id、thrust_n、timestamp"
                    )
                },
            }
        ],
    },
}


def _sg_executor() -> sg.OrchestratorAgentExecutorSemanticGroup:
    return sg.OrchestratorAgentExecutorSemanticGroup(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
        stream=False,
        semantic_group_id="live-mid-sg",
        agent_id="LiveMidDelegateSG",
        agent_card=SimpleNamespace(
            name="LiveMidDelegateSG",
            url="http://live-mid-sg",
            description="local commerce SG under test",
            skills=[],
        ),
    )


def _sd_executor() -> domain.OrchestratorAgentExecutorSemanticDomain:
    return domain.OrchestratorAgentExecutorSemanticDomain(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
        data_descriptors=["live-mid-dd"],
        dd_namespace="default",
        agent_id="LiveMidDelegateSD",
    )


def _peer_cards() -> List[Any]:
    return [
        SimpleNamespace(name=name, url=f"http://{name.lower()}", description=f"{name} card")
        for name in PEER_DOMAINS
    ]


async def _peer_capability_via_real_sd_llm(
    query: str,
    peer_name: str,
    sd_executor: domain.OrchestratorAgentExecutorSemanticDomain,
) -> bcc.CapabilityCheckResponse:
    """Simulate peer SG capability_check by calling real SD member LLM judge."""
    peer = PEER_DOMAINS[peer_name]
    judged = await sd_executor._judge_member_capability_with_llm(
        query=query,
        signatures=peer["signatures"],
        agent_name=f"{peer_name}-dd",
        agent_url=f"http://{peer_name.lower()}-dd",
        descriptor_type=peer["descriptor_type"],
        request_metadata={
            "run_id": "live-mid-delegate",
            "trace_id": "b" * 32,
            "user_id": "live-mid-tester",
        },
    )
    can_handle = bool(judged.get("can_handle"))
    can_contribute = bool(judged.get("can_contribute"))
    hint = {}
    if can_handle or can_contribute:
        hint = {
            "version": "v1",
            "semantic_group_id": peer_name,
            "selected_members": [f"{peer_name}-dd"],
            "can_handle": can_handle,
            "can_contribute": can_contribute,
        }
    print(
        f"  [peer={peer_name}] domain_match={judged.get('domain_match')} "
        f"can_handle={can_handle} can_contribute={can_contribute} "
        f"confidence={judged.get('confidence')} reason={judged.get('reason')}"
    )
    return bcc.CapabilityCheckResponse(
        can_handle=can_handle,
        can_contribute=can_contribute,
        confidence=float(judged.get("confidence") or 0.0),
        reason=str(judged.get("reason") or ""),
        contribution=str(judged.get("contribution") or ""),
        agent_name=peer_name,
        agent_url=f"http://{peer_name.lower()}",
        missing_requirements=list(judged.get("missing_requirements") or []),
        execution_hint=hint,
        collaboration_agents=[f"{peer_name}-dd"] if (can_handle or can_contribute) else [],
    )


@pytest.mark.asyncio
async def test_live_mid_delegate_selects_membership_peer(monkeypatch):
    """Membership query should select MembershipSG, not Order/Rocket."""
    sg_executor = _sg_executor()
    sd_executor = _sd_executor()
    query = "查询各会员等级对应的折扣率是多少？"

    async def _fake_send(q, card, *_args, **_kwargs):
        return await _peer_capability_via_real_sd_llm(q, card.name, sd_executor)

    monkeypatch.setattr(bcc, "send_capability_check", _fake_send)

    result = await sg_executor._select_mid_delegate_targets_via_capability(
        synthesized_query=query,
        collaborator_cards=_peer_cards(),
        soft_target_hints=[],
        already_delegated={},
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )

    print(
        f"\n[select-membership] targets={result['target_sg_names']} "
        f"hints={list(result['hints_by_sg'].keys())}\n"
        f"evidence=\n{result['evidence_text']}"
    )

    assert "MembershipSG" in result["target_sg_names"]
    assert "RocketSG" not in result["target_sg_names"]
    assert result["hints_by_sg"]["MembershipSG"]["selected_members"] == [
        "MembershipSG-dd"
    ]


@pytest.mark.asyncio
async def test_live_mid_delegate_soft_hint_miss_falls_back(monkeypatch):
    """Wrong soft hint must not gate selection; capable peer still wins in one round."""
    sg_executor = _sg_executor()
    sd_executor = _sd_executor()
    query = "会员等级折扣率列表"

    async def _fake_send(q, card, *_args, **_kwargs):
        return await _peer_capability_via_real_sd_llm(q, card.name, sd_executor)

    monkeypatch.setattr(bcc, "send_capability_check", _fake_send)

    result = await sg_executor._select_mid_delegate_targets_via_capability(
        synthesized_query=query,
        collaborator_cards=_peer_cards(),
        soft_target_hints=["RocketSG"],  # intentionally wrong
        already_delegated={},
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )

    print(
        f"\n[soft-hint-miss] probed={result['probed_names']} "
        f"targets={result['target_sg_names']}"
    )

    assert "RocketSG" in result["probed_names"]
    assert "MembershipSG" in result["target_sg_names"]
    assert "RocketSG" not in result["target_sg_names"]


@pytest.mark.asyncio
async def test_live_mid_delegate_detect_gap_with_llm(monkeypatch):
    """Detect should flag a gap and synthesize a query; targets are soft only."""
    monkeypatch.setenv("ENABLE_STRUCTURED_DELEGATION_DETECT", "false")
    sg_executor = _sg_executor()

    detection = await sg_executor._detect_delegation_needs(
        query="统计上周订单量，并给出对应会员等级折扣率",
        own_results={
            1: (
                "已查到上周订单 1280 笔，涉及 user_id 列表："
                "[U1001,U1002,U1003]。缺少会员等级与折扣率信息。"
            )
        },
        delegated_results={},
        collaborator_cards=_peer_cards(),
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )

    print(f"\n[detect-gap] detection={detection}")
    assert detection is not None
    assert (detection.get("synthesized_query") or "").strip()
    # Soft hints may be empty; selection is capability_check's job.
    assert detection.get("source") == "llm_detection"


@pytest.mark.asyncio
async def test_live_mid_delegate_detect_no_gap_when_complete(monkeypatch):
    """When own results already answer the question, detect should stop."""
    monkeypatch.setenv("ENABLE_STRUCTURED_DELEGATION_DETECT", "false")
    sg_executor = _sg_executor()

    detection = await sg_executor._detect_delegation_needs(
        query="上周订单量是多少？",
        own_results={1: "上周订单总量为 1280 笔，已完整回答用户问题。"},
        delegated_results={},
        collaborator_cards=_peer_cards(),
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )

    print(f"\n[detect-no-gap] detection={detection}")
    assert detection is None


@pytest.mark.asyncio
async def test_live_mid_delegate_end_to_end_detect_then_select(monkeypatch):
    """Full mid-delegate decision: detect gap → concurrent capability select."""
    monkeypatch.setenv("ENABLE_STRUCTURED_DELEGATION_DETECT", "false")
    sg_executor = _sg_executor()
    sd_executor = _sd_executor()

    detection = await sg_executor._detect_delegation_needs(
        query="根据这些用户查会员折扣率：U1001,U1002",
        own_results={
            1: "已拿到用户标识 [U1001,U1002]，但本域没有会员等级/折扣率表。"
        },
        delegated_results={},
        collaborator_cards=_peer_cards(),
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )
    print(f"\n[e2e] detection={detection}")
    assert detection is not None
    synth = (detection.get("synthesized_query") or "").strip()
    assert synth

    async def _fake_send(q, card, *_args, **_kwargs):
        return await _peer_capability_via_real_sd_llm(q, card.name, sd_executor)

    monkeypatch.setattr(bcc, "send_capability_check", _fake_send)

    selection = await sg_executor._select_mid_delegate_targets_via_capability(
        synthesized_query=synth,
        collaborator_cards=_peer_cards(),
        soft_target_hints=list(detection.get("target_sgs") or []),
        already_delegated={},
        user_id="live-mid-tester",
        run_id="live-mid-delegate",
        trace_id="b" * 32,
    )
    print(
        f"[e2e] synth={synth}\n"
        f"[e2e] soft_hints={detection.get('target_sgs')}\n"
        f"[e2e] selected={selection['target_sg_names']}\n"
        f"[e2e] evidence=\n{selection['evidence_text']}"
    )

    assert "MembershipSG" in selection["target_sg_names"]
    assert "RocketSG" not in selection["target_sg_names"]
