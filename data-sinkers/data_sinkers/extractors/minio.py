import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.minio.minio_reader import MinIOReader
from ..api.base import DocumentModel
from model_sdk import ModelManager
from .base import FileAnalyzer
from ..fingerprint.fingerprint import compute_minio_bucket_object_list_hash
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minio_extractor")

manager = ModelManager()

llm = manager.get_llm(
    provider=os.getenv("PROVIDER","openai_compatible"),
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model=os.getenv("Model"),
    temperature=0.01,
    extra_body={
        "enable_thinking": False
    },
)

def extract_minio(
		reader: MinIOReader, 
		descriptor: Dict[str, Any], 
		extract: Dict[str, Any], 
		prompts: Dict[str, Any]
	) -> List[DocumentModel]:

    results: List[DocumentModel] = []

    # Full bucket only; extract.files and extract.prefix are ignored.
    results = reader.query(prefix="", recursive=True, objects=None)

    file_analyzer = FileAnalyzer(llm, max_workers=50, batch_size=50)

    file_summary = file_analyzer.file_summary(results)

    summary = file_summary.get("summary") if file_summary else ""

    outline = file_summary.get("outline") if file_summary else ""

    logger.info(f"file_extractor, summary = {summary}, outline = {outline}")

    agent_card = file_analyzer.agent_card(outline)

    bucket = reader.config.get("bucket")
    object_list_hash = compute_minio_bucket_object_list_hash(bucket, reader.client.conn)

    fingerprint_associated_info = {
        "ddd": summary,
        "agent_card": agent_card,
        "object_list_hash": object_list_hash,
    }

    return results, fingerprint_associated_info