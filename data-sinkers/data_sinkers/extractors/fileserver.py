import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.fileserver.fileserver_reader import FileServerReader
from ..api.base import DocumentModel
from model_sdk import ModelManager
from .base import FileAnalyzer
from ..fingerprint.fingerprint import compute_fileserver_object_list_hash
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fileserver_extractor")

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

def extract_fileserver(
		reader: FileServerReader, 
		descriptor: Dict[str, Any], 
		extract: Dict[str, Any], 
		prompts: Dict[str, Any]
	) -> List[DocumentModel]:

    results: List[DocumentModel] = []

    files = extract.get('files')
    
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

    file_analyzer = FileAnalyzer(llm, max_workers=50, batch_size=50)

    file_summary = file_analyzer.file_summary(results)

    summary = file_summary.get("summary") if file_summary else ""

    outline = file_summary.get("outline") if file_summary else ""

    logger.info(f"file_extractor, summary = {summary}, outline = {outline}")

    agent_card = file_analyzer.agent_card(outline)

    object_list_hash = compute_fileserver_object_list_hash(reader.config, files)

    fingerprint_associated_info = {
        "ddd": summary,
        "agent_card": agent_card,
        "object_list_hash": object_list_hash,
    }

    return results, fingerprint_associated_info
