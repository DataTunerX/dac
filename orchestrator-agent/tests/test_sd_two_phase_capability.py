"""Unit tests for SD two-phase capability check (skill-agent scheme)."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent import capability_chain
from orchestrator_agent import orchestrator_agent_semantic_domain as domain
from orchestrator_agent import skill_capability_two_phase as skill_cc


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        return SimpleNamespace(content=self.responses.pop(0))


def _domain_json(verdict: str, reason: str = "领域交集测试") -> str:
    return json.dumps({"domain_verdict": verdict, "reason": reason}, ensure_ascii=False)


def _chain_json(*, d_matched, d_required=None, contribution="输入用户名，输出订单列表") -> str:
    required = list(d_required if d_required is not None else d_matched)
    matched = list(d_matched)
    ratio = (len(matched) / len(required)) if required else 1.0
    payload = {
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
                    "ratio": ratio,
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
        "contribution": contribution,
        "missing_requirements": [] if ratio >= 1.0 else ["外部数据"],
        "risks": [],
        "reason": "步骤1：测试链打分",
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_domain_none_skips_phase2():
    llm = _FakeLLM([_domain_json("none", "领域交集：明确无 — 工伤认定")])
    result = await skill_cc.run_two_phase_capability_check(
        llm,
        query="工伤认定流程怎么办",
        agent_name="OrdersAgent",
        agent_description="电商订单域",
        agent_skills="tables_detail: orders(订单)",
    )
    assert result.domain_verdict == "none"
    assert result.can_handle is False
    assert result.can_contribute is False
    assert result.phase2_invoked is False
    assert result.confidence == 0.0
    assert len(llm.calls) == 1
    joined = str(llm.calls[0][0].content)
    assert "领域相关判定员" in joined
    assert "工伤认定流程怎么办" in joined
    assert "tables_detail: orders(订单)" in joined


@pytest.mark.asyncio
async def test_uncertain_enters_phase2_and_injects_domain_info():
    llm = _FakeLLM(
        [
            _domain_json("uncertain", "领域交集：不确定 — 描述模糊"),
            _chain_json(d_matched=["订单表"], d_required=["订单表"]),
        ]
    )
    result = await skill_cc.run_two_phase_capability_check(
        llm,
        query="查一下订单状态",
        agent_name="OrdersAgent",
        agent_description="订单域",
        agent_skills="orders table",
    )
    assert result.phase2_invoked is True
    assert result.domain_verdict == "uncertain"
    assert result.can_handle is True
    assert len(llm.calls) == 2
    chain_prompt = str(llm.calls[1][0].content)
    assert "domain_verdict: uncertain" in chain_prompt
    assert "你不负责：判定 can_handle" in chain_prompt
    assert "你不负责：判定领域交不交叠" in chain_prompt


@pytest.mark.asyncio
async def test_has_then_chain_aggregate_handle():
    llm = _FakeLLM(
        [
            _domain_json("has", "领域交集：明确有 — 订单"),
            _chain_json(d_matched=["订单表"], d_required=["订单表"]),
        ]
    )
    result = await skill_cc.run_two_phase_capability_check(
        llm,
        query="查一下订单 ORD-001 的状态",
        agent_name="OrdersAgent",
        agent_description="订单域",
        agent_skills="1. table name: orders(订单)",
    )
    assert result.domain_verdict == "has"
    assert result.can_handle is True
    assert result.can_contribute is True
    assert result.score_version == capability_chain.SCORE_VERSION
    assert result.steps
    mapped = domain._member_response_from_two_phase(
        result,
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert mapped["evidence_mode"] == "capability_chain"
    assert mapped["domain_match"] is True
    assert mapped["domain_verdict"] == "has"
    assert "订单表" in mapped["matched_evidence"]


@pytest.mark.asyncio
async def test_domain_has_but_d_zero_cannot_handle():
    llm = _FakeLLM(
        [
            _domain_json("has", "能参与用户名面"),
            _chain_json(d_matched=[], d_required=["订单", "商品"], contribution=""),
        ]
    )
    result = await skill_cc.run_two_phase_capability_check(
        llm,
        query="张三买了哪些东西",
        agent_name="UserAgent",
        agent_description="用户域",
        agent_skills="users(用户)",
    )
    assert result.domain_verdict == "has"
    assert result.phase2_invoked is True
    assert result.can_handle is False
    mapped = domain._member_response_from_two_phase(
        result,
        agent_name="UserAgent",
        agent_url="http://users:10100",
        descriptor_type="structured-mysql",
    )
    assert mapped["can_handle"] is False
    assert mapped["domain_match"] is True


@pytest.mark.asyncio
async def test_sd_judge_uses_two_phase_and_inventory(monkeypatch):
    captured = {}

    async def fake_run(llm, **kwargs):
        captured.update(kwargs)
        captured["llm"] = llm
        return skill_cc.TwoPhaseResult(
            domain_verdict="none",
            reason="领域交集：明确无",
            phase2_invoked=False,
        )

    monkeypatch.setattr(skill_cc, "run_two_phase_capability_check", fake_run)
    executor = domain.OrchestratorAgentExecutorSemanticDomain(
        agent_id="OrdersAgent",
        agent_card=SimpleNamespace(name="OrdersAgent", url="http://orders:10100"),
    )
    monkeypatch.setattr(
        executor, "_build_capability_judge_llm", lambda: object()
    )
    result = await executor._judge_member_capability_with_llm(
        query="工伤认定流程",
        signatures=[
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "电商订单域",
                "agent_card": {"description": "订单专家"},
                "metadata_content": {
                    "tables_detail": "1. table name: orders(订单)"
                },
            }
        ],
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert captured["query"] == "工伤认定流程"
    assert "电商订单域" in captured["agent_description"]
    assert "orders(订单)" in captured["agent_skills"]
    assert result["domain_verdict"] == "none"
    assert result["can_handle"] is False
    assert result["can_contribute"] is False
    assert result["evidence_mode"] == "capability_chain"


@pytest.mark.asyncio
async def test_legacy_flag_uses_old_judge(monkeypatch):
    monkeypatch.setenv("SD_MEMBER_CAPABILITY_LEGACY_JUDGE", "true")
    executor = domain.OrchestratorAgentExecutorSemanticDomain(agent_id="OrdersAgent")
    executor._legacy_judge_member_capability_with_llm = AsyncMock(
        return_value={"can_handle": True, "evidence_mode": "llm", "domain_match": True}
    )
    two_phase = AsyncMock()
    monkeypatch.setattr(skill_cc, "run_two_phase_capability_check", two_phase)
    result = await executor._judge_member_capability_with_llm(
        query="q",
        signatures=[],
        agent_name="OrdersAgent",
        agent_url="http://x",
        descriptor_type="structured-mysql",
    )
    assert result["evidence_mode"] == "llm"
    executor._legacy_judge_member_capability_with_llm.assert_awaited_once()
    two_phase.assert_not_awaited()


def test_prompts_match_skill_agent_source():
    source = skill_cc._skill_agent_source_path()
    if source is None:
        pytest.skip("skill-agent source not beside orchestrator-agent")
    extracted = skill_cc._extract_string_assigns(
        source, ("DOMAIN_CHECK_PROMPT", "SKILL_CAPABILITY_CHECK_PROMPT")
    )
    assert skill_cc.DOMAIN_CHECK_PROMPT == extracted["DOMAIN_CHECK_PROMPT"]
    assert skill_cc.SKILL_CAPABILITY_CHECK_PROMPT == extracted["SKILL_CAPABILITY_CHECK_PROMPT"]
    assert "领域相关判定员" in skill_cc.DOMAIN_CHECK_PROMPT
    assert "你不负责：判定 can_handle" in skill_cc.SKILL_CAPABILITY_CHECK_PROMPT
    assert "你不负责：判定领域交不交叠" in skill_cc.SKILL_CAPABILITY_CHECK_PROMPT
