from typing import List, Dict, Optional, Union, Any, Literal
from .pdf import PDFProcessor
from .word import WordProcessor
from .excel import ExcelProcessor
from .csv import CsvProcessor
from .txt import TxtProcessor
from .markdown import MarkdownProcessor
from ..spliters.langchain import TextSplitterWrapper
from langchain.schema import Document
import logging
import os


class Processor:

    def __init__(
        self, 
        chunk_size: int = 1000, 
        chunk_overlap: int = 200,
        splitter_type: Literal['character', 'recursive'] = 'recursive',
        max_document_length: Optional[int] = None,
        **splitter_kwargs
    ):
        """
        Initialize PDF processor
        
        Args:
            chunk_size: Chunk size
            chunk_overlap: Chunk overlap size
            splitter_type: Splitter type ('character' or 'recursive')
            max_document_length: Maximum document length, documents will only be split if exceeding this length
            **splitter_kwargs: Additional parameters passed to the text splitter
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        self.text_splitter = TextSplitterWrapper(
            splitter_type=splitter_type,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_document_length=max_document_length,
            **splitter_kwargs
        )
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def split_documents(self, documents: List[Document]) -> List[Document]:

        if not documents:
            return []
        
        split_docs = self.text_splitter.split_documents(documents)
        self.logger.info(f"Split {len(documents)} documents into {len(split_docs)} chunks")
        return split_docs
    
    def process_file(
        self, 
        file_path: str,
        **loader_kwargs
    ) -> Union[List[Document], Dict]:

        self.logger.info(f"Processor.process_file, file_path={file_path}")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"file not found: {file_path}")
        
        file_type = os.path.splitext(file_path)[1].lower().lstrip('.')

        self.logger.info(f"Processor.process_file, file_type={file_type}")

        raw_documents = []

        if file_type == "pdf":
            processor = PDFProcessor()
            raw_documents = processor.process_pdf(file_path)

        if file_type == "docx":
            processor = WordProcessor()
            raw_documents = processor.process_word(file_path)

        if file_type == "doc":
            processor = WordProcessor()
            raw_documents = processor.process_word(file_path)

        if file_type == "xlsx":
            processor = ExcelProcessor()
            raw_documents = processor.process_excel(file_path)

        if file_type == "csv":
            processor = CsvProcessor()
            raw_documents = processor.process_csv(file_path)

        if file_type == "txt":
            processor = TxtProcessor()
            raw_documents = processor.process_txt(file_path)

        if file_type == "md":
            processor = MarkdownProcessor()
            raw_documents = processor.process_markdown(file_path)
            
        if not raw_documents:
            raise Exception(f"Failed to load file")

        self.logger.debug(f"Processor.process_file, raw_documents={raw_documents}")

        if len(raw_documents) > 1:
            return raw_documents
        else:
            split_documents = self.text_splitter.split_documents(raw_documents)
            return split_documents
