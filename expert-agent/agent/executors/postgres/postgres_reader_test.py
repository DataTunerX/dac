import asyncio
import sys
import os

# python -m agent.executors.postgres.postgres_reader_test

# Add project root directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from executors.postgres.postgres_reader import AsyncPostgresReaderContextManager

async def main():
    config = {
        'host': '192.168.xxx.xxx',
        'port': 5433,
        'user': 'postgres',
        'password': 'postgres',
        'database': 'test1'
    }
    
    # Using context manager
    async with AsyncPostgresReaderContextManager(config) as reader:
        # Test connection
        if await reader.test_connection():
            print("Connection successful")
        
        # results = await reader.query("SELECT * FROM balance_sheet LIMIT 10")
        # print(f"Found {len(results)} balance_sheet")
        
        # print(results)

        # Test schema
        # result = await reader.schema([])
        # print(f"✓ Schema query successful, returned {result}")

        # # Test sample
        # result = await reader.sample([])
        # print(f"✓ Sample data query successful, returned {result}")

        # Test relationship
        result = await reader.schema_relationship([])
        print(f"✓ Schema relationship query successful, returned {result}")

if __name__ == "__main__":
    asyncio.run(main())
