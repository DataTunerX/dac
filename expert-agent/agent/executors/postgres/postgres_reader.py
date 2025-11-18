import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional, Iterable, Union, AsyncGenerator
from contextlib import asynccontextmanager
import logging
import json
import asyncio
import asyncpg
from asyncpg.pool import Pool
import threading
from dataclasses import dataclass
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("async_postgres_reader")

@dataclass
class PostgresConfig:
    host: str
    user: str
    password: str
    database: str
    port: int = 5432
    timeout: int = 30
    sslmode: str = 'prefer'
    application_name: str = 'AsyncPostgresReader'
    min_connections: int = 1
    max_connections: int = 1

class AsyncPostgresPoolManager:
    _instance = None
    _lock = asyncio.Lock()
    _pools: Dict[str, Pool] = {}
    
    @classmethod
    async def get_pool(cls, config: PostgresConfig) -> Pool:
        config_key = f"{config.host}:{config.port}:{config.database}:{config.user}"
        
        async with cls._lock:
            if config_key not in cls._pools:
                cls._pools[config_key] = await asyncpg.create_pool(
                    host=config.host,
                    port=config.port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    min_size=config.min_connections,
                    max_size=config.max_connections,
                    command_timeout=config.timeout,
                    ssl=config.sslmode if config.sslmode != 'prefer' else None
                )
            return cls._pools[config_key]
    
    @classmethod
    async def close_all(cls):
        async with cls._lock:
            for pool in cls._pools.values():
                await pool.close()
            cls._pools.clear()

class AsyncPostgresReader:
    
    def __init__(self, config: Union[Dict[str, Any], PostgresConfig]):
        if isinstance(config, dict):
            self.config = PostgresConfig(**config)
        else:
            self.config = config
            
        self._validate_config()
        self._pool: Optional[Pool] = None
        self._pool_lock = asyncio.Lock()
        self._is_closed = False

    def _validate_config(self):
        required_keys = ['host', 'user', 'password', 'database']
        for key in required_keys:
            if not hasattr(self.config, key) or getattr(self.config, key) is None:
                raise ValueError(
                    f"PostgreSQL configuration is missing required parameter: {key}"
                )

    async def _ensure_pool(self):
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    self._pool = await AsyncPostgresPoolManager.get_pool(self.config)

    @asynccontextmanager
    async def _get_connection(self):
        await self._ensure_pool()
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")
        
        connection = await self._pool.acquire()
        try:
            yield connection
        finally:
            await self._pool.release(connection)

    async def close(self):
        if not self._is_closed and self._pool:
            self._is_closed = True
            self._pool = None

    async def __aenter__(self):
        await self._ensure_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def test_connection(self) -> bool:
        try:
            async with self._get_connection() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    async def query(
        self,
        input: str,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and directly return result list (non-generator version)
        
        Args:
            input: SQL statement to execute
            parameters: Parameter dictionary
            **kwargs: Additional options
                - as_dict: Whether to return dictionary format (default True)
        
        Returns:
            Query results as a list of dictionaries
        """
        as_dict = kwargs.get('as_dict', True)
        
        async with self._get_connection() as conn:
            results = await self._fetch_all(conn, input, parameters, as_dict)
            return results

    async def _fetch_all(
        self,
        conn,
        input: str,
        parameters: Optional[Dict[str, Any]],
        as_dict: bool
    ) -> List[Dict[str, Any]]:
        results = await conn.fetch(input, *self._prepare_parameters(parameters))
        if as_dict:
            return [dict(record) for record in results]
        return results

    def _prepare_parameters(self, parameters: Optional[Dict[str, Any]]) -> list:
        if parameters is None:
            return []

        if isinstance(parameters, dict):
            return list(parameters.values())
        elif isinstance(parameters, (list, tuple)):
            return list(parameters)
        else:
            return [parameters]


    async def schema(self, table_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        try:
            tables_sql = """
                SELECT 
                    t.table_name,
                    pg_catalog.obj_description(pc.oid, 'pg_class') as table_comment
                FROM 
                    information_schema.tables t
                JOIN 
                    pg_class pc ON pc.relname = t.table_name
                JOIN 
                    pg_namespace pn ON pn.oid = pc.relnamespace AND pn.nspname = t.table_schema
                WHERE 
                    t.table_schema NOT IN ('pg_catalog', 'information_schema')
                    AND t.table_type = 'BASE TABLE'
            """

            params = []
            if table_names:
                placeholders = ','.join(['$' + str(i+1) for i in range(len(table_names))])
                tables_sql += f" AND t.table_name IN ({placeholders})"
                params.extend(table_names)
            
            tables_sql += " ORDER BY t.table_name"

            columns_sql = """
                SELECT 
                    c.table_name,
                    c.column_name,
                    c.udt_name || 
                    CASE 
                        WHEN c.character_maximum_length IS NOT NULL THEN '(' || c.character_maximum_length || ')'
                        WHEN c.numeric_precision IS NOT NULL AND c.numeric_scale IS NOT NULL 
                            THEN '(' || c.numeric_precision || ',' || c.numeric_scale || ')'
                        WHEN c.numeric_precision IS NOT NULL THEN '(' || c.numeric_precision || ')'
                        ELSE ''
                    END as column_type,
                    c.is_nullable,
                    CASE 
                        WHEN EXISTS (
                            SELECT 1 FROM pg_index i
                            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                            JOIN pg_class pc ON pc.oid = i.indrelid
                            WHERE i.indisprimary 
                            AND a.attname = c.column_name
                            AND pc.relname = c.table_name
                        ) THEN 'PRI'
                        ELSE ''
                    END as column_key,
                    c.column_default,
                    '' as extra,
                    pg_catalog.col_description(
                        (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                        c.ordinal_position
                    ) as column_comment
                FROM 
                    information_schema.columns c
                WHERE 
                    c.table_schema NOT IN ('pg_catalog', 'information_schema')
                    AND c.table_name = $1
                ORDER BY c.ordinal_position
            """
            
            async with self._get_connection() as conn:
                if params:
                    tables = await conn.fetch(tables_sql, *params)
                else:
                    tables = await conn.fetch(tables_sql)

                result = []
                for table in tables:
                    columns = await conn.fetch(columns_sql, table['table_name'])
                    
                    result.append({
                        'table_name': table['table_name'],
                        'table_comment': table['table_comment'] or '',
                        'columns': [dict(col) for col in columns]
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to retrieve schema: {e}")
            raise RuntimeError(f"Failed to retrieve schema: {e}")

    async def sample(self, table_names: Optional[List[str]] = None) -> str:
        try:
            if not table_names:
                schema_info = await self.schema()
                table_names = [table['table_name'] for table in schema_info]
            
            results = []
            for table_name in table_names:
                try:
                    query = f'SELECT * FROM "{table_name}" LIMIT 10'
                    sample_data = await self.query(query)
                    
                    results.append({
                        'table_name': table_name,
                        'sample_data': sample_data[0] if sample_data else None
                    })
                    
                except Exception as e:
                    logger.error(f"Error sampling table {table_name}: {e}")
                    results.append({
                        'table_name': table_name,
                        'sample_data': None,
                        'error': str(e)
                    })
            
            return json.dumps(results, ensure_ascii=False, indent=2, default=str)
            
        except Exception as e:
            logger.error(f"Error in sample method: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)

    async def schema_relationship(self, table_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Asynchronously analyze relationships between tables
        {
          "foreign_keys": [
            {
              "from_table": "categories",
              "from_column": "parent_id",
              "to_table": "categories",
              "to_column": "category_id",
              "constraint_name": "categories_parent_id_fkey"
            },
            {
              "from_table": "order_items",
              "from_column": "order_id",
              "to_table": "orders",
              "to_column": "order_id",
              "constraint_name": "order_items_order_id_fkey"
            },
            {
              "from_table": "order_items",
              "from_column": "product_id",
              "to_table": "products",
              "to_column": "product_id",
              "constraint_name": "order_items_product_id_fkey"
            },
            {
              "from_table": "orders",
              "from_column": "user_id",
              "to_table": "users",
              "to_column": "user_id",
              "constraint_name": "orders_user_id_fkey"
            },
            {
              "from_table": "products",
              "from_column": "category_id",
              "to_table": "categories",
              "to_column": "category_id",
              "constraint_name": "products_category_id_fkey"
            }
          ],
          "relationships_summary": {
            "one_to_many": [
              {
                "from_table": "order_items",
                "from_column": "order_id",
                "to_table": "orders",
                "to_column": "order_id",
                "constraint_name": "order_items_order_id_fkey"
              },
              {
                "from_table": "order_items",
                "from_column": "product_id",
                "to_table": "products",
                "to_column": "product_id",
                "constraint_name": "order_items_product_id_fkey"
              },
              {
                "from_table": "orders",
                "from_column": "user_id",
                "to_table": "users",
                "to_column": "user_id",
                "constraint_name": "orders_user_id_fkey"
              },
              {
                "from_table": "products",
                "from_column": "category_id",
                "to_table": "categories",
                "to_column": "category_id",
                "constraint_name": "products_category_id_fkey"
              }
            ],
            "many_to_many": [],
            "self_referencing": [
              {
                "from_table": "categories",
                "from_column": "parent_id",
                "to_table": "categories",
                "to_column": "category_id",
                "constraint_name": "categories_parent_id_fkey"
              }
            ]
          }
        }
        """
        try:
            schema = 'public'
            params = [schema]
            
            table_condition = ""
            if table_names:
                placeholders = ','.join([f'${i+2}' for i in range(len(table_names))])
                table_condition = f"AND tc.table_name IN ({placeholders})"
                params.extend(table_names)

            foreign_keys_sql = f"""
                SELECT
                    tc.table_name as from_table,
                    kcu.column_name as from_column,
                    ccu.table_name as to_table,
                    ccu.column_name as to_column,
                    tc.constraint_name
                FROM 
                    information_schema.table_constraints AS tc 
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.table_schema = tc.table_schema
                WHERE 
                    tc.constraint_type = 'FOREIGN KEY' 
                    AND tc.table_schema = $1
                    {table_condition}
                ORDER BY
                    tc.table_name, kcu.ordinal_position
            """

            async with self._get_connection() as conn:
                foreign_keys = await conn.fetch(foreign_keys_sql, *params)
                
                logger.debug(f"Query returned row count: {len(foreign_keys)}")
                if foreign_keys:
                    logger.debug(f"Returned data sample: {foreign_keys[0]}")

                foreign_keys = [dict(record) for record in foreign_keys]
                logger.debug(f"Converted foreign key data: {foreign_keys}")

            relationships = self._analyze_relationship_types(foreign_keys)
            
            return {
                'foreign_keys': foreign_keys,
                'relationships_summary': relationships
            }

        except Exception as e:
            logger.error(f"Failed to analyze table relationships: {e}")
            raise RuntimeError(f"Failed to analyze table relationships: {e}")

    def _analyze_relationship_types(self, foreign_keys: List[Dict]) -> Dict[str, List]:
        relationships = {
            'one_to_many': [],
            'many_to_many': [],
            'self_referencing': []
        }
        
        if not foreign_keys:
            return relationships

        relation_map = {}
        for fk in foreign_keys:
            key = (fk['from_table'], fk['to_table'])
            if key not in relation_map:
                relation_map[key] = []
            relation_map[key].append(fk)

        for (from_table, to_table), fks in relation_map.items():
            if from_table == to_table:
                relationships['self_referencing'].extend(fks)
            elif self._is_many_to_many(from_table, to_table, foreign_keys):
                relationships['many_to_many'].extend(fks)
            else:
                relationships['one_to_many'].extend(fks)
        
        return relationships

    def _is_many_to_many(self, table1: str, table2: str, all_foreign_keys: List[Dict]) -> bool:
        if not all_foreign_keys:
            return False

        junction_tables = set()
        
        for fk in all_foreign_keys:
            if fk['to_table'] in [table1, table2]:
                junction_tables.add(fk['from_table'])

        for junction_table in junction_tables:
            ref_tables = set()
            for fk in all_foreign_keys:
                if fk['from_table'] == junction_table:
                    ref_tables.add(fk['to_table'])
            
            if table1 in ref_tables and table2 in ref_tables:
                return True
        
        return False


def format_schema_to_markdown(schema_results):
    if not schema_results:
        return "No schema information available"
    
    formatted = []
    for table_info in schema_results:
        table_name = table_info.get('table_name', 'unknown')
        table_comment = table_info.get('table_comment', '')
        
        formatted.append(f"\n## Table: `{table_name}`")
        if table_comment:
            formatted.append(f"*{table_comment}*")
        
        formatted.append("\n| Column | Type | Nullable | Key | Comment |")
        formatted.append("|--------|------|----------|-----|---------|")
        
        for column in table_info.get('columns', []):
            # 使用正确的键名 - 根据您的测试输出调整
            col_name = column.get('column_name', '')
            col_type = column.get('column_type', '')
            nullable = column.get('is_nullable', '')
            col_key = column.get('column_key', '')
            col_comment = column.get('column_comment', '')
            
            formatted.append(
                f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
            )
    
    return "\n".join(formatted)
    

class AsyncPostgresReaderContextManager:
    def __init__(self, config: Union[Dict[str, Any], PostgresConfig]):
        self.config = config
        self.reader = None

    async def __aenter__(self):
        self.reader = AsyncPostgresReader(self.config)
        await self.reader._ensure_pool()
        return self.reader

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.reader:
            await self.reader.close()
            await cleanup()

async def cleanup():
    await AsyncPostgresPoolManager.close_all()


async def execute_postgres(config, sql)-> List[Dict[str, Any]]:
    async with AsyncPostgresReaderContextManager(config) as reader:
        results = await reader.query(sql)
        return results

async def get_postgres_tables_schema(config, table_names: Optional[List[str]] = None)-> str:
    async with AsyncPostgresReaderContextManager(config) as reader:
        results = await reader.schema(table_names)
        schema_md = format_schema_to_markdown(results)
        return schema_md

async def get_postgres_tables_relationship(config, table_names: Optional[List[str]] = None)-> str:
    async with AsyncPostgresReaderContextManager(config) as reader:
        results = await reader.schema_relationship(table_names)
        json_str = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        return json_str

async def get_postgres_tables_sampledata(config, table_names: Optional[List[str]] = None)-> str:
    async with AsyncPostgresReaderContextManager(config) as reader:
        results = await reader.sample(table_names)
        relationship_str = json.dumps(results, ensure_ascii=False, indent=2)
        return relationship_str
