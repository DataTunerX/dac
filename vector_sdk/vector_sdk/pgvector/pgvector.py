import hashlib
import json
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional
import threading
import psycopg2.errors
import psycopg2.extras  # type: ignore
import psycopg2.pool  # type: ignore
from pydantic import BaseModel, model_validator

from ..vector_base import BaseVector
from ..vector_factory import AbstractVectorFactory
from ..vector_type import VectorType
from langchain_core.embeddings import Embeddings
from ..base import Document
from ..configs import vector_config
import asyncpg
from asyncpg.pool import Pool
import asyncio


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class PGVectorConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str
    database: str
    min_connection: int
    max_connection: int
    pg_bigm: bool = False

    @model_validator(mode="before")
    @classmethod
    def validate_config(cls, values: dict) -> dict:
        if not values["host"]:
            raise ValueError("config PGVECTOR_HOST is required")
        if not values["port"]:
            raise ValueError("config PGVECTOR_PORT is required")
        if not values["user"]:
            raise ValueError("config PGVECTOR_USER is required")
        if not values["password"]:
            raise ValueError("config PGVECTOR_PASSWORD is required")
        if not values["database"]:
            raise ValueError("config PGVECTOR_DATABASE is required")
        if not values["min_connection"]:
            raise ValueError("config PGVECTOR_MIN_CONNECTION is required")
        if not values["max_connection"]:
            raise ValueError("config PGVECTOR_MAX_CONNECTION is required")
        if values["min_connection"] > values["max_connection"]:
            raise ValueError("config PGVECTOR_MIN_CONNECTION should less than PGVECTOR_MAX_CONNECTION")
        return values


SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id UUID PRIMARY KEY,
    text TEXT NOT NULL,
    meta JSONB NOT NULL,
    embedding vector({dimension}) NOT NULL
) using heap;
"""

SQL_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS embedding_cosine_v1_idx_{index_hash} ON {table_name}
USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""

SQL_CREATE_INDEX_PG_BIGM = """
CREATE INDEX IF NOT EXISTS bigm_idx_{index_hash} ON {table_name}
USING gin (text gin_bigm_ops);
"""


class PGPoolManager:
    _instance = None
    _lock = threading.Lock()
    _async_lock = asyncio.Lock()
    
    _sync_pools: Dict[str, psycopg2.pool.SimpleConnectionPool] = {}
    _async_pools: Dict[str, Pool] = {}
    
    @classmethod
    def get_sync_pool(cls, config: PGVectorConfig) -> psycopg2.pool.SimpleConnectionPool:
        config_key = f"{config.host}:{config.port}:{config.database}"
        
        with cls._lock:
            if config_key not in cls._sync_pools:
                cls._sync_pools[config_key] = psycopg2.pool.SimpleConnectionPool(
                    config.min_connection,
                    config.max_connection,
                    host=config.host,
                    port=config.port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                )
            return cls._sync_pools[config_key]
    
    @classmethod
    async def get_async_pool(cls, config: PGVectorConfig) -> Pool:
        config_key = f"{config.host}:{config.port}:{config.database}"
        
        async with cls._async_lock:
            if config_key not in cls._async_pools:
                cls._async_pools[config_key] = await asyncpg.create_pool(
                    host=config.host,
                    port=config.port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    min_size=config.min_connection,
                    max_size=config.max_connection
                )
            return cls._async_pools[config_key]
    
    @classmethod
    def close_all(cls):
        with cls._lock:
            for pool in cls._sync_pools.values():
                pool.closeall()
            cls._sync_pools.clear()
        
        async def _close_async_pools():
            async with cls._async_lock:
                for pool in cls._async_pools.values():
                    await pool.close()
                cls._async_pools.clear()
        
        # Run the async close in a new event loop if not already in one
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(_close_async_pools())
        except RuntimeError:
            asyncio.run(_close_async_pools())


class PGVector(BaseVector):
    def __init__(self, collection_name: str, config: PGVectorConfig):
        super().__init__(collection_name)
        self.config = config
        self._sync_pool = PGPoolManager.get_sync_pool(config)
        self._async_pool: Optional[Pool] = None
        self.table_name = f"embedding_{collection_name}"
        self.index_hash = hashlib.md5(self.table_name.encode()).hexdigest()[:8]
        self.pg_bigm = config.pg_bigm
        self._async_pool_lock = asyncio.Lock()


    def get_type(self) -> str:
        return VectorType.PGVECTOR


    # new
    async def _ensure_async_pool(self):
        if self._async_pool is None:
            async with self._async_pool_lock:
                if self._async_pool is None:
                    self._async_pool = await PGPoolManager.get_async_pool(self.config)

    # new
    async def _get_async_connection(self):
        await self._ensure_async_pool()
        if self._async_pool is None:
            raise RuntimeError("Async connection pool not initialized")
        return await self._async_pool.acquire()


    # new
    async def close(self):
        # Individual PGVector instances don't close the pools - managed by PGPoolManager
        pass


    @contextmanager
    def _get_cursor(self):
        conn = self._sync_pool.getconn()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
            conn.commit()
            self._sync_pool.putconn(conn)


    def create(self, texts: list[Document], embeddings: list[list[float]], **kwargs):
        dimension = len(embeddings[0])
        self._create_collection(dimension)

    async def acreate(self, texts: list[Document], embeddings: list[list[float]], **kwargs):
        dimension = len(embeddings[0])
        await self._acreate_collection(dimension)

    def collection_exists(self) -> bool:
        """检查表是否存在"""
        try:
            with self._get_cursor() as cur:
                table_name_lower = self.table_name.lower()
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE tablename = %s AND schemaname = 'public')",
                    (table_name_lower,)
                )
                return cur.fetchone()[0]
        except Exception as e:
            logger.warning(f"Error checking if table exists: {e}")
            return False

    async def acollection_exists(self) -> bool:
        """异步检查表是否存在"""
        try:
            conn = await self._get_async_connection()
            table_name_lower = self.table_name.lower()
            try:
                result = await conn.fetchrow(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE tablename = $1 AND schemaname = 'public')",
                    table_name_lower
                )
                return result[0] if result else False
            finally:
                await conn.close()
        except Exception as e:
            logger.warning(f"Error checking if table exists: {e}")
            return False

    def add_texts(self, documents: list[Document], embeddings: list[list[float]], **kwargs):
        values = []
        pks = []
        for i, doc in enumerate(documents):
            if doc.metadata is not None:
                # Get or generate doc_id
                doc_id = doc.metadata.get("doc_id")
                if doc_id:
                    try:
                        # Convert to UUID object if it's a string
                        if isinstance(doc_id, str):
                            doc_id = uuid.UUID(doc_id)
                    except (ValueError, AttributeError):
                        # If conversion fails, generate a new UUID
                        doc_id = uuid.uuid4()
                else:
                    doc_id = uuid.uuid4()
                    
                pks.append(str(doc_id))
                values.append(
                    (
                        str(doc_id),  # Convert UUID to string before sending to PostgreSQL
                        doc.page_content,
                        json.dumps(doc.metadata),
                        embeddings[i],
                    )
                )
        with self._get_cursor() as cur:
            psycopg2.extras.execute_values(
                cur, 
                f"INSERT INTO {self.table_name} (id, text, meta, embedding) VALUES %s", 
                values
            )
        return pks


    # new
    async def aadd_texts(self, documents: list[Document], embeddings: list[list[float]], **kwargs):
        values = []
        pks = []
        for i, doc in enumerate(documents):
            if doc.metadata is not None:
                # Get or generate doc_id
                doc_id = doc.metadata.get("doc_id")
                if doc_id:
                    try:
                        # Convert to UUID object if it's a string
                        if isinstance(doc_id, str):
                            doc_id = uuid.UUID(doc_id)
                    except (ValueError, AttributeError):
                        # If conversion fails, generate a new UUID
                        doc_id = uuid.uuid4()
                else:
                    doc_id = uuid.uuid4()
                
                pks.append(str(doc_id))
                # Convert embedding list to string format expected by pgvector
                embedding_str = "[" + ",".join(map(str, embeddings[i])) + "]"
                values.append(
                    (
                        str(doc_id),  # Convert UUID to string
                        doc.page_content,
                        json.dumps(doc.metadata),
                        embedding_str,  # Use string format
                    )
                )
        
        conn = await self._get_async_connection()
        try:
            await conn.executemany(
                f"INSERT INTO {self.table_name} (id, text, meta, embedding) VALUES ($1, $2, $3, $4::vector)",
                values
            )
        finally:
            await conn.close()
        return pks


    def text_exists(self, id: str) -> bool:
        try:
            # Convert string to UUID if needed
            doc_id = uuid.UUID(id) if not isinstance(id, uuid.UUID) else id
        except (ValueError, AttributeError):
            # If invalid UUID format, document can't exist
            return False
            
        with self._get_cursor() as cur:
            cur.execute(
                f"SELECT id FROM {self.table_name} WHERE id = %s",
                (str(doc_id),)  # Convert to string for PostgreSQL
            )
            return cur.fetchone() is not None


    # new
    async def atext_exists(self, id: str) -> bool:
        try:
            # Convert string to UUID if needed
            doc_id = uuid.UUID(id) if not isinstance(id, uuid.UUID) else id
        except (ValueError, AttributeError):
            # If invalid UUID format, document can't exist
            return False
            
        conn = await self._get_async_connection()
        try:
            result = await conn.fetchrow(
                f"SELECT id FROM {self.table_name} WHERE id = $1",
                str(doc_id)  # Convert to string for PostgreSQL
            )
            return result is not None
        except asyncpg.UndefinedTableError:
            # If table doesn't exist, document definitely doesn't exist
            return False
        finally:
            await conn.close()


    def get_by_ids(self, ids: list[str]) -> list[Document]:
        with self._get_cursor() as cur:
            cur.execute(f"SELECT meta, text FROM {self.table_name} WHERE id IN %s", (tuple(ids),))
            docs = []
            for record in cur:
                docs.append(Document(page_content=record[1], metadata=record[0]))
        return docs


    # new
    async def aget_by_ids(self, ids: list[str]) -> list[Document]:
        conn = await self._get_async_connection()
        try:
            records = await conn.fetch(
                f"SELECT meta, text FROM {self.table_name} WHERE id = ANY($1::uuid[])",
                ids
            )
            docs = []
            for record in records:
                docs.append(Document(page_content=record[1], metadata=record[0]))
            return docs
        finally:
            await conn.close()


    def delete_by_ids(self, ids: list[str]) -> None:
        # Avoiding crashes caused by performing delete operations on empty lists in certain scenarios
        # Scenario 1: extract a document fails, resulting in a table not being created.
        # Then clicking the retry button triggers a delete operation on an empty list.
        if not ids:
            return
        with self._get_cursor() as cur:
            try:
                cur.execute(f"DELETE FROM {self.table_name} WHERE id IN %s", (tuple(ids),))
            except psycopg2.errors.UndefinedTable:
                # table not exists
                logging.warning(f"Table {self.table_name} not found, skipping delete operation.")
                return
            except Exception as e:
                raise e

    # new
    async def adelete_by_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        conn = await self._get_async_connection()
        try:
            try:
                await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE id = ANY($1::uuid[])",
                    ids
                )
            except asyncpg.UndefinedTableError:
                logging.warning(f"Table {self.table_name} not found, skipping delete operation.")
                return
            except Exception as e:
                raise e
        finally:
            await conn.close()


    def delete_by_metadata_field(self, key: str, value: str) -> None:
        with self._get_cursor() as cur:
            cur.execute(f"DELETE FROM {self.table_name} WHERE meta->>%s = %s", (key, value))


    # new
    async def adelete_by_metadata_field(self, key: str, value: str) -> None:
        conn = await self._get_async_connection()
        try:
            await conn.execute(
                f"DELETE FROM {self.table_name} WHERE meta->>$1 = $2",
                key, value
            )
        finally:
            await conn.close()


    def search_by_vector(self, query_vector: list[float], **kwargs: Any) -> list[Document]:
        """
        Search the nearest neighbors to a vector.

        :param query_vector: The input vector to search for similar items.
        :return: List of Documents that are nearest to the query vector.
        """
        top_k = kwargs.get("top_k", 4)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        document_ids_filter = kwargs.get("document_ids_filter")
        where_clause = ""
        if document_ids_filter:
            document_ids = ", ".join(f"'{id}'" for id in document_ids_filter)
            where_clause = f" WHERE meta->>'document_id' in ({document_ids}) "

        with self._get_cursor() as cur:
            cur.execute(
                f"SELECT meta, text, embedding <=> %s AS distance FROM {self.table_name}"
                f" {where_clause}"
                f" ORDER BY distance LIMIT {top_k}",
                (json.dumps(query_vector),),
            )
            docs = []
            score_threshold = float(kwargs.get("score_threshold") or 0.0)
            for record in cur:
                metadata, text, distance = record
                score = 1 - distance
                metadata["score"] = score
                if score > score_threshold:
                    docs.append(Document(page_content=text, metadata=metadata))
        return docs

    # new
    async def asearch_by_vector(self, query_vector: list[float], **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 4)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        document_ids_filter = kwargs.get("document_ids_filter")
        where_clause = ""
        if document_ids_filter:
            document_ids = ", ".join(f"'{id}'" for id in document_ids_filter)
            where_clause = f" WHERE meta->>'document_id' in ({document_ids}) "
        
        # Convert the vector list to a string representation
        vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        
        conn = await self._get_async_connection()
        try:
            records = await conn.fetch(
                f"SELECT meta, text, embedding <=> $1::vector AS distance FROM {self.table_name}"
                f" {where_clause}"
                f" ORDER BY distance LIMIT {top_k}",
                vector_str  # Pass the string representation
            )
            
            docs = []
            score_threshold = float(kwargs.get("score_threshold") or 0.0)
            for record in records:
                metadata_str, text, distance = record  # metadata is returned as a string
                metadata = json.loads(metadata_str)    # parse the JSON string to a dict
                score = 1 - distance
                metadata["score"] = score
                if score > score_threshold:
                    docs.append(Document(page_content=text, metadata=metadata))
            return docs
        finally:
            await conn.close()


    def search_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 5)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        with self._get_cursor() as cur:
            document_ids_filter = kwargs.get("document_ids_filter")
            where_clause = ""
            if document_ids_filter:
                document_ids = ", ".join(f"'{id}'" for id in document_ids_filter)
                where_clause = f" AND meta->>'document_id' in ({document_ids}) "
            if self.pg_bigm:
                cur.execute("SET pg_bigm.similarity_limit TO 0.000001")
                cur.execute(
                    f"""SELECT meta, text, bigm_similarity(unistr(%s), coalesce(text, '')) AS score
                    FROM {self.table_name}
                    WHERE text =%% unistr(%s)
                    {where_clause}
                    ORDER BY score DESC
                    LIMIT {top_k}""",
                    # f"'{query}'" is required in order to account for whitespace in query
                    (f"'{query}'", f"'{query}'"),
                )
            else:
                cur.execute(
                    f"""SELECT meta, text, ts_rank(to_tsvector(coalesce(text, '')), plainto_tsquery(%s)) AS score
                    FROM {self.table_name}
                    WHERE to_tsvector(text) @@ plainto_tsquery(%s)
                    {where_clause}
                    ORDER BY score DESC
                    LIMIT {top_k}""",
                    # f"'{query}'" is required in order to account for whitespace in query
                    (f"'{query}'", f"'{query}'"),
                )

            docs = []

            for record in cur:
                metadata, text, score = record
                metadata["score"] = score
                docs.append(Document(page_content=text, metadata=metadata))

        return docs

    # new
    async def asearch_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 5)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        document_ids_filter = kwargs.get("document_ids_filter")
        where_clause = ""
        if document_ids_filter:
            document_ids = ", ".join(f"'{id}'" for id in document_ids_filter)
            where_clause = f" AND meta->>'document_id' in ({document_ids}) "
        
        conn = await self._get_async_connection()
        try:
            if self.pg_bigm:
                await conn.execute("SET pg_bigm.similarity_limit TO 0.000001")
                records = await conn.fetch(
                    f"""SELECT meta, text, bigm_similarity($1, coalesce(text, '')) AS score
                    FROM {self.table_name}
                    WHERE text =%% $1
                    {where_clause}
                    ORDER BY score DESC
                    LIMIT {top_k}""",
                    query
                )
            else:
                records = await conn.fetch(
                    f"""SELECT meta, text, ts_rank(to_tsvector(coalesce(text, '')), plainto_tsquery($1)) AS score
                    FROM {self.table_name}
                    WHERE to_tsvector(text) @@ plainto_tsquery($1)
                    {where_clause}
                    ORDER BY score DESC
                    LIMIT {top_k}""",
                    query
                )
            
            docs = []
            for record in records:
                metadata_str, text, score = record
                # Parse the JSON string into a dictionary
                metadata = json.loads(metadata_str)
                metadata["score"] = score
                docs.append(Document(page_content=text, metadata=metadata))
            return docs
        finally:
            await conn.close()


    def delete(self) -> None:
        with self._get_cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")


    # new
    async def adelete(self) -> None:
        conn = await self._get_async_connection()
        try:
            await conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
        finally:
            await conn.close()


    def _create_collection(self, dimension: int):
        cache_key = f"vector_indexing_{self._collection_name}"
        lock_name = f"{cache_key}_lock"
        collection_exist_cache_key = f"vector_indexing_{self._collection_name}"

        with self._get_cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(SQL_CREATE_TABLE.format(table_name=self.table_name, dimension=dimension))
            # PG hnsw index only support 2000 dimension or less
            # ref: https://github.com/pgvector/pgvector?tab=readme-ov-file#indexing
            if dimension <= 2000:
                cur.execute(SQL_CREATE_INDEX.format(table_name=self.table_name, index_hash=self.index_hash))
            if self.pg_bigm:
                cur.execute(SQL_CREATE_INDEX_PG_BIGM.format(table_name=self.table_name, index_hash=self.index_hash))


    # new
    async def _acreate_collection(self, dimension: int):
        conn = await self._get_async_connection()
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(SQL_CREATE_TABLE.format(table_name=self.table_name, dimension=dimension))
            if dimension <= 2000:
                await conn.execute(SQL_CREATE_INDEX.format(table_name=self.table_name, index_hash=self.index_hash))
            if self.pg_bigm:
                await conn.execute(SQL_CREATE_INDEX_PG_BIGM.format(table_name=self.table_name, index_hash=self.index_hash))
        finally:
            await conn.close()


class PGVectorFactory(AbstractVectorFactory):
    def init_vector(self, collection_name: str, attributes: list, embeddings: Embeddings) -> PGVector:
        return PGVector(
            collection_name=collection_name,
            config=PGVectorConfig(
                host=vector_config.PGVECTOR_HOST or "localhost",
                port=vector_config.PGVECTOR_PORT,
                user=vector_config.PGVECTOR_USER or "postgres",
                password=vector_config.PGVECTOR_PASSWORD or "",
                database=vector_config.PGVECTOR_DATABASE or "postgres",
                min_connection=vector_config.PGVECTOR_MIN_CONNECTION,
                max_connection=vector_config.PGVECTOR_MAX_CONNECTION,
                pg_bigm=vector_config.PGVECTOR_PG_BIGM,
            ),
        )
