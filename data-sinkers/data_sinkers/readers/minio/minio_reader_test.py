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
        docs, file_descriptors, per_file_summaries = reader.query(objects=test_objects)
        print(f"\nTesting docs for: {docs}")
        print(f"\nFile descriptors (from query): {file_descriptors}")
        print(f"\nPer-file summaries (empty without file_analyzer): {per_file_summaries}")
                
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
