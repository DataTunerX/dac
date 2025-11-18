from abc import ABC, abstractmethod
from typing import Any, Optional
import os
import logging
from .vector_base import BaseVector
from .vector_type import VectorType
from langchain_core.embeddings import Embeddings
from .base import Document


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)

class AbstractVectorFactory(ABC):
    @abstractmethod
    def init_vector(self, collection_name: str, attributes: list, embeddings: Embeddings) -> BaseVector:
        raise NotImplementedError

    @staticmethod
    def gen_index_struct_dict(vector_type: VectorType, collection_name: str) -> dict:
        index_struct_dict = {"type": vector_type, "vector_store": {"class_prefix": collection_name}}
        return index_struct_dict


class Vector:
    def __init__(self, collection_name: str, embedding: Embeddings, attributes: Optional[list] = None):
        if attributes is None:
            attributes = ["doc_id", "document_id", "doc_hash"]
        self._collection_name = collection_name
        self._embeddings = embedding
        self._attributes = attributes
        self._vector_processor = self._init_vector()

    def _init_vector(self) -> BaseVector:
        vector_type = os.getenv("VECTOR_STORE", "pgvector")

        if not vector_type:
            raise ValueError("Vector store must be specified.")

        vector_factory_cls = self.get_vector_factory(vector_type)
        return vector_factory_cls().init_vector(self._collection_name, self._attributes, self._embeddings)

    @staticmethod
    def get_vector_factory(vector_type: str) -> type[AbstractVectorFactory]:
        match vector_type:
            case VectorType.PGVECTOR:
                from .pgvector.pgvector import PGVectorFactory

                return PGVectorFactory
            case _:
                raise ValueError(f"Vector store {vector_type} is not supported.")

    def create(self, texts: Optional[list] = None, **kwargs):
        if texts:
            embeddings = self._embeddings.embed_documents([document.page_content for document in texts])
            self._vector_processor.create(texts=texts, embeddings=embeddings, **kwargs)

    async def acreate(self, texts: Optional[list] = None, **kwargs):
        if texts:
            embeddings = await self._embeddings.aembed_documents([document.page_content for document in texts])
            await self._vector_processor.acreate(texts=texts, embeddings=embeddings, **kwargs)

    def collection_exists(self) -> bool:
        return self._vector_processor.collection_exists()

    async def acollection_exists(self) -> bool:
        return await self._vector_processor.acollection_exists()

    def add_texts(self, documents: list[Document], **kwargs):
        if kwargs.get("duplicate_check", False):
            documents = self._filter_duplicate_texts(documents)

        doc_ids = []
        embeddings = self._embeddings.embed_documents([document.page_content for document in documents])
        doc_ids = self._vector_processor.add_texts(documents=documents, embeddings=embeddings, **kwargs)
        return doc_ids

    async def aadd_texts(self, documents: list[Document], **kwargs):
        if kwargs.get("duplicate_check", False):
            documents = await self._afilter_duplicate_texts(documents)

        doc_ids = []
        embeddings = await self._embeddings.aembed_documents([document.page_content for document in documents])
        doc_ids = await self._vector_processor.aadd_texts(documents=documents, embeddings=embeddings, **kwargs)
        return doc_ids

    def text_exists(self, id: str) -> bool:
        return self._vector_processor.text_exists(id)

    async def atext_exists(self, id: str) -> bool:
        return await self._vector_processor.atext_exists(id)

    def delete_by_ids(self, ids: list[str]) -> None:
        self._vector_processor.delete_by_ids(ids)

    async def adelete_by_ids(self, ids: list[str]) -> None:
        await self._vector_processor.adelete_by_ids(ids)

    def delete_by_metadata_field(self, key: str, value: str) -> None:
        self._vector_processor.delete_by_metadata_field(key, value)

    async def adelete_by_metadata_field(self, key: str, value: str) -> None:
        await self._vector_processor.adelete_by_metadata_field(key, value)

    def search_by_vector(self, query: str, **kwargs: Any) -> list[Document]:
        query_vector = self._embeddings.embed_query(query)
        return self._vector_processor.search_by_vector(query_vector, **kwargs)

    async def asearch_by_vector(self, query: str, **kwargs: Any) -> list[Document]:
        query_vector = await self._embeddings.aembed_query(query)
        return await self._vector_processor.asearch_by_vector(query_vector, **kwargs)

    def search_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        return self._vector_processor.search_by_full_text(query, **kwargs)

    async def asearch_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        return await self._vector_processor.asearch_by_full_text(query, **kwargs)

    def delete(self) -> None:
        self._vector_processor.delete()

    async def adelete(self) -> None:
        await self._vector_processor.adelete()

    def _filter_duplicate_texts(self, texts: list[Document]) -> list[Document]:
        for text in texts.copy():
            if text.metadata is None:
                continue
            doc_id = text.metadata["doc_id"]
            if doc_id:
                exists_duplicate_node = self.text_exists(doc_id)
                if exists_duplicate_node:
                    texts.remove(text)

        return texts

    async def _afilter_duplicate_texts(self, texts: list[Document]) -> list[Document]:
        for text in texts.copy():
            if text.metadata is None:
                continue
            doc_id = text.metadata["doc_id"]
            if doc_id:
                exists_duplicate_node = self.text_exists(doc_id)  # 注意：这里保持同步调用
                if exists_duplicate_node:
                    texts.remove(text)
        return texts


    def __getattr__(self, name):
        if self._vector_processor is not None:
            method = getattr(self._vector_processor, name)
            if callable(method):
                return method

        raise AttributeError(f"'vector_processor' object has no attribute '{name}'")
