import os
from .word import WordProcessor

def test_word_processor_with_local_file():

    print("Starting WordProcessor test...")
    
    # Initialize processor
    processor = WordProcessor()
    print("✓ WordProcessor initialized successfully")
    
    file_path = "/app/testdata/naive.docx"
    
    # Check if file exists
    if not os.path.exists(file_path):
        print(f"✗ File does not exist: {file_path}")
        print("Please modify the file_path variable to your actual Word file path")
        return
    
    print(f"✓ Test file: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")
    
    try:
        # 1. Test process_word method
        print("\n1. Testing process_word...")
        result = processor.process_word(file_path)
        print(f"✓ Successfully returned {len(result)} documents")

        print("2. Document content details:")
        print("=" * 80)
        
        for i, doc in enumerate(result, 1):
            print(f"Document {i}:")
            print(f"Content: {doc.page_content}")
            
            # If there is metadata, print it too
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
    test_word_processor_with_local_file()


# python -m data_sinkers.file_processors.word_test
