"""Unit tests for mid-delegate remote SG selection via capability_check."""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator_agent.broadcast_capability_check as bcc
import orchestrator_agent.orchestrator_agent_semantic_group as sg


def _card(name, url=None):
    return SimpleNamespace(name=name, url=url or f"http://{name}", description=f"{name} desc")


def _resp(**overrides):
    values = {
        "can_handle": False,
        "can_contribute": False,
        "confidence": 0.5,
        "reason": "",
        "contribution": "",
        "agent_name": "peer",
        "execution_hint": {},
    }
    values.update(overrides)
    return bcc.CapabilityCheckResponse(**values)


def test_normalize_drops_weather_contributor_on_business_query():
    resp = _resp(
        can_contribute=True,
        confidence=0.95,
        agent_name="weather-agent",
        contribution="该查询需要访问订单表。本 Agent 仅具备 weather 技能，无法访问任何业务数据库。",
        reason="用户问题为查询特定订单，属于垂直业务库查询。",
    )
    normalized = bcc.normalize_capability_check_response(resp)
    assert normalized.can_contribute is False


def test_format_capability_evidence_for_planner_includes_roles():
    text = bcc.format_capability_evidence_for_planner(
        [
            (
                _card("sg-a"),
                _resp(can_handle=True, confidence=0.91, reason="covers membership"),
            ),
            (
                _card("sg-b"),
                _resp(
                    can_contribute=True,
                    confidence=0.7,
                    contribution="can supply user_ids",
                ),
            ),
        ]
    )
    assert "capability_check" in text
    assert "sg-a" in text and "role=handle" in text
    assert "sg-b" in text and "role=contribute" in text
    assert "covers membership" in text


def test_probe_agents_capability_concurrent_filters_and_ranks(monkeypatch):
    cards = [_card("a"), _card("b"), _card("c")]

    async def _fake_send(query, card, *_args, **_kwargs):
        mapping = {
            "a": _resp(
                can_contribute=True,
                confidence=0.6,
                agent_name="a",
                contribution="can provide membership tier fields",
            ),
            "b": _resp(can_handle=True, confidence=0.8, agent_name="b"),
            "c": None,
        }
        return mapping[card.name]

    monkeypatch.setattr(bcc, "send_capability_check", _fake_send)

    pairs = asyncio.run(
        bcc.probe_agents_capability_concurrent(
            "membership discount",
            cards,
            "u1",
            "r1",
            "t1",
            max_concurrency=4,
        )
    )
    assert [c.name for c, _ in pairs] == ["b", "a"]
    assert pairs[0][1].can_handle is True


def test_select_mid_delegate_single_round_broadcast_ranks_soft_hints(monkeypatch):
    """One concurrent broadcast round; soft hints only break equal-confidence ties."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="self-sg-xxx")
    executor.agent_id = "self-sg-xxx"
    executor.semantic_group_id = "self-sg-xxx"

    soft = _card("hint-sg-aaa")
    other = _card("other-sg-bbb")
    cards = [soft, other]

    calls: list[list[str]] = []

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        names = [c.name for c in probe_cards]
        calls.append(names)
        assert "跨 SG 补数子任务" in (query or "")
        return [
            (
                other,
                _resp(
                    can_handle=True,
                    confidence=0.88,
                    agent_name="other-sg-bbb",
                    reason="member evidence",
                    execution_hint={
                        "version": "v1",
                        "selected_members": ["member-dd"],
                        "can_handle": True,
                    },
                ),
            ),
            (
                soft,
                _resp(
                    can_handle=True,
                    confidence=0.88,
                    agent_name="hint-sg-aaa",
                    reason="soft-hinted peer also capable",
                ),
            ),
        ]

    async def _fake_list(*, collection_name=None):
        return cards + [_card("self-sg-xxx")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="查会员折扣率",
            collaborator_cards=cards,
            soft_target_hints=["hint-sg-aaa"],
            user_id="u",
            run_id="r",
            trace_id="t",
        )
    )

    assert len(calls) == 1
    assert set(calls[0]) == {"hint-sg-aaa", "other-sg-bbb"}
    # Equal confidence → soft hint ranks first.
    assert result["target_sg_names"][0] == "hint-sg-aaa"
    assert "other-sg-bbb" in result["target_sg_names"]
    assert result["hints_by_sg"]["other-sg-bbb"]["selected_members"] == ["member-dd"]
    assert "member evidence" in result["evidence_text"]


def test_select_mid_delegate_higher_confidence_beats_soft_hint(monkeypatch):
    """Capability confidence outranks soft_hint when both can_handle."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="self-sg-xxx")
    executor.agent_id = "self-sg-xxx"

    soft = _card("hint-sg-aaa")
    other = _card("other-sg-bbb")

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        return [
            (soft, _resp(can_handle=True, confidence=0.70, agent_name="hint-sg-aaa")),
            (other, _resp(can_handle=True, confidence=0.95, agent_name="other-sg-bbb")),
        ]

    async def _fake_list(*, collection_name=None):
        return [soft, other, _card("self-sg-xxx")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="查会员折扣率",
            collaborator_cards=[soft, other],
            soft_target_hints=["hint-sg-aaa"],
        )
    )
    assert result["target_sg_names"][0] == "other-sg-bbb"


def test_select_mid_delegate_soft_hint_fallback_when_capability_empty(monkeypatch):
    """Detect named a peer but every capability_check returns false → still select hint."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg-aaa")
    executor.agent_id = "order-sg-aaa"

    user = _card("UserAccountPaymentAgent-sg-42627bb7")
    other = _card("weather-sg-zzz")

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        return []

    async def _fake_list(*, collection_name=None):
        return [user, other, _card("order-sg-aaa")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)
    monkeypatch.setenv("SG_MID_DELEGATE_SOFT_HINT_FALLBACK", "true")

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="请查询 user_id=1 的用户详细信息",
            collaborator_cards=[user, other],
            soft_target_hints=["UserAccountPaymentAgent-sg-42627bb7"],
        )
    )
    assert result["target_sg_names"] == ["UserAccountPaymentAgent-sg-42627bb7"]
    assert "soft_hint fallback" in (result["evidence_text"] or "").lower() or (
        result["capable_pairs"]
        and "soft_hint fallback" in (result["capable_pairs"][0][1].reason or "")
    )


def test_select_mid_delegate_resolves_soft_hint_from_extra_cards(monkeypatch):
    """Soft hint only present on collaborator_cards must still enter the probe set."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg-aaa")
    executor.agent_id = "order-sg-aaa"

    user = _card("user-sg-bbb")
    probed: list[str] = []

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        names = [c.name for c in probe_cards]
        probed.extend(names)
        if "user-sg-bbb" in names:
            return [
                (
                    next(c for c in probe_cards if c.name == "user-sg-bbb"),
                    _resp(can_handle=True, confidence=0.9, agent_name="user-sg-bbb"),
                )
            ]
        return []

    async def _fake_list(*, collection_name=None):
        # Registry listing missed the soft-hint peer.
        return [_card("order-sg-aaa"), _card("other-sg-ccc")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="查用户姓名",
            collaborator_cards=[user],
            soft_target_hints=["user-sg-bbb"],
        )
    )
    assert "user-sg-bbb" in probed
    assert result["target_sg_names"] == ["user-sg-bbb"]


def test_select_mid_delegate_includes_all_registry_agents(monkeypatch):
    """Previously-delegated agents should NOT be excluded from the candidate pool
    — the same agent may need to be called again with a different synthesized_query."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="self-sg-xxx")
    executor.agent_id = "self-sg-xxx"

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        # Both done-sg-aaa and fresh-sg-bbb should be in the probe set
        names = [c.name for c in probe_cards]
        assert "done-sg-aaa" in names, "previously-delegated agents should still be probed"
        assert "fresh-sg-bbb" in names
        return [
            (
                [c for c in probe_cards if c.name == "fresh-sg-bbb"][0],
                _resp(can_handle=True, confidence=0.9, agent_name="fresh-sg-bbb"),
            )
        ]

    async def _fake_list(*, collection_name=None):
        return [_card("done-sg-aaa"), _card("fresh-sg-bbb"), _card("self-sg-xxx")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="q",
            collaborator_cards=[_card("done-sg-aaa"), _card("fresh-sg-bbb")],
        )
    )
    assert result["target_sg_names"] == ["fresh-sg-bbb"]


def test_select_mid_delegate_empty_peer_pool_broadcasts_registry(monkeypatch):
    """Routing peer pool empty must still broadcast full SG registry."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg-aaa")
    executor.agent_id = "order-sg-aaa"

    user_sg = _card("user-sg-bbb")
    calls = []

    async def _fake_probe(query, probe_cards, *_args, **_kwargs):
        names = [c.name for c in probe_cards]
        calls.append(names)
        if "user-sg-bbb" in names:
            return [
                (
                    user_sg,
                    _resp(can_handle=True, confidence=0.93, agent_name="user-sg-bbb"),
                )
            ]
        return []

    async def _fake_list(*, collection_name=None):
        return [_card("weather-agent"), user_sg, _card("order-sg-aaa")]

    monkeypatch.setattr(sg.sg_broadcast, "probe_agents_capability_concurrent", _fake_probe)
    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)

    result = asyncio.run(
        executor._select_mid_delegate_targets_via_capability(
            synthesized_query="请根据 user_id=1 查询下单用户姓名",
            collaborator_cards=[],  # empty routing peer pool
        )
    )
    assert calls and "user-sg-bbb" in calls[0]
    assert result["target_sg_names"] == ["user-sg-bbb"]


def test_load_mid_exec_broadcast_candidates_excludes_self_and_non_sg(monkeypatch):
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg-aaa")
    executor.agent_id = "order-sg-aaa"

    async def _fake_list(*, collection_name=None):
        return [
            _card("order-sg-aaa"),
            _card("user-sg-bbb"),
            _card("weather-agent"),  # no -sg- token
        ]

    monkeypatch.setattr(sg.sg_broadcast, "list_all_orchestrator_agent_cards", _fake_list)
    cards = asyncio.run(executor._load_mid_exec_broadcast_candidates())
    assert [c.name for c in cards] == ["user-sg-bbb"]


def test_structured_detect_keeps_signal_without_local_owner():
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg")
    weather = _card("weather-agent")
    weather.description = "weather skill only"
    result = executor._detect_delegation_via_structured(
        query="查询订单下单用户姓名，并汇总订单消费总额以便完整回答原问题",
        own_results={
            1: (
                "partial success\n"
                'structured_control: {"reason_code":"data_sovereignty_gap",'
                '"outcome":"partial","join_keys":{"user_id":["1"]},'
                '"unfulfilled_needs":[{"missing_table":"users",'
                '"reason":"outside_local_dd","intent_fragment":"下单用户姓名",'
                '"stage":"observe_partial"}]}'
            )
        },
        collaborator_cards=[weather],
        delegated_results={},
    )
    assert result is not None
    assert result["target_sgs"] == []
    synth = result["synthesized_query"]
    assert "user_id=1" in synth
    assert "下单用户姓名" in synth
    # Scoped: must not embed the full original multi-domain ask.
    assert "原始问题" not in synth
    assert "消费总额" not in synth
    assert "完整回答原问题" not in synth
    assert result["join_keys"]["user_id"] == ["1"]


def test_structured_detect_works_with_empty_collaborator_cards():
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg")
    result = executor._detect_delegation_via_structured(
        query="查用户姓名",
        own_results={
            1: (
                'structured_control: {"reason_code":"data_sovereignty_gap",'
                '"outcome":"partial","join_keys":{"user_id":["1","2"]},'
                '"unfulfilled_needs":[{"missing_table":"users",'
                '"reason":"outside_local_dd","intent_fragment":"用户姓名",'
                '"stage":"observe_partial"}]}'
            )
        },
        collaborator_cards=[],
        delegated_results={},
    )
    assert result is not None
    assert result["target_sgs"] == []
    assert "user_id=1,2" in result["synthesized_query"]


def test_apply_scoped_mid_exec_task_descriptions_overwrites_bloated_plan():
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    plan = SimpleNamespace(
        tasks=[
            SimpleNamespace(
                id=1,
                agent="user-sg-bbb",
                description=(
                    "查询 user_id=1..25 的姓名，以便与订单统计关联并完整回答原问题"
                ),
            )
        ]
    )
    scoped = "请仅查询并返回以下信息：用户姓名。 关联键：user_id=1,2。"
    out = sg.OrchestratorAgentExecutorSemanticGroup._apply_scoped_mid_exec_task_descriptions(
        plan, scoped
    )
    assert out is plan
    assert plan.tasks[0].description == scoped


def test_detect_runs_with_empty_collaborator_cards(monkeypatch):
    """Empty routing peers must not skip detect; LLM can still request help."""
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor.agent_card = SimpleNamespace(name="order-sg-aaa")
    executor.llm_non_stream = object()
    executor.metadata = {}

    async def _fake_invoke(**_kwargs):
        return {
            "needs_help": True,
            "synthesized_query": "请根据 user_id=1 查询下单用户姓名",
            "target_sgs": [],
            "reason": "缺用户姓名但有 user_id",
        }

    monkeypatch.setattr(sg, "invoke_llm_with_tool", _fake_invoke)
    monkeypatch.setenv("ENABLE_STRUCTURED_DELEGATION_DETECT", "false")

    result = asyncio.run(
        executor._detect_delegation_needs(
            query="查订单下单用户姓名和收货电话",
            own_results={
                1: "收货电话 13800001001；user_id=1；下单用户姓名未能确认，users 表不在本域"
            },
            delegated_results={},
            collaborator_cards=[],
        )
    )
    assert result is not None
    assert "user_id=1" in result["synthesized_query"]
    assert result["source"] == "llm_detection"


def test_dispatch_forwards_execution_hint(monkeypatch):
    executor = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    executor._llm_dependent_query_refine_enabled = lambda: False
    executor._truncate_progress_message = lambda text, n: text[:n]
    executor._task_results_from_upstream_ctx = lambda _ctx: {}

    captured = {}

    async def _delegate(**kwargs):
        captured.update(kwargs)
        return "ok"

    agent = SimpleNamespace(
        agent_name="self-sg",
        delegate_to_collaborator_sg=AsyncMock(side_effect=_delegate),
    )
    target = _card("peer-sg")
    plan = SimpleNamespace(
        tasks=[
            SimpleNamespace(
                id=1,
                agent="peer-sg",
                description="查会员等级",
                depends_on=[],
            )
        ]
    )
    hint = {"version": "v1", "selected_members": ["m1"], "can_handle": True}

    results = asyncio.run(
        executor._dispatch_mid_exec_delegation(
            plan=plan,
            target_cards=[target],
            user_id="u",
            run_id="r",
            trace_id="t",
            current_hop=2,
            delegation_chain=["root"],
            upstream_context={"mid_exec_round": 1},
            is_delegated=False,
            agent=agent,
            execution_hints_by_sg={"peer-sg": hint},
        )
    )

    assert results == {"peer-sg": "ok"}
    assert captured["execution_hint"] == hint
    assert captured["target_card"].name == "peer-sg"
