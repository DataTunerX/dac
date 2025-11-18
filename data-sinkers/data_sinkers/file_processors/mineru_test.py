import os
from .mineru import MinerULoader

def test_mineru_processor_with_local_file():
    print("Starting MinerULoader test...")
    
    # Initialize processor
    
    file_path = "/app/testdata/naive.pdf"
    
    loader = MinerULoader(file_path)
    print("✓ MinerULoader initialized successfully")

    # Check if file exists
    if not os.path.exists(file_path):
        print(f"✗ File does not exist: {file_path}")
        print("Please modify the file_path variable to your actual Excel file path")
        return
    
    print(f"✓ Test file: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")
    
    try:
        # 1. Test mineru loader
        result = loader.load()

        print("2. Document content details:")
        print("=" * 80)
        
        for i, doc in enumerate(result, 1):
            print(f"Document {i}:")
            print(f"Content: {doc.page_content}")
            
            # If there is metadata, print it as well
            if hasattr(doc, 'metadata') and doc.metadata:
                print(f"Metadata: {doc.metadata}")
            
            print("-" * 80 + "\n")  # Separate each document with a divider
        
        print("All documents printed! ✓")
        
        print("\n" + "="*50)
        print("All tests completed! ✓")
        
    except Exception as e:
        print(f"\n✗ Error occurred during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mineru_processor_with_local_file()


# python -m data_sinkers.file_processors.mineru_test
