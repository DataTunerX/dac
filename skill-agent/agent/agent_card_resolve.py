"""Resolve planner-emitted agent strings to registered AgentCard instances.

Copied from orchestrator-agent.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def resolve_agent_card_by_planner_name(
    agent_cards: Optional[List[Any]],
    agent_name: Optional[str],
) -> Optional[Any]:
    """Match ``AgentCard.name`` exactly, else unique prefix match."""
    if not agent_cards or agent_name is None:
        return None
    needle = str(agent_name).strip()
    if not needle:
        return None

    for card in agent_cards:
        cn = getattr(card, "name", None)
        if cn == needle:
            return card

    prefix_hits: List[Any] = []
    for card in agent_cards:
        cn = getattr(card, "name", None)
        if isinstance(cn, str) and cn.startswith(needle):
            prefix_hits.append(card)

    if len(prefix_hits) == 1:
        resolved = prefix_hits[0]
        rn = getattr(resolved, "name", "")
        if rn != needle:
            logger.info(
                "[AgentResolve] planner name %r uniquely prefixes registered %r — using resolved card",
                needle,
                rn,
            )
        return resolved

    if len(prefix_hits) > 1:
        logger.warning(
            "[AgentResolve] planner name %r prefix-matches multiple agents %s — refusing to guess",
            needle,
            [getattr(c, "name", "") for c in prefix_hits],
        )
    return None