import aiohttp
import json
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import requests

@dataclass
class SemanticDomainData:
    """SemanticDomain data class"""
    semantic_domain: Optional[str] = None
    agent_card: Optional[str] = None
    dd_namespace: Optional[str] = None
    dd_name: Optional[str] = None
    semantic_domain_id: Optional[str] = None
    descriptor_type: Optional[str] = None
    version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {}
        if self.semantic_domain is not None:
            data["semantic_domain"] = self.semantic_domain
        if self.agent_card is not None:
            data["agent_card"] = self.agent_card
        if self.dd_namespace is not None:
            data["dd_namespace"] = self.dd_namespace
        if self.dd_name is not None:
            data["dd_name"] = self.dd_name
        if self.semantic_domain_id is not None:
            data["semantic_domain_id"] = self.semantic_domain_id
        if self.descriptor_type is not None:
            data["descriptor_type"] = self.descriptor_type
        if self.version is not None:
            data["version"] = self.version
        return data

class SemanticDomainClient:
    """Synchronous version of semantic domain service API client (stateless version)"""
    
    def __init__(
        self, 
        base_url: str = "http://data-services.dac.svc.cluster.local:8000",
        timeout: int = 300
    ):
        """
        Initialize client
        
        Args:
            base_url: API base URL
            timeout: Request timeout (seconds)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generic method for sending HTTP requests
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            payload: Request body data (optional)
            params: Query parameters (optional)
            
        Returns:
            API response result
            
        Raises:
            Exception: Request failed or JSON parsing failed
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {"Content-Type": "application/json"}
        
        # 从环境变量读取 DATA_DESCRIPTOR 并添加到 header
        data_descriptor = os.getenv("DATA_DESCRIPTOR")
        if data_descriptor:
            headers["Data-Descriptor"] = data_descriptor
        
        try:
            request_kwargs = {
                "method": method,
                "url": url,
                "timeout": self.timeout,
                "headers": headers
            }
            
            if payload is not None:
                request_kwargs["json"] = payload
            
            if params is not None:
                request_kwargs["params"] = params
            
            # Create new session for each request
            with requests.Session() as session:
                response = session.request(**request_kwargs)
                response.raise_for_status()
                return response.json()
            
        except requests.RequestException as e:
            raise Exception(f"HTTP request failed: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Response JSON parsing failed: {e}")

    def create_semantic_domain(self, semantic_domain: SemanticDomainData) -> Dict[str, Any]:
        """
        Create single semantic domain record
        
        Args:
            semantic_domain: SemanticDomain data object
            
        Returns:
            API response result
        """
        payload = semantic_domain.to_dict()
        endpoint = "/semantic_domains"
        
        return self._make_request("POST", endpoint, payload)

    def batch_create_semantic_domains(self, semantic_domains: List[SemanticDomainData]) -> Dict[str, Any]:
        """
        Batch create semantic domain records
        
        Args:
            semantic_domains: List of semantic domain data objects
            
        Returns:
            API response result
        """
        payload = [domain.to_dict() for domain in semantic_domains]
        endpoint = "/semantic_domains/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_semantic_domain_by_id(self, semantic_domain_id: str) -> Dict[str, Any]:
        """
        Get semantic domain record by primary key semantic_domain_id
        
        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return self._make_request("GET", endpoint)

    def search_semantic_domains_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search semantic domain records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name
        }
        endpoint = "/semantic_domains/search/by-dd"
        
        return self._make_request("POST", endpoint, payload)

    def update_semantic_domain(self, semantic_domain_id: str, semantic_domain: SemanticDomainData) -> Dict[str, Any]:
        """
        Update semantic domain record
        
        Args:
            semantic_domain_id: Primary key of record to update
            semantic_domain: New semantic domain data
            
        Returns:
            API response result
        """
        payload = semantic_domain.to_dict()
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return self._make_request("PUT", endpoint, payload)

    def delete_semantic_domain(self, semantic_domain_id: str) -> Dict[str, Any]:
        """
        Delete semantic domain record
        
        Args:
            semantic_domain_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return self._make_request("DELETE", endpoint)

    def delete_semantic_domains_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete semantic domain records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}"
        
        return self._make_request("DELETE", endpoint)

    def check_semantic_domain_exists(self, semantic_domain_id: str) -> bool:
        """
        Check if semantic domain record exists
        
        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def check_semantic_domain_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if semantic domain record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def get_semantic_domain_count(self) -> int:
        """
        Get total number of semantic domain records
        
        Returns:
            int: Total record count
        """
        endpoint = "/semantic_domains/status/count"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_semantic_domain_count()
            return True
        except Exception:
            return False


class AsyncSemanticDomainClient:
    """SemanticDomain service API client"""
    
    def __init__(
        self, 
        base_url: str = "http://localhost:8000",
        timeout: int = 300
    ):
        """
        Initialize client
        
        Args:
            base_url: API base URL
            timeout: Request timeout (seconds)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generic method for sending HTTP requests
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            payload: Request body data (optional)
            params: Query parameters (optional)
            
        Returns:
            API response result
            
        Raises:
            Exception: Request failed or JSON parsing failed
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # 从环境变量读取 DATA_DESCRIPTOR 并添加到 header
        data_descriptor = os.getenv("DATA_DESCRIPTOR")
        if data_descriptor:
            headers["Data-Descriptor"] = data_descriptor
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                request_kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers
                }
                
                if payload is not None:
                    request_kwargs["json"] = payload
                
                if params is not None:
                    request_kwargs["params"] = params
                
                async with session.request(**request_kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
                    
            except aiohttp.ClientError as e:
                raise Exception(f"HTTP request failed: {e}")
            except json.JSONDecodeError as e:
                raise Exception(f"Response JSON parsing failed: {e}")

    async def acreate_semantic_domain(self, semantic_domain: SemanticDomainData) -> Dict[str, Any]:
        """
        Create single semantic domain record
        
        Args:
            semantic_domain: SemanticDomain data object
            
        Returns:
            API response result
            
        Example:
            >>> semantic_domain = SemanticDomainData(
            ...     semantic_domain="This is a test semantic domain",
            ...     agent_card="{\"name\": \"test_agent\"}",
            ...     dd_namespace="default",
            ...     dd_name="test_app"
            ... )
            >>> result = await client.acreate_semantic_domain(semantic_domain)
        """
        payload = semantic_domain.to_dict()
        endpoint = "/semantic_domains"
        
        return await self._make_request("POST", endpoint, payload)

    async def abatch_create_semantic_domains(self, semantic_domains: List[SemanticDomainData]) -> Dict[str, Any]:
        """
        Batch create semantic domain records
        
        Args:
            semantic_domains: List of semantic domain data objects
            
        Returns:
            API response result
        """
        payload = [domain.to_dict() for domain in semantic_domains]
        endpoint = "/semantic_domains/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_semantic_domain_by_id(self, semantic_domain_id: str) -> Dict[str, Any]:
        """
        Get semantic domain record by primary key semantic_domain_id
        
        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return await self._make_request("GET", endpoint)

    async def asearch_semantic_domains_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search semantic domain records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name
        }
        endpoint = "/semantic_domains/search/by-dd"
        
        return await self._make_request("POST", endpoint, payload)

    async def aupdate_semantic_domain(self, semantic_domain_id: str, semantic_domain: SemanticDomainData) -> Dict[str, Any]:
        """
        Update semantic domain record
        
        Args:
            semantic_domain_id: Primary key of record to update
            semantic_domain: New semantic domain data
            
        Returns:
            API response result
        """
        payload = semantic_domain.to_dict()
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return await self._make_request("PUT", endpoint, payload)

    async def adelete_semantic_domain(self, semantic_domain_id: str) -> Dict[str, Any]:
        """
        Delete semantic domain record
        
        Args:
            semantic_domain_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}"
        
        return await self._make_request("DELETE", endpoint)

    async def adelete_semantic_domains_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete semantic domain records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}"
        
        return await self._make_request("DELETE", endpoint)

    async def acheck_semantic_domain_exists(self, semantic_domain_id: str) -> bool:
        """
        Check if semantic domain record exists
        
        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_domains/{semantic_domain_id}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def acheck_semantic_domain_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if semantic domain record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def aget_semantic_domain_count(self) -> int:
        """
        Get total number of semantic domain records
        
        Returns:
            int: Total record count
        """
        endpoint = "/semantic_domains/status/count"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    async def ahealth_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            await self.aget_semantic_domain_count()
            return True
        except Exception:
            return False


# Usage example
async def async_main():
    """Usage example"""
    # Create client instance
    client = AsyncSemanticDomainClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = await client.ahealth_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = await client.aget_semantic_domain_count()
        print(f"\n2. Current total semantic domain records: {count}")
        
        # Create single semantic domain record
        semantic_domain = SemanticDomainData(
            semantic_domain="This is a test semantic domain for application services",
            agent_card="{\"name\": \"test_agent\", \"description\": \"Test agent\"}",
            dd_namespace="production",
            dd_name="user_service"
        )
        
        create_result = await client.acreate_semantic_domain(semantic_domain)
        print("\n3. Create semantic domain record result:", create_result)
        
        # Batch create semantic domain records
        batch_domains = [
            SemanticDomainData(
                semantic_domain=f"Semantic domain for service {i}",
                agent_card=f"{{\"name\": \"agent_{i}\"}}",
                dd_namespace="test",
                dd_name=f"service_{i}"
            ) for i in range(2, 5)
        ]
        
        batch_result = await client.abatch_create_semantic_domains(batch_domains)
        print("\n4. Batch create result:", batch_result)
        
        # Search by DD information
        search_result = await client.asearch_semantic_domains_by_dd("test", "service_2")
        print("\n5. DD information search result:", search_result)
        
        # Check if record exists
        if search_result.get("data"):
            first_domain = search_result["data"][0]
            domain_id = first_domain.get("semantic_domain_id")
            if domain_id:
                exists = await client.acheck_semantic_domain_exists(domain_id)
                print(f"\n6. Record {domain_id} exists: {exists}")
        
    except Exception as e:
        print(f"Operation failed: {e}")

def sync_main():
    """Synchronous version usage example"""
    print("\n=== Synchronous Client Example ===")
    # Create client instance
    client = SemanticDomainClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = client.health_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = client.get_semantic_domain_count()
        print(f"2. Current total semantic domain records: {count}")
        
        # Create single semantic domain record
        semantic_domain = SemanticDomainData(
            semantic_domain="Synchronous test semantic domain record",
            agent_card="{\"name\": \"sync_agent\"}",
            dd_namespace="production",
            dd_name="sync_service"
        )
        
        create_result = client.create_semantic_domain(semantic_domain)
        print(f"3. Create semantic domain record result: {create_result}")
        
        # Search by DD information
        search_result = client.search_semantic_domains_by_dd("production", "sync_service")
        print(f"4. DD information search result: {search_result}")
        
        print("Synchronous operations completed!")
        
    except Exception as e:
        print(f"Synchronous operations failed: {e}")


if __name__ == "__main__":
    import asyncio

    # Run asynchronous example
    asyncio.run(async_main())
    
    # Run synchronous example
    # sync_main()
