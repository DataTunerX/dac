from data_sinkers.readers.postgres.postgres_reader import PostgresReader

# python -m data_sinkers.readers.postgres.postgres_reader_test


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
            col_name = column.get('column_name', '')
            col_type = column.get('column_type', '')
            nullable = column.get('is_nullable', '')
            col_key = column.get('column_key', '')
            col_comment = column.get('column_comment', '')
            
            formatted.append(
                f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
            )
    
    return "\n".join(formatted)


def main():
    # Configure your local PostgreSQL connection
    config = {
        'host': '192.168.xxx.xxx',
        'user': 'postgres',      # Replace with your PostgreSQL username
        'password': 'postgres',  # Replace with your PostgreSQL password
        'database': 'test1',       # Replace with your database name
        'port': 5433                 # Default PostgreSQL port
    }

    # Initialize the reader
    reader = PostgresReader(config)

    try:
        # Test connection
        if not reader.test_connection():
            print("Failed to connect to database")
            return

        # print("=== Testing query() method ===")
        # # Test 1: Simple SELECT query
        # print("\nTest 1: Basic SELECT query")
        # try:
        #     results = reader.query("SELECT * FROM deposit_data LIMIT 1")  # Replace with a real table
        #     print(f"Found {len(results)} rows")
        #     for row in results:
        #         print(row)
        # except Exception as e:
        #     print(f"Query failed: {e}")

        # # Test 2: Parameterized query
        # print("\nTest 2: Parameterized query")
        # try:
        #     results = reader.query(
        #         "SELECT * FROM deposit_data WHERE id = %s", 
        #         parameters=["354df8da-c80a-4979-bb41-37cda8431436"]  # Replace with a valid ID
        #     )
        #     print(f"Found {len(results)} matching rows")
        #     for row in results:
        #         print(row)
        # except Exception as e:
        #     print(f"Parameterized query failed: {e}")

        # print("\n=== Testing schema() method ===")
        # # Get database schema
        # try:
        #     schema = reader.schema()
        #     print(f"Found {len(schema)} tables")
        #     md_str = format_schema_to_markdown(schema)
        #     print(md_str)
            
        #     # Print first table info as sample
        #     # if schema:
        #     #     first_table = schema[0]
        #     #     print(f"\nSample table: {first_table['table_name']}")
        #     #     print(f"Comment: {first_table['table_comment']}")
        #     #     for col in first_table['columns'][:100]:
        #     #         print(f"  {col['column_name']} ({col['column_type']}) - Nullable: {col['is_nullable']}")
        # except Exception as e:
        #     print(f"Schema retrieval failed: {e}")

        # print("\n=== Testing schema(tables) method ===")
        # # Get database schema
        # try:
        #     schema = reader.schema(["customer_data","test_data"])
        #     # schema = reader.schema(["test_data"])
        #     print(f"Found {len(schema)} tables")
            
        #     # Print first table info as sample
        #     # Print all tables info
        #     for i, table in enumerate(schema, 1):
        #         print(f"\nTable {i}: {table['table_name']}")
        #         print(f"Comment: {table['table_comment'] or 'No comment'}")
        #         print(f"Columns ({len(table['columns'])} total):")
                
        #         # Print all columns for this table
        #         for col in table['columns']:
        #             print(f"  {col['column_name']} ({col['column_type']}) - "
        #                   f"Nullable: {col['is_nullable']} - "
        #                   f"Key: {col['column_key']} - "
        #                   f"Default: {col['column_default']}")
                
        #         # Add separator between tables
        #         if i < len(schema):
        #             print("-" * 50)
        # except Exception as e:
        #     print(f"Schema retrieval failed: {e}")

        # sample_data = reader.sample(["deposit_data"])
        # sample_data = reader.sample()
        # print(f"sample_data = {sample_data}")

        print("\n=== Testing schema(tables) method ===")
        schema_relationship = reader.schema_relationship()
        print(f"schema_relationship = {schema_relationship}")

    finally:
        reader.close()
        print("\nConnection closed")

if __name__ == "__main__":
    main()
