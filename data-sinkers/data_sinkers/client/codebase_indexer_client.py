import aiohttp
import json
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import requests

@dataclass
class CodebaseIndexerData:
    """CodebaseIndexer data class"""
    filepath: Optional[str] = None
    code_deep_analysis: Optional[str] = None
    dd_namespace: Optional[str] = None
    dd_name: Optional[str] = None
    codebase_indexer_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {}
        if self.filepath is not None:
            data["filepath"] = self.filepath
        if self.code_deep_analysis is not None:
            data["code_deep_analysis"] = self.code_deep_analysis
        if self.dd_namespace is not None:
            data["dd_namespace"] = self.dd_namespace
        if self.dd_name is not None:
            data["dd_name"] = self.dd_name
        if self.codebase_indexer_id is not None:
            data["codebase_indexer_id"] = self.codebase_indexer_id
        return data

class CodebaseIndexerClient:
    """Synchronous version of codebase indexer service API client (stateless version)"""
    
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

    def batch_create_codebase_indexers(self, codebase_indexers: List[CodebaseIndexerData]) -> Dict[str, Any]:
        """
        Batch create codebase indexer records
        
        Args:
            codebase_indexers: List of codebase indexer data objects
            
        Returns:
            API response result
        """
        payload = [indexer.to_dict() for indexer in codebase_indexers]
        endpoint = "/codebase_indexers/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_codebase_indexer_count(self) -> int:
        """
        Get total number of codebase indexer records
        
        Returns:
            int: Total record count
        """
        endpoint = "/codebase_indexers/status/count"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    def check_codebase_indexer_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if codebase indexer record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def delete_codebase_indexers_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete codebase indexer records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}"
        
        return self._make_request("DELETE", endpoint)

    def search_codebase_indexers_by_filepath(
        self, 
        filepath: str, 
        dd_namespace: Optional[str] = None, 
        dd_name: Optional[str] = None,
        prefix_match: bool = False
    ) -> Dict[str, Any]:
        """
        Search codebase indexer records by filepath
        
        Args:
            filepath: File path to search for
            dd_namespace: Optional DD namespace filter
            dd_name: Optional DD name filter
            prefix_match: If True, use LIKE query for prefix matching
            
        Returns:
            API response result with list of matching records
        """
        endpoint = "/codebase_indexers/search/by-filepath"
        payload = {
            "filepath": filepath,
            "prefix_match": prefix_match
        }
        if dd_namespace is not None:
            payload["dd_namespace"] = dd_namespace
        if dd_name is not None:
            payload["dd_name"] = dd_name
        
        return self._make_request("POST", endpoint, payload)

    def search_codebase_indexers_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search codebase indexer records by DD namespace and name
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result with list of matching records
        """
        endpoint = "/codebase_indexers/search/by-dd"
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name
        }
        
        return self._make_request("POST", endpoint, payload)

    def get_codebase_indexer_by_id(self, codebase_indexer_id: str) -> Dict[str, Any]:
        """
        Get codebase indexer record by ID
        
        Args:
            codebase_indexer_id: Record ID
            
        Returns:
            API response result with record data
        """
        endpoint = f"/codebase_indexers/{codebase_indexer_id}"
        
        return self._make_request("GET", endpoint)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_codebase_indexer_count()
            return True
        except Exception:
            return False


class AsyncCodebaseIndexerClient:
    """CodebaseIndexer service API client"""
    
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

    async def abatch_create_codebase_indexers(self, codebase_indexers: List[CodebaseIndexerData]) -> Dict[str, Any]:
        """
        Batch create codebase indexer records
        
        Args:
            codebase_indexers: List of codebase indexer data objects
            
        Returns:
            API response result
        """
        payload = [indexer.to_dict() for indexer in codebase_indexers]
        endpoint = "/codebase_indexers/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_codebase_indexer_count(self) -> int:
        """
        Get total number of codebase indexer records
        
        Returns:
            int: Total record count
        """
        endpoint = "/codebase_indexers/status/count"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    async def acheck_codebase_indexer_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if codebase indexer record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def adelete_codebase_indexers_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete codebase indexer records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}"
        
        return await self._make_request("DELETE", endpoint)

    async def asearch_codebase_indexers_by_filepath(
        self, 
        filepath: str, 
        dd_namespace: Optional[str] = None, 
        dd_name: Optional[str] = None,
        prefix_match: bool = False
    ) -> Dict[str, Any]:
        """
        Search codebase indexer records by filepath
        
        Args:
            filepath: File path to search for
            dd_namespace: Optional DD namespace filter
            dd_name: Optional DD name filter
            prefix_match: If True, use LIKE query for prefix matching
            
        Returns:
            API response result with list of matching records
        """
        endpoint = "/codebase_indexers/search/by-filepath"
        payload = {
            "filepath": filepath,
            "prefix_match": prefix_match
        }
        if dd_namespace is not None:
            payload["dd_namespace"] = dd_namespace
        if dd_name is not None:
            payload["dd_name"] = dd_name
        
        return await self._make_request("POST", endpoint, payload)

    async def asearch_codebase_indexers_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search codebase indexer records by DD namespace and name
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result with list of matching records
        """
        endpoint = "/codebase_indexers/search/by-dd"
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name
        }
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_codebase_indexer_by_id(self, codebase_indexer_id: str) -> Dict[str, Any]:
        """
        Get codebase indexer record by ID
        
        Args:
            codebase_indexer_id: Record ID
            
        Returns:
            API response result with record data
        """
        endpoint = f"/codebase_indexers/{codebase_indexer_id}"
        
        return await self._make_request("GET", endpoint)

    async def ahealth_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            await self.aget_codebase_indexer_count()
            return True
        except Exception:
            return False


# Usage example
async def async_main():
    """Usage example"""
    # Create client instance
    client = AsyncCodebaseIndexerClient(base_url="http://192.168.3.7:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = await client.ahealth_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = await client.aget_codebase_indexer_count()
        print(f"\n2. Current total codebase indexer records: {count}")
        
        # Batch create codebase indexer records
        batch_indexers = [
            CodebaseIndexerData(
                filepath=f"/src/module_{i}/main.py",
                code_deep_analysis=f"Code analysis for module {i}",
                dd_namespace="test_namespace",
                dd_name="test_app"
            ) for i in range(1, 4)
        ]
        
        batch_result = await client.abatch_create_codebase_indexers(batch_indexers)
        print("\n3. Batch create result:", batch_result)
        
        # Check if records exist by DD info
        exists = await client.acheck_codebase_indexer_exists_by_dd_info("test_namespace", "test_app")
        print(f"\n4. Records exist for test_namespace/test_app: {exists}")
        
        # Get count after creation
        count_after = await client.aget_codebase_indexer_count()
        print(f"\n5. Total records after creation: {count_after}")
        
        # Delete by DD info
        delete_result = await client.adelete_codebase_indexers_by_dd_info("test_namespace", "test_app")
        print(f"\n6. Delete by DD info result: {delete_result}")
        
        # Verify deletion
        exists_after = await client.acheck_codebase_indexer_exists_by_dd_info("test_namespace", "test_app")
        print(f"\n7. Records exist after deletion: {exists_after}")
        
    except Exception as e:
        print(f"Operation failed: {e}")

def sync_main():
    """Synchronous version usage example"""
    print("\n=== Synchronous Client Example ===")
    # Create client instance
    client = CodebaseIndexerClient(base_url="http://192.168.3.7:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = client.health_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = client.get_codebase_indexer_count()
        print(f"2. Current total codebase indexer records: {count}")
        
        # Batch create codebase indexer records
        batch_indexers = [
            CodebaseIndexerData(
                filepath=f"/src/sync_module_{i}/main.py",
                code_deep_analysis=f"Sync code analysis for module {i}",
                dd_namespace="sync_namespace",
                dd_name="sync_app"
            ) for i in range(1, 3)
        ]
        
        batch_result = client.batch_create_codebase_indexers(batch_indexers)
        print(f"3. Batch create result: {batch_result}")
        
        # Check existence by DD info
        exists = client.check_codebase_indexer_exists_by_dd_info("sync_namespace", "sync_app")
        print(f"4. Records exist: {exists}")
        
        # Delete by DD info
        delete_result = client.delete_codebase_indexers_by_dd_info("sync_namespace", "sync_app")
        print(f"5. Delete result: {delete_result}")
        
        print("Synchronous operations completed!")
        
    except Exception as e:
        print(f"Synchronous operations failed: {e}")


if __name__ == "__main__":
    import asyncio

    # Run asynchronous example
    asyncio.run(async_main())
    
    # Run synchronous example
    # sync_main()
