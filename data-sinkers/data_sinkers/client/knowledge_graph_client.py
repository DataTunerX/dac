import json
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import requests

@dataclass
class KnowledgeGraphNode:
    """KnowledgeGraph node data class"""
    id: str
    labels: List[str]
    properties: Optional[Dict[str, Any]] = None
    name: Optional[str] = None  # 支持节点顶层的name字段
    extra_fields: Optional[Dict[str, Any]] = None  # 支持其他顶层字段（如title等）

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}
        if self.extra_fields is None:
            self.extra_fields = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format, including top-level fields like name"""
        result = {
            "id": self.id,
            "labels": self.labels,
            "properties": self.properties
        }
        # 添加name字段（如果存在）
        if self.name is not None:
            result["name"] = self.name
        # 添加其他顶层字段（如果存在）
        if self.extra_fields:
            result.update(self.extra_fields)
        return result


@dataclass
class KnowledgeGraphRelationship:
    """KnowledgeGraph relationship data class"""
    start: str
    end: str
    type: str
    properties: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "start": self.start,
            "end": self.end,
            "type": self.type,
            "properties": self.properties
        }


class KnowledgeGraphClient:
    """Synchronous version of knowledge graph service API client (stateless version)"""
    
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

    def add_with_source(
        self,
        source: str,
        nodes: List[KnowledgeGraphNode],
        relationships: Optional[List[KnowledgeGraphRelationship]] = None,
        clear_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Add knowledge graph data with source
        
        Args:
            source: Data source label (required)
            nodes: List of knowledge graph nodes
            relationships: List of knowledge graph relationships (optional)
            clear_existing: Whether to clear existing data before adding
            
        Returns:
            API response result
            
        Example:
            >>> nodes = [
            ...     KnowledgeGraphNode(
            ...         id="node_001",
            ...         labels=["Person", "Employee"],
            ...         properties={"name": "张三", "age": 30}
            ...     )
            ... ]
            >>> relationships = [
            ...     KnowledgeGraphRelationship(
            ...         start="node_001",
            ...         end="node_002",
            ...         type="REPORTS_TO",
            ...         properties={"since": "2023-01-01"}
            ...     )
            ... ]
            >>> result = client.add_with_source("test_source_1", nodes, relationships)
        """
        if not source:
            raise ValueError("source parameter is required and cannot be empty")
        
        if relationships is None:
            relationships = []
        
        payload = {
            "source": source,
            "clear_existing": clear_existing,
            "nodes": [node.to_dict() for node in nodes],
            "relationships": [rel.to_dict() for rel in relationships]
        }
        
        endpoint = "/knowledge_graph/add_with_source"
        
        return self._make_request("POST", endpoint, payload)

    def search_with_source(
        self,
        source: str,
        node_id: Optional[str] = None,
        label: Optional[str] = None,
        property_name: Optional[str] = None,
        property_value: Optional[Any] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search knowledge graph data with source
        
        Supports multiple search modes:
        - By node_id: Search for a specific node by ID
        - By label: Search for nodes with a specific label
        - By property: Search for nodes by property name and value
        - All nodes: Get all nodes (when no specific search criteria provided)
        
        Args:
            source: Data source label (required)
            node_id: Node ID to search for (optional)
            label: Node label to search for (optional)
            property_name: Property name to search for (optional)
            property_value: Property value to search for (optional)
            limit: Maximum number of results to return
            
        Returns:
            API response result
            
        Example:
            >>> # Search by node ID
            >>> result = client.search_with_source("test_source_1", node_id="node_001")
            
            >>> # Search by label
            >>> result = client.search_with_source("test_source_1", label="Person")
            
            >>> # Search by property
            >>> result = client.search_with_source("test_source_1", property_name="name", property_value="张三")
            
            >>> # Get all nodes
            >>> result = client.search_with_source("test_source_1", limit=10)
        """
        if not source:
            raise ValueError("source parameter is required and cannot be empty")
        
        payload = {
            "source": source,
            "limit": limit
        }
        
        if node_id is not None:
            payload["node_id"] = node_id
        elif label is not None:
            payload["label"] = label
        elif property_name is not None and property_value is not None:
            payload["property_name"] = property_name
            payload["property_value"] = property_value
        
        endpoint = "/knowledge_graph/search_with_source"
        
        return self._make_request("POST", endpoint, payload)

    def search_by_node_id(
        self,
        source: str,
        node_id: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search for a specific node by ID (convenience method)
        
        Args:
            source: Data source label
            node_id: Node ID to search for
            limit: Maximum number of results to return
            
        Returns:
            API response result
        """
        return self.search_with_source(source=source, node_id=node_id, limit=limit)

    def search_by_label(
        self,
        source: str,
        label: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search for nodes by label (convenience method)
        
        Args:
            source: Data source label
            label: Node label to search for
            limit: Maximum number of results to return
            
        Returns:
            API response result
        """
        return self.search_with_source(source=source, label=label, limit=limit)

    def search_by_property(
        self,
        source: str,
        property_name: str,
        property_value: Any,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search for nodes by property (convenience method)
        
        Args:
            source: Data source label
            property_name: Property name to search for
            property_value: Property value to search for
            limit: Maximum number of results to return
            
        Returns:
            API response result
        """
        return self.search_with_source(
            source=source,
            property_name=property_name,
            property_value=property_value,
            limit=limit
        )

    def get_all_nodes(
        self,
        source: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get all nodes for a source (convenience method)
        
        Args:
            source: Data source label
            limit: Maximum number of results to return
            
        Returns:
            API response result
        """
        return self.search_with_source(source=source, limit=limit)

    def delete_with_source(
        self,
        source: str
    ) -> Dict[str, Any]:
        """
        Delete knowledge graph data by source
        
        Args:
            source: Data source label (required)
            
        Returns:
            API response result containing deletion statistics
            
        Example:
            >>> result = client.delete_with_source("test_source_1")
            >>> print(f"Deleted {result['data']['nodes_deleted']} nodes and {result['data']['relationships_deleted']} relationships")
        """
        if not source:
            raise ValueError("source parameter is required and cannot be empty")
        
        payload = {
            "source": source
        }
        
        endpoint = "/knowledge_graph/delete_with_source"
        
        return self._make_request("DELETE", endpoint, payload)


    def add_with_mem0(
        self,
        user_id: str,
        agent_id: str,
        run_id: str,
        messages: List[Dict[str, str]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add knowledge graph data with mem0
        
        Args:
            user_id: User ID (required)
            agent_id: Agent ID (required)
            run_id: Run ID (required)
            messages: List of messages, each with "role" and "content" keys (required)
            metadata: Optional metadata dictionary
            
        Returns:
            API response result
            
        Example:
            >>> messages = [
            ...     {"role": "user", "content": "I like to eat pizza and pasta"},
            ...     {"role": "assistant", "content": "Okay, your dietary preferences have been remembered"}
            ... ]
            >>> metadata = {
            ...     "conversation_id": "conv_456",
            ...     "timestamp": "2023-10-01T10:00:00Z"
            ... }
            >>> result = client.add_with_mem0(
            ...     user_id="test1234",
            ...     agent_id="test1234",
            ...     run_id="test1234",
            ...     messages=messages,
            ...     metadata=metadata
            ... )
            
        API:
            curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0" \
              -H "Content-Type: application/json" \
              -d '{
                "user_id": "test1234",
                "agent_id": "test1234",
                "run_id": "test1234",
                "messages": [
                  {
                    "role": "user",
                    "content": "I like to eat pizza and pasta"
                  },
                  {
                    "role": "assistant",
                    "content": "Okay, your dietary preferences have been remembered"
                  }
                ],
                "metadata": {
                  "conversation_id": "conv_456",
                  "timestamp": "2023-10-01T10:00:00Z"
                }
              }' | jq .


        # Output:

        {
          "status": "success",
          "message": "knowledge graph added successfully",
          "data": {
            "results": [
                {
                  "id": "276c397f-90c5-4ca2-8d39-eba0462915b9",
                  "memory": "Likes to eat pizza and pasta",
                  "hash": "1fa6211ecb07b77eede443e4b82829f0",
                  "metadata": {
                    "conversation_id": "conv_456"
                  },
                  "score": 0.2985008181035018,
                  "created_at": "2025-09-18T05:38:36.042830-07:00",
                  "updated_at": null,
                  "user_id": "user1",
                  "agent_id": "assistant_001",
                  "run_id": "run_123456"
                }
              ]
            "relations": {
              "deleted_entities": [],
              "added_entities": [
                [
                  {
                    "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
                    "relationship": "likes_to_eat",
                    "target": "pizza"
                  }
                ],
                [
                  {
                    "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
                    "relationship": "likes_to_eat",
                    "target": "pasta"
                  }
                ]
              ]
            }
          }
        }


        """
        if not user_id:
            raise ValueError("user_id parameter is required and cannot be empty")
        if not agent_id:
            raise ValueError("agent_id parameter is required and cannot be empty")
        if not run_id:
            raise ValueError("run_id parameter is required and cannot be empty")
        if not messages:
            raise ValueError("messages parameter is required and cannot be empty")
        
        # Validate messages format
        for msg in messages:
            if not isinstance(msg, dict):
                raise ValueError("Each message must be a dictionary")
            if "role" not in msg or "content" not in msg:
                raise ValueError("Each message must have 'role' and 'content' keys")
        
        payload = {
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "messages": messages
        }
        
        if metadata is not None:
            payload["metadata"] = metadata
        
        endpoint = "/knowledge_graph_mem0"
        
        return self._make_request("POST", endpoint, payload)

    def search_with_mem0(
        self,
        query: str,
        user_id: str,
        agent_id: str,
        run_id: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Search knowledge graph data with mem0
        
        Args:
            query: Search query string (required)
            user_id: User ID (required)
            agent_id: Agent ID (required)
            run_id: Run ID (required)
            limit: Maximum number of results to return (default: 10)
            
        Returns:
            API response result
            
        Example:
            >>> result = client.search_with_mem0(
            ...     query="pizza",
            ...     user_id="test1234",
            ...     agent_id="test1234",
            ...     run_id="test1234",
            ...     limit=10
            ... )
            
        API:
            curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0/search" \
              -H "Content-Type: application/json" \
              -d '{
                "query": "pizza",
                "user_id": "test1234",
                "agent_id": "test1234",
                "run_id": "test1234",
                "limit": 10
              }' | jq .


        # output：

        {
          "status": "success",
          "data": {
            "query": "pizza",
            "results": {
              "results": [],
              "relations": [
                {
                  "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
                  "relationship": "likes_to_eat",
                  "destination": "pizza"
                }
              ]
            },
            "count": 2
          }
        }


        """
        if not query:
            raise ValueError("query parameter is required and cannot be empty")
        if not user_id:
            raise ValueError("user_id parameter is required and cannot be empty")
        if not agent_id:
            raise ValueError("agent_id parameter is required and cannot be empty")
        if not run_id:
            raise ValueError("run_id parameter is required and cannot be empty")
        
        payload = {
            "query": query,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "limit": limit
        }
        
        endpoint = "/knowledge_graph_mem0/search"
        
        return self._make_request("POST", endpoint, payload)

    def delete_with_mem0(
        self,
        user_id: str,
        agent_id: str,
        run_id: str
    ) -> Dict[str, Any]:
        """
        Delete knowledge graph data with mem0
        
        Args:
            user_id: User ID (required)
            agent_id: Agent ID (required)
            run_id: Run ID (required)
            
        Returns:
            API response result
            
        Example:
            >>> result = client.delete_with_mem0(
            ...     user_id="test1234",
            ...     agent_id="test1234",
            ...     run_id="test1234"
            ... )
            
        API:
            curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0/delete" \
              -H "Content-Type: application/json" \
              -d '{
                "user_id": "test1234",
                "agent_id": "test1234",
                "run_id": "test1234"
              }' | jq .

          # output
          {
          "status": "success",
          "message": "knowledge graphs deleted successfully",
          "data": {
            "message": "Memories deleted successfully!"
          }
        }

        """
        if not user_id:
            raise ValueError("user_id parameter is required and cannot be empty")
        if not agent_id:
            raise ValueError("agent_id parameter is required and cannot be empty")
        if not run_id:
            raise ValueError("run_id parameter is required and cannot be empty")
        
        payload = {
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id
        }
        
        endpoint = "/knowledge_graph_mem0/delete"
        
        return self._make_request("POST", endpoint, payload)


    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            # Try to search with a non-existent source to check if service is reachable
            self.get_all_nodes("__health_check__", limit=1)
            return True
        except Exception:
            return False

def convert_to_knowledge_graph(data: Dict[str, Any]) -> Tuple[List[KnowledgeGraphNode], List[KnowledgeGraphRelationship]]:
    """
    将 JSON 格式的知识图谱数据转换为 KnowledgeGraphNode 和 KnowledgeGraphRelationship 对象列表
    
    支持节点顶层的字段（如name），这些字段会被提取并存储到节点的顶层
    
    Args:
        data: 包含 nodes 和 relationships 的字典
        
    Returns:
        Tuple[List[KnowledgeGraphNode], List[KnowledgeGraphRelationship]]: 转换后的节点和关系列表
    """
    nodes = []
    relationships = []
    
    # 定义节点的标准字段（这些字段不应该作为extra_fields）
    standard_fields = {'id', 'labels', 'properties', 'name'}
    
    # 转换节点
    for node_data in data.get("nodes", []):
        # 提取标准字段
        node_id = node_data.get("id", "")
        labels = node_data.get("labels", [])
        properties = node_data.get("properties", {})
        name = node_data.get("name")
        
        # 提取其他顶层字段（除了标准字段）
        extra_fields = {
            k: v for k, v in node_data.items() 
            if k not in standard_fields and v is not None
        }
        
        node = KnowledgeGraphNode(
            id=node_id,
            labels=labels,
            properties=properties,
            name=name,
            extra_fields=extra_fields if extra_fields else None
        )
        nodes.append(node)
    
    # 转换关系
    for rel_data in data.get("relationships", []):
        relationship = KnowledgeGraphRelationship(
            start=rel_data.get("start", ""),
            end=rel_data.get("end", ""),
            type=rel_data.get("type", ""),
            properties=rel_data.get("properties", {})
        )
        relationships.append(relationship)
    
    return nodes, relationships


def convert_from_knowledge_graph(nodes: List[KnowledgeGraphNode], 
                                relationships: List[KnowledgeGraphRelationship]) -> Dict[str, Any]:
    """
    将 KnowledgeGraphNode 和 KnowledgeGraphRelationship 对象转换回原始 JSON 格式
    
    Args:
        nodes: KnowledgeGraphNode 对象列表
        relationships: KnowledgeGraphRelationship 对象列表
        
    Returns:
        Dict[str, Any]: 原始 JSON 格式的数据
    """
    return {
        "nodes": [node.to_dict() for node in nodes],
        "relationships": [rel.to_dict() for rel in relationships]
    }


# Usage example
if __name__ == "__main__":
    # Create client instance
    client = KnowledgeGraphClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        # 0. Test: Add Knowledge Graph Data with top-level name field
        print("=" * 50)
        print("0. Test: Add Knowledge Graph Data with top-level name field")
        print("=" * 50)
        
        # 测试节点顶层的name字段
        test_nodes_with_name = [
            KnowledgeGraphNode(
                id="test_node_001",
                name="张三",  # 顶层name字段
                labels=["Person", "Employee"],
                properties={
                    "age": 30,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="test_node_002",
                name="李四",  # 顶层name字段
                labels=["Person", "Manager"],
                properties={
                    "age": 35,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="test_node_003",
                name="技术部",  # 顶层name字段
                labels=["Department"],
                properties={
                    "location": "北京"
                }
            )
        ]
        
        test_relationships = [
            KnowledgeGraphRelationship(
                start="test_node_001",
                end="test_node_002",
                type="REPORTS_TO",
                properties={"since": "2023-01-01"}
            ),
            KnowledgeGraphRelationship(
                start="test_node_001",
                end="test_node_003",
                type="BELONGS_TO",
                properties={}
            ),
            KnowledgeGraphRelationship(
                start="test_node_002",
                end="test_node_003",
                type="MANAGES",
                properties={}
            )
        ]
        
        print("Adding nodes with top-level name field...")
        test_add_result = client.add_with_source(
            source="test_source_name_field",
            nodes=test_nodes_with_name,
            relationships=test_relationships,
            clear_existing=True
        )
        print(f"Add result: {json.dumps(test_add_result, indent=2, ensure_ascii=False)}")
        
        # 验证节点是否成功添加，并检查name字段
        print("\nVerifying nodes were added with name field...")
        verify_result = client.search_by_node_id(
            source="test_source_name_field",
            node_id="test_node_001",
            limit=1
        )
        print(f"Verification result: {json.dumps(verify_result, indent=2, ensure_ascii=False)}")
        
        # 测试 convert_to_knowledge_graph 函数处理顶层name字段
        print("\n" + "=" * 50)
        print("0.1. Test: convert_to_knowledge_graph with top-level name field")
        print("=" * 50)
        
        test_json_data = {
            "nodes": [
                {
                    "id": "convert_test_001",
                    "name": "测试节点1",  # 顶层name字段
                    "labels": ["Test"],
                    "properties": {
                        "value": "test1"
                    }
                },
                {
                    "id": "convert_test_002",
                    "name": "测试节点2",  # 顶层name字段
                    "labels": ["Test"],
                    "properties": {
                        "value": "test2"
                    }
                }
            ],
            "relationships": []
        }
        
        converted_nodes, converted_rels = convert_to_knowledge_graph(test_json_data)
        print(f"Converted {len(converted_nodes)} nodes")
        for node in converted_nodes:
            node_dict = node.to_dict()
            print(f"Node {node.id}: {json.dumps(node_dict, indent=2, ensure_ascii=False)}")
            assert "name" in node_dict, f"Node {node.id} should have 'name' field in to_dict()"
            assert node_dict["name"] == test_json_data["nodes"][int(node.id.split("_")[-1]) - 1]["name"]
        print("✓ convert_to_knowledge_graph correctly handles top-level name field")
        
        # 1. Add Knowledge Graph Data with Source
        print("\n" + "=" * 50)
        print("1. Add Knowledge Graph Data with Source")
        print("=" * 50)
        
        nodes = [
            KnowledgeGraphNode(
                id="node_001",
                labels=["Person", "Employee"],
                properties={
                    "name": "张三",
                    "age": 30,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="node_002",
                labels=["Person", "Manager"],
                properties={
                    "name": "李四",
                    "age": 35,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="node_003",
                labels=["Department"],
                properties={
                    "name": "技术部",
                    "location": "北京"
                }
            )
        ]
        
        relationships = [
            KnowledgeGraphRelationship(
                start="node_001",
                end="node_002",
                type="REPORTS_TO",
                properties={
                    "since": "2023-01-01"
                }
            ),
            KnowledgeGraphRelationship(
                start="node_001",
                end="node_003",
                type="BELONGS_TO",
                properties={}
            ),
            KnowledgeGraphRelationship(
                start="node_002",
                end="node_003",
                type="MANAGES",
                properties={}
            )
        ]
        
        add_result = client.add_with_source(
            source="test_source_1",
            nodes=nodes,
            relationships=relationships,
            clear_existing=False
        )
        print(f"Add result: {json.dumps(add_result, indent=2, ensure_ascii=False)}")
        
        # 2. Search Knowledge Graph Data - By Node ID
        print("\n" + "=" * 50)
        print("2. Search Knowledge Graph Data - By Node ID")
        print("=" * 50)
        
        search_by_id_result = client.search_by_node_id(
            source="test_source_1",
            node_id="node_001",
            limit=10
        )
        print(f"Search by node ID result: {json.dumps(search_by_id_result, indent=2, ensure_ascii=False)}")
        
        # 3. Search Knowledge Graph Data - By Label
        print("\n" + "=" * 50)
        print("3. Search Knowledge Graph Data - By Label")
        print("=" * 50)
        
        search_by_label_result = client.search_by_label(
            source="test_source_1",
            label="Person",
            limit=10
        )
        print(f"Search by label result: {json.dumps(search_by_label_result, indent=2, ensure_ascii=False)}")
        
        # 4. Search Knowledge Graph Data - By Property
        print("\n" + "=" * 50)
        print("4. Search Knowledge Graph Data - By Property")
        print("=" * 50)
        
        search_by_property_result = client.search_by_property(
            source="test_source_1",
            property_name="name",
            property_value="张三",
            limit=10
        )
        print(f"Search by property result: {json.dumps(search_by_property_result, indent=2, ensure_ascii=False)}")
        
        # 5. Search Knowledge Graph Data - All Nodes
        print("\n" + "=" * 50)
        print("5. Search Knowledge Graph Data - All Nodes")
        print("=" * 50)
        
        all_nodes_result = client.get_all_nodes(
            source="test_source_1",
            limit=10
        )
        print(f"Get all nodes result: {json.dumps(all_nodes_result, indent=2, ensure_ascii=False)}")
        
        # 6. Delete Knowledge Graph Data by Source
        print("\n" + "=" * 50)
        print("6. Delete Knowledge Graph Data by Source")
        print("=" * 50)
        
        delete_result = client.delete_with_source(source="test_source_1")
        print(f"Delete result: {json.dumps(delete_result, indent=2, ensure_ascii=False)}")
        
        print("\n" + "=" * 50)
        print("All tests completed!")
        print("=" * 50)
        
    except Exception as e:
        print(f"Operation failed: {e}")
        import traceback
        traceback.print_exc()
