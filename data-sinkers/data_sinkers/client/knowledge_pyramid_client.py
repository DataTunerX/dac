import requests
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Document:
    """Document data class"""
    page_content: str
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Post-initialization processing"""
        if self.metadata is None:
            self.metadata = {}

class KnowledgePyramidClient:
    """Knowledge Pyramid API Client"""
    
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
        
        endpoint = "/knowledge_pyramid/create_collection"
        
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
        endpoint = f"/knowledge_pyramid/{collection_name}/delete_all"
        
        return self._make_request("DELETE", endpoint)
    
    def add_documents(
        self,
        collection_name: str,
        documents: List[Document],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add documents to knowledge pyramid
        
        Add documents to both vector database and memory system to build knowledge pyramid
        
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
        
        endpoint = f"/knowledge_pyramid/{collection_name}/add_documents"
        
        return self._make_request("POST", endpoint, payload)

    def memories_get_all(
        self,
        collection_name: str
    ) -> Dict[str, Any]:
        """
        Get all memories from knowledge pyramid
        Args:
            collection_name: Collection name
        Returns:
            API response result
        """

        endpoint = f"/knowledge_pyramid/{collection_name}/memories_get_all"
        
        return self._make_request("POST", endpoint)

# Usage example
def main():
    """Usage example"""
    # Create client instance
    client = KnowledgePyramidClient(base_url="http://192.168.xxx.xxx:22000", timeout=300)
    
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
        # result = client.create_collection("test123")
        # print("Collection created successfully", result)

        # result = client.delete_collection("test123")
        # print("Collection deleted successfully", result)

        # Add documents to knowledge pyramid
        # result = client.add_documents(
        #     collection_name="test_knowledge",
        #     documents=documents
        # )
        # print("Documents added successfully:", result)

        result = client.memories_get_all("dac_dd_a01")
        print("memories get all successfully", result)
        
    except Exception as e:
        print("Failed to add documents:", str(e))

if __name__ == "__main__":
    main()