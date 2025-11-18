import os
from .excel import ExcelProcessor

def test_excel_processor_with_local_file():
    print("Starting ExcelProcessor test...")
    
    # Initialize processor
    processor = ExcelProcessor()
    print("✓ ExcelProcessor initialized successfully")
    
    file_path = "/app/testdata/table.xlsx"
    
    # Check if file exists
    if not os.path.exists(file_path):
        print(f"✗ File does not exist: {file_path}")
        print("Please modify the file_path variable to your actual Excel file path")
        return
    
    print(f"✓ Test file: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")
    
    try:
        # 1. Test process_excel method - unstructured loader
        print("\n1. Testing process_excel...")
        result = processor.process_excel(file_path)
        print(f"✓ Successfully returned {len(result)} documents")
        
        print("2. Document content details:")
        print("=" * 80)
        
        for i, doc in enumerate(result, 1):
            print(f"Document {i}:")
            print(f"Content: {doc.page_content}")
            
            # If there is metadata, print it as well
            if hasattr(doc, 'metadata') and doc.metadata:
                # Create a copy of metadata, remove orig_elements field
                metadata_to_print = doc.metadata.copy()
                if 'orig_elements' in metadata_to_print:
                    del metadata_to_print['orig_elements']
                
                print(f"Metadata: {metadata_to_print}")
            
            print("-" * 80 + "\n")  # Separate each document with a divider
        
        print("All documents printed! ✓")

        print("\n" + "="*50)
        print("All tests completed! ✓")
        
    except Exception as e:
        print(f"\n✗ Error occurred during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_excel_processor_with_local_file()


# python -m data_sinkers.file_processors.excel_test
