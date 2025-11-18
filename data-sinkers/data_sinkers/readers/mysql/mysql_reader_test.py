import pymysql
from data_sinkers.readers.mysql.mysql_reader import MySQLReader

# python -m data_sinkers.readers.mysql.mysql_reader_test


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


def main():
    # Configure your local MySQL connection
    config = {
        'host': '192.168.xxx.xxx',
        'user': 'root',
        'password': '123',
        'database': 'test1',
        'port': 3307
    }

    # Initialize the reader
    reader = MySQLReader(config)

    try:
        # print("=== Testing query() method ===")
        # # Test 1: Simple SELECT query
        # print("\nTest 1: Basic SELECT query")
        # results = reader.query("SELECT * FROM deposit_data LIMIT 1")  # Replace with a real table
        # print(f"Found {len(results)} rows")
        # for row in results:
        #     print(row)

        # # Test 2: Parameterized query
        # print("\nTest 2: Parameterized query")
        # results = reader.query(
        #     "SELECT * FROM deposit_data WHERE id = %s", 
        #     parameters=[1]  # Replace with a valid ID
        # )
        # print(f"Found {len(results)} matching rows")
        # for row in results:
        #     print(row)

        # print("\n=== Testing schema() method ===")
        # # Get database schema
        # schema = reader.schema()
        # print(f"Found {len(schema)} tables")
        
        # # Print table info
        # for table in schema:
        #     print(f"\nTable: {table['table_name']}")
        #     print(f"Comment: {table['table_comment']}")
        #     print("Columns:")
        #     for col in table['columns']:
        #         print(f"  {col['COLUMN_NAME']} ({col['COLUMN_TYPE']}) - {col['COLUMN_COMMENT']}")

        print("\n=== Testing schema(tables) method ===")
        # Get database schema
        # schema = reader.schema(["deposit_data"])
        schema = reader.schema()
        print(f"Found {len(schema)} tables")
        
        md_str = format_schema_to_markdown(schema)
        print(md_str)
        # Print table info
        # for table in schema:
        #     print(f"\nTable: {table['table_name']}")
        #     print(f"Comment: {table['table_comment']}")
        #     print("Columns:")
        #     for col in table['columns']:
        #         print(f"  {col['COLUMN_NAME']} ({col['COLUMN_TYPE']}) - {col['COLUMN_COMMENT']}")

        # print("=== Testing sample() method ===")
        # sample_data = reader.sample(["deposit_data"])
        # sample_data = reader.sample()
        # print(f"sample_data = {sample_data}")

        # print("\n=== Testing schema(tables) method ===")
        # schema_relationship = reader.schema_relationship()
        # print(f"schema_relationship = {schema_relationship}")

    except Exception as e:
        print(f"Error during testing: {e}")
    finally:
        reader.close()
        print("\nConnection closed")

if __name__ == "__main__":
    main()
