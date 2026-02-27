import aiohttp
import json
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import requests

@dataclass
class SemanticGroupData:
    """SemanticGroup data class"""
    group_name: str
    description: Optional[str] = None
    agent_card: Optional[str] = None
    version: Optional[str] = None
    id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {
            "group_name": self.group_name
        }
        if self.description is not None:
            data["description"] = self.description
        if self.agent_card is not None:
            data["agent_card"] = self.agent_card
        if self.version is not None:
            data["version"] = self.version
        if self.id is not None:
            data["id"] = self.id
        return data

@dataclass
class DDGroupRelationData:
    """DDGroupRelation data class"""
    sd_id: str
    group_id: str
    association_reason: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = {
            "sd_id": self.sd_id,
            "group_id": self.group_id
        }
        if self.association_reason is not None:
            data["association_reason"] = self.association_reason
        if self.id is not None:
            data["id"] = self.id
        return data

class SemanticGroupClient:
    """Synchronous version of semantic group service API client (stateless version)"""
    
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

    def create_semantic_group(self, semantic_group: SemanticGroupData) -> Dict[str, Any]:
        """
        Create single semantic group record
        
        Args:
            semantic_group: SemanticGroup data object
            
        Returns:
            API response result
        """
        payload = semantic_group.to_dict()
        endpoint = "/semantic_groups"
        
        return self._make_request("POST", endpoint, payload)

    def batch_create_semantic_groups(self, semantic_groups: List[SemanticGroupData]) -> Dict[str, Any]:
        """
        Batch create semantic group records
        
        Args:
            semantic_groups: List of semantic group data objects
            
        Returns:
            API response result
        """
        payload = [group.to_dict() for group in semantic_groups]
        endpoint = "/semantic_groups/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_semantic_group_by_id(self, group_id: str) -> Dict[str, Any]:
        """
        Get semantic group record by primary key group_id
        
        Args:
            group_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_groups/{group_id}"
        
        return self._make_request("GET", endpoint)

    def get_all_semantic_groups(self, page: Optional[int] = None, page_size: Optional[int] = None) -> Dict[str, Any]:
        """
        Get all semantic group records (supports pagination)
        
        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            API response result
        """
        endpoint = "/semantic_groups"
        params = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        
        return self._make_request("GET", endpoint, params=params if params else None)

    def update_semantic_group(self, group_id: str, semantic_group: SemanticGroupData) -> Dict[str, Any]:
        """
        Update semantic group record
        
        Args:
            group_id: Primary key of record to update
            semantic_group: New semantic group data
            
        Returns:
            API response result
        """
        payload = semantic_group.to_dict()
        endpoint = f"/semantic_groups/{group_id}"
        
        return self._make_request("PUT", endpoint, payload)

    def delete_semantic_group(self, group_id: str) -> Dict[str, Any]:
        """
        Delete semantic group record
        
        Args:
            group_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_groups/{group_id}"
        
        return self._make_request("DELETE", endpoint)

    def check_semantic_group_exists(self, group_id: str) -> bool:
        """
        Check if semantic group record exists
        
        Args:
            group_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_groups/{group_id}/exists"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    def get_semantic_group_count(self) -> int:
        """
        Get total number of semantic group records
        
        Returns:
            int: Total record count
        """
        endpoint = "/semantic_groups/status/count"
        
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_semantic_group_count()
            return True
        except Exception:
            return False

    # DD Group Relation methods
    def create_dd_group_relation(self, relation: DDGroupRelationData) -> Dict[str, Any]:
        """
        Create single DD group relation record
        
        Args:
            relation: DDGroupRelation data object
            
        Returns:
            API response result
        """
        payload = relation.to_dict()
        endpoint = "/dd_group_relations"
        
        return self._make_request("POST", endpoint, payload)

    def batch_create_dd_group_relations(self, relations: List[DDGroupRelationData]) -> Dict[str, Any]:
        """
        Batch create DD group relation records
        
        Args:
            relations: List of DD group relation data objects
            
        Returns:
            API response result
        """
        payload = [relation.to_dict() for relation in relations]
        endpoint = "/dd_group_relations/batch"
        
        return self._make_request("POST", endpoint, payload)

    def get_relations_by_group_id(self, group_id: str) -> Dict[str, Any]:
        """
        Get DD group relations by group_id
        
        Args:
            group_id: Group ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/group/{group_id}"
        
        return self._make_request("GET", endpoint)

    def get_relations_by_sd_id(self, sd_id: str) -> Dict[str, Any]:
        """
        Get DD group relations by sd_id
        
        Args:
            sd_id: Semantic domain ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/sd/{sd_id}"
        
        return self._make_request("GET", endpoint)

    def delete_dd_group_relation(self, relation_id: int) -> Dict[str, Any]:
        """
        Delete DD group relation record
        
        Args:
            relation_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/{relation_id}"
        
        return self._make_request("DELETE", endpoint)

    def delete_relations_by_group_id(self, group_id: str) -> Dict[str, Any]:
        """
        Delete all DD group relations by group_id
        
        Args:
            group_id: Group ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/group/{group_id}"
        
        return self._make_request("DELETE", endpoint)

    def delete_relations_by_sd_id(self, sd_id: str) -> Dict[str, Any]:
        """
        Delete all DD group relations by sd_id
        
        Args:
            sd_id: Semantic domain ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/sd/{sd_id}"
        
        return self._make_request("DELETE", endpoint)


class AsyncSemanticGroupClient:
    """SemanticGroup service API client"""
    
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

    async def acreate_semantic_group(self, semantic_group: SemanticGroupData) -> Dict[str, Any]:
        """
        Create single semantic group record (async)
        
        Args:
            semantic_group: SemanticGroup data object
            
        Returns:
            API response result
            
        Example:
            >>> semantic_group = SemanticGroupData(
            ...     group_name="AI模型应用与服务管理平台",
            ...     description="这是一个用于管理AI模型应用和服务的平台组",
            ...     version="v1.0"
            ... )
            >>> result = await client.acreate_semantic_group(semantic_group)
        """
        payload = semantic_group.to_dict()
        endpoint = "/semantic_groups"
        
        return await self._make_request("POST", endpoint, payload)

    async def abatch_create_semantic_groups(self, semantic_groups: List[SemanticGroupData]) -> Dict[str, Any]:
        """
        Batch create semantic group records (async)
        
        Args:
            semantic_groups: List of semantic group data objects
            
        Returns:
            API response result
        """
        payload = [group.to_dict() for group in semantic_groups]
        endpoint = "/semantic_groups/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_semantic_group_by_id(self, group_id: str) -> Dict[str, Any]:
        """
        Get semantic group record by primary key group_id (async)
        
        Args:
            group_id: Primary key ID
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_groups/{group_id}"
        
        return await self._make_request("GET", endpoint)

    async def aget_all_semantic_groups(self, page: Optional[int] = None, page_size: Optional[int] = None) -> Dict[str, Any]:
        """
        Get all semantic group records (supports pagination) (async)
        
        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            API response result
        """
        endpoint = "/semantic_groups"
        params = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        
        return await self._make_request("GET", endpoint, params=params if params else None)

    async def aupdate_semantic_group(self, group_id: str, semantic_group: SemanticGroupData) -> Dict[str, Any]:
        """
        Update semantic group record (async)
        
        Args:
            group_id: Primary key of record to update
            semantic_group: New semantic group data
            
        Returns:
            API response result
        """
        payload = semantic_group.to_dict()
        endpoint = f"/semantic_groups/{group_id}"
        
        return await self._make_request("PUT", endpoint, payload)

    async def adelete_semantic_group(self, group_id: str) -> Dict[str, Any]:
        """
        Delete semantic group record (async)
        
        Args:
            group_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/semantic_groups/{group_id}"
        
        return await self._make_request("DELETE", endpoint)

    async def acheck_semantic_group_exists(self, group_id: str) -> bool:
        """
        Check if semantic group record exists (async)
        
        Args:
            group_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        endpoint = f"/semantic_groups/{group_id}/exists"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("exists", False)

    async def aget_semantic_group_count(self) -> int:
        """
        Get total number of semantic group records (async)
        
        Returns:
            int: Total record count
        """
        endpoint = "/semantic_groups/status/count"
        
        response = await self._make_request("GET", endpoint)
        return response.get("data", {}).get("total_count", 0)

    async def ahealth_check(self) -> bool:
        """
        Health check (async)
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            await self.aget_semantic_group_count()
            return True
        except Exception:
            return False

    # DD Group Relation methods (async)
    async def acreate_dd_group_relation(self, relation: DDGroupRelationData) -> Dict[str, Any]:
        """
        Create single DD group relation record (async)
        
        Args:
            relation: DDGroupRelation data object
            
        Returns:
            API response result
        """
        payload = relation.to_dict()
        endpoint = "/dd_group_relations"
        
        return await self._make_request("POST", endpoint, payload)

    async def abatch_create_dd_group_relations(self, relations: List[DDGroupRelationData]) -> Dict[str, Any]:
        """
        Batch create DD group relation records (async)
        
        Args:
            relations: List of DD group relation data objects
            
        Returns:
            API response result
        """
        payload = [relation.to_dict() for relation in relations]
        endpoint = "/dd_group_relations/batch"
        
        return await self._make_request("POST", endpoint, payload)

    async def aget_relations_by_group_id(self, group_id: str) -> Dict[str, Any]:
        """
        Get DD group relations by group_id (async)
        
        Args:
            group_id: Group ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/group/{group_id}"
        
        return await self._make_request("GET", endpoint)

    async def aget_relations_by_sd_id(self, sd_id: str) -> Dict[str, Any]:
        """
        Get DD group relations by sd_id (async)
        
        Args:
            sd_id: Semantic domain ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/sd/{sd_id}"
        
        return await self._make_request("GET", endpoint)

    async def adelete_dd_group_relation(self, relation_id: int) -> Dict[str, Any]:
        """
        Delete DD group relation record (async)
        
        Args:
            relation_id: Primary key of record to delete
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/{relation_id}"
        
        return await self._make_request("DELETE", endpoint)

    async def adelete_relations_by_group_id(self, group_id: str) -> Dict[str, Any]:
        """
        Delete all DD group relations by group_id (async)
        
        Args:
            group_id: Group ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/group/{group_id}"
        
        return await self._make_request("DELETE", endpoint)

    async def adelete_relations_by_sd_id(self, sd_id: str) -> Dict[str, Any]:
        """
        Delete all DD group relations by sd_id (async)
        
        Args:
            sd_id: Semantic domain ID
            
        Returns:
            API response result
        """
        endpoint = f"/dd_group_relations/sd/{sd_id}"
        
        return await self._make_request("DELETE", endpoint)


# Usage example
async def async_main():
    """Usage example"""
    # Create client instance
    client = AsyncSemanticGroupClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = await client.ahealth_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = await client.aget_semantic_group_count()
        print(f"\n2. Current total semantic group records: {count}")
        
        # Create single semantic group record
        semantic_group = SemanticGroupData(
            group_name="AI模型应用与服务管理平台",
            description="这是一个用于管理AI模型应用和服务的平台组",
            version="v1.0"
        )
        
        create_result = await client.acreate_semantic_group(semantic_group)
        print("\n3. Create semantic group record result:", create_result)
        
        # Batch create semantic group records
        batch_groups = [
            SemanticGroupData(
                group_name=f"Group {i}",
                description=f"Description for group {i}",
                version="v1.0"
            ) for i in range(2, 5)
        ]
        
        batch_result = await client.abatch_create_semantic_groups(batch_groups)
        print("\n4. Batch create result:", batch_result)
        
        # Get all groups
        all_groups = await client.aget_all_semantic_groups()
        print("\n5. Get all groups result:", all_groups)
        
        # Test DD Group Relation operations
        if create_result.get("data") and create_result["data"].get("id"):
            group_id = create_result["data"]["id"]
            
            # Create a DD group relation
            test_sd_id = "test_sd_id_" + str(uuid.uuid4())[:8]
            relation = DDGroupRelationData(
                sd_id=test_sd_id,
                group_id=group_id,
                association_reason="测试关联原因：语义相似性分析"
            )
            
            relation_result = await client.acreate_dd_group_relation(relation)
            print("\n6. Create DD group relation result:", relation_result)
            
            # Get relations by SD ID
            relations_by_sd = await client.aget_relations_by_sd_id(test_sd_id)
            print("\n7. Get relations by SD ID result:", relations_by_sd)
            
            # Get relations by Group ID
            relations_by_group = await client.aget_relations_by_group_id(group_id)
            print("\n8. Get relations by Group ID result:", relations_by_group)
        
    except Exception as e:
        print(f"Operation failed: {e}")

def sync_main():
    """Synchronous version usage example"""
    print("\n=== Synchronous Client Example ===")
    # Create client instance
    client = SemanticGroupClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # Health check
        is_healthy = client.health_check()
        print(f"1. Service health status: {is_healthy}")
        
        # Get total record count
        count = client.get_semantic_group_count()
        print(f"2. Current total semantic group records: {count}")
        
        # Create single semantic group record
        semantic_group = SemanticGroupData(
            group_name="Synchronous Test Group",
            description="Synchronous test semantic group record",
            version="v1.0"
        )
        
        create_result = client.create_semantic_group(semantic_group)
        print(f"3. Create semantic group record result: {create_result}")
        
        # Get all groups
        all_groups = client.get_all_semantic_groups()
        print(f"4. Get all groups result: {all_groups}")
        
        print("Synchronous operations completed!")
        
    except Exception as e:
        print(f"Synchronous operations failed: {e}")


if __name__ == "__main__":
    import asyncio

    # Run asynchronous example
    asyncio.run(async_main())
    
    # Run synchronous example
    # sync_main()
