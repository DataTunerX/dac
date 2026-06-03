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
        """
        Initialize client.

        Args:
            base_url: API base URL. If None, uses env AgentRegistry.
            timeout: Request timeout (seconds)
        """
        resolved = (
            base_url
            or os.getenv("AgentRegistry")
            or "http://expert-registry.dac.svc.cluster.local:10100"
        )
        self.base_url = resolved.rstrip("/")
        self.timeout = timeout

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
        collection_name: str = "expert_agent_cards",
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

    async def alist_all_agents(
        self,
        collection: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List ALL registered agents from the registry service.

        Unlike asearch() which uses vector search, this retrieves every agent
        in the registry without filtering.

        Args:
            collection: When set, passed as ``?collection=`` query parameter
                (registry API parity with RoutingAgent list calls).

        Returns:
            List of agent data dicts (agent_cards from response)
        """
        endpoint = "/agents"
        if collection:
            endpoint = f"/agents?collection={quote(collection, safe='')}"
        response = await self._amake_request("GET", endpoint)
        return response.get("agent_cards", [])
