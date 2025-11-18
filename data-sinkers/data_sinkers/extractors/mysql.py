import os
import json
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.mysql.mysql_reader import MySQLReader
from ..api.base import DocumentModel
from ..prompts.mysql import build_mysql_prompt
from ..prompts.mysql import format_schema_to_markdown as mysql_format_schema_to_markdown
from ..prompts.mysql import format_one_schema_to_markdown as mysql_format_one_schema_to_markdown
from ..analyzers.fingerprint import FingerprintAnalyzer
from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.vector_client import VectorClient
from ..client.fingerprint_client import FingerprintClient, FingerprintData
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import logging


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mysql_extractor")

# Process 5 tables as one document
DEFAULT_SQL_BATCHSIZE = 5

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

def extract_mysql(
        reader: MySQLReader, 
        descriptor: Dict[str, Any], 
        extract: Dict[str, Any], 
        prompts: Dict[str, Any], 
        fingerprint_analyzer: FingerprintAnalyzer, 
        fingerprint_client: FingerprintClient,
        enable_allinone: str, 
        enable_sample_data: str,
        sql_process_mode: str
    ) -> List[DocumentModel]:

    results: List[DocumentModel] = []

    tables = extract.get('tables', [])

    logger.debug(f"===========extract_mysql, tables = {tables}")

    # If tables are specified, only get schemas of these tables, otherwise get all table schemas in the database.
    schema_results:List[Dict[str, Any]] = []
    if tables:
        schema_results = reader.schema(tables)
    else:
        schema_results = reader.schema()

    logger.debug(f"===========extract_mysql, schema_results = {schema_results}")

    # Tables relationship
    schema_relationship:Dict[str, Any] = {}
    if tables:
        schema_relationship = reader.schema_relationship(tables)
    else:
        schema_relationship = reader.schema_relationship()
    schema_relationship_str = json.dumps(schema_relationship, ensure_ascii=False, indent=2)
    schema_relationship_md = fingerprint_analyzer.generate_table_relationship(schema_relationship_str)

    logger.debug(f"extract_mysql, schema_relationship = {schema_relationship_str}")

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

    # Use LLM to generate DD fingerprint, then send to fingerprint database, containing DD fingerprint
    batch_size = get_safe_batch_size()
    fingerprint_document, batch_fingerprints = fingerprint_analyzer.analyze(schema_results, datasource_type="mysql", batch_size=batch_size)
    logger.debug(f"extract_mysql analyze, fingerprint_document = {fingerprint_document}")

    # Add fingerprint to fingerprint database
    fingerprint = FingerprintData(
            fingerprint_id=fingerprint_document.metadata["fingerprint_id"],
            fingerprint_summary=fingerprint_document.page_content,
            agent_info_name=fingerprint_document.metadata["agent_info_name"],
            agent_info_description=fingerprint_document.metadata["agent_info_description"],
            dd_namespace=descriptor.get('namespace'),
            dd_name=descriptor.get('name')
        )
    fingerprint_client.create_fingerprint(fingerprint)
    logger.info("========== extract_mysql, add fingerprint to fingerprint database success=")

    # Build document, then send to dataservices. All-in-one
    if enable_allinone == "enable":
        schema_md_str = mysql_format_schema_to_markdown(schema_results)
        logger.info(f"extract_mysql, schema_md_str = {schema_md_str}")

        tables_document = ""
        if enable_sample_data == "enable":
            # If tables are specified, only get sample data of these tables, otherwise get all table sample data in the database.
            sample_data_results = ""
            if tables:
                sample_data_results = reader.sample(tables)
            else:
                sample_data_results = reader.sample()

            tables_document = f"key information:\n{background_knowledge}\n\n{fingerprint_document.page_content} \n\ntable list:\n{schema_md_str} \n\ntable relationship:\n{schema_relationship_md}\n\nsample data:\n{sample_data_results}\n\nfewshots:\n{fewshots}\n\n"
        else:
            tables_document = f"key information:\n{background_knowledge}\n\n{fingerprint_document.page_content} \n\ntable list:\n{schema_md_str} \n\ntable relationship:\n{schema_relationship_md}\n\nfewshots:\n{fewshots}\n\n"

        results = [
            DocumentModel(
                page_content=tables_document,
                metadata={
                    "source_type": "mysql",
                    "dd_namespace": descriptor.get('namespace'),
                    "dd_name": descriptor.get('name'),
                    "fingerprint_id": fingerprint_document.metadata["fingerprint_id"],
                    "fingerprint_summary": fingerprint_document.metadata["fingerprint_summary"],

                }
            )
        ]
    else:
        if sql_process_mode=="batch":
            # Build document, then send to dataservices. Some tables schema -> one document
            batch_size = get_safe_batch_size()

            total_batches = (len(schema_results) + batch_size - 1) // batch_size
            for i in range(0, len(schema_results), batch_size):
                batch = schema_results[i:i + batch_size]
                batch_number = i // batch_size
                
                batch_sql_schema_md = mysql_format_schema_to_markdown(batch)

                # Reuse already generated batch fingerprints
                tables_fingerprint_id = ""
                tables_fingerprint = ""
                if batch_fingerprints and batch_number < len(batch_fingerprints):
                    batch_fingerprint_info = None
                    for bp in batch_fingerprints:
                        if bp["batch_number"] == batch_number:
                            batch_fingerprint_info = bp
                            break

                    tables_fingerprint_id = batch_fingerprint_info["fingerprint_id"]
                    tables_fingerprint = batch_fingerprint_info["fingerprint_summary"]
                else:
                    logger.warning(f"Batch {batch_number + 1} fingerprint does not exist")

                tables_document = ""
                if enable_sample_data == "enable":
                    batch_table_names = [table['table_name'] for table in batch]
                    sample_data_results = reader.sample(batch_table_names)
                    tables_document = f"{tables_fingerprint} \n\n {batch_sql_schema_md} \n\ntable relationship:\n{schema_relationship_md}\n\nsample data:\n{sample_data_results}"
                else:
                    tables_document = f"{tables_fingerprint} \n\n {batch_sql_schema_md} \n\ntable relationship:\n{schema_relationship_md}\n\n"

                logger.info(f"extract_mysql processing batch {batch_number + 1}/{total_batches}, current batch count: {len(batch)}")

                results.append(
                    DocumentModel(
                        page_content=tables_document,
                        metadata={
                            "source_type": "mysql",
                            "dd_namespace": descriptor.get('namespace'),
                            "dd_name": descriptor.get('name'),
                            "fingerprint_id": tables_fingerprint_id
                        }
                    )
                )
        elif sql_process_mode == "dictionary":
            # Build document, then send to dataservices. Some tables schema -> one document
            batch_size = get_safe_batch_size()
            total_batches = (len(schema_results) + batch_size - 1) // batch_size
            
            # Step 1: Collect markdown data for all batches
            batch_tasks = []
            for i in range(0, len(schema_results), batch_size):
                batch = schema_results[i:i + batch_size]
                batch_number = i // batch_size
                logger.info(f"extract_mysql processing batch {batch_number + 1}/{total_batches} for schema_to_markdown, current batch count: {len(batch)}")
                
                batch_sql_schema_md = mysql_format_schema_to_markdown(batch)
                if batch_sql_schema_md:
                    batch_tasks.append((batch_number, batch_sql_schema_md))
            
            # Step 2: Use thread pool to parallel process generate_tables_summary
            batch_results = []
            
            if batch_tasks:
                # Set max concurrency based on actual situation, using min(CPU cores, total batches)
                max_workers = 10
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks, maintaining order
                    future_to_index = {}
                    for index, markdown in batch_tasks:
                        future = executor.submit(fingerprint_analyzer.generate_tables_summary, markdown)
                        future_to_index[future] = index
                    
                    # Collect results and sort by original order
                    temp_results = [None] * len(batch_tasks)
                    for future in concurrent.futures.as_completed(future_to_index):
                        idx = future_to_index[future]
                        try:
                            batch_tables_summary = future.result()
                            logger.info(f"extract_mysql processing batch {idx + 1}/{total_batches}, batch_tables_summary = {batch_tables_summary}")
                            temp_results[idx] = batch_tables_summary
                        except Exception as exc:
                            logger.error(f"Batch {idx + 1} error generating table summary: {exc}")
                            # Use empty string as placeholder when error occurs
                            temp_results[idx] = ""
                    
                    # Add successful results to batch_results
                    for result in temp_results:
                        if result is not None:
                            batch_results.append(result)
            
            # Step 3: Build final result
            if not batch_results:
                # If all batches failed, use empty result
                batch_result_str = ""
            else:
                # Merge all batch results
                batch_result_str = "\n".join(batch_results)
            # Sample data is not used here; actual sample data collection is done in the expert agent based on selected tables.
            tables_document = f"key information:\n{background_knowledge}\n\ntable list:\n{batch_result_str}\n\ntable relationship:\n{schema_relationship_md}\n\nfewshots:\n{fewshots}\n\n"
            results = [
                DocumentModel(
                    page_content=tables_document,
                    metadata={
                        "source_type": "mysql",
                        "dd_namespace": descriptor.get('namespace'),
                        "dd_name": descriptor.get('name')
                    }
                )
            ]
        else:
            pass
            
    return results
