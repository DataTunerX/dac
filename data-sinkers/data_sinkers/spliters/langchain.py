from langchain.text_splitter import CharacterTextSplitter, RecursiveCharacterTextSplitter
from typing import Literal, Optional, List, Iterable
from langchain.schema import Document

class TextSplitterWrapper:
    """
    Unified text splitting utility class
    
    Provides two splitting methods:
    - 'character': Basic character splitter for structured text: For structured texts like legal clauses, code, etc., use CharacterTextSplitter with appropriate separators
    - 'recursive': Recursive character splitter (default), for regular text processing: Use the default RecursiveCharacterTextSplitter, which works better for most text types
    """
    
    def __init__(
        self,
        splitter_type: Literal['character', 'recursive'] = 'recursive',
        chunk_size: int = 5000,
        chunk_overlap: int = 200,
        max_document_length: Optional[int] = None,
        **kwargs
    ):
        """
        Initialize text splitter
        
        Args:
            splitter_type: Splitter type ('character' or 'recursive')
            chunk_size: Maximum length of each text chunk
            chunk_overlap: Number of overlapping characters between chunks
            max_document_length: Maximum document length, documents longer than this will be split (None means always split)
            **kwargs: Other parameters passed to the splitter
        """
        self.splitter_type = splitter_type
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_document_length = max_document_length
        
        # Initialize splitter
        common_params = {
            'chunk_size': chunk_size,
            'chunk_overlap': chunk_overlap,
            'length_function': len,
            'is_separator_regex': False
        }
        
        if splitter_type == 'character':
            self.splitter = CharacterTextSplitter(**common_params, **kwargs)
        else:
            self.splitter = RecursiveCharacterTextSplitter(**common_params, **kwargs)
    
    def split_text(self, text: str) -> List[str]:
        """
        Split text
        
        Args:
            text: Text to be split
            
        Returns:
            List of split text chunks
        """
        # If max length is set and text doesn't exceed it, return directly
        if self.max_document_length is not None and len(text) <= self.max_document_length:
            return [text]
            
        return self.splitter.split_text(text)
    
    def split_documents(self, documents: Iterable[Document]) -> List[Document]:
        """
        Split documents
        
        Args:
            documents: Documents to be split
            
        Returns:
            List of split documents
        """
        
        return self.splitter.split_documents(documents)
