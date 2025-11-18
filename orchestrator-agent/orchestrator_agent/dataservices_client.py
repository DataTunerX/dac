import aiohttp
import json
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator, Union
from dataclasses import dataclass
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# vector api
@dataclass
class SearchRequest:
    """Search request parameters"""
    collection_name: str
    query: str
    search_type: str = "hybrid"
    limit: int = 5
    hybrid_threshold: float = 0.1
    memory_threshold: float = 0.1
    extra_params: Optional[Dict[str, Any]] = None

# vector api
@dataclass
class VectorResult:
    """Vector search result item"""
    content: str
    metadata: Dict[str, Any]
    score: float
    search_type: str
    hybrid_score: float

# vector api
@dataclass
class MemoryResult:
    """Memory search result item"""
    id: str
    memory: str
    hash: str
    metadata: Optional[Dict[str, Any]]
    score: float
    created_at: str
    updated_at: Optional[str]
    user_id: str

# vector api
@dataclass
class SearchResult:
    """Search result - strictly follows API response format"""
    status: str
    collection: str
    search_type: str
    vector_result: List[VectorResult]
    memory_result: List[MemoryResult]

    def extract_content_as_string(self) -> str:
        """
        Extract content from vector_result and memory from memory_result,
        concatenate into a string with line breaks
        
        Returns:
            str: Concatenated string
        """
        contents = []
        
        # Extract content from vector_result
        for vec_item in self.vector_result:
            contents.append(vec_item.content)
        
        # Extract memory from memory_result
        for mem_item in self.memory_result:
            if mem_item.memory:  # Ensure memory is not empty
                contents.append(mem_item.memory)
        
        # Concatenate all content with line breaks
        return "\n".join(contents)

# vector api
@dataclass
class MultiSearchResult:
    """Multi-collection search result"""
    results: Dict[str, SearchResult]  # collection_name -> SearchResult
    all_content: str
    
    def get_result(self, collection_name: str) -> Optional[SearchResult]:
        """Get search result for specific collection"""
        return self.results.get(collection_name)
    
    def get_all_vector_results(self) -> List[VectorResult]:
        """Get all vector results from all collections"""
        all_vector_results = []
        for result in self.results.values():
            all_vector_results.extend(result.vector_result)
        return all_vector_results
    
    def get_all_memory_results(self) -> List[MemoryResult]:
        """Get all memory results from all collections"""
        all_memory_results = []
        for result in self.results.values():
            all_memory_results.extend(result.memory_result)
        return all_memory_results


# memory add api
@dataclass
class MemoryRequest:
    """Memory storage request - corrected to complete format"""
    user_id: str
    agent_id: str
    run_id: str
    messages: List[Dict[str, str]]
    metadata: Optional[Dict[str, Any]] = None

# memory add api
@dataclass  
class MemoryResponse:
    """Memory storage response - corrected to match actual API response"""
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None

# memory add api
@dataclass
class MemoryDataItem:
    """Memory result item"""
    id: str
    memory: str
    event: str

# memory search api
@dataclass
class MemorySearchRequest:
    """Memory search request parameters"""
    query: str
    user_id: str
    agent_id: str
    run_id: str
    limit: int = 10
    extra_params: Optional[Dict[str, Any]] = None

# memory search api
@dataclass
class MemorySearchResultItem:
    """Memory search result item"""
    id: str
    memory: str
    hash: str
    metadata: Optional[Dict[str, Any]]
    score: float
    created_at: str
    updated_at: Optional[str]
    user_id: str
    agent_id: str
    run_id: str

# memory search api
@dataclass
class MemorySearchResponse:
    """Memory search response"""
    status: str
    data: Optional[Dict[str, Any]] = None
    detail: Optional[str] = None

# history api
@dataclass
class HistoryMessage:
    role: str
    content: str

@dataclass
class CreateHistoryRequest:
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]

    def get_messages_json(self) -> str:
        """Serialize messages field to JSON string"""
        return json.dumps([msg.model_dump() for msg in self.messages], ensure_ascii=False)

@dataclass
class CreateHistoryResponse:
    status: str
    hid: str
    message: str

@dataclass
class SearchHistoryRequest:
    user_id: str
    agent_id: str
    run_id: str
    limit: int = 10

@dataclass
class HistoryRecordResponse:
    hid: str
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]
    created_at: datetime
    updated_at: datetime

@dataclass
class SearchHistoryResponse:
    status: str
    data: List[HistoryRecordResponse]
    total: int
    message: str



class DataServicesClient:
    """DataServices API asynchronous client (supports dynamic collections)"""
    
    def __init__(self, base_url: str = "http://data-services.dac.svc.cluster.local:8000", timeout: int = 300):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
    
    @asynccontextmanager
    async def session_context(self) -> AsyncGenerator['DataServicesClient', None]:
        """Asynchronous context manager"""
        try:
            await self._create_session()
            yield self
        finally:
            await self.close()
    
    async def _create_session(self):
        """Create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Content-Type": "application/json"
                }
            )
    
    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    #################### Knowledge pyramid API endpoints
    def _parse_search_response(self, response_data: Dict[str, Any]) -> SearchResult:
        """Parse search response data - strictly follows API format"""
        try:
            # Parse vector_result
            vector_result = []
            for item in response_data.get('vector_result', []):
                vector_result.append(VectorResult(
                    content=item.get('content', ''),
                    metadata=item.get('metadata', {}),
                    score=item.get('score', 0.0),
                    search_type=item.get('search_type', ''),
                    hybrid_score=item.get('hybrid_score', 0.0)
                ))
            
            # Parse memory_result
            memory_result = []
            for item in response_data.get('memory_result', []):
                memory_result.append(MemoryResult(
                    id=item.get('id', ''),
                    memory=item.get('memory', ''),
                    hash=item.get('hash', ''),
                    metadata=item.get('metadata'),
                    score=item.get('score', 0.0),
                    created_at=item.get('created_at', ''),
                    updated_at=item.get('updated_at'),
                    user_id=item.get('user_id', '')
                ))
            
            return SearchResult(
                status=response_data.get('status', ''),
                collection=response_data.get('collection', ''),
                search_type=response_data.get('search_type', ''),
                vector_result=vector_result,
                memory_result=memory_result
            )
            
        except Exception as e:
            error_msg = f"Failed to parse response data: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    async def search(
        self,
        collection_name: str,
        query: str,
        search_type: str = "hybrid",
        limit: int = 5,
        hybrid_threshold: float = 0.1,
        memory_threshold: float = 0.1,
        **extra_params
    ) -> SearchResult:
        """
        Execute search
        
        Args:
            collection_name: Collection name (e.g., test_knowledge_pyramid)
            query: Search query
            search_type: Search type
            limit: Number of results to return
            hybrid_threshold: Hybrid search threshold
            memory_threshold: Memory threshold
            **extra_params: Additional parameters
        
        Returns:
            SearchResult: Search results
        """
        request_data = SearchRequest(
            collection_name=collection_name,
            query=query,
            search_type=search_type,
            limit=limit,
            hybrid_threshold=hybrid_threshold,
            memory_threshold=memory_threshold,
            extra_params=extra_params
        )
        return await self._search(request_data)
    
    async def search_multiple_collections(
        self,
        collection_names: Union[List[str], str],
        query: str,
        search_type: str = "hybrid",
        limit: int = 5,
        hybrid_threshold: float = 0.1,
        memory_threshold: float = 0.1,
        **extra_params
    ) -> MultiSearchResult:
        """
        Execute search in multiple collections
        
        Args:
            collection_names: Collection name list or comma-separated string
            query: Search query
            search_type: Search type
            limit: Number of results per collection
            hybrid_threshold: Hybrid search threshold
            memory_threshold: Memory threshold
            **extra_params: Additional parameters
        
        Returns:
            MultiSearchResult: Multi-collection search results
        """
        # Process input parameters
        if isinstance(collection_names, str):
            # If it's a comma-separated string, split into list
            collection_names = [name.strip() for name in collection_names.split(",") if name.strip()]
        
        if not collection_names:
            raise ValueError("collection_names cannot be empty")
        
        results = {}
        all_contents = []
        
        # Execute search for each collection
        for collection_name in collection_names:
            try:
                result = await self.search(
                    collection_name=collection_name,
                    query=query,
                    search_type=search_type,
                    limit=limit,
                    hybrid_threshold=hybrid_threshold,
                    memory_threshold=memory_threshold,
                    **extra_params
                )
                results[collection_name] = result
                all_contents.append(result.extract_content_as_string())
                
            except Exception as e:
                logger.error(f"Collection {collection_name} search failed: {str(e)}")
                # Can choose to continue processing other collections or raise exception
                # Here we log error but continue processing other collections
                results[collection_name] = None
        
        # Concatenate all content
        all_content = "\n".join(all_contents)
        
        return MultiSearchResult(
            results=results,
            all_content=all_content
        )
    
    async def _search(self, request: SearchRequest) -> SearchResult:
        """
        Execute search request
        
        Args:
            request: Search request parameters
        
        Returns:
            SearchResult: Search results
        """
        # Dynamically build URL, including collection name
        url = f"{self.base_url}/knowledge_pyramid/{request.collection_name}/search"
        
        # Build request data - strictly follows curl example format
        payload = {
            "query": request.query,
            "search_type": request.search_type,
            "limit": request.limit,
            "hybrid_threshold": request.hybrid_threshold,
            "memory_threshold": request.memory_threshold
        }
        
        # Add extra parameters
        if request.extra_params:
            payload.update(request.extra_params)
        
        logger.info(f"Request URL: {url}")
        logger.debug(f"Request parameters: {payload}")
        
        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        # Use specialized parsing method to handle response
                        return self._parse_search_response(data)
                    except json.JSONDecodeError:
                        logger.error(f"JSON parsing failed: {response_text}")
                        raise ValueError(f"JSON parsing failed: {response_text}")
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                    
        except aiohttp.ClientError as e:
            error_msg = f"Network request error: {str(e)}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
        except asyncio.TimeoutError:
            error_msg = f"Request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            raise TimeoutError(error_msg)

    #################### Memory API endpoints
    async def store_memory(
        self,
        user_id: str,
        agent_id: str,
        run_id: str,
        messages: List[Dict[str, str]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryResponse:
        """
        Store memory to memories endpoint - corrected to complete API format
        
        Args:
            user_id: User ID
            agent_id: Agent ID
            run_id: Run ID
            messages: Message list, each message contains role and content
            metadata: Metadata information
        
        Returns:
            MemoryResponse: Storage result
        """
        url = f"{self.base_url}/memories"
        
        # Build request data - strictly follows curl example format
        payload = {
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "messages": messages,
            "metadata": metadata or {}
        }
        
        logger.info(f"Store memory request URL: {url}")
        logger.debug(f"Store memory request parameters: {payload}")
    
        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        # Parse according to actual API response format
                        return MemoryResponse(
                            status=data.get('status', ''),
                            message=data.get('message', ''),
                            data=data.get('data', {})
                        )
                    except json.JSONDecodeError:
                        logger.error(f"JSON parsing failed: {response_text}")
                        return MemoryResponse(
                            status='error',
                            message=f'JSON parsing failed: {response_text}'
                        )
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    return MemoryResponse(
                        status='error',
                        message=error_msg
                    )
                    
        except aiohttp.ClientError as e:
            error_msg = f"Network request error: {str(e)}"
            logger.error(error_msg)
            return MemoryResponse(
                status='error',
                message=error_msg
            )
        except asyncio.TimeoutError:
            error_msg = f"Request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            return MemoryResponse(
                status='error',
                message=error_msg
            )


    def parse_save_memory_results(self, response: MemoryResponse) -> List[MemoryDataItem]:
        """
        Parse result data from memory storage response
        
        Args:
            response: MemoryResponse object
        
        Returns:
            List[MemoryDataItem]: List of memory results
        """
        results = []
        if response.data and 'results' in response.data:
            for item in response.data['results']:
                results.append(MemoryDataItem(
                    id=item.get('id', ''),
                    memory=item.get('memory', ''),
                    event=item.get('event', '')
                ))
        return results


    async def search_memories(
        self,
        query: str,
        user_id: str,
        agent_id: str,
        run_id: str,
        limit: int = 10,
        **extra_params
    ) -> MemorySearchResponse:
        """
        Search memories
        """
        url = f"{self.base_url}/memories/search"
        
        payload = {
            "query": query,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "limit": limit
        }

        if extra_params:
            payload.update(extra_params)
        
        logger.debug(f"Memory search request parameters: {payload}")

        # Use context manager to ensure proper session management
        async with self.session_context() as client:
            try:
                async with client.session.post(url, json=payload) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        try:
                            data = await response.json()
                            return MemorySearchResponse(
                                status=data.get('status', ''),
                                data=data.get('data', {}),
                                detail=data.get('detail')
                            )
                        except json.JSONDecodeError:
                            logger.error(f"JSON parsing failed: {response_text}")
                            return MemorySearchResponse(
                                status='error',
                                data={'error': f'JSON parsing failed: {response_text}'},
                                detail=f'JSON parsing failed: {response_text}'
                            )
                    else:
                        try:
                            error_data = await response.json()
                            detail = error_data.get('detail', response_text)
                        except:
                            detail = response_text
                            error_data = {'error': response_text}
                        
                        error_msg = f"HTTP error: {response.status}, response: {detail}"
                        logger.error(error_msg)
                        return MemorySearchResponse(
                            status='error',
                            data=error_data,
                            detail=detail
                        )
                        
            except aiohttp.ClientError as e:
                error_msg = f"Network request error: {str(e)}"
                logger.error(error_msg)
                return MemorySearchResponse(
                    status='error',
                    data={'error': error_msg},
                    detail=error_msg
                )
            except asyncio.TimeoutError:
                error_msg = f"Request timeout: {self.timeout} seconds"
                logger.error(error_msg)
                return MemorySearchResponse(
                    status='error',
                    data={'error': error_msg},
                    detail=error_msg
                )

    def parse_memory_search_results(self, response: MemorySearchResponse) -> List[MemorySearchResultItem]:
        """
        Parse memory search results
        
        Args:
            response: MemorySearchResponse object
        
        Returns:
            List[MemorySearchResultItem]: List of memory search results
        """
        results = []
        if response.data and 'results' in response.data:
            # Note: The results field in API response contains a nested results array
            results_data = response.data['results']
            if 'results' in results_data:
                for item in results_data['results']:
                    results.append(MemorySearchResultItem(
                        id=item.get('id', ''),
                        memory=item.get('memory', ''),
                        hash=item.get('hash', ''),
                        metadata=item.get('metadata'),
                        score=item.get('score', 0.0),
                        created_at=item.get('created_at', ''),
                        updated_at=item.get('updated_at'),
                        user_id=item.get('user_id', ''),
                        agent_id=item.get('agent_id', ''),
                        run_id=item.get('run_id', '')
                    ))
        return results


    #################### History API endpoints
    async def create_history(self, request: CreateHistoryRequest) -> CreateHistoryResponse:
        """
        Create history record - asynchronous version
        
        Args:
            request: Create history record request parameters
                
        Returns:
            CreateHistoryResponse: Creation result
                
        Raises:
            aiohttp.ClientError: Network request exception
            ValueError: Response data parsing exception
        """
        url = f"{self.base_url}/history/create"
        
        # Prepare request data - use messages field instead of conversation
        payload = {
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "run_id": request.run_id,
            "messages": [{"role": msg.role, "content": msg.content} for msg in request.messages]
        }
        
        logger.info(f"Create history record request URL: {url}")
        logger.debug(f"Create history record request parameters: {payload}")

        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        
                        return CreateHistoryResponse(
                            status=response_data.get('status', ''),
                            hid=response_data.get('hid'),
                            message=response_data.get('message', '')
                        )
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON parsing failed: {response_text}")
                        raise ValueError(f"Response data parsing failed: {str(e)}")
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    raise aiohttp.ClientError(error_msg)
                    
        except aiohttp.ClientError as e:
            error_msg = f"Create history record request failed: {str(e)}"
            logger.error(error_msg)
            raise aiohttp.ClientError(error_msg)
        except asyncio.TimeoutError:
            error_msg = f"Request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            raise TimeoutError(error_msg)

    async def search_history(self, request: SearchHistoryRequest) -> SearchHistoryResponse:
        """
        Search history records - asynchronous version
        
        Args:
            request: Search history records request parameters
                
        Returns:
            SearchHistoryResponse: Search results
                
        Raises:
            aiohttp.ClientError: Network request exception
            ValueError: Response data parsing exception
        """
        url = f"{self.base_url}/history/search"
        
        # Prepare request data
        payload = {
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "run_id": request.run_id
        }
        
        # Add optional parameters
        if request.limit is not None:
            payload["limit"] = request.limit
        
        logger.debug(f"Search history records request URL: {url}")
        logger.debug(f"Search history records request parameters: {payload}")

        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        
                        # Parse history record data
                        history_records = []
                        for record_data in response_data.get('data', []):
                            # Handle time string conversion
                            try:
                                created_at = datetime.fromisoformat(record_data['created_at'].replace('Z', '+00:00'))
                                updated_at = datetime.fromisoformat(record_data['updated_at'].replace('Z', '+00:00'))
                            except (KeyError, ValueError) as e:
                                logger.warning(f"Time format parsing failed: {str(e)}, using current time")
                                created_at = updated_at = datetime.now()
                            
                            # Parse messages field
                            messages = []
                            for msg_data in record_data.get('messages', []):
                                messages.append(HistoryMessage(
                                    role=msg_data.get('role', ''),
                                    content=msg_data.get('content', '')
                                ))

                            history_record = HistoryRecordResponse(
                                hid=record_data.get('hid', ''),
                                user_id=record_data.get('user_id', ''),
                                agent_id=record_data.get('agent_id', ''),
                                run_id=record_data.get('run_id', ''),
                                messages=messages,  # Use messages field instead of conversation
                                created_at=created_at,
                                updated_at=updated_at
                            )
                            history_records.append(history_record)
                        
                        return SearchHistoryResponse(
                            status=response_data.get('status', ''),
                            data=history_records,
                            total=response_data.get('total', 0),
                            message=response_data.get('message', '')
                        )
                        
                    except (KeyError, ValueError) as e:
                        logger.error(f"Response data parsing failed: {str(e)}")
                        raise ValueError(f"Response data parsing failed: {str(e)}")
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    raise aiohttp.ClientError(error_msg)
                    
        except aiohttp.ClientError as e:
            error_msg = f"Search history records request failed: {str(e)}"
            logger.error(error_msg)
            raise aiohttp.ClientError(error_msg)
        except asyncio.TimeoutError:
            error_msg = f"Request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            raise TimeoutError(error_msg)


async def example_usage():
    """Usage example"""
    try:
        data_service_client = DataServicesClient(base_url= "http://192.168.xxx.xxx:22000", timeout= 300)
        try:
            # Example 1: Knowledge pyramid, multiple collection search - using list
            # multi_result = await data_service_client.search_multiple_collections(
            #     # collection_names=["test_knowledge_pyramid", "another_collection", "third_collection"],
            #     collection_names=["test_knowledge_pyramid"],
            #     query="java",
            #     search_type="hybrid",
            #     limit=10
            # )
            
            # print(f"\nMulti-collection search completed! Searched {len(multi_result.results)} collections")
            
            # # Process results for each collection
            # for collection_name, result in multi_result.results.items():
            #     if result:
            #         print(f"\nCollection '{collection_name}' results:")
            #         print(f"  Status: {result.status}")
            #         print(f"  Vector results: {len(result.vector_result)} items")
            #         print(f"  Memory results: {len(result.memory_result)} items")
            #     else:
            #         print(f"\nCollection '{collection_name}' search failed")
            
            # # Get concatenated string of all content
            # print(f"\nTotal content length from all collections: {len(multi_result.all_content)} characters")
            # print("First 200 character preview:")
            # print(multi_result.all_content[:200] + "..." if len(multi_result.all_content) > 200 else multi_result.all_content)

            # # Example 2: Store memory
            # print("=== Memory Storage Example ===")
            # memory_response = await data_service_client.store_memory(
            #     user_id="user1",
            #     agent_id="assistant_001",
            #     run_id="run_123456",
            #     messages=[
            #         {
            #             "role": "user",
            #             "content": "I like playing soccer"
            #         },
            #         {
            #             "role": "assistant", 
            #             "content": "Okay, I've remembered your dietary preference"
            #         }
            #     ],
            #     metadata={
            #         "conversation_id": "conv_456"
            #     }
            # )
            
            # print(f"Memory storage: {memory_response}")
            # print(f"Memory storage status: {memory_response.status}")
            # print(f"Memory storage message: {memory_response.message}")
            
            # if memory_response.status == "success":
            #     # Parse memory results
            #     memory_items = data_service_client.parse_save_memory_results(memory_response)
            #     for item in memory_items:
            #         print(f"Memory ID: {item.id}")
            #         print(f"Memory content: {item.memory}")
            #         print(f"Operation type: {item.event}")
            # else:
            #     print("Memory storage failed")
            
            # print("\n" + "="*50 + "\n")

            # # Example 3: Memory search
            # print("=== Memory Search Example ===")
            # memory_search_response = await data_service_client.search_memories(
            #     query="pasta",
            #     user_id="user1",
            #     agent_id="assistant_001",
            #     run_id="run_123456",
            #     limit=10
            # )
            

            # print(f"Memory search status: {memory_search_response}")
            # if memory_search_response.status == "success":
            #     # Parse search results
            #     search_items = data_service_client.parse_memory_search_results(memory_search_response)
            #     print(f"=== search_items = {search_items} ===") 
            #     for i, item in enumerate(search_items, 1):
            #         print(f"\n{i}. Memory content: {item.memory}")
            #         print(f"   Memory ID: {item.id}")
            #         print(f"   Similarity score: {item.score:.4f}")
            #         print(f"   Creation time: {item.created_at}")
            #         if item.metadata:
            #             print(f"   Metadata: {item.metadata}")
            # else:
            #     print("Memory search failed")
            #     if memory_search_response.data and 'error' in memory_search_response.data:
            #         print(f"Error message: {memory_search_response.data['error']}")
            
            # print("\n" + "="*50 + "\n")

            # # Example 4: Add history record

            # Example 4: Add history record
            print("=== Create History Conversation Example ===")
            
            # Prepare request data - use messages field
            create_request = CreateHistoryRequest(
                user_id="user_001",
                agent_id="agent_001",
                run_id="run_001",
                messages=[
                    HistoryMessage(role="user", content="Who are you?"),
                    HistoryMessage(role="assistant", content="I am Qwen, happy to serve you!")
                ]
            )
            
            try:
                # Call API
                response = await data_service_client.create_history(create_request)
                
                # Output results
                print("Create history conversation result:")
                print(f"Status: {response.status}")
                print(f"History conversation ID: {response.hid}")
                print(f"Message: {response.message}")
            except Exception as e:
                print(f"Create history conversation failed: {str(e)}")

            # Example 5: History conversation search
            print("\n=== Search History Conversation Example ===")
            
            # Prepare request data
            search_request = SearchHistoryRequest(
                user_id="user_001",
                agent_id="agent_001",
                run_id="run_001",
                limit=10
            )
            
            try:
                # Call API
                response = await data_service_client.search_history(search_request)
                
                # Output results
                print("\nSearch history conversation results:")
                print(f"Status: {response.status}")
                print(f"Total: {response.total}")
                print(f"Message: {response.message}")
                print(f"Found {len(response.data)} records:")
                
                for i, record in enumerate(response.data, 1):
                    print(f"\nRecord {i}:")
                    print(f"  History conversation ID: {record.hid}")
                    print(f"  User ID: {record.user_id}")
                    print(f"  Agent ID: {record.agent_id}")
                    print(f"  Run ID: {record.run_id}")
                    print(f"  Message count: {len(record.messages)}")
                    
                    # Print each message
                    for j, msg in enumerate(record.messages, 1):
                        print(f"    Message {j}: [{msg.role}] {msg.content}")
                    
                    print(f"  Creation time: {record.created_at}")
                    print(f"  Update time: {record.updated_at}")
            except Exception as e:
                print(f"Retrieve history conversation failed: {str(e)}")

        finally:
            await data_service_client.close()
            
    except Exception as e:
        print(f"Search failed: {str(e)}")

if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())

