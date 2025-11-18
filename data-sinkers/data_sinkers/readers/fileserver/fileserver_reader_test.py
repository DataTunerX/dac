import os
from data_sinkers.readers.fileserver.fileserver_reader import FileServerReader

# python -m data_sinkers.readers.fileserver.fileserver_reader_test

def test_file_download():
    # Configure your Nginx file server URL
    config = {
        'host': '192.168.xxx.xxx',
        'port': '8000'
    }
    
    # Files to test (should exist on your Nginx server)
    test_files = [
        'naive.txt',
        'naive.pdf',
        'naive.docx'
    ]
    
    reader = FileServerReader(config)
    
    try:
        # Initialize client connection
        reader._client = reader._connect()
        
        for file_path in test_files:
            print(f"\nTesting file_path for: {file_path}")
            
            docs = reader.query(file_path)

            print(f"\nTesting docs for: {docs}")
                
    finally:
        reader.close()
        print("\nConnection closed")

def main():
    print("=== Starting FileServerReader Tests ===")
    
    # Test basic file downloads
    print("\n=== Testing basic file downloads ===")
    test_file_download()

if __name__ == "__main__":
    main()
