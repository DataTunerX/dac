"""Agent Registry API Client — copied from orchestrator-agent."""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio
import aiohttp
from aiohttp import ClientTimeout
import os


class SearchType(str, Enum):
    """Search type enumeration"""
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    HYBRID = "hybrid"


@dataclass
class SearchResultItem:
    """Single search result item"""
    content: str
    metadata: Dict[str, Any]
    score: float
    search_type: str
    hybrid_score: Optional[float] = None


@dataclass
class SearchResult:
    """Search result data class matching actual API response"""
    status: str
    collection: str
    search_type: str
    result: List[SearchResultItem]


class AgentRegistryClient:
    """AgentRegistry API Client"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 300
    ):
        resolved = (
            base_url
            or os.getenv("AgentRegistry")
            or "http://biz-orchestrator-registry.dac.svc.cluster.local:8000"
        )
        self.base_url = resolved.rstrip("/")
        self.timeout = timeout

    async def _amake_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        timeout = ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                request_kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers
                }
                if payload is not None:
                    request_kwargs["json"] = payload
                async with session.request(**request_kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                raise Exception(f"HTTP request failed: {e}")
            except json.JSONDecodeError as e:
                raise Exception(f"Response JSON parsing failed: {e}")

    async def asearch(
        self,
        query: str,
        collection_name: str = "biz_orchestrator_agent_cards",
        limit: int = 10
    ) -> SearchResult:
        payload = {
            "query": query,
            "collection": collection_name,
            "limit": limit
        }
        endpoint = "/search"
        response = await self._amake_request("POST", endpoint, payload)
        result_items = [
            SearchResultItem(
                content=item.get("content", ""),
                metadata=item.get("metadata", {}),
                score=item.get("score", 0.0),
                search_type=item.get("search_type", ""),
                hybrid_score=item.get("hybrid_score")
            )
            for item in response.get("result", [])
        ]
        return SearchResult(
            status=response.get("status", ""),
            collection=response.get("collection", ""),
            search_type=response.get("search_type", ""),
            result=result_items
        )

    async def alist_all_agents(
        self,
        collection: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        endpoint = "/agents"
        if collection:
            endpoint = f"/agents?collection={quote(collection, safe='')}"
        response = await self._amake_request("GET", endpoint)
        return response.get("agent_cards", [])

    async def adelete_agent(self, agent_url: str) -> Dict[str, Any]:
        if not (agent_url or "").strip():
            raise ValueError("agent_url is required")
        endpoint = f"/agents?url={quote(agent_url.strip(), safe='')}"
        return await self._amake_request("DELETE", endpoint)