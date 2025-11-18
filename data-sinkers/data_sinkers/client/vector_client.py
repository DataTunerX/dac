import aiohttp
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
        self.timeout = aiohttp.ClientTimeout(total=timeout)
    
    async def _make_request(
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
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
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

    async def create_collection(
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
        
        return await self._make_request("POST", endpoint, payload)
    
    async def delete_collection(
        self,
        collection_name: str
    ) -> Dict[str, Any]:
        """
        Delete collection
        Args:
            collection_name: Name of the collection to delete
        """
        endpoint = f"/vector/{collection_name}/delete_all"
        
        return await self._make_request("DELETE", endpoint)
    
    async def add_documents(
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
        
        return await self._make_request("POST", endpoint, payload)

# Usage example
async def main():
    """Usage example"""
    # Create client instance
    client = VectorClient(timeout=300)
    
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
        result = await client.create_collection("test123")
        print("Collection created successfully", result)

        # Add documents to vector
        result = await client.add_documents(
            collection_name="test123",
            documents=documents
        )
        print("Documents added successfully:", result)

        # Delete collection
        result = await client.delete_collection("test123")
        print("Collection deleted successfully", result)
        
    except Exception as e:
        print("Failed to add documents:", str(e))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
