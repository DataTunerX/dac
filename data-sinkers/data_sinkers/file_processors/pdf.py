from typing import List, Dict, Optional, Union, Any, Literal
from langchain_community.document_loaders import (
    PyPDFium2Loader, 
    PDFPlumberLoader, 
    PyMuPDFLoader, 
    PDFMinerLoader,
    UnstructuredPDFLoader
)
from langchain.schema import Document
import logging
import os
from .mineru import MinerULoader


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PDFProcessor")


class PDFProcessor:
 
    def __init__(self):
        logger.info(f"PDFProcessor init")
    
    def load_with_pypdfium2(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = PyPDFium2Loader(
                file_path=file_path,
                mode="single",
                pages_delimiter=kwargs.get("pages_delimiter", "\n\f"),
                extract_images=kwargs.get("extract_images", False),
            )
            documents = loader.load()
            logger.info(f"PyPDFium2Loader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"PyPDFium2Loader failed: {e}")
            return []
    
    def load_with_pdfplumber(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = PDFPlumberLoader(file_path)
            documents = loader.load()
            logger.info(f"PDFPlumberLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"PDFPlumberLoader failed: {e}")
            return []
    
    def load_with_pymupdf(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = PyMuPDFLoader(file_path)
            documents = loader.load()
            logger.info(f"PyMuPDFLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"PyMuPDFLoader failed: {e}")
            return []
    
    def load_with_pdfminer(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = PDFMinerLoader(file_path)
            documents = loader.load()
            logger.info(f"PDFMinerLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"PDFMinerLoader failed: {e}")
            return []

    def load_with_unstructured(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = UnstructuredPDFLoader(
                file_path, mode="elements", strategy="auto", chunking_strategy="by_title", max_characters=1000,
            )
            documents = loader.load()
            logger.info(f"UnstructuredPDFLoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"UnstructuredPDFLoader failed: {e}")
            return []

    def load_with_ragflow(self, file_path: str, **kwargs) -> List[Document]:
        return []

    def load_with_mineru(self, file_path: str, **kwargs) -> List[Document]:
        try:
            loader = MinerULoader(file_path)
            documents = loader.load()
            logger.info(f"MinerULoader loaded {len(documents)} pages from {os.path.basename(file_path)}")
            return documents
        except Exception as e:
            logger.error(f"MinerULoader failed: {e}")
            return []
    
    def process_pdf(
        self, 
        file_path: str, 
        loader_type: str = "auto",
        **loader_kwargs
    ) -> Union[List[Document], Dict]:

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        if loader_type == "auto":
            loader_type = self._select_best_loader(file_path)

        loader_methods = {
            "pypdfium2": self.load_with_pypdfium2,
            "pdfplumber": self.load_with_pdfplumber,
            "pymupdf": self.load_with_pymupdf,
            "pdfminer": self.load_with_pdfminer,
            "unstructured": self.load_with_unstructured,
            "ragflow": self.load_with_ragflow,
            "mineru": self.load_with_mineru,
        }
        
        if loader_type not in loader_methods:
            raise ValueError(f"Unsupported loader type: {loader_type}. Supported: {list(loader_methods.keys())}")
        
        raw_documents = loader_methods[loader_type](file_path, **loader_kwargs)

        return raw_documents

    def _select_best_loader(self, file_path: str) -> str:

        file_size = os.path.getsize(file_path)

        if file_size > 10 * 1024 * 1024:
            return "pymupdf"
        else:
            return "mineru"
    
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
                
                split_docs = self.process_pdf(file_path, loader_type, **kwargs)
                results[filename] = split_docs
                
                logger.info(f"✓ Successfully processed {filename}: {len(split_docs)} chunks")
                
            except Exception as e:
                logger.error(f"✗ Failed to process {file_path}: {e}")
                results[file_path] = []
        
        return results
