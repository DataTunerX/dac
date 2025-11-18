import json
import logging
import sys
from pathlib import Path
import click
import httpx
import uvicorn
import os
import asyncio
import re
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Union
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from abc import ABC
from langchain_core.prompts.chat import(
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
    )
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import CallToolRequest, ReadResourceResult
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    MessageSendParams,
    SendStreamingMessageRequest,
    AgentCard,
    AgentSkill,
    TaskState,
    TaskStatus,
    TextPart,
)
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from a2a.client import A2AClient
from .redis_registry import RedisRegistry, HeartbeatService
import atexit
import signal
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from .dataservices_client import DataServicesClient, CreateHistoryRequest, HistoryMessage, SearchHistoryRequest
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .agentregistry_client import AgentRegistryClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

AgentRegistry = os.getenv("AgentRegistry", "expert-registry.dac.svc.cluster.local::10100")

os.environ["DASHSCOPE_API_KEY"] = "sk-xxx"

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_EN = """
# Role: Chief Strategy Planner

## Core Mission
You are a senior planning expert. Your responsibility is not merely to list tasks, but to **design an optimal execution strategy that achieves the final goal in the most efficient and reliable manner possible.**

## Planning Process & Principles
Before formulating a plan, you MUST conduct the following analysis:
1.  **Goal Decomposition via Backward Planning:** Work backward from the end goal to identify the **critical necessary conditions** for its achievement. Every step must be an essential milestone that directly contributes to accomplishing the objective.
2.  **Critical Path Optimization:** Identify the "critical path" within the overall plan (i.e., the sequence of tasks that determines the shortest possible duration or has the strongest dependencies). Prioritize and optimize the steps on this path to ensure overall efficiency.
3.  **Precise Resource Matching:** Assign each step to the most qualified expert, ensuring "the right person handles the right task." Consider task dependencies and potential expert workload to avoid bottlenecks.
4.  **Risk-Frontloading & Validation:** Position steps involving uncertainty or risk (e.g., information gathering, feasibility analysis) as early as possible. Validate core assumptions through small, initial steps before committing significant resources.
5.  **Data Processing Decomposition:** For database analysis problems, precisely dissect the query or requirement. Generate tasks that are easier to understand and execute, avoiding the introduction of unnecessary or superfluous analysis demands.


**Principles that must be followed**
1. For tasks that require database queries, you should not break them down; keep them as independent, complete tasks. For example, if you've planned a query into 3 tasks, but these three tasks could actually be completed with just one SQL statement, then you shouldn't split up this type of task.
2. For knowledge-based Q&A tasks, simply select the most suitable expert and use the original question as the step description without breaking down the original question.


**agents infomation of them are below: **

{agents}

When creating steps, please specify the order id, the step description and the agent names.


**Contextual data information related to the question**

{information}


The output format must be a valid JSON string. Example output format:

{instructions}


Output requirements:

1. Only output the required JSON-formatted data; other reasoning is not needed.
"""

PLANNER_COT_INSTRUCTIONS_EN_HISTORY = """
# Role: Chief Strategy Planner

## Core Mission
You are a senior planning expert. Your responsibility is not merely to list tasks, but to **design an optimal execution strategy that achieves the final goal in the most efficient and reliable manner possible.**

## Planning Process & Principles
Before formulating a plan, you MUST conduct the following analysis:
1.  **Goal Decomposition via Backward Planning:** Work backward from the end goal to identify the **critical necessary conditions** for its achievement. Every step must be an essential milestone that directly contributes to accomplishing the objective.
2.  **Critical Path Optimization:** Identify the "critical path" within the overall plan (i.e., the sequence of tasks that determines the shortest possible duration or has the strongest dependencies). Prioritize and optimize the steps on this path to ensure overall efficiency.
3.  **Precise Resource Matching:** Assign each step to the most qualified expert, ensuring "the right person handles the right task." Consider task dependencies and potential expert workload to avoid bottlenecks.
4.  **Risk-Frontloading & Validation:** Position steps involving uncertainty or risk (e.g., information gathering, feasibility analysis) as early as possible. Validate core assumptions through small, initial steps before committing significant resources.
5.  **Data Processing Decomposition:** For database analysis problems, precisely dissect the query or requirement. Generate tasks that are easier to understand and execute, avoiding the introduction of unnecessary or superfluous analysis demands.


**Principles that must be followed**
1. For tasks that require database queries, you should not break them down; keep them as independent, complete tasks. For example, if you've planned a query into 3 tasks, but these three tasks could actually be completed with just one SQL statement, then you shouldn't split up this type of task.
2. For knowledge-based Q&A tasks, simply select the most suitable expert and use the original question as the step description without breaking down the original question.



During planning, you must review the previous conversation records to ensure multi-turn dialogue capability. The conversation records are arranged chronologically, from past to present.
The recent conversation history is as follows:
{history}


**agents infomation of them are below: **
{agents}

When creating steps, please specify the order id, the step description and the agent names.


**Contextual data information related to the question**

{information}


The output format must be a valid JSON string. Example output format:

{instructions}


Output requirements:

1. Only output the required JSON-formatted data; other reasoning is not needed.
"""

# System Instructions to the Orchestrator Agent
Orchestrator_INSTRUCTIONS_ZH = """
你是一个知识专家，可以根据原始的问题，以及原始问题拆分出来的子问题和子问题的答案进行分析。

**回答规则**

1. 如果问题和答案是相关的，就进行合并总结，最后输出原始问题需要的答案。

2. 如果背景知识与用户问题无关或信息不足，请不要直接回答问题，你就询问用户，让用户进行相关信息的补充，或者重新提问。

3. 要满足多轮对话的能力，对话记录是按照时间，从过去到现在的对话记录。

"""

Orchestrator_INSTRUCTIONS_EN = """
You are a knowledge expert who can analyze based on the original question, as well as the sub-questions derived from the original question and their corresponding answers.

**Response Rules**

1. If the questions and answers are relevant, consolidate and summarize them, ultimately providing the answer required for the original question.

2. If the background knowledge is unrelated to the user's question or insufficient, please do not answer the question directly. Instead, ask the user to provide additional relevant information or rephrase the question.

"""

# Initialize Langfuse client
langfuse = get_client()

# Verify connection
if langfuse.auth_check():
    logger.info("Langfuse client is authenticated and ready!")
else:
    logger.info("Authentication failed. Please check your credentials and host.")

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


class PlannerTask(BaseModel):
    """Represents a single task generated by the Planner."""

    id: int = Field(description='Sequential ID for the task.')

    description: str = Field(
        description='description of subtask'
    )

    agent: str = Field(
        description='agent name of the task to be executed.'
    )


class TaskList(BaseModel):
    """Output schema for the Planner Agent."""

    original_query: Optional[str] = Field(
        description='The original user query for context.'
    )

    tasks: List[PlannerTask] = Field(
        description='A list of tasks to be executed sequentially.'
    )

class TaskStatus(BaseModel):
    """Represents a single task generated by the Planner."""

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

def tasklist_to_string(task_list: TaskList) -> str:
    lines = []
    for task in task_list.tasks:
        line = f"[{task.id}]: {task.description} - [{task.agent}]"
        lines.append(line)
    
    return "\nAll Tasks:\n" + "\n".join(lines) + "\n\n"

class PlannerAgent(BaseAgent):
    """Planner Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        dd_namespace: str = None,
        data_descriptors:list = None,
        descriptor_types:list = None
    ):
        logger.info('Initializing PlannerAgent')
        logger.info(f"PlannerAgent received descriptor_types: {descriptor_types}")
        logger.info(f"PlannerAgent received data_descriptors: {data_descriptors}")
        super().__init__(
            agent_name='PlannerAgent',
            description='Breakdown the user request into executable tasks',
            content_types=['text', 'text/plain'],
        )
        self.manager = ModelManager()
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body={
                "enable_thinking": False
            },
        )
        self.data_services_client = DataServicesClient(base_url=data_services_url, timeout=600)
        self.metadata = metadata
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.dd_namespace = dd_namespace
        self.data_descriptors = data_descriptors
        self.descriptor_types = descriptor_types

    # generate agent skills string
    def format_agent_skills(self, skills_list):
        result_lines = []
        
        for i, skill in enumerate(skills_list, 1):
            lines = [
                f"Skill {i}:",
                f"  ID: {skill.id}",
                f"  Name: {skill.name}",
                f"  Description: {skill.description}",
            ]

            if skill.tags:
                lines.append(f"  Tags: {', '.join(skill.tags)}")
            
            if skill.examples:
                lines.append(f"  Examples: {', '.join(skill.examples)}")
            
            result_lines.extend(lines)
            result_lines.append("")

        if result_lines and result_lines[-1] == "":
            result_lines.pop()
        
        return "\n".join(result_lines)

    # Create a prompt for the large language model to generate relevant information about all agents in order to determine which agents to use
    def generate_system_prompt_agents(self, agent_cards) -> str:
        result = []
        for index, agent_card in enumerate(agent_cards, start=1):
            skills = self.format_agent_skills(agent_card.skills)
            agent_content = f'{index}. agent name: {agent_card.name}, description：{agent_card.description}, skills:{skills}'
            result.append(agent_content)

        system_prompt_agents = '\n\n'.join(result)
        return system_prompt_agents

    def analyze_descriptor_types(self):
        """
        return: (ddname, structured, mysql) / (ddname, unstructured, "")
        """
        
        if self.descriptor_types is None:
            logger.error("descriptor_types is None")
            return "", "unknown", ""
        
        if not isinstance(self.descriptor_types, list):
            logger.error(f"descriptor_types is not a list, but {type(self.descriptor_types)}")
            return "", "unknown", ""
        
        if len(self.descriptor_types) == 0:
            logger.warning("descriptor_types is an empty list")
            return "", "unknown", ""

        logger.info(f"PlannerAgent analyze_descriptor_types, descriptor_types:{self.descriptor_types}")

        structured_pattern = r'structured-([a-zA-Z0-9_]+)'
        
        for desc_type in self.descriptor_types:
            desc_type_split = desc_type.split(":")

            match = re.search(structured_pattern, desc_type_split[1])
            if match:
                db_type = match.group(1)
                return desc_type_split[0], "structured", db_type
        
        for desc_type in self.descriptor_types:
            desc_type_split = desc_type.split(":")
            if "unstructured" in desc_type_split[1]:
                return desc_type_split[0], "unstructured", ""
        
        return "", "unknown", ""

    async def get_history(self) -> list:
        """
        human: Hello  
        assistant: Hello! How can I help you?  
        human: What's the weather like today?  
        assistant: Please provide your location information.
        """

        logger.info(f"PlannerAgent get_history metadata: user_id: {self.metadata['user_id']}, agent_id:{self.metadata['agent_id']}, run_id:{self.metadata['run_id']}")
        
        search_items = []

        search_request = SearchHistoryRequest(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
                limit=5
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"PlannerAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"PlannerAgent get_history response : {search_items}")

        all_messages = []
        for item in search_items:
            if hasattr(item, 'messages') and item.messages:
                all_messages.extend(item.messages)

        converted_messages = []
        for msg in all_messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                if msg.role == "user":
                    converted_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    converted_messages.append(AIMessage(content=msg.content))
            else:
                logger.warning(f"Unexpected message format: {msg}")

        logger.debug(f"PlannerAgent Converted {len(converted_messages)} history messages")

        formatted_lines = []
        for msg in converted_messages:
            if isinstance(msg, HumanMessage):
                formatted_lines.append(f"human：{msg.content}")
            elif isinstance(msg, AIMessage):
                formatted_lines.append(f"assistant：{msg.content}")

        return "\n".join(formatted_lines)

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

    async def get_knowledge(self, query) -> str:
        logger.info(f"=========get_knowledge, query: {query}, data_descriptors: {self.data_descriptors}")
        try:
            collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]

            knowledge = await self.data_services_client.search_multiple_collections(
                collection_names=collection_names,
                query=query,
                search_type="hybrid",
                limit=10,
                hybrid_threshold=0.1,
                memory_threshold=0.1
            )

        except Exception as e:
            logger.error(f'An error occurred during search knowledge from dataservices: {e}')
            knowledge = None
            raise
        finally:
            await self.data_services_client.close()

        knowledge_str = ""
        if knowledge:
            knowledge_str = knowledge.all_content
        logger.debug(f"get knowledge: {knowledge_str}")
        return knowledge_str

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

    async def make_plan(self, query, agent_cards) -> TaskList:

        ddname, agent_type, db_type = self.analyze_descriptor_types()

        if agent_type not in ["structured","unstructured"]:
            raise ValueError(f"Unsupported descriptor type: {agent_type}. ")

        information = ""

        # if agent is unstructured, do not use knowledge as context for planning.
        if agent_type == "unstructured":
            logger.info(" === PlannerAgent. agent is unstructured, do not use knowledge as context for planning")
            information = ""
        else:
            # get knowledge for plan
            information = await self.get_knowledge(query)

        system_template = ""
        if self.enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_EN_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_EN

        human_template = "{query}"

        json_prompt_instructions_zh: dict = {
            "original_query": "帮我查询北京的天气并推荐合适的穿衣建议",
            "tasks": [
                {
                    "id": 1,
                    "description": "查询北京当前和未来几天的天气情况", 
                    "agent": "天气查询员"
                },
                {
                    "id": 2,
                    "description": "根据天气情况推荐合适的穿衣搭配建议",
                    "agent": "时尚顾问"
                }
            ]
        }

        json_prompt_instructions_en: dict = {
            "original_query": "Help me check the weather in Beijing and recommend suitable clothing advice",
            "tasks": [
                {
                    "id": 1,
                    "description": "Check the current and upcoming weather conditions in Beijing", 
                    "agent": "Weather-Checker"
                },
                {
                    "id": 2,
                    "description": "Recommend appropriate clothing combinations based on the weather conditions",
                    "agent": "Fashion-Consultant"
                }
            ]
        }

        system_prompt = None

        if self.enable_history == "enable":
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["history", "agents", "information"],
                partial_variables={"instructions": json_prompt_instructions_en},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents", "information"],
                partial_variables={"instructions": json_prompt_instructions_en},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        chain = chat_prompt | self.llm

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        with langfuse.start_as_current_span(
            name="orchestrator-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            
            if self.enable_history == "enable":
                history = await self.get_history()
                answer = chain.invoke(
                    {"query": query, "history": history, "agents": system_prompt_agents, "information": information},
                    config={"callbacks": [langfuse_handler]}
                )
            else:
                answer = chain.invoke(
                    {"query": query, "agents": system_prompt_agents, "information": information},
                    config={"callbacks": [langfuse_handler]}
                )

            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === PlannerAgent.make_plan , llm result = {answer.content}")

        data_dict = self.format_llm_ouput(answer)

        tasks = TaskList(**data_dict)

        logger.info(f" === PlannerAgent.make_plan , tasks = {tasks}")

        return tasks


@asynccontextmanager
async def init_session(host, port, transport):
    """Initializes and manages an MCP ClientSession based on the specified transport.

    This asynchronous context manager establishes a connection to an MCP server
    using either Server-Sent Events (SSE) or Standard I/O (STDIO) transport.
    It handles the setup and teardown of the connection and yields an active
    `ClientSession` object ready for communication.

    Args:
        host: The hostname or IP address of the MCP server (used for SSE).
        port: The port number of the MCP server (used for SSE).
        transport: The communication transport to use ('sse' or 'stdio').

    Yields:
        ClientSession: An initialized and ready-to-use MCP client session.

    Raises:
        ValueError: If an unsupported transport type is provided (implicitly,
                    as it won't match 'sse' or 'stdio').
        Exception: Other potential exceptions during client initialization or
                   session setup.
    """
    if transport == 'sse':
        url = f'http://{host}:{port}/sse'
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(
                read_stream=read_stream, write_stream=write_stream
            ) as session:
                logger.debug('SSE ClientSession created, initializing...')
                await session.initialize()
                logger.info('SSE ClientSession initialized successfully.')
                yield session
    else:
        logger.error(f'Unsupported transport type: {transport}')
        raise ValueError(
            f"Unsupported transport type: {transport}. Must be 'sse' or 'stdio'."
        )


class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_descriptors:list = None,
        descriptor_types:list = None,
        debug: int = 0,
        data_services_url: str = None,
        metadata:dict = None,
        enable_history:str = None,
        agent_id: str = None,
        dd_namespace:str = None,
        max_loops: int = None
    ):
        logger.info('Initializing OrchestratorAgent')
        logger.info(f"OrchestratorAgent received descriptor_types: {descriptor_types}")
        logger.info(f"OrchestratorAgent received data_descriptors: {data_descriptors}")

        super().__init__(
            agent_name='OrchestratorAgent',
            description='call related agent than answer user question using agents answers.',
            content_types=['text', 'text/plain'],
        )
        self.planner_agent = PlannerAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=False,
            temperature=temperature,
            data_services_url=data_services_url,
            metadata=metadata,
            enable_history=enable_history,
            agent_id=agent_id,
            dd_namespace=dd_namespace,
            data_descriptors=data_descriptors,
            descriptor_types=descriptor_types
        )
        self.manager = ModelManager()
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body={
                "enable_thinking": False  # default to True
            },
        )
        self.data_descriptors = data_descriptors
        self.descriptor_types = descriptor_types
        self.debug = debug
        self.tasks_status = []
        self.data_services_client = DataServicesClient(base_url=data_services_url, timeout=600)
        self.metadata = metadata
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.max_loop_count = max_loops
        self.loop_retry_delay = 1
        self.agent_cards = []

    # get all plans (agent names) for user question to execute
    async def get_plan(self, query) -> TaskList:

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            return None

        return await self.planner_agent.make_plan(query, self.agent_cards)


    # get all or one resource (agent card) with resource name, such as list or expert_agent 
    async def find_resource(self, session: ClientSession, resource) -> ReadResourceResult:
        """Reads a resource from the connected MCP server.

        Args:
            session: The active ClientSession.
            resource: The URI of the resource to read (e.g., 'resource://agent_cards/list').

        Returns:
            The result of the resource read operation.
        """
        logger.info(f'Reading resource: {resource}')
        return await session.read_resource(resource)


    # get all AgentCards using find_resource func
    async def list_agent_cards(self, query) -> list[AgentCard]:
        """Reads all resources from the connected agent registry.
        Returns:
            agent_cards = [
                {
                "name": "Expert Agent",
                "description": "answer user question using self knowledge",
                "url": "http://192.168.xxx.xxx:20001/",
                "provider": null,
                "version": "1.0.0",
                "documentationUrl": null
                ...},
                ...
            ]
        """
        agent_cards = []

        agent_registry_client = AgentRegistryClient()
        
        try:
            response = await agent_registry_client.asearch(query, collection_name="expert_agent_cards")

            if response.status == "success":
                agent_cards_dict = []
                for item in response.result:
                    metadata = item.metadata
                    agent_data = metadata.get("agent", {})
                    
                    if isinstance(agent_data, dict):
                        agent_cards_dict.append(agent_data)
                    elif hasattr(agent_data, '__dict__'):
                        agent_dict = agent_data.__dict__.copy()
                        agent_cards_dict.append(agent_dict)
                
                agent_cards = [AgentCard(**agent_data) for agent_data in agent_cards_dict]
                
                logger.info(f"Successfully retrieved {len(agent_cards)} agent cards")
                return agent_cards
            else:
                logger.warning(f"Search returned non-success status: {response.status}")
                return []

        except Exception as e:
            logger.error(f'An error occurred during list_agent_cards: {e}')
            raise ValueError(f"An error occurred during list_agent_cards: {e}")


    # handle response artifact-update event to get knowledge string from a2a server
    def get_response_text(self, chunk) -> str:
        data = chunk.model_dump(mode='json', exclude_none=True)
        if (result := data.get('result')) is not None:
            kind = result.get('kind')
            if kind == 'artifact-update':
                artifact = result.get('artifact')
                parts = artifact.get('parts')
                if len(parts) > 0 and isinstance(parts[0], dict):
                    return parts[0].get('text')

            return ""


    # find one AgentCard with agent name which is from plan task
    async def find_agent(self, agent_name) -> AgentCard:
        # find agentcard using agent name
        agent_card = None

        for agentcard in self.agent_cards:
            if agentcard.name == agent_name:
                agent_card = agentcard

        return agent_card


    # call agent with a2a according to agent name which is from plan task (stream mode)
    async def a2a_stream(self, task_id, query, agent_name, current_tasks_status) -> AsyncIterable[str]:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            yield "Not found agent"
            return

        # Retrieve memories related to the question
        memory = await self.get_memory(query)

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'user_id': self.metadata['user_id'],
                'agent_id': self.metadata['agent_id'],
                'run_id': self.metadata['run_id'],
                'trace_id': self.metadata['trace_id'],
                'memory': memory,
                'current_tasks_status': current_tasks_status,
                'current_task': f"current task id: [{task_id}], task description: {query} ",
                'current_task_id': f"{task_id}",
            },
        }

        # build a2a client with agent_card
        async with httpx.AsyncClient() as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            try:
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result != "":
                        yield result

            except Exception as e:
                logger.error(f"An error occurred: {e}")
                yield "Error occurred"

    # call agent with a2a according to agent name which is from plan task (non-stream mode)
    async def a2a_non_stream(self, query, agent_name) -> str:
        # get agent card with agent name
        agent_card = await self.find_agent(agent_name)

        if agent_card is None:
            return "Not found agent"

        # Retrieve memories related to the question
        memory = self.get_memory(query)

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'user_id': self.metadata['user_id'],
                'agent_id': self.metadata['agent_id'],
                'run_id': self.metadata['run_id'],
                'memory': memory,
            },
        }

        # build a2a client with agent_card
        async with httpx.AsyncClient() as httpx_client:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            try:
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                agent_knowledge = []
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result != "":
                        agent_knowledge.append(result)
                return " ".join(agent_knowledge)

            except Exception as e:
                logger.error(f"An error occurred: {e}")
                return "Error occurred"

    async def get_last_step_status(self, step_result) -> str:
        last_step_last_status = ""

        step_status_llm_check_success = "reason:The current answer addresses the question very well."

        if step_status_llm_check_success in step_result:
            last_step_last_status = "complete"
        else:
            last_step_last_status = "fail"
        
        return last_step_last_status

    def _update_task_status(self, task_id: int, status: str, answer: str):
        for task_status in self.tasks_status:
            if task_status.id == task_id:
                task_status.status = status
                task_status.answer = answer
                break

    async def analyze_failure_reasons(self, tasks_status: List[TaskStatus]) -> str:
        failure_analysis = []
        
        for task in tasks_status:
            if task.status == "fail":
                failure_analysis.append(
                    f"Task {task.id} ('{task.description}') assign to {task.agent} fail."
                    f"Answer: {task.answer[:500]}..."
                )
        
        return "\n".join(failure_analysis) if failure_analysis else "No failed tasks found"

    async def should_retry_planning(self, tasks_status: List[TaskStatus]) -> bool:
        """Determine if replanning is needed"""
        if not tasks_status:
            return False
        
        any_failed = any(task.status == "fail" for task in tasks_status)
        
        return any_failed

    # get knowledge from expert agents (tasks param is TaskList)
    async def a2a_tasks(self, query, initial_tasks, updater, task_name, stream=True) -> list[str]:
        agents_knowledge = []

        if initial_tasks is None or not hasattr(initial_tasks, 'tasks') or not initial_tasks.tasks:
            logger.info("Warning: initial tasks is invalid")
            return agents_knowledge

        retry_count = 0
        current_tasks = initial_tasks
        
        while retry_count <= self.max_loop_count:
            logger.info(f"=== Start executing plan, retry count: {retry_count}/{self.max_loop_count} ===")
            
            self.tasks_status = []
            for task in current_tasks.tasks:
                task_status = TaskStatus(
                    id=task.id,
                    description=task.description,
                    agent=task.agent,
                    answer="",
                    status="not_started"
                )
                self.tasks_status.append(task_status)

            current_agents_knowledge = []
            
            for task in current_tasks.tasks:
                self._update_task_status(task.id, "start", "")
                logger.info(f"Task {task.id}: {task.description} -> [{task.agent}]")

                current_tasks_status_json = json.dumps([task_status.model_dump() for task_status in self.tasks_status])

                agent_steps_knowledge = []

                if self.debug == 1:
                    agent_knowledge_step = f"Task [{task.id}]: {task.description}; \n\n"
                    await updater.add_artifact(
                        [TextPart(text=agent_knowledge_step)],
                        name=task_name,
                    )

                if stream:
                    try:
                        async for agent_step_knowledge in self.a2a_stream(task.id, task.description, task.agent, current_tasks_status_json):
                            if self.debug == 1:
                                agent_knowledge_step = f"{agent_step_knowledge} \n"
                                await updater.add_artifact(
                                    [TextPart(text=agent_knowledge_step)],
                                    name=task_name,
                                )
                            agent_steps_knowledge.append(agent_step_knowledge)

                        agent_steps_knowledge_str = "\n".join(agent_steps_knowledge)

                        current_task_status = ""
                        if agent_steps_knowledge_str == "Error occurred":
                            current_task_status = "fail"
                        else:
                            last_step = agent_steps_knowledge[-1] if agent_steps_knowledge else ""
                            current_task_status = await self.get_last_step_status(last_step)

                        self._update_task_status(task.id, current_task_status, agent_steps_knowledge_str)
                        logger.info(f"Task {task.id} completion status: {current_task_status}")
                        current_agents_knowledge.append(agent_steps_knowledge_str)
                        if current_task_status == "fail":
                            break

                    except Exception as e:
                        logger.error(f"Error occurred while executing Task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(f"Task execution error: {str(e)}")

                else:
                    try:
                        agent_result = await self.a2a_non_stream(task.description, task.agent)
                        agent_knowledge_step = f"Task [{task.id}]: {task.description}; \nResult:\n {agent_result} \n"

                        current_task_status = "complete" if agent_result and "Error" not in agent_result else "fail"
                        self._update_task_status(task.id, current_task_status, agent_result)
                        
                        if self.debug == 1:
                            await updater.add_artifact(
                                [TextPart(text=agent_knowledge_step)],
                                name=task_name,
                            )
                        
                        current_agents_knowledge.append(agent_result)
                        
                    except Exception as e:
                        logger.error(f"Error during non-streaming execution of task {task.id}: {e}")
                        self._update_task_status(task.id, "fail", f"Execution error: {str(e)}")
                        current_agents_knowledge.append(f"Task execution error: {str(e)}")

            agents_knowledge.extend(current_agents_knowledge)
            
            if await self.should_retry_planning(self.tasks_status):
                retry_count += 1
                if retry_count <= self.max_loop_count:
                    logger.info(f"=== Plan execution failed, preparing for retry attempt {retry_count}  ===")
                    
                    failure_analysis = await self.analyze_failure_reasons(self.tasks_status)
                    logger.info(f"Failure analysis:\n{failure_analysis}")
                    
                    if self.debug == 1:
                        retry_msg = f"\n=== 计划执行遇到问题，正在进行第 {retry_count} 次重试 ===\n失败分析:\n{failure_analysis}\n"
                        # retry_msg = f"\n=== Plan execution encountered issues, performing retry attempt {retry_count} ===\nFailure analysis:\n{failure_analysis}\n"
                        await updater.add_artifact(
                            [TextPart(text=retry_msg)],
                            name=task_name,
                        )

                    improved_query = f"{query}\n\n之前的执行遇到了以下问题:\n{failure_analysis}\n请基于这些问题重新制定一个更好的计划。"
                    # improved_query = f"{query}\n\nThe previous execution encountered the following issues:\n{failure_analysis}\nPlease develop a better plan based on these problems."
                    new_tasks = await self.get_plan(improved_query)

                    if new_tasks is None or not hasattr(new_tasks, 'tasks') or not new_tasks.tasks:
                        logger.error("Re-planning failed, unable to obtain a valid plan")
                        
                        if self.debug == 1:
                            plan_fail_msg = f"\n⚠️ 重新规划失败，已达到最大重试次数 {self.max_loop_count}\n"
                            # plan_fail_msg = f"\n⚠️ Re-planning failed, maximum retry count {self.max_loop_count} reached\n"
                            await updater.add_artifact(
                                [TextPart(text=plan_fail_msg)],
                                name=task_name,
                            )
                        break
                    else:
                        current_tasks = new_tasks
                        logger.info(f"Re-planning successful, obtained {len(current_tasks.tasks)} new tasks")

                        if self.debug == 1:
                            new_plan_msg = f"\n=== 第 {retry_count} 次重新规划成功，新计划如下 ===\n"
                            # new_plan_msg = f"\n=== Retry attempt {retry_count} re-planning successful, new plan as follows ===\n"
                            new_plan_msg += tasklist_to_string(current_tasks)
                            await updater.add_artifact(
                                [TextPart(text=new_plan_msg)],
                                name=task_name,
                            )

                        await asyncio.sleep(self.loop_retry_delay)

                        continue
                else:
                    logger.info(f"Reached maximum retry count {self.max_loop_count}, stopping retries")
                    
                    if self.debug == 1:
                        max_retry_msg = f"\n⚠️ 已达到最大重试次数 {self.max_loop_count}，停止重试\n"
                        # max_retry_msg = f"\n⚠️ Maximum retry count {self.max_loop_count} reached, stopping retries\n"
                        await updater.add_artifact(
                            [TextPart(text=max_retry_msg)],
                            name=task_name,
                        )
                    break
            else:
                logger.info("All tasks completed successfully")
                
                if self.debug == 1:
                    success_msg = f"\n✅ 所有任务执行成功完成\n"
                    # success_msg = f"\n✅ All tasks executed successfully\n"
                    await updater.add_artifact(
                        [TextPart(text=success_msg)],
                        name=task_name,
                    )
                break
                
        logger.info(f"Task execution completed, total of {retry_count + 1} attempts made, collected {len(agents_knowledge)} knowledge items")
        return agents_knowledge

    async def add_memory(self, query, final_answer):
        final_answer_str = "".join(final_answer)
        logger.debug(f"add_memory metadata : user_id: {self.metadata['user_id']}, agent_id:{self.metadata['agent_id']}, run_id:{self.metadata['run_id']}")
        
        async with self.data_services_client.session_context() as client:
            memory_response = await client.store_memory(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
                messages=[
                    {
                        "role": "user",
                        "content": query
                    },
                    {
                        "role": "assistant", 
                        "content": final_answer_str
                    }
                ]
            )

        logger.debug(f"add_memory, query= {query}, final_answer={final_answer_str}, response : {memory_response}")
        return memory_response

    async def get_memory(self, query) -> str:
        logger.debug(f"get_memory metadata :query:{query}, user_id: {self.metadata['user_id']}, agent_id:{self.metadata['agent_id']}, run_id:{self.metadata['run_id']}")
        
        search_items = []

        async with self.data_services_client.session_context() as client:
            memory_search_response = await client.search_memories(
                query=query,
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
                limit=10
            )

        if memory_search_response.status == "success":
            search_items = self.data_services_client.parse_memory_search_results(memory_search_response)    
        else:
            if memory_search_response.detail:
                logger.error(f"get_memory error msg: {memory_search_response.detail}")

        logger.debug(f"get_memory response : {search_items}")

        memory_texts = [item.memory for item in search_items if item.memory]

        memory_texts_str = "\n".join(memory_texts)

        return memory_texts_str

    async def add_history(self, query, final_answer):
        final_answer_str = "".join(final_answer)
        logger.debug(f"add_history metadata : user_id: {self.metadata['user_id']}, agent_id:{self.metadata['agent_id']}, run_id:{self.metadata['run_id']}")
        
        create_request = CreateHistoryRequest(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
                messages=[
                    HistoryMessage(role="user", content=query),
                    HistoryMessage(role="assistant", content=final_answer_str)
                ]
            )
        async with self.data_services_client.session_context() as client:
            history_response = await client.create_history(create_request)

        logger.debug(f"add_history, query= {query}, final_answer={final_answer_str}, response : {history_response}")
        return history_response

    async def get_history(self) -> list:
        """
        [
            HumanMessage(content="Hello"),
            AIMessage(content="Hello! How can I help you? "),
            HumanMessage(content="What's the weather like today?  "), 
            AIMessage(content="Please provide your location information.")
        ]
        """

        logger.debug(f"OrchestratorAgent get_history metadata: user_id: {self.metadata['user_id']}, agent_id:{self.metadata['agent_id']}, run_id:{self.metadata['run_id']}")
        
        search_items = []

        search_request = SearchHistoryRequest(
                user_id=self.metadata['user_id'],
                agent_id=self.agent_id,
                run_id=self.metadata['run_id'],
                limit=10
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history(search_request)

        if history_search_response.status == "success":
            search_items = history_search_response.data
        else:
            if history_search_response.detail:
                logger.error(f"OrchestratorAgent get_history error msg: {history_search_response.detail}")

        logger.debug(f"OrchestratorAgent get_history response : {search_items}")

        all_messages = []
        for item in search_items:
            if hasattr(item, 'messages') and item.messages:
                all_messages.extend(item.messages)

        converted_messages = []
        for msg in all_messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                if msg.role == "user":
                    converted_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    converted_messages.append(AIMessage(content=msg.content))
            else:
                logger.warning(f"Unexpected message format: {msg}")

        logger.debug(f"OrchestratorAgent onverted {len(converted_messages)} history messages")
        return converted_messages

    async def stream(self, query, task_knowledges) -> AsyncIterable[dict[str, Any]]:

        # Retrieve memories related to the question
        memory = await self.get_memory(query)

        final_answer = []

        if task_knowledges and all(isinstance(item, list) for item in task_knowledges):
            flat_knowledges = []
            for task_knowledge in task_knowledges:
                flat_knowledges.extend(task_knowledge)
            knowledge = "\n\n".join(flat_knowledges)
        else:
            knowledge = "\n\n".join(task_knowledges) if task_knowledges else ""

        system_template = Orchestrator_INSTRUCTIONS_ZH

        human_template = "background knowledge: {knowledge}。\n\n{memory}\n\nuser question:{query}"

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = None
        if self.enable_history == "enable":
            # Retrieve history related to the runid
            history_messages = await self.get_history()
            chat_prompt = ChatPromptTemplate.from_messages([system_prompt, *history_messages, human_prompt])
        else:
            chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm

        with langfuse.start_as_current_span(
            name="orchestrator-stream",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
            
            for chunk in chain.stream({"query": query, "knowledge": knowledge, "memory": memory}, config={"callbacks": [langfuse_handler]}):
                if hasattr(chunk, 'content') and chunk.content:
                    final_answer.append(chunk.content)
                    yield {'content': chunk.content, 'is_task_complete': False}

            span.update_trace(output={"answer": "".join(final_answer)})

        langfuse.flush()

        yield {'content': '', 'is_task_complete': True}

        # add history
        if self.enable_history == "enable":
            await self.add_history(query, final_answer)

        # add memory
        await self.add_memory(query, final_answer)


class OrchestratorAgentExecutor(AgentExecutor):
    """
    A Orchestrator Agent executor call PlannerAgent to get agents, than call agents.
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
        descriptor_types:list = None,
        debug: int = 0,
        data_services_url: str = None,
        enable_history: str = None,
        agent_id: str = None,
        dd_namespace:str = None,
        max_loops: int = 1
    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.data_descriptors=data_descriptors
        self.descriptor_types=descriptor_types
        self.debug = debug
        self.data_services_url=data_services_url
        self.enable_history = enable_history
        self.agent_id = agent_id
        self.dd_namespace = dd_namespace
        self.max_loops = max_loops

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()

        metadata = context.metadata
        logger.info(f"===== OrchestratorAgentExecutor, user request metadata is {metadata}.")

        agent = OrchestratorAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            descriptor_types=self.descriptor_types,
            debug=self.debug,
            data_services_url=self.data_services_url,
            metadata=metadata,
            enable_history=self.enable_history,
            agent_id=self.agent_id,
            dd_namespace= self.dd_namespace,
            max_loops= self.max_loops

        )

        if not context.message:
            raise Exception('No message provided')

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        # make plans for user question, each plan is the name of agent card
        steps = await agent.get_plan(query)

        if steps is None:
            logger.info(f"===== OrchestratorAgentExecutor, steps is empty.")
            part = TextPart(text="Not found agents. You can provide more information.")
            await updater.add_artifact(
                [part],
                name=f'{agent.agent_name}-result',
            )
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )
        else:
            if self.debug == 1:
                steps_str = tasklist_to_string(steps)
                await updater.add_artifact(
                    [TextPart(text=steps_str)],
                    name=f'{agent.agent_name}-result',
                )

            # call each agent to get the knowledge owned by each agent, then get some knowledges from agents
            task_name = f'{agent.agent_name}-result'
            task_knowledges = await agent.a2a_tasks(query, steps, updater, task_name)

            logger.debug(f"===== OrchestratorAgentExecutor.task_knowledges = {task_knowledges}")
            conversition = []
            async for event in agent.stream(query, task_knowledges):
                is_task_complete = event['is_task_complete']
                if not is_task_complete:
                    if event['content']:
                        part = TextPart(text=event['content'])
                        await updater.add_artifact(
                            [part],
                            name=f'{agent.agent_name}-result',
                        )
                        await asyncio.sleep(0.01)
                        conversition.append(event['content'])
                else:
                    await updater.complete(
                        message=new_agent_text_message(
                            event['content'], context_id=task.context_id
                        )
                    )

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')


@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=10100)
@click.option('--agent-card', 'agent_card', default='/app/agent_card/orchestrator_agent.json')
@click.option('--redis-host', 'redis_host',default='localhost', help='Redis server host')
@click.option('--redis-port', 'redis_port', default=6379, type=int)
@click.option('--redis-db', 'redis_db', default=0, type=int)
@click.option('--password', 'password', default=None)
@click.option('--provider', 'provider', default='openai_compatible')
@click.option('--api-key', 'api_key', default=None, help='API key for the LLM provider')
@click.option('--base-url', 'base_url', default='https://dashscope.aliyuncs.com/compatible-mode/v1')
@click.option('--model', 'model', default='qwen2.5-72b-instruct')
@click.option('--temperature', 'temperature', default=0.01, type=float, help='Temperature for LLM generation')
@click.option('--heartbeat-interval', 'heartbeat_interval',default=10, type=int, help='Heartbeat interval in seconds')
@click.option('--debug', 'debug',default=1, type=int, help='show running log')
@click.option('--max-loops', 'max_loops',default=2, type=int, help='max loops to run')
def main(host, port, agent_card, redis_host, redis_port, redis_db, password, provider, api_key, base_url, model, temperature, heartbeat_interval, debug, max_loops):
    """Starts an Agent server."""

    # reset login config , otherwise there is no time info in the log message.
    logging.basicConfig(
        force=True,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    try:
        if not agent_card:
            raise ValueError('Agent card is required')
        with Path.open(agent_card) as file:
            data = json.load(file)
        agent_card = AgentCard(**data)
        agent_host = os.getenv('Agent_Host',"0.0.0.0")
        agent_port = os.getenv('Agent_Port',"20001")
        agent_card.name = os.getenv('Agent_Name',"ExpertAgent")
        agent_card.description = os.getenv('Agent_Description',"you are an smart agent, answer user question.")
        agent_card.url = f'http://{agent_host}:{agent_port}'

        # handle skills
        skills_file = Path("/app/skills.json")
        if skills_file.exists():
            with skills_file.open() as file:
                skills_data = json.load(file)
            agent_skills = []
            for skill_data in skills_data:
                agent_skill = AgentSkill(**skill_data)
                agent_skills.append(agent_skill)
            agent_card.skills = agent_skills
        else:
            agent_card.skills = []

        logger.info(f"agent_card is: {agent_card}")

        dd_namespace = os.getenv('DD_NAMESPACE')
        logger.info(f"dd_namespace is: {dd_namespace}")

        data_descriptors_str = os.getenv('Data_Descriptor')
        data_descriptors = data_descriptors_str.split(",")
        logger.info(f"data_descriptors is: {data_descriptors}")

        descriptor_types_str = os.getenv('DescriptorTypes')
        descriptor_types = descriptor_types_str.split(";")
        logger.info(f"descriptor_types is: {descriptor_types}")

        enable_history = os.getenv('Enable_History',"enable")
        logger.info(f"enable_history is: {enable_history}")

        #dataservices
        data_services_url = os.getenv('DataServicesURL',"http://data-services.dac.svc.cluster.local:8000")
        
        registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)
        heartbeat_service = HeartbeatService(registry, interval=heartbeat_interval)

        if heartbeat_service.register_agent(agent_card):
            heartbeat_service.start()
            logger.info(f"Agent registered to Redis with heartbeat (interval: {heartbeat_interval}s)")
        else:
            logger.error("Failed to register agent to Redis")

        signal.signal(signal.SIGTERM, lambda s, f: registry.graceful_shutdown(agent_card.url))
        signal.signal(signal.SIGINT, lambda s, f: registry.graceful_shutdown(agent_card.url))  # Ctrl+C
        atexit.register(lambda: registry.graceful_shutdown(agent_card.url))

        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)
        request_handler = DefaultRequestHandler(
            agent_executor=OrchestratorAgentExecutor(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                data_descriptors=data_descriptors,
                descriptor_types=descriptor_types,
                debug=debug,
                data_services_url=data_services_url,
                enable_history=enable_history,
                agent_id=agent_card.name,
                dd_namespace=dd_namespace,
                max_loops=max_loops
            ),
            task_store=InMemoryTaskStore(),
            push_config_store=push_config_store,
            push_sender= push_sender
        )

        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        logger.info(f'Starting server on {host}:{port}')

        uvicorn.run(server.build(), host=host, port=port)
    except FileNotFoundError:
        logger.error(f"Error: File '{agent_card}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Error: File '{agent_card}' contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
