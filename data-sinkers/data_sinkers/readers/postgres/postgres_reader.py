import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional, Iterable, Union
from contextlib import contextmanager
from ..base.base_reader import BaseDataReader
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("postgres_reader")

class PostgresReader(BaseDataReader):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._validate_config()
        self._client = self._connect()
        self._is_closed = False

    def _validate_config(self):
        """Validate configuration"""
        required_keys = ['host', 'user', 'password', 'database']
        if not all(k in self.config for k in required_keys):
            raise ValueError(
                f"PostgreSQL configuration is missing required parameters. Required: {required_keys}, "
                f"Current config: {list(self.config.keys())}"
            )

    def _connect(self) -> Any:
        """Create database connection with enhanced options"""
        try:
            conn = psycopg2.connect(
                host=self.config['host'],
                user=self.config['user'],
                password=self.config['password'],
                dbname=self.config['database'],
                port=self.config.get('port', 5432),
                connect_timeout=self.config.get('timeout', 10),
                cursor_factory=RealDictCursor,
                sslmode=self.config.get('sslmode', 'prefer'),
                application_name=self.config.get('application_name', 'PostgresReader')
            )
            # Set autocommit for read-only operations
            conn.autocommit = True
            return conn
        except psycopg2.Error as e:
            raise ConnectionError(f"PostgreSQL connection failed: {e}")

    def close(self):
        """Close the connection explicitly"""
        if not self._is_closed and self.client:
            self.client.close()
            self._is_closed = True

    def __del__(self):
        """Destructor to ensure connection is closed"""
        try:
            self.close()
        except Exception:
            pass

    def test_connection(self) -> bool:
        """Test if the connection is alive"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception:
            return False

    @contextmanager
    def _get_cursor(self, server_side: bool = False, as_dict: bool = True):
        """Context manager for cursor handling"""
        cursor = None
        try:
            cursor = self.client.cursor(
                name='server_side_cursor' if server_side else None,
                cursor_factory=RealDictCursor if as_dict else None
            )
            yield cursor
        finally:
            if cursor and not server_side:  # Server-side cursors must be closed explicitly
                cursor.close()

    def query(
        self,
        input: str,
        parameters: Optional[Dict[str, Any]] = None,
        server_side: bool = False,
        **kwargs
    ) -> Union[List[Dict[str, Any]], Iterable[Dict[str, Any]]]:
        """
        Execute SQL query and return results (PostgreSQL implementation)
        
        Args:
            input: SQL statement to execute
            parameters: Dictionary of parameters for parameterized query
            server_side: Whether to use server-side cursor (for large result sets)
            **kwargs: Additional options
                - as_dict: Whether to return dict format (default True, uses RealDictCursor)
        
        Returns:
            Query results as list of dicts (for small results) or generator (for large results)
            
        Examples:
            # Simple query
            results = reader.query("SELECT * FROM users LIMIT 10")
            
            # Parameterized query
            results = reader.query(
                "SELECT * FROM users WHERE create_time > %(start_time)s",
                parameters={'start_time': '2023-01-01'}
            )
            
            # Large dataset with batch processing
            for batch in reader.query("SELECT * FROM large_table", batchSize=5000, server_side=True):
                process_batch(batch)
        """
        as_dict = kwargs.get('as_dict', True)
        fetch_size = kwargs.get('batchSize')

        if server_side:
            # Always return generator for server-side cursors
            return self._query_server_side(input, parameters, fetch_size, as_dict)
        
        # Client-side processing
        with self._get_cursor(as_dict=as_dict) as cursor:
            cursor.execute(input, parameters)
            
            if fetch_size:
                return self._fetch_batches(cursor, fetch_size)
            return cursor.fetchall()

    def sample(self, table_names: Optional[List[str]] = None) -> str:
        """
        Get one sample record from each specified table
        """
        # If no table names provided, get all tables
        if not table_names:
            schema_info = self.schema()
            table_names = [table['table_name'] for table in schema_info]
        
        results = []
        for table_name in table_names:
            try:
                # Safe query with parameterized table name (though parameterized tables aren't supported in PostgreSQL)
                # Using proper quoting instead
                query = f'SELECT * FROM "{table_name}" LIMIT 1'
                sample_data = self.query(query)
                
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
        json_str = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        return json_str

    def _query_server_side(
        self,
        input: str,
        parameters: Optional[Dict[str, Any]],
        fetch_size: Optional[int],
        as_dict: bool
    ) -> Iterable[Dict[str, Any]]:
        """Handle server-side cursor queries"""
        cursor = None
        try:
            cursor = self.client.cursor(
                name='server_side_cursor',
                cursor_factory=RealDictCursor if as_dict else None
            )
            if fetch_size:
                cursor.itersize = fetch_size
            
            cursor.execute(input, parameters)
            
            while True:
                batch = cursor.fetchmany(fetch_size or cursor.itersize or 1000)
                if not batch:
                    break
                yield from batch
        finally:
            if cursor:
                cursor.close()

    def _fetch_batches(self, cursor, fetch_size: int) -> List[Dict[str, Any]]:
        """Fetch data in batches for client-side cursor"""
        results = []
        while True:
            batch = cursor.fetchmany(fetch_size)
            if not batch:
                break
            results.extend(batch)
        return results

    def schema(self, table_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        try:
            # Base SQL for table information
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
            
            # Add table filter if table_names is provided and not empty
            params = []
            if table_names:
                placeholders = ','.join(['%s'] * len(table_names))
                tables_sql += f" AND t.table_name IN ({placeholders})"
                params.extend(table_names)
            
            tables_sql += " ORDER BY t.table_name"
            
            # Get column information for tables - Fix primary key check logic
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
                            AND pc.relname = c.table_name  -- Fix: correctly associate table name
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
                    AND c.table_name = %s  -- Only query columns for the current table
            """
            
            columns_sql += " ORDER BY c.ordinal_position"
            
            with self._get_cursor() as cursor:
                # Get tables
                if params:
                    cursor.execute(tables_sql, params)
                else:
                    cursor.execute(tables_sql)
                tables = cursor.fetchall()
                
                # Get columns for each table
                result = []
                for table in tables:
                    # Query column information for each table separately
                    cursor.execute(columns_sql, [table['table_name']])
                    columns = cursor.fetchall()
                    
                    result.append({
                        'table_name': table['table_name'],
                        'table_comment': table['table_comment'] or '',
                        'columns': [dict(col) for col in columns]
                    })
            
            return result
            
        except psycopg2.Error as e:
            raise RuntimeError(f"Failed to retrieve schema: {e}")


    def schema_relationship(self, table_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Specifically analyze relationships between tables
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
            table_condition = ""
            schema = self.config.get('schema', 'public')
            params = [schema]
            
            if table_names:
                placeholders = ', '.join(['%s'] * len(table_names))
                table_condition = f"AND tc.table_name IN ({placeholders})"
                params.extend(table_names)

            # PostgreSQL foreign key query
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
                    AND tc.table_schema = %s
                    {table_condition}
                ORDER BY
                    tc.table_name, kcu.ordinal_position
            """

            logger.debug(f"Executed SQL: {foreign_keys_sql}")
            logger.debug(f"Parameters: {params}")

            # Use your _get_cursor context manager
            with self._get_cursor() as cursor:
                cursor.execute(foreign_keys_sql, params)
                foreign_keys = cursor.fetchall()
                
                logger.debug(f"Query returned rows: {len(foreign_keys)}")
                if foreign_keys:
                    logger.debug(f"Sample returned data: {foreign_keys[0]}")
                
                # RealDictCursor returns RealDictRow objects, need to convert to regular dictionaries
                # Directly use dict() to convert each row
                foreign_keys = [dict(row) for row in foreign_keys]
                logger.debug(f"Converted foreign key data: {foreign_keys}")

            # Analyze relationship types
            relationships = self._analyze_relationship_types(foreign_keys)
            
            return {
                'foreign_keys': foreign_keys,
                'relationships_summary': relationships
            }

        except Exception as e:
            logger.error(f"Failed to analyze table relationships: {e}")
            raise RuntimeError(f"Failed to analyze table relationships: {e}")

    def _analyze_relationship_types(self, foreign_keys: List[Dict]) -> Dict[str, List]:
        """Analyze relationship types"""
        relationships = {
            'one_to_many': [],
            'many_to_many': [],
            'self_referencing': []
        }
        
        if not foreign_keys:
            return relationships
        
        # Build relationship mapping
        relation_map = {}
        for fk in foreign_keys:
            key = (fk['from_table'], fk['to_table'])
            if key not in relation_map:
                relation_map[key] = []
            relation_map[key].append(fk)
        
        # Analyze relationship types
        for (from_table, to_table), fks in relation_map.items():
            # Self-referencing relationships
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
        if not all_foreign_keys:
            return False
        
        # Find junction tables: junction tables should reference both tables
        junction_tables = set()
        
        for fk in all_foreign_keys:
            if fk['to_table'] in [table1, table2]:
                junction_tables.add(fk['from_table'])
        
        # Check if junction tables connect to both tables
        for junction_table in junction_tables:
            ref_tables = set()
            for fk in all_foreign_keys:
                if fk['from_table'] == junction_table:
                    ref_tables.add(fk['to_table'])
            
            if table1 in ref_tables and table2 in ref_tables:
                return True
        
        return False
