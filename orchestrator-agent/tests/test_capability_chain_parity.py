"""Parity guard: orchestrator ``capability_chain`` must match skill-agent's formula.

The orchestrator copy is a hand-maintained sibling of
``skill-agent/agent/capability_chain.py``. Prompts are already pinned to the
live skill-agent source at import time; this test does the same for the
aggregation formula so a rule change cannot silently land on only one side.

Mirrors skill-agent ``tests/test_capability_chain.py``'s domain-mismatch cases.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent import capability_chain as cc


def _rc(required, matched, evidence_strength="solid"):
    return cc.RatioCheck(
        required=list(required),
        matched=list(matched),
        ratio=(len(matched) / len(required)) if required else 1.0,
        evidence_strength=evidence_strength,
    )


def _step(
    step_id,
    *,
    is_final,
    I,
    D,
    R,
    O=1.0,
    C=None,
    inputs=None,
    outputs=None,
    operation="retrieve",
):
    return cc.StepEvaluation(
        step_id=step_id,
        description=f"step {step_id}",
        operation=operation,
        is_final=is_final,
        inputs=list(inputs or []),
        outputs=list(outputs or []),
        constraints=[],
        input_match=I,
        data_coverage=D,
        operation_capability=O,
        result_match=R,
        constraint_satisfaction=C or _rc([], [], evidence_strength="solid"),
    )


def _result(steps, *, contribution="", missing=None, grade="A", reason="test"):
    return cc.CapabilityChainResult(
        steps=list(steps),
        evidence_grade=grade,
        contribution=contribution,
        missing_requirements=list(missing or []),
        risks=[],
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Domain-mismatch hard gate (parity with skill-agent)
# ---------------------------------------------------------------------------


def test_domain_mismatch_all_d_zero_solid_forces_cannot_handle():
    """All steps D=0(solid) → domain mismatch, regardless of I/O/R/C scores."""
    s1 = _step(
        1,
        is_final=True,
        inputs=[cc.InputItem(name="问题", source="query")],
        outputs=["结论"],
        I=_rc(["问题"], ["问题"]),
        D=_rc(["劳动法", "辞退补偿"], []),
        O=1.0,
        R=_rc(["结论"], ["结论"]),
    )
    # Without the gate this scores (1+0+1+1+1)/5 = 0.8 >= 0.7 → can_handle=True
    agg = cc.aggregate(_result([s1], grade="D"), threshold=0.7)

    assert agg.can_handle is False
    assert agg.can_contribute is False
    assert agg.confidence == 0.0
    assert agg.handle_score == 0.0
    assert agg.contributing_steps == []


def test_domain_mismatch_multiple_steps_all_d_zero_solid():
    """Gate also fires when the LLM splits the out-of-domain query into steps."""
    s1 = _step(
        1,
        is_final=False,
        inputs=[cc.InputItem(name="问题", source="query")],
        outputs=["政策条款"],
        I=_rc(["问题"], ["问题"]),
        D=_rc(["劳动合同法"], []),
        R=_rc(["政策条款"], []),
    )
    s2 = _step(
        2,
        is_final=True,
        inputs=[cc.InputItem(name="政策条款", source="upstream")],
        outputs=["结论"],
        I=_rc(["政策条款"], ["政策条款"]),
        D=_rc(["辞退补偿标准"], []),
        R=_rc(["结论"], ["结论"]),
    )
    agg = cc.aggregate(_result([s1, s2], grade="D"), threshold=0.7)

    assert agg.can_handle is False
    assert agg.can_contribute is False
    assert agg.handle_score == 0.0


def test_partial_d_zero_solid_is_not_gated():
    """Only some steps D=0(solid) → normal scoring, contribution still possible."""
    s1 = _step(
        1,
        is_final=False,
        inputs=[cc.InputItem(name="订单号", source="query")],
        outputs=["订单明细"],
        I=_rc(["订单号"], ["订单号"]),
        D=_rc(["订单表"], ["订单表"]),
        R=_rc(["订单明细"], ["订单明细"]),
    )
    s2 = _step(
        2,
        is_final=True,
        inputs=[cc.InputItem(name="订单明细", source="upstream")],
        outputs=["退款率"],
        I=_rc(["订单明细"], ["订单明细"]),
        D=_rc(["退款表"], []),
        R=_rc(["退款率"], []),
    )
    agg = cc.aggregate(_result([s1, s2]), threshold=0.7)

    assert agg.handle_score > 0.0
    assert agg.can_handle is False  # step 2 below threshold
    assert agg.can_contribute is True
    assert agg.contributing_steps == [1]


def test_d_zero_speculative_is_not_gated():
    """D=0(speculative) is LLM guesswork, not a domain-mismatch fact."""
    s1 = _step(
        1,
        is_final=True,
        inputs=[cc.InputItem(name="订单号", source="query")],
        outputs=["订单明细"],
        I=_rc(["订单号"], ["订单号"]),
        D=_rc(["订单表"], [], evidence_strength="speculative"),
        R=_rc(["订单明细"], ["订单明细"]),
    )
    agg = cc.aggregate(_result([s1]), threshold=0.7)

    assert agg.can_handle is True
    assert agg.handle_score > 0.0


def test_empty_steps_is_not_gated():
    agg = cc.aggregate(_result([]), threshold=0.7)

    assert agg.can_handle is False
    assert agg.can_contribute is False


# ---------------------------------------------------------------------------
# Live parity with skill-agent source, when the sibling tree is present
# ---------------------------------------------------------------------------

_SKILL_SOURCE = (
    Path(__file__).resolve().parents[2] / "skill-agent" / "agent" / "capability_chain.py"
)


def _read_skill_aggregate() -> str | None:
    if not _SKILL_SOURCE.is_file():
        return None
    source = _SKILL_SOURCE.read_text(encoding="utf-8")
    marker = "def aggregate("
    start = source.find(marker)
    if start < 0:
        return None
    rest = source[start:]
    return rest[: rest.find("\ndef ", 1)]


def test_orchestrator_aggregate_covers_skill_agent_domain_gate():
    source = _read_skill_aggregate()
    if source is None:
        pytest.skip("skill-agent source not beside orchestrator-agent")

    gate_marker = 's.data_coverage.ratio == 0.0 and s.data_coverage.evidence_strength == "solid"'
    if gate_marker not in source:
        pytest.skip("skill-agent no longer defines the domain-mismatch gate")

    own = (
        Path(__file__).resolve().parents[1]
        / "orchestrator_agent"
        / "capability_chain.py"
    ).read_text(encoding="utf-8")
    assert gate_marker in own, (
        "skill-agent aggregate has the D=0(solid) domain-mismatch gate but the "
        "orchestrator copy does not; port it or remove it from both."
    )