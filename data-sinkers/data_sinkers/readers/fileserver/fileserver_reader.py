import requests
import tempfile
import os
from typing import Any, Dict, Optional, Tuple, List
from langchain_core.documents import Document
from ..base.base_reader import BaseDataReader
from ...file_processors.general import Processor
from ..per_file_summary import build_per_file_summary_document
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fileserver_reader")

FILESERVER_ENDPOINT_KEY = "fileserver_endpoint"


def _fileserver_uri(host: str, port: str, endpoint: str) -> str:
    """Canonical URI for Map-Reduce / pyramid metadata (aligned with minio:// style)."""
    ep = str(endpoint or "").lstrip("/")
    return f"fileserver://{host}:{port}/{ep}"


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
    
    def query_one(self, endpoint: str, **kwargs) -> List[Document]:
        """Download one file from file-server, chunk, attach ``source`` metadata."""
        host = str(self.config["host"])
        port = str(self.config["port"])
        endpoint = str(endpoint).lstrip("/")
        url = f"http://{host}:{port}/{endpoint}"
        params = kwargs.get("params", None)

        result: List[Document] = []
        temp_path = ""
        filename = ""

        try:
            response = self._client.get(url, params=params, stream=True)
            response.raise_for_status()

            content_disposition = response.headers.get("Content-Disposition", "")
            filename = None

            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[1].strip("\"'")

            if filename is None and "/" in endpoint:
                filename = endpoint.split("/")[-1]

            if filename is None:
                filename = endpoint.split("?")[0].split("/")[-1]

            suffix = os.path.splitext(filename)[1] if filename else None
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        tmp_file.write(chunk)
                temp_path = tmp_file.name

            file_size = os.path.getsize(temp_path) if temp_path else 0
            chunk_size = 1000
            processor = Processor(
                chunk_size=chunk_size,
                chunk_overlap=chunk_size // 5,
                splitter_type="recursive",
            )

            result = processor.process_file(temp_path)
            file_uri = _fileserver_uri(host, port, endpoint)
            extra_meta: Dict[str, Any] = {
                "name": endpoint,
                FILESERVER_ENDPOINT_KEY: endpoint,
                "source": file_uri,
                "file_path": file_uri,
                "minio_path": file_uri,
                "fileserver_host": host,
                "fileserver_port": port,
                "file_size": file_size,
            }
            for doc in result:
                base = dict(doc.metadata) if doc.metadata else {}
                base.update(extra_meta)
                doc.metadata = base

            return result

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def query(self, endpoint: str, **kwargs) -> List[Document]:
        """Backward-compatible alias for :meth:`query_one`."""
        return self.query_one(endpoint, **kwargs)

    def query_files(
        self,
        files: List[str],
        file_analyzer: Any = None,
        **kwargs,
    ) -> Tuple[List[Document], List[Document]]:
        """Process configured file list sequentially (L1 chunk + optional L2 per-file summary).

        Returns:
            (all_chunk_documents, per_file_summary_documents)
        """
        host = str(self.config["host"])
        port = str(self.config["port"])
        all_documents: List[Document] = []
        per_file_summaries: List[Document] = []

        for i, endpoint in enumerate(files):
            ep = str(endpoint).strip().lstrip("/")
            if not ep:
                continue
            logger.info(
                "Processing fileserver file %d/%d: %s",
                i + 1,
                len(files),
                ep,
            )
            try:
                documents = self.query_one(ep, **kwargs)
                all_documents.extend(documents)
                if documents and file_analyzer is not None:
                    file_uri = _fileserver_uri(host, port, ep)
                    summary_doc = build_per_file_summary_document(
                        file_analyzer,
                        documents,
                        file_uri=file_uri,
                        extra_metadata={
                            FILESERVER_ENDPOINT_KEY: ep,
                            "fileserver_host": host,
                            "fileserver_port": port,
                        },
                    )
                    if summary_doc is not None:
                        per_file_summaries.append(summary_doc)
                logger.info(
                    "Fileserver file %s done: chunks=%d per_file_summary=%s",
                    ep,
                    len(documents),
                    "yes" if documents and file_analyzer else "no",
                )
            except Exception as e:
                logger.error("Error processing fileserver file %s: %s", ep, e)
                continue

        return all_documents, per_file_summaries
    
    def close(self) -> None:
        if hasattr(self, '_client') and self._client is not None:
            self._client.close()
            self._client = None