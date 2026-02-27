import asyncio
from dbutils.pooled_db import PooledDB
from pymysql import Error
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
from contextlib import asynccontextmanager
import uuid
import aiomysql
import json
from ..api.base import CodebaseIndexer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncCodebaseIndexerService:
    def __init__(self, host: str = None, user: str = None, password: str = None, 
                 database: str = None, port: int = None, pool_size: int = None, pool = None):
        """
        Args:
            host: Database host address
            user: Database username
            password: Database password
            database: Database name
            port: Database port, default 3306
            pool_size: Connection pool size, default 50
            pool: external connection pool
        """
        self.host = host or os.getenv('MYSQL_HOST', '192.168.3.7')
        self.user = user or os.getenv('MYSQL_USER', 'root')
        self.password = password or os.getenv('MYSQL_PASSWORD', '123')
        self.database = database or os.getenv('MYSQL_FINGERPRINT_DATABASE', 'fingerprint')
        self.port = port or int(os.getenv('MYSQL_PORT', '3307'))
        self.pool_size = pool_size or int(os.getenv('MYSQL_MAX_CONNECTION', '50'))
        self.pool = pool
        
        logger.info(f"Asynchronous MySQL connection pool configuration completed, maximum connections: {pool_size}")
    
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
                charset='utf8mb4',
                use_unicode=True,
                autocommit=False,
                cursorclass=aiomysql.DictCursor
            )
            logger.info("Asynchronous MySQL connection pool created successfully.")
            
        await self._create_table_if_not_exists()
    
    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            logger.info("Asynchronous MySQL connection pool has been closed.")
    
    @asynccontextmanager
    async def _get_connection(self):
        if self.pool is None:
            await self.initialize()
        
        connection = None
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute("SET NAMES 'utf8mb4'")
                    await cursor.execute("SET CHARACTER SET utf8mb4")
                yield connection
        except Error as e:
            logger.error(f"Database connection error.: {e}")
            if connection:
                await connection.rollback()
            raise
    
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
            logger.error(f"Database operation error.: {e}")
            raise
        finally:
            if own_connection and connection:
                self.pool.release(connection)
    
    async def _create_table_if_not_exists(self):
        """
        create table if table not exist in database, or update table structure if exists
            
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS codebase_indexer (
            codebase_indexer_id VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            filepath VARCHAR(255) COMMENT 'code filepath',
            code_deep_analysis MEDIUMTEXT COMMENT 'code deep analysis',
            dd_namespace VARCHAR(255) COMMENT 'DD namespace',
            dd_name VARCHAR(255) COMMENT 'DD name',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
            INDEX idx_filepath (filepath(255)),
            INDEX idx_dd_name (dd_name),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='code deep analysis information table'
        """
        
        # Expected columns and their definitions
        expected_columns = {
            'codebase_indexer_id': 'VARCHAR(255)',
            'filepath': 'VARCHAR(255)',
            'code_deep_analysis': 'MEDIUMTEXT',
            'dd_namespace': 'VARCHAR(255)',
            'dd_name': 'VARCHAR(255)',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP'
        }
        
        try:
            async with self._get_cursor() as cursor:
                # Check if table exists
                await cursor.execute("SHOW TABLES LIKE 'codebase_indexer'")
                table_exists = await cursor.fetchone()
                
                if not table_exists:
                    # Create table if it doesn't exist
                    await cursor.execute(create_table_query)
                    logger.info("Semantic domain table created")
                else:
                    # Table exists, check and update structure
                    # Check existing columns
                    await cursor.execute("DESCRIBE codebase_indexer")
                    columns = await cursor.fetchall()
                    existing_column_names = {col['Field'] for col in columns}
                    
                    # Add missing columns
                    for col_name, col_type in expected_columns.items():
                        if col_name not in existing_column_names:
                            if col_name == 'created_at':
                                alter_query = f"ALTER TABLE codebase_indexer ADD COLUMN {col_name} {col_type} DEFAULT CURRENT_TIMESTAMP COMMENT '{'Creation time' if col_name == 'created_at' else 'Update time'}'"
                            elif col_name == 'updated_at':
                                alter_query = f"ALTER TABLE codebase_indexer ADD COLUMN {col_name} {col_type} DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time'"
                            else:
                                comment_map = {
                                    'codebase_indexer_id': 'Primary key',
                                    'filepath': 'code filepath',
                                    'code_deep_analysis': 'code deep analysis',
                                    'dd_namespace': 'DD namespace',
                                    'dd_name': 'DD name'
                                }
                                alter_query = f"ALTER TABLE codebase_indexer ADD COLUMN {col_name} {col_type} COMMENT '{comment_map.get(col_name, '')}'"
                            
                            await cursor.execute(alter_query)
                            logger.info(f"Added missing column: {col_name}")
                    
                    # Check and add missing indexes
                    await cursor.execute("SHOW INDEXES FROM codebase_indexer")
                    indexes = await cursor.fetchall()
                    index_names = {idx['Key_name'] for idx in indexes}
                    
                    if 'idx_filepath' not in index_names:
                        await cursor.execute("ALTER TABLE codebase_indexer ADD INDEX idx_filepath (filepath(255))")
                        logger.info("Added missing index: idx_filepath")
                    
                    if 'idx_dd_name' not in index_names:
                        await cursor.execute("ALTER TABLE codebase_indexer ADD INDEX idx_dd_name (dd_name)")
                        logger.info("Added missing index: idx_dd_name")
                    
                    if 'idx_created_at' not in index_names:
                        await cursor.execute("ALTER TABLE codebase_indexer ADD INDEX idx_created_at (created_at)")
                        logger.info("Added missing index: idx_created_at")
                    
                    logger.info("Semantic domain table structure checked and updated if needed")
                    
            logger.info("Semantic domain table creation/check completed")
        except Error as e:
            logger.error(f"Table creation/update error: {e}")
            raise
    
    async def create(self, codebase_indexer: CodebaseIndexer) -> bool:
        """
        create codebase indexer record
        
        Args:
            codebase_indexer: CodebaseIndexer object
            
        Returns:
            bool: Whether the operation was successful
        """
        # Generate ID if not provided
        if not codebase_indexer.codebase_indexer_id:
            codebase_indexer.codebase_indexer_id = str(uuid.uuid4())
        
        insert_query = """
        INSERT INTO codebase_indexer 
        (codebase_indexer_id, filepath, code_deep_analysis, dd_namespace, dd_name)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        values = (
            codebase_indexer.codebase_indexer_id,
            codebase_indexer.filepath,
            codebase_indexer.code_deep_analysis,
            codebase_indexer.dd_namespace,
            codebase_indexer.dd_name
        )
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, values)
                return result > 0
        except Error as e:
            logger.error(f"Error creating codebase indexer record: {e}")
            return False
    
    async def batch_create(self, codebase_indexers: List[CodebaseIndexer]) -> bool:
        """
        batch create codebase indexer records
        
        Args:
            codebase_indexers: List of CodebaseIndexer objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO codebase_indexer 
        (codebase_indexer_id, filepath, code_deep_analysis, dd_namespace, dd_name)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = []
                    for record in codebase_indexers:
                        # Generate ID if not provided
                        if not record.codebase_indexer_id:
                            record.codebase_indexer_id = str(uuid.uuid4())
                        
                        data.append((
                            record.codebase_indexer_id,
                            record.filepath,
                            record.code_deep_analysis,
                            record.dd_namespace,
                            record.dd_name
                        ))
                    
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(codebase_indexers)
        except Error as e:
            logger.error(f"Batch create codebase indexer records error: {e}")
            return False
    
    async def get_by_id(self, codebase_indexer_id: str) -> Optional[CodebaseIndexer]:
        """
        Retrieve codebase indexer record by primary key codebase_indexer_id

        Args:
            codebase_indexer_id: Primary key ID
            
        Returns:
            Optional[CodebaseIndexer]: Found CodebaseIndexer object, returns None if not found
        """
        select_query = "SELECT * FROM codebase_indexer WHERE codebase_indexer_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (codebase_indexer_id,))
                result = await cursor.fetchone()
                
                if result:
                    return CodebaseIndexer(
                        codebase_indexer_id=result['codebase_indexer_id'],
                        filepath=result['filepath'],
                        code_deep_analysis=result['code_deep_analysis'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    )
                return None
        except Error as e:
            logger.error(f"Query codebase indexer record error: {e}")
            return None

    async def get_by_filepath(self, filepath: str, dd_namespace: str = None, dd_name: str = None) -> List[CodebaseIndexer]:
        """
        Retrieve codebase indexer records by filepath (supports exact match and prefix match)

        Args:
            filepath: File path to search for
            dd_namespace: Optional DD namespace filter
            dd_name: Optional DD name filter
            
        Returns:
            List[CodebaseIndexer]: List of found CodebaseIndexer objects
        """
        # Build query with optional DD filters
        conditions = ["filepath = %s"]
        params = [filepath]
        
        if dd_namespace is not None:
            conditions.append("dd_namespace = %s")
            params.append(dd_namespace)
        if dd_name is not None:
            conditions.append("dd_name = %s")
            params.append(dd_name)
        
        select_query = f"SELECT * FROM codebase_indexer WHERE {' AND '.join(conditions)} ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, tuple(params))
                results = await cursor.fetchall()
                
                records = []
                for result in results:
                    records.append(CodebaseIndexer(
                        codebase_indexer_id=result['codebase_indexer_id'],
                        filepath=result['filepath'],
                        code_deep_analysis=result['code_deep_analysis'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return records
        except Error as e:
            logger.error(f"Query filepath record error: {e}")
            return []

    async def search_by_filepath_prefix(self, filepath_prefix: str, dd_namespace: str = None, dd_name: str = None) -> List[CodebaseIndexer]:
        """
        Search codebase indexer records by filepath prefix (LIKE query)

        Args:
            filepath_prefix: File path prefix to search for
            dd_namespace: Optional DD namespace filter
            dd_name: Optional DD name filter
            
        Returns:
            List[CodebaseIndexer]: List of found CodebaseIndexer objects
        """
        # Build query with optional DD filters
        conditions = ["filepath LIKE %s"]
        params = [f"{filepath_prefix}%"]
        
        if dd_namespace is not None:
            conditions.append("dd_namespace = %s")
            params.append(dd_namespace)
        if dd_name is not None:
            conditions.append("dd_name = %s")
            params.append(dd_name)
        
        select_query = f"SELECT * FROM codebase_indexer WHERE {' AND '.join(conditions)} ORDER BY filepath ASC, created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, tuple(params))
                results = await cursor.fetchall()
                
                records = []
                for result in results:
                    records.append(CodebaseIndexer(
                        codebase_indexer_id=result['codebase_indexer_id'],
                        filepath=result['filepath'],
                        code_deep_analysis=result['code_deep_analysis'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return records
        except Error as e:
            logger.error(f"Search filepath prefix error: {e}")
            return []

    async def get_by_dd_info(self, dd_namespace: str, dd_name: str) -> List[CodebaseIndexer]:
        """
        Retrieve codebase indexer records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            List[CodebaseIndexer]: List of found CodebaseIndexer objects
        """
        select_query = "SELECT * FROM codebase_indexer WHERE dd_namespace = %s AND dd_name = %s ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (dd_namespace, dd_name))
                results = await cursor.fetchall()
                
                records = []
                for result in results:
                    records.append(CodebaseIndexer(
                        codebase_indexer_id=result['codebase_indexer_id'],
                        filepath=result['filepath'],
                        code_deep_analysis=result['code_deep_analysis'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return records
        except Error as e:
            logger.error(f"Query DD information record error: {e}")
            return []
    
    async def get_all(self, page: int = None, page_size: int = None) -> List[CodebaseIndexer]:
        """
        Get all codebase indexer records (supports pagination)

        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            List[CodebaseIndexer]: List of CodebaseIndexer objects
        """
        base_query = "SELECT * FROM codebase_indexer ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                if page is not None and page_size is not None:
                    offset = (page - 1) * page_size
                    await cursor.execute(f"{base_query} LIMIT %s OFFSET %s", (page_size, offset))
                else:
                    await cursor.execute(base_query)
                
                results = await cursor.fetchall()
                
                records = []
                for result in results:
                    records.append(CodebaseIndexer(
                        codebase_indexer_id=result['codebase_indexer_id'],
                        filepath=result['filepath'],
                        code_deep_analysis=result['code_deep_analysis'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return records
        except Error as e:
            logger.error(f"Query all records error: {e}")
            return []
    
    async def update(self, codebase_indexer_id: str, codebase_indexer: CodebaseIndexer) -> bool:
        """
        Update codebase indexer record

        Args:
            codebase_indexer_id: Primary key of the record to update
            codebase_indexer: CodebaseIndexer object with new data
            
        Returns:
            bool: Whether the operation was successful
        """
        # Build dynamic update query based on provided fields
        update_fields = []
        values = []
        
        if codebase_indexer.filepath is not None:
            update_fields.append("filepath = %s")
            values.append(codebase_indexer.filepath)
        if codebase_indexer.code_deep_analysis is not None:
            update_fields.append("code_deep_analysis = %s")
            values.append(codebase_indexer.code_deep_analysis)
        if codebase_indexer.dd_namespace is not None:
            update_fields.append("dd_namespace = %s")
            values.append(codebase_indexer.dd_namespace)
        if codebase_indexer.dd_name is not None:
            update_fields.append("dd_name = %s")
            values.append(codebase_indexer.dd_name)
        
        if not update_fields:
            return False
        
        values.append(codebase_indexer_id)
        update_query = f"""
        UPDATE codebase_indexer 
        SET {', '.join(update_fields)}
        WHERE codebase_indexer_id = %s
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, tuple(values))
                return result > 0
        except Error as e:
            logger.error(f"Update codebase indexer record error: {e}")
            return False
    
    async def delete(self, codebase_indexer_id: str) -> bool:
        """
        Delete codebase indexer record

        Args:
            codebase_indexer_id: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM codebase_indexer WHERE codebase_indexer_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (codebase_indexer_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete codebase indexer record error: {e}")
            return False

    async def delete_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Delete codebase indexer records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM codebase_indexer WHERE dd_namespace = %s AND dd_name = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (dd_namespace, dd_name))
                return result > 0
        except Error as e:
            logger.error(f"Delete DD information record error: {e}")
            return False
    
    async def count(self, condition: str = None, params: tuple = None) -> int:
        """
        Get total record count

        Args:
            condition: Query condition (WHERE clause)
            params: Query parameters
            
        Returns:
            int: Total record count
        """
        base_query = "SELECT COUNT(*) as total FROM codebase_indexer"
        
        try:
            async with self._get_cursor() as cursor:
                if condition:
                    await cursor.execute(f"{base_query} WHERE {condition}", params)
                else:
                    await cursor.execute(base_query)
                
                result = await cursor.fetchone()
                return result['total'] if result else 0
        except Error as e:
            logger.error(f"Count records error: {e}")
            return 0
    
    async def exists(self, codebase_indexer_id: str) -> bool:
        """
        Check if record exists

        Args:
            codebase_indexer_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_by_id(codebase_indexer_id) is not None

    async def exists_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Check if records exist for DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether records exist
        """
        count = await self.count("dd_namespace = %s AND dd_name = %s", (dd_namespace, dd_name))
        return count > 0
    
    async def get_connection_pool_status(self) -> Dict[str, Any]:
        """
        Get connection pool status information

        Returns:
            Dict[str, Any]: Connection pool status information
        """
        if self.pool:
            return {
                'minsize': self.pool.minsize,
                'maxsize': self.pool.maxsize,
                'size': getattr(self.pool, '_size', 'unknown'),
                'freesize': getattr(self.pool, '_free', 'unknown'),
                'database': self.database,
                'host': self.host,
                'pool_initialized': True
            }
        else:
            return {'status': 'pool_not_initialized'}
