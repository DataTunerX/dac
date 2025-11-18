import json
import logging
import sys
from pathlib import Path
import click
import httpx
import uvicorn
import os
import asyncio
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
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .agentregistry_client import AgentRegistryClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_ZH = """
你是一个专业的任务规划师。你需要根据用户的输入，以及可以使用的智能体，来选择一个最好的执行路径。

思考过程：
1. 分析用户的请求，按照解决问题的思路，将问题拆分成多个可执行的任务。
2. 根据任务，以及提供的智能体，找到最适合处理任务的智能体，只能选择一个智能体。
3. 你要一步一步的仔细思考。最终给出一个合适的答案。


**回答决策规则：**
1. 如果能找到合适的智能体，那就设置agent字段为合适的智能体。
2. 如果不能能找到合适的智能体，那就设置agent字段为空字符串。


可以使用的智能体列表：
{agents}


输出的格式一定要是合法的json字符串，输出格式参考示例：

{instructions}

输出要求：

1.仅输出需要的json格式的数据，其它的推理的就不需要输出了。
"""


PLANNER_COT_INSTRUCTIONS_EN = """
You are a professional task planner. You need to select the best execution path based on the user's input and the available agents.

Thought process:
1. Analyze the user's request and break down the problem into multiple executable tasks according to the problem-solving approach.
2. Based on the tasks and the provided agents, find the most suitable agent to handle the task. Only one agent can be selected.
3. Think carefully step by step. Finally, provide an appropriate answer.

**Response decision rules:**
1. If a suitable agent can be found, set the agent field to the appropriate agent.
2. If no suitable agent can be found, set the agent field to an empty string.

List of available agents:
{agents}

The output must be in the format of a valid JSON string. Refer to the following example for the output format:

{instructions}

Output requirements:

1. Only output the required data in JSON format; no additional reasoning is needed.
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

class PlannerStep(BaseModel):
    """Output schema for the Planner Agent."""

    original_query: Optional[str] = Field(
        description='The original user query for context.'
    )

    agent: str = Field(
        description='agent name of the step to be executed.'
    )

class PlannerAgent(BaseAgent):
    """Planner Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01
    ):
        logger.info('Initializing PlannerAgent')
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
                "enable_thinking": False  # default to True
            },
        )

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

    # Generate a prompt containing information about all agents for the large language model to determine which agents to use.
    def generate_system_prompt_agents(self, agent_cards) -> str:
        result = []
        for index, agent_card in enumerate(agent_cards, start=1):
            skills = self.format_agent_skills(agent_card.skills)
            agent_content = f'{index}. agent name: {agent_card.name}, description：{agent_card.description}, skills: {skills}'
            result.append(agent_content)

        system_prompt_agents = '\n\n'.join(result)
        return system_prompt_agents

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

    def make_plan(self, query, agent_cards, user_id, run_id, trace_id) -> PlannerStep:
        """
        Based on the information from all provided agent cards, analyze which agents are required for the user's query, and finally return the names and descriptions of these agent cards.
        """

        system_template = PLANNER_COT_INSTRUCTIONS_ZH

        human_template = "{query}"

        json_prompt_instructions: dict = {
            "original_query": "Using Python, write a program for a sorting algorithm.",
            "agent": "coder-agent"
        }

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["agents"],
            partial_variables={"instructions": json_prompt_instructions},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        chain = chat_prompt | self.llm

        # Use the predefined trace ID with trace_context
        with langfuse.start_as_current_span(
            name="routingagent-make_plan",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )
         
            # LangChain execution will be part of this trace
            answer = chain.invoke(
                {"query": query, "agents": system_prompt_agents},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === PlannerAgent.make_plan , llm result = {answer.content}")

        data_dict = self.format_llm_ouput(answer)

        logger.info(f" === PlannerAgent.make_plan , data_dict = {data_dict}")

        step = PlannerStep(**data_dict)
        logger.info(f" === PlannerAgent.make_plan , step = {step}")
        return step


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


class RoutingAgent(BaseAgent):
    """Routing Agent."""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01
    ):
        logger.info('Initializing RoutingAgent')
        super().__init__(
            agent_name='RoutingAgent',
            description='call related agent than answer user question using agents answers.',
            content_types=['text', 'text/plain'],
        )
        self.planner_agent = PlannerAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=False,
            temperature=temperature
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
        self.agent_cards = []


    # get all plans (agent names) for user question to execute
    async def get_plan(self, query, user_id, run_id, trace_id) -> PlannerStep:

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            return None

        return self.planner_agent.make_plan(query, self.agent_cards, user_id, run_id, trace_id)


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
            response = await agent_registry_client.asearch(query, collection_name="orchestrator_agent_cards")

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

class RoutingAgentExecutor(AgentExecutor):
    """
    A Routing Agent executor call PlannerAgent to get agents, than call agents.
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01
    ):
        self.agent = RoutingAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=stream,
            temperature=temperature
        )

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        if not context.message:
            raise Exception('No message provided')

        metadata = context.metadata
        logger.info(f"=====user request metadata is {metadata}.")

        user_id = metadata.get('user_id') or str(uuid4())

        run_id = metadata.get('run_id') or str(uuid4())

        request_id = str(uuid4())

        trace_id = Langfuse.create_trace_id(seed=request_id)

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # make plans for user question, each plan is the name of agent card
        step = await self.agent.get_plan(query, user_id, run_id, trace_id)
        logger.info(f"===== RoutingAgentExecutor, step is {step}.")

        if step is None or (step is not None and (step.agent is None or step.agent == "")):
            logger.info("===== RoutingAgentExecutor, step is empty.")
            part = TextPart(text="No enough information to handle your question. You can provide more information.")
            await updater.add_artifact(
                [part],
                name=f'{self.agent.agent_name}-result',
            )
            await updater.complete(
                message=new_agent_text_message(
                    "", context_id=task.context_id
                )
            )
        else:
            # get agent card with agent name
            agent_card = await self.agent.find_agent(step.agent)

            if agent_card is None:
                logger.info("===== RoutingAgentExecutor, Not found agents.")
                part = TextPart(text="Not found agents. You can provide more information.")
                await updater.add_artifact(
                    [part],
                    name=f'{self.agent.agent_name}-result',
                )
                await updater.complete(
                    message=new_agent_text_message(
                        "", context_id=task.context_id
                    )
                )
            else:
                logger.info(f"===== RoutingAgentExecutor, found agent: {agent_card}.")

                send_message_payload: dict[str, Any] = {
                    'message': {
                        'role': 'user',
                        'parts': [
                            {'type': 'text', 'text': query}
                        ],
                        'messageId': uuid4().hex,
                    },
                    'metadata': {
                        'user_id': user_id,
                        'agent_id': agent_card.name,
                        'run_id': run_id,
                        'trace_id': trace_id,
                    },
                }

                # build a2a client from agent_card.url
                async with httpx.AsyncClient() as httpx_client:
                    client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                    try:
                        streaming_request = SendStreamingMessageRequest(
                            id=uuid4().hex,
                            params=MessageSendParams(**send_message_payload)
                        )
                        stream_response = client.send_message_streaming(streaming_request)
                        async for chunk in stream_response:
                            result = self.agent.get_response_text(chunk)
                            if result:
                                part = TextPart(text=result)
                                await updater.add_artifact(
                                    [part],
                                    name=f'{self.agent.agent_name}-result',
                                )
                        await updater.complete(
                            message=new_agent_text_message(
                                "", context_id=task.context_id
                            )
                        )
                    except Exception as e:
                        logger.error(f"An error occurred: {e}")

    @override
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')



@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=10100)
@click.option('--agent-card', 'agent_card', default='/app/agent_card/routing_agent.json')
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
def main(host, port, agent_card, redis_host, redis_port, redis_db, password, provider, api_key, base_url, model, temperature, heartbeat_interval):
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
        agent_host = os.getenv('Agent_Host')
        agent_port = os.getenv('Agent_Port',"19999")
        agent_card.url = f'http://{agent_host}:{agent_port}'

        logger.info(f"agent_card is: {agent_card}")
        
        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)
        request_handler = DefaultRequestHandler(
            agent_executor=RoutingAgentExecutor(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature
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
