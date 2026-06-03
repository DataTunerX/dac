"""SG Orchestrator ``data_inventory`` — derive table inventory from signatures.

We query the **signature API**
(``/signatures/search/by-dd``) which stores the actual DB schema discovered
by the data-sinker pipeline.  The ``metadata_content.tables_detail`` field
contains every table name + entity name for a Semantic Domain (DD).

The output is a **plain text block** appended to ``agent_card.description``:
no AgentSkill, no tag-based infrastructure.  Since ``description`` is already
rendered by ``generate_system_prompt_agents``, the routing LLM sees the
inventory with zero code changes to the prompt template.

Two consumption tiers:

1. :func:`build_sg_inventory_description` — SG-level aggregation: resolve
   member DDs from ``/semantic_groups/{id}/with_members``, then query each
   DD's signature and produce a compact text block.

2. :func:`get_sd_inventory_description` — single SD level: given
   ``(dd_namespace, dd_name)``, produce the same text block from one DD's
   signature.

Consumer helpers (for SovereigntyIndex etc.) are kept:
   :func:`extract_table_names_from_detail` — parse the raw text
   :func:`_resolve_sg_members_async` — discover member DDs
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    from a2a.types import AgentCard, AgentSkill
except ImportError:
    AgentCard = Any  # type: ignore[assignment]
    AgentSkill = Any  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Regex to extract table names from the 【data_inventory】 block appended to
# agent_card.description.  Format (produced by _format_inventory_text):
#
#     【data_inventory】
#     tables=[categories, inventory_logs, product_images, products]
#     absent=none
#     source=signature_api; db_type=mysql
#
_INVENTORY_BLOCK_RE = re.compile(
    r"【data_inventory】\s*\n(.*?)(?=\n【|\Z)",
    re.DOTALL,
)
_TABLES_INVENTORY_LINE_RE = re.compile(r"tables=\[(.*?)\]")

# Regex to extract table name and entity name from tables_detail lines.
#   Format: "1. table name: products(商品)，table description: ..."
_TABLES_DETAIL_LINE_RE = re.compile(
    r"table\s*name\s*:\s*(\S+?)(?:\(([^)]*)\))?\s*[，,]"
)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_table_name(name: str) -> str:
    raw = str(name or "").strip().strip("`'\"")
    return raw.lower()


def _dedupe_sort_tables(tables: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    seen: Set[str] = set()
    for t in tables or []:
        normalized = _normalize_table_name(t)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    deduped.sort()
    return deduped


# ---------------------------------------------------------------------------
# tables_detail parser
# ---------------------------------------------------------------------------


def parse_tables_detail(tables_detail: str) -> Dict[str, str]:
    """Parse ``tables_detail`` into ``{table_name: entity_name}``.

    Input format (one per line)::

        1. table name: orders(订单)，table description: 存储订单主表信息。
        2. table name: payment_records(支付记录)，table description: ...

    Returns a dict mapping the *normalised* table name to the entity name
    (Chinese label in parentheses).  Entity name defaults to ``""`` when not
    present.
    """
    result: Dict[str, str] = {}
    if not tables_detail:
        return result
    for line in str(tables_detail).split("\n"):
        m = _TABLES_DETAIL_LINE_RE.search(line)
        if not m:
            continue
        table_name = _normalize_table_name(m.group(1))
        entity_name = (m.group(2) or "").strip()
        if table_name and table_name not in result:
            result[table_name] = entity_name
    return result


def extract_table_names_from_detail(tables_detail: str) -> List[str]:
    """Return sorted, normalised table names from a ``tables_detail`` string."""
    return sorted(parse_tables_detail(tables_detail).keys())


# ---------------------------------------------------------------------------
# Signature API helpers
# ---------------------------------------------------------------------------


async def _fetch_signature_for_dd(
    dd_namespace: str,
    dd_name: str,
    *,
    data_services_url: str,
    session: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    """Query ``POST /signatures/search/by-dd``; return newest signature dict.

    Returns ``None`` when the DD has no signature or the API is unreachable.
    """
    url = f"{data_services_url.rstrip('/')}/signatures/search/by-dd"
    payload = {"dd_namespace": dd_namespace, "dd_name": dd_name}
    try:
        import aiohttp

        async def _do(s):
            async with s.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

        if session is not None:
            data = await _do(session)
        else:
            async with aiohttp.ClientSession() as s:
                data = await _do(s)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[DataInventory] signature search failed for %s/%s: %s",
            dd_namespace, dd_name, e,
        )
        return None

    if not data or data.get("status") != "success":
        return None
    results = data.get("data") or []
    return results[0] if results else None


async def _fetch_dd_tables_from_signature(
    dd_namespace: str,
    dd_name: str,
    *,
    data_services_url: str,
    session: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Return ``{table_name: entity_name}`` parsed from a DD's signature."""
    sig = await _fetch_signature_for_dd(
        dd_namespace, dd_name,
        data_services_url=data_services_url,
        session=session,
        headers=headers,
    )
    if not sig:
        return {}
    mc = sig.get("metadata_content", {})
    if isinstance(mc, str):
        try:
            mc = json.loads(mc)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(mc, dict):
        return {}
    td = mc.get("tables_detail", "")
    if isinstance(td, str):
        return parse_tables_detail(td)
    return {}


# ---------------------------------------------------------------------------
# SG member discovery
# ---------------------------------------------------------------------------


@dataclass
class SDMemberInfo:
    """Minimal SD member info extracted from data-services."""

    dd_namespace: str
    dd_name: str
    semantic_domain_id: str


async def _resolve_sg_members_async(
    semantic_group_id: str,
    data_services_url: str,
    *,
    session: Optional[Any] = None,
) -> List[SDMemberInfo]:
    """Resolve a Semantic Group's member DDs via data-services.

    Soft-fails to an empty list so callers can degrade gracefully.
    """
    if not semantic_group_id:
        return []

    url = f"{data_services_url.rstrip('/')}/semantic_groups/{semantic_group_id}/with_members"
    try:
        import aiohttp

        async def _do(s):
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

        if session is not None:
            data = await _do(session)
        else:
            async with aiohttp.ClientSession() as s:
                data = await _do(s)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[DataInventory] get_semantic_group_with_members failed for %s: %s",
            semantic_group_id, e,
        )
        return []

    if not data or data.get("status") != "success":
        return []

    inner = data.get("data", {})
    members_raw = inner.get("members") or []
    result: List[SDMemberInfo] = []
    for m in members_raw:
        if not isinstance(m, dict):
            continue
        sd = m.get("semantic_domain")
        if not isinstance(sd, dict):
            continue
        ns = str(sd.get("dd_namespace") or "").strip()
        name = str(sd.get("dd_name") or "").strip()
        sid = str(sd.get("semantic_domain_id") or "").strip()
        if ns and name:
            result.append(SDMemberInfo(dd_namespace=ns, dd_name=name, semantic_domain_id=sid))
    return result


# ---------------------------------------------------------------------------
# Text description builders (entry points)
# ---------------------------------------------------------------------------


def _run_async_at_startup(coro):
    """Run an async coroutine from synchronous startup code.

    Safe to call from both startup code (non-loop context) and tests within
    a running loop.  In the latter case the coroutine is simply awaited.
    """
    try:
        loop = asyncio.get_running_loop()
        # Already inside a running loop — await directly.
        if loop.is_running():
            import threading
            result: list = []
            exc: list = []
            def _run():
                try:
                    result.append(asyncio.run(coro))
                except Exception as e:
                    exc.append(e)
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join()
            if exc:
                raise exc[0]
            return result[0]
    except RuntimeError:
        pass
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def build_sg_inventory_description(
    semantic_group_id: str,
    *,
    data_services_url: str,
) -> str:
    """Build a plain text inventory block for a Semantic Group.

    Example output::

        【data_inventory】
        tables=[order_items, order_shipping, orders, payment_records]
        absent=none
        source=signature_api; db_type=mysql

    Returns an empty string (``""``) when no inventory can be gathered,
    so the caller can safely append via ``if text: desc += "\\n" + text``.
    """
    if not semantic_group_id:
        return ""

    members, all_tables, db_type = _run_async_at_startup(
        _aggregate_sg_tables_async(semantic_group_id, data_services_url)
    )

    if not all_tables:
        logger.info(
            "[DataInventory][SG] group=%s: no inventory derived from signatures.",
            semantic_group_id,
        )
        return ""

    return _format_inventory_text(
        sorted(all_tables.keys()),
        table_comments=all_tables,
        db_type=db_type,
    )


def get_sd_inventory_description(
    dd_namespace: str,
    dd_name: str,
    *,
    data_services_url: str,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """Build a plain text inventory block for a single SD (DD).

    Example output::

        【data_inventory】
        tables=[categories, inventory_logs, product_images, products]
        absent=none
        source=signature_api; db_type=mysql
    """
    sig = _run_async_at_startup(
        _fetch_signature_for_dd(dd_namespace, dd_name, data_services_url=data_services_url, headers=headers)
    )
    if not sig:
        return ""

    mc = sig.get("metadata_content", {})
    if isinstance(mc, str):
        try:
            mc = json.loads(mc)
        except Exception:
            mc = {}
    if not isinstance(mc, dict):
        return ""

    td = mc.get("tables_detail", "")
    if isinstance(td, str):
        tables_map = parse_tables_detail(td)
    else:
        tables_map = {}
    if not tables_map:
        return ""

    db_type = mc.get("data_type") or mc.get("db_type")

    return _format_inventory_text(
        sorted(tables_map.keys()),
        table_comments=tables_map,
        db_type=db_type,
    )


# ---------------------------------------------------------------------------
# Internal: data aggregation + text formatting
# ---------------------------------------------------------------------------


async def _aggregate_member_tables_from_signatures(
    members: List[SDMemberInfo],
    data_services_url: str,
    *,
    session: Any,
) -> Dict[str, str]:
    """Query signatures for each member DD and merge table maps."""
    all_tables: Dict[str, str] = {}
    for m in members:
        dd_tables = await _fetch_dd_tables_from_signature(
            m.dd_namespace, m.dd_name,
            data_services_url=data_services_url,
            session=session,
        )
        all_tables.update(dd_tables)
    return all_tables


async def _aggregate_sg_tables_async(
    semantic_group_id: str,
    data_services_url: str,
) -> Tuple[List[SDMemberInfo], Dict[str, str], Optional[str]]:
    """Resolve SG members and aggregate all DD tables from signatures.

    Returns ``(members, {table_name: entity_name}, db_type_or_None)``.
    """
    import aiohttp

    async with aiohttp.ClientSession() as session:
        members = await _resolve_sg_members_async(
            semantic_group_id, data_services_url, session=session,
        )
        if not members:
            return [], {}, None

        all_tables: Dict[str, str] = {}
        db_type: Optional[str] = None

        for m in members:
            sig = await _fetch_signature_for_dd(
                m.dd_namespace, m.dd_name,
                data_services_url=data_services_url,
                session=session,
            )
            if not sig:
                continue
            mc = sig.get("metadata_content", {})
            if isinstance(mc, str):
                try:
                    mc = json.loads(mc)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(mc, dict):
                continue
            td = mc.get("tables_detail", "")
            if isinstance(td, str):
                dd_tables = parse_tables_detail(td)
                all_tables.update(dd_tables)
                if db_type is None:
                    db_type = mc.get("data_type") or mc.get("db_type")

        return members, all_tables, db_type


def _format_inventory_text(
    tables: List[str],
    *,
    table_comments: Optional[Dict[str, str]] = None,
    db_type: Optional[str] = None,
) -> str:
    """Format the inventory as a plain text block.

    Example::

        【data_inventory】
        tables=[categories, inventory_logs, product_images, products]
        absent=none
        source=signature_api; db_type=mysql
    """
    table_comments = table_comments or {}
    lines = [
        "【data_inventory】",
        f"tables=[{', '.join(tables)}]",
    ]
    # Compute absent = tables that other DDs in the same domain own but we don't.
    # At the SG level this is a no-op (we show all known tables); we keep absent
    # as a placeholder so the LLM can see the field exists.
    # TODO: SG-level absent requires a "known universe" — this is a cross-SG concern
    #       better served by SovereigntyIndex at runtime.
    lines.append("absent=none")
    source_parts = ["source=signature_api"]
    if db_type:
        source_parts.append(f"db_type={db_type}")
    lines.append("; ".join(source_parts))

    # Entity name annotations (table comments) — only when present.
    comment_lines = []
    for t in tables:
        entity = (table_comments.get(t) or "").strip()
        if entity:
            comment_lines.append(f"{t} ({entity})")
    if comment_lines:
        lines.append("table_comments: " + ", ".join(comment_lines))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Consumer helpers (retained for SovereigntyIndex etc.)
# ---------------------------------------------------------------------------


def _parse_description_inventory_block(description: str) -> Optional[str]:
    """Extract the raw ``【data_inventory】`` block from ``agent_card.description``.

    Returns the block body (without the header) or ``None``.
    """
    if not description:
        return None
    m = _INVENTORY_BLOCK_RE.search(description)
    return m.group(1).strip() if m else None


def extract_inventory_tables_from_description(description: str) -> Set[str]:
    """Parse table names from a ``【data_inventory】`` block in description.

    Returns normalised, deduped table names.  Returns empty set when no
    inventory block is present.
    """
    body = _parse_description_inventory_block(description)
    if not body:
        return set()
    m = _TABLES_INVENTORY_LINE_RE.search(body)
    if not m:
        return set()
    raw = m.group(1)
    return {_normalize_table_name(t.strip()) for t in raw.split(",") if t.strip()}


def extract_inventory_description(description: str) -> str:
    """Return the full ``【data_inventory】`` block text, or empty string."""
    body = _parse_description_inventory_block(description)
    if not body:
        return ""
    return "\n".join(["【data_inventory】", body])


def extract_inventory_tables(card: Any) -> Set[str]:
    """Return normalised tables from a card's data inventory.

    Parses the ``【data_inventory】`` block in ``agent_card.description``
    (appended at startup by ``server.py`` via ``build_sg_inventory_description``
    or ``get_sd_inventory_description``).  Returns empty set when no inventory
    block is present.
    """
    desc = None
    if isinstance(card, dict):
        desc = card.get("description")
    elif hasattr(card, "description"):
        desc = getattr(card, "description", None)
    return extract_inventory_tables_from_description(str(desc or ""))


def build_table_owner_index(cards: Iterable[Any]) -> Dict[str, List[str]]:
    """Build ``normalised_table → [agent_name, ...]`` over a card list."""
    index: Dict[str, List[str]] = {}
    for card in cards or []:
        name = _card_name(card)
        if not name:
            continue
        for t in extract_inventory_tables(card):
            owners = index.setdefault(t, [])
            if name not in owners:
                owners.append(name)
    return index


def find_table_owners(table_name: str, cards: Iterable[Any]) -> List[str]:
    """Return agent names whose card declares this table."""
    normalized = _normalize_table_name(table_name)
    if not normalized:
        return []
    owners: List[str] = []
    for card in cards or []:
        if normalized in extract_inventory_tables(card):
            name = _card_name(card)
            if name and name not in owners:
                owners.append(name)
    return owners


def _card_name(card: Any) -> str:
    if isinstance(card, dict):
        return (card.get("name") or "").strip()
    return (getattr(card, "name", "") or "").strip()


# ---------------------------------------------------------------------------
# Sovereignty index
# ---------------------------------------------------------------------------


class SovereigntyIndex:
    """Cached ``table → [peer_sg_name, ...]`` lookup from data-services.

    Calls the shared ``GET /table-ownership-index`` endpoint which is built
    centrally by querying all SGs → member DDs → signature fingerprints,
    so every SG Orchestrator shares the same index without redundant work.
    """

    DEFAULT_TTL_SEC = 30

    def __init__(
        self,
        *,
        data_services_url: str,
        ttl_sec: Optional[int] = None,
        own_agent_name: Optional[str] = None,
    ) -> None:
        self.data_services_url = data_services_url.rstrip("/")
        try:
            self.ttl_sec = int(ttl_sec) if ttl_sec is not None else int(
                os.getenv("SOVEREIGNTY_INDEX_TTL_SEC", str(self.DEFAULT_TTL_SEC))
            )
        except (TypeError, ValueError):
            self.ttl_sec = self.DEFAULT_TTL_SEC
        self.own_agent_name = (own_agent_name or "").strip()
        self._index: Optional[Dict[str, List[str]]] = None
        self._loaded_at: float = 0.0

    async def refresh(self) -> Dict[str, List[str]]:
        """Fetch the shared table-ownership-index from data-services."""
        logger.info("[SovereigntyIndex] refreshing index from data-services (url=%s, stale=%s)", self.data_services_url, self._is_stale())
        import aiohttp

        url = f"{self.data_services_url}/table-ownership-index"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("[SovereigntyIndex] data-services returned HTTP %s", resp.status)
                        return self._index or {}
                    data = await resp.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("[SovereigntyIndex] fetch failed: %s", e)
            return self._index or {}

        if data.get("status") != "success":
            logger.warning("[SovereigntyIndex] data-services status=%s", data.get("status"))
            return self._index or {}

        raw_index = data.get("data") or {}

        # Filter out self when own_agent_name is set.
        if self.own_agent_name:
            filtered: Dict[str, List[str]] = {}
            for table_name, owners in raw_index.items():
                others = [o for o in (owners or []) if o != self.own_agent_name]
                if others:
                    filtered[table_name] = others
            self._index = filtered
        else:
            self._index = raw_index

        self._loaded_at = time.time()
        logger.info(
            "[SovereigntyIndex] refreshed from data-services: unique_tables=%d",
            len(self._index),
        )
        return self._index

    def _is_stale(self) -> bool:
        return (time.time() - self._loaded_at) > self.ttl_sec

    async def find_owners(self, table_name: str) -> List[str]:
        normalized = _normalize_table_name(table_name)
        if not normalized:
            return []
        if self._index is None or self._is_stale():
            await self.refresh()
        owners = list((self._index or {}).get(normalized) or [])
        logger.info(
            "[SovereigntyIndex] find_owners: table=%s normalized=%s owners=%s",
            table_name, normalized, owners,
        )
        return owners

    async def find_owners_for_many(self, table_names: Iterable[str]) -> Dict[str, List[str]]:
        normalized = [
            _normalize_table_name(t) for t in table_names or [] if _normalize_table_name(t)
        ]
        if not normalized:
            logger.info("[SovereigntyIndex] find_owners_for_many: empty input")
            return {}
        if self._index is None or self._is_stale():
            await self.refresh()
        idx = self._index or {}
        out: Dict[str, List[str]] = {}
        for n in normalized:
            owners = idx.get(n) or []
            if owners:
                out[n] = list(owners)
        logger.info(
            "[SovereigntyIndex] find_owners_for_many: queried=%d matched=%d unmatched=%s",
            len(normalized), len(out),
            [t for t in normalized if t not in out],
        )
        logger.info("[SovereigntyIndex] find_owners_for_many: details=%s", out)
        return out