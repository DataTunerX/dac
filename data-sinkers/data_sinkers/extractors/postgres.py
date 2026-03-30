import os
import json
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.postgres.postgres_reader import PostgresReader
from ..readers.code.github_reader import GitHubReader
from ..readers.code.gitee_reader import GiteeReader
from ..readers.code.gitlab_reader import GitLabReader
from ..api.base import DocumentModel
from ..prompts.postgres import format_schema_to_markdown_with_tables, format_schema_to_markdown_with_all_tables
from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.vector_client import VectorClient
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import logging
from .base import CodeFileLister,CodeAnalyzer,SQLAnalyzer, DEFAULT_CODE_DOWNLOAD_DIR
from model_sdk import ModelManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("postgres_extractor")

# Process 5 tables as one document
DEFAULT_SQL_BATCHSIZE = 5

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

def get_safe_batch_size():
    """Safely get batch size"""
    try:
        batch_size_str = os.getenv('SQL_BATCHSIZE', "5")
        batch_size = int(batch_size_str)
        
        # Validate batch size reasonableness
        if batch_size <= 0:
            logger.warning(f"SQL_BATCHSIZE cannot be less than or equal to 0, using default value 5. Current value: {batch_size}")
            return DEFAULT_SQL_BATCHSIZE
        if batch_size > 100:
            logger.warning(f"SQL_BATCHSIZE is too large, limiting to maximum value 100. Current value: {batch_size}")
            return 100
            
        return batch_size
        
    except (ValueError, TypeError) as e:
        logger.warning(f"SQL_BATCHSIZE environment variable conversion failed, using default value 5. Error: {e}")
        return DEFAULT_SQL_BATCHSIZE

def extract_postgres(
        sql_reader: PostgresReader, 
        descriptor: Dict[str, Any], 
        extract: Dict[str, Any], 
        prompts: Dict[str, Any], 
        codeRepo: Dict[str, Any], 
        enable_allinone: str,
        enable_sample_data: str,
        sql_process_mode: str
    ) -> (List[DocumentModel], dict):

    results: List[DocumentModel] = []
    tables = extract.get('tables', [])

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

    # download code
    local_repo_dir = ""
    
    if codeRepo and isinstance(codeRepo, dict):
        code_repo_type = codeRepo.get('codeRepoType', 'github')
        code_repo_path = codeRepo.get('codeRepoPath')
        code_repo_branch = codeRepo.get('codeRepoBranch', 'main')
        code_repo_token = codeRepo.get('codeRepoToken', '')

        logger.info(f"===========codeRepo = {codeRepo}")

        code_config = {
            'token': code_repo_token
        }

        if code_repo_type == "github":
            code_reader = GitHubReader(code_config)

        if code_repo_type == "gitee":
            code_reader = GiteeReader(code_config)
        
        if code_repo_type == "gitlab":
            code_reader = GitLabReader(code_config)

        if code_repo_path:
            local_repo_dir = code_reader.query(code_repo_path, branch=code_repo_branch)
            logger.info(f"===========local_repo_dir = {local_repo_dir}")
    
    code_analyzer = CodeAnalyzer(llm, max_workers=50, batch_size=50)

    sql_analyzer = SQLAnalyzer(llm, max_workers=20, batch_size=20)

    logger.info("Starting concurrent database and code analysis...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        db_future = executor.submit(sql_analyzer.analyze_database, sql_reader, tables, format_schema_to_markdown_with_tables)

        code_future = executor.submit(code_analyzer.analyze_code, local_repo_dir)

        try:
            db_ddd_summary, schema_results, all_tables_schema_relationship_md, all_tables_details, batch_process_schemas_result = db_future.result(timeout=3600)
            logger.info("Database analysis completed successfully.")

            code_ddd_summary, analysis_results, module_files_group_result = code_future.result(timeout=3600)
            logger.info("Code analysis completed successfully.")
        except concurrent.futures.TimeoutError:
            logger.error("Error: One or both analysis tasks timed out.")
            return results, {}
        except Exception as e:
            logger.error(f"Error during concurrent analysis: {e}")
            return results, {}

    logger.info(f"=======db_ddd_summary: {db_ddd_summary}")

    logger.info(f"=======code_ddd_summary: {code_ddd_summary}")

    ddd_str = ""

    if code_ddd_summary:
        db_sum = (db_ddd_summary or {}).get("summary") or ""
        code_sum = (code_ddd_summary or {}).get("summary") or ""
        db_and_code = f"{db_sum} \n\n{code_sum}"
        db_and_code_ddd_summary = code_analyzer.ddd(db_and_code)
        logger.info(f"db_and_code_ddd_result:\n{(db_and_code_ddd_summary or {}).get('summary')}")

        ddd_str = (db_and_code_ddd_summary or {}).get("summary") or ""
    else:
        ddd_str = (db_ddd_summary or {}).get("summary") or ""

    sql_summary, all_group_tables_for_chunk_summary = sql_analyzer.process(
        sql_reader,
        format_schema_to_markdown_with_tables,
        background_knowledge,
        fewshots,
        schema_results,
        all_tables_schema_relationship_md,
        all_tables_details,
        batch_process_schemas_result,
        ddd_str
    )

    agent_card = sql_analyzer.agent_card(ddd_str)

    # Finally package the converted results into documents.
    results = convert_sql_summary_to_document_models(sql_summary, all_group_tables_for_chunk_summary, descriptor)

    tables_schema_md_list = format_schema_to_markdown_with_all_tables(schema_results)

    fingerprint_associated_info = {
        "schema_results": schema_results,
        "tables_schema_md_list": tables_schema_md_list,
        "db_ddd" : db_ddd_summary.get("summary") if db_ddd_summary else None,
        "code_ddd": code_ddd_summary.get("summary") if code_ddd_summary else None,
        "ddd": ddd_str,
        "tables_relationship": all_tables_schema_relationship_md,
        "tables_detail": all_tables_details,
        "agent_card": agent_card
    }

    return results, fingerprint_associated_info

def convert_sql_summary_to_document_models(sql_summary, all_group_tables_for_chunk_summary, descriptor=None)-> List[DocumentModel]:
    documents = []
    
    for item in sql_summary:
        for module_name, content in item.items():

            chunk_summary_content = None
            
            for chunk_item in all_group_tables_for_chunk_summary:
                if isinstance(chunk_item, dict) and module_name in chunk_item:
                    chunk_summary_content = chunk_item[module_name]
                    break

            document = DocumentModel(
                page_content=content,
                metadata={
                    "source_type": "postgres",
                    "dd_namespace": descriptor.get('namespace') if descriptor else None,
                    "dd_name": descriptor.get('name') if descriptor else None,
                    "module_name": module_name,
                    "summary": chunk_summary_content,
                    "content_type": "database"
                }
            )
            documents.append(document)
    
    return documents
