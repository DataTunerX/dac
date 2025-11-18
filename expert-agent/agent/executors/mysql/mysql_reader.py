import asyncio
import aiomysql
from aiomysql import Error
from aiomysql.cursors import DictCursor
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mysql_reader")


class AsyncMySQLReader:

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._validate_config()
        self.pool = None
        self._is_closed = False
        self._client = None

    def _validate_config(self) -> None:
        required_keys = ['host', 'user', 'password', 'database']
        if not all(k in self.config for k in required_keys):
            raise ValueError(
                f"MySQL Configuration is missing required parameters, need: {required_keys}，current configuration: {list(self.config.keys())}"
            )

    async def _connect(self) -> Any:
        await self.initialize()
        return self.pool

    @property
    async def client(self):
        if self._client is None:
            self._client = await self._connect()
        return self._client

    async def initialize(self):
        if self.pool is None:
            port = self.config.get('port', 3306)
            if isinstance(port, str):
                port = int(port)

            timeout = self.config.get('timeout', 30)
            if isinstance(timeout, str) and timeout.isdigit():
                timeout = int(timeout)
            elif not isinstance(timeout, int):
                timeout = 10

            max_connections = self.config.get('max_connections', 1)
            if isinstance(max_connections, str) and max_connections.isdigit():
                max_connections = int(max_connections)
            elif not isinstance(max_connections, int):
                max_connections = 10

            try:
                self.pool = await aiomysql.create_pool(
                    host=self.config['host'],
                    user=self.config['user'],
                    password=self.config['password'],
                    db=self.config['database'],
                    port=port,
                    connect_timeout=timeout,
                    charset='utf8mb4',
                    use_unicode=True,
                    autocommit=True,
                    minsize=1,
                    maxsize=max_connections,
                    cursorclass=DictCursor,
                )
                logger.debug("Asynchronous MySQL connection pool created successfully")
            except Error as e:
                raise ConnectionError(f"MySQL connection pool creation failed: {e}")

    async def close(self) -> None:
        if self.pool and not self._is_closed:
            try:
                self.pool.close()
                await self.pool.wait_closed()
            except Error:
                pass
            finally:
                self._is_closed = True
                self._client = None
                logger.debug("Asynchronous MySQL connection pool has been closed")

    def __del__(self):
        if hasattr(self, 'pool') and self.pool and not self._is_closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
            except:
                pass

    async def test_connection(self) -> bool:
        try:
            async with self._get_cursor() as cursor:
                await cursor.execute("SELECT 1")
                return True
        except Error:
            return False

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
            logger.error(f"MySQL connection fail: {e}")
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
            logger.error(f"MySQL operation fail: {e}")
            raise
        finally:
            if own_connection and connection:
                self.pool.release(connection)

    async def query(
        self,
        input: str,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results (aiomysql adapted version)

        Parameters:
            input: SQL statement
            parameters: Parameter dictionary (aiomysql uses `%s` placeholders but supports dictionary parameters)
            **kwargs:
                - batchSize: Number of rows to fetch per batch
                - as_dict: Whether to return dictionaries (default True, controlled by DictCursor)

        Returns:
            Query result list (each row is a dictionary)
        """
        as_dict = kwargs.get('as_dict', True)
        fetch_size = kwargs.get('batchSize')

        try:
            async with self._get_cursor() as cursor:
                await cursor.execute(input, parameters)

                if fetch_size:
                    results = []
                    while True:
                        batch = await cursor.fetchmany(fetch_size)
                        if not batch:
                            break
                        results.extend(batch)
                    return results
                return await cursor.fetchall()
        except Error as e:
            raise RuntimeError(f"SQL执行失败: {e}")

    async def schema(self, table_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get database table structure information (asynchronous version)
        
        Parameters:
            table_names: Optional parameter, specifies the list of table names to retrieve. If None or empty list, retrieves all tables
        
        Returns:
        [
            {
                'table_name': 'users',
                'table_comment': 'User information table',
                'columns': [
                    {
                        'TABLE_NAME': 'users',
                        'COLUMN_NAME': 'id',
                        'COLUMN_TYPE': 'int(11)',
                        'IS_NULLABLE': 'NO',
                        'COLUMN_KEY': 'PRI',
                        'COLUMN_DEFAULT': None,
                        'EXTRA': 'auto_increment',
                        'COLUMN_COMMENT': 'User ID'
                    },
                    {
                        'TABLE_NAME': 'users',
                        'COLUMN_NAME': 'username',
                        'COLUMN_TYPE': 'varchar(50)',
                        'IS_NULLABLE': 'NO',
                        'COLUMN_KEY': '',
                        'COLUMN_DEFAULT': None,
                        'EXTRA': '',
                        'COLUMN_COMMENT': 'Username'
                    }
                ]
            }
        ]
        """
        try:
            table_condition = ""
            params = [self.config['database']]
            
            if table_names:
                placeholders = ', '.join(['%s'] * len(table_names))
                table_condition = f"AND TABLE_NAME IN ({placeholders})"
                params.extend(table_names)

            tables_sql = f"""
                SELECT 
                    TABLE_NAME, 
                    TABLE_COMMENT 
                FROM 
                    INFORMATION_SCHEMA.TABLES 
                WHERE 
                    TABLE_SCHEMA = %s
                    {table_condition}
            """

            columns_sql = f"""
                SELECT 
                    TABLE_NAME,
                    COLUMN_NAME,
                    COLUMN_TYPE,
                    IS_NULLABLE,
                    COLUMN_KEY,
                    COLUMN_DEFAULT,
                    EXTRA,
                    COLUMN_COMMENT
                FROM 
                    INFORMATION_SCHEMA.COLUMNS 
                WHERE 
                    TABLE_SCHEMA = %s
                    {table_condition}
                ORDER BY 
                    TABLE_NAME, ORDINAL_POSITION
            """

            async with self._get_cursor() as cursor:
                await cursor.execute(tables_sql, params)
                tables = await cursor.fetchall()

                await cursor.execute(columns_sql, params)
                columns = await cursor.fetchall()

            result = []
            column_dict = {}
            for col in columns:
                column_dict.setdefault(col['TABLE_NAME'], []).append(col)
            
            for table in tables:
                result.append({
                    'table_name': table['TABLE_NAME'],
                    'table_comment': table['TABLE_COMMENT'],
                    'columns': column_dict.get(table['TABLE_NAME'], [])
                })
            
            return result

        except Error as e:
            raise RuntimeError(f"get table schema fail: {e}")

    async def sample(self, table_names: Optional[List[str]] = None) -> str:
        """
        Query one sample data record from each specified table (asynchronous version)
        
        Parameters:
            table_names: Optional parameter, specifies the list of table names to sample from. If None or empty list, retrieves samples from all tables
        
        Returns the following data as a string:
        [
            {
                'table_name': 'users',
                'sample_data': {
                    'id': 1,
                    'username': 'john_doe',
                    'email': 'john@example.com'
                }
            },
            {
                'table_name': 'products',
                'sample_data': {
                    'id': 1,
                    'name': 'Laptop',
                    'price': 999.99
                }
            }
        ]
        """
        try:
            if not table_names:
                async with self._get_cursor() as cursor:
                    await cursor.execute("""
                        SELECT TABLE_NAME 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = %s 
                        AND TABLE_TYPE = 'BASE TABLE'
                    """, (self.config['database'],))
                    tables = await cursor.fetchall()
                    table_names = [table['TABLE_NAME'] for table in tables]
            
            if not table_names:
                return "[]"
            
            results = []
            for table_name in table_names:
                try:
                    async with self._get_cursor() as cursor:
                        safe_table_name = table_name.replace('`', '``')
                        await cursor.execute(f"SELECT * FROM `{safe_table_name}` LIMIT 10")
                        sample_data = await cursor.fetchone()
                        
                        results.append({
                            'table_name': table_name,
                            'sample_data': sample_data if sample_data else {}
                        })
                        
                except Error as e:
                    logger.warning(f"Unable to sample data from table {table_name}: {e}")
                    results.append({
                        'table_name': table_name,
                        'sample_data': {},
                        'error': str(e)
                    })
            
            json_str = json.dumps(results, ensure_ascii=False, indent=2, default=str)
            return json_str
            
        except Error as e:
            raise RuntimeError(f"sample data fail: {e}")

    async def schema_relationship(self, table_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Specifically analyze relationships between tables (asynchronous version)
        
        return:
        {
          "foreign_keys": [
            {
              "from_table": "categories",
              "from_column": "parent_id",
              "to_table": "categories",
              "to_column": "category_id",
              "constraint_name": "categories_ibfk_1"
            },
            {
              "from_table": "order_items",
              "from_column": "order_id",
              "to_table": "orders",
              "to_column": "order_id",
              "constraint_name": "order_items_ibfk_1"
            },
            {
              "from_table": "order_items",
              "from_column": "product_id",
              "to_table": "products",
              "to_column": "product_id",
              "constraint_name": "order_items_ibfk_2"
            },
            {
              "from_table": "orders",
              "from_column": "user_id",
              "to_table": "users",
              "to_column": "user_id",
              "constraint_name": "orders_ibfk_1"
            },
            {
              "from_table": "products",
              "from_column": "category_id",
              "to_table": "categories",
              "to_column": "category_id",
              "constraint_name": "products_ibfk_1"
            }
          ],
          "relationships_summary": {
            "one_to_many": [
              {
                "from_table": "order_items",
                "from_column": "order_id",
                "to_table": "orders",
                "to_column": "order_id",
                "constraint_name": "order_items_ibfk_1"
              },
              {
                "from_table": "order_items",
                "from_column": "product_id",
                "to_table": "products",
                "to_column": "product_id",
                "constraint_name": "order_items_ibfk_2"
              },
              {
                "from_table": "orders",
                "from_column": "user_id",
                "to_table": "users",
                "to_column": "user_id",
                "constraint_name": "orders_ibfk_1"
              },
              {
                "from_table": "products",
                "from_column": "category_id",
                "to_table": "categories",
                "to_column": "category_id",
                "constraint_name": "products_ibfk_1"
              }
            ],
            "many_to_many": [],
            "self_referencing": [
              {
                "from_table": "categories",
                "from_column": "parent_id",
                "to_table": "categories",
                "to_column": "category_id",
                "constraint_name": "categories_ibfk_1"
              }
            ]
          }
        }
        """
        try:
            table_condition = ""
            params = [self.config['database']]
            
            if table_names:
                placeholders = ', '.join(['%s'] * len(table_names))
                table_condition = f"AND TABLE_NAME IN ({placeholders})"
                params.extend(table_names)

            foreign_keys_sql = f"""
                SELECT
                    TABLE_NAME as from_table,
                    COLUMN_NAME as from_column,
                    REFERENCED_TABLE_NAME as to_table,
                    REFERENCED_COLUMN_NAME as to_column,
                    CONSTRAINT_NAME
                FROM
                    INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE
                    TABLE_SCHEMA = %s
                    AND REFERENCED_TABLE_NAME IS NOT NULL
                    {table_condition}
                ORDER BY
                    TABLE_NAME, ORDINAL_POSITION
            """

            async with self._get_cursor() as cursor:
                await cursor.execute(foreign_keys_sql, params)
                foreign_keys = await cursor.fetchall()

            relationships = self._analyze_relationship_types(foreign_keys)
            
            return {
                'foreign_keys': foreign_keys,
                'relationships_summary': relationships
            }

        except Error as e:
            raise RuntimeError(f"Failed to analyze table relationships: {e}")

    def _analyze_relationship_types(self, foreign_keys: List[Dict]) -> Dict[str, List]:
        relationships = {
            'one_to_many': [],
            'many_to_many': [],
            'self_referencing': []
        }
        
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
            col_name = column.get('COLUMN_NAME', '')
            col_type = column.get('COLUMN_TYPE', '')
            nullable = column.get('IS_NULLABLE', '')
            col_key = column.get('COLUMN_KEY', '')
            col_comment = column.get('COLUMN_COMMENT', '')
            
            formatted.append(
                f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
            )
    
    return "\n".join(formatted)


class AsyncMySQLReaderContextManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.reader = None

    async def __aenter__(self):
        self.reader = AsyncMySQLReader(self.config)
        await self.reader.initialize()
        return self.reader

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.reader:
            await self.reader.close()


async def execute_mysql(config, sql)-> List[Dict[str, Any]]:
    async with AsyncMySQLReaderContextManager(config) as reader:
        results = await reader.query(sql)
        return results

async def get_mysql_tables_schema(config, table_names: Optional[List[str]] = None)-> str:

    logger.debug(f"mysql_reader.get_mysql_tables_schema config={config}")

    async with AsyncMySQLReaderContextManager(config) as reader:
        results = await reader.schema(table_names)
        schema_md = format_schema_to_markdown(results)
        return schema_md

async def get_mysql_tables_relationship(config, table_names: Optional[List[str]] = None)-> str:

    logger.debug(f"mysql_reader.get_mysql_tables_relationship config={config}")

    async with AsyncMySQLReaderContextManager(config) as reader:
        results = await reader.schema_relationship(table_names)
        json_str = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        return json_str

async def get_mysql_tables_sampledata(config, table_names: Optional[List[str]] = None)-> str:

    logger.debug(f"mysql_reader.get_mysql_tables_sampledata config={config}")

    async with AsyncMySQLReaderContextManager(config) as reader:
        results = await reader.sample(table_names)
        relationship_str = json.dumps(results, ensure_ascii=False, indent=2)
        return relationship_str
