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
from a2a.types import TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .dataservices_client import DataServicesClient
from .schema import ROLE_TYPE, Memory, Message
from .prompts import (  
    NEXT_STEP_PROMPT_ZH,
    REQUERY_PROMPT_ZH,
    OBSERVE_PROMPT_UNSTRUCTURED_ZH,
    LOCATE_KNOWLEDGE_PROMPT_ZH
)

from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)



# System Instructions to Agent
INSTRUCTIONS = """
You are an intelligent expert who answers user questions based on relevant knowledge.

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

class DocAgent(BaseAgent):
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
        descriptor_types_json_string: str = None,
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
        self.descriptor_types_json_string = descriptor_types_json_string
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

    def format_llm_output(self, answer) -> dict:
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
                logger.error(f" === format_llm_output, Parsing failed after cleanup.: {e2}")
                try:
                    import ast
                    data_dict = ast.literal_eval(cleaned_content)
                except (ValueError, SyntaxError) as e3:
                    logger.error(f" === format_llm_output, ast parsing fail: {e3}")
                    try:
                        cleaned_content = cleaned_content.replace("'", '"')
                        data_dict = json.loads(cleaned_content)
                    except json.JSONDecodeError as e4:
                        logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")
                except Exception as e5:
                    logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        return data_dict

    async def invoke_unstructured(self, knowledge) -> LLMResult:

        memory = self.metadata.get('memory', '')

        logger.info(f" === ExpertAgent.invoke_unstructured, memory = {memory}")

        system_template = self.next_step_prompt
        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "answer": "Java是一种高级、面向对象、跨平台的编程语言，由Sun公司推出，具有可移植性、安全性等特点，广泛应用于企业级应用和Android开发。",
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
            name="doc-agent-invoke",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "knowledge": knowledge, "original_query":self.original_query, "history_querys":history_querys, "memory":memory, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === ExpertAgent.invoke_unstructured, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "answer": "System error: Unable to process model response",
                "conclusion": "error",
                "requery": ""
            }

        llm_result = LLMResult(**data_dict)

        logger.info(f" === ExpertAgent.invoke_unstructured , llm_result = {llm_result}")

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
            name="doc-agent-requery",
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

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery , llm_result = {llm_result}")

        return llm_result

    async def observe_unstructured(self, query, answer, knowledge) -> ObserveResult:

        system_template = OBSERVE_PROMPT_UNSTRUCTURED_ZH

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
            name="doc-agent-observe",
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

        logger.info(f" === ExpertAgent.observe_unstructured, answer = {llm_answer}")

        data_dict = self.format_llm_output(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_unstructured , llm_result = {llm_result}")

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

    async def get_all_knowledge_blocks(self):
        """
        从 dataservices 获取所有知识块数据（包含 id, text, metadata_value）。
        用于两阶段知识检索的数据源。
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
        """
        使用 LLM 从知识摘要中筛选与用户问题相关的知识 ID。

        Args:
            knowledge_summaries: 格式化后的知识摘要字符串（包含 [Knowledge ID: xxx] 标记）

        Returns:
            KnowledgeSelectionResult: 包含相关知识 ID 列表
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_template = LOCATE_KNOWLEDGE_PROMPT_ZH
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
            name="doc-agent-select-knowledge",
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

        logger.info(f" === DocAgent.select_relevant_knowledge, answer = {answer}")

        data_dict = self.format_llm_output(answer)

        if data_dict is None:
            logger.error("select_relevant_knowledge: LLM output parsing failed, returning empty result")
            return KnowledgeSelectionResult(knowledge_ids=[], intent_analysis="", reasoning="parsing failed")

        return KnowledgeSelectionResult(**data_dict)

    async def get_knowledge(self) -> str:
        """
        两阶段知识检索：
        第一阶段（粗筛）：获取所有知识块的摘要（metadata_value），LLM 根据用户问题筛选出相关的 knowledge_ids
        第二阶段（精取）：根据筛选出的 knowledge_ids，获取对应的完整知识内容（text 字段），用换行符拼接
        """
        logger.info(f"=========get_knowledge (two-stage), query: {self.query}, data_descriptors: {self.data_descriptors}")

        knowledge_str = ""

        try:
            # 第一阶段：获取所有知识块
            knowledge_blocks = await self.get_all_knowledge_blocks()

            if knowledge_blocks is None or not knowledge_blocks.get_all_items():
                logger.warning("get_knowledge: No knowledge blocks found, falling back to empty knowledge")
            else:
                # 将摘要分批（避免超出 LLM 上下文限制）
                metadata_batches = knowledge_blocks.extract_metadata_as_batches(max_chars_per_batch=60000)
                logger.info(f"get_knowledge: {len(knowledge_blocks.get_all_items())} knowledge blocks split into {len(metadata_batches)} batches")

                all_selected_ids = []

                # 对每个批次让 LLM 筛选相关知识 ID（所有批次并行处理）
                async def _process_batch(batch_idx, batch):
                    logger.info(f"get_knowledge: Processing batch {batch_idx + 1}/{len(metadata_batches)}, chars: {len(batch)}")
                    selection_result = await self.select_relevant_knowledge(batch)
                    if selection_result.knowledge_ids:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected {len(selection_result.knowledge_ids)} knowledge IDs: {selection_result.knowledge_ids}")
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} intent: {selection_result.intent_analysis}")
                    else:
                        logger.info(f"get_knowledge: Batch {batch_idx + 1} selected 0 knowledge IDs")
                    return selection_result

                batch_results = await asyncio.gather(
                    *[_process_batch(idx, batch) for idx, batch in enumerate(metadata_batches)],
                    return_exceptions=True
                )

                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"get_knowledge: Batch {idx + 1} failed with error: {result}")
                        continue
                    if result.knowledge_ids:
                        all_selected_ids.extend(result.knowledge_ids)

                # 去重
                seen = set()
                unique_ids = [kid for kid in all_selected_ids if not (kid in seen or seen.add(kid))]
                logger.info(f"get_knowledge: Total unique selected knowledge IDs: {len(unique_ids)}")

                # 第二阶段：根据 ID 获取完整知识内容，用换行符拼接
                if unique_ids:
                    knowledge_str = knowledge_blocks.get_text_by_ids(unique_ids)
                    logger.info(f"get_knowledge: Retrieved full knowledge content, length: {len(knowledge_str)}")

        except Exception as e:
            logger.error(f'An error occurred during two-stage knowledge retrieval: {e}')
            raise

        # 如果 metadata 中有 extra_context（来自 semantic group 的其他 agent 结果），合并到 knowledge 中
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

    def parse_descriptor_types_json(self, descriptor_types_json_string: str) -> List[Dict[str, Any]]:
        """
        解析 DescriptorTypes 环境变量（JSON 格式）为字典列表
        
        Args:
            descriptor_types_json_string: JSON 格式的配置字符串
        Returns:
            解析后的字典列表
        """
        if not descriptor_types_json_string:
            return []
        
        descriptor_types_json_string = descriptor_types_json_string.strip()
        
        if not descriptor_types_json_string.startswith('['):
            logger.warning(f"DescriptorTypes 不是 JSON 数组格式: {descriptor_types_json_string[:100]}...")
            return []
        
        try:
            return json.loads(descriptor_types_json_string)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {e}, 输入: {descriptor_types_json_string[:100]}...")
            return []

    async def step(self) -> str:
        """Execute a single step with streaming support."""

        configs = self.parse_descriptor_types_json(self.descriptor_types_json_string)

        agent_type = "unstructured"

        llm_result = None

        try:
            # generate final sql for this step
            if agent_type == "unstructured":
                knowledge = await self.get_knowledge()

                # ========== answer_model=original: 直接返回知识内容，跳过 LLM 回答和验证 ==========
                answer_model = self.metadata.get('answer_model', '') if self.metadata else ''
                logger.info(f"[step] 检查 answer_model: '{answer_model}'")
                if answer_model == "original":
                    logger.info(f">>>>>> [answer_model=original] DocAgent.step() 直接返回知识内容，跳过 invoke_unstructured 和 observe <<<<<<")
                    if knowledge and knowledge.strip():
                        self.state = AgentState.FINISHED
                        self.save_step_status(self.query, knowledge)
                        return knowledge
                    else:
                        self.state = AgentState.FINISHED
                        no_knowledge_msg = f"未找到与问题 '{self.query}' 相关的知识"
                        self.save_step_status(self.query, no_knowledge_msg)
                        return no_knowledge_msg

                llm_result = await self.invoke_unstructured(knowledge)
                if llm_result:
                    if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                        current_tasks_status_str =  self.format_tasks_status(self.current_tasks_status.tasks)
                        # observe 判断「answer」是否真正回答问题；第三参为任务状态（非原始 knowledge）
                        observe_result = await self.observe_unstructured(self.query, llm_result.answer, current_tasks_status_str)
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
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"

        # 1. Unstructured processing is correct
        # 2. Unstructured processing triggers re-query
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
                return answer
            else:
                return llm_result.answer
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

                step_result = await self.step()

                steps_status = self.get_step_history_for_requery()

                logger.debug(f"******************** steps status: \n\n {steps_status}")

                yield step_result

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class DocAgentExecutor(AgentExecutor):
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
        descriptor_types_json_string: str = None,
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
        self.descriptor_types_json_string=descriptor_types_json_string
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
        logger.info(f"=====answer_model={metadata.get('answer_model', '(not set)') if metadata else '(no metadata)'}")

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

        agent = DocAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            dd_namespace=self.dd_namespace,
            descriptor_types_json_string=self.descriptor_types_json_string,
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