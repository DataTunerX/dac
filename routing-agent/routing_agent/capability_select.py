"""Routing-side helpers for capability-chain scored broadcast results.

Skill-agent (``CAPABILITY_EVALUATION_SCORING_DESIGN.md``) is the only place
that *scores*.  Routing only:

* keeps / drops candidates with a fixed threshold rule
* ranks them with a fixed key so A/B evidence beats C/D at the same score
* decides whether a single-root fast path is allowed
* decides whether a contributor-only set should go to multi-root composition

No content-based scoring lives here.
"""

from __future__ import annotations

from typing import Any, Iterable

EVIDENCE_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}
# Legacy single-score judgements have no evidence grade; treat them as B so
# they neither outrank a chain-scored A nor lose to a chain-scored C by default.
LEGACY_EVIDENCE_RANK = 2
TRUSTED_EVIDENCE_GRADES = frozenset({"A", "B"})


def is_chain_scored(resp: Any) -> bool:
    if bool(getattr(resp, "is_chain_scored", False)):
        return True
    return bool(str(getattr(resp, "score_version", "") or "").strip())


def evidence_rank(resp: Any) -> int:
    if not is_chain_scored(resp):
        return LEGACY_EVIDENCE_RANK
    grade = str(getattr(resp, "evidence_grade", "") or "").strip().upper()
    return EVIDENCE_RANK.get(grade, 0)


def sort_key(resp: Any) -> tuple[int, int, float]:
    """Descending sort key: handle first, then evidence, then confidence."""
    can_handle = 1 if getattr(resp, "can_handle", False) else 0
    try:
        conf = float(getattr(resp, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return (can_handle, evidence_rank(resp), conf)


def keep_after_broadcast_threshold(resp: Any, threshold: float) -> bool:
    """Whether a capable response survives the routing broadcast threshold.

    * ``can_handle``: must meet ``threshold`` (same as before).
    * chain-scored ``can_contribute``: keep unconditionally — the agent already
      gated contribution on step_score >= 0.7 and a complete contribution
      statement.  Filtering again by the legacy 0.5 band would drop the
      wrong people (contribute confidence is a *step* score, not a
      whole-query score).
    * legacy ``can_contribute``: still must meet ``threshold``.
    """
    can_handle = bool(getattr(resp, "can_handle", False))
    can_contribute = bool(getattr(resp, "can_contribute", False))
    try:
        conf = float(getattr(resp, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if can_handle:
        return conf >= threshold
    if can_contribute:
        if is_chain_scored(resp):
            return True
        return conf >= threshold
    return False


def evidence_trusted_for_fast_path(resp: Any) -> bool:
    """C/D (or missing) chain evidence must not skip multi-root composition."""
    if not is_chain_scored(resp):
        return True
    grade = str(getattr(resp, "evidence_grade", "") or "").strip().upper()
    return grade in TRUSTED_EVIDENCE_GRADES


def partition_route_candidates(
    capable_agents: Iterable[tuple[Any, Any]],
    handle_threshold: float,
) -> tuple[list[tuple[Any, Any]], list[tuple[Any, Any]]]:
    """Split capable agents into high-confidence handlers vs contributors."""
    handlers: list[tuple[Any, Any]] = []
    contributors: list[tuple[Any, Any]] = []
    for card, resp in capable_agents:
        try:
            conf = float(getattr(resp, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if getattr(resp, "can_handle", False) and conf >= handle_threshold:
            handlers.append((card, resp))
        elif (
            (not getattr(resp, "can_handle", False))
            and getattr(resp, "can_contribute", False)
            and (conf >= handle_threshold or is_chain_scored(resp))
        ):
            contributors.append((card, resp))
    handlers.sort(key=lambda x: sort_key(x[1]), reverse=True)
    contributors.sort(key=lambda x: sort_key(x[1]), reverse=True)
    return handlers, contributors


def should_compose_contributors_only(
    handlers: list,
    contributors: list,
    min_contributors: int = 2,
) -> bool:
    """No one can finish the query alone, but several agents can each do a step."""
    return (not handlers) and len(contributors) >= min_contributors
