"""Deterministic candidate shortlisting for routing capability checks.

Phase 0.6 of ``docs/MULTI_AGENT_V2_DESIGN.md``.

Routing currently sends a model-based capability check to every registered
agent, and each pre-plan candidate broadcasts again, so the number of model
calls per query grows with the square of the registry. This module ranks
candidates using registry metadata only — no model calls — so routing can check
a bounded set instead.

It ships in shadow mode first: the shortlist is computed and logged while the
full candidate set still decides the active route, which is what makes the
expected-lead recall gate measurable before anything is excluded.

Ranking signals, strongest first:

1. Explicit user target — pinned, never excluded by the cap.
2. Agent-name match against the query.
3. Skill id/name match.
4. Description overlap.

Chinese queries are tokenized as character bigrams, English as lowercase word
tokens, so both corpora produce usable overlap scores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

DEFAULT_TOP_K = 5

# Weights are ordinal, not calibrated: they order candidates, they are not
# evidence of executability (see design §8.5).
WEIGHT_EXPLICIT = 1000.0
WEIGHT_STATIC = 500.0
WEIGHT_NAME = 8.0
WEIGHT_SKILL = 4.0
WEIGHT_DESCRIPTION = 1.0

_ASCII_TOKEN = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_SPLIT_NAME = re.compile(r"[^a-z0-9㐀-鿿]+")


def tokenize(text: str) -> set[str]:
    """Lowercase ASCII words (length >= 2) plus CJK character bigrams."""
    raw = (text or "").lower()
    tokens = {t for t in _ASCII_TOKEN.findall(raw) if len(t) >= 2}

    cjk_runs = re.findall(r"[㐀-鿿豈-﫿]+", raw)
    for run in cjk_runs:
        if len(run) == 1:
            tokens.add(run)
            continue
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


GENERIC_NAME_TOKENS = frozenset({"agent", "tdb", "qa", "the", "and", "api", "svc"})


def _name_tokens(name: str) -> set[str]:
    """Tokens from an agent name, dropping generic words.

    The filter is applied after the union, not before it: "use a tdb agent"
    would otherwise give every TDB agent the same positive name score and make
    the ranking — and ``positive_score_count`` — meaningless.
    """
    parts = [p for p in _SPLIT_NAME.split((name or "").lower()) if p]
    tokens = {p for p in parts if len(p) >= 2}
    tokens |= tokenize(name)
    return {t for t in tokens if t not in GENERIC_NAME_TOKENS}


def _overlap(query_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    hits = query_tokens & candidate_tokens
    if not hits:
        return 0.0
    # Normalize by the query so a verbose agent description cannot dominate.
    return len(hits) / len(query_tokens)


@dataclass
class RankedCandidate:
    """One agent's shortlist position and the evidence behind it."""

    name: str
    score: float
    rank: int = 0
    included: bool = False
    explicit: bool = False
    static: bool = False
    signals: dict[str, float] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.explicit:
            return "explicit_target"
        if self.static:
            return "static_match"
        if self.score <= 0:
            return "no_metadata_match"
        strongest = max(self.signals, key=lambda k: self.signals[k], default="")
        return f"matched_on_{strongest}" if strongest else "scored"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.name,
            "rank": self.rank,
            "score": round(self.score, 4),
            "included": self.included,
            "explicit": self.explicit,
            "static": self.static,
            "reason": self.reason,
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "matched": self.matched[:8],
        }


@dataclass
class Shortlist:
    """Ranked candidates split into the proposed top-K and the rest."""

    k: int
    ranked: list[RankedCandidate]

    @property
    def included(self) -> list[RankedCandidate]:
        return [c for c in self.ranked if c.included]

    @property
    def excluded(self) -> list[RankedCandidate]:
        return [c for c in self.ranked if not c.included]

    @property
    def included_names(self) -> list[str]:
        return [c.name for c in self.included]

    def rank_of(self, agent_name: str) -> Optional[int]:
        for candidate in self.ranked:
            if candidate.name == agent_name:
                return candidate.rank
        return None

    def contains(self, agent_name: str) -> bool:
        return any(c.name == agent_name and c.included for c in self.ranked)

    def exclusion_reason(self, agent_name: str) -> str:
        for candidate in self.ranked:
            if candidate.name == agent_name:
                if candidate.included:
                    return ""
                return f"rank_{candidate.rank}_beyond_k_{self.k}:{candidate.reason}"
        return "not_in_registry"

    @property
    def positive_score_count(self) -> int:
        """Candidates with any metadata evidence for this query."""
        return sum(1 for c in self.ranked if c.score > 0)

    @property
    def dropped_static_matches(self) -> list[str]:
        """Literal query mentions that the cap still excluded.

        Non-empty means ``k`` is too small for the query: a literally named
        agent did not get a capability check.
        """
        return [c.name for c in self.ranked if c.static and not c.included]

    @property
    def cutoff_is_arbitrary(self) -> bool:
        """Whether the last included slot was decided without evidence.

        When fewer than ``k`` candidates have a positive score, or the candidate
        at the cutoff ties with the one just outside it, the boundary is settled
        by the name tie-break rather than by fit. Enforcement is only safe where
        this stays false or the tied candidates are all irrelevant, so the shadow
        record reports it instead of presenting the cut as meaningful.
        """
        if self.positive_score_count < self.k:
            return True
        included = self.included
        excluded = self.excluded
        if not included or not excluded:
            return False
        return abs(included[-1].score - excluded[0].score) < 1e-9

    def to_shadow_record(self, **extra: Any) -> dict[str, Any]:
        """Machine-readable record for corpus replay and recall measurement."""
        record: dict[str, Any] = {
            "schema_version": "v1",
            "record_type": "candidate_shortlist",
            "k": self.k,
            "candidate_count": len(self.ranked),
            "positive_score_count": self.positive_score_count,
            "cutoff_is_arbitrary": self.cutoff_is_arbitrary,
            "dropped_static_matches": self.dropped_static_matches,
            "included": [c.to_dict() for c in self.included],
            "excluded": [c.to_dict() for c in self.excluded],
        }
        record.update(extra)
        return record


def _card_name(card: Any) -> str:
    return str(getattr(card, "name", "") or "")


def _card_skill_tokens(card: Any) -> tuple[set[str], set[str]]:
    """Return (skill tokens, description tokens) for one agent card."""
    skill_tokens: set[str] = set()
    for skill in getattr(card, "skills", None) or []:
        skill_tokens |= _name_tokens(str(getattr(skill, "name", "") or ""))
        skill_tokens |= _name_tokens(str(getattr(skill, "id", "") or ""))
        for tag in getattr(skill, "tags", None) or []:
            skill_tokens |= _name_tokens(str(tag))

    description_parts = [str(getattr(card, "description", "") or "")]
    for skill in getattr(card, "skills", None) or []:
        description_parts.append(str(getattr(skill, "description", "") or ""))
    description_tokens = tokenize(" ".join(description_parts))
    return skill_tokens, description_tokens


STRONG_DIRECTIVES = (
    "must use", "only use", "use only", "must be answered by",
    "必须使用", "必须用", "只用", "只能用", "仅使用", "仅用", "指定使用", "指定由",
)
"""Phrases that name a required agent."""

WEAK_DIRECTIVES = (
    "please use", "route to", "send to", "delegate to", "ask",
    "请使用", "请用", "使用", "交给", "让",
)
"""Phrases that name a preferred agent."""

NEGATION_MARKERS = (
    "do not use", "don't use", "dont use", "not use", "never use",
    "avoid using", "without using", "instead of", "rather than",
    "other than", "except",
    "不要使用", "不要用", "不用", "别用", "别使用", "禁止使用", "不得使用",
    "不应使用", "避免使用", "避免用", "而不是", "而非", "除了",
)
"""Phrases that exclude an agent.

Needed because a directive can be a substring of its own negation: ``使用``
lives inside ``不要使用``, and ``use`` inside ``do not use``. Without this the
forbidden agent scores as though the user had asked for it."""

DIRECTIVE_WINDOW = 40
"""How far before an agent mention a directive may appear, in characters."""


_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def _name_occurrences(haystack: str, needle: str):
    """Positions where *needle* appears as a whole name, not inside a longer one.

    ``History-TDB-Agent`` is a substring of ``Art-history-TDB-Agent``; without a
    boundary check a directive naming one would also credit the other.
    """
    if not needle:
        return
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        before_ok = start == 0 or haystack[start - 1] not in _NAME_CHARS
        after_ok = end == len(haystack) or haystack[end] not in _NAME_CHARS
        if before_ok and after_ok:
            yield start
        start = haystack.find(needle, start + 1)


def _is_negated(prefix: str, directive_pos: int, directive_len: int) -> bool:
    """Whether the directive at *directive_pos* is cancelled by a negation.

    A negation counts when it covers the directive ("do not **use**") or sits
    between the directive and the agent name ("use A rather than B").
    """
    for marker in NEGATION_MARKERS:
        index = prefix.rfind(marker)
        while index != -1:
            if index <= directive_pos <= index + len(marker):
                return True
            if directive_pos < index:
                return True
            index = prefix.rfind(marker, 0, index)
    return False


def _directive_strength(prefix: str) -> int:
    """2 for a required agent, 1 for a preferred one, 0 for neither."""
    for markers, strength in ((STRONG_DIRECTIVES, 2), (WEAK_DIRECTIVES, 1)):
        for marker in markers:
            position = prefix.rfind(marker)
            if position == -1:
                continue
            if _is_negated(prefix, position, len(marker)):
                continue
            return strength
    return 0


def find_explicit_target(
    query: str,
    cards: Sequence[Any],
    *,
    window: int = DIRECTIVE_WINDOW,
) -> Optional[str]:
    """The agent the user required, or ``None``.

    A bare mention is not a directive: "compare with Alpha-Agent" names Alpha
    but does not select it, while "must use Zeta-Agent" does. A negated mention
    is not a directive either — "不要使用 A，请使用 B" selects B. Detection is
    deliberately narrow — a false positive pins the wrong agent into the
    shortlist and, once Phase 4 lands, would override lead selection.
    """
    haystack = (query or "").lower()
    if not haystack:
        return None

    best: Optional[tuple[int, int, str]] = None  # (-strength, position, name)
    for card in cards:
        name = _card_name(card)
        if not name:
            continue
        for start in _name_occurrences(haystack, name.lower()):
            prefix = haystack[max(0, start - window) : start]
            strength = _directive_strength(prefix)
            if strength:
                candidate = (-strength, start, name)
                if best is None or candidate < best:
                    best = candidate

    return best[2] if best else None


def static_matches(query: str, cards: Sequence[Any]) -> list[str]:
    """Agents the query names literally, by agent name or by skill id.

    This is the recall safeguard that runs before the cap: a literal mention is
    stronger evidence than any similarity score, so such agents keep a slot even
    when their token overlap is low.
    """
    haystack = (query or "").lower()
    if not haystack:
        return []
    hits: list[str] = []
    for card in cards:
        name = _card_name(card)
        if not name:
            continue
        needles = [name.lower()]
        for skill in getattr(card, "skills", None) or []:
            for value in (getattr(skill, "id", ""), getattr(skill, "name", "")):
                text = str(value or "").strip().lower()
                if len(text) >= 4:
                    needles.append(text)
        if any(
            needle and next(_name_occurrences(haystack, needle), None) is not None
            for needle in needles
        ):
            hits.append(name)
    return hits


def build_shortlist(
    query: str,
    cards: Sequence[Any],
    *,
    explicit_target: Optional[str] = None,
    k: int = DEFAULT_TOP_K,
    always_include: Optional[Iterable[str]] = None,
) -> Shortlist:
    """Rank *cards* for *query* and mark the proposed top-*k*.

    ``k`` is a hard ceiling on model-based capability checks, so the returned
    included set never exceeds it. ``explicit_target`` and ``always_include``
    (literal query mentions) are ranked *ahead* of similarity-scored candidates
    rather than added beyond the cap — otherwise "at most K capability checks"
    would not hold, and the rollout metric that gates enforcement would be
    measuring something the code does not do.

    The explicit target is ranked first, so with ``k >= 1`` it is always checked.
    """
    # Generic terms are dropped from the query side too, so they cannot inflate
    # scores through the skill or description channels either: every agent here
    # is a "tdb agent", so the word separates nothing.
    query_tokens = tokenize(query) - GENERIC_NAME_TOKENS
    static = {str(n) for n in (always_include or []) if n}
    explicit_name = str(explicit_target) if explicit_target else ""

    ranked: list[RankedCandidate] = []
    for card in cards:
        name = _card_name(card)
        if not name:
            continue
        skill_tokens, description_tokens = _card_skill_tokens(card)
        name_score = _overlap(query_tokens, _name_tokens(name))
        skill_score = _overlap(query_tokens, skill_tokens)
        description_score = _overlap(query_tokens, description_tokens)

        explicit = bool(explicit_name) and name == explicit_name
        is_static = name in static
        score = (
            WEIGHT_NAME * name_score
            + WEIGHT_SKILL * skill_score
            + WEIGHT_DESCRIPTION * description_score
        )
        if explicit:
            score += WEIGHT_EXPLICIT
        elif is_static:
            score += WEIGHT_STATIC

        matched = sorted(query_tokens & (skill_tokens | description_tokens | _name_tokens(name)))
        ranked.append(
            RankedCandidate(
                name=name,
                score=score,
                explicit=explicit,
                static=is_static,
                signals={
                    "name": name_score,
                    "skill": skill_score,
                    "description": description_score,
                },
                matched=matched,
            )
        )

    # Deterministic: score descending, then name ascending so equal scores never
    # depend on registry iteration order.
    ranked.sort(key=lambda c: (-c.score, c.name))

    limit = max(1, int(k))
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
        candidate.included = index <= limit

    return Shortlist(k=limit, ranked=ranked)
