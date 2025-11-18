import aiohttp
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import requests

@dataclass
class FingerprintData:
    """Fingerprint data class"""
    fingerprint_id: str
    fingerprint_summary: str
    agent_info_name: str
    agent_info_description: str
    dd_namespace: str
    dd_name: str
    fid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {
            "fingerprint_id": self.fingerprint_id,
            "fingerprint_summary": self.fingerprint_summary,
            "agent_info_name": self.agent_info_name,
            "agent_info_description": self.agent_info_description,
            "dd_namespace": self.dd_namespace,
            "dd_name": self.dd_name
        }
        if self.fid:
            data["fid"] = self.fid
        return data

class FingerprintClient:
    """Synchronous version of fingerprint service API client (stateless version)"""
    
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

    def create_fingerprint(self, fingerprint: FingerprintData) -> Dict[str, Any]:
        """
        Create single fingerprint record
        
        Args:
            fingerprint: Fingerprint data object
            
        Returns:
            API response result
        """
        payload = fingerprint.to_dict()
        endpoint = "/fingerprints"
        
        return self._make_request("POST", endpoint, payload)

    def batch_create_fingerprints(self, fingerprints: List[FingerprintData]) -> Dict[str, Any]:
        """
        Batch create fingerprint records
        
        Args:
            fingerprints: List of fingerprint data objects
            
        Returns:
            API response result
        """
        payload = [fp.to_dict() for fp in fingerprints]
        endpoint = "/fingerprints/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_fingerprint_by_fid(self, fid: str) -> Dict[str, Any]:
        """
        Get fingerprint record by primary key fid
        
        Args:
            fid: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/{fid}"
        
        return self._make_request("GET", endpoint)

    def get_fingerprint_by_fingerprint_id(self, fingerprint_id: str) -> Dict[str, Any]:
        """
        Get fingerprint record by fingerprint ID
        
        Args:
            fingerprint_id: Fingerprint ID
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/fingerprint_id/{fingerprint_id}"
        
        return self._make_request("GET", endpoint)

    def search_fingerprints_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search fingerprint records by DD information
        
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
        endpoint = "/fingerprints/search/by-dd"
        
        return self._make_request("POST", endpoint, payload)

    def update_fingerprint(self, fid: str, fingerprint: FingerprintData) -> Dict[str, Any]:
        """
        Update fingerprint record
        
        Args:
            fid: Primary key of record to update
            fingerprint: New fingerprint data
            
        Returns:
            API response result
        """
        payload = fingerprint.to_dict()
        endpoint = f"/fingerprints/{fid}"
        
        return self._make_request("PUT", endpoint, payload)

    def delete_fingerprint(self, fid: str) -> Dict[str, Any]:
        """
        Delete fingerprint record
        
        Args:
            fid: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/{fid}"
        
        return self._make_request("DELETE", endpoint)

    def delete_fingerprints_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete fingerprint records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/dd_info/{dd_namespace}/{dd_name}"
        
        return self._make_request("DELETE", endpoint)

    def check_fingerprint_exists(self, fid: str) -> bool:
        """
        Check if fingerprint record exists
        
        Args:
            fid: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/fingerprints/{fid}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def check_fingerprint_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if fingerprint record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/fingerprints/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def get_fingerprint_count(self) -> int:
        """
        Get total number of fingerprint records
        
        Returns:
            int: Total record count
        """
        endpoint = "/fingerprints/status/count"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_fingerprint_count()
            return True
        except Exception:
            return False


class AsyncFingerprintClient:
    """Fingerprint service API client"""
    
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

    async def acreate_fingerprint(self, fingerprint: FingerprintData) -> Dict[str, Any]:
        """
        Create single fingerprint record
        
        Args:
            fingerprint: Fingerprint data object
            
        Returns:
            API response result
            
        Example:
            >>> fingerprint = FingerprintData(
            ...     fingerprint_id="FP123456",
            ...     fingerprint_summary="Test fingerprint summary",
            ...     agent_info_name="Test agent",
            ...     agent_info_description="Test agent description",
            ...     dd_namespace="default",
            ...     dd_name="test_app"
            ... )
            >>> result = await client.create_fingerprint(fingerprint)
        """
        payload = fingerprint.to_dict()
        endpoint = "/fingerprints"
        
        return await self._make_request("POST", endpoint, payload)

    async def abatch_create_fingerprints(self, fingerprints: List[FingerprintData]) -> Dict[str, Any]:
        """
        Batch create fingerprint records
        
        Args:
            fingerprints: List of fingerprint data objects
            
        Returns:
            API response result
        """
        payload = [fp.to_dict() for fp in fingerprints]
        endpoint = "/fingerprints/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_fingerprint_by_fid(self, fid: str) -> Dict[str, Any]:
        """
        Get fingerprint record by primary key fid
        
        Args:
            fid: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/{fid}"
        
        return await self._make_request("GET", endpoint)

    async def aget_fingerprint_by_fingerprint_id(self, fingerprint_id: str) -> Dict[str, Any]:
        """
        Get fingerprint record by fingerprint ID
        
        Args:
            fingerprint_id: Fingerprint ID
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/fingerprint_id/{fingerprint_id}"
        
        return await self._make_request("GET", endpoint)

    async def asearch_fingerprints_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search fingerprint records by DD information
        
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
        endpoint = "/fingerprints/search/by-dd"
        
        return await self._make_request("POST", endpoint, payload)

    async def aupdate_fingerprint(self, fid: str, fingerprint: FingerprintData) -> Dict[str, Any]:
        """
        Update fingerprint record
        
        Args:
            fid: Primary key of record to update
            fingerprint: New fingerprint data
            
        Returns:
            API response result
        """
        payload = fingerprint.to_dict()
        endpoint = f"/fingerprints/{fid}"
        
        return await self._make_request("PUT", endpoint, payload)

    async def adelete_fingerprint(self, fid: str) -> Dict[str, Any]:
        """
        Delete fingerprint record
        
        Args:
            fid: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/{fid}"
        
        return await self._make_request("DELETE", endpoint)

    async def adelete_fingerprints_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete fingerprint records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/fingerprints/dd_info/{dd_namespace}/{dd_name}"
        
        return await self._make_request("DELETE", endpoint)

    async def acheck_fingerprint_exists(self, fid: str) -> bool:
        """
        Check if fingerprint record exists
        
        Args:
            fid: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/fingerprints/{fid}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def acheck_fingerprint_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if fingerprint record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/fingerprints/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def aget_fingerprint_count(self) -> int:
        """
        Get total number of fingerprint records
        
        Returns:
            int: Total record count
        """
        endpoint = "/fingerprints/status/count"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    async def ahealth_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            await self.get_fingerprint_count()
            return True
        except Exception:
            return False


# Usage example
async def async_main():
    """Usage example"""
    # Create client instance
    client = AsyncFingerprintClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = await client.ahealth_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = await client.aget_fingerprint_count()
        print(f"\n2. Current total fingerprint records: {count}")
        
        # Create single fingerprint record
        fingerprint = FingerprintData(
            fingerprint_id="FP001",
            fingerprint_summary="This is a test fingerprint record",
            agent_info_name="Test agent",
            agent_info_description="Agent service for testing",
            dd_namespace="production",
            dd_name="user_service"
        )
        
        create_result = await client.acreate_fingerprint(fingerprint)
        print("\n3. Create fingerprint record result:", create_result)
        
        # Batch create fingerprint records
        batch_fingerprints = [
            FingerprintData(
                fingerprint_id=f"FP00{i}",
                fingerprint_summary=f"Batch test fingerprint {i}",
                agent_info_name=f"Agent{i}",
                agent_info_description=f"Batch test agent {i}",
                dd_namespace="test",
                dd_name=f"service_{i}"
            ) for i in range(2, 5)
        ]
        
        batch_result = await client.abatch_create_fingerprints(batch_fingerprints)
        print("\n4. Batch create result:", batch_result)
        
        # Search by DD information
        search_result = await client.asearch_fingerprints_by_dd("test", "service_2")
        print("\n5. DD information search result:", search_result)
        
        # Check if record exists
        if search_result.get("data"):
            first_fingerprint = search_result["data"][0]
            fid = first_fingerprint.get("fid")
            if fid:
                exists = await client.acheck_fingerprint_exists(fid)
                print(f"\n6. Record {fid} exists: {exists}")
        
    except Exception as e:
        print(f"Operation failed: {e}")

def sync_main():
    """Synchronous version usage example"""
    print("\n=== Synchronous Client Example ===")
    # Create client instance
    client = FingerprintClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = client.health_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = client.get_fingerprint_count()
        print(f"2. Current total fingerprint records: {count}")
        
        # Create single fingerprint record
        fingerprint = FingerprintData(
            fingerprint_id="FP002",
            fingerprint_summary="Synchronous test fingerprint record",
            agent_info_name="Synchronous test agent",
            agent_info_description="Agent service for synchronous testing",
            dd_namespace="production",
            dd_name="sync_service"
        )
        
        create_result = client.create_fingerprint(fingerprint)
        print(f"3. Create fingerprint record result: {create_result}")
        
        # Search by DD information
        search_result = client.search_fingerprints_by_dd("production", "sync_service")
        print(f"4. DD information search result: {search_result}")
        
        print("Synchronous operations completed!")
        
    except Exception as e:
        print(f"Synchronous operations failed: {e}")


if __name__ == "__main__":
    import asyncio

    # Run asynchronous example
    # asyncio.run(async_main())
    
    # Run synchronous example
    sync_main()
