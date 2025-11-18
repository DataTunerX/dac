import os
import json
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..readers.postgres.postgres_reader import PostgresReader
from ..api.base import DocumentModel
from ..prompts.postgres import build_postgres_prompt
from ..prompts.postgres import format_schema_to_markdown as postgres_format_schema_to_markdown
from ..prompts.postgres import format_one_schema_to_markdown as postgres_format_one_schema_to_markdown
from ..analyzers.fingerprint import FingerprintAnalyzer
from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.vector_client import VectorClient
from ..client.fingerprint_client import FingerprintClient, FingerprintData
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("postgres_extractor")

# Process 5 tables as one document by default
DEFAULT_SQL_BATCHSIZE = 5

def get_safe_batch_size():
    """Safely get the batch size"""
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
        logger.warning(f"Failed to convert SQL_BATCHSIZE environment variable, using default value 5. Error: {e}")
        return DEFAULT_SQL_BATCHSIZE


def extract_postgres(
        reader: PostgresReader, 
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

    # querys = extract.get('querys', [])
    tables = extract.get('tables', [])
    # batch_size = extract.get('batchSize', 1000)

    # query_result: Dict[str, List[Dict[str, Any]]] = {}
    # for query in querys:
    #     if query and query.strip():
    #         result = reader.query(input=query, batch_size=batch_size)
    #         query_result[query] = result
    #         logger.info(f"Execute SQL query: {query}, returned {len(result) if result else 0} records")
    #     else:
    #         logger.warning(f"Skipping empty query: {query}")


    # If tables are set, only get schemas of these tables, otherwise get all table schemas in the database.
    schema_results:List[Dict[str, Any]] = []
    if tables:
        schema_results = reader.schema(tables)
    else:
        schema_results = reader.schema()

    # Table relationships
    schema_relationship:Dict[str, Any] = {}
    if tables:
        schema_relationship = reader.schema_relationship(tables)
    else:
        schema_relationship = reader.schema_relationship()
    schema_relationship_str = json.dumps(schema_relationship, ensure_ascii=False, indent=2)
    schema_relationship_md = fingerprint_analyzer.generate_table_relationship(schema_relationship_str)

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

    # Use LLM to generate DD fingerprint, then send to fingerprint database, contains DD fingerprint
    batch_size = get_safe_batch_size()
    fingerprint_document, batch_fingerprints = fingerprint_analyzer.analyze(schema_results, datasource_type="postgres", batch_size=batch_size)
    logger.debug(f"extract_postgres analyze, fingerprint_document = {fingerprint_document}")

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
    logger.info("========== extract_postgres, add fingerprint to fingerprint database success=")

    # Build document, then send to dataservices. All-in-one mode
    if enable_allinone == "enable":
        schema_md_str = postgres_format_schema_to_markdown(schema_results)
        logger.info(f"extract_postgres, schema_md_str = {schema_md_str}")

        tables_document = ""
        if enable_sample_data == "enable":
            # If tables are set, only get sample data of these tables, otherwise get all table sample data in the database.
            sample_data_results = ""
            if tables:
                sample_data_results = reader.sample(tables)
            else:
                sample_data_results = reader.sample()

            tables_document = f"key information:\n{background_knowledge}\n\n{fingerprint_document.page_content} \n\n {schema_md_str} \n\ntable relationship:\n{schema_relationship_md}\n\nsample data:\n{sample_data_results}"
        else:
            tables_document = f"key information:\n{background_knowledge}\n\n{fingerprint_document.page_content} \n\n {schema_md_str} \n\ntable relationship:\n{schema_relationship_md}\n\n"

        results = [
            DocumentModel(
                page_content=tables_document,
                metadata={
                    "source_type": "postgres",
                    "dd_namespace": descriptor.get('namespace'),
                    "dd_name": descriptor.get('name'),
                    "fingerprint_id": fingerprint_document.metadata["fingerprint_id"],
                    "fingerprint_summary": fingerprint_document.metadata["fingerprint_summary"],

                }
            )
        ]
    else:
        if sql_process_mode=="batch":
            # Build document, then send to dataservices. Some table schemas -> one document
            batch_size = get_safe_batch_size()

            total_batches = (len(schema_results) + batch_size - 1) // batch_size
            for i in range(0, len(schema_results), batch_size):
                batch = schema_results[i:i + batch_size]
                batch_number = i // batch_size
                
                batch_sql_schema_md = postgres_format_schema_to_markdown(batch)

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
                    tables_document = f"{tables_fingerprint} \n\n {batch_sql_schema_md} \n\ntable relationship:\n{schema_relationship_md}\n\nsample data:\n{sample_data_results}\n\nfewshots:\n{fewshots}\n\n"
                else:
                    tables_document = f"{tables_fingerprint} \n\n {batch_sql_schema_md} \n\ntable relationship:\n{schema_relationship_md}\n\nfewshots:\n{fewshots}\n\n"

                logger.info(f"extract_postgres processing batch {batch_number + 1}/{total_batches}, this batch count: {len(batch)}")

                results.append(
                    DocumentModel(
                        page_content=tables_document,
                        metadata={
                            "source_type": "postgres",
                            "dd_namespace": descriptor.get('namespace'),
                            "dd_name": descriptor.get('name'),
                            "fingerprint_id": tables_fingerprint_id
                        }
                    )
                )
        elif sql_process_mode == "dictionary":
            # Build document, then send to dataservices. Some table schemas -> one document
            batch_size = get_safe_batch_size()
            total_batches = (len(schema_results) + batch_size - 1) // batch_size
            
            # Step 1: Collect markdown data for all batches
            batch_tasks = []
            for i in range(0, len(schema_results), batch_size):
                batch = schema_results[i:i + batch_size]
                batch_number = i // batch_size
                logger.info(f"extract_postgres processing batch {batch_number + 1}/{total_batches} for schema_to_markdown, this batch count: {len(batch)}")
                
                batch_sql_schema_md = postgres_format_schema_to_markdown(batch)
                if batch_sql_schema_md:
                    batch_tasks.append((batch_number, batch_sql_schema_md))
            
            # Step 2: Use thread pool to parallel process generate_tables_summary
            batch_results = []
            
            if batch_tasks:
                # Set max concurrency based on实际情况, here using min(CPU cores, total batch count)
                max_workers = 10
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks, maintain order
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
                            logger.info(f"extract_postgres processing batch {idx + 1}/{total_batches}, batch_tables_summary = {batch_tables_summary}")
                            temp_results[idx] = batch_tables_summary
                        except Exception as exc:
                            logger.error(f"Batch {idx + 1} error generating table summary: {exc}")
                            # Use empty string as placeholder on error
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
            
            tables_document = f"key information:\n{background_knowledge}\n\ntable list:\n{batch_result_str}\n\ntable relationship:\n{schema_relationship_md}\n\nfewshots:\n{fewshots}\n\n"
            results = [
                DocumentModel(
                    page_content=tables_document,
                    metadata={
                        "source_type": "postgres",
                        "dd_namespace": descriptor.get('namespace'),
                        "dd_name": descriptor.get('name')
                    }
                )
            ]
        else:
            pass
            
    return results