import os
import logging
from typing import List, Dict, Any, Optional
from model_sdk import ModelManager
from vector_sdk import Vector, Document, CacheEmbedding
from ..api.base import DocumentModel, SearchType
from datetime import datetime
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VectorService:
    def __init__(self):
        self.config = None
        self.model_manager = None
        self.embedding_model = None
        self.vector_instances = {}

    async def initialize(self, config: Optional[Dict[str, Any]] = None):
        self.config = config
        provider = os.getenv('EMBEDDING_PROVIDER')
        model = os.getenv('EMBEDDING_MODEL')
        api_key = os.getenv('EMBEDDING_API_KEY')
        
        if not api_key:
            raise ValueError("EMBEDDING_API_KEY environment variable is required")
        
        try:
            self.model_manager = ModelManager()
            
            if provider == 'azure':
                self.embedding_model = self.model_manager.get_embedding(
                    provider=provider,
                    model=model,
                    azure_endpoint=os.getenv('AZURE_ENDPOINT'),
                    api_key=api_key,
                    deployment=os.getenv('EMBEDDING_DEPLOYMENT'),
                    api_version=os.getenv('API_VERSION', '2023-05-15')
                )
            elif provider == 'dashscope':
                self.embedding_model = self.model_manager.get_embedding(
                    provider=provider,
                    model=model,
                    dashscope_api_key=api_key
                )
            else:
                self.embedding_model = self.model_manager.get_embedding(
                    provider=provider,
                    model=model,
                    base_url=os.getenv('EMBEDDING_BASE_URL'),
                    api_key=api_key
                )
        except Exception as e:
            logger.error(f"Failed to initialize services: {str(e)}")
            raise

        logger.info("Vector Service initialized successfully")

    def get_vector_instance(self, collection_name: str) -> Vector:
        if collection_name not in self.vector_instances:
            embedding = CacheEmbedding(self.embedding_model) if self.embedding_model else None
            self.vector_instances[collection_name] = Vector(
                collection_name=collection_name,
                embedding=embedding
            )
            logger.info(f"Created new Vector instance for collection: {collection_name}")
        
        return self.vector_instances[collection_name]

    # create collection
    async def create_collection_with_vector(self, collection_name: str, documents: List[Document]) -> Dict[str, Any]:
        vector = self.get_vector_instance(collection_name)

        try:
            exist = await vector.acollection_exists()
            if exist:
                logger.info(f"Collection {collection_name} exist already")
            else:
                await vector.acreate(texts=documents)
                logger.info(f"Collection {collection_name} created successfully")

        except Exception as e:
            logger.error(f"Error collection create: {str(e)}")
            raise

        return {
            "status": "success",
            "message": f"Collection {collection_name} created successfully or exist already"
        }

    # delete collection
    async def delete_collection_with_vector(self, collection_name: str) -> Dict[str, Any]:
        vector = self.get_vector_instance(collection_name)
        try:
            exist = await vector.acollection_exists()
            if exist:
                await vector.adelete()
                logger.info(f"Collection {collection_name} exist, delete successfully")
            else:
                logger.info(f"Collection {collection_name} not exist, there is no need to execute delete operation")
            
            if collection_name in self.vector_instances:
                if hasattr(self.vector_instances[collection_name], 'close'):
                    await self.vector_instances[collection_name].close()
                del self.vector_instances[collection_name]
        
        except Exception as e:
            logger.error(f"Error in delete_collection: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

        return {
            "status": "success",
            "message": f"Collection '{collection_name}' deleted successfully"
        }

    # add documents
    async def add_documents_with_vector(self, collection_name: str, documents: List[DocumentModel]) -> Dict[str, Any]:
        vector = self.get_vector_instance(collection_name)
        documents = [
            Document(
                page_content=doc.page_content,
                metadata=doc.metadata
            ) for doc in documents
        ]
        
        document_ids = await vector.aadd_texts(
            documents=documents
        )
        
        return {
            "status": "success",
            "message": "Document added successfully",
            "results": document_ids,

        }

    def hybrid_merge_with_weights(self, vector_results, fulltext_results, vector_weight=0.7, fulltext_weight=0.3, hybrid_threshold: Optional[float] = None):

        all_results = []
        
        for result in vector_results:
            new_result = result.copy()
            new_result['hybrid_score'] = result['score'] * vector_weight
            new_result['search_type'] = 'vector'
            if hybrid_threshold is None or new_result['hybrid_score'] >= hybrid_threshold:
                all_results.append(new_result)
        
        for result in fulltext_results:
            new_result = result.copy()
            new_result['hybrid_score'] = result['score'] * fulltext_weight
            new_result['search_type'] = 'fulltext'

            logger.info(f"new_result['hybrid_score'] = {new_result['hybrid_score']}, hybrid_threshold={hybrid_threshold}")

            if hybrid_threshold is None or new_result['hybrid_score'] >= hybrid_threshold:
                all_results.append(new_result)

        return sorted(all_results, key=lambda x: x['hybrid_score'], reverse=True)

    # search documents
    async def search_documents_with_vector(self, query: str, collection_name: str, search_type: str, limit: int = 10, hybrid_threshold: Optional[float] = 0.01, vector_weight: Optional[float] = 0.7, fulltext_weight:Optional[float] = 0.3) -> Dict[str, Any]:
        vector = self.get_vector_instance(collection_name)
        vector_sorted_results = []
        try:
            if search_type == SearchType.VECTOR:
                results = await vector.asearch_by_vector(
                    query=query,
                    top_k=limit,
                    score_threshold=hybrid_threshold
                )

                vector_results = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": float(doc.metadata.get('score', 0)),
                        "search_type": search_type,
                        "hybrid_score": 0.0
                    } for doc in results
                ]

                vector_sorted_results = sorted(
                    vector_results, 
                    key=lambda x: x['score'], 
                    reverse=True
                )

            elif search_type == SearchType.FULLTEXT:
                results = await vector.asearch_by_full_text(
                    query=query,
                    top_k=limit
                )

                vector_results = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": float(doc.metadata.get('score', 0)),
                        "search_type": search_type,
                        "hybrid_score": 0.0
                    } for doc in results
                ]

                if hybrid_threshold is not None:
                    filtered_results = [
                        result for result in vector_results 
                        if result['score'] >= hybrid_threshold
                    ]
                else:
                    filtered_results = vector_results
                
                vector_sorted_results = sorted(
                    filtered_results, 
                    key=lambda x: x['score'], 
                    reverse=True
                )
            elif search_type == SearchType.HYBRID:
                results_vector = await vector.asearch_by_vector(
                    query=query,
                    top_k=limit
                )
                results_fulltext = await vector.asearch_by_full_text(
                    query=query,
                    top_k=limit
                )

                vector_results_dict = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": float(doc.metadata.get('score', 0)),
                        "search_type": "vector"
                    } for doc in results_vector
                ]
                
                fulltext_results_dict = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": float(doc.metadata.get('score', 0)),
                        "search_type": "fulltext"
                    } for doc in results_fulltext
                ]
                
                hybrid_results = self.hybrid_merge_with_weights(vector_results_dict, fulltext_results_dict, hybrid_threshold=hybrid_threshold, vector_weight=vector_weight, fulltext_weight=fulltext_weight)
                vector_sorted_results = hybrid_results
                
            else:
                results = []

        except Exception as e:
            logger.error(f"Error searching vector: {str(e)}")
            raise

        return {
            "status": "success",
            "collection": collection_name,
            "search_type": search_type,
            "result": vector_sorted_results
        }

    # delete all documents
    async def delete_all_documents_by_collection_name(self, collection_name: str) -> Dict[str, Any]:
        
        try:
            vector = self.get_vector_instance(collection_name)
            if vector is None:
                logger.error(f"Vector instance for collection '{collection_name}' is None")
                return {
                    "status": "error",
                    "message": f"Vector service not initialized for collection '{collection_name}'",
                    "collection": collection_name
                }

            exist = await vector.acollection_exists()
            if exist:
                await vector.adelete()
            else:
                logger.warn(f"Collection {collection_name} already does not exist")
                return {
                    "status": "success",
                    "message": f"Collection {collection_name} already does not exist",
                    "collection": collection_name
                }
        except Exception as e:
            logger.error(f"Error delete_all_documents_by_collection_name , adelete: {str(e)}")
            raise

        return {
            "status": "success",
            "message": "Documents deleted successfully",
            "collection": collection_name
        }

    # delete for documents
    async def delete_documents_by_ids(self, collection_name: str, documents: List[str]) -> Dict[str, Any]:

        documents_list = list(documents) if documents else []

        logger.info(f"\ndelete_documents_by_ids ,collection_name: {collection_name} ,documents, {documents_list}")

        try:
            vector = self.get_vector_instance(collection_name)
            if vector is None:
                logger.error(f"Vector instance for collection '{collection_name}' is None")
                return {
                    "status": "error",
                    "message": f"Vector service not initialized for collection '{collection_name}'",
                    "collection": collection_name
                }
            await vector.adelete_by_ids(ids=documents_list)
        except Exception as e:
            logger.error(f"Error delete_documents_by_ids , adelete_by_ids: {str(e)}")
            raise

        return {
            "status": "success",
            "message": "Documents deleted successfully",
            "collection": collection_name
        }

    async def delete_by_metadata_field(self, collection_name: str, key: str, value: str) -> None:

        logger.info(f"\nadelete_by_metadata_field ,key: {key} ,value, {value}")

        try:
            vector = self.get_vector_instance(collection_name)
            if vector is None:
                logger.error(f"Vector instance for collection '{collection_name}' is None")
                return {
                    "status": "error",
                    "message": f"Vector service not initialized for collection '{collection_name}'",
                    "collection": collection_name
                }
            await vector.adelete_by_metadata_field(key, value)
        except Exception as e:
            logger.error(f"Error delete_by_metadata_field , adelete_by_metadata_field: {str(e)}")
            raise

        return {
            "status": "success",
            "message": "Documents deleted successfully",
            "collection": collection_name,
            "key": key,
            "value": value
        }


