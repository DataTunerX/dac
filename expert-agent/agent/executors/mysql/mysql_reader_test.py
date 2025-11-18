import asyncio
import sys
import os

# python -m agent.executors.mysql.mysql_reader_test

# Add project root directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from executors.mysql.mysql_reader import AsyncMySQLReaderContextManager

async def main():
    config = {
        'host': '192.168.xxx.xxx',
        'port': 3307,
        'user': 'root',
        'password': '123',
        'database': 'test1'
    }
    
    print("=== Testing Async MySQLReader ===")
    
    # Test 1: Using context manager
    print("\n1. Testing context manager:")
    try:
        async with AsyncMySQLReaderContextManager(config) as reader:
            # Test connection
            if await reader.test_connection():
                print("✓ Connection test successful")
            else:
                print("✗ Connection test failed")
                return
            
            # Test query
            # result = await reader.query("SELECT * FROM balance_sheet LIMIT 5")
            # print(f"✓ Query test successful, returned {len(result)} records")
            
            # # Display first few records
            # if result:
            #     print("First 3 record samples:")
            #     for i, row in enumerate(result[:3]):
            #         print(f"  Record {i+1}: {dict(list(row.items())[:3])}...")  # Show only first 3 fields

            # # Test schema
            # result = await reader.schema([])
            # print(f"✓ Schema query successful, returned {result}")

            # # Test sample
            # result = await reader.sample([])
            # print(f"✓ Sample data query successful, returned {result}")

            # Test relationship
            result = await reader.schema_relationship([])
            print(f"✓ Schema relationship query successful, returned {result}")
            
    except Exception as e:
        print(f"✗ Context manager test failed: {e}")
        return
    
    print("\n=== All tests completed ===")

if __name__ == "__main__":
    asyncio.run(main())
