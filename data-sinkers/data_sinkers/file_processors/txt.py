from typing import List, Dict, Optional, Union, Any, Literal
from langchain_community.document_loaders import (
        TextLoader,
    )
from langchain.schema import Document
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TxtProcessor")


class TxtProcessor:
    
    def __init__(self):
        logger.info(f"TxtProcessor init")
    
    def load_with_langchain(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = TextLoader(file_path)
            documents = loader.load()
            logger.info(f"TextLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"TextLoader failed: {e}")
            return []
    
    def process_txt(
        self, 
        file_path: str, 
        loader_type: str = "auto",
        **loader_kwargs
    ) -> Union[List[Document], Dict]:

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"txt file not found: {file_path}")

        if loader_type == "auto":
            loader_type = self._select_best_loader(file_path)

        loader_methods = {
            "langchain": self.load_with_langchain
        }
        
        if loader_type not in loader_methods:
            raise ValueError(f"Unsupported loader type: {loader_type}. Supported: {list(loader_methods.keys())}")
        
        raw_documents = loader_methods[loader_type](file_path, **loader_kwargs)

        return raw_documents

    def _select_best_loader(self, file_path: str) -> str:

        file_size = os.path.getsize(file_path)

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
                
                split_docs = self.process_txt(file_path, loader_type, **kwargs)
                results[filename] = split_docs
                
                logger.info(f"✓ Successfully processed {filename}: {len(split_docs)} chunks")
                
            except Exception as e:
                logger.error(f"✗ Failed to process {file_path}: {e}")
                results[file_path] = []
        
        return results
