import os
from .pdf import PDFProcessor

def test_pdf_processor_with_local_file():
    print("Starting PDFProcessor test...")

    processor = PDFProcessor()
    print("✓ PDFProcessor initialized successfully")

    file_path = "/app/testdata/naive.pdf"

    if not os.path.exists(file_path):
        print(f"✗ File does not exist: {file_path}")
        print("Please modify the file_path variable to your actual PDF file path")
        return

    print(f"✓ Test file: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")

    try:
        loader_types = ["pypdfium2", "pdfplumber", "pymupdf", "pdfminer", "unstructured", "mineru"]

        for loader_type in loader_types:
            print(f"\n1. Testing {loader_type} loader...")
            try:
                result = processor.process_pdf(file_path, loader_type=loader_type)
                print(f"✓ {loader_type} loaded {len(result)} documents")

                print(f"✓ result: {result} ")

                if result:
                    print(f"  First document preview: {result[0].page_content[:100]}...")

            except Exception as e:
                print(f"✗ {loader_type} failed: {e}")

        print("All documents printed! ✓")

    except Exception as e:
        print(f"\n✗ Error occurred during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_pdf_processor_with_local_file()