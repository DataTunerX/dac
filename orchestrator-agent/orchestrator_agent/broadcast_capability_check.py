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
SG_EXECUTION_HINT_KEY = "sg_execution_hint"

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
    collaboration_agents: list[str] = Field(default_factory=list)
    collaboration_roles: dict[str, str] = Field(default_factory=dict)
    collaboration_paths: list[dict] = Field(default_factory=list)
    member_results: list[dict] = Field(default_factory=list)
    degraded: bool = False
    unavailable_count: int = 0
    missing_requirements: list[str] = Field(default_factory=list)
    # Opaque SG-issued handoff; Routing/mid-delegate may transport it as-is.
    execution_hint: dict = Field(default_factory=dict)


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
    if any(re.search(pattern, normalized) for pattern in generic_patterns):
        return True
    inability_patterns = (
        r"无法访问",
        r"无法查询",
        r"无法访问任何业务",
        r"无任何业务数据库",
        r"不具备",
        r"仅具备 weather",
        r"only (has|have) weather",
        r"cannot access",
        r"no business database",
        r"本 agent 仅具备",
    )
    return any(re.search(pattern, normalized) for pattern in inability_patterns)


def _is_skill_mismatch_contributor(response: "CapabilityCheckResponse") -> bool:
    name = str(getattr(response, "agent_name", "") or "").lower()
    blob = " ".join(
        [
            str(getattr(response, "contribution", "") or ""),
            str(getattr(response, "reason", "") or ""),
        ]
    ).lower()
    if "weather" in name and not re.search(r"天气|weather|forecast|气温", blob):
        return True
    return False


def normalize_capability_check_response(response: CapabilityCheckResponse) -> CapabilityCheckResponse:
    if response.can_handle or not response.can_contribute:
        return response
    blob = f"{response.contribution or ''} {response.reason or ''}"
    if _is_non_actionable_contribution_text(response.contribution) or _is_non_actionable_contribution_text(blob):
        logger.info(
            "SG broadcast: normalize non-actionable contributor '%s' contribution='%s'",
            response.agent_name,
            (response.contribution or "")[:120],
        )
        response.can_contribute = False
        response.contribution = ""
        return response
    if _is_skill_mismatch_contributor(response):
        logger.info(
            "SG broadcast: normalize skill-mismatch contributor '%s'",
            response.agent_name,
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


def _is_unreachable_registry_error(exc: BaseException) -> bool:
    """True for DNS / connect failures that mean the card URL is a ghost."""
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "name does not resolve",
        "nodename nor servname",
        "name or service not known",
        "temporary failure in name resolution",
        "getaddrinfo failed",
        "connecterror",
        "connection refused",
        "network is unreachable",
        "no route to host",
        "errno -2",
        "errno -3",
        "gaierror",
    )
    return any(m in text for m in markers)


async def purge_unreachable_agent_card(
    agent_card: AgentCard,
    *,
    error: BaseException,
) -> None:
    """Best-effort DELETE from registry when capability probe hits DNS/connect fail."""
    enabled = os.getenv("REGISTRY_PURGE_ON_PROBE_UNREACHABLE", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )
    if not enabled:
        return
    if not _is_unreachable_registry_error(error):
        return
    url = str(getattr(agent_card, "url", "") or "").strip()
    if not url:
        return
    try:
        client = AgentRegistryClient(timeout=10)
        result = await client.adelete_agent(url)
        logger.warning(
            "SG broadcast: purged unreachable agent from registry | name=%s url=%s "
            "error=%s result=%s",
            getattr(agent_card, "name", ""),
            url,
            error,
            result,
        )
    except Exception as purge_exc:  # noqa: BLE001
        logger.error(
            "SG broadcast: failed to purge unreachable agent | name=%s url=%s err=%s",
            getattr(agent_card, "name", ""),
            url,
            purge_exc,
        )


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
            hint = response_data.get("execution_hint") or {}
            if not isinstance(hint, dict):
                hint = {}
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
                collaboration_agents=response_data.get("collaboration_agents") or [],
                collaboration_roles=response_data.get("collaboration_roles") or {},
                collaboration_paths=response_data.get("collaboration_paths") or [],
                member_results=response_data.get("member_results") or [],
                degraded=bool(response_data.get("degraded", False)),
                unavailable_count=int(response_data.get("unavailable_count", 0) or 0),
                missing_requirements=response_data.get("missing_requirements") or [],
                execution_hint=hint,
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
        await purge_unreachable_agent_card(agent_card, error=e)
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
                "SG broadcast: exception for agent %s query=%s: %s",
                all_agent_cards[i].name,
                (query or "")[:100],
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
        "SG broadcast: capable_count=%d names=%s query=%s",
        len(capable_agents),
        [c.name for c, _ in capable_agents[:8]],
        (query or "")[:100],
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


def _capability_probe_concurrency() -> int:
    try:
        return max(1, int(os.getenv("SG_MID_DELEGATE_CAPABILITY_CONCURRENCY", "8") or 8))
    except ValueError:
        return 8


async def probe_agents_capability_concurrent(
    query: str,
    agent_cards: list[AgentCard],
    user_id: str,
    run_id: str,
    trace_id: str,
    *,
    propagated_history: Optional[dict] = None,
    get_response_text: Optional[Callable[[Any], str]] = None,
    max_concurrency: Optional[int] = None,
) -> list[tuple[AgentCard, CapabilityCheckResponse]]:
    """Concurrently probe a concrete candidate set with standard capability_check.

    Unlike ``broadcast_capability_check`` (full registry), this only probes the
    provided cards — used by mid-delegate remote SG selection.
    """
    cards = [c for c in (agent_cards or []) if getattr(c, "name", None) and getattr(c, "url", None)]
    if not cards:
        logger.info(
            "[CapabilityProbe] skip | reason=empty_candidate_set query_preview=%s",
            (query or "")[:80],
        )
        return []

    concurrency = max_concurrency or _capability_probe_concurrency()
    semaphore = asyncio.Semaphore(concurrency)
    logger.info(
        "[CapabilityProbe] start concurrent probes | candidates=%d concurrency=%d "
        "names=%s query_preview=%s",
        len(cards),
        concurrency,
        [getattr(c, "name", "") for c in cards[:12]],
        (query or "")[:120],
    )

    async def _one(card: AgentCard) -> Optional[tuple[AgentCard, CapabilityCheckResponse]]:
        async with semaphore:
            resp = await send_capability_check(
                query,
                card,
                user_id,
                run_id,
                trace_id,
                propagated_history=propagated_history,
                get_response_text=get_response_text,
            )
            if resp is None:
                logger.info(
                    "[CapabilityProbe] no_response | agent=%s url=%s query=%s",
                    getattr(card, "name", ""),
                    getattr(card, "url", ""),
                    (query or "")[:120],
                )
                return None
            resp = normalize_capability_check_response(resp)
            logger.info(
                "[CapabilityProbe] result | agent=%s can_handle=%s can_contribute=%s "
                "confidence=%.2f degraded=%s query=%s reason=%s",
                getattr(card, "name", "") or resp.agent_name,
                resp.can_handle,
                resp.can_contribute,
                float(resp.confidence or 0.0),
                resp.degraded,
                (query or "")[:120],
                (resp.reason or "")[:160],
            )
            return card, resp

    gathered = await asyncio.gather(
        *[_one(card) for card in cards],
        return_exceptions=True,
    )

    capable: list[tuple[AgentCard, CapabilityCheckResponse]] = []
    errors = 0
    for index, item in enumerate(gathered):
        if isinstance(item, Exception):
            errors += 1
            logger.error(
                "[CapabilityProbe] exception | agent=%s err=%s",
                getattr(cards[index], "name", ""),
                item,
            )
            continue
        if item is None:
            continue
        card, resp = item
        if resp.can_handle or resp.can_contribute:
            capable.append((card, resp))

    capable.sort(
        key=lambda pair: (1 if pair[1].can_handle else 0, float(pair[1].confidence or 0.0)),
        reverse=True,
    )
    logger.info(
        "[CapabilityProbe] done | probed=%d capable=%d errors=%d "
        "handlers=%s contributors=%s",
        len(cards),
        len(capable),
        errors,
        [c.name for c, r in capable if r.can_handle][:10],
        [c.name for c, r in capable if (not r.can_handle) and r.can_contribute][:10],
    )
    return capable


def format_capability_evidence_for_planner(
    capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]],
    *,
    limit: int = 12,
) -> str:
    """Render capability-check evidence for planner memory (not card descriptions)."""
    if not capable_agents:
        return "(no capability-check capable peers)"
    lines = [
        "Remote SG candidates selected by standard capability_check "
        "(member-evidence based; do NOT rely on generic card descriptions):"
    ]
    for index, (card, resp) in enumerate(capable_agents[:limit], start=1):
        name = getattr(card, "name", "") or resp.agent_name or "?"
        role = "handle" if resp.can_handle else "contribute"
        reason = (resp.reason or "")[:_REASON_TRUNC]
        contribution = (resp.contribution or "")[:_CONTRIBUTION_TRUNC]
        lines.append(
            f"  #{index} agent={name} role={role} confidence={float(resp.confidence or 0.0):.2f}"
        )
        if reason:
            lines.append(f"       reason={reason}")
        if contribution:
            lines.append(f"       contribution={contribution}")
        missing = list(resp.missing_requirements or [])[:6]
        if missing:
            lines.append(f"       missing_requirements={missing}")
    return "\n".join(lines)
