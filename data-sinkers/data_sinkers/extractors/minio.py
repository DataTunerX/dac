import hashlib
import json
import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.minio.minio_reader import MinIOReader
from ..api.base import DocumentModel
from model_sdk import ModelManager
from .base import FileAnalyzer
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

    object_names = extract.get('files')

    if object_names is None:
        raise ValueError("object_names is None - 'files' key not found in extract dictionary")
    
    if not isinstance(object_names, list):
        raise ValueError(f"object_names must be a list, got {type(object_names)}")

    results = reader.query(objects=object_names)

    file_analyzer = FileAnalyzer(llm, max_workers=50, batch_size=50)

    file_summary = file_analyzer.file_summary(results)

    summary = file_summary.get("summary") if file_summary else ""

    outline = file_summary.get("outline") if file_summary else ""

    logger.info(f"file_extractor, summary = {summary}, outline = {outline}")

    agent_card = file_analyzer.agent_card(outline)

    # Compute object list hash for change detection (path + etag/size)
    object_list_hash = None
    try:
        bucket = reader.config.get("bucket")
        items = []
        for obj_name in object_names:
            try:
                stat = reader.client.conn.stat_object(bucket, obj_name)
                items.append((obj_name, stat.etag or "", stat.size))
            except Exception:
                items.append((obj_name, "", 0))
        items.sort(key=lambda x: x[0])
        object_list_hash = hashlib.md5(json.dumps(items).encode()).hexdigest()
    except Exception as e:
        logger.warning("Failed to compute object_list_hash: %s", e)

    fingerprint_associated_info = {
        "ddd": summary,
        "agent_card": agent_card,
        "object_list_hash": object_list_hash,
    }

    return results, fingerprint_associated_info