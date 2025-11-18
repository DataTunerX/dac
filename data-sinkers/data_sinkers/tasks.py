import time
import os
from urllib.parse import quote_plus
from celery import Celery
from data_sinkers import get_reader
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from enum import Enum
import logging
import re
from .client.knowledge_pyramid_client import KnowledgePyramidClient
from .client.vector_client import VectorClient
from .client.fingerprint_client import FingerprintClient, FingerprintData
from .analyzers.fingerprint import FingerprintAnalyzer
from .api.base import DocumentModel
from .extractors.mysql import extract_mysql
from .extractors.postgres import extract_postgres
from .extractors.minio import extract_minio
from .extractors.fileserver import extract_fileserver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_sinkers")

# redis config for worker
redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = os.getenv('REDIS_PORT', '6379')
redis_db_broker = os.getenv('REDIS_DB_BROKER', '0')
redis_db_backend = os.getenv('REDIS_DB_BACKEND', '1')
redis_password = os.getenv('REDIS_PASSWORD')

provider = os.getenv('PROVIDER', 'openai_compatible')
api_key = os.getenv('API_KEY', '')
base_url = os.getenv('BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
model = os.getenv('Model', 'qwen3-32b')
temperature = float(os.getenv('Temperature', '0.01'))

enable_allinone = os.getenv('ENABLE_ALLINONE', 'disable')
enable_sample_data = os.getenv('ENABLE_SAMPLE_DATA', 'disable')

fingerprint_analyzer = FingerprintAnalyzer(
    provider=provider,
    api_key=api_key,
    base_url=base_url,
    model=model
)

# data services
data_services_url = os.getenv('DATA_SERVICES')

# URL encode the password if it contains special characters
password_part = f':{quote_plus(redis_password)}@' if redis_password else ''

class DataSourceType(str, Enum):
    MYSQL = "mysql"
    MINIO = "minio"
    POSTGRESQL = "postgres"
    FILESERVER = "fileserver"

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
    },
    task_track_started=True
)

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
        }
    }
    return config_map.get(source_type, {})


#build KnowledgePyramidClient to send documents to data-services
knowledge_pyramid_client = KnowledgePyramidClient(base_url=data_services_url, timeout=600)

#build VectorClient to send fingerprint documents to data-services
vector_client = VectorClient(base_url=data_services_url, timeout=600)

#build fingerprint client to send fingerprint to data-services
fingerprint_client = FingerprintClient(base_url=data_services_url, timeout=600)


@celery.task(name='tasks.process_data', bind=True, acks_late=True)
def process_data(self, data: Dict[str, Any]):
    logger.info(f"============= start task {self.request.id} ===================")
    
    try:
        operation = data.get('operation')
        source_data = data.get('source', {})
        descriptor = data.get('descriptor', {})
        extract = data.get('extract', {})
        prompts = data.get('prompts', {})

        sql_process_mode="dictionary"

        collection_name = generate_collection_name(descriptor)

        logger.info(f"===start task, data={data}===")

        if operation == "Delete":
            try:
                if not all([operation, descriptor]):
                    raise ValueError("Missing necessary input fields to delete the collection: operation, descriptor")

                dd_namespace = descriptor.get('namespace')
                dd_name = descriptor.get('name')
                fingerprint_result = send_delete_fingerprint(client=fingerprint_client, dd_namespace=dd_namespace, dd_name=dd_name)
                logger.info(f"Successfully sent delete fingerprint request {collection_name} to fingerprint database")

                pyramid_result = send_delete_collection_to_knowledge_pyramid(client=knowledge_pyramid_client, collection_name=collection_name)
                logger.info(f"Successfully sent delete collection request {collection_name} to Knowledge Pyramid")
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

        reader = get_reader(source_type.value, connection_config)
        
        result: List[DocumentModel] = []

        try:
            if source_type == DataSourceType.MYSQL:
                result = extract_mysql(reader, descriptor, extract, prompts, fingerprint_analyzer=fingerprint_analyzer, fingerprint_client=fingerprint_client, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data, sql_process_mode=sql_process_mode)
                
            elif source_type == DataSourceType.POSTGRESQL:
                result = extract_postgres(reader, descriptor, extract, prompts, fingerprint_analyzer=fingerprint_analyzer, fingerprint_client=fingerprint_client, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data, sql_process_mode=sql_process_mode)

            elif source_type == DataSourceType.MINIO:
                result = extract_minio(reader, descriptor, extract, prompts, fingerprint_analyzer=fingerprint_analyzer, fingerprint_client=fingerprint_client, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data)

            elif source_type == DataSourceType.FILESERVER:
                result = extract_fileserver(reader, descriptor, extract, prompts, fingerprint_analyzer=fingerprint_analyzer, fingerprint_client=fingerprint_client, enable_allinone=enable_allinone, enable_sample_data=enable_sample_data) 

            logger.info(f"============= process_data extract success, result = {result} ")

            processing = data.get('data', {}).get('processing')
            if processing and result:
                result = apply_processing(result, processing)
            
            serializable_result = [item.dict() for item in result] if result else []

            try:
                pyramid_result = send_add_documents_to_knowledge_pyramid(client=knowledge_pyramid_client, documents=serializable_result, collection_name=collection_name)
                logger.info(f"Successfully sent {len(serializable_result)} documents to Knowledge Pyramid")
            except Exception as e:
                raise ValueError(f"KnowledgePyramidClient to send documents to data-services fail: {data}") from e

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
            reader.close()
            
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}", exc_info=True)
        raise ValueError(f"process_data fail: {data}, error={str(e)}") from e

def apply_processing(data: List[DocumentModel], processing: Dict[str, Any]) ->List[DocumentModel]:

    cleaning_rules = processing.get('cleaning', [])
    for rule in cleaning_rules:
        rule_type = rule.get('rule')
        params = rule.get('params', {})
        
        if rule_type == "remove_duplicates":
            pass
        elif rule_type == "fill_missing":
            pass
    
    return data

def send_add_documents_to_knowledge_pyramid(client: KnowledgePyramidClient, documents: List[Dict[str, Any]], collection_name: str) -> Dict[str, Any]:
    try:
        create_collection_result = client.create_collection(
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

        add_documents_result = client.add_documents(
            collection_name=collection_name,
            documents=document_objects
        )
        logger.info(f"add document success: {add_documents_result}")
        return add_documents_result
    except Exception as e:
        logger.error(f"create collection or add document fail: {str(e)}")
        raise

def send_delete_collection_to_knowledge_pyramid(client: KnowledgePyramidClient, collection_name: str) -> Dict[str, Any]:
    try:
        delete_collection_result = client.delete_collection(
            collection_name=collection_name
        )
        logger.info(f"delete collection: {delete_collection_result}")

        return delete_collection_result
    except Exception as e:
        logger.error(f"delete collection fail: {str(e)}")
        raise

def send_delete_fingerprint(client: FingerprintClient, dd_namespace: str ,dd_name: str) -> Dict[str, Any]:
    try:
        result = client.delete_fingerprints_by_dd_info(
            dd_namespace=dd_namespace,
            dd_name=dd_name

        )
        logger.info(f"delete fingerprint: {result}")

        return result
    except Exception as e:
        logger.error(f"delete fingerprint fail: {str(e)}")
        raise

def _is_valid_table_name(self, table_name: str) -> bool:
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