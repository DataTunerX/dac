import requests
import tempfile
import os
from typing import Any, Dict, Optional, Tuple, List
from abc import ABC, abstractmethod
from langchain.schema import Document
from ..base.base_reader import BaseDataReader
from ...file_processors.general import Processor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fileserver_reader")

class FileServerReader(BaseDataReader):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._validate_config()
        self._client = self._connect()
    
    def _validate_config(self) -> None:
        """验证配置"""
        assert 'host' in self.config, "miss host"
        assert 'port' in self.config, "miss port"
    
    def _connect(self) -> requests.Session:
        return requests.Session()
    
    def query(self, endpoint: str, **kwargs) -> List[Document]:
        url = f"http://{self.config['host']}:{self.config['port']}/{endpoint}"
        params = kwargs.get('params', None)
        
        result = []
        temp_path = ""
        filename = ""
        
        try:
            response = self._client.get(url, params=params, stream=True)
            response.raise_for_status()
            
            # Get filename from headers or fallback to URL
            content_disposition = response.headers.get('Content-Disposition', '')
            filename = None
            
            # Try from Content-Disposition first
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"\'')
            
            # Fallback 1: From URL if path-like
            if filename is None and '/' in endpoint:
                filename = endpoint.split('/')[-1]
            
            # Fallback 2: Use last part of URL
            if filename is None:
                filename = endpoint.split('?')[0].split('/')[-1]  # Remove query params
            
            # Create temp file
            suffix = os.path.splitext(filename)[1] if filename else None
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        tmp_file.write(chunk)
                temp_path = tmp_file.name

            chunk_size = 1000
            splitter_type = "recursive"

            processor = Processor(
                chunk_size=chunk_size,
                chunk_overlap=chunk_size // 5,
                splitter_type=splitter_type
            )
            
            result = processor.process_file(temp_path)
            
            return result

        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            logger.error(f"Error processing {url}: {e}")
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    
    def close(self) -> None:
        if hasattr(self, '_client') and self._client is not None:
            self._client.close()
            self._client = None