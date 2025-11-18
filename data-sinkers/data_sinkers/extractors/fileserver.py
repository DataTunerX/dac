import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.fileserver.fileserver_reader import FileServerReader
from ..api.base import DocumentModel
from ..analyzers.fingerprint import FingerprintAnalyzer
from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.vector_client import VectorClient
from ..client.fingerprint_client import FingerprintClient, FingerprintData
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fileserver_extractor")

def extract_fileserver(
		reader: FileServerReader, 
		descriptor: Dict[str, Any], 
		extract: Dict[str, Any], 
		prompts: Dict[str, Any],
		fingerprint_analyzer: FingerprintAnalyzer, 
		fingerprint_client: FingerprintClient,
		enable_allinone: str, 
		enable_sample_data: str
	) -> List[DocumentModel]:

    results: List[DocumentModel] = []

    files = extract.get('files')

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
    
    if files is None:
        raise ValueError("files is None - 'files' key not found in extract dictionary")
    
    if not isinstance(files, list):
        raise ValueError(f"files must be a list, got {type(files)}")

    for file_path in files:
        logger.info(f"Processing file: {file_path}")
        
        try:
            file_results = reader.query(file_path)

            if isinstance(file_results, list):
                results.extend(file_results)
            else:
                results.append(file_results)
                
            logger.info(f"Successfully processed file {file_path}, got {len(file_results) if isinstance(file_results, list) else 1} results")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
            continue

    logger.info(f"Total results: {len(results)}")
    return results
