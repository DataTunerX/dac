import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import click
import httpx
import uvicorn
from enum import Enum
import os
import re
import asyncio
import atexit
import signal
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import uuid
import numpy as np
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Union
from pydantic import BaseModel, Field
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TaskStatus, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .dataservices_client import DataServicesClient, MetadataValuesResult  # MetadataValuesResult 用于两阶段 LLM 知识检索
from .schema import ROLE_TYPE, AgentState, Memory, Message
from .prompts import ( 
    TASK_ANALYZE_NEXT_STEP_PROMPT_ZH, 
    MYSQL_NEXT_STEP_PROMPT_ZH, 
    POSTGRES_NEXT_STEP_PROMPT_ZH, 
    TABLE_SELECTOR_NEXT_STEP_PROMPT_ZH, 
    DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH, 
    COMMON_NEXT_STEP_PROMPT_ZH, 
    REQUERY_PROMPT_ZH,
    REQUERY_SQL_PROMPT_ZH,
    OBSERVE_PROMPT_SQL_ZH,
    OBSERVE_PROMPT_COMMON_ZH
)
from .executors.mysql.mysql_reader import execute_mysql, get_mysql_tables_schema, get_mysql_tables_relationship, get_mysql_tables_sampledata
from .executors.postgres.postgres_reader import execute_postgres, get_postgres_tables_schema, get_postgres_tables_relationship, get_postgres_tables_sampledata
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

SUPPORTED_DATABASE_TYPES = ["mysql", "postgres"]

SQL_PROCESS_MODE = os.getenv('SQL_PROCESS_MODE', "dictionary")

# System Instructions to Agent
INSTRUCTIONS = """
You are an intelligent expert who answers user questions based on relevant knowledge.

"""

NEXT_STEP_PROMPT_EN = """
Based on the user's question and the provided background knowledge, please follow the following rules to respond:


**current time**
{current_time}


**Response Rules:**
1. If the background knowledge can fully address the user's question, return `terminate` in the conclusion field and **write the actual answer content** (facts, data, events) extracted from the background knowledge in the `answer` field. Do not only state that "the background knowledge provides/answers..."; instead, directly state the facts (e.g. "According to the material, the product sold 1 million units last year, mainly in Asia and Europe.").
2. If the background knowledge is irrelevant or insufficient, do not answer the question directly. Based on the original question, preserve the original meaning and regenerate a clearer and more understandable new question, placing it in the `requery` field. You only need to regenerate the question.
3. When generating questions, do not ask users to supplement materials.
4. When generating questions, check the historical query list and avoid generating duplicate questions.
5. In the `answer` field, explain the reason for not being able to answer directly and prompt for more relevant information.
6. If the background knowledge contains source code snippets (extra context from other agents), you must carefully analyze the business logic in the code (e.g., data processing workflows, field mappings, enum value definitions, state transition rules, etc.) and use these business rules to answer the question more accurately. The business rules in code are critical for understanding data semantics.

**Output Format Requirements:**
- Must return a standard JSON format string
- Ensure the output can be directly parsed by `json.loads()`
- Include three required fields: `answer`, `conclusion`, `requery`

**requery Examples**

1. Example 1
Original question: What is Java?
New question: What is the definition of Java?

2. Example 2
Original question: What is Java?
New question: What is the Java programming language?

3. Example 3
Original question: What is Java?
New question: What are the main uses of Java?


**Historical query list as follows:**
{history_querys}

**Example Reference:**

Output example when a complete answer can be provided:
{terminate_fewshots}

Output example when more information is needed:
{continue_fewshots}

**Relevant information:**
{memory}

**Current Background Knowledge:**
{knowledge}

**Note:** Strictly adhere to the JSON format for output. Do not include any additional explanations or text.

"""

NEXT_STEP_PROMPT_ZH = """
根据用户的问题和提供的背景知识，请遵循以下规则进行响应：


**当前时间**
{current_time}


**回答规则：**
1. 若背景知识能够充分解答用户问题，请在结论字段返回 `terminate`，并在 `answer` 字段中**直接写出从背景知识中提取的具体答案内容**（事实、数据、事件等），不要只写“背景知识提供了…能够解答”之类的说明。例如：应写“根据资料，该产品在去年销量达100万台，主要市场在亚洲和欧洲”，而不要写“当前背景知识提供了该产品的市场情况，能够充分解答用户的问题”。
2. 若背景知识与用户问题无关或信息不足，请不要直接回答问题，请根据原始的问题，保留原问题的语意，重新生成一个更清晰易懂的相似的新问题，放入 `requery` 字段, 你要重新生成问题就行。
3. 在生成问题的时候, 不要让用户补充材料。
4. 在生成问题的时候, 要仔细检查历史的query列表，不要生成和历史query重复或者相同的问题，生成出来5个相似的问题，然后从中选择一个和之前的历史query不同的问题，作为下次提问的问题。
5. 在 `answer` 字段中说明无法直接回答的原因，并提示需要更相关的信息。
6. 如果背景知识中包含源代码片段（来自其他智能体的额外上下文），你必须仔细分析代码中的业务逻辑（如数据处理流程、字段映射关系、枚举值定义、状态转换规则等），并结合这些业务逻辑来更准确地回答问题。代码中的业务规则是理解数据含义的重要依据。

**输出格式要求：**
- 必须返回标准的 JSON 格式字符串
- 确保输出可直接被 `json.loads()` 解析
- 包含三个必要字段：`answer`, `conclusion`, `requery`

**requery的示例**

原来的提问: python是什么?

新的相似的问题:

1. Python语言的基本概念和主要应用领域是什么？
2. 请介绍Python编程语言的特点和典型使用场景
3. Python是什么类型的语言？它主要用于哪些方面？
4. 能详细说明Python的定义和它的主要功能用途吗？
5. Python编程语言的核心特征和常见应用有哪些？
6. 解释Python的定位以及它在实际项目中的主要作用
7. Python语言的基本介绍和其主要应用范围
8. 什么是Python？它在软件开发中的主要用途是什么？
9. 请描述Python语言的性质和它最常被使用的领域
10. Python编程语言的基本概况和典型应用场景有哪些？


**原始的问题**

{original_query}

**历史的query列表:**

{history_querys}

**示例参考：**

可完整回答时的输出示例：
{terminate_fewshots}

需要更多信息时的输出示例：
{continue_fewshots}

**相关信息**
{memory}

**当前背景知识：**
{knowledge}

**注意：** 请严格遵循JSON格式输出，不要包含任何额外的解释或文本。

"""

# Initialize Langfuse client
langfuse = get_client()

langfuse_auth_check = os.getenv('LANGFUSE_AUTH_CHECK',"disable")
if langfuse_auth_check == "enable":
    # Verify connection
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Authentication failed. Please check your credentials and host.")

# Initialize Langfuse CallbackHandler for Langchain (tracing)
langfuse_handler = CallbackHandler()

class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        'arbitrary_types_allowed': True,
        'extra': 'allow',
    }

    agent_name: str = Field(
        description='The name of the agent.',
    )

    description: str = Field(
        description="A brief description of the agent's purpose.",
    )

    content_types: list[str] = Field(description='Supported content types.')

class TaskAnalyze(BaseModel):

    task: Optional[str] = Field(
        description='The name of  current task description.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class LLMResult(BaseModel):

    answer: Optional[str] = Field(
        description='The answer of llm for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

    requery: Optional[str] = Field(
        description='The regenerated new user query.'
    )

class RequeryResult(BaseModel):

    requery: Optional[str] = Field(
        description='The new query for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class ObserveResult(BaseModel):

    reason: Optional[str] = Field(
        description='The reason for answer.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class TaskStatus(BaseModel):

    id: int = Field(description='Sequential ID for the task.')

    description: str = Field(
        description='description of subtask'
    )

    agent: str = Field(
        description='agent name of the task to be executed.'
    )

    answer: str = Field(
        description='answer of the task.'
    )

    status: str = Field(
        description='the status of the task to be executed.'
    )

class TaskStatusList(BaseModel):
    """Represents a list of tasks."""
    
    tasks: List[TaskStatus] = Field(description='List of tasks')

class StepStatus(BaseModel):

    id: int = Field(description='Sequential ID for the steps.')

    query: str = Field(
        description='description of subtask'
    )

    answer: str = Field(
        description='answer of the step.'
    )

class StepStatusList(BaseModel):
    """Represents a list of steps."""
    
    steps: List[StepStatus] = Field(description='List of steps')

class DimensionItem(BaseModel):
    name: str = Field(description="Dimension name")
    column: str = Field(description="Column name")
    table: str = Field(description="Table name")
    sql: str = Field(description="SQL query statement")

class Dimensions(BaseModel):
    """SQL Dimensions"""
    
    dimensions: Optional[List[DimensionItem]] = Field(
        default=None,
        description='LLM response to user question, containing dimension list'
    )
    
    reason: Optional[str] = Field(
        default=None,
        description='Regenerated new user query'
    )

# ============================================================================
# 两阶段 LLM 知识检索 —— DB (structured) 专用 Prompt
#
# 替代原有的向量/混合搜索，改为与 code-agent / doc-agent 一致的 LLM 索引匹配：
#   Stage 1: 将所有知识块摘要（表结构、字段、模块描述）发给 LLM，
#            LLM 根据用户问题选出相关的 knowledge_id
#   Stage 2: 按选中的 ID 取完整内容（CREATE TABLE、业务描述等），
#            传给后续 SQL 生成流程
#
# 此 Prompt 专为结构化数据库场景设计，强调：
#   - 表结构相关性（字段是否能满足查询条件）
#   - 关联表识别（多表 JOIN 需要同时选中所有参与表）
#   - 宁多勿少（多给几张表不影响 SQL 生成，少给会导致缺失）
# ============================================================================
LOCATE_DB_KNOWLEDGE_PROMPT_ZH = """

# Role
你是一位精通数据库架构和业务数据建模的专家。你能根据用户问题的真实意图，从数据库知识摘要（表结构、模块分组、业务描述）中精准定位与问题相关的知识记录。

**当前时间**
{current_time}

# Task
基于提供的【知识摘要列表】，深入理解每条记录描述的数据库表结构、字段含义、表间关系和业务模块。根据用户的【查询问题】，判断哪些知识记录包含回答问题所需的表结构信息（用于生成 SQL 或理解数据模型），返回这些记录的 Knowledge ID。

# 检索推理法则
在选择相关知识时，请遵循以下逻辑：
1. **意图理解**：理解用户问题的真实意图——用户可能需要查询特定数据、统计汇总、关联分析等，要判断需要哪些表参与。
2. **表结构相关性**：摘要中描述的表是否包含与问题相关的字段、业务实体或关联关系？
3. **关联表识别**：如果问题涉及多表关联（如订单和用户），需要同时选择所有参与关联的表的知识块。
4. **宁多勿少**：如果不确定某个表结构是否会被 SQL 查询用到，倾向于将其包含进来，确保后续 SQL 生成有足够的表结构信息。
5. **排除无关**：明显与问题无关的表（如完全不同的业务模块）应排除。

# Constraints
- **禁止猜测**：只基于摘要内容进行判断，不要假设摘要未提及的内容。
- **输出要求**：仅返回标准 JSON，严禁任何 markdown 代码块标识符或多余文字。

# Output Format (JSON)
{{
  "knowledge_ids": ["Knowledge ID 1", "Knowledge ID 2", "Knowledge ID 3"],
  "intent_analysis": "对用户真实意图的理解，以及需要哪些表来满足查询。",
  "reasoning": "选择这些知识记录的原因，说明各表在回答问题中的作用。"
}}

---
# Context: 知识摘要列表
{knowledge}

---
# User Query: 用户问题

"""

class KnowledgeSelectionResult(BaseModel):
    """LLM 从摘要中筛选出的相关知识 ID 列表"""

    knowledge_ids: List[str] = Field(
        default_factory=list,
        description="与用户问题相关的知识记录 ID 列表"
    )

    intent_analysis: Optional[str] = Field(
        default=None,
        description="对用户真实意图的理解"
    )

    reasoning: Optional[str] = Field(
        default=None,
        description="选择这些知识记录的原因"
    )


class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class ExpertAgent(BaseAgent):
    """Expert Agent"""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_descriptors:list = None,
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None

    ):
        logger.info('Initializing ExpertAgent')
        super().__init__(
            agent_name='ExpertAgent',
            description='answer user question using yourself knowledge.',
            content_types=['text', 'text/plain'],
        )

        self.manager = ModelManager()
        _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        self.query=query
        self.original_query=query
        self.data_descriptors = data_descriptors
        self.dd_namespace = dd_namespace
        self.descriptor_types = descriptor_types
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=True,
        )
        self.current_step = 0
        self.state: AgentState = AgentState.IDLE
        self.duplicate_threshold: int = 2
        self.next_step_prompt = NEXT_STEP_PROMPT_ZH
        self.memory = Memory()
        self.old_querys = []
        self.metadata = metadata
        self.max_steps=max_steps
        self.current_tasks_status = current_tasks_status
        self.current_task_id = current_task_id
        self.step_status_list: List[StepStatus] = []

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR
            raise e
        finally:
            self.state = previous_state

    async def stream(self, knowledge) -> AsyncIterable[dict[str, Any]]:
        enhanced_query = f"user question: {self.query}\n\n Background knowledge: {knowledge} \n\n{NEXT_STEP_PROMPT_ZH}"

        messages = [
        SystemMessage(content=INSTRUCTIONS),
        HumanMessage(content=enhanced_query)
        ]

        async for chunk in self.llm.astream(messages):
            if hasattr(chunk, 'content') and chunk.content:
                yield {'content': chunk.content, 'is_task_complete': False}
        yield {'content': '', 'is_task_complete': True}

    def format_llm_ouput(self, answer) -> dict:
        data_dict = None
    
        try:
            data_dict = json.loads(answer.content)
        except json.JSONDecodeError as e:

            cleaned_content = answer.content.strip()

            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]
            elif cleaned_content.startswith('```'):
                cleaned_content = cleaned_content[3:]
            
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]
            
            cleaned_content = cleaned_content.strip()
            
            try:
                data_dict = json.loads(cleaned_content)
            except json.JSONDecodeError as e2:
                logger.error(f" === format_llm_ouput, Parsing failed after cleanup.: {e2}")
                try:
                    import ast
                    data_dict = ast.literal_eval(cleaned_content)
                except (ValueError, SyntaxError) as e3:
                    logger.error(f" === format_llm_ouput, ast parsing fail: {e3}")
                    try:
                        cleaned_content = cleaned_content.replace("'", '"')
                        data_dict = json.loads(cleaned_content)
                    except json.JSONDecodeError as e4:
                        logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")
                except Exception as e5:
                    logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        return data_dict

    async def invoke_structured_with_table_selector(self, knowledge, db_type) -> (str, str, str):
        system_template = TABLE_SELECTOR_NEXT_STEP_PROMPT_ZH

        human_template = "question：{query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-tableselector",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_with_table_selector, llm answer = {answer}")

        tables = self.format_llm_ouput(answer)

        logger.info(f" === ExpertAgent.invoke_structured_with_table_selector , invoke_structured_with_table_selector, tables = {tables}")

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        source_metadata = self.analyze_descriptor_source_metadata()
        db_connect_config = source_metadata[ddname]

        sql_schema = ""
        sql_relationship = ""
        sql_sample_data = ""

        if db_type == "mysql":
            sql_schema = await get_mysql_tables_schema(db_connect_config, tables)
            sql_relationship = await get_mysql_tables_relationship(db_connect_config, tables)
            sql_sample_data = await get_mysql_tables_sampledata(db_connect_config, tables)

        if db_type == "postgres":
            sql_schema = await get_postgres_tables_schema(db_connect_config, tables)
            sql_relationship = await get_postgres_tables_relationship(db_connect_config, tables)
            sql_sample_data = await get_postgres_tables_sampledata(db_connect_config, tables)

        logger.debug(f"ExpertAgent.invoke_structured_with_table_selector, sql_schema={sql_schema}")

        return sql_schema, sql_relationship, sql_sample_data

    async def execute_db_query(self, db_connect_config: dict, dbtype: str, sql: str) -> List[Dict[str, Any]]:
        try:
            if not db_connect_config:
                raise ValueError("Database connection configuration cannot be empty.")
            
            if not sql or not sql.strip():
                raise ValueError("SQL statement cannot be empty.")
            
            if not dbtype:
                raise ValueError("Database type cannot be empty.")
            
            dbtype_lower = dbtype.lower()
            
            if dbtype_lower == 'mysql':
                return await execute_mysql(db_connect_config, sql)
            elif dbtype_lower == 'postgres':
                return await execute_postgres(db_connect_config, sql)
            else:
                raise ValueError(f"Unsupported database type: {dbtype}")
                
        except ValueError as ve:
            raise ve
            
        except ConnectionError as ce:
            logging.error(f"Database connection failed.: {str(ce)}")
            raise ConnectionError(f"Unable to connect to the database.: {str(ce)}")
            
        except Exception as e:
            logging.error(f"An error occurred while executing the database query: {str(e)}")
            raise Exception(f"Query execution failed.: {str(e)}")

    async def process_dimensions(self, db_connect_config, dbtype: str = 'mysql', dimensions: Dimensions = None) -> str:

        if not dimensions or not dimensions.dimensions:
            return "No dimension configuration available"
        
        supported_dbtypes = ['mysql', 'postgres']
        if dbtype.lower() not in supported_dbtypes:
            return f"Unsupported database type: {dbtype}"
        
        results = []
        
        for dimension in dimensions.dimensions:
            try:
                query_results = await self.execute_db_query(db_connect_config, dbtype, dimension.sql)
                
                values = set()
                for row in query_results:
                    for value in row.values():
                        if value is not None and str(value).strip():
                            if isinstance(value, bool):
                                display_value = '是' if value else '否'
                            else:
                                display_value = str(value).strip()
                            values.add(display_value)
                
                sorted_values = sorted(list(values))
                
                if sorted_values:
                    result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）包括：{', '.join(sorted_values)}"
                    results.append(result_line)
                else:
                    result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）：无数据"
                    results.append(result_line)
                    
            except Exception as e:
                result_line = f"{dimension.name}（数据库字段：{dimension.column}，表：{dimension.table}）查询失败：{str(e)}"
                results.append(result_line)
        
        return "\n\n".join(results)

    async def invoke_structured_with_dimension_selector(self, knowledge, db_type) -> (str, str):

        system_template = ""

        if db_type == "mysql":
            system_template = DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = DIMENSION_SELECTOR_NEXT_STEP_PROMPT_ZH

        human_template = "question：{query}"

        dimension_selector_json_prompt_instructions_zh = {
          "dimensions": [
            {
              "name": "性别",
              "column": "gender",
              "table": "user", 
              "sql": "SELECT DISTINCT gender FROM user"
            },
            {
              "name": "产品分类",
              "column": "category",
              "table": "product",
              "sql": "SELECT DISTINCT category FROM product"
            },
            {
              "name": "城市", 
              "column": "city",
              "table": "customer",
              "sql": "SELECT DISTINCT city FROM customer"
            }
          ],
          "reason": ""
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
            partial_variables={"dimension_selector": dimension_selector_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-dimensionselector",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_with_dimension_selector, llm answer = {answer}")

        dimensions = self.format_llm_ouput(answer)

        dimensions_llm_parsed = Dimensions(**dimensions)

        logger.info(f"-------------------- ExpertAgent.invoke_structured_with_dimension_selector , invoke_structured_with_dimension_selector, dimensions = {dimensions_llm_parsed}")

        dimensions_result = ""

        if dimensions_llm_parsed.dimensions:
            ddname, agent_type, db_type = self.analyze_descriptor_types()

            source_metadata = self.analyze_descriptor_source_metadata()
            db_connect_config = source_metadata[ddname]

            dimensions_result = await self.process_dimensions(db_connect_config, db_type, dimensions_llm_parsed)
            logger.info(f"ExpertAgent.invoke_structured_with_dimension_selector, dimensions_result={dimensions_result}")
        else:
            logger.debug(f"ExpertAgent.invoke_structured_with_dimension_selector, reason={dimensions_llm_parsed.reason}")

        return dimensions_result, dimensions_llm_parsed.reason

    
    def _get_agent_domain_description(self) -> str:
        """Return a domain description based on the agent's descriptor_type."""
        ddname, agent_type, db_type = self.analyze_descriptor_types()
        if agent_type == "structured":
            return (
                f"你是数据库领域的专家（{db_type or 'SQL'}）。"
                f"你的专业知识范围仅限于：数据库表结构、字段含义、数据关系、数据查询和SQL相关的问题。"
                f"对于API接口、源代码实现、文档内容等超出数据库领域的问题，你不应该回答。"
            )
        elif agent_type == "code":
            return (
                "你是源代码分析领域的专家。"
                "你的专业知识范围仅限于：源代码的业务逻辑、函数实现、调用关系、代码结构等。"
                "对于数据库查询、API文档描述等超出源代码分析领域的问题，你不应该回答。"
            )
        elif agent_type == "unstructured":
            return (
                "你是文档分析领域的专家。"
                "你的专业知识范围仅限于：API文档、设计文档、技术手册等非结构化文档中的信息。"
                "对于数据库查询、源代码实现等超出文档领域的问题，你不应该回答。"
            )
        return "你是一个通用的智能专家。请基于提供的背景知识来回答问题。"

    async def invoke_common(self, knowledge: str = "") -> LLMResult:

        current_task = self.metadata.get('current_task', '')

        system_template = COMMON_NEXT_STEP_PROMPT_ZH
        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？"
        }

        agent_domain = self._get_agent_domain_description()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_task","current_time","knowledge","agent_domain"],
            partial_variables={"current_tasks_status":self.current_tasks_status.tasks, "terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_task": self.query, "current_time":current_time, "knowledge": knowledge, "agent_domain": agent_domain},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_common, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_common , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result


    async def invoke_structured_task_analyze(self) -> TaskAnalyze:

        logger.debug(f"##################### ExpertAgent.invoke_structured_task_analyze, current_tasks_status = {self.current_tasks_status}")

        current_task = self.metadata.get('current_task', '')

        system_template = TASK_ANALYZE_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "task": "从数据库中获取每个商品分类及其对应的商品价格数据",
            "conclusion": "sql",
        }

        continue_json_prompt_instructions_zh: dict = {
            "task": "整理并输出各分类的平均商品价格结果",
            "conclusion": "nosql",
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_task","current_time"],
            partial_variables={"current_tasks_status":self.current_tasks_status.tasks, "terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-task_analyze",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_task": self.query, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_task_analyze, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "task": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = TaskAnalyze(**data_dict)

        logger.info(f"##################### ExpertAgent.invoke_structured_task_analyze, current task = {current_task}, query:{self.query}, action:{llm_result.conclusion}")

        return llm_result


    async def invoke_structured_dictionary_mode(self, knowledge, db_type) -> (LLMResult, str, str):

        memory = self.metadata.get('memory', '')

        logger.debug(f" === ExpertAgent.invoke_structured_dictionary_mode, memory = {memory}")

        sql_schema, sql_relationship, sql_sample_data = await self.invoke_structured_with_table_selector(knowledge, db_type)

        tables_knowledge = f"\n\nTables Schema:\n {sql_schema}\n\nTables Relationshp:\n{sql_relationship}\n\nSample SQL Data:\n{sql_sample_data}\n\n"

        dimensions, dimensions_reason = await self.invoke_structured_with_dimension_selector(tables_knowledge, db_type)

        system_template = ""

        if db_type == "mysql":
            system_template = MYSQL_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = POSTGRES_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","original_query","history_querys","memory", "dimensions","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-sql_dict",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": tables_knowledge,"original_query": self.original_query,"history_querys": history_querys,"memory": memory, "dimensions":dimensions, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_structured_dictionary_mode, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_structured_dictionary_mode , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result, dimensions, dimensions_reason

    async def invoke_structured(self, knowledge, db_type) -> LLMResult:

        memory = self.metadata.get('memory', '')

        logger.info(f" === ExpertAgent.invoke_structured, memory = {memory}")

        tables_knowledge = knowledge

        system_template = ""

        if db_type == "mysql":
            system_template = MYSQL_NEXT_STEP_PROMPT_ZH

        if db_type == "postgres":
            system_template = POSTGRES_NEXT_STEP_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "基于背景知识，Java是一种高级、面向对象、跨平台的编程语言...",
            "conclusion": "terminate",
            "requery": ""
        }

        continue_json_prompt_instructions_zh: dict = {
            "answer": "当前背景知识主要涵盖Java和Go语言，无法提供Python相关的详细信息",
            "conclusion": "continue",
            "requery": "能否提供Python编程语言的具体介绍和特点？"
        }


        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","original_query","history_querys","memory","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-sql_nodict",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": tables_knowledge,"original_query": self.original_query,"history_querys": history_querys,"memory": memory, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_structured, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_structured , llm_result = {llm_result}")

        # add last step query into old_querys, next loop will use these old querys to regenerate query to avoid generate the same query.
        self.old_querys.append(self.query)

        return llm_result


    async def invoke_requery(self) -> RequeryResult:

        step_history = self.get_step_history_for_requery()

        system_template = REQUERY_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "requery": "新生成的问题...",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "requery": "",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["original_query","history_querys","current_time","step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-requery",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "original_query": self.original_query,"history_querys": history_querys, "current_time":current_time, "step_history":step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_requery, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery , llm_result = {llm_result}")

        return llm_result

    async def invoke_requery_sql(self, sql, information, knowledge) -> RequeryResult:

        step_history = self.get_step_history_for_requery()

        system_template = REQUERY_SQL_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "requery": "新生成的问题...",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "requery": "",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["sql","information","knowledge","original_query","history_querys","current_time","step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-requery_sql",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "sql":sql, "information":information, "knowledge":knowledge, "original_query": self.original_query,"history_querys": history_querys, "current_time":current_time, "step_history":step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_requery_sql, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery_sql , llm_result = {llm_result}")

        return llm_result

    async def observe_sql(self, query, sql, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_SQL_ZH

        human_template = "question: {query}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "满足问题的原因",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "不满足问题的原因",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time", "sql", "answer"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        llm_answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-observe_sql",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time, "sql":sql},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.observe_sql, answer = {llm_answer}")

        data_dict = self.format_llm_ouput(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_sql , llm_result = {llm_result}")

        return llm_result


    async def observe_common(self, query, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_COMMON_ZH

        human_template = "question: {query};\n\nanswer:{answer}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "满足问题的原因",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "不满足问题的原因",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        llm_answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="expert-observe_common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.observe_common, answer = {llm_answer}")

        data_dict = self.format_llm_ouput(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_common , llm_result = {llm_result}")

        return llm_result

    def generate_collection_name(self, dd_name: str) -> str:
        """
        Format: namespace_name
        Rule: Replace '-' with '_'
        Returns:
        str: The generated collection_name
        """

        collection_name = f"{self.dd_namespace}_{dd_name}"

        # Replace '-' in namespace with '_'
        collection_name = collection_name.replace('-', '_')
        
        return collection_name

    async def get_all_knowledge_blocks(self) -> Optional[MetadataValuesResult]:
        """
        从 dataservices 获取所有知识块数据（包含 id, text, metadata_value）。
        用于两阶段知识检索的第一阶段数据源。
        """
        logger.info(f"=========get_all_knowledge_blocks, data_descriptors: {self.data_descriptors}")
        try:
            collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]
            logger.info(f"get_all_knowledge_blocks collection_names: {collection_names}")

            await self.data_services_client._create_session()
            result = await self.data_services_client.find_metadata_values_in_collections(
                collection_names=collection_names
            )

            if result.status != "success":
                logger.error(f"find_metadata_values_in_collections failed: {result.errors}")
                return None

            logger.info(f"get_all_knowledge_blocks success, items count: {len(result.get_all_items())}")
            return result

        except Exception as e:
            logger.error(f'An error occurred during get_all_knowledge_blocks: {e}')
            return None
        finally:
            await self.data_services_client.close()

    async def select_relevant_knowledge(self, knowledge_summaries: str) -> KnowledgeSelectionResult:
        """Stage 1 核心: 使用 LLM 从知识摘要中筛选与用户问题相关的 knowledge_id。

        将一个批次的摘要文本 + 用户问题发给 LLM (LOCATE_DB_KNOWLEDGE_PROMPT_ZH)，
        LLM 返回 JSON: { knowledge_ids: [...], intent_analysis, reasoning }。
        当知识块较多时，会被 get_knowledge() 拆成多个批次并行调用本方法。
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_template = LOCATE_DB_KNOWLEDGE_PROMPT_ZH
        human_template = "{query}"

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge", "current_time"],
        )
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        chain = chat_prompt | self.llm

        with langfuse.start_as_current_span(
            name="expert-select-db-knowledge",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge_summaries, "current_time": current_time},
                config={"callbacks": [langfuse_handler]}
            )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.select_relevant_knowledge, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            logger.error("select_relevant_knowledge: LLM output parsing failed, returning empty result")
            return KnowledgeSelectionResult(knowledge_ids=[], intent_analysis="", reasoning="parsing failed")

        return KnowledgeSelectionResult(**data_dict)

    async def get_knowledge(self) -> str:
        """
        两阶段知识检索：
        第一阶段（粗筛）：获取所有知识块的摘要（metadata_value），LLM 根据用户问题筛选出相关的 knowledge_ids
        第二阶段（精取）：根据筛选出的 knowledge_ids，获取对应的完整知识内容（text 字段）
        """
        logger.info(f"=========get_knowledge (two-stage), query: {self.query}, data_descriptors: {self.data_descriptors}")

        knowledge_str = ""

        try:
            # ── Stage 1: 粗筛 ──────────────────────────────────────────
            # 从 data-services 获取所有知识块（含 摘要 + 全文）
            knowledge_blocks = await self.get_all_knowledge_blocks()

            if knowledge_blocks is None or not knowledge_blocks.get_all_items():
                logger.warning("get_knowledge: No knowledge blocks found, falling back to empty knowledge")
            else:
                # 按 60000 字符上限分批（≈15K tokens），防止超出 LLM 上下文窗口
                metadata_batches = knowledge_blocks.extract_metadata_as_batches(max_chars_per_batch=60000)
                logger.info(f"get_knowledge: {len(knowledge_blocks.get_all_items())} knowledge blocks split into {len(metadata_batches)} batches")

                all_selected_ids = []

                async def _process_batch(batch_idx, batch):
                    logger.info(f"get_knowledge: Processing batch {batch_idx + 1}/{len(metadata_batches)}, chars: {len(batch)}")
                    selection_result = await self.select_relevant_knowledge(batch)
                    if selection_result.knowledge_ids:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected {len(selection_result.knowledge_ids)} knowledge IDs: {selection_result.knowledge_ids}")
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} intent: {selection_result.intent_analysis}")
                    else:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected 0 knowledge IDs")
                    return selection_result

                # 多批次并行发给 LLM 筛选，减少总延迟
                batch_results = await asyncio.gather(
                    *[_process_batch(idx, batch) for idx, batch in enumerate(metadata_batches)],
                    return_exceptions=True
                )

                # 收集所有批次选中的 knowledge_id
                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"get_knowledge: Batch {idx + 1} failed with error: {result}")
                        continue
                    if result.knowledge_ids:
                        all_selected_ids.extend(result.knowledge_ids)

                # 去重（保留首次出现顺序）
                seen = set()
                unique_ids = [kid for kid in all_selected_ids if not (kid in seen or seen.add(kid))]
                logger.info(f"get_knowledge: Total unique selected knowledge IDs: {len(unique_ids)}")

                # ── Stage 2: 精取 ──────────────────────────────────────
                # 按选中的 ID 从同一个 MetadataValuesResult 中提取 text 全文，无需额外网络请求
                if unique_ids:
                    knowledge_str = knowledge_blocks.get_text_by_ids(unique_ids)
                    logger.info(f"get_knowledge: Retrieved full knowledge content, length: {len(knowledge_str)}")

        except Exception as e:
            logger.error(f'An error occurred during two-stage knowledge retrieval: {e}')
            raise

        # 合并来自 semantic group 其他 agent 的额外上下文（如代码分析结果、文档片段）
        extra_context = (self.metadata or {}).get('extra_context', '')
        if extra_context:
            logger.info(f"get_knowledge: 发现 extra_context ({len(extra_context)} 字)，合并到 knowledge")
            if knowledge_str:
                knowledge_str = (
                    f"{knowledge_str}\n\n"
                    f"--- 以下是来自其他智能体的额外上下文，可能是相关的业务逻辑的代码，也有可能是相关的文档 ---\n\n"
                    f"{extra_context}"
                )
            else:
                knowledge_str = extra_context

        logger.debug(f"get knowledge: {knowledge_str}")
        logger.info(f"get knowledge: {knowledge_str[:100] if knowledge_str else 'None'}")
        return knowledge_str

    def analyze_descriptor_types(self):
        """
        Parse descriptor_types from JSON format.
        Returns: (ddname, agent_type, db_type)

        Expected input: self.descriptor_types is a list with one element that is a
        JSON array string, e.g. ['[{"name":"dd","descriptorType":"structured-mysql","dbType":"mysql",...}]']
        """
        if not self.descriptor_types or not isinstance(self.descriptor_types, list) or len(self.descriptor_types) == 0:
            logger.error(f"analyze_descriptor_types: invalid descriptor_types={self.descriptor_types}")
            return "", "unknown", ""

        first_item = self.descriptor_types[0].strip()
        try:
            data_list = json.loads(first_item)
            if not isinstance(data_list, list):
                data_list = [data_list]
            if not data_list:
                return "", "unknown", ""

            cfg = data_list[0]
            name = cfg.get("name", "")
            descriptor_type = cfg.get("descriptorType", "unknown")
            db_type = cfg.get("dbType", "")

            match = re.search(r'structured-([a-zA-Z0-9_]+)', descriptor_type)
            if match:
                return name, "structured", match.group(1) if not db_type else db_type

            return name, descriptor_type, db_type
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"analyze_descriptor_types: failed to parse JSON: {e}, raw={first_item[:200]}")
            return "", "unknown", ""

    def analyze_descriptor_source_metadata(self):
        """
        Parse source metadata from JSON config field.
        Returns: {
            'dd1name': {'host': 'mysql-server', 'port': 3306, 'user': 'root', ...},
            'dd2name': {'host': 'postgres-server', 'port': 5432, ...}
        }
        """
        source_metadatas = {}
        if not self.descriptor_types or not isinstance(self.descriptor_types, list) or len(self.descriptor_types) == 0:
            return source_metadatas

        first_item = self.descriptor_types[0].strip()
        try:
            data_list = json.loads(first_item)
            if not isinstance(data_list, list):
                data_list = [data_list]
            for cfg in data_list:
                name = cfg.get("name", "")
                config = cfg.get("config", {})
                if not name or not config:
                    continue
                parsed = {}
                for k, v in config.items():
                    if k == 'port':
                        try:
                            parsed[k] = int(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                    else:
                        parsed[k] = v
                source_metadatas[name] = parsed
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"analyze_descriptor_source_metadata: failed to parse JSON: {e}")
        return source_metadatas

    def custom_json_serializer(self, obj):

        if obj is None:
            return None
        
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        
        elif isinstance(obj, Decimal):
            return float(obj)
        
        elif isinstance(obj, uuid.UUID):
            return str(obj)
        
        elif isinstance(obj, (bytes, bytearray)):
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                return obj.hex()

        elif isinstance(obj, Enum):
            return obj.value

        elif isinstance(obj, Path):
            return str(obj)
        
        elif isinstance(obj, (set, frozenset)):
            return list(obj)
        
        elif hasattr(obj, 'dtype'):
            if hasattr(obj, 'tolist'):
                return obj.tolist()
            elif hasattr(obj, 'item'):
                return obj.item()
        
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    async def step(self) -> str:
        """Execute a single step with streaming support."""

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        if agent_type not in ["structured"]:
            raise ValueError(f"Unsupported descriptor type: {agent_type}. ")
        
        if agent_type == "structured" and db_type not in SUPPORTED_DATABASE_TYPES:
            raise ValueError(f"Unsupported db type: {db_type}. ")

        llm_result = None
        dimensions = ""
        dimensions_reason = ""
        try:
            if agent_type == "structured":
                # Determine whether the current query needs to execute SQL or should be analyzed based on the large model itself.
                task_analyze = await self.invoke_structured_task_analyze()
                if task_analyze.conclusion == "sql":
                    knowledge = await self.get_knowledge()
                    if SQL_PROCESS_MODE == "dictionary":
                        llm_result, dimensions, dimensions_reason = await self.invoke_structured_dictionary_mode(knowledge, db_type)
                    else:
                        llm_result = await self.invoke_structured(knowledge, db_type)

                    if llm_result:
                        # if llm result to say terminate, this agent will end
                        if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                            self.state = AgentState.FINISHED
                            source_metadata = self.analyze_descriptor_source_metadata()
                            db_connect_config = source_metadata[ddname]
                            sql_result :List[Dict[str, Any]] = []
                            # Execute the SQL statement generated by the large model.
                            try:
                                sql_result = await self.execute_db_query(db_connect_config, db_type, llm_result.answer)
                                logger.info(f"sql execute sql: {llm_result.answer}")
                            except Exception as e:
                                # if sql error, will requery and enter next loop
                                logger.error(f"execute_db_query error : {e}")
                                llm_result.conclusion = "continue"
                                requery = await self.invoke_requery_sql(llm_result.answer, f"sql error: {e}", knowledge)
                                if requery.conclusion == "terminate" and requery.requery:
                                    llm_result.requery = requery.requery
                                    self.state = AgentState.IDLE
                                    llm_result.answer = f"sql error:{e}, sql: {llm_result.answer}"

                            if sql_result:
                                # Case: The large model successfully generated SQL, and data was retrieved.
                                # observe llm result meet question.
                                sql_result_str = json.dumps(sql_result, indent=2, ensure_ascii=False, default=self.custom_json_serializer)
                                logger.debug(f"sql execute sql_result_str: {sql_result_str}")
                                observe_result = await self.observe_sql(self.query, llm_result.answer, sql_result_str, knowledge)
                                if observe_result.conclusion == "terminate":
                                    # Case: The large model successfully generated SQL, data was retrieved, and it is evaluated that the question has been successfully answered. This indicates that the current step has completed its own task and will return directly.
                                    self.state = AgentState.FINISHED
                                    step_status_llm_check_success = "The current answer addresses the question very well."
                                    observe_message = f"\nsql: {llm_result.answer}, \n\nsql query result: {sql_result_str}, \n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"
                                    llm_result.answer = observe_message
                                else:
                                    # Case: The large model successfully generated SQL and data was retrieved, but the evaluation indicates that the data does not match the question, meaning the generated SQL is incorrect. In this case, the question needs to be rephrased to proceed to the next step for generating new SQL.
                                    llm_result.conclusion = "continue"
                                    requery = await self.invoke_requery_sql(llm_result.answer, "searched records do not meet query", knowledge)
                                    if requery.conclusion == "terminate" and requery.requery:
                                        llm_result.requery = requery.requery
                                        self.state = AgentState.IDLE
                                        llm_result.answer = f"searched records do not meet query, sql: {llm_result.answer}, \n\nsql query result: {sql_result_str}, \n\nreason: {observe_result.reason}"
                            else:
                                # Case: The large model successfully generated SQL, but no data was retrieved. It is necessary to review whether the result is genuinely empty. If it is determined that the SQL is problematic, the question should be rephrased to proceed to the next step for generating new SQL.
                                # if sql no result, will requery and enter next loop
                                sql_result_str = "not found records"
                                observe_result = await self.observe_sql(self.query, llm_result.answer, sql_result_str, knowledge)
                                if observe_result.conclusion == "terminate":
                                    # Case: The large model successfully generated SQL, but no data was retrieved. The evaluation confirms that the SQL is correct, yet there is simply no data. This situation also indicates that the current step has completed its task and will return directly.
                                    self.state = AgentState.FINISHED
                                    step_status_llm_check_success = "The current answer addresses the question very well."
                                    observe_message = f"\nsql: {llm_result.answer} \n\nsql query result: {sql_result_str}\n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"
                                    llm_result.answer = observe_message
                                else:
                                    # Case: The large model successfully generated SQL, but no data was retrieved. The evaluation indicates a mismatch between the data and the question, meaning the generated SQL is incorrect. In this case, the question needs to be rephrased to proceed to the next step for generating new SQL.
                                    llm_result.conclusion = "continue"
                                    requery = await self.invoke_requery_sql(llm_result.answer, "not found records", knowledge)
                                    if requery.conclusion == "terminate" and requery.requery:
                                        llm_result.requery = requery.requery
                                        self.state = AgentState.IDLE
                                        llm_result.answer = f"not found records, sql: {llm_result.answer}, \n reason: {observe_result.reason}"

                else:
                    # If analysis determines the query does not require SQL execution, use the large model for general question answering. If the LLM returns "continue", it indicates the question is unrelated to the context and cannot be answered. No further processing is done here, as the "continue" response will be handled by subsequent logic, proceeding to the next step loop.  
                    # If the LLM can process the query normally (returning "terminate"), but evaluation reveals the question hasn't been fully resolved, the question should be regenerated to enter the next step loop.
                    knowledge = await self.get_knowledge()
                    llm_result = await self.invoke_common(knowledge)
                    if llm_result:
                        if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                            current_tasks_status_str =  self.format_tasks_status(self.current_tasks_status.tasks)
                            observe_result = await self.observe_common(self.query, llm_result.answer, current_tasks_status_str)
                            observe_message = f"\nquery: {self.query} \n\nreason:{observe_result.reason}"
                            if observe_result.conclusion == "continue":
                                llm_result.conclusion = "continue"
                                self.state = AgentState.IDLE
                                requery = await self.invoke_requery()
                                if requery.conclusion == "terminate" and requery.requery:
                                    llm_result.requery = requery.requery
                                llm_result.answer = f"knowledge can do not meet query, \n\nreason: {observe_result.reason}"
                            else:
                                step_status_llm_check_success = "The current answer addresses the question very well."
                                llm_result.answer = f"{llm_result.answer}, \n\nreason:{step_status_llm_check_success} ,{observe_result.reason}"

            else:
                raise ValueError(f"Unknown agent type: {agent_type}")
        except Exception as e:
            # If any issues are encountered during execution, regenerate the question and proceed to the next step loop, including SQL execution errors and re-querying.
            logger.error(f"step error : {e}")
            self.state = AgentState.IDLE
            self.save_step_status(self.query, f"step error : {e}")
            requery = await self.invoke_requery()
            if requery.conclusion == "terminate":
                self.query = requery.requery
                self._update_task_description(requery.requery)
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!", dimensions, dimensions_reason

        # 1. SQL is normally generated and its direct results are judged correct
        # 2. SQL returns no results, trigger re-query
        # 3. NoSQL execution is judged correct
        # 4. NoSQL execution is judged incorrect, trigger re-query
        if llm_result:
            # if llm result to say terminate, this agent will end
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                self.state = AgentState.FINISHED
                self.memory.add_message(Message.assistant_message(llm_result.answer))
                self.save_step_status(self.query, llm_result.answer)

            # if need to re-query, reset query to self.query for next loop
            if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "continue":
                self.save_step_status(self.query, llm_result.answer)
                if hasattr(llm_result, 'requery') and llm_result.requery:
                    self.query = llm_result.requery
                    self._update_task_description(llm_result.requery)

            if not llm_result.answer:
                answer = f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"
                return answer, dimensions, dimensions_reason
            else:
                return llm_result.answer, dimensions, dimensions_reason
        else:
            raise ValueError("step can not handle normal!")

    def save_step_status(self, query:str, answer: str):
        step_status = StepStatus(
            id=self.current_step,
            query=query,
            answer=answer
        )
        self.step_status_list.append(step_status)
        logger.info(f"Saved step {self.current_step} status: query='{query}'")

    def get_step_history_for_requery(self) -> str:
        if not self.step_status_list:
            return "No historical step records"
        
        history_lines = []
        for step in self.step_status_list:
            history_lines.append(f"Step {step.id}:")
            history_lines.append(f"  Query: {step.query}")
            history_lines.append(f"  Answer: {step.answer}")
            history_lines.append("")
        
        return "\n".join(history_lines)

    def format_tasks_status(self, tasks):
        if not tasks:
            return "No tasks available"
        
        lines = []
        for task in tasks:
            lines.append(f"Task {task.id}: {task.description}")
            lines.append(f"  Agent: {task.agent}")
            lines.append(f"  Status: {task.status}")
            lines.append(f"  Answer: {task.answer}\n")
        
        return "\n".join(lines)

    def _update_task_description(self, new_task_description: str):
        if self.current_tasks_status and self.current_tasks_status.tasks and self.current_task_id is not None:
            for task in self.current_tasks_status.tasks:
                if task.id == self.current_task_id:
                    task.description = new_task_description
                    logger.info(f"Updated task {self.current_task_id} description to: {new_task_description}")
                    break

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt_en = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."

        stuck_prompt_zh = "\
        观察到重复的响应。请考虑采用新的策略，避免重复已经尝试过的无效路径。"

        self.next_step_prompt = f"{stuck_prompt_zh}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt_zh}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {**(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    async def run(self) -> AsyncIterable[str]:
        """Run the agent with streaming support."""
        logger.debug(f"************** agent run, query: {self.query}, data_descriptors: {self.data_descriptors} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if self.query:
            self.update_memory("user", self.query)

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1

                current_task = self.metadata.get('current_task', '')

                logger.info(f"******************** {current_task}, current query: {self.query}, Executing step {self.current_step}/{self.max_steps}")

                step_result_str = f"step {self.current_step}/{self.max_steps}: query: {self.query}"

                step_result ,dimensions, dimensions_reason = await self.step()

                steps_status = self.get_step_history_for_requery()

                logger.debug(f"******************** steps status: \n\n {steps_status}")
                
                if not dimensions and not dimensions_reason:
                    step_result = f"{step_result_str}\n\nanswer: {step_result}\n"

                if dimensions and not dimensions_reason:
                    step_result = f"{step_result_str} \n\nconditions:{dimensions} \n\nanswer: {step_result} \n"
                
                if dimensions_reason and not dimensions:
                    step_result = f"{step_result_str} \n\nconditions:{dimensions_reason} \n\nanswer: {step_result} \n"

                if dimensions_reason and dimensions:
                    step_result = f"{step_result_str} \n\nconditions: {dimensions}, {dimensions_reason} \n\nanswer: {step_result} \n"

                yield step_result

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class ExpertAgentExecutorSemanticDomain(AgentExecutor):
    """
    A Expert Agent answer user question.
    """

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_descriptors:list = None,
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        max_steps:int = 5

    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.data_descriptors=data_descriptors
        self.dd_namespace=dd_namespace
        self.descriptor_types=descriptor_types
        self.data_services_url=data_services_url
        self.stream_enabled = stream
        self.max_steps = max_steps

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()
        logger.info(f"=====user query is {query}.")

        metadata = context.metadata
        logger.info(f"=====user request metadata is {metadata}.")

        current_tasks_status = None
        current_tasks_status_str = metadata.get('current_tasks_status', '')
        if current_tasks_status_str:
            current_tasks_status_json = json.loads(current_tasks_status_str)
            current_tasks_status = TaskStatusList(tasks=current_tasks_status_json)
        else:
            current_tasks_status = TaskStatusList(tasks=[])
        
        current_task_id = None
        current_task_id_str = metadata.get('current_task_id')
        if current_task_id_str:
            current_task_id = int(current_task_id_str)

        agent = ExpertAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            dd_namespace=self.dd_namespace,
            descriptor_types=self.descriptor_types,
            data_services_url=self.data_services_url,
            query=query,
            metadata=metadata,
            max_steps=self.max_steps,
            current_tasks_status=current_tasks_status,
            current_task_id=current_task_id
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if self.stream_enabled:
            async for chunk in agent.run():
                if chunk:
                    part = TextPart(text=chunk)
                    await updater.add_artifact(
                        [part],
                        name=f'{agent.agent_name}-result',
                    )
                            
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')