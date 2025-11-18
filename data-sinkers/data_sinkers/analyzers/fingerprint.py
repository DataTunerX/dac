import hashlib
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from model_sdk import ModelManager
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from ..prompts.mysql import format_schema_to_markdown as mysql_format_schema_to_markdown
from ..prompts.postgres import format_schema_to_markdown as postgres_format_schema_to_markdown
from ..api.base import DocumentModel
from langchain_core.messages import SystemMessage, HumanMessage
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import time

logger = logging.getLogger(__name__)

# Initialize analyzer
Analyzer_Prompt = """
You are a helpful analysis assistant. The following content is data for an intelligent agent. 

**your target job**

1. You need to define a agent name and agent description in English based on the table definitions and data for an agent. 

2. The name should be a program variable with the first letter capitalized. Finally, output the name and description in JSON format. 

3. The name must contain a clear business domain definition. For example, it should be like "Loan Assistant" or "Borrowing Assistant", rather than vague terms like "Financial Assistant" which lack specific business meaning.

**sample data**

{
    "name": "LoanAdvisorAgent", 
    "description": "A professional intelligent advisor specializing in banking loan business analysis. Expert in deep analysis of balance sheets, loan portfolios, and retail loan details. Capable of assessing loan portfolio quality, identifying credit risk concentrations, monitoring lending trends across branches, and providing data-driven decision support for loan approval, risk pricing, and post-lending management."
}

{
    "name": "CreditAnalyzerAgent", 
    "description": "A specialized credit risk assessment expert that evaluates institutional credit health through analysis of balance sheets, deposit structures, and loan data. Able to identify abnormal credit patterns, detect potential default risks, assess customer credit quality, and provide precise analytical insights for credit policy formulation and risk management."
}

{
    "name": "FinancingConsultantAgent", 
    "description": "An enterprise financing solutions consultant that provides financing strategy recommendations based on comprehensive financial data analysis. Capable of evaluating financing needs, optimizing capital structure, analyzing cost-effectiveness of different financing channels, and offering professional advisory services for debt management, fund allocation, and financing decisions."
}

The specific content is as follows:

"""

class AnalyzeResult(BaseModel):
    name: str = Field(
        description='the name of agent'
    )

    description: str = Field(
        description='the description of agent'
    )

class FingerprintAnalyzer:
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen3-32b",
        temperature: float = 0.01,
        enable_thinking: bool = False,
        system_prompt: Optional[str] = None,
        max_concurrent: int = 10
    ):
        """
        Initialize the text analyzer
        
        Args:
            provider: LLM provider (e.g., "openai_compatible")
            api_key: API key for the LLM service
            base_url: Base URL for the API endpoint
            model: Model name to use
            temperature: Controls randomness (0.0-1.0)
            enable_thinking: Whether to enable chain-of-thought
            system_prompt: Optional system message to guide analysis
            max_concurrent: Maximum number of concurrent requests
        """
        self.manager = ModelManager()
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.system_prompt = system_prompt
        self.max_concurrent = max_concurrent
        # Initialize LLM
        self.llm = self._initialize_llm()
    
    def _initialize_llm(self):
        """Initialize the LLM instance"""
        return self.manager.get_llm(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            extra_body={"enable_thinking": self.enable_thinking}
        )
    
    def _generate_fingerprint_id(self, summary: str) -> str:
        """
        Generate fingerprint ID using MD5 hash
        
        Args:
            summary: Summary text
            
        Returns:
            MD5 hash value as fingerprint ID
        """
        return hashlib.md5(summary.encode()).hexdigest()
    
    def generate_fingerprint(self, content: str) -> Tuple[str, str]:
        """
        Generate content fingerprint (summary) and corresponding fingerprint ID using large language model
        
        Args:
            content: Original text content
            
        Returns:
            (fingerprint summary, fingerprint ID)
        """
        try:    
            # Construct prompt, requiring the model to generate a concise summary
            prompt = f"""
            Please generate a highly condensed summary fingerprint for the following text, requirements:

            **Core Objectives:**
            - Extract the most essential information kernel of the text to form a content fingerprint with high discriminative power
            - Retain key facts, core viewpoints, and important data

            **Technical Specifications:**
            - Strictly control to around 500 words (within the 400-500 word range)
            - Use high information density expression
            - Use purely factual language, avoid any subjective evaluation

            **Processing Requirements:**
            - Remove all decorative words and redundant descriptions
            - Focus on the unique information characteristics of the text
            - Ensure the summary accurately represents the core content of the original text

            Text to be processed:
            {content}

            Please output the summary fingerprint directly, no additional explanation needed.
            
            """
            
            result = self.llm.invoke([HumanMessage(content=prompt)])
            fingerprint_summary = result.content.strip()
            fingerprint_id = self._generate_fingerprint_id(fingerprint_summary)
            return fingerprint_summary, fingerprint_id
        except Exception as e:
            logger.error(f"Error generating fingerprint: {e}")
            raise

    def generate_table_relationship(self, content: str) -> str:
        """
        Use large language model to summarize relationships between tables
        Args:
            content: Original text content
        Returns:
            **Specific Relationship Details**

            | Relationship Type | Master Table → Detail Table | Association Fields | Constraint Name |
            |----------|-------------------------|---------------------------|--------------------|
            | **Self-referencing** | categories → categories | parent_id → category_id | categories_ibfk_1 |
            | **One-to-Many** | orders → order_items | order_id → order_id | order_items_ibfk_1 |
            | **One-to-Many** | products → order_items | product_id → product_id | order_items_ibfk_2 |
            | **One-to-Many** | users → orders | user_id → user_id | orders_ibfk_1 |
            | **One-to-Many** | categories → products | category_id → category_id | products_ibfk_1 |
        """
        try:    
            # Construct prompt, requiring the model to generate a concise summary
            prompt = f"""
            Organize the relationships between the tables.

            The output reference example is as follows, no other information needs to be output, display using markdown table format:

            **Specific Relationship Details**

            | Relationship Type | Master Table → Detail Table | Association Fields | Constraint Name |
            |------------|-------------------------|---------------------------|--------------------|
            | **Self-referencing** | categories → categories | parent_id → category_id | categories_ibfk_1 |
            | **One-to-Many** | orders → order_items | order_id → order_id | order_items_ibfk_1 |
            | **One-to-Many** | products → order_items | product_id → product_id | order_items_ibfk_2 |
            | **One-to-Many** | users → orders | user_id → user_id | orders_ibfk_1 |
            | **One-to-Many** | categories → products | category_id → category_id | products_ibfk_1 |

            Specific data required for analysis:
            {content}
            
            """
            
            result = self.llm.invoke([HumanMessage(content=prompt)])
            relationship = result.content.strip()
            return relationship
        except Exception as e:
            logger.error(f"Error generating relationship: {e}")
            raise

    def generate_tables_summary(self, content: str) -> str:
        """
        Use large language model to summarize relationships between tables
        Args:
            content: Original text content
        Returns:
            **categories**  
            *Product category table, supports infinite level category structure, used to organize and manage product category system*  

            - `category_id`: Unique identifier ID for category  
            - `category_name`: Category name  
            - `parent_id`: Parent category ID, points to category_id in the current table, used to build multi-level category structure. NULL indicates first-level category  
            - `description`: Detailed category description  
            - `created_at`: Category creation time  

            ---

            **order_items**  
            *Order details table, stores specific information for each product in an order, supports one order containing multiple products*  

            - `order_item_id`: Unique identifier ID for order item  
            - `order_id`: Order ID, foreign key associates with orders table, identifies the order it belongs to  
            - `product_id`: Product ID, foreign key associates with products table, identifies the purchased product  
            - `quantity`: Purchase quantity  
            - `unit_price`: Product unit price at the time of order  
            - `subtotal`: Subtotal amount, calculated field, automatically generated (quantity × unit price)  

            ---

            **orders**  
            *Main order table, stores basic order information, status, and shipping address*  

            - `order_id`: Unique identifier ID for order  
            - `user_id`: User ID, foreign key associates with users table, identifies the user the order belongs to  
            - `order_date`: Order date, indicates order time  
            - `total_amount`: Total order amount  
            - `status`: Order status: pending-processing, confirmed-confirmed, shipped-shipped, delivered-delivered, cancelled-cancelled  
            - `shipping_address`: Shipping address, detailed delivery information  

        """
        try:    
            # Construct prompt, requiring the model to generate a concise summary
            prompt = f"""
            You are a database expert, your task has two parts:
            The first task is to use about 200 words to summarize the core business capabilities responsible for all data tables based on the table names and field meanings.
            The second task is to extract key information from all data tables, including table names, table fields and comments, extract each table independently, and then display with line breaks.

            **Principles for Extracting Key Information**
            1. Keep field names and annotations, do not keep other field definitions.
            2. Keep table annotations.
            3. Do not keep non-business meaning items like primary key, auto-increment, not null, optional, default current timestamp, decimal number.

            **Output Requirements**
            First output the summary part, then output the extracted part.

            **Specific data required for analysis:**
            {content}
            
            """
            
            result = self.llm.invoke([HumanMessage(content=prompt)])
            relationship = result.content.strip()
            return relationship
        except Exception as e:
            logger.error(f"Error generating relationship: {e}")
            raise
    
    def analyze(
        self,
        data: Union[List[Dict[str, Any]], List[DocumentModel]],
        metadata: Optional[Dict[str, Any]] = None,
        custom_fingerprint: Optional[str] = None,
        datasource_type: str = None,
        batch_size: int = None
    ) -> (DocumentModel, []):
        """
        Add content fingerprint to database
        
        Args:
            data: Original content
            metadata: Metadata information
            custom_fingerprint: Custom fingerprint summary (optional)
            
        Returns:
            DocumentModel containing fingerprint ID (MD5 hash)
        """
        # Generate fingerprint summary

        document = None

        fingerprint_id = ""
        fingerprint_summary = ""

        if datasource_type == "mysql":
            fingerprint_summary, fingerprint_id, batch_fingerprints = self.process_sql_schemas_in_batches(data, datasource_type=datasource_type, batch_size=batch_size, max_length=50000)

        if datasource_type == "postgres":
            fingerprint_summary, fingerprint_id, batch_fingerprints = self.process_sql_schemas_in_batches(data, datasource_type=datasource_type, batch_size=batch_size, max_length=50000)
        
        if datasource_type == "minio":
            fingerprint_summary, fingerprint_id, batch_fingerprints = self.process_no_sql_in_batches(data, datasource_type=datasource_type, batch_size=batch_size, max_length=50000)

        if datasource_type == "fileserver":
            fingerprint_summary, fingerprint_id, batch_fingerprints = self.process_no_sql_in_batches(data, datasource_type=datasource_type, batch_size=batch_size, max_length=50000)

        logger.debug(f"############### analyze.process_sql_schemas_in_batches , fingerprint_summary: {fingerprint_summary}, fingerprint_id: {fingerprint_id}, batch_fingerprints: {batch_fingerprints}")

        agent_info = self.agent_info(fingerprint_summary)

        logger.info(f"FingerprintAnalyzer, ============== agent_info = {agent_info}")
        # Check if the same fingerprint already exists
        if self.fingerprint_exists(fingerprint_id):
            logger.info(f"Fingerprint already exists: {fingerprint_id}")
            return document, batch_fingerprints
        
        # Prepare metadata
        if metadata is None:
            metadata = {}
        
        metadata.update({
            "fingerprint_id": fingerprint_id,
            "fingerprint_length": len(fingerprint_summary),
            "created_at": datetime.now().isoformat(),
            "fingerprint_summary": fingerprint_summary,
            "agent_info_name": agent_info.name,
            "agent_info_description": agent_info.description
        })
        
        # Create document object
        document = DocumentModel(
            page_content=fingerprint_summary,
            metadata=metadata
        )
        return document, batch_fingerprints

    def _combine_batch_results(self, batch_results: List[Dict], max_length: int = 50000) -> str:
        """
        Extract partial content from multiple batch results to form a string of specified length
        
        Args:
            batch_results: List of batch results, each containing summary
            max_length: Target maximum length
        
        Returns:
            Combined string
        """
        if not batch_results:
            return ""

        # First check if the total length of all batch contents does not exceed the limit
        total_length = sum(len(batch["summary"]) for batch in batch_results)
        if total_length <= max_length:
            # If total length does not exceed limit, directly return combination of all contents
            combined_content = "\n".join(batch["summary"] for batch in batch_results)
            logger.info(f"_combine_batch_results, Total length within limit, returning all content directly, target length: {max_length}, actual length: {len(combined_content)}, batch count: {len(batch_results)}")
            return combined_content
        
        # Calculate approximate length each batch should contribute
        avg_length_per_batch = max_length // len(batch_results)
        
        combined_parts = []
        current_length = 0
        
        for batch in batch_results:
            summary = batch["summary"]
            
            # If current batch content length is less than or equal to average length, use all
            if len(summary) <= avg_length_per_batch:
                combined_parts.append(summary)
                current_length += len(summary)
            else:
                # If exceeds average length, take first avg_length_per_batch characters
                # Can be optimized to extract important parts, here simply take first N characters
                truncated_summary = summary[:avg_length_per_batch]
                combined_parts.append(truncated_summary)
                current_length += len(truncated_summary)
        
        # If combined content still exceeds maximum length, perform final truncation
        combined_content = "\n".join(combined_parts)
        if len(combined_content) > max_length:
            combined_content = combined_content[:max_length]
        
        logger.info(f"_combine_batch_results, Target length: {max_length}, actual length: {len(combined_content)}, batch count: {len(batch_results)}")
        return combined_content

    def process_sql_schemas_in_batches(self, sql_schemas: List[Dict[str, Any]], batch_size: int = 5, datasource_type: str = None, max_length: int = 50000):
        """Process SQL schema data in batches"""
        if not sql_schemas:
            logger.debug("process_sql_schemas_in_batches, sql_schemas is empty =")
            return None, None, None

        logger.debug(f"process_sql_schemas_in_batches, sql_schemas = {sql_schemas} ")

        total_batches = (len(sql_schemas) + batch_size - 1) // batch_size

        logger.debug(f"process_sql_schemas_in_batches, total_batches = {total_batches} ")

        # Store fingerprint results for each batch
        batch_results = []

        batch_fingerprints = []

        # Step 1: Collect markdown data for all batches
        batch_tasks = []
        for i in range(0, len(sql_schemas), batch_size):
            batch = sql_schemas[i:i + batch_size]
            logger.info(f"process_sql_schemas_in_batches, Processing batch {i//batch_size + 1}/{total_batches} for schema_to_markdown, this batch count: {len(batch)}")
            batch_sql_schema_md = ""

            if datasource_type == "mysql":
                batch_sql_schema_md = mysql_format_schema_to_markdown(batch)
            elif datasource_type == "postgres":
                batch_sql_schema_md = postgres_format_schema_to_markdown(batch)

            logger.debug(f"process_sql_schemas_in_batches, batch_sql_schema_md = {batch_sql_schema_md} ")
            if batch_sql_schema_md:
                batch_tasks.append((i // batch_size, batch_sql_schema_md))

        # Step 2: Use thread pool to process generate_fingerprint in parallel
        if batch_tasks:
            with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
                # Submit all tasks, maintain order
                future_to_index = {}
                for index, markdown in batch_tasks:
                    future = executor.submit(self.generate_fingerprint, markdown)
                    future_to_index[future] = index
            
                # Collect results and sort by original order
                temp_results = [None] * len(batch_tasks)
                for future in concurrent.futures.as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        fingerprint_summary, fingerprint_id = future.result()
                        logger.info(f"process_sql_schemas_in_batches, Batch {idx + 1} fingerprint generated, fingerprint_id={fingerprint_id}, fingerprint_summary={fingerprint_summary}")
                        # Store batch fingerprint information
                        batch_fingerprint_info = {
                            "batch_number": idx,
                            "fingerprint_id": fingerprint_id,
                            "fingerprint_summary": fingerprint_summary
                        }
                        batch_fingerprints.append(batch_fingerprint_info)

                        temp_results[idx] = {
                            "summary": fingerprint_summary,
                            "id": fingerprint_id
                        }
                    except Exception as exc:
                        logger.error(f"Batch {idx + 1} processing error generating fingerprint: {exc}")
                        # Use None as placeholder when error occurs, will skip later
                
                # Add successful results to batch_results
                for result in temp_results:
                    if result is not None:
                        batch_results.append(result)

        # Step 3: Determine return result based on batch count
        if len(batch_results) == 0:
            logger.debug("No batch results")
            return None, None, None
        elif len(batch_results) == 1:
            # Only one batch, directly return that batch's result
            logger.debug(f"Only one batch, Fingerprint : {batch_results[0]['summary']},  fingerprint_id: {batch_results[0]['id']}, batch_fingerprints={batch_fingerprints}")
            return batch_results[0]["summary"], batch_results[0]["id"], batch_fingerprints
        else:
            # Multiple batches, extract partial content from each batch to form specified length
            combined_content = self._combine_batch_results(batch_results, max_length)
            final_fingerprint_summary, final_fingerprint_id = self.generate_fingerprint(combined_content)
            logger.debug(f"Multiple batches, Fingerprint : {final_fingerprint_summary},  fingerprint_id: {final_fingerprint_id}, batch_fingerprints={batch_fingerprints}")
            return final_fingerprint_summary, final_fingerprint_id, batch_fingerprints

    def process_no_sql_in_batches(self, no_sql_data: List[DocumentModel], batch_size: int = 5, datasource_type: str = None, max_length: int = 50000):
        """Process non-SQL data in batches, using thread pool for parallel processing"""
        total_batches = (len(no_sql_data) + batch_size - 1) // batch_size

        # Store fingerprint results for each batch
        batch_results = []
        batch_fingerprints = []

        # Step 1: Prepare text data for all batches
        batch_tasks = []
        for i in range(0, len(no_sql_data), batch_size):
            batch = no_sql_data[i:i + batch_size]
            logger.info(f"process_no_sql_in_batches, Processing batch {i//batch_size + 1}/{total_batches}, this batch count: {len(batch)}")
            
            # Merge DocumentModel content of batch into text
            batch_content = "\n".join([doc.page_content for doc in batch])
            
            if batch_content.strip():  # Only process non-empty content
                batch_tasks.append((i // batch_size, batch_content))

        # Step 2: Use thread pool to process generate_fingerprint in parallel
        if batch_tasks:
            with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
                # Submit all tasks, maintain order
                future_to_index = {}
                for index, content in batch_tasks:
                    future = executor.submit(self.generate_fingerprint, content)
                    future_to_index[future] = index
                
                # Collect results and sort by original order
                temp_results = [None] * len(batch_tasks)
                for future in concurrent.futures.as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        fingerprint_summary, fingerprint_id = future.result()
                        logger.info(f"process_no_sql_in_batches, Batch {idx + 1} fingerprint generated, fingerprint_id={fingerprint_id}, fingerprint_summary_length={len(fingerprint_summary)}")
                        
                        # Store batch fingerprint information
                        batch_fingerprint_info = {
                            "batch_number": idx,
                            "fingerprint_id": fingerprint_id,
                            "fingerprint_summary": fingerprint_summary
                        }
                        batch_fingerprints.append(batch_fingerprint_info)

                        temp_results[idx] = {
                            "summary": fingerprint_summary,
                            "id": fingerprint_id
                        }
                    except Exception as exc:
                        logger.error(f"process_no_sql_in_batches, Batch {idx + 1} processing error generating fingerprint: {exc}")
                        # Use None as placeholder when error occurs, will skip later
                
                # Add successful results to batch_results
                for result in temp_results:
                    if result is not None:
                        batch_results.append(result)

        # Step 3: Determine return result based on batch count
        if len(batch_results) == 0:
            return None, None, None
        elif len(batch_results) == 1:
            # Only one batch, directly return that batch's result
            return batch_results[0]["summary"], batch_results[0]["id"], batch_fingerprints
        else:
            # Multiple batches, extract partial content from each batch to form specified length
            combined_content = self._combine_batch_results(batch_results, max_length)
            final_fingerprint_summary, final_fingerprint_id = self.generate_fingerprint(combined_content)
            return final_fingerprint_summary, final_fingerprint_id, batch_fingerprints

    def agent_info(
        self,
        text: str,
        custom_instructions: Optional[str] = None,
        datasource_type: str = None
    ) -> AnalyzeResult:
        """
        Analyze input text with optional instructions
        
        Args:
            text: Input text to analyze
            custom_instructions: Custom instructions for analysis
            
        Returns:
            Analysis result as string
        """
        # Retry configuration
        max_retries = 3
        retry_delay = 1  # seconds
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # Prepare messages
                messages = []

                if not self.system_prompt:
                    self.system_prompt = Analyzer_Prompt

                messages.append(SystemMessage(content=self.system_prompt))

                if custom_instructions:
                    messages.append(SystemMessage(content=custom_instructions))

                if not messages:
                    return "prompt must be provided."

                messages.append(HumanMessage(content=text))
                
                # Get analysis answer
                answer = self.llm.invoke(messages)

                logger.info(f" === DataAnalyzer.agent_info, Retry count: {retry_count}, llm = {answer}")

                # Initialize data_dict
                data_dict = None
                
                try:
                    # First try to parse raw content directly
                    data_dict = json.loads(answer.content)
                    logger.info(f" === DataAnalyzer.agent_info, data_dict = {data_dict}")
                except json.JSONDecodeError as e:
                    logger.warning(f" === DataAnalyzer.agent_info, JSONDecodeError = {e}, attempting to clean content")
                    
                    # Preprocess content: remove code block markers
                    cleaned_content = answer.content.strip()
                    
                    # Remove ```json and ``` markers
                    if cleaned_content.startswith('```json'):
                        cleaned_content = cleaned_content[7:]  # Remove ```json
                    elif cleaned_content.startswith('```'):
                        cleaned_content = cleaned_content[3:]  # Remove ```
                    
                    if cleaned_content.endswith('```'):
                        cleaned_content = cleaned_content[:-3]  # Remove trailing ```
                    
                    cleaned_content = cleaned_content.strip()  # Clean whitespace again
                    
                    try:
                        # Try to parse cleaned content
                        data_dict = json.loads(cleaned_content)
                        logger.info(f" === DataAnalyzer.agent_info, data_dict after cleaning code blocks = {data_dict}")
                    except json.JSONDecodeError as e2:
                        logger.warning(f" === DataAnalyzer.agent_info, Parse failed after cleaning: {e2}, attempting single quote conversion")
                        try:
                            # If standard JSON parsing fails, try processing Python dictionary string, convert single quotes to double quotes to make valid JSON
                            json_str = cleaned_content.replace("'", '"')
                            data_dict = json.loads(json_str)
                            logger.info(f" === DataAnalyzer.agent_info, data_dict after conversion = {data_dict}")
                        except json.JSONDecodeError as e3:
                            logger.warning(f" === DataAnalyzer.agent_info, Secondary parse failed: {e3}")

                # If parsing successful, return result
                if data_dict is not None:
                    analyze_result = AnalyzeResult(**data_dict)
                    return analyze_result
                
                # If parsing failed and still have retries left
                if retry_count < max_retries:
                    logger.warning(f" === DataAnalyzer.agent_info, Parse attempt {retry_count + 1} failed, performing retry {retry_count + 2}")
                    retry_count += 1
                    time.sleep(retry_delay)
                    continue
                else:
                    # Reached maximum retry count
                    logger.error(f" === DataAnalyzer.agent_info, Unable to parse model response format after {max_retries} retries.")
                    return None
                    
            except Exception as e:
                logger.error(f" === DataAnalyzer.agent_info, Request exception on attempt {retry_count + 1}: {e}")
                
                if retry_count < max_retries:
                    logger.warning(f" === DataAnalyzer.agent_info, Performing retry {retry_count + 2}")
                    retry_count += 1
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f" === DataAnalyzer.agent_info, Still failed after {max_retries} retries.")
                    return None

        # Should not reach here in theory, but for safety
        logger.error(" === DataAnalyzer.agent_info, Retry loop ended abnormally")
        return None
        
    def fingerprint_exists(self, fingerprint_id: str) -> bool:
        """
        Check if fingerprint ID already exists
        
        Args:
            fingerprint_id: Fingerprint ID
            
        Returns:
            Whether it exists
        """
        return False

    def check_duplicate(
        self,
        content: str,
        threshold: float = 0.8
    ) -> bool:
        """
        Check if content is duplicate
        
        Args:
            content: Content to check
            threshold: Duplicate judgment threshold
            
        Returns:
            (Whether duplicate)
        """
        return False
