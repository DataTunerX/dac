"""SG-side capability broadcast (aligned with Routing Agent broadcast routing).

Root SG first make_plan after Routing may reuse ``routing_agent_pool`` from metadata.
Subsequent make_plan (replan, mid-exec, delegated SG) calls ``broadcast_capability_check``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Optional
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.types import AgentCard, MessageSendParams, SendStreamingMessageRequest
from pydantic import BaseModel, Field

from .agentregistry_client import AgentRegistryClient
from .a2a_client import get_response_text as default_get_response_text

logger = logging.getLogger(__name__)

CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"
PROPAGATED_HISTORY_KEY = "propagated_history"
ROUTING_AGENT_POOL_KEY = "routing_agent_pool"
ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY = "routing_skip_broadcast_eligible"
ROUTING_SELECTED_ROOT_KEY = "routing_selected_root"

_CONTRIBUTION_TRUNC = 300
_REASON_TRUNC = 200


class CapabilityCheckResponse(BaseModel):
    can_handle: bool = False
    confidence: float = 0.0
    reason: str = ""
    agent_name: str = ""
    agent_url: str = ""
    route_path: list[str] = Field(default_factory=list)
    route_paths: list[dict] = Field(default_factory=list)
    can_contribute: bool = False
    contribution: str = ""
    execution_strategy: str = "single"


def _is_non_actionable_contribution_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip()).lower()
    if len(normalized) < 6:
        return True
    generic_patterns = (
        r"互补的信息",
        r"补充并完善",
        r"补充相关信息",
        r"完善相关信息",
        r"辅助信息",
        r"相关信息",
        r"相关数据",
        r"更多信息",
        r"其他信息",
        r"其它信息",
        r"complementary information",
        r"supplementary information",
        r"additional information",
        r"related information",
        r"auxiliary information",
    )
    return any(re.search(pattern, normalized) for pattern in generic_patterns)


def normalize_capability_check_response(response: CapabilityCheckResponse) -> CapabilityCheckResponse:
    if response.can_handle or not response.can_contribute:
        return response
    if _is_non_actionable_contribution_text(response.contribution):
        logger.info(
            "SG broadcast: normalize non-actionable contributor '%s' contribution='%s'",
            response.agent_name,
            (response.contribution or "")[:120],
        )
        response.can_contribute = False
        response.contribution = ""
    return response


def _parse_agent_cards_from_response(raw_list: list) -> list[AgentCard]:
    cards: list[AgentCard] = []
    for item in raw_list or []:
        agent_data = item.get("agent", item) if isinstance(item, dict) else item
        if isinstance(agent_data, dict):
            cards.append(AgentCard(**agent_data))
        elif hasattr(agent_data, "__dict__"):
            cards.append(AgentCard(**agent_data.__dict__))
    return cards


def _agent_card_to_dict(card: AgentCard) -> dict[str, Any]:
    dump = getattr(card, "model_dump", None) or getattr(card, "dict", None)
    if dump:
        return dump()
    return {"name": getattr(card, "name", ""), "url": getattr(card, "url", "")}


async def list_all_orchestrator_agent_cards(
    *,
    collection_name: Optional[str] = None,
) -> list[AgentCard]:
    client = AgentRegistryClient()
    coll = collection_name or os.getenv("AgentRegistryCollection", "orchestrator_agent_cards")
    try:
        raw = await client.alist_all_agents(collection=coll)
        cards = _parse_agent_cards_from_response(raw)
        logger.info(
            "SG broadcast: list_all_orchestrator_agent_cards collection=%s count=%d",
            coll,
            len(cards),
        )
        return cards
    except Exception as e:
        logger.error("SG broadcast: list_all_orchestrator_agent_cards failed: %s", e)
        return []


async def send_capability_check(
    query: str,
    agent_card: AgentCard,
    user_id: str,
    run_id: str,
    trace_id: str,
    *,
    propagated_history: Optional[dict] = None,
    get_response_text: Optional[Callable[[Any], str]] = None,
) -> Optional[CapabilityCheckResponse]:
    extract = get_response_text or default_get_response_text
    send_message_payload: dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": query}],
            "messageId": uuid4().hex,
        },
        "metadata": {
            "message_type": CAPABILITY_CHECK_MESSAGE_TYPE,
            "user_id": user_id,
            "run_id": run_id,
            "trace_id": trace_id,
            PROPAGATED_HISTORY_KEY: propagated_history or {},
        },
    }
    broadcast_timeout = float(os.getenv("BROADCAST_TIMEOUT", "30"))
    try:
        async with httpx.AsyncClient(timeout=broadcast_timeout) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            streaming_request = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_message_payload),
            )
            stream_response = client.send_message_streaming(streaming_request)
            response_parts: list[str] = []
            async for chunk in stream_response:
                result = extract(chunk)
                if result:
                    response_parts.append(result)
            full_response = "".join(response_parts).strip()
            if full_response.startswith("```json"):
                full_response = full_response[7:]
            elif full_response.startswith("```"):
                full_response = full_response[3:]
            if full_response.endswith("```"):
                full_response = full_response[:-3]
            full_response = full_response.strip()
            response_data = json.loads(full_response)
            rp = response_data.get("route_path") or []
            rps = response_data.get("route_paths") or []
            if not rps and rp:
                rps = [{"path": rp, "confidence": response_data.get("confidence", 0.0)}]
            return CapabilityCheckResponse(
                can_handle=response_data.get("can_handle", False),
                confidence=response_data.get("confidence", 0.0),
                reason=response_data.get("reason", ""),
                agent_name=response_data.get("agent_name", agent_card.name),
                agent_url=response_data.get("agent_url", agent_card.url),
                route_path=rp,
                route_paths=rps,
                can_contribute=response_data.get("can_contribute", False),
                contribution=response_data.get("contribution", ""),
                execution_strategy=response_data.get("execution_strategy", "single"),
            )
    except json.JSONDecodeError as e:
        logger.error(
            "SG broadcast: JSON parse error for agent %s (%s): %s",
            agent_card.name,
            agent_card.url,
            e,
        )
        return None
    except Exception as e:
        logger.error(
            "SG broadcast: capability check failed for agent %s (%s): %s",
            agent_card.name,
            agent_card.url,
            e,
        )
        return None


async def broadcast_capability_check(
    query: str,
    user_id: str,
    run_id: str,
    trace_id: str,
    *,
    propagated_history: Optional[dict] = None,
    get_response_text: Optional[Callable[[Any], str]] = None,
) -> list[tuple[AgentCard, CapabilityCheckResponse]]:
    all_agent_cards = await list_all_orchestrator_agent_cards()
    if not all_agent_cards:
        logger.warning("SG broadcast: no orchestrator agents in registry")
        return []

    logger.info(
        "SG broadcast: sending capability check to %d agents for query: %s...",
        len(all_agent_cards),
        (query or "")[:100],
    )
    tasks = [
        send_capability_check(
            query,
            card,
            user_id,
            run_id,
            trace_id,
            propagated_history=propagated_history,
            get_response_text=get_response_text,
        )
        for card in all_agent_cards
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                "SG broadcast: exception for agent %s: %s",
                all_agent_cards[i].name,
                result,
            )
            continue
        if result is None:
            continue
        result = normalize_capability_check_response(result)
        if result.can_handle or result.can_contribute:
            capable_agents.append((all_agent_cards[i], result))

    capable_agents.sort(
        key=lambda x: (1 if x[1].can_handle else 0, x[1].confidence),
        reverse=True,
    )
    logger.info(
        "SG broadcast: capable_count=%d names=%s",
        len(capable_agents),
        [c.name for c, _ in capable_agents[:8]],
    )
    return capable_agents


def build_routing_agent_pool(
    capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]],
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for card, resp in capable_agents:
        name = getattr(card, "name", "") or resp.agent_name
        if not name:
            continue
        role = "handle" if resp.can_handle else "contribute"
        contribution = str(resp.contribution or "")
        reason = str(resp.reason or "")
        if len(contribution) > _CONTRIBUTION_TRUNC:
            contribution = contribution[:_CONTRIBUTION_TRUNC] + "..."
        if len(reason) > _REASON_TRUNC:
            reason = reason[:_REASON_TRUNC] + "..."
        pool.append(
            {
                "agent": _agent_card_to_dict(card),
                "agent_name": name,
                "role": role,
                "confidence": float(resp.confidence or 0.0),
                "contribution": contribution,
                "reason": reason,
            }
        )
    return pool


def parse_routing_agent_pool(metadata: Optional[dict]) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get(ROUTING_AGENT_POOL_KEY)
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def log_routing_agent_pool_received(metadata: Optional[dict]) -> None:
    """Log the routing_agent_pool snapshot forwarded by Routing Agent in A2A metadata."""
    if not isinstance(metadata, dict):
        return
    pool = parse_routing_agent_pool(metadata)
    if not pool:
        return

    skip_eligible = metadata.get(ROUTING_SKIP_BROADCAST_ELIGIBLE_KEY)
    selected_root = str(metadata.get(ROUTING_SELECTED_ROOT_KEY) or "")
    run_id = str(metadata.get("run_id") or "")
    trace_id = str(metadata.get("trace_id") or "")

    header = (
        "[RoutingPool] received from RoutingAgent | pool_size=%d "
        "skip_broadcast_eligible=%s selected_root=%s run_id=%s trace_id=%s"
    )
    lines = [
        header
        % (len(pool), skip_eligible, selected_root or "(none)", run_id or "(none)", trace_id or "(none)")
    ]
    for index, entry in enumerate(pool, start=1):
        name = str(entry.get("agent_name") or "").strip() or "?"
        role = str(entry.get("role") or "?").strip()
        confidence = float(entry.get("confidence") or 0.0)
        agent_data = entry.get("agent") if isinstance(entry.get("agent"), dict) else {}
        url = str(agent_data.get("url") or "").strip()
        description = str(agent_data.get("description") or "").strip()
        if len(description) > _REASON_TRUNC:
            description = description[:_REASON_TRUNC] + "..."
        contribution = str(entry.get("contribution") or "").strip()
        if len(contribution) > _CONTRIBUTION_TRUNC:
            contribution = contribution[:_CONTRIBUTION_TRUNC] + "..."
        reason = str(entry.get("reason") or "").strip()
        if len(reason) > _REASON_TRUNC:
            reason = reason[:_REASON_TRUNC] + "..."
        detail = (
            f"  #{index} agent={name} role={role} confidence={confidence:.2f} url={url or '(none)'}"
        )
        if description:
            detail += f" description={description!r}"
        if contribution:
            detail += f" contribution={contribution!r}"
        if reason:
            detail += f" reason={reason!r}"
        lines.append(detail)
    logger.info("\n".join(lines))


def _agent_card_from_pool_snapshot(agent_data: dict) -> AgentCard:
    defaults: dict[str, Any] = {
        "capabilities": {},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [],
        "version": "1.0.0",
        "description": "",
        "url": "",
        "name": "",
    }
    merged = {**defaults, **(agent_data or {})}
    return AgentCard(**merged)


def pool_to_peer_agent_cards(
    pool: list[dict[str, Any]],
    self_agent_name: str,
) -> list[AgentCard]:
    self_name = (self_agent_name or "").strip()
    out: list[AgentCard] = []
    seen: set[str] = set()
    for entry in pool or []:
        name = (entry.get("agent_name") or "").strip()
        if not name or name in seen:
            continue
        if self_name and name == self_name:
            continue
        agent_data = entry.get("agent")
        if isinstance(agent_data, dict):
            try:
                out.append(_agent_card_from_pool_snapshot(agent_data))
                seen.add(name)
            except Exception as e:
                logger.warning("SG broadcast: invalid agent snapshot for %s: %s", name, e)
    return out
