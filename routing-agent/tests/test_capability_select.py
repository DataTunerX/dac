"""Unit tests for routing-side capability-chain selection helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routing_agent.capability_select import (  # noqa: E402
    evidence_rank,
    evidence_trusted_for_fast_path,
    keep_after_broadcast_threshold,
    partition_route_candidates,
    should_compose_contributors_only,
    sort_key,
)


def _resp(**kwargs):
    defaults = dict(
        can_handle=False,
        can_contribute=False,
        confidence=0.0,
        score_version="",
        evidence_grade="",
        is_chain_scored=False,
    )
    defaults.update(kwargs)
    if defaults["score_version"]:
        defaults["is_chain_scored"] = True
    return SimpleNamespace(**defaults)


def test_legacy_evidence_ranks_as_b():
    assert evidence_rank(_resp()) == 2


def test_chain_evidence_rank_order():
    assert evidence_rank(_resp(score_version="capability-chain-v1", evidence_grade="A")) == 3
    assert evidence_rank(_resp(score_version="capability-chain-v1", evidence_grade="D")) == 0
    assert evidence_rank(_resp(score_version="capability-chain-v1", evidence_grade="")) == 0


def test_sort_handle_beats_contribute_even_if_contribute_score_is_higher():
    handle = _resp(can_handle=True, confidence=0.7, score_version="capability-chain-v1", evidence_grade="A")
    contrib = _resp(
        can_contribute=True, confidence=1.0, score_version="capability-chain-v1", evidence_grade="A"
    )
    assert sort_key(handle) > sort_key(contrib)


def test_sort_same_handle_prefers_stronger_evidence():
    a = _resp(can_handle=True, confidence=0.9, score_version="capability-chain-v1", evidence_grade="A")
    d = _resp(can_handle=True, confidence=0.9, score_version="capability-chain-v1", evidence_grade="D")
    assert sort_key(a) > sort_key(d)


def test_broadcast_threshold_handle_must_meet():
    low = _resp(can_handle=True, confidence=0.4)
    assert keep_after_broadcast_threshold(low, 0.5) is False
    ok = _resp(can_handle=True, confidence=0.7)
    assert keep_after_broadcast_threshold(ok, 0.5) is True


def test_broadcast_threshold_bypassed_for_chain_contributor():
    # Contribute confidence is a step score; do not re-apply the 0.5 whole-query band.
    chain = _resp(
        can_contribute=True,
        confidence=0.4,
        score_version="capability-chain-v1",
        evidence_grade="A",
    )
    assert keep_after_broadcast_threshold(chain, 0.5) is True


def test_broadcast_threshold_still_applies_to_legacy_contributor():
    legacy = _resp(can_contribute=True, confidence=0.4)
    assert keep_after_broadcast_threshold(legacy, 0.5) is False
    ok = _resp(can_contribute=True, confidence=0.6)
    assert keep_after_broadcast_threshold(ok, 0.5) is True


def test_fast_path_requires_a_or_b_evidence_for_chain_scores():
    assert evidence_trusted_for_fast_path(
        _resp(score_version="capability-chain-v1", evidence_grade="A")
    )
    assert evidence_trusted_for_fast_path(
        _resp(score_version="capability-chain-v1", evidence_grade="B")
    )
    assert not evidence_trusted_for_fast_path(
        _resp(score_version="capability-chain-v1", evidence_grade="C")
    )
    assert not evidence_trusted_for_fast_path(
        _resp(score_version="capability-chain-v1", evidence_grade="D")
    )
    assert evidence_trusted_for_fast_path(_resp())  # legacy


def test_partition_and_compose_zhangsan_case():
    """Design 12.1 + 12.2: both agents contribute, neither can_handle."""
    user = (
        SimpleNamespace(name="user-agent"),
        _resp(
            can_contribute=True,
            confidence=1.0,
            score_version="capability-chain-v1",
            evidence_grade="A",
        ),
    )
    order = (
        SimpleNamespace(name="order-agent"),
        _resp(
            can_contribute=True,
            confidence=1.0,
            score_version="capability-chain-v1",
            evidence_grade="A",
        ),
    )
    handlers, contributors = partition_route_candidates([user, order], 0.6)
    assert handlers == []
    assert [c.name for c, _ in contributors] == ["user-agent", "order-agent"]
    assert should_compose_contributors_only(handlers, contributors) is True


def test_partition_single_handler_no_compose():
    handler = (
        SimpleNamespace(name="order-agent"),
        _resp(
            can_handle=True,
            can_contribute=True,
            confidence=0.7,
            score_version="capability-chain-v1",
            evidence_grade="A",
        ),
    )
    handlers, contributors = partition_route_candidates([handler], 0.6)
    assert len(handlers) == 1
    assert contributors == []
    assert should_compose_contributors_only(handlers, contributors) is False


def test_one_contributor_is_not_enough_to_compose():
    only = [
        (
            SimpleNamespace(name="user-agent"),
            _resp(can_contribute=True, confidence=1.0, score_version="capability-chain-v1", evidence_grade="A"),
        )
    ]
    handlers, contributors = partition_route_candidates(only, 0.6)
    assert should_compose_contributors_only(handlers, contributors) is False
