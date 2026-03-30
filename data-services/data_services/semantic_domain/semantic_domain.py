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
from ..api.base import SemanticDomain
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncSemanticDomainService:
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
        self.host = host or os.getenv('MYSQL_HOST', '192.168.3.238')
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
        CREATE TABLE IF NOT EXISTS semantic_domain (
            semantic_domain_id VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            semantic_domain MEDIUMTEXT COMMENT 'Semantic Domain', -- 需求点：语义分析的结果
            agent_card MEDIUMTEXT COMMENT 'Agent Card',           -- 需求点：用于创建agent的信息
            dd_namespace VARCHAR(255) COMMENT 'DD namespace',
            dd_name VARCHAR(255) COMMENT 'DD name',
            descriptor_type VARCHAR(64) COMMENT 'Descriptor type (code/structured/unstructured)',
            version VARCHAR(32) COMMENT 'Version, incremented on each update',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
            INDEX idx_semantic_domain (semantic_domain(255)),
            INDEX idx_dd_name (dd_name),
            INDEX idx_descriptor_type (descriptor_type),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='semantic domain information table'
        """
        
        # Expected columns and their definitions
        expected_columns = {
            'semantic_domain_id': 'VARCHAR(255)',
            'semantic_domain': 'MEDIUMTEXT',
            'agent_card': 'MEDIUMTEXT',
            'dd_namespace': 'VARCHAR(255)',
            'dd_name': 'VARCHAR(255)',
            'descriptor_type': 'VARCHAR(64)',
            'version': 'VARCHAR(32)',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP'
        }
        
        try:
            async with self._get_cursor() as cursor:
                # Check if table exists
                await cursor.execute("SHOW TABLES LIKE 'semantic_domain'")
                table_exists = await cursor.fetchone()
                
                if not table_exists:
                    # Create table if it doesn't exist
                    await cursor.execute(create_table_query)
                    logger.info("Semantic domain table created")
                else:
                    # Table exists, check and update structure
                    # Check existing columns
                    await cursor.execute("DESCRIBE semantic_domain")
                    columns = await cursor.fetchall()
                    existing_column_names = {col['Field'] for col in columns}
                    
                    # Add missing columns
                    for col_name, col_type in expected_columns.items():
                        if col_name not in existing_column_names:
                            if col_name == 'created_at':
                                alter_query = f"ALTER TABLE semantic_domain ADD COLUMN {col_name} {col_type} DEFAULT CURRENT_TIMESTAMP COMMENT '{'Creation time' if col_name == 'created_at' else 'Update time'}'"
                            elif col_name == 'updated_at':
                                alter_query = f"ALTER TABLE semantic_domain ADD COLUMN {col_name} {col_type} DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time'"
                            else:
                                comment_map = {
                                    'semantic_domain_id': 'Primary key',
                                    'semantic_domain': 'Semantic Domain',
                                    'agent_card': 'Agent Card',
                                    'dd_namespace': 'DD namespace',
                                    'dd_name': 'DD name',
                                    'descriptor_type': 'Descriptor type (code/structured/unstructured)',
                                    'version': 'Version incremented on each update'
                                }
                                alter_query = f"ALTER TABLE semantic_domain ADD COLUMN {col_name} {col_type} COMMENT '{comment_map.get(col_name, '')}'"
                            
                            await cursor.execute(alter_query)
                            logger.info(f"Added missing column: {col_name}")
                    
                    # Check and add missing indexes
                    await cursor.execute("SHOW INDEXES FROM semantic_domain")
                    indexes = await cursor.fetchall()
                    index_names = {idx['Key_name'] for idx in indexes}
                    
                    if 'idx_semantic_domain' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_domain ADD INDEX idx_semantic_domain (semantic_domain(255))")
                        logger.info("Added missing index: idx_semantic_domain")
                    
                    if 'idx_dd_name' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_domain ADD INDEX idx_dd_name (dd_name)")
                        logger.info("Added missing index: idx_dd_name")
                    
                    if 'idx_descriptor_type' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_domain ADD INDEX idx_descriptor_type (descriptor_type)")
                        logger.info("Added missing index: idx_descriptor_type")
                    
                    if 'idx_created_at' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_domain ADD INDEX idx_created_at (created_at)")
                        logger.info("Added missing index: idx_created_at")
                    
                    logger.info("Semantic domain table structure checked and updated if needed")
                    
            logger.info("Semantic domain table creation/check completed")
        except Error as e:
            logger.error(f"Table creation/update error: {e}")
            raise
    
    async def create(self, semantic_domain: SemanticDomain) -> bool:
        """
        create SemanticDomain record
        
        Args:
            semantic_domain: SemanticDomain object
            
        Returns:
            bool: Whether the operation was successful
        """
        # Generate ID if not provided
        if not semantic_domain.semantic_domain_id:
            semantic_domain.semantic_domain_id = str(uuid.uuid4())
        
        insert_query = """
        INSERT INTO semantic_domain 
        (semantic_domain_id, semantic_domain, agent_card, dd_namespace, dd_name, descriptor_type, version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        version = getattr(semantic_domain, 'version', None) or '1'
        values = (
            semantic_domain.semantic_domain_id,
            semantic_domain.semantic_domain,
            semantic_domain.agent_card,
            semantic_domain.dd_namespace,
            semantic_domain.dd_name,
            semantic_domain.descriptor_type,
            version
        )
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, values)
                return result > 0
        except Error as e:
            logger.error(f"Error creating semantic domain record: {e}")
            return False
    
    async def batch_create(self, semantic_domains: List[SemanticDomain]) -> bool:
        """
        batch create SemanticDomains
        
        Args:
            semantic_domains: List of SemanticDomain objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO semantic_domain 
        (semantic_domain_id, semantic_domain, agent_card, dd_namespace, dd_name, descriptor_type, version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = []
                    for domain in semantic_domains:
                        # Generate ID if not provided
                        if not domain.semantic_domain_id:
                            domain.semantic_domain_id = str(uuid.uuid4())
                        version = getattr(domain, 'version', None) or '1'
                        data.append((
                            domain.semantic_domain_id,
                            domain.semantic_domain,
                            domain.agent_card,
                            domain.dd_namespace,
                            domain.dd_name,
                            domain.descriptor_type,
                            version
                        ))
                    
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(semantic_domains)
        except Error as e:
            logger.error(f"Batch create semantic domain records error: {e}")
            return False
    
    async def get_by_id(self, semantic_domain_id: str) -> Optional[SemanticDomain]:
        """
        Retrieve semantic domain record by primary key semantic_domain_id

        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            Optional[SemanticDomain]: Found SemanticDomain object, returns None if not found
        """
        select_query = "SELECT * FROM semantic_domain WHERE semantic_domain_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (semantic_domain_id,))
                result = await cursor.fetchone()
                
                if result:
                    return SemanticDomain(
                        semantic_domain_id=result['semantic_domain_id'],
                        semantic_domain=result['semantic_domain'],
                        agent_card=result['agent_card'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        descriptor_type=result.get('descriptor_type'),
                        version=result.get('version'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    )
                return None
        except Error as e:
            logger.error(f"Query semantic domain record error: {e}")
            return None

    async def get_by_dd_info(self, dd_namespace: str, dd_name: str) -> List[SemanticDomain]:
        """
        Retrieve semantic domain records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            List[SemanticDomain]: List of found SemanticDomain objects
        """
        select_query = "SELECT * FROM semantic_domain WHERE dd_namespace = %s AND dd_name = %s ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (dd_namespace, dd_name))
                results = await cursor.fetchall()
                
                domains = []
                for result in results:
                    domains.append(SemanticDomain(
                        semantic_domain_id=result['semantic_domain_id'],
                        semantic_domain=result['semantic_domain'],
                        agent_card=result['agent_card'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        descriptor_type=result.get('descriptor_type'),
                        version=result.get('version'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return domains
        except Error as e:
            logger.error(f"Query DD information record error: {e}")
            return []
    
    async def get_all(self, page: int = None, page_size: int = None) -> List[SemanticDomain]:
        """
        Get all semantic domain records (supports pagination)

        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            List[SemanticDomain]: List of semantic domain records
        """
        base_query = "SELECT * FROM semantic_domain ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                if page is not None and page_size is not None:
                    offset = (page - 1) * page_size
                    await cursor.execute(f"{base_query} LIMIT %s OFFSET %s", (page_size, offset))
                else:
                    await cursor.execute(base_query)
                
                results = await cursor.fetchall()
                
                domains = []
                for result in results:
                    domains.append(SemanticDomain(
                        semantic_domain_id=result['semantic_domain_id'],
                        semantic_domain=result['semantic_domain'],
                        agent_card=result['agent_card'],
                        dd_namespace=result['dd_namespace'],
                        dd_name=result['dd_name'],
                        descriptor_type=result.get('descriptor_type'),
                        version=result.get('version'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return domains
        except Error as e:
            logger.error(f"Query all records error: {e}")
            return []
    
    async def update(self, semantic_domain_id: str, semantic_domain: SemanticDomain) -> bool:
        """
        Update semantic domain record

        Args:
            semantic_domain_id: Primary key of the record to update
            semantic_domain: New semantic domain data
            
        Returns:
            bool: Whether the operation was successful
        """
        update_query = """
        UPDATE semantic_domain 
        SET semantic_domain = %s, agent_card = %s, dd_namespace = %s, dd_name = %s, descriptor_type = %s, version = %s, updated_at = CURRENT_TIMESTAMP
        WHERE semantic_domain_id = %s
        """
        version = getattr(semantic_domain, 'version', None) or '1'
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, (
                    semantic_domain.semantic_domain,
                    semantic_domain.agent_card,
                    semantic_domain.dd_namespace,
                    semantic_domain.dd_name,
                    semantic_domain.descriptor_type,
                    version,
                    semantic_domain_id
                ))
                return result > 0
        except Error as e:
            logger.error(f"Update semantic domain record error: {e}")
            return False
    
    async def delete(self, semantic_domain_id: str) -> bool:
        """
        Delete semantic domain record

        Args:
            semantic_domain_id: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM semantic_domain WHERE semantic_domain_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (semantic_domain_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete semantic domain record error: {e}")
            return False

    async def delete_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Delete semantic domain records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM semantic_domain WHERE dd_namespace = %s AND dd_name = %s"
        
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
        base_query = "SELECT COUNT(*) as total FROM semantic_domain"
        
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
    
    async def exists(self, semantic_domain_id: str) -> bool:
        """
        Check if record exists

        Args:
            semantic_domain_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_by_id(semantic_domain_id) is not None

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
