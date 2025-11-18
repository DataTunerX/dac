import pymysql
from pymysql import Error
from pymysql.cursors import DictCursor
from typing import List, Dict, Any, Optional
from ..base.base_reader import BaseDataReader
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mysql_reader")

class MySQLReader(BaseDataReader):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._validate_config()
        self._client = self._connect()
        self._is_closed = False

    def _validate_config(self):
        """Validate configuration parameters"""
        required_keys = ['host', 'user', 'password', 'database']
        if not all(k in self.config for k in required_keys):
            raise ValueError(
                f"MySQL configuration is missing required parameters. Required: {required_keys}, Current configuration: {list(self.config.keys())}"
            )

    def _connect(self) -> Any:
        """Create database connection (PyMySQL)"""
        try:
            # Ensure port is integer type
            port = self.config.get('port', 3306)
            if isinstance(port, str):
                port = int(port)

            # Handle timeout type
            timeout = self.config.get('timeout', 10)
            if isinstance(timeout, str) and timeout.isdigit():
                timeout = int(timeout)
            elif not isinstance(timeout, int):
                timeout = 10  # Default value

            conn = pymysql.connect(
                host=self.config['host'],
                user=self.config['user'],
                password=self.config['password'],
                db=self.config['database'],
                port=port,
                connect_timeout=timeout,
                charset='utf8mb4',
                cursorclass=DictCursor,  # Use DictCursor to return dictionary format
                autocommit=True,  # Auto-commit mode
            )
            return conn
        except Error as e:
            raise ConnectionError(f"MySQL connection failed: {e}")

    def close(self):
        """Explicitly close connection"""
        if hasattr(self, '_is_closed') and not self._is_closed and hasattr(self, '_client') and self._client:
            try:
                self._client.close()
            except Error:
                pass  # Ignore exceptions during closing
            finally:
                self._is_closed = True

    def __del__(self):
        """Destructor ensures connection is closed"""
        if hasattr(self, 'close'):
            self.close()

    def test_connection(self) -> bool:
        """Test if connection is valid"""
        try:
            with self.client.cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Error:
            return False

    def query(
        self,
        input: str,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results (PyMySQL adapted version)

        Parameters:
            input: SQL statement
            parameters: Parameter dictionary (PyMySQL uses `%s` placeholders, but supports dictionary parameters)
            **kwargs:
                - batchSize: Number of rows to fetch in batches
                - as_dict: Whether to return dictionaries (default True, controlled by DictCursor)

        Returns:
            List of query results (each row is a dictionary)
        """
        as_dict = kwargs.get('as_dict', True)
        fetch_size = kwargs.get('batchSize')

        try:
            cursor = self.client.cursor(DictCursor if as_dict else None)
            # PyMySQL parameterized queries use `%s`, but support dictionary parameters
            cursor.execute(input, parameters)

            if fetch_size:
                results = []
                while True:
                    batch = cursor.fetchmany(fetch_size)
                    if not batch:
                        break
                    results.extend(batch)
                return results
            return cursor.fetchall()
        except Error as e:
            raise RuntimeError(f"SQL execution failed: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()

    def sample(self, table_names: Optional[List[str]] = None) -> str:
        """
        Query one sample data record from each specified table
        
        Parameters:
            table_names: Optional parameter, specifies the list of table names to sample from. If None or empty list, samples from all tables.
        
        Returns a string of the following data:
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
            # Get all table names
            if not table_names:
                with self.client.cursor(DictCursor) as cursor:
                    cursor.execute("""
                        SELECT TABLE_NAME 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = %s 
                        AND TABLE_TYPE = 'BASE TABLE'
                    """, (self.config['database'],))
                    tables = cursor.fetchall()
                    table_names = [table['TABLE_NAME'] for table in tables]
            
            if not table_names:
                return []
            
            results = []
            for table_name in table_names:
                try:
                    with self.client.cursor(DictCursor) as cursor:
                        # Use parameterized queries to prevent SQL injection
                        cursor.execute(f"SELECT * FROM `{table_name}` LIMIT 1")
                        sample_data = cursor.fetchone()
                        
                        results.append({
                            'table_name': table_name,
                            'sample_data': sample_data if sample_data else {}
                        })
                        
                except Error as e:
                    logger.warning(f"Unable to sample data from table {table_name}: {e}")
                    # If query fails, still return table name but with empty sample data
                    results.append({
                        'table_name': table_name,
                        'sample_data': {},
                        'error': str(e)
                    })
            
            json_str = json.dumps(results, ensure_ascii=False, indent=2, default=str)
            return json_str
            
        except Error as e:
            raise RuntimeError(f"Data sampling failed: {e}")


    def schema(self, table_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get database table structure information
        
        Parameters:
            table_names: Optional parameter, specifies the list of table names to get. If None or empty list, gets all tables.
        
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
            # Build SQL query conditions
            table_condition = ""
            params = [self.config['database']]
            
            if table_names:
                # Build table name placeholders
                placeholders = ', '.join(['%s'] * len(table_names))
                table_condition = f"AND TABLE_NAME IN ({placeholders})"
                params.extend(table_names)
            
            # Get all table information
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
            
            # Get all column information
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

            with self.client.cursor(DictCursor) as cursor:
                cursor.execute(tables_sql, params)
                tables = cursor.fetchall()

                cursor.execute(columns_sql, params)
                columns = cursor.fetchall()

            # Organize table structure data
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
            raise RuntimeError(f"Failed to get table structure: {e}")

    def schema_relationship(self, table_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Specifically analyze relationships between tables
        
        Returns:
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

            # Get foreign key relationships
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

            with self.client.cursor(DictCursor) as cursor:
                cursor.execute(foreign_keys_sql, params)
                foreign_keys = cursor.fetchall()

            # Analyze relationship types
            relationships = self._analyze_relationship_types(foreign_keys)
            
            return {
                'foreign_keys': foreign_keys,
                'relationships_summary': relationships
            }

        except Error as e:
            raise RuntimeError(f"Failed to analyze table relationships: {e}")

    def _analyze_relationship_types(self, foreign_keys: List[Dict]) -> Dict[str, List]:
        """Analyze relationship types"""
        relationships = {
            'one_to_many': [],
            'many_to_many': [],
            'self_referencing': []
        }
        
        # Build relationship mapping
        relation_map = {}
        for fk in foreign_keys:
            key = (fk['from_table'], fk['to_table'])
            if key not in relation_map:
                relation_map[key] = []
            relation_map[key].append(fk)
        
        # Analyze relationship types
        for (from_table, to_table), fks in relation_map.items():
            # Self-referencing relationship
            if from_table == to_table:
                relationships['self_referencing'].extend(fks)
            # Check if it's a many-to-many relationship (through junction table)
            elif self._is_many_to_many(from_table, to_table, foreign_keys):
                relationships['many_to_many'].extend(fks)
            else:
                relationships['one_to_many'].extend(fks)
        
        return relationships

    def _is_many_to_many(self, table1: str, table2: str, all_foreign_keys: List[Dict]) -> bool:
        """Check if it's a many-to-many relationship"""
        # Find junction tables: junction tables should reference both tables
        junction_tables = set()
        
        for fk in all_foreign_keys:
            if fk['to_table'] in [table1, table2]:
                junction_tables.add(fk['from_table'])
        
        # Check if junction table connects to both tables
        for junction_table in junction_tables:
            ref_tables = set()
            for fk in all_foreign_keys:
                if fk['from_table'] == junction_table:
                    ref_tables.add(fk['to_table'])
            
            if table1 in ref_tables and table2 in ref_tables:
                return True
        
        return False
