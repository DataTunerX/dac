import time
import os
import json
from urllib.parse import quote_plus
from celery import Celery
from data_sinkers import get_reader
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import logging
import re
from .client.knowledge_pyramid_client import KnowledgePyramidClient
from .client.vector_client import VectorClient
from .client.signature_client import SignatureClient, SignatureData
from .client.semantic_domain_client import SemanticDomainClient, SemanticDomainData
from .client.semantic_group_client import SemanticGroupClient
from .client.celery_httpserver_client import CeleryHttpserverClient
from .client.knowledge_graph_client import KnowledgeGraphClient, convert_to_knowledge_graph
from .client.codebase_indexer_client import CodebaseIndexerClient, CodebaseIndexerData
from .api.base import DocumentModel
from .extractors.mysql import extract_mysql
from .extractors.postgres import extract_postgres
from .extractors.code import extract_code
from .extractors.minio import extract_minio
from .extractors.fileserver import extract_fileserver
from .extractors.knowledge_graph import Knowledge_Graph
from .fingerprint.fingerprint import (
    FingerprintBuilder,
    CODE_COMMIT_SHA_METADATA_KEY,
    fingerprint_id_for_unstructured,
    resolve_code_commit_sha_for_fingerprint,
)
from .semantic_group.semantic_group import SemanticGrouper
from .source_helpers import merge_code_repo_into_metadata
from .connection_config import DataSourceType, get_connection_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_sinkers")

# redis config for worker
redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = os.getenv('REDIS_PORT', '6379')
redis_db_broker = os.getenv('REDIS_DB_BROKER', '4')
redis_db_backend = os.getenv('REDIS_DB_BACKEND', '5')
redis_password = os.getenv('REDIS_PASSWORD')

provider = os.getenv('PROVIDER', 'openai_compatible')
api_key = os.getenv('API_KEY', '')
base_url = os.getenv('BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
model = os.getenv('Model', 'qwen3-32b')
temperature = float(os.getenv('Temperature', '0.01'))

enable_allinone = os.getenv('ENABLE_ALLINONE', 'disable')
enable_sample_data = os.getenv('ENABLE_SAMPLE_DATA', 'disable')

# data services
data_services_url = os.getenv('DATA_SERVICES', 'http://localhost:8000')

# URL encode the password if it contains special characters
password_part = f':{quote_plus(redis_password)}@' if redis_password else ''

class DataSourceConfig(BaseModel):
    type: DataSourceType
    name: str
    metadata: Dict[str, Any]
    authentication_ref: Optional[str] = Field(None, alias="authenticationRef")
    extract: Dict[str, Any]
    processing: Optional[Dict[str, Any]] = None
    classification: Optional[Dict[str, Any]] = None


celery = Celery(
    'tasks',
    broker=f'redis://{password_part}{redis_host}:{redis_port}/{redis_db_broker}',
    backend=f'redis://{password_part}{redis_host}:{redis_port}/{redis_db_backend}'
)

# config Celery
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue='dataset',
    task_routes={
        'tasks.process_data': {'queue': 'dataset'},
        'tasks.semantic_group': {'queue': 'dataset'},
    },
    task_track_started=True
)

#build KnowledgePyramidClient to send documents to data-services
knowledge_pyramid_client = KnowledgePyramidClient(base_url=data_services_url, timeout=600)

#build VectorClient to send signature documents to data-services
vector_client = VectorClient(base_url=data_services_url, timeout=600)
vector_client.initialize()

#build signature client to send signature to data-services
signature_client = SignatureClient(base_url=data_services_url, timeout=600)

#build semantic domain client to send semantic domain to data-services
semantic_domain_client = SemanticDomainClient(base_url=data_services_url, timeout=600)

#build semantic group client to send semantic group to data-services
semantic_group_client = SemanticGroupClient(base_url=data_services_url, timeout=600)

#build celery httpserver client to trigger celery tasks
celery_httpserver_url = os.getenv('CELERY_HTTPSERVER_API_BASE_URL', 'http://celery-httpserver.dac.svc.cluster.local:8000')
celery_httpserver_client = CeleryHttpserverClient(base_url=celery_httpserver_url, timeout=600)

# build semantic grouper with vector client, semantic group client and semantic domain client
semantic_grouper = SemanticGrouper(
    vector_client=vector_client,
    semantic_group_client=semantic_group_client,
    semantic_domain_client=semantic_domain_client
)

knowledgeGraphClient = KnowledgeGraphClient(base_url=data_services_url, timeout=600)

#build codebase indexer client to send codebase index to data-services
codebase_indexer_client = CodebaseIndexerClient(base_url=data_services_url, timeout=600)

@celery.task(name='tasks.process_data', bind=True, acks_late=True)
def process_data(self, data: Dict[str, Any]):
    logger.info(f"============= start task {self.request.id} ===================")
    
    try:
        operation = data.get('operation')
        source_data = data.get('source', {})
        descriptor = data.get('descriptor', {})
        extract = data.get('extract', {})
        prompts = data.get('prompts', {})
        codeRepo = data.get('codeRepo', {})

        sql_process_mode="dictionary"

        collection_name = generate_collection_name(descriptor)

        logger.info(f"===start task, data={data}===")

        if operation == "Delete":
            try:
                if not all([operation, descriptor]):
                    raise ValueError("Missing necessary input fields to delete the collection: operation, descriptor")

                dd_namespace = descriptor.get('namespace')
                dd_name = descriptor.get('name')
                signature_result = send_delete_signature(dd_namespace=dd_namespace, dd_name=dd_name)
                logger.info(f"Successfully sent delete signature request {collection_name} to signature database")

                pyramid_result = send_delete_collection_to_knowledge_pyramid(collection_name=collection_name)
                logger.info(f"Successfully sent delete collection request {collection_name} to Knowledge Pyramid")

                send_delete_knowledge_graph(collection_name)
                logger.info(f"Successfully sent delete collection request {collection_name} to Knowledge graph")

                # Delete codebase index records
                send_delete_codebase_index(dd_namespace=dd_namespace, dd_name=dd_name)
                logger.info(f"Successfully sent delete codebase index request for {dd_namespace}/{dd_name}")
                
                semantic_group_data = {
                    "operation": "Delete",
                    "descriptor": descriptor
                }
                semantic_group_event(semantic_group_data)

            except Exception as e:
                raise ValueError(f"KnowledgePyramidClient to send delete collection to data-services fail: {data}") from e

            return {
                "status": "success",
                "task_id": self.request.id,
                "descriptor": descriptor
            }

        if not all([source_data, descriptor]):
            raise ValueError("Missing necessary input fields to create collection and add documents: source, descriptor")

        try:
            source_type = DataSourceType(source_data.get('type'))
        except ValueError as e:
            raise ValueError(f"Unsupported data source type: {source_data.get('type')}") from e

        source_metadata = merge_code_repo_into_metadata(
            source_data.get("metadata", {}), codeRepo
        )
        connection_config = get_connection_config(source_type, source_metadata)
        
        logger.info(f"connection_config = {connection_config}")

        reader = None
        result: List[DocumentModel] = []

        try:
            reader = get_reader(source_type.value, connection_config)
            if source_type == DataSourceType.MYSQL:
                result, fingerprint_associated_info = extract_mysql(reader, descriptor, extract, prompts, codeRepo, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data, sql_process_mode=sql_process_mode)
                
            elif source_type == DataSourceType.POSTGRESQL:
                result, fingerprint_associated_info = extract_postgres(reader, descriptor, extract, prompts, codeRepo, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data, sql_process_mode=sql_process_mode)

            elif source_type == DataSourceType.GITHUB:
                result, fingerprint_associated_info, codebase_index_result = extract_code(reader, descriptor, "github")

            elif source_type == DataSourceType.GITEE:
                result, fingerprint_associated_info, codebase_index_result = extract_code(reader, descriptor, "gitee")

            elif source_type == DataSourceType.GITLAB:
                result, fingerprint_associated_info, codebase_index_result = extract_code(reader, descriptor, "gitlab")

            elif source_type == DataSourceType.MINIO:
                result, fingerprint_associated_info = extract_minio(reader, descriptor, extract, prompts)

            elif source_type == DataSourceType.FILESERVER:
                result, fingerprint_associated_info = extract_fileserver(reader, descriptor, extract, prompts) 

            logger.debug(f"============= process_data extract success, result = {result} , fingerprint_associated_info = {fingerprint_associated_info}")

            send_add_signature(source_type, connection_config, descriptor, fingerprint_associated_info)
            logger.info(f"Successfully sent add collection request {collection_name} to signature")
            
            added_semantic_domain = send_add_semantic_domain(descriptor, fingerprint_associated_info)
            logger.info(f"Successfully sent add collection request {collection_name} to semantic domain")

            added_knowledge_graph = send_add_knowledge_graph(collection_name, fingerprint_associated_info)
            logger.info(f"Successfully sent add collection request {collection_name} to Knowledge graph")
            
            # Send codebase index to data-services for code repositories (GitHub/GitLab/Gitee)
            if source_type in [DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB]:
                if codebase_index_result:
                    send_codebase_index_to_dataservices(codebase_index_result, descriptor)
                    logger.info(f"Successfully sent codebase index to data-services for {collection_name}")
            
            serializable_result = [item.dict() for item in result] if result else []

            pyramid_result = None

            if serializable_result:
                try:
                    pyramid_result = send_add_documents_to_knowledge_pyramid(documents=serializable_result, collection_name=collection_name)
                    logger.info(f"Successfully sent {len(serializable_result)} documents to Knowledge Pyramid")
                except Exception as e:
                    raise ValueError(f"KnowledgePyramidClient to send documents to data-services fail: {data}") from e

            semantic_group_data = {
                "operation": "AddOrUpdate",
                "descriptor": descriptor
            }
            semantic_group_event(semantic_group_data)

            return {
                "status": "success",
                "task_id": self.request.id,
                "descriptor": descriptor,
                "data": serializable_result,
                "pyramid_result": pyramid_result,
                "metadata": {
                    "source_type": source_type.value,
                    "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            }
        except Exception as e:
            logger.error(f"Data processing failed: {str(e)}", exc_info=True)
            raise ValueError(f"extract data fail: {data}, error={str(e)}") from e
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception as e:
                    logger.warning(f"Failed to close reader: {str(e)}", exc_info=True)
            
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}", exc_info=True)
        raise ValueError(f"process_data fail: {data}, error={str(e)}") from e

def send_add_signature(data_type, connection_config, descriptor, fingerprint_associated_info):
    """
    Create and send signature record to data-services
    
    Args:
        data_type: Data source type
        connection_config: Connection configuration
        descriptor: Descriptor containing namespace and name
        fingerprint_associated_info: Associated information including tables, etc.
    """
    fingerprintBuilder = FingerprintBuilder()

    fingerprint_summary = ""
    commit_sha: Optional[str] = None
    fingerprint_id: Optional[str] = None

    if data_type == DataSourceType.MYSQL:
        fingerprint_summary = fingerprintBuilder.generate_db_fingerprint_summary(data_type, fingerprint_associated_info["tables_schema_md_list"])
    elif data_type == DataSourceType.POSTGRESQL:
        fingerprint_summary = fingerprintBuilder.generate_db_fingerprint_summary(data_type, fingerprint_associated_info["tables_schema_md_list"])
    elif data_type in (DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB):
        repo_url = connection_config.get("codeRepoPath") or ""
        branch = connection_config.get("codeRepoBranch") or "main"
        token = connection_config.get("token") or connection_config.get("codeRepoToken") or ""
        commit_sha = resolve_code_commit_sha_for_fingerprint(
            repo_url,
            branch,
            token or None,
            resolved_head_sha=fingerprint_associated_info.get("resolved_head_sha"),
            stored_commit_sha=None,
        )
        fingerprint_summary = fingerprintBuilder.generate_code_fingerprint_summary(
            data_type, connection_config, commit_sha
        )
    elif data_type == DataSourceType.MINIO:
        obj_hash = fingerprint_associated_info.get("object_list_hash")
        fingerprint_id = fingerprint_id_for_unstructured(
            data_type, connection_config, obj_hash
        )
    elif data_type == DataSourceType.FILESERVER:
        obj_hash = fingerprint_associated_info.get("object_list_hash")
        fingerprint_id = fingerprint_id_for_unstructured(
            data_type, connection_config, obj_hash
        )

    if fingerprint_id is None:
        fingerprint_id = fingerprintBuilder.generate_fingerprint_id(fingerprint_summary)

    # Determine sig_type based on data source type
    sig_type_map = {
        DataSourceType.MYSQL: "database",
        DataSourceType.POSTGRESQL: "database",
        DataSourceType.GITHUB: "application",
        DataSourceType.GITEE: "application",
        DataSourceType.GITLAB: "application",
        DataSourceType.MINIO: "file_system",
        DataSourceType.FILESERVER: "file_system"
    }
    sig_type = sig_type_map.get(data_type, "application")

    # Build location_info from connection_config based on data source type
    location_info = None
    if data_type in [DataSourceType.MYSQL, DataSourceType.POSTGRESQL]:
        location_info = {
            k: v for k, v in {
                "host": connection_config.get("host"),
                "port": connection_config.get("port"),
                "database": connection_config.get("database")
            }.items() if v is not None
        }
        location_info = location_info if location_info else None
    elif data_type in [DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB]:
        location_info = {
            k: v for k, v in {
                "repo_path": connection_config.get("codeRepoPath"),
                "branch": connection_config.get("codeRepoBranch")
            }.items() if v is not None
        }
        location_info = location_info if location_info else None
    elif data_type == DataSourceType.MINIO:
        location_info = {
            k: v for k, v in {
                "host": connection_config.get("host"),
                "bucket": connection_config.get("bucket")
            }.items() if v is not None
        }
        location_info = location_info if location_info else None
    elif data_type == DataSourceType.FILESERVER:
        location_info = {
            k: v for k, v in {
                "host": connection_config.get("host"),
                "port": connection_config.get("port")
            }.items() if v is not None
        }
        location_info = location_info if location_info else None

    # Build metadata_content from fingerprint_summary and related info
    metadata_content = {
        "data_type": data_type,
        "sig_type": sig_type
    }
    if data_type in [DataSourceType.MYSQL, DataSourceType.POSTGRESQL]:
        metadata_content.update({
            "tables_detail": fingerprint_associated_info.get("tables_detail", {}),
            "tables_relationship": fingerprint_associated_info.get("tables_relationship", {}),
            "tables_schema_md_list": fingerprint_associated_info.get("tables_schema_md_list", [])
        })
    elif data_type in (DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB):
        if commit_sha:
            metadata_content[CODE_COMMIT_SHA_METADATA_KEY] = commit_sha

    signature = SignatureData(
        sig_type=sig_type,
        discovery_mode="auto",  # Default to auto discovery mode
        fingerprint=fingerprint_id,
        location_info=location_info,
        metadata_content=metadata_content,
        dd_namespace=descriptor.get('namespace'),
        dd_name=descriptor.get('name')
    )

    logger.info(f"send_add_signature: signature = {signature}")

    try:
        result = signature_client.create_signature(signature)
        logger.debug(f"create signature: {result}")

        return result
    except Exception as e:
        logger.error(f"create signature fail: {str(e)}", exc_info=True)
        raise

def send_add_semantic_domain(descriptor, fingerprint_associated_info):
    """
    Create and send semantic domain record to data-services
    
    Args:
        descriptor: Descriptor containing namespace and name
        fingerprint_associated_info: Associated information including semantic_domain, agent_card, etc.
    """
    agent_card = json.dumps(fingerprint_associated_info.get("agent_card", {}), ensure_ascii=False, indent=4)
    semantic_domain_text = fingerprint_associated_info.get("ddd")

    # 从环境变量中获取 DataDescriptor CRD 的 descriptorType（由 dd.go 设置）
    descriptor_type = os.environ.get("DESCRIPTOR_TYPE", "")

    semantic_domain = SemanticDomainData(
        semantic_domain=semantic_domain_text,
        agent_card=agent_card,
        dd_namespace=descriptor.get('namespace'),
        dd_name=descriptor.get('name'),
        descriptor_type=descriptor_type if descriptor_type else None
    )

    logger.info(f"send_add_semantic_domain: semantic_domain = {semantic_domain}")

    try:
        result = semantic_domain_client.create_semantic_domain(semantic_domain)
        logger.debug(f"create semantic domain: {result}")

        return result
    except Exception as e:
        logger.error(f"create semantic domain fail: {str(e)}", exc_info=True)
        raise

def send_add_documents_to_knowledge_pyramid(documents: List[Dict[str, Any]], collection_name: str) -> Dict[str, Any]:
    try:
        create_collection_result = knowledge_pyramid_client.create_collection(
            collection_name=collection_name
        )
        logger.info(f"create collection: {create_collection_result}")

        document_objects = [
            DocumentModel(
                page_content=doc["page_content"], 
                metadata={k: v for k, v in doc.get("metadata", {}).items() if k != "orig_elements"}
            )
            for doc in documents
        ]

        add_documents_result = knowledge_pyramid_client.add_documents(
            collection_name=collection_name,
            documents=document_objects
        )
        logger.info(f"add document success: {add_documents_result}")
        return add_documents_result
    except Exception as e:
        logger.error(f"create collection or add document fail: {str(e)}", exc_info=True)
        raise

def send_delete_collection_to_knowledge_pyramid(collection_name: str) -> Dict[str, Any]:
    try:
        delete_collection_result = knowledge_pyramid_client.delete_collection(
            collection_name=collection_name
        )
        logger.info(f"delete collection: {delete_collection_result}")

        return delete_collection_result
    except Exception as e:
        logger.error(f"delete collection fail: {str(e)}", exc_info=True)
        raise

def send_add_knowledge_graph(collection_name, fingerprint_associated_info):
    try:
        knowledge_graph = Knowledge_Graph()

        semantic_domain_text = fingerprint_associated_info.get("ddd")

        knowledge_graph_result = knowledge_graph.knowledge_graph(semantic_domain_text)

        nodes, relationships = convert_to_knowledge_graph(knowledge_graph_result)

        logger.info(f"send_add_knowledge_graph, nodes={nodes}, relationships={relationships}")

        knowledgeGraphClient.add_with_source(source=collection_name, nodes=nodes, relationships=relationships, clear_existing=True)

    except Exception as e:
        logger.error(f"delete collection fail: {str(e)}", exc_info=True)
        raise

def send_delete_knowledge_graph(collection_name):
    try:
        knowledgeGraphClient.delete_with_source(collection_name)
    except Exception as e:
        logger.error(f"delete collection fail: {str(e)}", exc_info=True)
        raise

def send_codebase_index_to_dataservices(codebase_index_result: List[Dict], descriptor: Dict) -> Dict[str, Any]:
    """
    Send codebase index results to data-services via batch API
    
    Args:
        codebase_index_result: List of code analysis results from CodebaseIndexer
        descriptor: Descriptor containing namespace and name
        
    Returns:
        API response result
    """
    if not codebase_index_result:
        logger.info("No codebase index result to send")
        return {"status": "skipped", "message": "No codebase index result"}
    
    dd_namespace = descriptor.get('namespace')
    dd_name = descriptor.get('name')
    
    # Convert codebase_index_result to CodebaseIndexerData objects
    codebase_indexers = []
    for result in codebase_index_result:
        # Only process successful results
        if result.get('status') != 'success':
            continue
            
        file_path = result.get('file_path', '')
        analysis_result = result.get('analysis_result', {})
        
        # Convert analysis_result to JSON string for storage
        code_deep_analysis = json.dumps(analysis_result, ensure_ascii=False) if analysis_result else ''
        
        codebase_indexer = CodebaseIndexerData(
            filepath=file_path,
            code_deep_analysis=code_deep_analysis,
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )
        codebase_indexers.append(codebase_indexer)
    
    if not codebase_indexers:
        logger.info("No valid codebase index results to send after filtering")
        return {"status": "skipped", "message": "No valid results after filtering"}
    
    logger.info(f"Sending {len(codebase_indexers)} codebase index records to data-services")
    
    try:
        result = codebase_indexer_client.batch_create_codebase_indexers(codebase_indexers)
        logger.info(f"Successfully sent codebase index to data-services: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send codebase index to data-services: {str(e)}", exc_info=True)
        raise

def send_delete_codebase_index(dd_namespace: str, dd_name: str) -> Dict[str, Any]:
    """
    Delete codebase index records by DD information
    
    Args:
        dd_namespace: DD namespace
        dd_name: DD name
        
    Returns:
        API response result
    """
    try:
        result = codebase_indexer_client.delete_codebase_indexers_by_dd_info(
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )
        logger.info(f"delete codebase index: {result}")
        return result
    except Exception as e:
        logger.error(f"delete codebase index fail: {str(e)}", exc_info=True)
        raise

# 给dd进行语义域分组
def incremental_semantic_group(descriptor) -> Dict[str, Any]:
    """
    对语义域进行分组
    
    Args:
        descriptor: 数据描述符，包含 namespace 和 name
            函数内部会通过 semantic_domain_client 获取对应的语义域数据
    
    Returns:
        分组结果，包含 action、group_id、group_name、confidence 等信息
    """
    try:
        dd_namespace = descriptor.get('namespace')
        dd_name = descriptor.get('name')

        semantic_domain = semantic_domain_client.search_semantic_domains_by_dd(
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )

        if semantic_domain is None:
            logger.warning(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
            raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")

        # 处理返回格式：search_semantic_domains_by_dd 返回格式为 {"data": [...]}
        if isinstance(semantic_domain, dict):
            if 'data' in semantic_domain:
                data_list = semantic_domain.get('data', [])
                # data 是一个列表，取第一个元素
                if isinstance(data_list, list):
                    if len(data_list) == 0:
                        logger.warning(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
                        raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
                    domain_data = data_list[0]  # 取第一个语义域
                else:
                    # 如果不是列表，直接使用（向后兼容）
                    domain_data = data_list
            else:
                # 如果没有 'data' 键，假设整个响应就是语义域数据
                domain_data = semantic_domain
        else:
            logger.error(f"semantic_domain 参数格式错误: {type(semantic_domain)}")
            raise ValueError(f"semantic_domain 参数必须是字典类型，当前类型: {type(semantic_domain)}")

        # 确保 domain_data 是字典类型
        if not isinstance(domain_data, dict):
            logger.error(f"domain_data 格式错误: 期望字典类型，实际类型: {type(domain_data)}")
            raise ValueError(f"domain_data 必须是字典类型，当前类型: {type(domain_data)}")

        domain = {
            "semantic_domain_id": domain_data.get('semantic_domain_id', ''),
            "semantic_domain": domain_data.get('semantic_domain', ''),
            "agent_card": domain_data.get('agent_card', ''),
            "dd_name": domain_data.get('dd_name', descriptor.get('name', '')),
            "dd_namespace": domain_data.get('dd_namespace', descriptor.get('namespace', ''))
        }
        
        result = semantic_grouper.incremental_semantic_group_analyse(domain)
        
        logger.info(f"语义域分组完成: {result}")
        return result
        
    except Exception as e:
        logger.error(f"语义域分组失败: {str(e)}", exc_info=True)
        raise

def decremental_semantic_group(descriptor) -> Dict[str, Any]:
    """
    删除 DD 对应的所有语义域与语义组的关联。
    一个 DD 可能有多条 semantic_domain 记录（多次 add/update），必须对全部执行 decremental，
    否则 delete_semantic_domain 会删除所有记录，但 dd_group_relation 中会残留孤儿关系。
    """
    try:
        dd_namespace = descriptor.get('namespace')
        dd_name = descriptor.get('name')

        semantic_domain = semantic_domain_client.search_semantic_domains_by_dd(
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )

        if isinstance(semantic_domain, dict):
            if 'data' in semantic_domain:
                data_list = semantic_domain.get('data', [])
                if isinstance(data_list, list):
                    if len(data_list) == 0:
                        logger.warning(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
                        raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
                    domain_list = data_list
                else:
                    domain_list = [data_list] if isinstance(data_list, dict) else []
            else:
                domain_list = [semantic_domain] if isinstance(semantic_domain, dict) else []
        else:
            logger.error(f"semantic_domain 参数格式错误: {type(semantic_domain)}")
            raise ValueError(f"semantic_domain 参数必须是字典类型，当前类型: {type(semantic_domain)}")

        last_result = None
        for domain_data in domain_list:
            if not isinstance(domain_data, dict):
                logger.warning(f"跳过无效的 domain_data，类型: {type(domain_data)}")
                continue
            sd_id = domain_data.get('semantic_domain_id')
            if not sd_id:
                logger.warning(f"跳过缺少 semantic_domain_id 的 domain_data")
                continue
            logger.info(f"对语义域 {sd_id} 执行 decremental: {dd_namespace}/{dd_name}")
            result = semantic_grouper.decremental_semantic_group_analyse(sd_id)
            last_result = result
            if isinstance(result, dict) and result.get('status') == 'error':
                logger.error(f"decremental 失败: {result.get('message', '')}")
                raise ValueError(result.get('message', '删除语义域失败'))

        logger.info(f"语义域分组完成 (共处理 {len(domain_list)} 条): {last_result}")
        return last_result or {"status": "success", "message": "无语义域需处理"}
        
    except Exception as e:
        logger.error(f"语义域分组失败: {str(e)}", exc_info=True)
        raise



# def send_delete_documents_from_vector_semantic_groups(descriptor) -> Dict[str, Any]:
#     try:
#         group_name = generate_collection_name(descriptor)

#         delete_documents_result = vector_client.delete_by_metadata_field(
#             collection_name="semantic_groups",
#             key="group_name",
#             value=group_name
#         )
#         logger.info(f"delete document by metadata field success: {delete_documents_result}")
#         return delete_documents_result
#     except Exception as e:
#         logger.error(f"delete document by metadata field fail: {str(e)}", exc_info=True)
#         raise

def send_delete_signature(dd_namespace: str, dd_name: str) -> Dict[str, Any]:
    """
    Delete signature records by DD information
    
    Args:
        dd_namespace: DD namespace
        dd_name: DD name
        
    Returns:
        API response result
    """
    try:
        result = signature_client.delete_signatures_by_dd_info(
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )
        logger.info(f"delete signature: {result}")

        return result
    except Exception as e:
        logger.error(f"delete signature fail: {str(e)}", exc_info=True)
        raise

def send_delete_semantic_domain(dd_namespace: str, dd_name: str) -> Dict[str, Any]:
    """
    Delete semantic domain records by DD information
    
    Args:
        dd_namespace: DD namespace
        dd_name: DD name
        
    Returns:
        API response result
    """
    try:
        result = semantic_domain_client.delete_semantic_domains_by_dd_info(
            dd_namespace=dd_namespace,
            dd_name=dd_name
        )
        logger.info(f"delete semantic domain: {result}")

        return result
    except Exception as e:
        logger.error(f"delete semantic domain fail: {str(e)}", exc_info=True)
        raise

def _is_valid_table_name(table_name: str) -> bool:
    """验证表名是否有效（仅包含字母、数字和下划线，且以字母或下划线开头）"""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name))

def generate_collection_name(descriptor: dict) -> str:
    """
    Generate collection_name based on descriptor
    
    Format: namespace_name
    Rule: Replace '-' with '_'
    
    Args:
        descriptor: Dictionary containing name and namespace
        
    Returns:
        str: Generated collection_name
    """
    namespace = descriptor.get('namespace', '')
    name = descriptor.get('name', '')
    
    # Combine into collection_name
    collection_name = f"{namespace}_{name}"

    # Replace '-' with '_' in the namespace
    collection_name = collection_name.replace('-', '_')
    
    return collection_name


def semantic_group_event(data):
    operation = data.get('operation')
    descriptor = data.get('descriptor', {})

    if not descriptor:
        raise ValueError("Missing necessary input fields to add/delete: descriptor")
            
    dd_namespace = descriptor.get('namespace')
    dd_name = descriptor.get('name')
            
    if not all([dd_namespace, dd_name]):
        raise ValueError("Missing necessary fields in descriptor: namespace, name")
            
    # Use Celery HTTP client to trigger semantic_group_task with AddOrUpdate operation
    task_data = {
        "operation": operation,
        "descriptor": {
            "name": dd_name,
            "namespace": dd_namespace
        }
    }
            
    try:
        result = celery_httpserver_client.semantic_group_task(task_data)
        task_id = result.get("task_id")
        logger.info(f"Successfully triggered semantic_group_task add/delete request for {dd_namespace}/{dd_name}, operation: {operation}, task_id: {task_id}")
                
        return {
            "status": "success",
            "celery_task_id": task_id,
            "descriptor": descriptor
        }
    except Exception as e:
        logger.error(f"Failed to trigger semantic_group_task add/delete request: {str(e)}, operation: {operation} for {dd_namespace}/{dd_name}", exc_info=True)
        raise ValueError(f"CeleryHttpserverClient to trigger semantic_group_task add/delete fail: {data}") from e


@celery.task(name='tasks.semantic_group', bind=True, acks_late=True)
def semantic_group(self, data: Dict[str, Any]):
    logger.info(f"============= start task {self.request.id} ===================")
    
    logger.info(f"====== semantic_group task, data = {data}")

    try:
        operation = data.get('operation')

        descriptor = data.get('descriptor', {})

        collection_name = generate_collection_name(descriptor)

        if operation == "AddOrUpdate":
            if not descriptor:
                raise ValueError("Missing necessary input fields to AddOrUpdate: descriptor")
            
            dd_namespace = descriptor.get('namespace')
            dd_name = descriptor.get('name')
            
            if not all([dd_namespace, dd_name]):
                raise ValueError("Missing necessary fields in descriptor: namespace, name")

            incremental_semantic_group_result = incremental_semantic_group(descriptor)
            
            # 检查返回结果，如果是 error 状态，抛出异常
            if isinstance(incremental_semantic_group_result, dict):
                status = incremental_semantic_group_result.get('status')
                if status == "error":
                    error_message = incremental_semantic_group_result.get('message', '添加/更新语义域失败')
                    logger.error(f"Failed to add/update semantic domain for {dd_namespace}/{dd_name}: {error_message}")
                    raise ValueError(f"添加/更新语义域失败: {error_message}")
            
            logger.info(f"Successfully incremental semantic domain for {dd_namespace}/{dd_name}, result: {incremental_semantic_group_result}")

        if operation == "Delete":
            if not descriptor:
                raise ValueError("Missing necessary input fields to Delete: descriptor")
            
            dd_namespace = descriptor.get('namespace')
            dd_name = descriptor.get('name')
            
            if not all([dd_namespace, dd_name]):
                raise ValueError("Missing necessary fields in descriptor: namespace, name")

            decremental_semantic_group_result = decremental_semantic_group(descriptor)
            
            # 检查返回结果，如果是 error 状态，抛出异常
            if isinstance(decremental_semantic_group_result, dict):
                status = decremental_semantic_group_result.get('status')
                if status == "error":
                    error_message = decremental_semantic_group_result.get('message', '删除语义域失败')
                    logger.error(f"Failed to delete semantic domain for {dd_namespace}/{dd_name}: {error_message}")
                    raise ValueError(f"删除语义域失败: {error_message}")
            
            logger.info(f"Successfully decremental semantic domain for {dd_namespace}/{dd_name}, result: {decremental_semantic_group_result}")

            # 语义分组结束之后，再将被删除的dd的语义域删除，因为再重组的过程中可能需要这个dd的语义域的信息
            semantic_domain_result = send_delete_semantic_domain(dd_namespace=dd_namespace, dd_name=dd_name)
            logger.info(f"Successfully sent delete semantic domain request for {dd_namespace}/{dd_name} to semantic domain database")
            
            
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}", exc_info=True)
        raise ValueError(f"semantic_group fail: {data}, error={str(e)}") from e

