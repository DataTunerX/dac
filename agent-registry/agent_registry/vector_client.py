import json
import requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio
import aiohttp
from aiohttp import ClientTimeout
from dataclasses import asdict, is_dataclass

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


def serialize_object(obj: Any) -> Any:
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [serialize_object(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_object(value) for key, value in obj.items()}
    elif is_dataclass(obj):
        return serialize_object(asdict(obj))
    elif hasattr(obj, '__dict__'):
        obj_dict = {}
        for key, value in obj.__dict__.items():
            if not key.startswith('_'):
                obj_dict[key] = serialize_object(value)
        return obj_dict
    elif hasattr(obj, '_asdict'):
        return serialize_object(obj._asdict())
    else:
        return str(obj)



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

    async def acreate_collection(
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
        
        return await self._amake_request("POST", endpoint, payload)
    
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

    async def adelete_collection(
        self,
        collection_name: str
    ) -> Dict[str, Any]:
        """
        Delete collection
        Args:
            collection_name: Name of the collection to delete
        """
        endpoint = f"/vector/{collection_name}/delete_all"
        
        return await self._amake_request("DELETE", endpoint)
    
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
            >>> result = client.add_documents("test_knowledge", documents)
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

    async def aadd_documents(
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
        
        return await self._amake_request("POST", endpoint, payload)

    def search(
        self,
        collection_name: str,
        query: str,
        search_type: SearchType = SearchType.VECTOR,
        limit: int = 10,
        hybrid_threshold: float = 0.1,
        fulltext_weight: Optional[float] = 0.5,
        vector_weight: Optional[float] = 0.5
    ) -> SearchResult:
        """
        Search documents with vector, fulltext or hybrid search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            search_type: Type of search (vector, fulltext, hybrid)
            limit: Maximum number of results to return
            hybrid_threshold: Threshold for hybrid search
            fulltext_weight: Weight for fulltext search in hybrid mode
            vector_weight: Weight for vector search in hybrid mode
            
        Returns:
            SearchResult object containing documents and scores
            
        Example:
            >>> result = client.search(
            ...     collection_name="test_knowledge",
            ...     query="machine learning",
            ...     search_type=SearchType.HYBRID,
            ...     limit=5
            ... )
            >>> for item in result.result:
            ...     print(item.content)
        """
        payload = {
            "query": query,
            "search_type": search_type.value,
            "limit": limit,
            "hybrid_threshold": hybrid_threshold
        }
        
        # Only add weight parameters for hybrid search
        if search_type == SearchType.HYBRID:
            if fulltext_weight is not None:
                payload["fulltext_weight"] = fulltext_weight
            if vector_weight is not None:
                payload["vector_weight"] = vector_weight
        
        endpoint = f"/vector/{collection_name}/search"
        
        response = self._make_request("POST", endpoint, payload)
        
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

    async def asearch(
        self,
        collection_name: str,
        query: str,
        search_type: SearchType = SearchType.VECTOR,
        limit: int = 10,
        hybrid_threshold: float = 0.1,
        fulltext_weight: Optional[float] = 0.5,
        vector_weight: Optional[float] = 0.5
    ) -> SearchResult:
        """
        Search documents with vector, fulltext or hybrid search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            search_type: Type of search (vector, fulltext, hybrid)
            limit: Maximum number of results to return
            hybrid_threshold: Threshold for hybrid search
            fulltext_weight: Weight for fulltext search in hybrid mode
            vector_weight: Weight for vector search in hybrid mode
            
        Returns:
            SearchResult object containing documents and scores
            
        Example:
            >>> result = await client.search(
            ...     collection_name="test_knowledge",
            ...     query="machine learning",
            ...     search_type=SearchType.HYBRID,
            ...     limit=5
            ... )
            >>> for item in result.result:
            ...     print(item.content)
        """
        payload = {
            "query": query,
            "search_type": search_type.value,
            "limit": limit,
            "hybrid_threshold": hybrid_threshold
        }
        
        # Only add weight parameters for hybrid search
        if search_type == SearchType.HYBRID:
            if fulltext_weight is not None:
                payload["fulltext_weight"] = fulltext_weight
            if vector_weight is not None:
                payload["vector_weight"] = vector_weight
        
        endpoint = f"/vector/{collection_name}/search"
        
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

    def vector_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        Convenience method for vector-only search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            SearchResult object containing documents and scores
        """
        return self.search(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.VECTOR,
            limit=limit
        )

    async def avector_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        Convenience method for vector-only search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            SearchResult object containing documents and scores
        """
        return await self.asearch(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.VECTOR,
            limit=limit
        )

    def fulltext_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        Convenience method for fulltext-only search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            SearchResult object containing documents and scores
        """
        return self.search(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.FULLTEXT,
            limit=limit
        )

    async def afulltext_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        Convenience method for fulltext-only search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            SearchResult object containing documents and scores
        """
        return await self.asearch(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.FULLTEXT,
            limit=limit
        )

    def hybrid_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10,
        hybrid_threshold: float = 0.1,
        fulltext_weight: float = 0.5,
        vector_weight: float = 0.5
    ) -> SearchResult:
        """
        Convenience method for hybrid search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            hybrid_threshold: Threshold for hybrid search
            fulltext_weight: Weight for fulltext search
            vector_weight: Weight for vector search
            
        Returns:
            SearchResult object containing documents and scores
        """
        return self.search(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.HYBRID,
            limit=limit,
            hybrid_threshold=hybrid_threshold,
            fulltext_weight=fulltext_weight,
            vector_weight=vector_weight
        )

    async def ahybrid_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 10,
        hybrid_threshold: float = 0.1,
        fulltext_weight: float = 0.5,
        vector_weight: float = 0.5
    ) -> SearchResult:
        """
        Convenience method for hybrid search
        
        Args:
            collection_name: Collection name to search in
            query: Search query string
            limit: Maximum number of results to return
            hybrid_threshold: Threshold for hybrid search
            fulltext_weight: Weight for fulltext search
            vector_weight: Weight for vector search
            
        Returns:
            SearchResult object containing documents and scores
        """
        return await self.asearch(
            collection_name=collection_name,
            query=query,
            search_type=SearchType.HYBRID,
            limit=limit,
            hybrid_threshold=hybrid_threshold,
            fulltext_weight=fulltext_weight,
            vector_weight=vector_weight
        )

    def delete_by_metadata_field(
        self,
        collection_name: str,
        key: str,
        value: str
    ) -> Dict[str, Any]:
        """
        Delete documents by metadata field
        """
        payload = {
            "key": key,
            "value": value
        }

        endpoint = f"/vector/{collection_name}/delete_by_metadata_field"
        
        return self._make_request("DELETE", endpoint, payload)

    async def adelete_by_metadata_field(
        self,
        collection_name: str,
        key: str,
        value: str
    ) -> Dict[str, Any]:
        """
        
        """
        payload = {
            "key": key,
            "value": value
        }

        endpoint = f"/vector/{collection_name}/delete_by_metadata_field"
        
        return await self._amake_request("DELETE", endpoint, payload)


# Usage example
def main():
    """Usage example"""
    # Create client instance
    client = VectorClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
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
        ),
        Document(
            page_content="Python is widely used in data science and machine learning projects",
            metadata={
                "category": "Programming",
                "source": "Tutorial",
                "created_at": "2024-01-17"
            }
        ),
        Document(
            page_content="Natural language processing enables computers to understand human language",
            metadata={
                "category": "NLP",
                "source": "Academic paper",
                "created_at": "2024-01-18"
            }
        )
    ]
    
    collection_name = "test_search_collection"
    
    try:
        # Create collection
        print("=== Creating Collection ===")
        result = client.create_collection(collection_name)
        print("Collection created successfully")
        print(f"Response: {result}\n")

        # Add documents to vector
        print("=== Adding Documents ===")
        result = client.add_documents(
            collection_name=collection_name,
            documents=documents
        )
        print("Documents added successfully")
        print(f"Response: {result}\n")

        # Wait a moment for documents to be processed
        import time
        time.sleep(2)

        # Test vector search
        print("=== Testing Vector Search ===")
        vector_result = client.vector_search(
            collection_name=collection_name,
            query="machine learning artificial intelligence",
            limit=3
        )
        print(f"Vector search status: {vector_result.status}")
        print(f"Collection: {vector_result.collection}")
        print(f"Search type: {vector_result.search_type}")
        print(f"Found {len(vector_result.result)} results:")
        for i, item in enumerate(vector_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}")
            if item.hybrid_score:
                print(f"   Hybrid score: {item.hybrid_score:.4f}")
            print()

        # Test fulltext search
        print("=== Testing Fulltext Search ===")
        fulltext_result = client.fulltext_search(
            collection_name=collection_name,
            query="Python programming",
            limit=2
        )
        print(f"Fulltext search status: {fulltext_result.status}")
        print(f"Found {len(fulltext_result.result)} results:")
        for i, item in enumerate(fulltext_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}\n")

        # Test hybrid search
        print("=== Testing Hybrid Search ===")
        hybrid_result = client.hybrid_search(
            collection_name=collection_name,
            query="deep learning image recognition",
            limit=4,
            fulltext_weight=0.4,
            vector_weight=0.6
        )
        print(f"Hybrid search status: {hybrid_result.status}")
        print(f"Found {len(hybrid_result.result)} results:")
        for i, item in enumerate(hybrid_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}")
            if item.hybrid_score:
                print(f"   Hybrid score: {item.hybrid_score:.4f}")
            print()

        # Delete collection
        print("=== Cleaning Up ===")
        result = client.delete_collection(collection_name)
        print("Collection deleted successfully")
        print(f"Response: {result}\n")
        
    except Exception as e:
        print(f"Operation failed: {str(e)}")
        # Clean up on failure
        try:
            client.delete_collection(collection_name)
            print("Cleaned up collection after error")
        except:
            pass

def simple_test():
    """Simple test function for quick verification"""
    client = VectorClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
    collection_name = "quick_test1"
    test_documents = [
        Document(
            page_content="Agent Name: SatelliteAgent  Description: I am a satellite agent and can answer some satellite-related questions. URL: http://192.168.xxx.xxx:20004",
            metadata={"type": "agent_card", "skills": [], "agent_url": "http://192.168.xxx.xxx:20004", "timestamp": "2025-11-11T12:24:36.565643", "agent_name": "SatelliteAgent", "description": "I am a satellite agent and can answer some satellite-related questions."}
        )
    ]
    
    try:
        # Create and populate collection
        # client.create_collection(collection_name)
        # client.add_documents(collection_name, test_documents)
        
        # Quick search test
        result = client.vector_search(collection_name, "I am a satellite agent.", limit=10)
        print(f"Quick test - Status: {result.status}")
        print(f"Collection: {result.collection}")
        print(f"Search type: {result.search_type}")
        print(f"Results count: {len(result.result)}")
        for i, item in enumerate(result.result):
            print(f"Result {i+1}:")
            print(f"  Content: {item.content}")
            print(f"  Score: {item.score}")
            print(f"  Search type: {item.search_type}")
            print(f"  Metadata: {item.metadata}")
            
        # Clean up
        # client.delete_collection(collection_name)

        client.delete_by_metadata_field(collection_name, key="agent_url", value="http://192.168.xxx.xxx:20004")

        result = client.vector_search(collection_name, "I am a satellite agent.", limit=10)
        print(f"Quick test - Status: {result.status}")
        print(f"Collection: {result.collection}")
        print(f"Search type: {result.search_type}")
        print(f"Results count: {len(result.result)}")
        for i, item in enumerate(result.result):
            print(f"Result {i+1}:")
            print(f"  Content: {item.content}")
            print(f"  Score: {item.score}")
            print(f"  Search type: {item.search_type}")
            print(f"  Metadata: {item.metadata}")

        
    except Exception as e:
        print(f"Simple test failed: {e}")


# Usage example
async def amain():
    """Usage example"""
    # Create client instance
    client = VectorClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
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
        ),
        Document(
            page_content="Python is widely used in data science and machine learning projects",
            metadata={
                "category": "Programming",
                "source": "Tutorial",
                "created_at": "2024-01-17"
            }
        ),
        Document(
            page_content="Natural language processing enables computers to understand human language",
            metadata={
                "category": "NLP",
                "source": "Academic paper",
                "created_at": "2024-01-18"
            }
        )
    ]
    
    collection_name = "test_search_collection"
    
    try:
        # Create collection
        print("=== Creating Collection ===")
        result = await client.acreate_collection(collection_name)
        print("Collection created successfully")
        print(f"Response: {result}\n")

        # Add documents to vector
        print("=== Adding Documents ===")
        result = await client.aadd_documents(
            collection_name=collection_name,
            documents=documents
        )
        print("Documents added successfully")
        print(f"Response: {result}\n")

        # Wait a moment for documents to be processed
        await asyncio.sleep(2)

        # Test vector search
        print("=== Testing Vector Search ===")
        vector_result = await client.avector_search(
            collection_name=collection_name,
            query="machine learning artificial intelligence",
            limit=3
        )
        print(f"Vector search status: {vector_result.status}")
        print(f"Collection: {vector_result.collection}")
        print(f"Search type: {vector_result.search_type}")
        print(f"Found {len(vector_result.result)} results:")
        for i, item in enumerate(vector_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}")
            if item.hybrid_score:
                print(f"   Hybrid score: {item.hybrid_score:.4f}")
            print()

        # Test fulltext search
        print("=== Testing Fulltext Search ===")
        fulltext_result = await client.afulltext_search(
            collection_name=collection_name,
            query="Python programming",
            limit=2
        )
        print(f"Fulltext search status: {fulltext_result.status}")
        print(f"Found {len(fulltext_result.result)} results:")
        for i, item in enumerate(fulltext_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}\n")

        # Test hybrid search
        print("=== Testing Hybrid Search ===")
        hybrid_result = await client.ahybrid_search(
            collection_name=collection_name,
            query="deep learning image recognition",
            limit=4,
            fulltext_weight=0.4,
            vector_weight=0.6
        )
        print(f"Hybrid search status: {hybrid_result.status}")
        print(f"Found {len(hybrid_result.result)} results:")
        for i, item in enumerate(hybrid_result.result):
            print(f"{i+1}. Score: {item.score:.4f}")
            print(f"   Content: {item.content[:100]}...")
            print(f"   Metadata: {item.metadata}")
            print(f"   Search type: {item.search_type}")
            if item.hybrid_score:
                print(f"   Hybrid score: {item.hybrid_score:.4f}")
            print()

        # Delete collection
        print("=== Cleaning Up ===")
        result = await client.adelete_collection(collection_name)
        print("Collection deleted successfully")
        print(f"Response: {result}\n")
        
    except Exception as e:
        print(f"Operation failed: {str(e)}")
        # Clean up on failure
        try:
            await client.adelete_collection(collection_name)
            print("Cleaned up collection after error")
        except:
            pass

async def asimple_test():
    """Simple test function for quick verification"""
    client = VectorClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
    collection_name = "quick_test"
    test_documents = [
        Document(
            page_content="The quick brown fox jumps over the lazy dog",
            metadata={"type": "example", "id": 1}
        ),
        Document(
            page_content="Machine learning models require large amounts of data",
            metadata={"type": "ai", "id": 2}
        )
    ]
    
    try:
        # Create and populate collection
        # await client.acreate_collection(collection_name)
        # await client.aadd_documents(collection_name, test_documents)
        
        # Quick search test
        result = await client.avector_search(collection_name, "The quick brown fox jumps over the lazy dog", limit=10)
        print(f"Quick test - Status: {result.status}")
        print(f"Collection: {result.collection}")
        print(f"Search type: {result.search_type}")
        print(f"Results count: {len(result.result)}")
        for i, item in enumerate(result.result):
            print(f"Result {i+1}:")
            print(f"  Content: {item.content}")
            print(f"  Score: {item.score}")
            print(f"  Search type: {item.search_type}")
            print(f"  Metadata: {item.metadata}")
            
        # Clean up
        # await client.delete_collection(collection_name)
        
    except Exception as e:
        print(f"Simple test failed: {e}")


if __name__ == "__main__":
    # Run the comprehensive test
    # print("Running comprehensive search tests...")
    # main()
    
    # Uncomment below to run a quick test instead
    print("Running quick test...")
    simple_test()



    # print("Running quick test...")
    # asyncio.run(amain())


    # print("Running quick test...")
    # asyncio.run(asimple_test())


