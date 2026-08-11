from typing import List, Dict, Union
from langchain_community.document_loaders import (
        UnstructuredExcelLoader,
    )
from langchain_core.documents import Document
import logging
import os
import pandas as pd

from .excel_header import resolve_excel_header, skip_leading_empty_rows

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ExcelProcessor")


class ExcelProcessor:

    def __init__(self):
        logger.info(f"ExcelProcessor init")

    def load_with_unstructured(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = UnstructuredExcelLoader(
                file_path, mode="elements", strategy="auto", chunking_strategy="by_title", max_characters=1000,
            )
            documents = loader.load()
            logger.info(f"UnstructuredExcelLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"UnstructuredExcelLoader failed: {e}")
            return []

    def load_by_rows(self, file_path: str, **kwargs) -> List[Document]:
        try:
            sheet_name = kwargs.get("sheet_name", 0)
            excel_file = pd.ExcelFile(file_path)
            if isinstance(sheet_name, int):
                sheet_label = excel_file.sheet_names[sheet_name]
            else:
                sheet_label = sheet_name

            raw_df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
            raw_df = skip_leading_empty_rows(raw_df)

            file_label = f"{os.path.basename(file_path)}:{sheet_label}"
            header = resolve_excel_header(raw_df, file_label)
            if header is None:
                logger.error(f"load_by_rows failed: header detection failed for {file_label}")
                return []

            data_start = header.data_start
            column_names = header.column_names
            logger.info(
                f"Header detection ({header.method}): {data_start} header row(s) in {os.path.basename(file_path)}"
            )

            df = raw_df.iloc[data_start:].reset_index(drop=True)
            df.columns = column_names

            documents = []
            for idx, row in df.iterrows():
                content_parts = []
                for col_idx, col in enumerate(column_names):
                    value = row.iloc[col_idx]
                    if pd.notna(value):
                        content_parts.append(f"{col}: {value}")
                if not content_parts:
                    continue
                documents.append(
                    Document(
                        page_content="\n".join(content_parts),
                        metadata={
                            "row_index": int(idx),
                            "source": file_path,
                            "sheet_name": sheet_label,
                            "header_method": header.method,
                        },
                    )
                )

            logger.info(
                f"load_by_rows loaded {len(documents)} rows from {os.path.basename(file_path)}"
            )
            return documents
        except Exception as e:
            logger.error(f"load_by_rows failed: {e}")
            return []

    def process_excel(
        self,
        file_path: str,
        loader_type: str = "auto",
        **loader_kwargs
    ) -> Union[List[Document], Dict]:

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"excel file not found: {file_path}")

        if loader_type == "auto":
            loader_type = self._select_best_loader(file_path)

        loader_methods = {
            "by_rows": self.load_by_rows,
            "unstructured": self.load_with_unstructured,
        }

        if loader_type not in loader_methods:
            raise ValueError(f"Unsupported loader type: {loader_type}. Supported: {list(loader_methods.keys())}")

        raw_documents = loader_methods[loader_type](file_path, **loader_kwargs)

        return raw_documents

    def _select_best_loader(self, file_path: str) -> str:
        return "by_rows"

    def batch_process(
        self,
        file_paths: List[str],
        loader_type: str = "auto",
        **kwargs
    ) -> Dict[str, List[Document]]:

        results = {}

        for file_path in file_paths:
            try:
                filename = os.path.basename(file_path)
                logger.info(f"Processing {filename}...")

                split_docs = self.process_excel(file_path, loader_type, **kwargs)
                results[filename] = split_docs

                logger.info(f"✓ Successfully processed {filename}: {len(split_docs)} chunks")

            except Exception as e:
                logger.error(f"✗ Failed to process {file_path}: {e}")
                results[file_path] = []

        return results
