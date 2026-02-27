import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio
import aiohttp
from aiohttp import ClientTimeout
import os

from a2a.types import AgentCard

logger = logging.getLogger(__name__)

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
        timeout: int = 300,
        agents_timeout: float = 15.0,
    ):
        """
        Initialize client.

        Args:
            base_url: API base URL. If None, uses env AgentRegistryURL or AgentRegistry.
            timeout: Request timeout (seconds) for general requests.
            agents_timeout: Timeout (seconds) for GET /agents.
        """
        url = base_url or os.getenv("AgentRegistryURL") or os.getenv("AgentRegistry") or "http://orchestrator-registry.dac.svc.cluster.local:10100"
        self.base_url = url.rstrip("/")
        self.timeout = timeout
        self.agents_timeout = agents_timeout

    async def _amake_request(
        self, 
        method: str, 
        endpoint: str, 
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generic method for sending HTTP requests
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            payload: Request body data (optional)
            
        Returns:
            API response result
            
        Raises:
            Exception: Request failed or JSON parsing failed
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {
            "Content-Type": "application/json"
        }

        timeout = ClientTimeout(total=self.timeout)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Only set json parameter when there is payload
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
        collection_name: str = "orchestrator_agent_cards",
        limit: int = 10
    ) -> SearchResult:
        """
        Search documents with vector, fulltext or hybrid search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            SearchResult object containing documents and scores
        """
        payload = {
            "query": query,
            "collection": collection_name,
            "limit": limit
        }
        
        endpoint = f"/search"
        
        response = await self._amake_request("POST", endpoint, payload)
        
        # Convert response to SearchResult object based on actual API format
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

    async def get_registered_agent_cards(self) -> List[AgentCard]:
        """
        Fetch all registered agent cards from agent registry (GET /agents).
        Returns list of AgentCard with required a2a fields defaulted when missing.
        """
        cards: List[AgentCard] = []
        url = f"{self.base_url}/agents"
        timeout = ClientTimeout(total=self.agents_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Agent registry GET /agents returned %s: %s",
                            resp.status,
                            (await resp.text())[:200],
                        )
                        return cards
                    data = await resp.json()
        except Exception as e:
            logger.warning("Failed to fetch agent registry for cards: %s", e)
            return cards
        for card in data.get("agent_cards") or []:
            if isinstance(card, dict):
                try:
                    d = dict(card)
                    d.setdefault("version", "1.0.0")
                    d.setdefault("capabilities", {"streaming": "True", "pushNotifications": "True", "stateTransitionHistory": "False"})
                    d.setdefault("defaultInputModes", ["text", "text/plain"])
                    d.setdefault("defaultOutputModes", ["text", "text/plain"])
                    d.setdefault("skills", [])
                    ac = AgentCard(**d)
                    cards.append(ac)
                    logger.info("Fetched registered agent card: name=%s url=%s", getattr(ac, "name", ""), getattr(ac, "url", ""))
                except Exception as e:
                    logger.debug("Skip invalid agent card from registry: %s", e)
            else:
                cards.append(card)
                logger.info("Fetched registered agent card: name=%s url=%s", getattr(card, "name", ""), getattr(card, "url", ""))
        return cards
