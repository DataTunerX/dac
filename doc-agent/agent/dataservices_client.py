import aiohttp
import json
import logging
import os
from typing import Callable, Dict, Any, Optional, List, AsyncGenerator, Union, Tuple
from dataclasses import dataclass
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# vector api
@dataclass
class SearchRequest:
    collection_name: str
    query: str
    search_type: str = "hybrid"
    limit: int = 5
    hybrid_threshold: float = 0.1
    extra_params: Optional[Dict[str, Any]] = None

# vector api
@dataclass
class VectorResult:
    content: str
    metadata: Dict[str, Any]
    score: float
    search_type: str
    hybrid_score: float

# vector api
@dataclass
class MemoryResult:
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
    status: str
    collection: str
    search_type: str
    vector_result: List[VectorResult]
    memory_result: List[MemoryResult]

    def extract_content_as_string(self) -> str:
        """
        Extract the content from vector_result and memory from memory_result,
        concatenate them into a single string using line breaks
        
        Returns:
            str: The concatenated string
        """
        contents = []
        
        for vec_item in self.vector_result:
            contents.append(vec_item.content)
        
        for mem_item in self.memory_result:
            if mem_item.memory:
                contents.append(mem_item.memory)

        return "\n".join(contents)

# vector api
@dataclass
class MultiSearchResult:
    results: Dict[str, SearchResult]  # collection_name -> SearchResult
    all_content: str
    
    def get_result(self, collection_name: str) -> Optional[SearchResult]:
        return self.results.get(collection_name)
    
    def get_all_vector_results(self) -> List[VectorResult]:
        all_vector_results = []
        for result in self.results.values():
            all_vector_results.extend(result.vector_result)
        return all_vector_results
    
    def get_all_memory_results(self) -> List[MemoryResult]:
        all_memory_results = []
        for result in self.results.values():
            all_memory_results.extend(result.memory_result)
        return all_memory_results


# memory add api
@dataclass
class MemoryRequest:
    user_id: str
    agent_id: str
    run_id: str
    messages: List[Dict[str, str]]
    metadata: Optional[Dict[str, Any]] = None

# memory add api
@dataclass  
class MemoryResponse:
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None

# memory add api
@dataclass
class MemoryDataItem:
    id: str
    memory: str
    event: str

# memory search api
@dataclass
class MemorySearchRequest:
    query: str
    user_id: str
    agent_id: str
    run_id: str
    limit: int = 10
    extra_params: Optional[Dict[str, Any]] = None

# memory search api
@dataclass
class MemorySearchResultItem:
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
    status: str
    data: Optional[Dict[str, Any]] = None


# semantic group with members api
@dataclass
class SemanticDomainInfo:
    """Semantic domain details from data services."""
    semantic_domain_id: Optional[str] = None
    semantic_domain: Optional[str] = None
    agent_card: Optional[str] = None
    dd_namespace: Optional[str] = None
    dd_name: Optional[str] = None
    descriptor_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class DDGroupRelationInfo:
    """Group-SD relation."""
    id: Optional[int] = None
    sd_id: str = ""
    group_id: str = ""
    association_reason: Optional[str] = None


@dataclass
class SemanticGroupMemberDetail:
    """One member: relation + semantic domain."""
    relation: DDGroupRelationInfo
    semantic_domain: Optional[SemanticDomainInfo] = None


@dataclass
class SemanticGroupWithMembersResult:
    """Semantic group with its member semantic domains."""
    group: Dict[str, Any]  # semantic group dict (id, group_name, description, ...)
    members: List[SemanticGroupMemberDetail]


# find_metadata_values_in_collections api
@dataclass
class MetadataValuesResult:
    """Result of find_metadata_values_in_collections API."""
    status: str
    data: Dict[str, List[Any]]  # collection_name -> list of metadata values
    errors: Optional[Dict[str, str]] = None  # collection_name -> error message

    def extract_metadata_as_batches(self, max_chars_per_batch: int = 60000,
                                      text_key: str = "metadata_value",
                                      id_key: str = "id") -> list:
        """
        将所有知识摘要按字符数上限分批，切分点对齐到完整记录边界。

        Args:
            max_chars_per_batch: 每个批次的最大字符数（默认 60000，约 15K tokens）
            text_key: 摘要文本字段名
            id_key: ID 字段名

        Returns:
            list[str]: 分批后的摘要字符串列表，每个批次包含若干条完整记录。
        """
        items = []
        for collection_name, values in self.data.items():
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    item_id = item.get(id_key, "")
                    text = item.get(text_key, "")
                    if text:
                        entry = f"[Knowledge ID: {item_id}]\n{text}" if item_id else text
                        items.append(entry)
                elif isinstance(item, str):
                    items.append(item)

        if not items:
            return []

        separator = "\n\n=========\n\n"
        sep_len = len(separator)

        batches = []
        current_batch = []
        current_len = 0

        for entry in items:
            entry_len = len(entry)
            additional = entry_len + (sep_len if current_batch else 0)

            if current_batch and current_len + additional > max_chars_per_batch:
                batches.append(separator.join(current_batch))
                current_batch = [entry]
                current_len = entry_len
            else:
                current_batch.append(entry)
                current_len += additional

        if current_batch:
            batches.append(separator.join(current_batch))

        return batches

    def get_blocks_by_ids(
        self,
        knowledge_ids: List[str],
        text_key: str = "text",
        id_key: str = "id",
        metadata_key: str = "metadata_value",
    ) -> List[Dict[str, Any]]:
        """
        根据知识块 ID 列表获取完整知识块（保持块完整性，按 knowledge_ids 顺序返回）。

        Returns:
            List[Dict]: 每项含 id / text / metadata_value
        """
        id_to_block: Dict[str, Dict[str, Any]] = {}

        for _collection_name, values in self.data.items():
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                item_id = item.get(id_key, "")
                text = item.get(text_key, "")
                if not item_id or not text:
                    continue
                id_to_block[item_id] = {
                    "id": item_id,
                    "text": text,
                    "metadata_value": item.get(metadata_key, "") or "",
                }

        blocks: List[Dict[str, Any]] = []
        for knowledge_id in knowledge_ids:
            block = id_to_block.get(knowledge_id)
            if block:
                blocks.append(block)
        return blocks

    async def get_text_by_ids(
        self,
        knowledge_ids: List[str],
        *,
        query: str = "",
        llm: Any = None,
        parse_output: Optional[Callable[[Any], Dict[str, Any]]] = None,
        text_key: str = "text",
        id_key: str = "id",
        trace: Any = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        根据知识块 ID 获取完整内容并拼接。

        当总字符数超过 ``DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS`` 时，对完整知识块进行
        LLM 批量打分，再按分数与长度预算选取最优块（保持块完整性，不截断块内文本）。
        """
        from .tools.knowledge_context_budget import (
            join_knowledge_blocks,
            log_final_knowledge_selection,
            log_selection_report,
            score_trigger_chars,
            select_blocks_by_score,
            should_score_and_select,
            total_block_chars,
        )
        from .tools.knowledge_llm_score import score_knowledge_blocks_batch_parallel

        meta: Dict[str, Any] = {
            "score_select_applied": False,
            "score_select_report": {},
            "total_chars_before_select": 0,
            "score_trigger_chars": score_trigger_chars(),
        }

        blocks = self.get_blocks_by_ids(
            knowledge_ids,
            text_key=text_key,
            id_key=id_key,
        )
        if not blocks:
            return "", meta

        total_chars = total_block_chars(blocks)
        trigger_chars = score_trigger_chars()
        meta["total_chars_before_select"] = total_chars

        if llm and query and should_score_and_select(blocks):
            meta["score_select_applied"] = True
            logger.info(
                "[DOC KNOWLEDGE GATE] total_chars=%d > trigger=%d → LLM score + select",
                total_chars,
                trigger_chars,
            )
            blocks = await score_knowledge_blocks_batch_parallel(
                blocks,
                query=query,
                llm=llm,
                parse_output=parse_output,
                trace=trace,
            )
            # 保存打分后的全量数据用于最终选块日志（select_blocks_by_score 会缩减）
            scored_all = list(blocks)
            blocks, select_report = select_blocks_by_score(blocks)
            meta["score_select_report"] = select_report
            log_selection_report(logger, report=select_report)
            log_final_knowledge_selection(logger, blocks, total_input=len(scored_all))
        else:
            log_selection_report(
                logger,
                report={},
                skipped=True,
                total_chars=total_chars,
                trigger_chars=trigger_chars,
            )

        return join_knowledge_blocks(blocks), meta

    def get_all_items(self) -> List[Dict[str, Any]]:
        """
        获取所有知识块数据项。

        Returns:
            List[Dict]: 所有知识块的列表
        """
        all_items = []
        for collection_name, values in self.data.items():
            if isinstance(values, list):
                all_items.extend(values)
        return all_items


def get_data_descriptor():
    """Build Data-Descriptor header from env DD_NAMESPACE and Data_Descriptor. Only used when DataSourceType is SemanticDomain."""
    dd_namespace = os.getenv('DD_NAMESPACE')
    data_descriptors_str = os.getenv('Data_Descriptor')
    if not data_descriptors_str or not dd_namespace:
        return ""
    data_descriptors = data_descriptors_str.split(",")
    if not data_descriptors:
        return ""
    data_descriptor = data_descriptors[0].strip()
    data_descriptor_all = f"{dd_namespace}_{data_descriptor}"
    return data_descriptor_all.replace("-", "_")


class DataServicesClient:
    def __init__(
        self,
        base_url: str = "http://data-services.dac.svc.cluster.local:8000",
        timeout: int = 30,
        use_data_descriptor_header: bool = False,
    ):
        """
        Args:
            base_url: Data-services API base URL.
            timeout: Request timeout in seconds.
            use_data_descriptor_header: If True (SemanticDomain), set Data-Descriptor header from env; if False (SemanticGroup), do not set it.
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.use_data_descriptor_header = use_data_descriptor_header
        self.session: Optional[aiohttp.ClientSession] = None

    @asynccontextmanager
    async def session_context(self) -> AsyncGenerator['DataServicesClient', None]:
        try:
            await self._create_session()
            yield self
        finally:
            await self.close()

    async def _create_session(self):
        """Create aiohttp session. Data-Descriptor header only set when use_data_descriptor_header is True (SemanticDomain)."""
        if self.session is None or self.session.closed:
            headers = {"Content-Type": "application/json"}
            if self.use_data_descriptor_header:
                data_descriptor = get_data_descriptor()
                if data_descriptor:
                    headers["Data-Descriptor"] = data_descriptor
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers=headers,
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    def _parse_search_response(self, response_data: Dict[str, Any]) -> SearchResult:
        try:
            vector_result = []
            for item in response_data.get('vector_result', []):
                vector_result.append(VectorResult(
                    content=item.get('content', ''),
                    metadata=item.get('metadata', {}),
                    score=item.get('score', 0.0),
                    search_type=item.get('search_type', ''),
                    hybrid_score=item.get('hybrid_score', 0.0)
                ))

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
        **extra_params
    ) -> SearchResult:
        """
        Execute search

        Args:
            collection_name: Collection name (e.g.: test_knowledge_pyramid)
            query: Search query term
            search_type: Search type
            limit: Number of results to return
            hybrid_threshold: Hybrid search threshold
            **extra_params: Additional parameters
        
        Returns:
            SearchResult: Search result
        """
        request_data = SearchRequest(
            collection_name=collection_name,
            query=query,
            search_type=search_type,
            limit=limit,
            hybrid_threshold=hybrid_threshold,
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
        **extra_params
    ) -> MultiSearchResult:
        """
        Execute search across multiple collections

        Args:
            collection_names: List of collection names or comma-separated string
            query: Search query term
            search_type: Search type
            limit: Number of results to return per collection
            hybrid_threshold: Hybrid search threshold
            **extra_params: Additional parameters
        
        Returns:
            MultiSearchResult: Multi-collection search result
        """

        if isinstance(collection_names, str):
            collection_names = [name.strip() for name in collection_names.split(",") if name.strip()]
        
        if not collection_names:
            raise ValueError("collection_names Cannot be empty")
        
        results = {}
        all_contents = []

        for collection_name in collection_names:
            try:
                result = await self.search(
                    collection_name=collection_name,
                    query=query,
                    search_type=search_type,
                    limit=limit,
                    hybrid_threshold=hybrid_threshold,
                    **extra_params
                )
                results[collection_name] = result
                all_contents.append(result.extract_content_as_string())
                
            except Exception as e:
                logger.error(f"Collection {collection_name} search fail: {str(e)}")
                results[collection_name] = None

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
            SearchResult: Search result
        """

        url = f"{self.base_url}/knowledge_pyramid/{request.collection_name}/search"

        payload = {
            "query": request.query,
            "search_type": request.search_type,
            "limit": request.limit,
            "hybrid_threshold": request.hybrid_threshold
        }

        if request.extra_params:
            payload.update(request.extra_params)
        
        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        return self._parse_search_response(data)
                    except json.JSONDecodeError:
                        logger.error(f"JSON parse fail: {response_text}")
                        raise ValueError(f"JSON parse fail: {response_text}")
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                    
        except aiohttp.ClientError as e:
            error_msg = f"network request error: {str(e)}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
        except asyncio.TimeoutError:
            error_msg = f"request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            raise TimeoutError(error_msg)


    async def find_metadata_values_in_collections(
        self,
        collection_names: List[str],
    ) -> MetadataValuesResult:
        """
        Find metadata values (e.g., summary) in multiple collections.

        Args:
            collection_names: List of collection names to query.

        Returns:
            MetadataValuesResult: Contains status, data (collection_name -> metadata values), and errors if any.
        """
        url = f"{self.base_url}/knowledge_pyramid/find_metadata_values_in_collections"
        payload = {"collection_names": collection_names}

        try:
            await self._create_session()
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()

                if response.status == 200:
                    try:
                        data = await response.json()
                        return MetadataValuesResult(
                            status=data.get("status", ""),
                            data=data.get("results", {}),
                            errors=data.get("errors")
                        )
                    except json.JSONDecodeError:
                        logger.error(f"JSON parse fail: {response_text}")
                        return MetadataValuesResult(
                            status="error",
                            data={},
                            errors={"parse_error": f"JSON parse fail: {response_text}"}
                        )
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    return MetadataValuesResult(
                        status="error",
                        data={},
                        errors={"http_error": error_msg}
                    )

        except aiohttp.ClientError as e:
            error_msg = f"network request error: {str(e)}"
            logger.error(error_msg)
            return MetadataValuesResult(
                status="error",
                data={},
                errors={"network_error": error_msg}
            )
        except asyncio.TimeoutError:
            error_msg = f"request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            return MetadataValuesResult(
                status="error",
                data={},
                errors={"timeout_error": error_msg}
            )

    async def store_memory(
        self,
        user_id: str,
        agent_id: str,
        run_id: str,
        messages: List[Dict[str, str]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> MemoryResponse:
        """
        Store memory to the memories endpoint - corrected to complete API format

        Args:
            user_id: User ID
            agent_id: Agent ID
            run_id: Run ID
            messages: List of messages, each containing role and content
            metadata: Metadata information
        
        Returns:
            MemoryResponse: Storage result
        """
        url = f"{self.base_url}/memories"

        payload = {
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "messages": messages,
            "metadata": metadata or {}
        }
    
        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        return MemoryResponse(
                            status=data.get('status', ''),
                            message=data.get('message', ''),
                            data=data.get('data', {})
                        )
                    except json.JSONDecodeError:
                        logger.error(f"JSON parse fail: {response_text}")
                        return MemoryResponse(
                            status='error',
                            message=f'JSON parse fail: {response_text}'
                        )
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    return MemoryResponse(
                        status='error',
                        message=error_msg
                    )
                    
        except aiohttp.ClientError as e:
            error_msg = f"network request error: {str(e)}"
            logger.error(error_msg)
            return MemoryResponse(
                status='error',
                message=error_msg
            )
        except asyncio.TimeoutError:
            error_msg = f"request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            return MemoryResponse(
                status='error',
                message=error_msg
            )

    def parse_memory_results(self, response: MemoryResponse) -> List[MemoryDataItem]:
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
        Search memory

        Args:
            query: Search query term
            user_id: User ID
            agent_id: Agent ID
            run_id: Run ID
            limit: Number of results to return
            **extra_params: Additional parameters
        
        Returns:
            MemorySearchResponse: Search response
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

        try:
            await self._create_session()
            
            async with self.session.post(url, json=payload) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        return MemorySearchResponse(
                            status=data.get('status', ''),
                            data=data.get('data', {})
                        )
                    except json.JSONDecodeError:
                        logger.error(f"JSON parse fail: {response_text}")
                        return MemorySearchResponse(
                            status='error',
                            data={'error': f'JSON parse fail: {response_text}'}
                        )
                else:
                    error_msg = f"HTTP error: {response.status}, response: {response_text}"
                    logger.error(error_msg)
                    return MemorySearchResponse(
                        status='error',
                        data={'error': error_msg}
                    )
                
        except aiohttp.ClientError as e:
            error_msg = f"network request error: {str(e)}"
            logger.error(error_msg)
            return MemorySearchResponse(
                status='error',
                data={'error': error_msg}
            )
        except asyncio.TimeoutError:
            error_msg = f"request timeout: {self.timeout} seconds"
            logger.error(error_msg)
            return MemorySearchResponse(
                status='error',
                data={'error': error_msg}
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

    async def get_semantic_group_with_members(self, group_id: str) -> Optional[SemanticGroupWithMembersResult]:
        """
        Get semantic group by id and detailed info of its member semantic domains.

        Args:
            group_id: Semantic group ID.

        Returns:
            SemanticGroupWithMembersResult with group and members (relation + semantic_domain),
            or None if not found or request failed.
        """
        url = f"{self.base_url}/semantic_groups/{group_id}/with_members"
        try:
            await self._create_session()
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"get_semantic_group_with_members HTTP {response.status}: {await response.text()}")
                    return None
                data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"get_semantic_group_with_members request error: {e}")
            return None
        if data.get("status") != "success" or not data.get("data"):
            return None
        payload = data["data"]
        group = payload.get("group") or {}
        members_raw = payload.get("members") or []
        members = []
        for m in members_raw:
            rel = m.get("relation") or {}
            relation = DDGroupRelationInfo(
                id=rel.get("id"),
                sd_id=rel.get("sd_id", ""),
                group_id=rel.get("group_id", ""),
                association_reason=rel.get("association_reason"),
            )
            sd_raw = m.get("semantic_domain")
            semantic_domain = None
            if sd_raw and isinstance(sd_raw, dict):
                semantic_domain = SemanticDomainInfo(
                    semantic_domain_id=sd_raw.get("semantic_domain_id"),
                    semantic_domain=sd_raw.get("semantic_domain"),
                    agent_card=sd_raw.get("agent_card"),
                    dd_namespace=sd_raw.get("dd_namespace"),
                    dd_name=sd_raw.get("dd_name"),
                    descriptor_type=sd_raw.get("descriptor_type"),
                    created_at=sd_raw.get("created_at"),
                    updated_at=sd_raw.get("updated_at"),
                )
            members.append(SemanticGroupMemberDetail(relation=relation, semantic_domain=semantic_domain))
        return SemanticGroupWithMembersResult(group=group, members=members)


async def example_usage():
    try:
        data_service_client = DataServicesClient()
        try:
            # 示例1: 多个集合搜索 - 使用列表
            multi_result = await data_service_client.search_multiple_collections(
                # collection_names=["test_knowledge_pyramid", "another_collection", "third_collection"],
                collection_names=["test_knowledge_pyramid"],
                query="java",
                search_type="hybrid",
                limit=10
            )
            
            print(f"\n多集合搜索完成! 共搜索 {len(multi_result.results)} 个集合")
            
            # 处理每个集合的结果
            for collection_name, result in multi_result.results.items():
                if result:
                    print(f"\n集合 '{collection_name}' 结果:")
                    print(f"  状态: {result.status}")
                    print(f"  向量结果: {len(result.vector_result)} 条")
                    print(f"  记忆结果: {len(result.memory_result)} 条")
                else:
                    print(f"\n集合 '{collection_name}' 搜索失败")
            
            # 获取所有内容的拼接字符串
            print(f"\n所有集合的内容总长度: {len(multi_result.all_content)} 字符")
            print("前200字符预览:")
            print(multi_result.all_content[:200] + "..." if len(multi_result.all_content) > 200 else multi_result.all_content)

            # # 示例2: 存储记忆
            # print("=== 记忆存储示例 ===")
            # memory_response = await data_service_client.store_memory(
            #     user_id="user1",
            #     agent_id="assistant_001",
            #     run_id="run_123456",
            #     messages=[
            #         {
            #             "role": "user",
            #             "content": "我喜欢吃披萨和意大利面"
            #         },
            #         {
            #             "role": "assistant", 
            #             "content": "好的，已记住您的饮食偏好"
            #         }
            #     ],
            #     metadata={
            #         "conversation_id": "conv_456"
            #     }
            # )
            
            # print(f"记忆存储状态: {memory_response.status}")
            # print(f"记忆存储消息: {memory_response.message}")
            
            # if memory_response.status == "success":
            #     # 解析记忆结果
            #     memory_items = data_service_client.parse_memory_results(memory_response)
            #     for item in memory_items:
            #         print(f"记忆ID: {item.id}")
            #         print(f"记忆内容: {item.memory}")
            #         print(f"操作类型: {item.event}")
            # else:
            #     print("记忆存储失败")
            
            # print("\n" + "="*50 + "\n")

            # # 示例3: 记忆搜索
            # print("=== 记忆搜索示例 ===")
            # memory_search_response = await data_service_client.search_memories(
            #     query="意大利面",
            #     user_id="user1",
            #     agent_id="assistant_001",
            #     run_id="run_123456",
            #     limit=10
            # )
            
            # print(f"记忆搜索状态: {memory_search_response.status}")
            # if memory_search_response.status == "success":
            #     # 解析搜索结果
            #     search_items = data_service_client.parse_memory_search_results(memory_search_response)    
            #     for i, item in enumerate(search_items, 1):
            #         print(f"\n{i}. 记忆内容: {item.memory}")
            #         print(f"   记忆ID: {item.id}")
            #         print(f"   相似度分数: {item.score:.4f}")
            #         print(f"   创建时间: {item.created_at}")
            #         if item.metadata:
            #             print(f"   元数据: {item.metadata}")
            # else:
            #     print("记忆搜索失败")
            #     if memory_search_response.data and 'error' in memory_search_response.data:
            #         print(f"错误信息: {memory_search_response.data['error']}")
            
            # print("\n" + "="*50 + "\n")
        finally:
            await data_service_client.close()
            
    except Exception as e:
        print(f"搜索失败: {str(e)}")

if __name__ == "__main__":
    # 运行示例
    asyncio.run(example_usage())
