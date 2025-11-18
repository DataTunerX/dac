import asyncio
from dbutils.pooled_db import PooledDB
from pymysql import Error
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
from contextlib import asynccontextmanager
import uuid
import aiomysql
from ..api.base import Fingerprint
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncFingerprintService:
    def __init__(self, host: str = None, user: str = None, password: str = None, 
                 database: str = None, port: int = None, pool_size: int = None):
        """
        Args:
            host: Database host address
            user: Database username  
            password: Database password
            database: Database name
            port: Database port, default 3306
            pool_size: Connection pool size, default 50
        """
        self.host = host or os.getenv('MYSQL_HOST', '')
        self.user = user or os.getenv('MYSQL_USER', 'root')
        self.password = password or os.getenv('MYSQL_PASSWORD', '123')
        self.database = database or os.getenv('MYSQL_FINGERPRINT_DATABASE', 'fingerprint')
        self.port = port or int(os.getenv('MYSQL_PORT', '3307'))
        self.pool_size = pool_size or int(os.getenv('MYSQL_MAX_CONNECTION', '50'))
        self.pool = None
        
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
        create table if table not exist in database
            
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS fingerprints (
            fid VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            fingerprint_id VARCHAR(255) NOT NULL COMMENT 'Fingerprint ID',
            fingerprint_summary TEXT COMMENT 'Fingerprint summary',
            agent_info_name VARCHAR(255) COMMENT 'Agent name',
            agent_info_description TEXT COMMENT 'Agent description',
            dd_namespace VARCHAR(255) COMMENT 'DD namespace',
            dd_name VARCHAR(255) COMMENT 'DD name',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
            INDEX idx_fingerprint_id (fingerprint_id),
            INDEX idx_agent_name (agent_info_name),
            INDEX idx_dd_namespace (dd_namespace),
            INDEX idx_dd_name (dd_name),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Fingerprint information table'
        """
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(create_table_query)
            logger.info("Fingerprint table creation/check completed")
        except Error as e:
            logger.error(f"Table creation error: {e}")
            raise
    
    async def create(self, fingerprint: Fingerprint) -> bool:
        """
        create Fingerprint
        Args:
            fingerprint: Fingerprint object
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO fingerprints 
        (fid, fingerprint_id, fingerprint_summary, agent_info_name, agent_info_description, dd_namespace, dd_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, (
                    fingerprint.fid,
                    fingerprint.fingerprint_id,
                    fingerprint.fingerprint_summary,
                    fingerprint.agent_info_name,
                    fingerprint.agent_info_description,
                    fingerprint.dd_namespace,
                    fingerprint.dd_name
                ))
                return result > 0
        except Error as e:
            logger.error(f"Error creating record: {e}")
            return False
    
    async def batch_create(self, fingerprints: List[Fingerprint]) -> bool:
        """
        batch create Fingerprints
        Args:
            fingerprints: List of Fingerprint objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO fingerprints 
        (fid, fingerprint_id, fingerprint_summary, agent_info_name, agent_info_description, dd_namespace, dd_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = [(fp.fid, fp.fingerprint_id, fp.fingerprint_summary, 
                             fp.agent_info_name, fp.agent_info_description, 
                             fp.dd_namespace, fp.dd_name) 
                            for fp in fingerprints]
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(fingerprints)
        except Error as e:
            logger.error(f"Batch create records error: {e}")
            return False
    
    async def get_by_fid(self, fid: str) -> Optional[Fingerprint]:
        """
        Retrieve fingerprint record by primary key fid

        Args:
            fid: Primary key ID
            
        Returns:
            Optional[Fingerprint]: Found Fingerprint object, returns None if not found
        """
        select_query = "SELECT * FROM fingerprints WHERE fid = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (fid,))
                result = await cursor.fetchone()
                
                if result:
                    return Fingerprint(
                        fid=result['fid'],
                        fingerprint_id=result['fingerprint_id'],
                        fingerprint_summary=result['fingerprint_summary'],
                        agent_info_name=result['agent_info_name'],
                        agent_info_description=result['agent_info_description'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name']
                    )
                return None
        except Error as e:
            logger.error(f"Query record error: {e}")
            return None
    
    async def get_by_fingerprint_id(self, fingerprint_id: str) -> Optional[Fingerprint]:
        """
        Retrieve fingerprint record by fingerprint_id

        Args:
            fingerprint_id: Fingerprint ID
            
        Returns:
            Optional[Fingerprint]: Found Fingerprint object, returns None if not found
        """
        select_query = "SELECT * FROM fingerprints WHERE fingerprint_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (fingerprint_id,))
                result = await cursor.fetchone()
                
                if result:
                    return Fingerprint(
                        fid=result['fid'],
                        fingerprint_id=result['fingerprint_id'],
                        fingerprint_summary=result['fingerprint_summary'],
                        agent_info_name=result['agent_info_name'],
                        agent_info_description=result['agent_info_description'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name']
                    )
                return None
        except Error as e:
            logger.error(f"Query record error: {e}")
            return None

    async def get_by_dd_info(self, dd_namespace: str, dd_name: str) -> List[Fingerprint]:
        """
        Retrieve fingerprint records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            List[Fingerprint]: List of found Fingerprint objects
        """
        select_query = "SELECT * FROM fingerprints WHERE dd_namespace = %s AND dd_name = %s ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (dd_namespace, dd_name))
                results = await cursor.fetchall()
                
                fingerprints = []
                for result in results:
                    fingerprints.append(Fingerprint(
                        fid=result['fid'],
                        fingerprint_id=result['fingerprint_id'],
                        fingerprint_summary=result['fingerprint_summary'],
                        agent_info_name=result['agent_info_name'],
                        agent_info_description=result['agent_info_description'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name']
                    ))
                
                return fingerprints
        except Error as e:
            logger.error(f"Query DD information record error: {e}")
            return []
    
    async def get_all(self, page: int = None, page_size: int = None) -> List[Fingerprint]:
        """
        Get all fingerprint records (supports pagination)

        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            List[Fingerprint]: List of fingerprint records
        """
        base_query = "SELECT * FROM fingerprints ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                if page is not None and page_size is not None:
                    offset = (page - 1) * page_size
                    await cursor.execute(f"{base_query} LIMIT %s OFFSET %s", (page_size, offset))
                else:
                    await cursor.execute(base_query)
                
                results = await cursor.fetchall()
                
                fingerprints = []
                for result in results:
                    fingerprints.append(Fingerprint(
                        fid=result['fid'],
                        fingerprint_id=result['fingerprint_id'],
                        fingerprint_summary=result['fingerprint_summary'],
                        agent_info_name=result['agent_info_name'],
                        agent_info_description=result['agent_info_description'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name']
                    ))
                
                return fingerprints
        except Error as e:
            logger.error(f"Query all records error: {e}")
            return []
    
    async def update(self, fid: str, fingerprint: Fingerprint) -> bool:
        """
        Update fingerprint record

        Args:
            fid: Primary key of the record to update
            fingerprint: New fingerprint data
            
        Returns:
            bool: Whether the operation was successful
        """
        update_query = """
        UPDATE fingerprints 
        SET fingerprint_id = %s, fingerprint_summary = %s, 
            agent_info_name = %s, agent_info_description = %s,
            dd_namespace = %s, dd_name = %s
        WHERE fid = %s
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, (
                    fingerprint.fingerprint_id,
                    fingerprint.fingerprint_summary,
                    fingerprint.agent_info_name,
                    fingerprint.agent_info_description,
                    fingerprint.dd_namespace,
                    fingerprint.dd_name,
                    fid
                ))
                return result > 0
        except Error as e:
            logger.error(f"Update record error: {e}")
            return False
    
    async def delete(self, fid: str) -> bool:
        """
        Delete fingerprint record

        Args:
            fid: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM fingerprints WHERE fid = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (fid,))
                return result > 0
        except Error as e:
            logger.error(f"delete record error: {e}")
            return False

    async def delete_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Delete fingerprint records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM fingerprints WHERE dd_namespace = %s AND dd_name = %s"
        
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
        base_query = "SELECT COUNT(*) as total FROM fingerprints"
        
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
    
    async def exists(self, fid: str) -> bool:
        """
        Check if record exists

        Args:
            fid: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_by_fid(fid) is not None

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