"""
ExcelProcessor manual test — by_rows with hybrid header detection.

Run:
    PYTHONPATH=. python -m data_sinkers.file_processors.excel_test

Optional env:
    EXCEL_HEADER_LLM    true/false (default true; needs API_KEY for LLM call)
    API_KEY / BASE_URL / Model / PROVIDER  for LLM header fallback
"""

import logging
import os
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)

from .excel import ExcelProcessor
from .excel_header import get_last_header_resolution

KAOGU_CANDIDATES = [
    os.environ.get("KAOGU_XLSX", ""),
    "/Users/james/daocloud/code/raytest/dac/tests-data/files/kaogu.xlsx",
]


def _resolve_kaogu_path() -> Optional[str]:
    for path in KAOGU_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def _print_header_resolution() -> None:
    resolved = get_last_header_resolution()
    print("\n--- Header detection result ---")
    if not resolved:
        print("  ✗ no header resolution available")
        return
    print(f"  method:      {resolved.method}")
    print(f"  header rows: {resolved.data_start}")
    print(f"  columns ({len(resolved.column_names)}):")
    for i, name in enumerate(resolved.column_names):
        print(f"    C{i}: {name}")


def _print_document_samples(docs: List) -> None:
    if not docs:
        print("  (no documents)")
        return

    indices = [0]
    for i, doc in enumerate(docs):
        if "五铢" in doc.page_content:
            indices.append(i)
            break
    if len(docs) > 1:
        indices.append(len(docs) - 1)

    seen = set()
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        doc = docs[idx]
        print(f"\nDocument {idx + 1} (row_index={doc.metadata.get('row_index')}):")
        print(f"  header_method: {doc.metadata.get('header_method')}")
        print(f"  content:\n{doc.page_content}")
        print(f"  metadata: {doc.metadata}")


def test_excel_processor_with_local_file() -> None:
    print("Starting ExcelProcessor test (by_rows + hybrid header)...")

    file_path = _resolve_kaogu_path()
    if not file_path:
        print("✗ kaogu.xlsx not found. Set KAOGU_XLSX or place file in tests-data.")
        return

    processor = ExcelProcessor()
    print("✓ ExcelProcessor initialized")
    print(f"✓ Test file: {file_path}")
    print(f"  size: {os.path.getsize(file_path)} bytes")
    print(f"  EXCEL_HEADER_LLM: {os.getenv('EXCEL_HEADER_LLM', 'true')}")
    print(f"  Model: {os.getenv('Model', '(not set)')}")

    try:
        print("\n--- process_excel (loader_type=by_rows) ---")
        result = processor.process_excel(file_path, loader_type="by_rows")
        print(f"✓ documents: {len(result)}")

        _print_header_resolution()

        if result:
            methods = {d.metadata.get("header_method") for d in result}
            print(f"\n  header_method(s) in docs: {methods}")

        print("\n--- Sample documents ---")
        _print_document_samples(result)

        print("\n" + "=" * 50)
        print("All tests completed! ✓")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_excel_processor_with_local_file()
