import json
import logging
import os
import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
import click
import uvicorn
import sys
import uuid
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import asyncio
from enum import Enum
from datetime import datetime
from uvicorn.config import LOGGING_CONFIG
import httpx
from .api.base import DocumentModel, SearchType, CreateRequest, AddTextsRequest, SearchRequest,DeleteRequest, MetadataRequest
from .api.base import MemoryMessage, MemoryAddRequest, MemoryUpdateRequest, MemorySearchRequest, MemoryGetAllRequest, MemoryDeleteRequest, MemoryResponse
from .api.base import KnowledgePyramidAddRequest, KnowledgePyramidSearchRequest, KnowledgePyramidDeleteRequest, KnowledgePyramidDeleteByMetadataRequest
from .api.base import VectorAddDocumentsRequest, VectorDeleteDocumentsRequest, VectorSearchRequest, VectorCreateCollectionRequest, VectorDeleteCollectionRequest, VectorDeleteDocumentsByMetaFieldRequest, VectorGetIdsByMetaFieldRequest, VectorGetIdsByMetaFieldResponse
from .api.base import SignatureCreateRequest, SignatureUpdateRequest, SignatureResponse, SignatureSearchByDDRequest, SignatureListResponse
from .api.base import SemanticDomainCreateRequest, SemanticDomainUpdateRequest, SemanticDomainResponse, SemanticDomainSearchByDDRequest, SemanticDomainListResponse
from .api.base import CodebaseIndexer, CodebaseIndexerCreateRequest, CodebaseIndexerUpdateRequest, CodebaseIndexerResponse, CodebaseIndexerSearchByDDRequest, CodebaseIndexerSearchByFilepathRequest, CodebaseIndexerListResponse
from .api.base import UnstructuredFileUpsertRequest, UnstructuredFileBatchUpsertRequest, UnstructuredFileDeleteByObjectRequest, UnstructuredFileDeleteByDdRequest, UnstructuredFileResponse, UnstructuredFileListResponse
from .api.base import SemanticGroupCreateRequest, SemanticGroupUpdateRequest, SemanticGroupResponse, SemanticGroupListResponse, DDGroupRelationCreateRequest, DDGroupRelationUpdateRequest, DDGroupRelationListResponse, SemanticGroupWithMembersResponse
from .api.base import CreateHistoryRequest, CreateHistoryResponse, SearchHistoryRequest, SearchHistoryResponse, HistoryRecordResponse, HistoryRecord, HistoryMessage,SearchHistoryRequestByUserAndRun
from .api.base import KnowledgeGraphAddRequest, KnowledgeGraphSearchRequest, KnowledgeGraphDeleteRequest, KnowledgeGraphGetGraphRequest, KnowledgeGraphResponse
from .api.base import Signature, SemanticDomain, SemanticGroup, DDGroupRelation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="data services", version="0.1.0")

BACKEND_SERVICE_URL = os.getenv("DATA_SERVICES", "http://data-services.dac:8000")

data_descriptor = os.getenv("DATA_DESCRIPTOR")

# Proxy HTTP client timeout configuration.
#
# The global ``http_client`` proxies every inbound request to the upstream
# ``data-services`` backend. A single 60s timeout is too tight for some
# write operations (notably ``POST /memories``, which triggers mem0's LLM
# fact extraction + embedding + vector/RDB writes and routinely takes
# tens of seconds). Split timeouts per category and allow operators to
# override via environment variables at deploy time.
PROXY_CONNECT_TIMEOUT = float(os.getenv("PROXY_CONNECT_TIMEOUT", "10"))
PROXY_READ_TIMEOUT = float(os.getenv("PROXY_READ_TIMEOUT", "300"))
PROXY_WRITE_TIMEOUT = float(os.getenv("PROXY_WRITE_TIMEOUT", "60"))
PROXY_POOL_TIMEOUT = float(os.getenv("PROXY_POOL_TIMEOUT", "10"))

http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=PROXY_CONNECT_TIMEOUT,
        read=PROXY_READ_TIMEOUT,
        write=PROXY_WRITE_TIMEOUT,
        pool=PROXY_POOL_TIMEOUT,
    )
)
logger.info(
    "proxy http_client timeout configured: connect=%ss read=%ss write=%ss pool=%ss",
    PROXY_CONNECT_TIMEOUT,
    PROXY_READ_TIMEOUT,
    PROXY_WRITE_TIMEOUT,
    PROXY_POOL_TIMEOUT,
)


def validate_data_descriptor(header_value: Optional[str] = None) -> None:
    """
    验证请求中的 data_descriptor 信息是否与环境变量中的一致
    
    验证规则：直接对比 header 中的 Data-Descriptor 值与环境变量 DATA_DESCRIPTOR 是否相等
    
    Args:
        header_value: 从 Header 中提取的 Data-Descriptor 值
    
    Raises:
        HTTPException: 如果验证失败
    """
    # 如果环境变量未设置，跳过验证
    if not data_descriptor:
        logger.warning("DATA_DESCRIPTOR environment variable is not set, skipping validation")
        return
    
    # 完全验证：未传递 Data-Descriptor header 则报错
    if not header_value or not header_value.strip():
        logger.error("Request missing Data-Descriptor header")
        raise HTTPException(
            status_code=403,
            detail="Data-Descriptor header is required"
        )
    
    # 环境变量值
    env_dd = data_descriptor.strip()
    # Header 中的值
    header_dd = header_value.strip()
    
    # 直接比较是否相等
    if header_dd != env_dd:
        logger.error(
            f"Data descriptor mismatch: header={header_dd}, env={env_dd}"
        )
        raise HTTPException(
            status_code=403,
            detail=f"Data descriptor mismatch. Request Data-Descriptor header ({header_dd}) does not match environment DATA_DESCRIPTOR ({env_dd})"
        )
    
    logger.debug(f"Data descriptor validation passed: header={header_dd}, env={env_dd}")


async def extract_data_descriptor_from_request(
    request: Request,
    body_bytes: Optional[bytes] = None
) -> Optional[str]:
    """
    从请求的 HTTP Header 中提取 Data-Descriptor 值
    
    Args:
        request: FastAPI Request 对象
        body_bytes: 请求体的原始字节（未使用，保留以兼容现有调用）
    
    Returns:
        Data-Descriptor header 的值，如果不存在则返回 None
    """
    # 从 Data-Descriptor header 中提取
    data_descriptor_header = request.headers.get("Data-Descriptor")
    if data_descriptor_header:
        return data_descriptor_header.strip()
    return None


async def proxy_request(
    method: str,
    path: str,
    request: Request,
    body: Optional[bytes] = None
) -> Response:
    """
    通用代理函数，将请求转发到后端服务
    
    Args:
        method: HTTP 方法 (GET, POST, PUT, DELETE)
        path: 请求路径
        request: FastAPI Request 对象
        body: 请求体（如果为 None，则从 request 中读取）
    
    Returns:
        Response: 后端服务的响应
    """
    backend_url = None
    try:
        # 使用 request.url.path 获取实际请求路径，这样路径参数已经被替换
        actual_path = request.url.path
        
        # 跳过健康检查等不需要验证的端点
        skip_validation_paths = ["/", "/info"]
        if actual_path not in skip_validation_paths:
            # 从请求的 Header 中提取 Data-Descriptor 并验证
            header_value = await extract_data_descriptor_from_request(request)
            validate_data_descriptor(header_value)
        
        # 构建完整的后端 URL
        backend_url = f"{BACKEND_SERVICE_URL.rstrip('/')}{actual_path}"
        
        # 获取请求体
        if body is None:
            try:
                body = await request.body()
            except Exception:
                body = None
        
        # 获取查询参数
        query_params = dict(request.query_params)
        
        # 获取请求头（排除一些不需要转发的头）
        headers = {}
        for key, value in request.headers.items():
            # 排除一些不需要转发的头
            if key.lower() not in ["host", "content-length", "connection"]:
                headers[key] = value
        
        # 转发请求到后端服务
        async with http_client.stream(
            method=method,
            url=backend_url,
            headers=headers,
            params=query_params if query_params else None,
            content=body
        ) as response:
            # 读取响应内容
            response_body = await response.aread()
            
            # 构建响应头（排除一些不需要转发的头）
            response_headers = {}
            for key, value in response.headers.items():
                if key.lower() not in ["content-length", "transfer-encoding", "connection"]:
                    response_headers[key] = value
            
            # 返回响应
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type", "application/json")
            )
    except httpx.TimeoutException as e:
        # Upstream took longer than our configured timeout window. Surface
        # this as a proper 504 Gateway Timeout so callers can distinguish a
        # "slow backend" from a genuine "bad gateway" and decide to retry
        # accordingly. (Write-heavy endpoints like POST /memories are the
        # most common source of this error — see the PROXY_*_TIMEOUT envs
        # at the top of this module for tuning.)
        backend_url_str = backend_url or "unknown"
        logger.error(
            f"Timeout proxying request to {backend_url_str}: {str(e)} "
            f"(connect={PROXY_CONNECT_TIMEOUT}s read={PROXY_READ_TIMEOUT}s "
            f"write={PROXY_WRITE_TIMEOUT}s pool={PROXY_POOL_TIMEOUT}s)",
            exc_info=True,
        )
        raise HTTPException(status_code=504, detail=f"Upstream timeout: {str(e)}")
    except httpx.HTTPError as e:
        backend_url_str = backend_url or "unknown"
        logger.error(f"Error proxying request to {backend_url_str}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Backend service error: {str(e)}")
    except Exception as e:
        backend_url_str = backend_url or "unknown"
        logger.error(f"Unexpected error in proxy_request (URL: {backend_url_str}): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"status": "running"}

@app.get("/info")
async def get_info():
    return {
        "service": "data-services",
        "version": "0.1.0"
    }


@app.get("/datadescriptors/{namespace}/{name}")
async def proxy_get_datadescriptor(namespace: str, name: str, http_request: Request):
    return await proxy_request(
        "GET", f"/datadescriptors/{namespace}/{name}", http_request
    )


@app.patch("/datadescriptors/{namespace}/{name}/sync-requested-at")
async def proxy_patch_sync_requested_at(
    namespace: str, name: str, http_request: Request
):
    return await proxy_request(
        "PATCH",
        f"/datadescriptors/{namespace}/{name}/sync-requested-at",
        http_request,
    )


###################################### memory routes #########################
@app.post("/memories")
async def add_memory(_request: MemoryAddRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/memories", http_request)


# memory routes
@app.get("/memories/{memory_id}")
async def get_memory(memory_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/memories/{memory_id}", http_request)


# memory routes
@app.post("/memories/get_all")
async def get_all_memories(_request: MemoryGetAllRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/memories/get_all", http_request)


# memory routes
@app.post("/memories/search")
async def search_memories(_request: MemorySearchRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/memories/search", http_request)


# memory routes
@app.put("/memories/{memory_id}")
async def update_memory(memory_id: str, _request: MemoryUpdateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("PUT", f"/memories/{memory_id}", http_request)


# memory routes
@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", f"/memories/{memory_id}", http_request)


# memory routes
@app.post("/memories/delete")
async def delete_memories(_request: MemoryDeleteRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/memories/delete", http_request)


# memory routes
@app.get("/memories/{memory_id}/history")
async def get_memory_history(memory_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/memories/{memory_id}/history", http_request)


# memory routes
@app.post("/memories/reset")
async def reset_all(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", "/memories/reset", http_request)


################################### knowledge pyramid routes ############################
@app.post("/knowledge_pyramid/{collection_name}/add_documents")
async def add_documents_with_knowledge_pyramid(
    collection_name: str, 
    _request: KnowledgePyramidAddRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", f"/knowledge_pyramid/{collection_name}/add_documents", http_request)


@app.post("/knowledge_pyramid/{collection_name}/get_all")
async def get_all_documents_with_knowledge_pyramid(
    collection_name: str,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", f"/knowledge_pyramid/{collection_name}/get_all", http_request)

@app.post("/knowledge_pyramid/find_metadata_values_in_collections")
async def find_metadata_values_in_collections(_request: MetadataRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/knowledge_pyramid/find_metadata_values_in_collections", http_request)

@app.post("/knowledge_pyramid/{collection_name}/search")
async def search_documents_with_knowledge_pyramid(
    collection_name: str,
    _request: KnowledgePyramidSearchRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", f"/knowledge_pyramid/{collection_name}/search", http_request)


# knowledge pyramid routes
@app.delete("/knowledge_pyramid/{collection_name}/delete_by_ids")
async def delete_documents_and_memorys_by_ids(
    collection_name: str, 
    _request: KnowledgePyramidDeleteRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/knowledge_pyramid/{collection_name}/delete_by_ids", http_request)


@app.delete("/knowledge_pyramid/{collection_name}/delete_by_metadata_field")
async def delete_documents_by_metadata_with_knowledge_pyramid(
    collection_name: str,
    _request: KnowledgePyramidDeleteByMetadataRequest,
    http_request: Request,
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request(
        "DELETE",
        f"/knowledge_pyramid/{collection_name}/delete_by_metadata_field",
        http_request,
    )


# knowledge pyramid routes
@app.delete("/knowledge_pyramid/{collection_name}/delete_all")
async def delete_all_documents_by_collection_name(
    collection_name: str,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", f"/knowledge_pyramid/{collection_name}/delete_all", http_request)

# knowledge pyramid routes
@app.post("/knowledge_pyramid/create_collection")
async def create_collection(_request: CreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", "/knowledge_pyramid/create_collection", http_request)

# knowledge pyramid routes
@app.delete("/knowledge_pyramid/delete_collection")
async def delete_collection(_request: DeleteRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", "/knowledge_pyramid/delete_collection", http_request)

############################### vector routes ################################
@app.post("/vector/{collection_name}/add_documents")
async def add_documents_with_vector(
    collection_name: str, 
    _request: VectorAddDocumentsRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", f"/vector/{collection_name}/add_documents", http_request)

# vector routes
@app.post("/vector/{collection_name}/search")
async def search_documents_with_vector(
    collection_name: str,
    _request: VectorSearchRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", f"/vector/{collection_name}/search", http_request)

# vector routes
@app.delete("/vector/{collection_name}/delete_by_ids")
async def delete_documents_by_ids(
    collection_name: str, 
    _request: VectorDeleteDocumentsRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/vector/{collection_name}/delete_by_ids", http_request)

# vector routes
@app.delete("/vector/{collection_name}/delete_by_metadata_field")
async def delete_by_metadata_field(
    collection_name: str, 
    _request: VectorDeleteDocumentsByMetaFieldRequest,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/vector/{collection_name}/delete_by_metadata_field", http_request)


@app.post("/vector/{collection_name}/get_ids_by_metadata_field", response_model=VectorGetIdsByMetaFieldResponse)
async def get_ids_by_metadata_field(
    collection_name: str,
    _request: VectorGetIdsByMetaFieldRequest,
    http_request: Request,
):
    """与 data-services 一致：按 metadata 键值查询文档 id 列表"""
    return await proxy_request("POST", f"/vector/{collection_name}/get_ids_by_metadata_field", http_request)


# vector routes
@app.delete("/vector/{collection_name}/delete_all")
async def delete_all_documents_by_collection_name(
    collection_name: str,
    http_request: Request
):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", f"/vector/{collection_name}/delete_all", http_request)

# vector routes
@app.post("/vector/create_collection")
async def create_collection(_request: VectorCreateCollectionRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", "/vector/create_collection", http_request)

# vector routes
@app.delete("/vector/delete_collection")
async def delete_collection(_request: VectorDeleteCollectionRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", "/vector/delete_collection", http_request)


################################### signature routes ############################
@app.post("/signatures", response_model=SignatureResponse)
async def create_signature(_request: SignatureCreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", "/signatures", http_request)

@app.post("/signatures/batch", response_model=SignatureResponse)
async def batch_create_signatures(_signatures: List[SignatureCreateRequest], http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/signatures/batch", http_request)

@app.get("/signatures/{sig_id}", response_model=SignatureResponse)
async def get_signature_by_sig_id(sig_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/signatures/{sig_id}", http_request)

@app.get("/signatures/fingerprint/{fingerprint}", response_model=SignatureResponse)
async def get_signature_by_fingerprint(fingerprint: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/signatures/fingerprint/{fingerprint}", http_request)

@app.post("/signatures/search/by-dd", response_model=SignatureListResponse)
async def search_signatures_by_dd(_request: SignatureSearchByDDRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("POST", "/signatures/search/by-dd", http_request)

@app.put("/signatures/{sig_id}", response_model=SignatureResponse)
async def update_signature(sig_id: str, _request: SignatureUpdateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("PUT", f"/signatures/{sig_id}", http_request)

@app.delete("/signatures/{sig_id}", response_model=SignatureResponse)
async def delete_signature(sig_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", f"/signatures/{sig_id}", http_request)

@app.delete("/signatures/dd_info/{dd_namespace}/{dd_name}", response_model=SignatureResponse)
async def delete_signatures_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("DELETE", f"/signatures/dd_info/{dd_namespace}/{dd_name}", http_request)

@app.get("/signatures/{sig_id}/exists", response_model=SignatureResponse)
async def check_signature_exists(sig_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/signatures/{sig_id}/exists", http_request)

@app.get("/signatures/dd_info/{dd_namespace}/{dd_name}/exists", response_model=SignatureResponse)
async def check_signature_exists_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", f"/signatures/dd_info/{dd_namespace}/{dd_name}/exists", http_request)

@app.get("/signatures/status/count", response_model=SignatureResponse)
async def get_signature_count(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型"""
    return await proxy_request("GET", "/signatures/status/count", http_request)


################################### semantic domain routes ############################
@app.post("/semantic_domains", response_model=SemanticDomainResponse)
async def create_semantic_domain(_request: SemanticDomainCreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/semantic_domains", http_request)

@app.post("/semantic_domains/batch", response_model=SemanticDomainResponse)
async def batch_create_semantic_domains(_semantic_domains: List[SemanticDomainCreateRequest], http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/semantic_domains/batch", http_request)

@app.get("/semantic_domains/{semantic_domain_id}", response_model=SemanticDomainResponse)
async def get_semantic_domain_by_id(semantic_domain_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/semantic_domains/{semantic_domain_id}", http_request)

@app.post("/semantic_domains/search/by-dd", response_model=SemanticDomainListResponse)
async def search_semantic_domains_by_dd(_request: SemanticDomainSearchByDDRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/semantic_domains/search/by-dd", http_request)

@app.put("/semantic_domains/{semantic_domain_id}", response_model=SemanticDomainResponse)
async def update_semantic_domain(semantic_domain_id: str, _request: SemanticDomainUpdateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("PUT", f"/semantic_domains/{semantic_domain_id}", http_request)

@app.delete("/semantic_domains/{semantic_domain_id}", response_model=SemanticDomainResponse)
async def delete_semantic_domain(semantic_domain_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/semantic_domains/{semantic_domain_id}", http_request)

@app.delete("/semantic_domains/dd_info/{dd_namespace}/{dd_name}", response_model=SemanticDomainResponse)
async def delete_semantic_domains_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}", http_request)

@app.get("/semantic_domains/{semantic_domain_id}/exists", response_model=SemanticDomainResponse)
async def check_semantic_domain_exists(semantic_domain_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/semantic_domains/{semantic_domain_id}/exists", http_request)

@app.get("/semantic_domains/dd_info/{dd_namespace}/{dd_name}/exists", response_model=SemanticDomainResponse)
async def check_semantic_domain_exists_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/semantic_domains/dd_info/{dd_namespace}/{dd_name}/exists", http_request)

@app.get("/semantic_domains/status/count", response_model=SemanticDomainResponse)
async def get_semantic_domain_count(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", "/semantic_domains/status/count", http_request)

################################### codebase indexer routes ############################
@app.post("/codebase_indexers", response_model=CodebaseIndexerResponse)
async def create_codebase_indexer(_request: CodebaseIndexerCreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/codebase_indexers", http_request)

@app.post("/codebase_indexers/batch", response_model=CodebaseIndexerResponse)
async def batch_create_codebase_indexers(_codebase_indexers: List[CodebaseIndexerCreateRequest], http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/codebase_indexers/batch", http_request)

@app.get("/codebase_indexers/{codebase_indexer_id}", response_model=CodebaseIndexerResponse)
async def get_codebase_indexer_by_id(codebase_indexer_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/codebase_indexers/{codebase_indexer_id}", http_request)

@app.post("/codebase_indexers/search/by-dd", response_model=CodebaseIndexerListResponse)
async def search_codebase_indexers_by_dd(_request: CodebaseIndexerSearchByDDRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/codebase_indexers/search/by-dd", http_request)

@app.post("/codebase_indexers/search/by-filepath", response_model=CodebaseIndexerListResponse)
async def search_codebase_indexers_by_filepath(_request: CodebaseIndexerSearchByFilepathRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/codebase_indexers/search/by-filepath", http_request)

@app.put("/codebase_indexers/{codebase_indexer_id}", response_model=CodebaseIndexerResponse)
async def update_codebase_indexer(codebase_indexer_id: str, _request: CodebaseIndexerUpdateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("PUT", f"/codebase_indexers/{codebase_indexer_id}", http_request)

@app.delete("/codebase_indexers/{codebase_indexer_id}", response_model=CodebaseIndexerResponse)
async def delete_codebase_indexer(codebase_indexer_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/codebase_indexers/{codebase_indexer_id}", http_request)

@app.delete("/codebase_indexers/dd_info/{dd_namespace}/{dd_name}", response_model=CodebaseIndexerResponse)
async def delete_codebase_indexers_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}", http_request)

@app.get("/codebase_indexers/{codebase_indexer_id}/exists", response_model=CodebaseIndexerResponse)
async def check_codebase_indexer_exists(codebase_indexer_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/codebase_indexers/{codebase_indexer_id}/exists", http_request)

@app.get("/codebase_indexers/dd_info/{dd_namespace}/{dd_name}/exists", response_model=CodebaseIndexerResponse)
async def check_codebase_indexer_exists_by_dd_info(dd_namespace: str, dd_name: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/codebase_indexers/dd_info/{dd_namespace}/{dd_name}/exists", http_request)

@app.get("/codebase_indexers/status/count", response_model=CodebaseIndexerResponse)
async def get_codebase_indexer_count(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", "/codebase_indexers/status/count", http_request)

################################### semantic group routes ############################
@app.post("/semantic_groups", response_model=SemanticGroupResponse)
async def create_semantic_group(_request: SemanticGroupCreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/semantic_groups", http_request)

@app.post("/semantic_groups/batch", response_model=SemanticGroupResponse)
async def batch_create_semantic_groups(_semantic_groups: List[SemanticGroupCreateRequest], http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/semantic_groups/batch", http_request)

@app.get("/semantic_groups/{group_id}", response_model=SemanticGroupResponse)
async def get_semantic_group_by_id(group_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/semantic_groups/{group_id}", http_request)

@app.get("/semantic_groups/{group_id}/with_members", response_model=SemanticGroupWithMembersResponse)
async def get_semantic_group_with_members(group_id: str, http_request: Request):
    """获取 semantic group 及其包含的 semantic domain 成员详细信息，代理到后端服务"""
    return await proxy_request("GET", f"/semantic_groups/{group_id}/with_members", http_request)


@app.get("/semantic_groups/{group_id}/children", response_model=SemanticGroupListResponse)
async def get_semantic_group_children(group_id: str, http_request: Request):
    """列出某组的直接子组（与 data-services 对齐）"""
    return await proxy_request("GET", f"/semantic_groups/{group_id}/children", http_request)


@app.get("/semantic_groups_roots", response_model=SemanticGroupListResponse)
async def get_semantic_groups_roots(http_request: Request):
    """所有根 semantic group（与 data-services 对齐）"""
    return await proxy_request("GET", "/semantic_groups_roots", http_request)


@app.get("/semantic_groups_leaf_orphans", response_model=SemanticGroupListResponse)
async def get_semantic_groups_leaf_orphans(http_request: Request):
    """叶子且无父的组（与 data-services 对齐）"""
    return await proxy_request("GET", "/semantic_groups_leaf_orphans", http_request)


@app.get("/semantic_groups_orphans_with_members", response_model=SemanticGroupListResponse)
async def get_semantic_groups_orphans_with_members(http_request: Request):
    """有成员但无父的 orphan 组（与 data-services 对齐）"""
    return await proxy_request("GET", "/semantic_groups_orphans_with_members", http_request)


@app.get("/semantic_groups", response_model=SemanticGroupListResponse)
async def get_all_semantic_groups(http_request: Request, page: Optional[int] = None, page_size: Optional[int] = None):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    # FastAPI 会自动注入 Request 对象
    return await proxy_request("GET", "/semantic_groups", http_request)

@app.put("/semantic_groups/{group_id}", response_model=SemanticGroupResponse)
async def update_semantic_group(group_id: str, _request: SemanticGroupUpdateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("PUT", f"/semantic_groups/{group_id}", http_request)

@app.delete("/semantic_groups/{group_id}", response_model=SemanticGroupResponse)
async def delete_semantic_group(group_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/semantic_groups/{group_id}", http_request)

@app.get("/semantic_groups/{group_id}/exists", response_model=SemanticGroupResponse)
async def check_semantic_group_exists(group_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/semantic_groups/{group_id}/exists", http_request)

@app.get("/semantic_groups/status/count", response_model=SemanticGroupResponse)
async def get_semantic_group_count(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", "/semantic_groups/status/count", http_request)


@app.post("/semantic_groups/maintenance/purge_orphan_vectors", response_model=SemanticGroupResponse)
async def purge_orphan_semantic_group_vectors(http_request: Request):
    """清理已删除组在向量库中的残留（与 data-services 对齐）"""
    return await proxy_request("POST", "/semantic_groups/maintenance/purge_orphan_vectors", http_request)


# DD Group Relation routes
@app.post("/dd_group_relations", response_model=SemanticGroupResponse)
async def create_dd_group_relation(_request: DDGroupRelationCreateRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/dd_group_relations", http_request)

@app.post("/dd_group_relations/batch", response_model=SemanticGroupResponse)
async def batch_create_dd_group_relations(_relations: List[DDGroupRelationCreateRequest], http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/dd_group_relations/batch", http_request)

@app.get("/dd_group_relations/group/{group_id}", response_model=DDGroupRelationListResponse)
async def get_relations_by_group_id(group_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/dd_group_relations/group/{group_id}", http_request)

@app.get("/dd_group_relations/sd/{sd_id}", response_model=DDGroupRelationListResponse)
async def get_relations_by_sd_id(sd_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("GET", f"/dd_group_relations/sd/{sd_id}", http_request)


@app.put("/dd_group_relations/{relation_id}", response_model=SemanticGroupResponse)
async def update_dd_group_relation(
    relation_id: int, _request: DDGroupRelationUpdateRequest, http_request: Request
):
    """更新 dd_group_relation（如同步 SD 指纹到 association_reason）"""
    return await proxy_request("PUT", f"/dd_group_relations/{relation_id}", http_request)


@app.delete("/dd_group_relations/{relation_id}", response_model=SemanticGroupResponse)
async def delete_dd_group_relation(relation_id: int, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/dd_group_relations/{relation_id}", http_request)

@app.delete("/dd_group_relations/group/{group_id}", response_model=SemanticGroupResponse)
async def delete_relations_by_group_id(group_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/dd_group_relations/group/{group_id}", http_request)

@app.delete("/dd_group_relations/sd/{sd_id}", response_model=SemanticGroupResponse)
async def delete_relations_by_sd_id(sd_id: str, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", f"/dd_group_relations/sd/{sd_id}", http_request)


################################### unstructured-files routes (backend: /unstructured-files) ############################
# Order aligned with data-services; DELETE /bucket/{bucket} must register before DELETE /{row_id}.
@app.post("/unstructured-files", response_model=UnstructuredFileResponse)
async def unstructured_files_upsert_one(_request: UnstructuredFileUpsertRequest, http_request: Request):
    """代理到 data-services：单条 upsert（含可选 file_summary）"""
    return await proxy_request("POST", "/unstructured-files", http_request)


@app.post("/unstructured-files/batch", response_model=UnstructuredFileResponse)
async def unstructured_files_batch_upsert(_request: UnstructuredFileBatchUpsertRequest, http_request: Request):
    """代理到 data-services：批量 upsert MinIO 文件元数据（含可选 file_summary）"""
    return await proxy_request("POST", "/unstructured-files/batch", http_request)


@app.get("/unstructured-files/{row_id}", response_model=UnstructuredFileResponse)
async def unstructured_files_get_by_id(row_id: int, http_request: Request):
    """代理到 data-services：按主键 id 查询"""
    return await proxy_request("GET", f"/unstructured-files/{row_id}", http_request)


@app.get("/unstructured-files", response_model=UnstructuredFileListResponse)
async def unstructured_files_list(http_request: Request):
    """代理到 data-services：列表（query: bucket, dd_namespace, dd_name, limit, offset）"""
    return await proxy_request("GET", "/unstructured-files", http_request)


@app.post("/unstructured-files/delete-by-object", response_model=UnstructuredFileResponse)
async def unstructured_files_delete_by_object(_request: UnstructuredFileDeleteByObjectRequest, http_request: Request):
    """代理到 data-services：按 bucket + minio_path + DD 删除一条"""
    return await proxy_request("POST", "/unstructured-files/delete-by-object", http_request)


@app.post("/unstructured-files/delete-by-dd", response_model=UnstructuredFileResponse)
async def unstructured_files_delete_by_dd(_request: UnstructuredFileDeleteByDdRequest, http_request: Request):
    """代理到 data-services：删除某 DataDescriptor 下全部 unstructured_files 行"""
    return await proxy_request("POST", "/unstructured-files/delete-by-dd", http_request)


@app.delete("/unstructured-files/bucket/{bucket}", response_model=UnstructuredFileResponse)
async def unstructured_files_delete_by_bucket(bucket: str, http_request: Request):
    """代理到 data-services：按 bucket 全删（慎用）"""
    return await proxy_request("DELETE", f"/unstructured-files/bucket/{bucket}", http_request)


@app.delete("/unstructured-files/{row_id}", response_model=UnstructuredFileResponse)
async def unstructured_files_delete_by_id(row_id: int, http_request: Request):
    """代理到 data-services：按主键 id 删除"""
    return await proxy_request("DELETE", f"/unstructured-files/{row_id}", http_request)


################################### history routes ############################
@app.post("/history/create", response_model=CreateHistoryResponse)
async def create_history_record(_request: CreateHistoryRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/history/create", http_request)

@app.post("/history/search", response_model=SearchHistoryResponse)
async def search_history_records(_search_request: SearchHistoryRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/history/search", http_request)

@app.post("/history/search_user_run", response_model=SearchHistoryResponse)
async def search_history_records_by_user_and_run(_search_request: SearchHistoryRequestByUserAndRun, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/history/search_user_run", http_request)

##################################### knowledge graph #######################################
@app.post("/knowledge_graph/add_with_source", response_model=KnowledgeGraphResponse)
async def knowledge_graph_add_with_source(_request: KnowledgeGraphAddRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/knowledge_graph/add_with_source", http_request)

@app.post("/knowledge_graph/search_with_source", response_model=KnowledgeGraphResponse)
async def knowledge_graph_search_with_source(_request: KnowledgeGraphSearchRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/knowledge_graph/search_with_source", http_request)

@app.post("/knowledge_graph/get_graph_by_source", response_model=KnowledgeGraphResponse)
async def knowledge_graph_get_graph_by_source(_request: KnowledgeGraphGetGraphRequest, http_request: Request):
    """按 source 查询整图（所有节点 + 所有关系），代理到后端服务"""
    return await proxy_request("POST", "/knowledge_graph/get_graph_by_source", http_request)

@app.delete("/knowledge_graph/delete_with_source", response_model=KnowledgeGraphResponse)
async def knowledge_graph_delete_with_source(_request: KnowledgeGraphDeleteRequest, http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("DELETE", "/knowledge_graph/delete_with_source", http_request)


@app.post("/knowledge_graph/create_vector_index", response_model=KnowledgeGraphResponse)
async def knowledge_graph_create_vector_index(http_request: Request):
    """代理请求到后端服务，保留原有的 request 类型用于验证和文档"""
    return await proxy_request("POST", "/knowledge_graph/create_vector_index", http_request)


@click.command()
@click.option('--host', default='0.0.0.0', help='Host to bind')
@click.option('--port', default=8000, help='Port to bind')
def main(host, port):
    logging.basicConfig(
        force=True,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    log_config = LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_config["formatters"]["default"]["fmt"] = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    async def run_server():
        # 代理模式不需要初始化服务，直接启动服务器
        logger.info(f"Starting proxy server on {host}:{port}")
        logger.info(f"Backend service URL: {BACKEND_SERVICE_URL}")
        
        # 如果指定的 host 不是 0.0.0.0，检查是否是有效的 IP
        if host != '0.0.0.0':
            import socket
            try:
                # 尝试绑定到指定 IP，如果失败则提示
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                test_socket.bind((host, port))
                test_socket.close()
            except OSError as e:
                logger.warning(f"Warning: Cannot bind to {host}:{port}. Error: {e}")
                logger.warning(f"Tip: Use 0.0.0.0 to bind to all interfaces, or check if the IP address is correct.")
                raise
        
        config = uvicorn.Config(app, host=host, port=port, log_config=log_config)
        server = uvicorn.Server(config)
        await server.serve()

    try:
        asyncio.run(run_server())
    except OSError as e:
        if "Address already in use" in str(e) or "address already in use" in str(e).lower():
            logger.error(f'Port {port} is already in use. Please choose a different port.')
        elif "Cannot assign requested address" in str(e) or "cannot assign requested address" in str(e).lower():
            logger.error(f'Cannot bind to {host}:{port}. The IP address {host} may not be available on this machine.')
            logger.error(f'Tip: Use --host 0.0.0.0 to bind to all network interfaces.')
        else:
            logger.error(f'Server startup failed: {e}', exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f'Server startup failed: {e}', exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()