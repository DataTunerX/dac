import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiomysql
from pymysql import Error

from ..api.base import UnstructuredFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TABLE_NAME = "unstructured_files"


class AsyncUnstructuredFilesService:
    """MySQL persistence for MinIO-backed unstructured file snapshots (table `unstructured_files`)."""

    def __init__(
        self,
        host: str = None,
        user: str = None,
        password: str = None,
        database: str = None,
        port: int = None,
        pool_size: int = None,
        pool=None,
    ):
        self.host = host or os.getenv("MYSQL_HOST", "192.168.3.7")
        self.user = user or os.getenv("MYSQL_USER", "root")
        self.password = password or os.getenv("MYSQL_PASSWORD", "123")
        self.database = database or os.getenv("MYSQL_FINGERPRINT_DATABASE", "fingerprint")
        self.port = port or int(os.getenv("MYSQL_PORT", "3307"))
        self.pool_size = pool_size or int(os.getenv("MYSQL_MAX_CONNECTION", "50"))
        self.pool = pool

    async def initialize(self):
        if self.pool is None:
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                minsize=2,
                maxsize=self.pool_size,
                charset="utf8mb4",
                use_unicode=True,
                autocommit=False,
                cursorclass=aiomysql.DictCursor,
            )
            logger.info("unstructured-files: MySQL pool created.")
        await self._create_table_if_not_exists()

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            logger.info("unstructured-files: MySQL pool closed.")

    @asynccontextmanager
    async def _get_cursor(self, connection: aiomysql.Connection = None):
        cursor = None
        own_connection = False
        try:
            if connection is None:
                if self.pool is None:
                    await self.initialize()
                connection = await self.pool.acquire()
                own_connection = True
            async with connection.cursor() as cursor:
                yield cursor
                await connection.commit()
        except Error as e:
            if connection:
                await connection.rollback()
            logger.error(f"unstructured-files DB error: {e}")
            raise
        finally:
            if own_connection and connection:
                self.pool.release(connection)

    async def _create_table_if_not_exists(self):
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Primary key',
            dd_namespace VARCHAR(255) NOT NULL COMMENT 'DataDescriptor namespace',
            dd_name VARCHAR(255) NOT NULL COMMENT 'DataDescriptor name',
            file_name VARCHAR(512) NOT NULL COMMENT 'File display name',
            `bucket` VARCHAR(255) NOT NULL COMMENT 'MinIO bucket',
            minio_path VARCHAR(2048) NOT NULL COMMENT 'Full MinIO object path or URI',
            file_size BIGINT NOT NULL DEFAULT 0 COMMENT 'Size in bytes',
            file_summary MEDIUMTEXT NULL COMMENT 'Optional file summary or analysis text',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
            UNIQUE KEY uk_unstructured_files_dd_bucket_path (dd_namespace(64), dd_name(64), `bucket`(64), minio_path(512)),
            INDEX idx_unstructured_files_created (created_at),
            INDEX idx_unstructured_files_bucket (`bucket`),
            INDEX idx_unstructured_files_dd (dd_namespace, dd_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='unstructured-files: MinIO file metadata snapshots'
        """
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(create_sql)
                logger.info(f"unstructured-files: ensured table {TABLE_NAME}")
        except Error as e:
            logger.error(f"unstructured-files: schema error: {e}")
            raise

    @staticmethod
    def _row_to_model(row: Dict[str, Any]) -> UnstructuredFile:
        return UnstructuredFile(
            id=row["id"],
            dd_namespace=row["dd_namespace"],
            dd_name=row["dd_name"],
            file_name=row["file_name"],
            bucket=row["bucket"],
            minio_path=row["minio_path"],
            file_size=row["file_size"],
            file_summary=row.get("file_summary"),
            created_at=row["created_at"],
        )

    async def upsert(self, record: UnstructuredFile) -> int:
        """Insert or update by (dd_namespace, dd_name, bucket, minio_path); returns row id."""
        sql = f"""
        INSERT INTO {TABLE_NAME} (dd_namespace, dd_name, file_name, `bucket`, minio_path, file_size, file_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
            file_name = new.file_name,
            file_size = new.file_size,
            file_summary = IF(new.file_summary IS NULL, {TABLE_NAME}.file_summary, new.file_summary)
        """
        async with self._get_cursor() as cursor:
            await cursor.execute(
                sql,
                (
                    record.dd_namespace,
                    record.dd_name,
                    record.file_name,
                    record.bucket,
                    record.minio_path,
                    record.file_size,
                    record.file_summary,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            await cursor.execute(
                f"SELECT id FROM {TABLE_NAME} WHERE dd_namespace = %s AND dd_name = %s "
                f"AND `bucket` = %s AND minio_path = %s",
                (record.dd_namespace, record.dd_name, record.bucket, record.minio_path),
            )
            r = await cursor.fetchone()
            return int(r["id"]) if r else 0

    async def batch_upsert(self, records: List[UnstructuredFile]) -> int:
        if not records:
            return 0
        n = 0
        for r in records:
            await self.upsert(r)
            n += 1
        return n

    async def get_by_id(self, row_id: int) -> Optional[UnstructuredFile]:
        async with self._get_cursor() as cursor:
            await cursor.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = %s", (row_id,))
            row = await cursor.fetchone()
            return self._row_to_model(row) if row else None

    async def get_by_dd_bucket_path(
        self,
        dd_namespace: str,
        dd_name: str,
        bucket: str,
        minio_path: str,
    ) -> Optional[UnstructuredFile]:
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE dd_namespace = %s AND dd_name = %s "
                f"AND `bucket` = %s AND minio_path = %s",
                (dd_namespace, dd_name, bucket, minio_path),
            )
            row = await cursor.fetchone()
            return self._row_to_model(row) if row else None

    async def list_by_bucket(
        self,
        bucket: str,
        limit: int = 500,
        offset: int = 0,
        dd_namespace: Optional[str] = None,
        dd_name: Optional[str] = None,
    ) -> List[UnstructuredFile]:
        limit = max(1, min(limit, 2000))
        offset = max(0, offset)
        filters = ["`bucket` = %s"]
        params: List[Any] = [bucket]
        if dd_namespace is not None and dd_name is not None:
            filters.append("dd_namespace = %s")
            filters.append("dd_name = %s")
            params.extend([dd_namespace, dd_name])
        where = " AND ".join(filters)
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE {where} ORDER BY id ASC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = await cursor.fetchall()
            return [self._row_to_model(r) for r in rows]

    async def list_by_dd(
        self,
        dd_namespace: str,
        dd_name: str,
        limit: int = 500,
        offset: int = 0,
    ) -> List[UnstructuredFile]:
        limit = max(1, min(limit, 2000))
        offset = max(0, offset)
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE dd_namespace = %s AND dd_name = %s "
                f"ORDER BY id ASC LIMIT %s OFFSET %s",
                (dd_namespace, dd_name, limit, offset),
            )
            rows = await cursor.fetchall()
            return [self._row_to_model(r) for r in rows]

    async def list_all(
        self,
        limit: int = 500,
        offset: int = 0,
        dd_namespace: Optional[str] = None,
        dd_name: Optional[str] = None,
    ) -> List[UnstructuredFile]:
        limit = max(1, min(limit, 2000))
        offset = max(0, offset)
        if dd_namespace is not None and dd_name is not None:
            return await self.list_by_dd(dd_namespace, dd_name, limit=limit, offset=offset)
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"SELECT * FROM {TABLE_NAME} ORDER BY id ASC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [self._row_to_model(r) for r in rows]

    async def delete_by_id(self, row_id: int) -> bool:
        async with self._get_cursor() as cursor:
            await cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE id = %s", (row_id,))
            return cursor.rowcount > 0

    async def delete_by_dd_bucket_path(
        self,
        dd_namespace: str,
        dd_name: str,
        bucket: str,
        minio_path: str,
    ) -> bool:
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"DELETE FROM {TABLE_NAME} WHERE dd_namespace = %s AND dd_name = %s "
                f"AND `bucket` = %s AND minio_path = %s",
                (dd_namespace, dd_name, bucket, minio_path),
            )
            return cursor.rowcount > 0

    async def delete_by_bucket(self, bucket: str) -> int:
        async with self._get_cursor() as cursor:
            await cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE `bucket` = %s", (bucket,))
            return cursor.rowcount

    async def delete_by_dd(self, dd_namespace: str, dd_name: str) -> int:
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"DELETE FROM {TABLE_NAME} WHERE dd_namespace = %s AND dd_name = %s",
                (dd_namespace, dd_name),
            )
            return cursor.rowcount

    async def count_by_bucket(self, bucket: str) -> int:
        async with self._get_cursor() as cursor:
            await cursor.execute(
                f"SELECT COUNT(*) AS c FROM {TABLE_NAME} WHERE `bucket` = %s",
                (bucket,),
            )
            row = await cursor.fetchone()
            return int(row["c"]) if row else 0
