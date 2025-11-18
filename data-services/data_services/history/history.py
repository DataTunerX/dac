import asyncio
from dbutils.pooled_db import PooledDB
from pymysql import Error
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
from contextlib import asynccontextmanager
import uuid
import aiomysql
from ..api.base import HistoryRecord
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncHistoryService:
    def __init__(self, host: str = None, user: str = None, password: str = None, 
                 database: str = None, port: int = None, pool_size: int = None):
        """
        Initialize database connection pool

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
        self.database = database or os.getenv('MYSQL_HISTORY_DATABASE', 'history')
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
        """Create history conversation table (if not exists)"""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS history (
            hid VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            user_id VARCHAR(255) NOT NULL COMMENT 'User ID',
            agent_id VARCHAR(255) NOT NULL COMMENT 'Agent ID',
            run_id VARCHAR(255) COMMENT 'Run ID',
            conversation TEXT COMMENT 'Conversation record',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
            INDEX idx_user_id (user_id),
            INDEX idx_agent_id (agent_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='History conversation table'
        """
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(create_table_query)
            logger.info("History conversation table creation/check completed")
        except Error as e:
            logger.error(f"Table creation error: {e}")
            raise
    
    async def create(self, history_record: HistoryRecord) -> bool:
        """
        Create a new history record

        Args:
            history_record: HistoryRecord object
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO history 
        (hid, user_id, agent_id, run_id, conversation)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, (
                    history_record.hid,
                    history_record.user_id,
                    history_record.agent_id,
                    history_record.run_id,
                    history_record.conversation
                ))
                return result > 0
        except Error as e:
            logger.error(f"Create history record error: {e}")
            return False
    
    async def batch_create(self, history_records: List[HistoryRecord]) -> bool:
        """
        Batch create history records

        Args:
            history_records: List of HistoryRecord objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO history 
        (hid, user_id, agent_id, run_id, conversation)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = [(record.hid, record.user_id, record.agent_id, 
                             record.run_id, record.conversation) 
                            for record in history_records]
                    
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(history_records)
        except Error as e:
            logger.error(f"Batch create history records error: {e}")
            return False
    
    async def get_by_hid(self, hid: str) -> Optional[HistoryRecord]:
        """
        Retrieve history record by primary key hid

        Args:
            hid: Primary key ID
            
        Returns:
            Optional[HistoryRecord]: Found HistoryRecord object, returns None if not found
        """
        select_query = "SELECT * FROM history WHERE hid = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (hid,))
                result = await cursor.fetchone()
                
                if result:
                    return HistoryRecord(
                        hid=result['hid'],
                        user_id=result['user_id'],
                        agent_id=result['agent_id'],
                        run_id=result['run_id'],
                        conversation=result['conversation'],
                        created_at=result['created_at'],
                        updated_at=result['updated_at']
                    )
                return None
        except Error as e:
            logger.error(f"Query history record error: {e}")
            return None
    
    async def get_by_user_agent_run(self, user_id: str, agent_id: str, run_id: str, limit: int = None) -> List[HistoryRecord]:
        """
        Retrieve history records based on three conditions: user_id, agent_id, and run_id
        """
        if limit is not None:
            base_query = """
            SELECT * FROM (
                SELECT * FROM history 
                WHERE user_id = %s AND agent_id = %s AND run_id = %s 
                ORDER BY created_at DESC 
                LIMIT %s
            ) AS recent_records 
            ORDER BY created_at ASC
            """
            params = (user_id, agent_id, run_id, limit)
        else:
            base_query = """
            SELECT * FROM history 
            WHERE user_id = %s AND agent_id = %s AND run_id = %s 
            ORDER BY created_at ASC
            """
            params = (user_id, agent_id, run_id)
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(base_query, params)
                results = await cursor.fetchall()
                
                history_records = []
                for result in results:
                    history_records.append(HistoryRecord(
                        hid=result['hid'],
                        user_id=result['user_id'],
                        agent_id=result['agent_id'],
                        run_id=result['run_id'],
                        conversation=result['conversation'],
                        created_at=result['created_at'],
                        updated_at=result['updated_at']
                    ))
                
                return history_records
        except Error as e:
            logger.error(f"Query history records by user, agent, and run ID error: {e}")
            return []

    async def delete(self, hid: str) -> bool:
        """
        Delete history record

        Args:
            hid: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM history WHERE hid = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (hid,))
                return result > 0
        except Error as e:
            logger.error(f"Delete history record error.: {e}")
            return False

    async def exists(self, hid: str) -> bool:
        """
        Check if history record exists

        Args:
            hid: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_by_hid(hid) is not None
    
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