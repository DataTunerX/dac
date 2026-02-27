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
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from .agentregistry_client import AgentRegistryClient
from .dataservices_client import DataServicesClient, CreateHistoryRequest, HistoryMessage, SearchHistoryRequest

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# System Instructions to the Planner Agent
PLANNER_COT_INSTRUCTIONS_ZH = """
# Role：专业任务规划师（业务领地导航专家）

## 核心使命
通过识别用户意图中的“核心本体”，将其分发至拥有该业务领地主权的专家智能体。

## 任务执行逻辑（Chain-of-Thought）
在构造 JSON 响应时，必须在内部完成以下“领地判定”逻辑：
1. **本体提取（Entity Extraction）**：从用户输入中剥离动作（如统计、查询、处理），锁定**核心业务名词**（即“业务实体”）。
2. **领地归属判定（Domain Ownership）**：
   - 将提取的“业务实体”与各智能体的 `description` 进行语义映射。
   - **判定准则**：智能体的描述决定了其**业务边界**。只要该实体属于该智能体的业务范畴，该智能体即拥有该问题的“第一处理权”。
3. **能力泛化推断（Capability Generalization）**：
   - **屏蔽显式限制**：忽略智能体技能列表中是否缺失特定动词。只要业务实体对齐，应默认该智能体具备处理该实体相关一切需求（包括但不限于查询、分析、操作、管理）的隐含能力。
   - **主权优先**：当智能体身份与业务实体高度一致时，即使其声称不负责某细分操作，也应视其为该业务的唯一入口进行分发。

## 智能体选择流程
1. **实体主权匹配**：优先匹配用户问题的“主语”与智能体的“业务定义”。
2. **拒绝盲目过滤**：不得因技能（Skills）描述不全而拒绝分发。技能仅作为功能参考，不作为准入限制。
3. **严防“跨领地”分发**：
   - 只有当用户问题的实体与智能体的业务领地**完全无关**（属于不同维度的业务系统）时，才允许返回空字符串 `""`。
   - 在同一个业务体系内，必须选择最相关的领地专家。
4. **上下文一致性**：保持多轮对话中业务实体的逻辑承接。
5. **名称精确匹配**：agent 字段必须与列表中 **name** 完全一致。

---
**可用的智能体（领域专家）：**
{agents}

---
## 输出要求
1. **格式控制**：**只允许输出一个合法的 JSON 字符串**，不包含 Markdown。
2. **字段定义**：
   - `thought_process`: 记录 1. 识别的核心业务实体；2. 该实体如何映射到智能体的领地；3. 基于主权原则的隐含能力推断过程。
   - `original_query`: 用户原始输入。
   - `agent`: 匹配的智能体 `name`，若无任何领地相关专家则填 `""`。

## 示例参考
{instructions}
"""

PLANNER_COT_INSTRUCTIONS_ZH_HISTORY = """
# Role：专业任务规划师（业务领地导航专家）

## 核心使命
通过识别用户意图中的“核心本体”，将其分发至拥有该业务领地主权的专家智能体。

## 任务执行逻辑（Chain-of-Thought）
在构造 JSON 响应时，必须在内部完成以下“领地判定”逻辑：
1. **本体提取（Entity Extraction）**：从用户输入中剥离动作（如统计、查询、处理），锁定**核心业务名词**（即“业务实体”）。
2. **领地归属判定（Domain Ownership）**：
   - 将提取的“业务实体”与各智能体的 `description` 进行语义映射。
   - **判定准则**：智能体的描述决定了其**业务边界**。只要该实体属于该智能体的业务范畴，该智能体即拥有该问题的“第一处理权”。
3. **能力泛化推断（Capability Generalization）**：
   - **屏蔽显式限制**：忽略智能体技能列表中是否缺失特定动词。只要业务实体对齐，应默认该智能体具备处理该实体相关一切需求（包括但不限于查询、分析、操作、管理）的隐含能力。
   - **主权优先**：当智能体身份与业务实体高度一致时，即使其声称不负责某细分操作，也应视其为该业务的唯一入口进行分发。

## 智能体选择流程
1. **实体主权匹配**：优先匹配用户问题的“主语”与智能体的“业务定义”。
2. **拒绝盲目过滤**：不得因技能（Skills）描述不全而拒绝分发。技能仅作为功能参考，不作为准入限制。
3. **严防“跨领地”分发**：
   - 只有当用户问题的实体与智能体的业务领地**完全无关**（属于不同维度的业务系统）时，才允许返回空字符串 `""`。
   - 在同一个业务体系内，必须选择最相关的领地专家。
4. **上下文一致性**：保持多轮对话中业务实体的逻辑承接。
5. **名称精确匹配**：agent 字段必须与列表中 **name** 完全一致。

---
**对话历史（按时间顺序）：**
{history}

**可用的智能体（领域专家）：**
{agents}

---
## 输出要求
1. **格式控制**：**只允许输出一个合法的 JSON 字符串**，不包含 Markdown。
2. **字段定义**：
   - `thought_process`: 记录 1. 识别的核心业务实体；2. 该实体如何映射到智能体的领地；3. 基于主权原则的隐含能力推断过程。
   - `original_query`: 用户原始输入。
   - `agent`: 匹配的智能体 `name`，若无任何领地相关专家则填 `""`。

## 示例参考
{instructions}
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

class PlannerStep(BaseModel):
    """Output schema for the Planner Agent."""

    original_query: Optional[str] = Field(
        description='The original user query for context.'
    )

    agent: str = Field(
        description='agent name of the step to be executed.'
    )


# ==================== Capability Check Protocol (Broadcast Routing) ====================
# Message type flag used in A2A metadata to indicate a capability check request
CAPABILITY_CHECK_MESSAGE_TYPE = "capability_check"


class CapabilityCheckResponse(BaseModel):
    """Standard response model for capability check A2A requests.
    
    When routing broadcasts a 'can you handle this?' request to all orchestrators,
    each orchestrator responds with this structured JSON so the router can easily
    parse and compare answers.
    """
    can_handle: bool = Field(
        description="Whether this agent can handle the given query."
    )
    confidence: float = Field(
        default=0.0,
        description="Confidence level from 0.0 to 1.0."
    )
    reason: str = Field(
        default="",
        description="Brief explanation for the capability assessment."
    )
    agent_name: str = Field(
        default="",
        description="Name of the responding agent."
    )
    agent_url: str = Field(
        default="",
        description="URL of the responding agent."
    )

# ==================== Multi-Root Task Plan Protocol ====================

MULTI_ROOT_CONFIDENCE_THRESHOLD = float(os.getenv("MULTI_ROOT_CONFIDENCE_THRESHOLD", "0.6"))

MULTI_ROOT_TASK_PLAN_PROMPT = """# Role：智能任务分析与规划师

多个领域专家都表示可以处理用户的问题，请你**逐步分析**该问题是否真的需要多个专家协作，还是交给一个最合适的专家即可。

## 思考步骤（Chain-of-Thought，写入 reasoning 字段）

**步骤 1 - 提取核心意图**：用户问题中涉及哪些**数据实体**和**业务动作**？逐一列出。

**步骤 2 - 领域归属判定**：将步骤 1 提取的每个数据实体映射到下面的领域专家。判断：这些实体是否分属**不同专家的独占领域**？还是存在一个专家能完整覆盖所有实体？

**步骤 3 - 拆解必要性判定（关键）**：
- 如果所有数据实体都属于**同一个专家的领域**，则**不需要拆解**，直接交给该专家。
- 如果数据实体明确分属**两个或以上专家的独占领域**，且用户确实需要来自不同领域的数据，才**需要拆解**。
- **不要为了"更全面"而强行拆解**——如果一个专家能完整回答，拆解反而会降低回答质量。
- 当领域有重叠时，优先选择**置信度更高**或**描述更匹配**的单个专家。

**步骤 4 - 任务规划**：
- 若判定**不需要拆解**：tasks 中只放 1 条任务，description 使用用户原始问题，agent 为最佳专家。
- 若判定**需要拆解**：将问题按领域拆为多个子任务，每个子任务只涉及一个专家擅长的内容。description 忠实反映用户原始意图中属于该领域的部分，不捏造用户未提及的条件。

**步骤 5 - 依赖关系**：子任务之间是否有先后依赖？后续任务需要前序任务的结果时，设置 depends_on。无依赖的子任务可以并行执行。

---
## 可用的领域专家

{agents}

---
## 输出格式

**只输出一个合法 JSON 对象**，不包含 Markdown：

{{
  "reasoning": "步骤1：... 步骤2：... 步骤3：... 步骤4：... 步骤5：...",
  "needs_split": true 或 false,
  "tasks": [
    {{"id": 1, "description": "任务描述", "agent": "专家名称", "depends_on": []}}
  ]
}}

注意：
- agent 字段必须与上面列表中的 name **完全一致**
- needs_split=false 时 tasks 中只有 1 条任务
- needs_split=true 时 tasks 中有 2 条或以上任务

## 用户问题

{query}
"""

MULTI_ROOT_AGGREGATE_PROMPT = """你是一个智能综合分析师。多个领域专家分别完成了各自的子任务，请综合他们的结果，为用户提供一个完整、连贯的最终答案。

## 用户原始问题

{query}

## 各领域专家的回答

{results}

## 要求

1. 综合所有专家的回答，形成一个完整的答案
2. 如果不同专家的回答有关联，请建立联系并做对比/分析
3. 使用自然、流畅的语言，不要简单罗列
4. 如果某个专家未能提供有效回答，说明该部分信息暂不可用
"""


class MultiRootTask(BaseModel):
    id: int = Field(description="Task ID")
    description: str = Field(description="Sub-task description")
    agent: str = Field(description="Agent name to handle this task")
    depends_on: List[int] = Field(default_factory=list, description="IDs of tasks this depends on")


class MultiRootTaskPlan(BaseModel):
    reasoning: str = Field(default="", description="Planning reasoning")
    needs_split: bool = Field(default=True, description="Whether the query truly needs multi-agent split")
    tasks: List[MultiRootTask] = Field(default_factory=list, description="List of sub-tasks")


# ==================== End Multi-Root Task Plan Protocol ====================


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
        data_services_url: str = None
    ):
        logger.info('Initializing PlannerAgent')
        super().__init__(
            agent_name='PlannerAgent',
            description='Breakdown the user request into executable tasks',
            content_types=['text', 'text/plain'],
        )
        self.manager = ModelManager()
        # 默认设置 enable_thinking 参数；设 ENABLE_THINKING_PARAM=false/0/no 时不传该参数（extra_body={}，用模型默认）
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
        self.data_services_client = DataServicesClient(base_url=data_services_url, timeout=600)

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
        if not agent_cards:
            return ""
        lines = []
        for index, agent_card in enumerate(agent_cards, start=1):
            skills = self.format_agent_skills(agent_card.skills) if getattr(agent_card, "skills", None) else "（无）"
            block = [
                f"--- 智能体 {index} ---",
                f"name: {agent_card.name}",
                f"description: {agent_card.description or ''}",
                f"skills:\n{skills}" if skills and skills.strip() else "skills: （无）",
            ]
            lines.append("\n".join(block))
        return "\n\n".join(lines)

    def format_llm_ouput(self, answer) -> dict:
        data_dict = None
    
        logger.info(f"PlannerAgent llm output: {answer}")

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

    async def get_history(self, user_id:str, run_id:str) -> str:
        """
        return ->：

        human: Hello  
        assistant: Hello! How can I help you?  
        human: What's the weather like today?  
        assistant: Please provide your location information.
        """

        logger.info(f"PlannerAgent get_history metadata: user_id: {user_id}, run_id:{run_id}")
        
        search_items = []

        history_limit = int(os.getenv('History_Limit','10'))

        search_request = SearchHistoryRequest(
                user_id=user_id,
                run_id=run_id,
                limit=history_limit
            )

        async with self.data_services_client.session_context() as client:
            history_search_response = await client.search_history_by_user_and_run(search_request)

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

    async def make_plan(self, query, agent_cards, user_id, run_id, trace_id) -> PlannerStep:
        """
        Based on the information from all provided agent cards, analyze which agents are required for the user's query, and finally return the names and descriptions of these agent cards.
        """

        enable_history = os.getenv('Enable_History',"enable")
        logger.info(f"enable_history is: {enable_history}")

        system_template = ""
        if enable_history == "enable":
            system_template = PLANNER_COT_INSTRUCTIONS_ZH_HISTORY
        else:
            system_template = PLANNER_COT_INSTRUCTIONS_ZH

        human_template = "{query}"

        json_prompt_instructions: dict = {
          "thought_process": "1.本体提取：对象为'订单'；2.领域判定：EcommerceAgent 负责订单领域；3.能力推断：该 Agent 具备统计功能。结论：匹配成功。",
          "original_query": "查询订单状态分布",
          "agent": "EcommerceTransactionOrchestrator"
        }

        system_prompt = None
        if enable_history == "enable":
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["history", "agents"],
                partial_variables={"instructions": json_prompt_instructions},
            )
        else:
            system_prompt = SystemMessagePromptTemplate.from_template(
                template=system_template,
                input_variables=["agents"],
                partial_variables={"instructions": json_prompt_instructions},
            )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        system_prompt_agents = self.generate_system_prompt_agents(agent_cards)

        logger.info(f"PlannerAgent.make_plan, system_prompt_agents = {system_prompt_agents}")

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

            answer = None
            if enable_history == "enable":
                history = await self.get_history(user_id=user_id, run_id=run_id)
                answer = chain.invoke(
                    {"query": query, "history": history, "agents": system_prompt_agents},
                    config={"callbacks": [langfuse_handler]}
                )
            else:
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
        temperature: float = 0.01,
        data_services_url: str = None
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
            temperature=temperature,
            data_services_url=data_services_url
        )
        self.manager = ModelManager()
        # 默认设置 enable_thinking 参数；设 ENABLE_THINKING_PARAM=false/0/no 时不传该参数（extra_body={}，用模型默认）
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
        self.data_services_url = (
            data_services_url
            if data_services_url
            else os.getenv("DataServicesURL", "http://data-services.dac.svc.cluster.local:8000")
        )
        self.agent_cards = []

    def _extract_semantic_group_id_from_agent_name(self, agent_name: str) -> Optional[str]:
        """Extract semantic group id from orchestrator name suffix: xxx-sg-<group_id>."""
        marker = "-sg-"
        if marker not in agent_name:
            return None
        group_id = agent_name.split(marker)[-1].strip()
        return group_id or None

    def _extract_semantic_group_id_from_agent_card(self, card: AgentCard) -> Optional[str]:
        """Extract semantic_group_id from capabilities.extensions contract first.

        Preferred source:
          - capabilities.extensions[uri='dac.semantic_group'].params["dac.semantic_group_id"]
        Backward compatibility:
          - params["semantic_group_id"]
        Fallback:
          - name suffix xxx-sg-<group_id>
        """
        caps = getattr(card, "capabilities", None)
        ext_list = None
        if isinstance(caps, dict):
            ext_list = caps.get("extensions")
        elif caps is not None:
            ext_list = getattr(caps, "extensions", None)

        if isinstance(ext_list, list):
            for ext in ext_list:
                if isinstance(ext, dict):
                    uri = ext.get("uri")
                    params = ext.get("params") or {}
                else:
                    uri = getattr(ext, "uri", None)
                    params = getattr(ext, "params", None) or {}
                if uri != "dac.semantic_group" or not isinstance(params, dict):
                    continue
                gid = (params.get("dac.semantic_group_id") or params.get("semantic_group_id") or "").strip()
                if gid:
                    return gid

        return self._extract_semantic_group_id_from_agent_name(card.name)

    async def _is_root_semantic_group(self, group_id: str) -> tuple[Optional[bool], str]:
        """Check whether semantic group is root by parent_id.

        Returns:
            (is_root, reason), where is_root=None means unknown/failed.
        """
        try:
            url = f"{self.data_services_url.rstrip('/')}/semantic_groups/{group_id}"
            logger.info("[RootGuardCheck] request: group_id=%s, url=%s", group_id, url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                body_preview = (resp.text or "")[:300]
                logger.warning(
                    "[RootGuardCheck] response non-200: group_id=%s, url=%s, status=%s, body_preview=%s",
                    group_id, url, resp.status_code, body_preview
                )
                return None, f"http_{resp.status_code}"
            parent_id = resp.json().get("data", {}).get("parent_id")
            logger.info(
                "[RootGuardCheck] response ok: group_id=%s, url=%s, parent_id=%s, is_root=%s",
                group_id, url, parent_id, parent_id is None
            )
            return parent_id is None, "ok"
        except Exception as e:
            logger.error(
                "[RootGuardCheck] request exception: group_id=%s, url=%s, error=%s",
                group_id,
                f"{self.data_services_url.rstrip('/')}/semantic_groups/{group_id}",
                e,
            )
            return None, f"exception:{e}"

    async def _apply_root_membership_guard(self, agent_cards: list[AgentCard]) -> list[AgentCard]:
        """Optional guard: filter out non-root SG agents before capability checks."""
        guard_enabled = os.getenv("ENABLE_ROOT_MEMBERSHIP_GUARD", "true").strip().lower() in ("true", "1", "yes")
        if not guard_enabled:
            return agent_cards

        guard_fail_policy = os.getenv("ROOT_GUARD_FAIL_POLICY", "fail_close").strip().lower()
        if guard_fail_policy not in ("fail_open", "fail_close"):
            logger.warning("Invalid ROOT_GUARD_FAIL_POLICY=%s, fallback to fail_close", guard_fail_policy)
            guard_fail_policy = "fail_close"

        kept: list[AgentCard] = []
        filtered: list[str] = []
        unknown: list[str] = []

        for card in agent_cards:
            group_id = self._extract_semantic_group_id_from_agent_card(card)
            # Non-SG agents are kept as-is.
            if not group_id:
                kept.append(card)
                continue

            is_root, reason = await self._is_root_semantic_group(group_id)
            if is_root is True:
                kept.append(card)
                continue
            if is_root is False:
                filtered.append(f"{card.name}(non_root)")
                continue

            # Unknown root status
            if guard_fail_policy == "fail_open":
                kept.append(card)
                unknown.append(f"{card.name}({reason},kept)")
            else:
                filtered.append(f"{card.name}(unknown:{reason})")
                unknown.append(f"{card.name}({reason},filtered)")

        logger.info(
            "Root membership guard: total=%d, kept=%d, filtered=%d, unknown=%d",
            len(agent_cards), len(kept), len(filtered), len(unknown)
        )
        if filtered:
            logger.warning("Root membership guard filtered agents: %s", filtered)
        return kept

    # get all plans (agent names) for user question to execute
    async def get_plan(self, query, user_id, run_id, trace_id) -> PlannerStep:

        self.agent_cards = await self.list_agent_cards(query)

        if len(self.agent_cards) == 0:
            logger.info("No agents found in registry, using default agent card: %s", self.default_agentcard().url)
            self.agent_cards = [self.default_agentcard()]

        return await self.planner_agent.make_plan(query, self.agent_cards, user_id, run_id, trace_id)


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
                "url": "http://192.168.xxx.xxx:20001",
                "provider": null,
                "version": "1.0.0",
                "documentationUrl": null
                ...},
                ...
            ]
        """
        agent_cards = []

        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("AgentRegistryCollection", "orchestrator_agent_cards")
        logger.info(
            "list_agent_cards: AgentRegistry base_url=%s, collection=%s (env AgentRegistryCollection)",
            os.getenv("AgentRegistry", "http://orchestrator-registry.dac.svc.cluster.local:10100").rstrip("/"),
            collection_name,
        )
        try:
            response = await agent_registry_client.asearch(query, collection_name=collection_name)

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
                
                agent_names = [card.name for card in agent_cards]
                logger.info(f"Successfully retrieved {len(agent_cards)} agent cards: {agent_names}")
                return agent_cards
            else:
                logger.warning(f"Search returned non-success status: {response.status}")
                return []

        except Exception as e:
            logger.error(f'An error occurred during list_agent_cards: {e}')
            raise ValueError(f"An error occurred during list_agent_cards: {e}")


    def default_agentcard(self) -> AgentCard:
        """Build a default AgentCard when no agents are found in registry. URL points to common orchestrator."""
        default_url = "http://common-orchestrator-agent.dac.svc.cluster.local:10100"
        return AgentCard(
            name="CommonAgent",
            description="I am a common system intelligent agent that can answer user-related questions.",
            url=default_url,
            version="1.0.0",
            capabilities={"streaming": "True", "pushNotifications": "True", "stateTransitionHistory": "False"},
            defaultInputModes=["text", "text/plain"],
            defaultOutputModes=["text", "text/plain"],
            skills=[],
        )

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

        logger.info(f"find_agent, agents= {self.agent_cards}, agent_name:= {agent_name}")
        agent_card = None

        for agentcard in self.agent_cards:
            if agentcard.name == agent_name:
                agent_card = agentcard

        return agent_card

    # ==================== Broadcast Routing Methods ====================

    async def list_all_agent_cards(self) -> list[AgentCard]:
        """Fetch ALL registered orchestrator agents from the registry service.
        
        Unlike list_agent_cards() which uses vector search,
        this retrieves every agent without query-based filtering.
        
        Returns:
            List of all AgentCard objects from the registry.
        """
        agent_registry_client = AgentRegistryClient()
        collection_name = os.getenv("AgentRegistryCollection", "orchestrator_agent_cards")
        all_agent_cards: list[AgentCard] = []

        try:
            agents_data = await agent_registry_client.alist_all_agents(
                collection_name=collection_name
            )
            logger.info(f"[DEBUG] list_all_agent_cards: agents_data type={type(agents_data).__name__}, len={len(agents_data)}")
            for idx, agent_data in enumerate(agents_data):
                logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] type={type(agent_data).__name__}, value(first 500 chars)={str(agent_data)[:500]}")
                if isinstance(agent_data, dict):
                    # Handle nested format where agent card is inside an "agent" key
                    if "agent" in agent_data and isinstance(agent_data["agent"], dict):
                        agent_data = agent_data["agent"]
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] unwrapped 'agent' key, keys now={list(agent_data.keys())}")
                    try:
                        all_agent_cards.append(AgentCard(**agent_data))
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] parsed OK as AgentCard, name={all_agent_cards[-1].name}")
                    except Exception as e:
                        logger.warning(f"Failed to parse agent card item[{idx}]: {e}, keys={list(agent_data.keys())}, data={str(agent_data)[:500]}")
                elif hasattr(agent_data, '__dict__'):
                    try:
                        all_agent_cards.append(AgentCard(**agent_data.__dict__))
                        logger.info(f"[DEBUG] list_all_agent_cards: item[{idx}] parsed OK from object, name={all_agent_cards[-1].name}")
                    except Exception as e:
                        logger.warning(f"Failed to parse agent card from object item[{idx}]: {e}")
                else:
                    logger.warning(f"[DEBUG] list_all_agent_cards: item[{idx}] skipped, not dict and no __dict__, type={type(agent_data).__name__}")

            agent_names = [card.name for card in all_agent_cards]
            logger.info(f"Broadcast routing: retrieved {len(all_agent_cards)} agents from registry: {agent_names}")
        except Exception as e:
            logger.error(f"Broadcast routing: failed to list all agents: {e}", exc_info=True)

        filtered_cards = await self._apply_root_membership_guard(all_agent_cards)
        filtered_names = [card.name for card in filtered_cards]
        logger.info(
            "Broadcast routing: candidates after root guard = %d, names=%s",
            len(filtered_cards),
            filtered_names,
        )
        return filtered_cards

    async def send_capability_check(
        self, query: str, agent_card: AgentCard, user_id: str, run_id: str, trace_id: str
    ) -> Optional[CapabilityCheckResponse]:
        """Send a capability check A2A request to a single orchestrator agent.
        
        Sends the user query with message_type='capability_check' in metadata.
        The receiving orchestrator should respond with a CapabilityCheckResponse JSON.
        
        Args:
            query: The user's question.
            agent_card: The target orchestrator agent's card.
            user_id: User ID for tracing.
            run_id: Run ID for tracing.
            trace_id: Trace ID for tracing.
            
        Returns:
            CapabilityCheckResponse if successful, None on failure.
        """
        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'type': 'text', 'text': query}
                ],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'message_type': CAPABILITY_CHECK_MESSAGE_TYPE,
                'user_id': user_id,
                'agent_id': agent_card.name,
                'run_id': run_id,
                'trace_id': trace_id,
            },
        }

        broadcast_timeout = float(os.getenv("BROADCAST_TIMEOUT", "30"))

        try:
            async with httpx.AsyncClient(timeout=broadcast_timeout) as httpx_client:
                client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                stream_response = client.send_message_streaming(streaming_request)
                response_parts = []
                async for chunk in stream_response:
                    result = self.get_response_text(chunk)
                    if result and result != "":
                        response_parts.append(result)

                full_response = "".join(response_parts).strip()

                # Clean markdown wrappers if present
                if full_response.startswith("```json"):
                    full_response = full_response[7:]
                elif full_response.startswith("```"):
                    full_response = full_response[3:]
                if full_response.endswith("```"):
                    full_response = full_response[:-3]
                full_response = full_response.strip()

                response_data = json.loads(full_response)
                return CapabilityCheckResponse(
                    can_handle=response_data.get("can_handle", False),
                    confidence=response_data.get("confidence", 0.0),
                    reason=response_data.get("reason", ""),
                    agent_name=response_data.get("agent_name", agent_card.name),
                    agent_url=response_data.get("agent_url", agent_card.url),
                )
        except json.JSONDecodeError as e:
            logger.error(
                f"Broadcast routing: JSON parse error for agent {agent_card.name} ({agent_card.url}): {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Broadcast routing: capability check failed for agent {agent_card.name} ({agent_card.url}): {e}"
            )
            return None

    async def broadcast_capability_check(
        self, query: str, user_id: str, run_id: str, trace_id: str
    ) -> list[tuple[AgentCard, CapabilityCheckResponse]]:
        """Broadcast a capability check to ALL registered orchestrator agents concurrently.
        
        Returns all capable agents sorted by confidence (highest first), not just the top one.
        The caller decides whether to use single-root or multi-root routing.
        """
        all_agent_cards = await self.list_all_agent_cards()

        if not all_agent_cards:
            logger.warning("Broadcast routing: no agents found in registry")
            return []

        logger.info(
            f"Broadcast routing: sending capability check to {len(all_agent_cards)} agents "
            f"for query: {query[:100]}..."
        )
        tasks = [
            self.send_capability_check(query, agent_card, user_id, run_id, trace_id)
            for agent_card in all_agent_cards
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Broadcast routing: exception for agent {all_agent_cards[i].name}: {result}"
                )
                continue
            if result is None:
                logger.info(
                    f"Broadcast routing: agent {all_agent_cards[i].name} returned no valid response"
                )
                continue
            if result.can_handle:
                capable_agents.append((all_agent_cards[i], result))
                logger.info(
                    f"Broadcast routing: agent '{result.agent_name}' CAN handle "
                    f"(confidence: {result.confidence}, reason: {result.reason})"
                )
            else:
                logger.info(
                    f"Broadcast routing: agent '{result.agent_name}' CANNOT handle "
                    f"(reason: {result.reason})"
                )

        capable_agents.sort(key=lambda x: x[1].confidence, reverse=True)
        logger.info(f"Broadcast routing: {len(capable_agents)} agent(s) can handle the query")
        return capable_agents

    async def get_plan_by_broadcast(
        self, query: str, user_id: str, run_id: str, trace_id: str
    ) -> tuple[Optional[PlannerStep], Optional[MultiRootTaskPlan], list[AgentCard]]:
        """Broadcast-based routing with single-root fast path and multi-root task plan.
        
        Returns:
            (step, multi_plan, agent_cards) where:
            - Single root: (PlannerStep, None, [agent]) 
            - Multi root: (None, MultiRootTaskPlan, [agents...])
            - No match: (None, None, [])
        """
        capable_agents = await self.broadcast_capability_check(query, user_id, run_id, trace_id)

        if not capable_agents:
            logger.info("Broadcast routing: no capable agent found, returning None")
            return None, None, []

        high_confidence = [
            (card, resp) for card, resp in capable_agents
            if resp.confidence >= MULTI_ROOT_CONFIDENCE_THRESHOLD
        ]

        # Single-root fast path: only one high-confidence agent, route directly
        if len(high_confidence) <= 1:
            selected_card, selected_resp = capable_agents[0]
            self.agent_cards = [selected_card]
            step = PlannerStep(original_query=query, agent=selected_card.name)
            logger.info(
                f"Broadcast routing: SINGLE ROOT fast path -> agent='{selected_card.name}' "
                f"(confidence={selected_resp.confidence})"
            )
            return step, None, [selected_card]

        # Multi-root: multiple agents with high confidence, use LLM task planning
        logger.info(
            f"Broadcast routing: MULTI ROOT detected, {len(high_confidence)} agents with "
            f"confidence >= {MULTI_ROOT_CONFIDENCE_THRESHOLD}"
        )
        agent_cards = [card for card, _ in high_confidence]
        self.agent_cards = agent_cards

        multi_plan = await self._plan_cross_root_tasks(query, high_confidence)

        if multi_plan and multi_plan.tasks:
            # LLM may decide split is unnecessary (needs_split=false, single task)
            if len(multi_plan.tasks) == 1:
                single_agent_name = multi_plan.tasks[0].agent
                single_card = next((c for c in agent_cards if c.name == single_agent_name), agent_cards[0])
                self.agent_cards = [single_card]
                step = PlannerStep(original_query=query, agent=single_card.name)
                logger.info(
                    "Multi-root LLM analysis: split NOT needed, routing to single agent '%s' "
                    "(reasoning: %s)", single_card.name, multi_plan.reasoning[:200]
                )
                return step, None, [single_card]
            return None, multi_plan, agent_cards

        # Fallback to single root if planning fails
        selected_card = agent_cards[0]
        step = PlannerStep(original_query=query, agent=selected_card.name)
        logger.warning("Multi-root task planning failed, falling back to single root")
        return step, None, [selected_card]

    async def _plan_cross_root_tasks(
        self, query: str, capable_agents: list[tuple[AgentCard, CapabilityCheckResponse]]
    ) -> Optional[MultiRootTaskPlan]:
        """Use LLM to decompose a user query into sub-tasks across multiple Root Orchestrators."""
        agents_desc = "\n".join([
            f"- name: {card.name}, description: {card.description}, "
            f"confidence: {resp.confidence}, reason: {resp.reason}"
            for card, resp in capable_agents
        ])

        prompt_text = MULTI_ROOT_TASK_PLAN_PROMPT.format(agents=agents_desc, query=query)

        try:
            response = await self.planner_agent.llm.ainvoke([HumanMessage(content=prompt_text)])
            raw = response.content.strip()

            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            plan_data = json.loads(raw)
            plan = MultiRootTaskPlan(**plan_data)
            logger.info(f"Multi-root task plan: {len(plan.tasks)} sub-tasks, reasoning: {plan.reasoning[:200]}")
            return plan
        except Exception as e:
            logger.error(f"Multi-root task planning failed: {e}", exc_info=True)
            return None

    async def dispatch_single_task_to_agent(
        self, task_description: str, agent_card: AgentCard,
        user_id: str, run_id: str, trace_id: str
    ) -> str:
        """Dispatch a single sub-task to an agent via A2A streaming and collect the full response."""
        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [{'type': 'text', 'text': task_description}],
                'messageId': uuid4().hex,
            },
            'metadata': {
                'user_id': user_id,
                'agent_id': agent_card.name,
                'run_id': run_id,
                'trace_id': trace_id,
            },
        }
        dispatch_timeout = float(os.getenv("MULTI_ROOT_DISPATCH_TIMEOUT", "120"))
        try:
            async with httpx.AsyncClient(timeout=dispatch_timeout) as httpx_client:
                client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
                streaming_request = SendStreamingMessageRequest(
                    id=uuid4().hex,
                    params=MessageSendParams(**send_message_payload)
                )
                parts = []
                async for chunk in client.send_message_streaming(streaming_request):
                    text = self.get_response_text(chunk)
                    if text:
                        parts.append(text)
                return "".join(parts).strip()
        except Exception as e:
            logger.error(f"Multi-root dispatch failed for agent {agent_card.name}: {e}")
            return f"[Error: {agent_card.name} 未能完成任务 - {e}]"

    async def execute_multi_root_plan(
        self, query: str, plan: MultiRootTaskPlan,
        user_id: str, run_id: str, trace_id: str
    ) -> str:
        """Execute a multi-root task plan: dispatch sub-tasks (respecting dependencies) and aggregate."""
        task_results: dict[int, str] = {}
        tasks_by_id = {t.id: t for t in plan.tasks}

        # Group tasks by dependency level for staged execution
        remaining = set(tasks_by_id.keys())
        while remaining:
            ready = [tid for tid in remaining if all(d in task_results for d in tasks_by_id[tid].depends_on)]
            if not ready:
                logger.error("Multi-root plan: circular dependency detected, breaking")
                break

            dispatch_coros = []
            for tid in ready:
                task_def = tasks_by_id[tid]
                agent_card = await self.find_agent(task_def.agent)
                if agent_card is None:
                    logger.warning(f"Multi-root plan: agent '{task_def.agent}' not found, skipping task {tid}")
                    task_results[tid] = f"[Agent '{task_def.agent}' 不可用]"
                    continue
                dispatch_coros.append((tid, self.dispatch_single_task_to_agent(
                    task_def.description, agent_card, user_id, run_id, trace_id
                )))

            if dispatch_coros:
                results = await asyncio.gather(*[coro for _, coro in dispatch_coros], return_exceptions=True)
                for (tid, _), result in zip(dispatch_coros, results):
                    if isinstance(result, Exception):
                        task_results[tid] = f"[Error: {result}]"
                    else:
                        task_results[tid] = result
                    logger.info(f"Multi-root plan: task {tid} completed (len={len(task_results[tid])})")

            remaining -= set(ready)

        return await self._aggregate_multi_root_results(query, plan, task_results)

    async def _aggregate_multi_root_results(
        self, query: str, plan: MultiRootTaskPlan, task_results: dict[int, str]
    ) -> str:
        """Use LLM to aggregate results from multiple root agents into a coherent answer."""
        results_text = "\n\n".join([
            f"### 子任务 {t.id}: {t.description}\n**执行专家**: {t.agent}\n**结果**:\n{task_results.get(t.id, '[无结果]')}"
            for t in plan.tasks
        ])

        prompt_text = MULTI_ROOT_AGGREGATE_PROMPT.format(query=query, results=results_text)

        try:
            response = await self.planner_agent.llm.ainvoke([HumanMessage(content=prompt_text)])
            return response.content.strip()
        except Exception as e:
            logger.error(f"Multi-root aggregation failed: {e}")
            return f"各领域专家的回答:\n\n{results_text}"

    # ==================== End Broadcast Routing Methods ====================

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
        temperature: float = 0.01,
        data_services_url: str = None,
        max_retries: int = 1,
        retry_delay: float = 1.0,
    ):
        self.agent = RoutingAgent(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=stream,
            temperature=temperature,
            data_services_url=data_services_url
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay

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

        # Determine routing mode: "broadcast" (default, new) or "vector" (legacy)
        routing_mode = os.getenv("ROUTING_MODE", "broadcast").strip().lower()
        logger.info(f"===== RoutingAgentExecutor, routing_mode={routing_mode}")

        step = None
        multi_plan = None

        if routing_mode == "broadcast":
            # ---- Broadcast Mode: ask ALL agents, supports single-root fast path + multi-root task plan ----
            logger.info("===== RoutingAgentExecutor, using BROADCAST routing mode")
            for attempt in range(self.max_retries):
                step, multi_plan, _ = await self.agent.get_plan_by_broadcast(query, user_id, run_id, trace_id)
                logger.info(f"===== RoutingAgentExecutor (broadcast), attempt {attempt + 1}, step={step}, multi_plan tasks={len(multi_plan.tasks) if multi_plan else 0}")

                if multi_plan and multi_plan.tasks:
                    break
                if step is not None and step.agent and step.agent != "":
                    break

                if attempt < self.max_retries - 1:
                    logger.warning(f"===== Broadcast routing: no capable agent found, retrying ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

            # Multi-root path: dispatch sub-tasks, aggregate, and return
            if multi_plan and multi_plan.tasks:
                logger.info(f"===== RoutingAgentExecutor: MULTI-ROOT plan with {len(multi_plan.tasks)} sub-tasks")
                aggregated = await self.agent.execute_multi_root_plan(
                    query, multi_plan, user_id, run_id, trace_id
                )
                part = TextPart(text=aggregated)
                await updater.add_artifact(
                    [part],
                    name=f'{self.agent.agent_name}-result',
                )
                await updater.complete(
                    message=new_agent_text_message("", context_id=task.context_id)
                )
                return
        else:
            # ---- Vector Mode (default): vector search + LLM planner ----
            logger.info("===== RoutingAgentExecutor, using VECTOR routing mode")
            for attempt in range(self.max_retries):
                step = await self.agent.get_plan(query, user_id, run_id, trace_id)
                logger.info(f"===== RoutingAgentExecutor, attempt {attempt + 1}, step is {step}.")
                
                if step is not None and step.agent and step.agent != "":
                    break
                    
                if attempt < self.max_retries - 1:
                    logger.warning(f"===== Empty step or agent, retrying ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

        # if plan step can not find any agent, then use default agent to handle user question.
        if step is None or (step is not None and (step.agent is None or step.agent == "")):
            logger.info("===== RoutingAgentExecutor, can not find any agent, will use default agentcard.")
            step = PlannerStep(original_query=query, agent="CommonAgent")

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
                logger.info("===== RoutingAgentExecutor, Not found agents, will use default agentcard.")
                agent_card = self.agent.default_agentcard()

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
        logger.info(
            "Runtime build info: hostname=%s, pod_name=%s, app_version=%s, image=%s, image_tag=%s, git_sha=%s",
            os.getenv("HOSTNAME", "unknown"),
            os.getenv("POD_NAME", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
        )

        #dataservices
        data_services_url = os.getenv('DataServicesURL',"http://data-services.dac.svc.cluster.local:8000")
        
        max_retries = int(os.getenv('max_retries','1'))

        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)
        request_handler = DefaultRequestHandler(
            agent_executor=RoutingAgentExecutor(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                data_services_url=data_services_url,
                max_retries = max_retries
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
