import aiohttp
import json
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import requests

@dataclass
class SignatureData:
    """Signature data class"""
    sig_type: str
    discovery_mode: str
    fingerprint: str
    location_info: Optional[Dict[str, Any]] = None
    metadata_content: Optional[Dict[str, Any]] = None
    dd_namespace: Optional[str] = None
    dd_name: Optional[str] = None
    sig_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {
            "sig_type": self.sig_type,
            "discovery_mode": self.discovery_mode,
            "fingerprint": self.fingerprint,
        }
        if self.location_info is not None:
            data["location_info"] = self.location_info
        if self.metadata_content is not None:
            data["metadata_content"] = self.metadata_content
        if self.dd_namespace is not None:
            data["dd_namespace"] = self.dd_namespace
        if self.dd_name is not None:
            data["dd_name"] = self.dd_name
        if self.sig_id:
            data["sig_id"] = self.sig_id
        return data

class SignatureClient:
    """Synchronous version of signature service API client (stateless version)"""
    
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

    def create_signature(self, signature: SignatureData) -> Dict[str, Any]:
        """
        Create single signature record
        
        Args:
            signature: Signature data object
            
        Returns:
            API response result
        """
        payload = signature.to_dict()
        endpoint = "/signatures"
        
        return self._make_request("POST", endpoint, payload)

    def batch_create_signatures(self, signatures: List[SignatureData]) -> Dict[str, Any]:
        """
        Batch create signature records
        
        Args:
            signatures: List of signature data objects
            
        Returns:
            API response result
        """
        payload = [sig.to_dict() for sig in signatures]
        endpoint = "/signatures/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_signature_by_sig_id(self, sig_id: str) -> Dict[str, Any]:
        """
        Get signature record by primary key sig_id
        
        Args:
            sig_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/{sig_id}"
        
        return self._make_request("GET", endpoint)

    def get_signature_by_fingerprint(self, fingerprint: str) -> Dict[str, Any]:
        """
        Get signature record by fingerprint value
        
        Args:
            fingerprint: Fingerprint value
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/fingerprint/{fingerprint}"
        
        return self._make_request("GET", endpoint)

    def search_signatures_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search signature records by DD information
        
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
        endpoint = "/signatures/search/by-dd"
        
        return self._make_request("POST", endpoint, payload)

    def update_signature(self, sig_id: str, signature: SignatureData) -> Dict[str, Any]:
        """
        Update signature record
        
        Args:
            sig_id: Primary key of record to update
            signature: New signature data
            
        Returns:
            API response result
        """
        payload = signature.to_dict()
        endpoint = f"/signatures/{sig_id}"
        
        return self._make_request("PUT", endpoint, payload)

    def delete_signature(self, sig_id: str) -> Dict[str, Any]:
        """
        Delete signature record
        
        Args:
            sig_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/{sig_id}"
        
        return self._make_request("DELETE", endpoint)

    def delete_signatures_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete signature records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/dd_info/{dd_namespace}/{dd_name}"
        
        return self._make_request("DELETE", endpoint)

    def check_signature_exists(self, sig_id: str) -> bool:
        """
        Check if signature record exists
        
        Args:
            sig_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/signatures/{sig_id}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def check_signature_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if signature record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/signatures/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def get_signature_count(self) -> int:
        """
        Get total number of signature records
        
        Returns:
            int: Total record count
        """
        endpoint = "/signatures/status/count"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_signature_count()
            return True
        except Exception:
            return False


class AsyncSignatureClient:
    """Signature service API client"""
    
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

    async def acreate_signature(self, signature: SignatureData) -> Dict[str, Any]:
        """
        Create single signature record
        
        Args:
            signature: Signature data object
            
        Returns:
            API response result
            
        Example:
            >>> signature = SignatureData(
            ...     sig_type="application",
            ...     discovery_mode="auto",
            ...     fingerprint="FP123456",
            ...     metadata_content={"summary": "Test signature summary"},
            ...     dd_namespace="default",
            ...     dd_name="test_app"
            ... )
            >>> result = await client.acreate_signature(signature)
        """
        payload = signature.to_dict()
        endpoint = "/signatures"
        
        return await self._make_request("POST", endpoint, payload)

    async def abatch_create_signatures(self, signatures: List[SignatureData]) -> Dict[str, Any]:
        """
        Batch create signature records
        
        Args:
            signatures: List of signature data objects
            
        Returns:
            API response result
        """
        payload = [sig.to_dict() for sig in signatures]
        endpoint = "/signatures/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_signature_by_sig_id(self, sig_id: str) -> Dict[str, Any]:
        """
        Get signature record by primary key sig_id
        
        Args:
            sig_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/{sig_id}"
        
        return await self._make_request("GET", endpoint)

    async def aget_signature_by_fingerprint(self, fingerprint: str) -> Dict[str, Any]:
        """
        Get signature record by fingerprint value
        
        Args:
            fingerprint: Fingerprint value
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/fingerprint/{fingerprint}"
        
        return await self._make_request("GET", endpoint)

    async def asearch_signatures_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Search signature records by DD information
        
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
        endpoint = "/signatures/search/by-dd"
        
        return await self._make_request("POST", endpoint, payload)

    async def aupdate_signature(self, sig_id: str, signature: SignatureData) -> Dict[str, Any]:
        """
        Update signature record
        
        Args:
            sig_id: Primary key of record to update
            signature: New signature data
            
        Returns:
            API response result
        """
        payload = signature.to_dict()
        endpoint = f"/signatures/{sig_id}"
        
        return await self._make_request("PUT", endpoint, payload)

    async def adelete_signature(self, sig_id: str) -> Dict[str, Any]:
        """
        Delete signature record
        
        Args:
            sig_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/{sig_id}"
        
        return await self._make_request("DELETE", endpoint)

    async def adelete_signatures_by_dd_info(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """
        Delete signature records by DD information
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            API response result
        """
        endpoint = f"/signatures/dd_info/{dd_namespace}/{dd_name}"
        
        return await self._make_request("DELETE", endpoint)

    async def acheck_signature_exists(self, sig_id: str) -> bool:
        """
        Check if signature record exists
        
        Args:
            sig_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/signatures/{sig_id}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def acheck_signature_exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if signature record with DD information exists
        
        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/signatures/dd_info/{dd_namespace}/{dd_name}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def aget_signature_count(self) -> int:
        """
        Get total number of signature records
        
        Returns:
            int: Total record count
        """
        endpoint = "/signatures/status/count"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    async def ahealth_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            await self.aget_signature_count()
            return True
        except Exception:
            return False


# Usage example
async def async_main():
    """Usage example"""
    # Create client instance
    client = AsyncSignatureClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = await client.ahealth_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = await client.aget_signature_count()
        print(f"\n2. Current total signature records: {count}")
        
        # Create single signature record
        signature = SignatureData(
            sig_type="application",
            discovery_mode="auto",
            fingerprint="FP001",
            location_info={"ip": "192.168.1.100"},
            metadata_content={"summary": "This is a test signature record"},
            dd_namespace="production",
            dd_name="user_service"
        )
        
        create_result = await client.acreate_signature(signature)
        print("\n3. Create signature record result:", create_result)
        
        # Batch create signature records
        batch_signatures = [
            SignatureData(
                sig_type="database",
                discovery_mode="manual",
                fingerprint=f"FP00{i}",
                metadata_content={"summary": f"Batch test signature {i}"},
                dd_namespace="test",
                dd_name=f"service_{i}"
            ) for i in range(2, 5)
        ]
        
        batch_result = await client.abatch_create_signatures(batch_signatures)
        print("\n4. Batch create result:", batch_result)
        
        # Search by DD information
        search_result = await client.asearch_signatures_by_dd("test", "service_2")
        print("\n5. DD information search result:", search_result)
        
        # Check if record exists
        if search_result.get("data"):
            first_signature = search_result["data"][0]
            sig_id = first_signature.get("sig_id")
            if sig_id:
                exists = await client.acheck_signature_exists(sig_id)
                print(f"\n6. Record {sig_id} exists: {exists}")
        
    except Exception as e:
        print(f"Operation failed: {e}")

def sync_main():
    """Synchronous version usage example"""
    print("\n=== Synchronous Client Example ===")
    # Create client instance
    client = SignatureClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = client.health_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = client.get_signature_count()
        print(f"2. Current total signature records: {count}")
        
        # Create single signature record
        signature = SignatureData(
            sig_type="application",
            discovery_mode="auto",
            fingerprint="FP002",
            metadata_content={"summary": "Synchronous test signature record"},
            dd_namespace="production",
            dd_name="sync_service"
        )
        
        create_result = client.create_signature(signature)
        print(f"3. Create signature record result: {create_result}")
        
        # Search by DD information
        search_result = client.search_signatures_by_dd("production", "sync_service")
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
