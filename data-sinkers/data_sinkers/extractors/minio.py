import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.minio.minio_reader import MinIOReader
from ..api.base import DocumentModel
from ..analyzers.fingerprint import FingerprintAnalyzer
from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.vector_client import VectorClient
from ..client.fingerprint_client import FingerprintClient, FingerprintData
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minio_extractor")

def extract_minio(
		reader: MinIOReader, 
		descriptor: Dict[str, Any], 
		extract: Dict[str, Any], 
		prompts: Dict[str, Any],
		fingerprint_analyzer: FingerprintAnalyzer, 
		fingerprint_client: FingerprintClient,
		enable_allinone: str, 
		enable_sample_data: str
	) -> List[DocumentModel]:

    results: List[DocumentModel] = []

    object_names = extract.get('files')

    background_knowledge = ""
    if prompts:
        background_knowledge_list = prompts.get('background_knowledge')
        if background_knowledge_list:
            background_knowledge = "\n".join([f"{i+1}. {item['description']}" for i, item in enumerate(background_knowledge_list)])
    logger.info(f"===========background_knowledge = {background_knowledge}")

    fewshots = ""
    if prompts:
        fewshots_list = prompts.get('fewshots')
        if fewshots_list:
            for i, item in enumerate(fewshots_list, 1):
                fewshots += f"{i}. user input: {item['query']} \n   sql: {item['answer']} \n\n"

            fewshots = fewshots.rstrip()
    logger.info(f"===========fewshots = {fewshots}")

    if object_names is None:
        raise ValueError("object_names is None - 'files' key not found in extract dictionary")
    
    if not isinstance(object_names, list):
        raise ValueError(f"object_names must be a list, got {type(object_names)}")

    results = reader.query(objects=object_names)

    return results