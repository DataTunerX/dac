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
from ..api.base import SemanticGroup, DDGroupRelation
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AsyncSemanticGroupService:
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
        create_semantic_groups_table_query = """
        CREATE TABLE IF NOT EXISTS semantic_groups (
            id VARCHAR(255) PRIMARY KEY COMMENT 'Primary key',
            group_name VARCHAR(255) NOT NULL COMMENT 'Group name',
            description MEDIUMTEXT COMMENT 'Group description',
            agent_card MEDIUMTEXT COMMENT 'Agent Card',
            version VARCHAR(20) COMMENT 'Version',
            parent_id VARCHAR(255) DEFAULT NULL COMMENT 'Parent group ID (NULL = root or leaf)',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
            INDEX idx_group_name (group_name),
            INDEX idx_created_at (created_at),
            INDEX idx_parent_id (parent_id),
            FOREIGN KEY (parent_id) REFERENCES semantic_groups(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='semantic groups table'
        """
        
        create_dd_group_relation_table_query = """
        CREATE TABLE IF NOT EXISTS dd_group_relation (
            id SERIAL PRIMARY KEY COMMENT 'Primary key',
            sd_id VARCHAR(255) NOT NULL COMMENT 'Semantic domain ID',
            group_id VARCHAR(255) NOT NULL COMMENT 'Group ID',
            association_reason MEDIUMTEXT COMMENT 'Reason for association',
            UNIQUE(sd_id, group_id),
            INDEX idx_sd_id (sd_id),
            INDEX idx_group_id (group_id),
            FOREIGN KEY (group_id) REFERENCES semantic_groups(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DD group relation table'
        """
        
        # Expected columns for semantic_groups
        expected_semantic_groups_columns = {
            'id': 'VARCHAR(255)',
            'group_name': 'VARCHAR(255)',
            'description': 'MEDIUMTEXT',
            'agent_card': 'MEDIUMTEXT',
            'version': 'VARCHAR(20)',
            'parent_id': 'VARCHAR(255)',
            'created_at': 'TIMESTAMP'
        }
        
        # Expected columns for dd_group_relation
        expected_dd_group_relation_columns = {
            'id': 'SERIAL',
            'sd_id': 'VARCHAR(255)',
            'group_id': 'VARCHAR(255)',
            'association_reason': 'MEDIUMTEXT'
        }
        
        try:
            async with self._get_cursor() as cursor:
                # Check if semantic_groups table exists
                await cursor.execute("SHOW TABLES LIKE 'semantic_groups'")
                semantic_groups_exists = await cursor.fetchone()
                
                if not semantic_groups_exists:
                    # Create semantic_groups table if it doesn't exist
                    await cursor.execute(create_semantic_groups_table_query)
                    logger.info("Semantic groups table created")
                else:
                    # Table exists, check and update structure
                    await cursor.execute("DESCRIBE semantic_groups")
                    columns = await cursor.fetchall()
                    existing_column_names = {col['Field'] for col in columns}
                    
                    # Add missing columns
                    for col_name, col_type in expected_semantic_groups_columns.items():
                        if col_name not in existing_column_names:
                            if col_name == 'created_at':
                                alter_query = f"ALTER TABLE semantic_groups ADD COLUMN {col_name} {col_type} DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time'"
                            elif col_name == 'parent_id':
                                alter_query = f"ALTER TABLE semantic_groups ADD COLUMN parent_id VARCHAR(255) DEFAULT NULL COMMENT 'Parent group ID (NULL = root or leaf)'"
                            else:
                                comment_map = {
                                    'id': 'Primary key',
                                    'group_name': 'Group name',
                                    'description': 'Group description',
                                    'agent_card': 'Agent Card',
                                    'version': 'Version'
                                }
                                alter_query = f"ALTER TABLE semantic_groups ADD COLUMN {col_name} {col_type} COMMENT '{comment_map.get(col_name, '')}'"
                            
                            await cursor.execute(alter_query)
                            logger.info(f"Added missing column to semantic_groups: {col_name}")
                    
                    # Check and add missing indexes
                    await cursor.execute("SHOW INDEXES FROM semantic_groups")
                    indexes = await cursor.fetchall()
                    index_names = {idx['Key_name'] for idx in indexes}
                    
                    if 'idx_group_name' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_groups ADD INDEX idx_group_name (group_name)")
                        logger.info("Added missing index: idx_group_name")
                    
                    if 'idx_created_at' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_groups ADD INDEX idx_created_at (created_at)")
                        logger.info("Added missing index: idx_created_at")
                    
                    if 'idx_parent_id' not in index_names:
                        await cursor.execute("ALTER TABLE semantic_groups ADD INDEX idx_parent_id (parent_id)")
                        logger.info("Added missing index: idx_parent_id")
                
                # Check if dd_group_relation table exists
                await cursor.execute("SHOW TABLES LIKE 'dd_group_relation'")
                dd_group_relation_exists = await cursor.fetchone()
                
                if not dd_group_relation_exists:
                    # Create dd_group_relation table if it doesn't exist
                    await cursor.execute(create_dd_group_relation_table_query)
                    logger.info("DD group relation table created")
                else:
                    # Table exists, check and update structure
                    await cursor.execute("DESCRIBE dd_group_relation")
                    columns = await cursor.fetchall()
                    existing_column_names = {col['Field'] for col in columns}
                    
                    # Add missing columns
                    for col_name, col_type in expected_dd_group_relation_columns.items():
                        if col_name not in existing_column_names:
                            comment_map = {
                                'id': 'Primary key',
                                'sd_id': 'Semantic domain ID',
                                'group_id': 'Group ID',
                                'association_reason': 'Reason for association'
                            }
                            alter_query = f"ALTER TABLE dd_group_relation ADD COLUMN {col_name} {col_type} COMMENT '{comment_map.get(col_name, '')}'"
                            await cursor.execute(alter_query)
                            logger.info(f"Added missing column to dd_group_relation: {col_name}")
                    
                    # Check and add missing indexes
                    await cursor.execute("SHOW INDEXES FROM dd_group_relation")
                    indexes = await cursor.fetchall()
                    index_names = {idx['Key_name'] for idx in indexes}
                    
                    if 'idx_sd_id' not in index_names:
                        await cursor.execute("ALTER TABLE dd_group_relation ADD INDEX idx_sd_id (sd_id)")
                        logger.info("Added missing index: idx_sd_id")
                    
                    if 'idx_group_id' not in index_names:
                        await cursor.execute("ALTER TABLE dd_group_relation ADD INDEX idx_group_id (group_id)")
                        logger.info("Added missing index: idx_group_id")
                    
                    # Check unique constraint
                    await cursor.execute("SHOW INDEXES FROM dd_group_relation WHERE Key_name = 'sd_id'")
                    unique_check = await cursor.fetchall()
                    # Note: MySQL doesn't have a direct way to check unique constraints via SHOW INDEXES
                    # We'll rely on the table creation to handle this
                
                logger.info("Semantic group tables creation/check completed")
        except Error as e:
            logger.error(f"Table creation/update error: {e}")
            raise
    
    # SemanticGroup CRUD operations
    async def create_group(self, semantic_group: SemanticGroup) -> bool:
        """
        create SemanticGroup record
        
        Args:
            semantic_group: SemanticGroup object
            
        Returns:
            bool: Whether the operation was successful
        """
        # Generate ID if not provided
        if not semantic_group.id:
            semantic_group.id = str(uuid.uuid4())
        
        insert_query = """
        INSERT INTO semantic_groups 
        (id, group_name, description, agent_card, version, parent_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        values = (
            semantic_group.id,
            semantic_group.group_name,
            semantic_group.description,
            semantic_group.agent_card,
            semantic_group.version,
            getattr(semantic_group, 'parent_id', None)
        )
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, values)
                return result > 0
        except Error as e:
            logger.error(f"Error creating semantic group record: {e}")
            return False
    
    async def batch_create_groups(self, semantic_groups: List[SemanticGroup]) -> bool:
        """
        batch create SemanticGroups
        
        Args:
            semantic_groups: List of SemanticGroup objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO semantic_groups 
        (id, group_name, description, agent_card, version, parent_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = []
                    for group in semantic_groups:
                        # Generate ID if not provided
                        if not group.id:
                            group.id = str(uuid.uuid4())
                        
                        data.append((
                            group.id,
                            group.group_name,
                            group.description,
                            group.agent_card,
                            group.version,
                            getattr(group, 'parent_id', None)
                        ))
                    
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(semantic_groups)
        except Error as e:
            logger.error(f"Batch create semantic group records error: {e}")
            return False
    
    async def get_group_by_id(self, group_id: str) -> Optional[SemanticGroup]:
        """
        Retrieve semantic group record by primary key id

        Args:
            group_id: Primary key ID
            
        Returns:
            Optional[SemanticGroup]: Found SemanticGroup object, returns None if not found
        """
        select_query = "SELECT * FROM semantic_groups WHERE id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (group_id,))
                result = await cursor.fetchone()
                
                if result:
                    return SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    )
                return None
        except Error as e:
            logger.error(f"Query semantic group record error: {e}")
            return None
    
    async def get_all_groups(self, page: int = None, page_size: int = None) -> List[SemanticGroup]:
        """
        Get all semantic group records (supports pagination)

        Args:
            page: Page number (starting from 1)
            page_size: Page size
            
        Returns:
            List[SemanticGroup]: List of semantic group records
        """
        base_query = "SELECT * FROM semantic_groups ORDER BY created_at DESC"
        
        try:
            async with self._get_cursor() as cursor:
                if page is not None and page_size is not None:
                    offset = (page - 1) * page_size
                    await cursor.execute(f"{base_query} LIMIT %s OFFSET %s", (page_size, offset))
                else:
                    await cursor.execute(base_query)
                
                results = await cursor.fetchall()
                
                groups = []
                for result in results:
                    groups.append(SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    ))
                
                return groups
        except Error as e:
            logger.error(f"Query all records error: {e}")
            return []
    
    async def update_group(self, group_id: str, semantic_group: SemanticGroup) -> bool:
        """
        Update semantic group record

        Args:
            group_id: Primary key of the record to update
            semantic_group: New semantic group data
            
        Returns:
            bool: Whether the operation was successful
        """
        update_query = """
        UPDATE semantic_groups 
        SET group_name = %s, description = %s, agent_card = %s, version = %s, parent_id = %s
        WHERE id = %s
        """
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, (
                    semantic_group.group_name,
                    semantic_group.description,
                    semantic_group.agent_card,
                    semantic_group.version,
                    getattr(semantic_group, 'parent_id', None),
                    group_id
                ))
                return result > 0
        except Error as e:
            logger.error(f"Update semantic group record error: {e}")
            return False
    
    async def delete_group(self, group_id: str) -> bool:
        """
        Delete semantic group record (cascade delete relations)

        Args:
            group_id: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM semantic_groups WHERE id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (group_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete semantic group record error: {e}")
            return False
    
    async def count_groups(self, condition: str = None, params: tuple = None) -> int:
        """
        Get total record count

        Args:
            condition: Query condition (WHERE clause)
            params: Query parameters
            
        Returns:
            int: Total record count
        """
        base_query = "SELECT COUNT(*) as total FROM semantic_groups"
        
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
    
    async def exists_group(self, group_id: str) -> bool:
        """
        Check if record exists

        Args:
            group_id: Primary key ID
            
        Returns:
            bool: Whether it exists
        """
        return await self.get_group_by_id(group_id) is not None
    
    # DDGroupRelation CRUD operations
    async def create_relation(self, relation: DDGroupRelation) -> bool:
        """
        create DDGroupRelation record
        
        Args:
            relation: DDGroupRelation object
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO dd_group_relation 
        (sd_id, group_id, association_reason)
        VALUES (%s, %s, %s)
        """
        
        values = (
            relation.sd_id,
            relation.group_id,
            relation.association_reason
        )
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(insert_query, values)
                return result > 0
        except Error as e:
            logger.error(f"Error creating DD group relation record: {e}")
            return False
    
    async def batch_create_relations(self, relations: List[DDGroupRelation]) -> bool:
        """
        batch create DDGroupRelations
        
        Args:
            relations: List of DDGroupRelation objects
            
        Returns:
            bool: Whether the operation was successful
        """
        insert_query = """
        INSERT INTO dd_group_relation 
        (sd_id, group_id, association_reason)
        VALUES (%s, %s, %s)
        """
        
        try:
            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    data = []
                    for relation in relations:
                        data.append((
                            relation.sd_id,
                            relation.group_id,
                            relation.association_reason
                        ))
                    
                    affected_rows = 0
                    for item in data:
                        result = await cursor.execute(insert_query, item)
                        affected_rows += result
                    
                    await connection.commit()
                    return affected_rows == len(relations)
        except Error as e:
            logger.error(f"Batch create DD group relation records error: {e}")
            return False
    
    async def get_relations_by_group_id(self, group_id: str) -> List[DDGroupRelation]:
        """
        Retrieve DD group relations by group_id

        Args:
            group_id: Group ID
            
        Returns:
            List[DDGroupRelation]: List of found DDGroupRelation objects
        """
        select_query = "SELECT * FROM dd_group_relation WHERE group_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (group_id,))
                results = await cursor.fetchall()
                
                relations = []
                for result in results:
                    relations.append(DDGroupRelation(
                        id=result.get('id'),
                        sd_id=result['sd_id'],
                        group_id=result['group_id'],
                        association_reason=result.get('association_reason')
                    ))
                
                return relations
        except Error as e:
            logger.error(f"Query DD group relations by group_id error: {e}")
            return []
    
    async def get_relations_by_sd_id(self, sd_id: str) -> List[DDGroupRelation]:
        """
        Retrieve DD group relations by sd_id

        Args:
            sd_id: Semantic domain ID
            
        Returns:
            List[DDGroupRelation]: List of found DDGroupRelation objects
        """
        select_query = "SELECT * FROM dd_group_relation WHERE sd_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (sd_id,))
                results = await cursor.fetchall()
                
                relations = []
                for result in results:
                    relations.append(DDGroupRelation(
                        id=result.get('id'),
                        sd_id=result['sd_id'],
                        group_id=result['group_id'],
                        association_reason=result.get('association_reason')
                    ))
                
                return relations
        except Error as e:
            logger.error(f"Query DD group relations by sd_id error: {e}")
            return []
    
    async def delete_relation(self, relation_id: int) -> bool:
        """
        Delete DD group relation record

        Args:
            relation_id: Primary key of the record to delete
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM dd_group_relation WHERE id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (relation_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete DD group relation record error: {e}")
            return False
    
    async def delete_relations_by_group_id(self, group_id: str) -> bool:
        """
        Delete all DD group relations by group_id

        Args:
            group_id: Group ID
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM dd_group_relation WHERE group_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (group_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete DD group relations by group_id error: {e}")
            return False
    
    async def delete_relations_by_sd_id(self, sd_id: str) -> bool:
        """
        Delete all DD group relations by sd_id

        Args:
            sd_id: Semantic domain ID
            
        Returns:
            bool: Whether the operation was successful
        """
        delete_query = "DELETE FROM dd_group_relation WHERE sd_id = %s"
        
        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(delete_query, (sd_id,))
                return result > 0
        except Error as e:
            logger.error(f"Delete DD group relations by sd_id error: {e}")
            return False
    
    async def get_children_by_parent_id(self, parent_id: str) -> List[SemanticGroup]:
        """
        Retrieve child groups by parent_id.

        Args:
            parent_id: Parent group ID

        Returns:
            List[SemanticGroup]: List of child group records
        """
        select_query = "SELECT * FROM semantic_groups WHERE parent_id = %s ORDER BY created_at DESC"

        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query, (parent_id,))
                results = await cursor.fetchall()

                groups = []
                for result in results:
                    groups.append(SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    ))

                return groups
        except Error as e:
            logger.error(f"Query children by parent_id error: {e}")
            return []

    async def get_root_groups(self) -> List[SemanticGroup]:
        """
        Retrieve all root groups (parent_id IS NULL).

        Returns:
            List[SemanticGroup]: List of root group records
        """
        select_query = "SELECT * FROM semantic_groups WHERE parent_id IS NULL ORDER BY created_at DESC"

        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query)
                results = await cursor.fetchall()

                groups = []
                for result in results:
                    groups.append(SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    ))

                return groups
        except Error as e:
            logger.error(f"Query root groups error: {e}")
            return []

    async def get_leaf_groups_without_parent(self) -> List[SemanticGroup]:
        """
        Retrieve leaf groups that have SD members but no parent (candidates for merging).
        A leaf group has at least one dd_group_relation entry and parent_id IS NULL.

        Returns:
            List[SemanticGroup]: List of orphan leaf group records
        """
        select_query = """
        SELECT DISTINCT sg.* FROM semantic_groups sg
        INNER JOIN dd_group_relation dgr ON sg.id = dgr.group_id
        WHERE sg.parent_id IS NULL
        ORDER BY sg.created_at DESC
        """

        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query)
                results = await cursor.fetchall()

                groups = []
                for result in results:
                    groups.append(SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    ))

                return groups
        except Error as e:
            logger.error(f"Query leaf groups without parent error: {e}")
            return []

    async def update_parent_id(self, group_id: str, parent_id: Optional[str]) -> bool:
        """
        Update only the parent_id of a group.

        Args:
            group_id: Group to update
            parent_id: New parent group ID (None to unset)

        Returns:
            bool: Whether the operation was successful
        """
        update_query = "UPDATE semantic_groups SET parent_id = %s WHERE id = %s"

        try:
            async with self._get_cursor() as cursor:
                result = await cursor.execute(update_query, (parent_id, group_id))
                return result > 0
        except Error as e:
            logger.error(f"Update parent_id error: {e}")
            return False

    async def get_orphan_groups_with_members(self) -> List[SemanticGroup]:
        """
        Retrieve all groups with parent_id IS NULL that have at least one member
        (either SD relations or child groups). Used by hierarchical merge to find
        merge candidates at any level.

        Returns:
            List[SemanticGroup]: Orphan groups with members
        """
        select_query = """
        SELECT DISTINCT sg.* FROM semantic_groups sg
        LEFT JOIN dd_group_relation dgr ON sg.id = dgr.group_id
        LEFT JOIN semantic_groups child ON child.parent_id = sg.id
        WHERE sg.parent_id IS NULL
          AND (dgr.id IS NOT NULL OR child.id IS NOT NULL)
        ORDER BY sg.created_at DESC
        """

        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(select_query)
                results = await cursor.fetchall()

                groups = []
                for result in results:
                    groups.append(SemanticGroup(
                        id=result['id'],
                        group_name=result['group_name'],
                        description=result.get('description'),
                        agent_card=result.get('agent_card'),
                        version=result.get('version'),
                        parent_id=result.get('parent_id'),
                        created_at=result.get('created_at')
                    ))

                return groups
        except Error as e:
            logger.error(f"Query orphan groups with members error: {e}")
            return []

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
