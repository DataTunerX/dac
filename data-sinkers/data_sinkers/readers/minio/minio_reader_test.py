import asyncio
import os
from data_sinkers.readers.minio.minio_reader import MinIOReader

# python -m data_sinkers.readers.minio.minio_reader_test

def test_minio_download():
    # Configure your MinIO connection
    config = {
        'host': '192.168.xxx.xxx:9000',
        'access_key': 'minioadmin',
        'secret_key': 'minioadmin',
        'bucket': 'dac'
    }

    test_objects = [
        'naive.pdf',
        'naive.docx'
    ]
    
    reader = MinIOReader(config)
    
    try:
        # docs = reader.query()
        docs = reader.query(objects=test_objects)
        print(f"\nTesting docs for: {docs}")
                
    finally:
        reader.close()
        print("\nConnection closed")

def main():
    print("=== Starting MinIOReader Tests ===")
    
    # Test basic file downloads
    print("\n=== Testing basic file downloads ===")
    test_minio_download()

if __name__ == "__main__":
    main()
