from typing import List, Dict, Optional, Union, Any, Literal
from langchain_community.document_loaders import (
    PyPDFium2Loader, 
    PDFPlumberLoader, 
    PyMuPDFLoader, 
    PDFMinerLoader,
    UnstructuredPDFLoader
)
from langchain_core.documents import Document
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

        # Stamp the loader used onto every doc so downstream process_file can branch
        # (e.g. pymupdf → merge+CharacterTextSplitter, mineru → keep markdown-header splits).
        for d in raw_documents:
            if isinstance(d, Document):
                md = dict(d.metadata) if d.metadata else {}
                md["pdf_loader"] = loader_type
                d.metadata = md

        return raw_documents

    def _select_best_loader(self, file_path: str) -> str:

        file_size = os.path.getsize(file_path)
        max_mineru_bytes = 1000 * 1024 * 1024  # 1000 MB

        # Two independent knobs (both set by execution-engine from the DD spec):
        #   - PDF_LOADER_POLICY: "auto" (default) | "ocr" | "text"
        #     Selects PDF processing by capability (not library name).
        #   - MINERU_DEVICE_MODE: "cuda" | "cpu"
        #     Controls which device the OCR/layout backend runs on.
        #
        # Decision matrix:
        #   policy=text                          -> pymupdf (text layer only, no OCR)
        #   policy=ocr + size < 1GB              -> mineru (OCR/layout; cuda or cpu per device mode)
        #   policy=auto + gpu_available + <1GB   -> mineru (OCR when GPU available)
        #   anything else (no GPU under auto, or file too large) -> pymupdf
        policy = (os.getenv("PDF_LOADER_POLICY", "auto") or "").strip().lower() or "auto"
        # Legacy technology-named policy values (pre ocr/text rename).
        if policy == "mineru":
            policy = "ocr"
        elif policy == "pymupdf":
            policy = "text"
        mineru_device_mode = (os.getenv("MINERU_DEVICE_MODE", "cpu") or "").strip().lower()
        gpu_available = mineru_device_mode == "cuda"
        too_big = file_size >= max_mineru_bytes

        if policy == "text":
            logger.info("PDF loader selected: pymupdf (PDF_LOADER_POLICY=text, text layer only)")
            return "pymupdf"

        if policy == "ocr":
            if too_big:
                logger.info(
                    "PDF loader selected: pymupdf (PDF_LOADER_POLICY=ocr but file too large: "
                    "file_size=%d bytes >= %d, falling back to text layer)",
                    file_size, max_mineru_bytes,
                )
                return "pymupdf"
            logger.info(
                "PDF loader selected: mineru (PDF_LOADER_POLICY=ocr, MINERU_DEVICE_MODE=%s, "
                "file_size=%d bytes) — OCR/layout parsing",
                mineru_device_mode, file_size,
            )
            return "mineru"

        # policy == "auto" (and any unknown value falls back here)
        if gpu_available and not too_big:
            logger.info(
                "PDF loader selected: mineru (PDF_LOADER_POLICY=auto, MINERU_DEVICE_MODE=%s, "
                "file_size=%d bytes, OCR when GPU available)",
                mineru_device_mode, file_size,
            )
            return "mineru"

        reason = "no GPU (MINERU_DEVICE_MODE=%s)" % mineru_device_mode
        if too_big:
            reason = "file too large for OCR backend (%d bytes >= %d)" % (file_size, max_mineru_bytes)
        logger.info("PDF loader selected: pymupdf (PDF_LOADER_POLICY=auto, %s, text layer only)", reason)
        return "pymupdf"
    
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
