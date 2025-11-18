from typing import List, Dict, Optional, Union, Any, Literal
from langchain_community.document_loaders import (
        UnstructuredCSVLoader,
        CSVLoader,
    )
from langchain.schema import Document
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CsvProcessor")


class CsvProcessor:

    def __init__(self):
        logger.info(f"CsvProcessor init")

    def load_with_langchain(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = CSVLoader(file_path)
            documents = loader.load()
            logger.info(f"CSVLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"CSVLoader failed: {e}")
            return []
    
    def load_with_unstructured(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = UnstructuredCSVLoader(
                file_path, mode="elements", strategy="auto", chunking_strategy="by_title", max_characters=1000,
            )
            documents = loader.load()
            logger.info(f"UnstructuredCSVLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"UnstructuredCSVLoader failed: {e}")
            return []

    def load_with_ragflow(self, file_path: str, **kwargs) -> List[Document]:
        return []
    
    def process_csv(
        self, 
        file_path: str, 
        loader_type: str = "auto",
        **loader_kwargs
    ) -> Union[List[Document], Dict]:

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"csv file not found: {file_path}")
        
        if loader_type == "auto":
            loader_type = self._select_best_loader(file_path)
        
        loader_methods = {
            "langchain": self.load_with_langchain,
            "unstructured": self.load_with_unstructured,
            "ragflow": self.load_with_ragflow
        }
        
        if loader_type not in loader_methods:
            raise ValueError(f"Unsupported loader type: {loader_type}. Supported: {list(loader_methods.keys())}")
        
        raw_documents = loader_methods[loader_type](file_path, **loader_kwargs)

        return raw_documents

    def _select_best_loader(self, file_path: str) -> str:

        file_size = os.path.getsize(file_path)

        # return "unstructured"
        return "langchain"
    
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
                
                split_docs = self.process_csv(file_path, loader_type, **kwargs)
                results[filename] = split_docs
                
                logger.info(f"✓ Successfully processed {filename}: {len(split_docs)} chunks")
                
            except Exception as e:
                logger.error(f"✗ Failed to process {file_path}: {e}")
                results[file_path] = []
        
        return results
