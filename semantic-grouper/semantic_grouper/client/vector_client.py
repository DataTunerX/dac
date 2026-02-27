import aiohttp
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field, validator, ConfigDict
from enum import Enum
import requests

@dataclass
class Document:
    """Document data class"""
    page_content: str
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Post-initialization processing"""
        if self.metadata is None:
            self.metadata = {}

class SearchType(str, Enum):
    """搜索类型枚举"""
    VECTOR = "vector"
    HYBRID = "hybrid"
    KEYWORD = "keyword"
    FULLTEXT = "fulltext"

class Metadata(BaseModel):
    """元数据模型"""
    model_config = ConfigDict(extra='allow')  # 允许额外字段（如 group_id, group_name 等）
    
    source: Optional[str] = Field(None, description="数据来源")
    category: Optional[str] = Field(None, description="分类")
    created_at: Optional[str] = Field(None, description="创建时间")
    score: Optional[float] = Field(None, description="元数据评分")

class SearchResultItem(BaseModel):
    """搜索结果项"""
    content: str = Field(..., description="内容文本")
    metadata: Metadata = Field(default_factory=Metadata, description="元数据")
    score: float = Field(..., description="相似度得分", ge=0.0, le=1.0)
    search_type: SearchType = Field(SearchType.VECTOR, description="搜索类型")
    hybrid_score: float = Field(0.0, description="混合搜索得分")

class SearchResult(BaseModel):
    """搜索结果模型"""
    status: str = Field(..., description="状态: success, error")
    collection: str = Field(..., description="集合名称")
    search_type: SearchType = Field(..., description="搜索类型")
    result: List[SearchResultItem] = Field(default_factory=list, description="搜索结果列表")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        """从字典创建实例"""
        return cls(**data)
    
    def to_json(self, **kwargs) -> str:
        """转换为JSON字符串"""
        return self.json(**kwargs)
    
    @classmethod
    def from_json(cls, json_str: str) -> "SearchResult":
        """从JSON字符串创建实例"""
        import json as json_lib
        data = json_lib.loads(json_str)
        return cls.from_dict(data)

class VectorClient:
    """Vector API Client"""
    
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
        self.session = requests.Session()


    def initialize(self):
        self.create_collection("semantic_groups")
    
    def _make_request(
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
        
        # 从环境变量读取 DATA_DESCRIPTOR 并添加到 header
        data_descriptor = os.getenv("DATA_DESCRIPTOR")
        if data_descriptor:
            headers["Data-Descriptor"] = data_descriptor
        
        try:
            # Only set json parameter when there is payload
            request_kwargs = {
                "method": method,
                "url": url,
                "headers": headers,
                "timeout": self.timeout
            }
            
            if payload is not None:
                request_kwargs["json"] = payload
            
            response = self.session.request(**request_kwargs)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP request failed: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Response JSON parsing failed: {e}")

    def create_collection(
        self,
        collection_name: str
    ) -> Dict[str, Any]:
        """
        Create a new collection
        Args:
            collection_name: Collection name
        Returns:
            API response result
        """
    
        documents_data = [
            {
                "page_content": "Python is a popular programming language",
                "metadata": {"author": "Guido van Rossum", "year": 1991}
            }
        ]
        
        payload = {
            "collection_name": collection_name,
            "documents": documents_data
        }
        
        endpoint = "/vector/create_collection"
        
        return self._make_request("POST", endpoint, payload)
    
    def delete_collection(
        self,
        collection_name: str
    ) -> Dict[str, Any]:
        """
        Delete collection
        Args:
            collection_name: Name of the collection to delete
        """
        endpoint = f"/vector/{collection_name}/delete_all"
        
        return self._make_request("DELETE", endpoint)
    
    def delete_by_metadata_field(
        self,
        collection_name: str,
        key: str,
        value: str
    ) -> Dict[str, Any]:
        """
        Delete documents by metadata field
        
        Delete documents from vector database that match the specified metadata field key-value pair.
        
        Args:
            collection_name: Collection name
            key: Metadata field key
            value: Metadata field value
            
        Returns:
            API response result containing status, message, and collection name
            
        Example:
            >>> result = client.delete_by_metadata_field(
            ...     collection_name="test_vector123",
            ...     key="source",
            ...     value="ResearchPaper"
            ... )
            >>> # Returns: {"status": "success", "message": "Documents deleted successfully", "collection": "test_vector123"}
        """
        payload = {
            "key": key,
            "value": value
        }
        
        endpoint = f"/vector/{collection_name}/delete_by_metadata_field"
        
        return self._make_request("DELETE", endpoint, payload)
    
    def add_documents(
        self,
        collection_name: str,
        documents: List[Document],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add documents to vector database
        
        Add documents to vector database to build knowledge base
        
        Args:
            collection_name: Collection name
            documents: List of documents
            **kwargs: Additional request parameters
            
        Returns:
            API response result
            
        Example:
            >>> documents = [
            ...     Document(
            ...         page_content="Machine learning is one of the core technologies of artificial intelligence",
            ...         metadata={"category": "AI", "source": "Technical documentation"}
            ...     )
            ... ]
            >>> result = await client.add_documents("test_knowledge", documents)
        """
        # Convert document format
        documents_data = [
            {
                "page_content": doc.page_content,
                "metadata": doc.metadata or {}
            }
            for doc in documents
        ]
        
        payload = {
            "documents": documents_data
        }
        
        # Merge additional parameters
        payload.update(kwargs)
        
        endpoint = f"/vector/{collection_name}/add_documents"
        
        return self._make_request("POST", endpoint, payload)
    
    def search(
        self,
        collection_name: str,
        query: str,
        search_type: str = "vector",
        limit: int = 5,
        hybrid_threshold: float = 0.1,
        **extra_params
    ) -> SearchResult:
        """
        Search in vector database
        
        Args:
            collection_name: Collection name
            query: Search query text
            search_type: Search type (hybrid, vector, keyword)
            limit: Maximum number of results
            hybrid_threshold: Hybrid search threshold
            **extra_params: Additional search parameters
            
        Returns:
            SearchResult object
        """
        payload = {
            "query": query,
            "search_type": search_type,
            "limit": limit,
            "hybrid_threshold": hybrid_threshold,
            "vector_weight": 0.5,
            "fulltext_weight": 0.5
        }
        payload.update(extra_params)
        
        endpoint = f"/vector/{collection_name}/search"
        
        response = self._make_request("POST", endpoint, payload)

        return SearchResult.from_dict(response)

# Usage example
def main():
    """Usage example"""
    # Create client instance
    client = VectorClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    # Prepare documents
    documents = [
        Document(
            page_content="Machine learning is one of the core technologies of artificial intelligence",
            metadata={
                "category": "AI",
                "source": "Technical documentation",
                "created_at": "2024-01-15"
            }
        ),
        Document(
            page_content="Deep learning has made breakthrough progress in the field of image recognition",
            metadata={
                "category": "Deep Learning",
                "source": "Research paper",
                "created_at": "2024-01-16"
            }
        )
    ]
    
    try:
        # Create collection
        result = client.create_collection("test123")
        print("Collection created successfully", result)

        # Add documents to vector
        result = client.add_documents(
            collection_name="test123",
            documents=documents
        )
        print("Documents added successfully:", result)

        # search documents to vector
        result = client.search(
            collection_name="test123",
            query="Machine learning",
            search_type="vector",
            limit=10
        )
        print("Documents search successfully:", result)

        # Delete documents by metadata field
        result = client.delete_by_metadata_field(
            collection_name="test123",
            key="source",
            value="Research paper"
        )
        print("Documents deleted by metadata field successfully:", result)

        # Search again to verify deletion
        result = client.search(
            collection_name="test123",
            query="Machine learning",
            search_type="vector",
            limit=10
        )
        print("Documents search after deletion:", result)

        # Delete collection
        result = client.delete_collection("test123")
        print("Collection deleted successfully", result)
        
    except Exception as e:
        print("Failed to add documents:", str(e))

if __name__ == "__main__":
    main()
