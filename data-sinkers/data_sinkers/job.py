import time
import os
import json
from data_sinkers import get_reader
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from enum import Enum
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
from .client.semantic_grouper_client import SemanticGrouperClient
from .api.base import DocumentModel
from .extractors.mysql import extract_mysql
from .extractors.postgres import extract_postgres
from .extractors.code import extract_code
from .extractors.minio import extract_minio
from .extractors.fileserver import extract_fileserver
from .extractors.knowledge_graph import Knowledge_Graph
from .fingerprint.fingerprint import FingerprintBuilder, get_remote_commit_sha

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_sinkers")

provider = os.getenv('PROVIDER', 'openai_compatible')
api_key = os.getenv('API_KEY', '')
base_url = os.getenv('BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
model = os.getenv('Model', 'qwen3-32b')
temperature = float(os.getenv('Temperature', '0.01'))

enable_allinone = os.getenv('ENABLE_ALLINONE', 'disable')
enable_sample_data = os.getenv('ENABLE_SAMPLE_DATA', 'disable')

# data services
data_services_url = os.getenv('DATA_SERVICES', 'http://localhost:8000')

data_descriptor = os.getenv('DATA_DESCRIPTOR')
if not data_descriptor:
    raise ValueError("DATA_DESCRIPTOR environment variable is not set")

logger.info(f"data_descriptor = {data_descriptor}")

class DataSourceType(str, Enum):
    MYSQL = "mysql"
    MINIO = "minio"
    POSTGRESQL = "postgres"
    FILESERVER = "fileserver"
    GITHUB = "github"
    GITEE = "gitee"
    GITLAB = "gitlab"

class DataSourceConfig(BaseModel):
    type: DataSourceType
    name: str
    metadata: Dict[str, Any]
    authentication_ref: Optional[str] = Field(None, alias="authenticationRef")
    extract: Dict[str, Any]
    processing: Optional[Dict[str, Any]] = None
    classification: Optional[Dict[str, Any]] = None

def get_connection_config(source_type: DataSourceType, metadata: Dict[str, Any]) -> Dict[str, Any]:
    config_map = {
        DataSourceType.MYSQL: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 3306),
            "user": metadata.get("user", "root"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", ""),
        },
        DataSourceType.POSTGRESQL: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 5432),
            "user": metadata.get("user", "postgres"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", "postgres"),
        },
        DataSourceType.MINIO: {
            "host": metadata.get("host", "localhost:9000"),
            "access_key": metadata.get("access_key", ""),
            "secret_key": metadata.get("secret_key", ""),
            "bucket": metadata.get("bucket", ""),
            "secure": metadata.get("secure", False),
        },
        DataSourceType.FILESERVER: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 8000),
        },
        DataSourceType.GITHUB: {
            "codeRepoPath": metadata.get("codeRepoPath", "https://github.com/octocat/Hello-World"),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        },
        DataSourceType.GITEE: {
            "codeRepoPath": metadata.get("codeRepoPath", "https://github.com/octocat/Hello-World"),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        },
        DataSourceType.GITLAB: {
            "codeRepoPath": metadata.get("codeRepoPath", "https://gitlab.com/octocat/Hello-World"),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        }
    }
    return config_map.get(source_type, {})


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

# build semantic grouper client to call the semantic-grouper service
semantic_grouper_client = SemanticGrouperClient()

knowledgeGraphClient = KnowledgeGraphClient(base_url=data_services_url, timeout=600)

#build codebase indexer client to send codebase index to data-services
codebase_indexer_client = CodebaseIndexerClient(base_url=data_services_url, timeout=600)

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

        logger.info(f"data_descriptor = {data_descriptor}, collection_name = {collection_name}")

        if data_descriptor != collection_name:
            raise ValueError("only matching data descriptor can be processed.")

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
        
        connection_config = get_connection_config(
            source_type, 
            source_data.get('metadata', {})
        )
        
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

            # AddOrUpdate re-sync: delete existing data before create to avoid duplicates.
            # semantic_domain uses update-if-exists (handled in send_add_semantic_domain).
            dd_namespace = descriptor.get('namespace')
            dd_name = descriptor.get('name')
            try:
                signature_client.delete_signatures_by_dd_info(dd_namespace, dd_name)
                knowledge_pyramid_client.delete_collection(collection_name)
                send_delete_knowledge_graph(collection_name)
                if source_type in [DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB]:
                    codebase_indexer_client.delete_codebase_indexers_by_dd_info(dd_namespace, dd_name)
                logger.info(
                    "[data-sinker] feature=add_or_update_preclear Cleared signature/pyramid/graph/codebase_indexer "
                    "for AddOrUpdate re-sync dd=%s/%s",
                    dd_namespace,
                    dd_name,
                )
            except Exception as clear_err:
                logger.warning(
                    "[data-sinker] feature=add_or_update_preclear Non-fatal error during pre-clear dd=%s/%s: %s",
                    dd_namespace,
                    dd_name,
                    clear_err,
                )

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

    if data_type == DataSourceType.MYSQL:
        fingerprint_summary = fingerprintBuilder.generate_db_fingerprint_summary(
            data_type, fingerprint_associated_info["tables_schema_md_list"]
        )
    elif data_type == DataSourceType.POSTGRESQL:
        fingerprint_summary = fingerprintBuilder.generate_db_fingerprint_summary(
            data_type, fingerprint_associated_info["tables_schema_md_list"]
        )
    elif data_type in (DataSourceType.GITHUB, DataSourceType.GITEE, DataSourceType.GITLAB):
        repo_url = connection_config.get("codeRepoPath") or ""
        branch = connection_config.get("codeRepoBranch") or "main"
        token = connection_config.get("token") or connection_config.get("codeRepoToken") or ""
        commit_sha = get_remote_commit_sha(repo_url, branch, token or None)
        fingerprint_summary = fingerprintBuilder.generate_code_fingerprint_summary(
            data_type, connection_config, commit_sha
        )
    elif data_type == DataSourceType.MINIO:
        obj_hash = fingerprint_associated_info.get("object_list_hash")
        fingerprint_summary = fingerprintBuilder.generate_object_list_fingerprint_summary(
            data_type, connection_config, obj_hash
        )
    elif data_type == DataSourceType.FILESERVER:
        obj_hash = fingerprint_associated_info.get("object_list_hash")
        fingerprint_summary = fingerprintBuilder.generate_object_list_fingerprint_summary(
            data_type, connection_config, obj_hash
        )

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

    signature = SignatureData(
        sig_type=sig_type,
        discovery_mode="auto",  # Default to auto discovery mode
        fingerprint=fingerprint_id,
        location_info=location_info,
        metadata_content=metadata_content,
        dd_namespace=descriptor.get('namespace'),
        dd_name=descriptor.get('name')
    )

    logger.info(
        "[data-sinker] feature=write_signature Creating signature in data-services dd=%s/%s data_type=%s fingerprint_id=%s",
        descriptor.get("namespace"),
        descriptor.get("name"),
        getattr(data_type, "value", str(data_type)),
        fingerprint_id,
    )

    try:
        result = signature_client.create_signature(signature)
        logger.debug(f"create signature: {result}")

        return result
    except Exception as e:
        logger.error(f"create signature fail: {str(e)}", exc_info=True)
        raise


def _coerce_semantic_domain_text(fingerprint_associated_info: Dict[str, Any]) -> Optional[str]:
    """
    Normalize the DDD text sent to data-services as semantic_domain.

    - ``ddd`` should be a string; postgres historically set it to a dict (full ddd result).
    - If ``ddd`` is missing/empty but ``db_ddd`` / ``code_ddd`` exist, use those so PUT
      includes semantic_domain (otherwise the API omits the field and the DB keeps the old value).
    """
    raw = fingerprint_associated_info.get("ddd")
    if isinstance(raw, dict):
        raw = raw.get("summary")
    if raw is not None:
        s = raw if isinstance(raw, str) else str(raw)
        if s.strip():
            return s
    for key in ("db_ddd", "code_ddd"):
        fb = fingerprint_associated_info.get(key)
        if fb is not None:
            s = fb if isinstance(fb, str) else str(fb)
            if s.strip():
                return s
    return None


def send_add_semantic_domain(descriptor, fingerprint_associated_info):
    """
    Create or update semantic domain record in data-services.
    Update-if-exists: when re-sync, update existing record (semantic_domain, agent_card, version)
    to avoid relationship disruption (dd_group_relation references semantic_domain_id).
    """
    agent_card = json.dumps(fingerprint_associated_info.get("agent_card", {}), ensure_ascii=False, indent=4)
    semantic_domain_text = _coerce_semantic_domain_text(fingerprint_associated_info)
    if semantic_domain_text is None:
        logger.warning(
            "send_add_semantic_domain: no non-empty ddd/db_ddd/code_ddd; "
            "semantic_domain will be omitted on PUT and data-services will keep the previous value"
        )

    # 从环境变量中获取 DataDescriptor CRD 的 descriptorType（由 dd.go 设置）
    descriptor_type = os.environ.get("DESCRIPTOR_TYPE", "")
    dd_namespace = descriptor.get('namespace')
    dd_name = descriptor.get('name')

    try:
        existing = semantic_domain_client.search_semantic_domains_by_dd(dd_namespace, dd_name)
        domains = existing.get("data") or []
        count = existing.get("count", 0) or len(domains)

        if count > 0 and domains:
            # Update existing: take the first (most recent by created_at DESC)
            to_update = domains[0] if isinstance(domains[0], dict) else domains[0].model_dump()
            sd_id = to_update.get("semantic_domain_id")
            current_version = to_update.get("version") or "0"
            try:
                new_version = str(int(current_version) + 1)
            except (ValueError, TypeError):
                new_version = "1"

            update_data = SemanticDomainData(
                semantic_domain=semantic_domain_text,
                agent_card=agent_card,
                dd_namespace=dd_namespace,
                dd_name=dd_name,
                descriptor_type=descriptor_type if descriptor_type else None,
                version=new_version
            )
            result = semantic_domain_client.update_semantic_domain(sd_id, update_data)
            logger.info(f"send_add_semantic_domain: updated existing semantic_domain {sd_id}, version={new_version}")

            # If multiple records exist (legacy), delete the stale ones
            for extra in domains[1:]:
                extra_id = extra.get("semantic_domain_id") if isinstance(extra, dict) else getattr(extra, "semantic_domain_id", None)
                if extra_id and extra_id != sd_id:
                    try:
                        semantic_domain_client.delete_semantic_domain(extra_id)
                        logger.info(f"send_add_semantic_domain: deleted stale semantic_domain {extra_id}")
                    except Exception as del_err:
                        logger.warning(f"send_add_semantic_domain: failed to delete stale {extra_id}: {del_err}")

            return result
        else:
            # Create new
            semantic_domain = SemanticDomainData(
                semantic_domain=semantic_domain_text,
                agent_card=agent_card,
                dd_namespace=dd_namespace,
                dd_name=dd_name,
                descriptor_type=descriptor_type if descriptor_type else None,
                version="1"
            )
            logger.info(f"send_add_semantic_domain: creating new semantic_domain")
            result = semantic_domain_client.create_semantic_domain(semantic_domain)
            logger.debug(f"create semantic domain: {result}")
            return result
    except Exception as e:
        logger.error(f"create/update semantic domain fail: {str(e)}", exc_info=True)
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

        semantic_domain_text = _coerce_semantic_domain_text(fingerprint_associated_info)

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
    Process codebase_index_result and send to data-services via batch interface.
    
    Args:
        codebase_index_result: List of dicts containing analysis results from code extractor
            Each dict has: filepath, status, analysis_result, error
        descriptor: Descriptor containing namespace and name
        
    Returns:
        API response result from batch create
    """
    try:
        dd_namespace = descriptor.get('namespace')
        dd_name = descriptor.get('name')
        
        # Filter successful results and convert to CodebaseIndexerData
        codebase_indexer_data_list = []
        for item in codebase_index_result:
            if item.get('status') != 'success':
                logger.debug(f"Skipping non-success item: {item.get('file_path')} with status {item.get('status')}")
                continue
            
            analysis_result = item.get('analysis_result', {})
            # Convert analysis_result to JSON string if it's a dict
            if isinstance(analysis_result, dict):
                analysis_result_json = json.dumps(analysis_result, ensure_ascii=False)
            else:
                analysis_result_json = str(analysis_result)
            
            codebase_data = CodebaseIndexerData(
                filepath=item.get('file_path', ''),
                code_deep_analysis=analysis_result_json,
                dd_namespace=dd_namespace,
                dd_name=dd_name
            )
            codebase_indexer_data_list.append(codebase_data)
        
        if not codebase_indexer_data_list:
            logger.info("No successful codebase index results to send")
            return {"status": "success", "message": "No data to send"}
        
        logger.info(f"Sending {len(codebase_indexer_data_list)} codebase indexer records to data-services")
        
        result = codebase_indexer_client.batch_create_codebase_indexers(codebase_indexer_data_list)
        logger.info(f"Batch create codebase indexer result: {result}")
        
        return result
    except Exception as e:
        logger.error(f"send codebase index to dataservices fail: {str(e)}", exc_info=True)
        raise

def send_delete_codebase_index(dd_namespace: str, dd_name: str) -> Dict[str, Any]:
    """
    Delete codebase indexer records by DD information.
    
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
    """
    Delegate semantic group operations to the semantic-grouper service.

    The semantic-grouper service handles distributed locking and sequential
    execution internally, so concurrent calls from multiple data-sinker pods
    are safe.
    
    Args:
        data: Dictionary containing 'operation' and 'descriptor'
    """
    operation = data.get('operation')
    descriptor = data.get('descriptor', {})

    if not descriptor:
        raise ValueError("Missing necessary input fields to add/delete: descriptor")
            
    dd_namespace = descriptor.get('namespace')
    dd_name = descriptor.get('name')
            
    if not all([dd_namespace, dd_name]):
        raise ValueError("Missing necessary fields in descriptor: namespace, name")
    
    logger.info(f"============= start semantic_group_event {operation} ===================")
    logger.info(f"====== semantic_group_event, data = {data}")

    try:
        collection_name = generate_collection_name(descriptor)

        logger.info(f"data_descriptor = {data_descriptor}, collection_name = {collection_name}")

        if data_descriptor != collection_name:
            raise ValueError("only matching data descriptor can be processed.")

        result = semantic_grouper_client.group(
            operation=operation,
            descriptor={"namespace": dd_namespace, "name": dd_name}
        )
        logger.info(f"Successfully completed semantic group event for {dd_namespace}/{dd_name}, operation: {operation}, result: {result}")
            
    except Exception as e:
        logger.error(f"Semantic group event execution failed: {str(e)}, operation: {operation} for {dd_namespace}/{dd_name}", exc_info=True)
        raise ValueError(f"semantic_group_event fail: {data}, error={str(e)}") from e


class ProcessDataWrapper:
    """Wrapper class to make process_data callable as a method"""
    def __init__(self, task_id: str = "main-task"):
        # Create a mock request object with id attribute
        self.request = type('Request', (), {'id': task_id})()

    def process_data(self, data: Dict[str, Any]):
        """Wrapper method that calls the module-level process_data function"""
        return process_data(self, data)


def write_status(status: str, task_id: str, error: Optional[str] = None, result: Optional[Dict[str, Any]] = None):
    """
    Write execution status to /app/status/status.json file.
    
    Args:
        status: Status of execution ('success' or 'failure')
        task_id: Task ID
        error: Error message if status is 'failure'
        result: Result data if status is 'success'
    """
    status_file = '/app/status/status.json'
    status_data = {
        'status': status,
        'task_id': task_id,
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    if status == 'success' and result is not None:
        status_data['result'] = {
            'descriptor': result.get('descriptor'),
            'task_id': result.get('task_id'),
            'metadata': result.get('metadata'),
        }
        # Include data count if available
        if 'data' in result:
            status_data['result']['data_count'] = len(result.get('data', []))
    elif status == 'failure' and error:
        status_data['error'] = str(error)
    
    # Print complete status_data information
    logger.info(f"Status data (complete): {json.dumps(status_data, ensure_ascii=False, indent=2)}")
    
    try:
        # Ensure directory exists and is readable by other containers (e.g. status service)
        status_dir = os.path.dirname(status_file)
        os.makedirs(status_dir, exist_ok=True)
        try:
            os.chmod(status_dir, 0o755)
        except OSError as e:
            logger.warning(f"Could not chmod status dir {status_dir}: {e}")

        # Write status to file
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)

        # Make file readable by other containers (e.g. status service)
        try:
            os.chmod(status_file, 0o644)
        except OSError as e:
            logger.warning(f"Could not chmod status file {status_file}: {e}")

        logger.info(f"Status written to {status_file}: {status}")
    except Exception as e:
        logger.error(f"Failed to write status to {status_file}: {str(e)}", exc_info=True)
        # Don't raise exception here, as status writing failure shouldn't stop the main process


def main():
    """
    Main entry point for running process_data directly.
    Reads a JSON file from /app/data.json and passes it to process_data method.
    
    Usage:
        python -m data_sinkers.job
        python -m data_sinkers.job --task-id <task_id>
    """
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='Process data from JSON file')
    parser.add_argument('--task-id', type=str, default='main-task', help='Task ID for logging (default: main-task)')
    
    args = parser.parse_args()
    task_id = args.task_id
    
    # Read JSON file - fixed path
    json_file_path = '/app/data.json'
    if not os.path.exists(json_file_path):
        error_msg = f"JSON file not found: {json_file_path}"
        logger.error(error_msg)
        write_status('failure', task_id, error=error_msg)
        # Sleep for a long time to keep container running
        logger.info("Job completed (failed), sleeping to keep container alive...")
        time.sleep(86400 * 365)  # Sleep for 1 year (effectively forever)
        sys.exit(1)
    
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Successfully loaded JSON file: {json_file_path}")
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse JSON file: {json_file_path}, error: {str(e)}"
        logger.error(error_msg)
        write_status('failure', task_id, error=error_msg)
        # Sleep for a long time to keep container running
        logger.info("Job completed (failed), sleeping to keep container alive...")
        time.sleep(86400 * 365)  # Sleep for 1 year (effectively forever)
        sys.exit(1)
    except Exception as e:
        error_msg = f"Failed to read JSON file: {json_file_path}, error: {str(e)}"
        logger.error(error_msg)
        write_status('failure', task_id, error=error_msg)
        # Sleep for a long time to keep container running
        logger.info("Job completed (failed), sleeping to keep container alive...")
        time.sleep(86400 * 365)  # Sleep for 1 year (effectively forever)
        sys.exit(1)
    
    # Create wrapper instance and call process_data
    wrapper = ProcessDataWrapper(task_id=task_id)
    
    # Call process_data with the loaded data
    try:
        result = wrapper.process_data(data)
        logger.info(f"Process completed successfully: {result}")
        
        # Write success status
        write_status('success', task_id, result=result)
        
        # Sleep for a long time to keep container running after job completion
        logger.info("Job completed successfully, sleeping to keep container alive...")
        time.sleep(86400 * 365)  # Sleep for 1 year (effectively forever)
        
        return result
    except Exception as e:
        error_msg = f"Process failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Write failure status
        write_status('failure', task_id, error=error_msg)
        
        # Sleep for a long time to keep container running after job failure
        logger.info("Job completed (failed), sleeping to keep container alive...")
        time.sleep(86400 * 365)  # Sleep for 1 year (effectively forever)
        
        sys.exit(1)


if __name__ == "__main__":
    main()
