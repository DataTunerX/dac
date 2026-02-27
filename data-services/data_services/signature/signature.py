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
from ..api.base import Signature
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncSignatureService:
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
                # Commit happens after the cursor context exits
                await connection.commit()
                logger.debug("Transaction committed successfully")
        except Error as e:
            if connection:
                await connection.rollback()
                logger.error(f"Database operation error, rolled back: {e}")
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
        CREATE TABLE IF NOT EXISTS signatures (
            sig_id VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            sig_type ENUM('application', 'database', 'api', 'file_system') NOT NULL,
            discovery_mode ENUM('auto', 'manual') NOT NULL, -- 需求点：支持自动与手动生成
            fingerprint VARCHAR(255) NOT NULL COMMENT 'Fingerprint', -- 特征指纹（如元数据计算出的 Hash），用于检测变更
            location_info JSON,                       -- 需求点：存储位置（IP, URL, DB_Instance等）
            metadata_content JSON,                    -- 需求点：存储表结构、字段、类型等详细元数据
            dd_namespace VARCHAR(255) COMMENT 'DD namespace',
            dd_name VARCHAR(255) COMMENT 'DD name',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
            INDEX idx_fingerprint (fingerprint),
            INDEX idx_dd_name (dd_name),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Fingerprint information table'
        """
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(create_table_query)
                
                # Check if table exists and update structure if needed
                await cursor.execute("SHOW TABLES LIKE 'signatures'")
                table_exists = await cursor.fetchone()
                
                if table_exists:
                    # Check and add missing columns
                    await cursor.execute("DESCRIBE signatures")
                    columns = await cursor.fetchall()
                    column_names = {col['Field']: col for col in columns}
                    
                    # Modify sig_id column if it's not VARCHAR(255)
                    if 'sig_id' in column_names:
                        sig_id_col = column_names['sig_id']
                        if 'varchar' not in sig_id_col['Type'].lower():
                            # Check if there's a primary key constraint
                            await cursor.execute("""
                                SELECT CONSTRAINT_NAME 
                                FROM information_schema.TABLE_CONSTRAINTS 
                                WHERE TABLE_SCHEMA = DATABASE() 
                                AND TABLE_NAME = 'signatures' 
                                AND CONSTRAINT_TYPE = 'PRIMARY KEY'
                            """)
                            pk_constraint = await cursor.fetchone()
                            
                            if pk_constraint:
                                # Drop primary key constraint
                                await cursor.execute("ALTER TABLE signatures DROP PRIMARY KEY")
                            
                            # Modify column type
                            await cursor.execute("ALTER TABLE signatures MODIFY COLUMN sig_id VARCHAR(255) COMMENT 'Primary key'")
                            
                            # Re-add primary key
                            await cursor.execute("ALTER TABLE signatures ADD PRIMARY KEY (sig_id)")
                            logger.info("Modified sig_id column to VARCHAR(255)")
                    
                    # Handle sig_name field if it exists (add default value or make it nullable)
                    if 'sig_name' in column_names:
                        sig_name_col = column_names['sig_name']
                        if sig_name_col['Null'] == 'NO' and sig_name_col.get('Default') is None:
                            # Make it nullable or add default value
                            try:
                                await cursor.execute("ALTER TABLE signatures MODIFY COLUMN sig_name VARCHAR(255) DEFAULT NULL")
                                logger.info("Modified sig_name column to allow NULL")
                            except Exception as e:
                                logger.warning(f"Could not modify sig_name column: {e}")
                    
                    # Add missing columns
                    if 'sig_type' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN sig_type ENUM('application', 'database', 'api', 'file_system') NOT NULL DEFAULT 'application' AFTER sig_id")
                    
                    if 'discovery_mode' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN discovery_mode ENUM('auto', 'manual') NOT NULL DEFAULT 'auto' AFTER sig_type")
                    
                    if 'fingerprint' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN fingerprint VARCHAR(255) NOT NULL COMMENT 'Fingerprint' AFTER discovery_mode")
                    
                    if 'location_info' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN location_info JSON AFTER fingerprint")
                    
                    if 'metadata_content' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN metadata_content JSON AFTER location_info")
                    
                    if 'dd_namespace' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN dd_namespace VARCHAR(255) COMMENT 'DD namespace' AFTER metadata_content")
                    
                    if 'dd_name' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN dd_name VARCHAR(255) COMMENT 'DD name' AFTER dd_namespace")
                    
                    if 'created_at' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time' AFTER dd_name")
                    
                    if 'updated_at' not in column_names:
                        await cursor.execute("ALTER TABLE signatures ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time' AFTER created_at")
                    
                    # Check and add missing indexes
                    await cursor.execute("SHOW INDEXES FROM signatures")
                    indexes = await cursor.fetchall()
                    index_names = [idx['Key_name'] for idx in indexes]
                    
                    if 'idx_fingerprint' not in index_names:
                        await cursor.execute("ALTER TABLE signatures ADD INDEX idx_fingerprint (fingerprint)")
                    
                    if 'idx_dd_name' not in index_names:
                        await cursor.execute("ALTER TABLE signatures ADD INDEX idx_dd_name (dd_name)")
                    
                    if 'idx_created_at' not in index_names:
                        await cursor.execute("ALTER TABLE signatures ADD INDEX idx_created_at (created_at)")
                    
                    logger.info("Signature table structure updated")
                else:
                    logger.info("Signature table created")
                    
            logger.info("Signature table creation/check completed")
        except Error as e:
            logger.error(f"Table creation/update error: {e}")
            raise
    
    async def create(self, signature: Signature) -> bool:
        """
        create Signature
        Args:
            signature: Signature object
            
        Returns:
            bool: Whether the operation was successful
        """
        # Check if sig_name column exists and include it in INSERT if needed
        # Check if sig_name column exists
        async with self._get_connection() as conn:
            async with conn.cursor() as check_cursor:
                await check_cursor.execute("DESCRIBE signatures")
                columns = await check_cursor.fetchall()
                column_names = [col['Field'] for col in columns]
                has_sig_name = 'sig_name' in column_names
        
        if has_sig_name:
            insert_query = """
            INSERT INTO signatures 
            (sig_id, sig_name, sig_type, discovery_mode, fingerprint, location_info, metadata_content, dd_namespace, dd_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                signature.sig_id,  # sig_id
                signature.sig_id,  # sig_name (use sig_id as default)
                signature.sig_type,  # sig_type
                signature.discovery_mode,  # discovery_mode
                signature.fingerprint,  # fingerprint
                json.dumps(signature.location_info) if signature.location_info else None,  # location_info
                json.dumps(signature.metadata_content) if signature.metadata_content else None,  # metadata_content
                signature.dd_namespace,  # dd_namespace
                signature.dd_name  # dd_name
            )
        else:
            insert_query = """
            INSERT INTO signatures 
            (sig_id, sig_type, discovery_mode, fingerprint, location_info, metadata_content, dd_namespace, dd_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                signature.sig_id,  # sig_id
                signature.sig_type,  # sig_type
                signature.discovery_mode,  # discovery_mode
                signature.fingerprint,  # fingerprint
                json.dumps(signature.location_info) if signature.location_info else None,  # location_info
                json.dumps(signature.metadata_content) if signature.metadata_content else None,  # metadata_content
                signature.dd_namespace,  # dd_namespace
                signature.dd_name  # dd_name
            )
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, values)
                return result > 0
        except Error as e:
            logger.error(f"Error creating record: {e}")
            return False
    
    async def batch_create(self, signatures: List[Signature]) -> bool:
        """
        batch create Signatures
        Args:
            signatures: List of Signature objects
            
        Returns:
            bool: Whether the operation was successful
        """
        # Check if sig_name column exists and include it in INSERT if needed
        # Check if sig_name column exists
        async with self._get_connection() as conn:
            async with conn.cursor() as check_cursor:
                await check_cursor.execute("DESCRIBE signatures")
                columns = await check_cursor.fetchall()
                column_names = [col['Field'] for col in columns]
                has_sig_name = 'sig_name' in column_names
        
        if has_sig_name:
            insert_query = """
            INSERT INTO signatures 
            (sig_id, sig_name, sig_type, discovery_mode, fingerprint, location_info, metadata_content, semantic_domain, agent_card, dd_namespace, dd_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        else:
            insert_query = """
            INSERT INTO signatures 
            (sig_id, sig_type, discovery_mode, fingerprint, location_info, metadata_content, dd_namespace, dd_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    if has_sig_name:
                        data = [(sig.sig_id,  # sig_id
                                sig.sig_id,  # sig_name (use sig_id as default)
                                sig.sig_type,  # sig_type
                                sig.discovery_mode,  # discovery_mode
                                sig.fingerprint,  # fingerprint
                                json.dumps(sig.location_info) if sig.location_info else None,  # location_info
                                json.dumps(sig.metadata_content) if sig.metadata_content else None,  # metadata_content
                                sig.dd_namespace,  # dd_namespace
                                sig.dd_name)  # dd_name
                                for sig in signatures]
                    else:
                        data = [(sig.sig_id,  # sig_id
                                sig.sig_type,  # sig_type
                                sig.discovery_mode,  # discovery_mode
                                sig.fingerprint,  # fingerprint
                                json.dumps(sig.location_info) if sig.location_info else None,  # location_info
                                json.dumps(sig.metadata_content) if sig.metadata_content else None,  # metadata_content
                                sig.dd_namespace,  # dd_namespace
                                sig.dd_name)  # dd_name
                                for sig in signatures]
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(signatures)
        except Error as e:
            logger.error(f"Batch create records error: {e}")
            return False
    
    async def get_by_fid(self, sig_id: str) -> Optional[Signature]:
        """
        Retrieve signature record by primary key sig_id

        Args:
            sig_id: Primary key ID
            
        Returns:
            Optional[Signature]: Found Signature object, returns None if not found
        """
        select_query = "SELECT * FROM signatures WHERE sig_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (sig_id,))
                result = await cursor.fetchone()
                
                if result:
                    location_info = json.loads(result['location_info']) if result.get('location_info') else None
                    metadata_content = json.loads(result['metadata_content']) if result.get('metadata_content') else None
                    return Signature(
                        sig_id=str(result['sig_id']),  # Convert to string
                        sig_type=result.get('sig_type', 'application'),
                        discovery_mode=result.get('discovery_mode', 'auto'),
                        fingerprint=result.get('fingerprint', ''),
                        location_info=location_info,
                        metadata_content=metadata_content,
                        dd_namespace=result.get('dd_namespace'),
                        dd_name=result.get('dd_name'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    )
                return None
        except Error as e:
            logger.error(f"Query record error: {e}")
            return None
    
    async def get_by_signature_id(self, signature_id: str) -> Optional[Signature]:
        """
        Retrieve signature record by fingerprint

        Args:
            signature_id: Fingerprint value (signature identifier)
            
        Returns:
            Optional[Signature]: Found Signature object, returns None if not found
        """
        select_query = "SELECT * FROM signatures WHERE fingerprint = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (signature_id,))
                result = await cursor.fetchone()
                
                if result:
                    location_info = json.loads(result['location_info']) if result.get('location_info') else None
                    metadata_content = json.loads(result['metadata_content']) if result.get('metadata_content') else None
                    return Signature(
                        sig_id=str(result['sig_id']),  # Convert to string
                        sig_type=result.get('sig_type', 'application'),
                        discovery_mode=result.get('discovery_mode', 'auto'),
                        fingerprint=result.get('fingerprint', ''),
                        location_info=location_info,
                        metadata_content=metadata_content,
                        dd_namespace=result.get('dd_namespace'),
                        dd_name=result.get('dd_name'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    )
                return None
        except Error as e:
            logger.error(f"Query record error: {e}")
            return None

    async def get_by_dd_info(self, dd_namespace: str, dd_name: str) -> List[Signature]:
        """
        Retrieve signature records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            List[Signature]: List of found Signature objects
        """
        select_query = "SELECT * FROM signatures WHERE dd_namespace = %s AND dd_name = %s ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (dd_namespace, dd_name))
                results = await cursor.fetchall()
                
                signatures = []
                for result in results:
                    location_info = json.loads(result['location_info']) if result.get('location_info') else None
                    metadata_content = json.loads(result['metadata_content']) if result.get('metadata_content') else None
                    signatures.append(Signature(
                        sig_id=str(result['sig_id']),  # Convert to string
                        sig_type=result.get('sig_type', 'application'),
                        discovery_mode=result.get('discovery_mode', 'auto'),
                        fingerprint=result.get('fingerprint', ''),
                        location_info=location_info,
                        metadata_content=metadata_content,
                        dd_namespace=result.get('dd_namespace'),
                        dd_name=result.get('dd_name'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return signatures
        except Error as e:
            logger.error(f"Query DD information record error: {e}")
            return []
    
    async def get_all(self, page: int = None, page_size: int = None) -> List[Signature]:
        """
        Get all signature records (supports pagination)

        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            List[Signature]: List of signature records
        """
        base_query = "SELECT * FROM signatures ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                if page is not None and page_size is not None:
                    offset = (page - 1) * page_size
                    await cursor.execute(f"{base_query} LIMIT %s OFFSET %s", (page_size, offset))
                else:
                    await cursor.execute(base_query)
                
                results = await cursor.fetchall()
                
                signatures = []
                for result in results:
                    location_info = json.loads(result['location_info']) if result.get('location_info') else None
                    metadata_content = json.loads(result['metadata_content']) if result.get('metadata_content') else None
                    signatures.append(Signature(
                        sig_id=str(result['sig_id']),  # Convert to string
                        sig_type=result.get('sig_type', 'application'),
                        discovery_mode=result.get('discovery_mode', 'auto'),
                        fingerprint=result.get('fingerprint', ''),
                        location_info=location_info,
                        metadata_content=metadata_content,
                        dd_namespace=result.get('dd_namespace'),
                        dd_name=result.get('dd_name'),
                        created_at=result.get('created_at'),
                        updated_at=result.get('updated_at')
                    ))
                
                return signatures
        except Error as e:
            logger.error(f"Query all records error: {e}")
            return []
    
    async def update(self, sig_id: str, signature: Signature) -> bool:
        """
        Update signature record

        Args:
            sig_id: Primary key of the record to update
            signature: New signature data
            
        Returns:
            bool: Whether the operation was successful
        """
        update_query = """
        UPDATE signatures 
        SET sig_type = %s, discovery_mode = %s, fingerprint = %s, location_info = %s, metadata_content = %s, 
            dd_namespace = %s, dd_name = %s
        WHERE sig_id = %s
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, (
                    signature.sig_type,  # sig_type
                    signature.discovery_mode,  # discovery_mode
                    signature.fingerprint,  # fingerprint
                    json.dumps(signature.location_info) if signature.location_info else None,  # location_info
                    json.dumps(signature.metadata_content) if signature.metadata_content else None,  # metadata_content
                    signature.dd_namespace,  # dd_namespace
                    signature.dd_name,  # dd_name
                    sig_id  # sig_id (WHERE clause)
                ))
                return result > 0
        except Error as e:
            logger.error(f"Update record error: {e}")
            return False
    
    async def delete(self, sig_id: str) -> bool:
        """
        Delete signature record

        Args:
            sig_id: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM signatures WHERE sig_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (sig_id,))
                return result > 0
        except Error as e:
            logger.error(f"delete record error: {e}")
            return False

    async def delete_by_dd_info(self, dd_namespace: str, dd_name: str) -> bool:
        """
        Delete signature records by DD namespace and DD name

        Args:
            dd_namespace: DD namespace
            dd_name: DD name
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM signatures WHERE dd_namespace = %s AND dd_name = %s"
        
        try:
            # First, check how many records exist before deletion
            count_before = await self.count("dd_namespace = %s AND dd_name = %s", (dd_namespace, dd_name))
            logger.info(f"Before deletion: {count_before} signature record(s) found for DD: namespace='{dd_namespace}', name='{dd_name}'")
            
            if count_before == 0:
                logger.warning(f"No signature records found to delete for DD: namespace='{dd_namespace}', name='{dd_name}'")
                return False
            
            # Execute delete operation with explicit transaction management
            connection = None
            try:
                if self.pool is None:
                    await self.initialize()
                connection = await self.pool.acquire()
                
                async with connection.cursor() as cursor:
                    result = await cursor.execute(delete_query, (dd_namespace, dd_name))
                    affected_rows = cursor.rowcount if hasattr(cursor, 'rowcount') else result
                    logger.info(f"Delete query executed: affected_rows={affected_rows}, result={result} for DD: namespace='{dd_namespace}', name='{dd_name}'")
                
                # Explicitly commit the transaction
                await connection.commit()
                logger.info(f"Transaction committed for DD: namespace='{dd_namespace}', name='{dd_name}'")
                
            except Error as e:
                if connection:
                    await connection.rollback()
                    logger.error(f"Delete operation error, rolled back: {e}")
                raise
            finally:
                if connection:
                    self.pool.release(connection)
            
            # Verify deletion after commit (using a new connection)
            count_after = await self.count("dd_namespace = %s AND dd_name = %s", (dd_namespace, dd_name))
            logger.info(f"After deletion (after commit): {count_after} signature record(s) remain for DD: namespace='{dd_namespace}', name='{dd_name}'")
            
            if count_after == 0:
                return True
            elif count_after < count_before:
                # Some records were deleted but not all
                logger.warning(f"Partial deletion: {count_before - count_after} record(s) deleted, {count_after} record(s) still exist for DD: namespace='{dd_namespace}', name='{dd_name}'")
                return True  # Consider partial deletion as success
            else:
                # No records were deleted
                logger.error(f"Deletion failed: {count_before} record(s) before, {count_after} record(s) after. No records were deleted for DD: namespace='{dd_namespace}', name='{dd_name}'")
                return False
        except Error as e:
            logger.error(f"Delete DD information record error: {e}", exc_info=True)
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
        base_query = "SELECT COUNT(*) as total FROM signatures"
        
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
    
    async def exists(self, sig_id: str) -> bool:
        """
        Check if record exists

        Args:
            sig_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_by_fid(sig_id) is not None

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