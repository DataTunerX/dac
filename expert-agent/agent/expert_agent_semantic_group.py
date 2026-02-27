import json
import hashlib
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
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Tuple, Union
from uuid import uuid4
from pydantic import BaseModel, Field
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.types import MessageSendParams, SendStreamingMessageRequest
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from a2a.client import A2AClient
from typing_extensions import override
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .dataservices_client import DataServicesClient, SemanticDomainInfo, SemanticGroupInfo
from .agentregistry_client import AgentRegistryClient
from .schema import ROLE_TYPE, AgentState, Memory, Message
from .prompts import (  
    COMMON_NEXT_STEP_PROMPT_GROUP_ZH, 
    NEXT_STEP_PROMPT_ZH,
    REQUERY_PROMPT_ZH,
    OBSERVE_PROMPT_COMMON_ZH,
    NEXT_STEP_PROMPT_EN
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
        semantic_group_id:str = None,
        data_services_url: str = None,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None,
        resolve_intersection_mode: Optional[str] = None,
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
        self.semantic_group_id = semantic_group_id
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=False,
        )
        self.parent_registry_base_url = (
            os.getenv("AgentRegistryURL")
            or os.getenv("AgentRegistry")
            or "http://orchestrator-registry.dac.svc.cluster.local:8000"
        )
        self.leaf_registry_base_url = (
            os.getenv("LeafAgentRegistry")
            or os.getenv("AgentRegistryURL")
            or os.getenv("AgentRegistry")
            or "http://orchestrator-registry.dac.svc.cluster.local:8000"
        )
        logger.info(
            "[VersionMarker][ExpertSGInit] build_marker=%s, app_version=%s, image_tag=%s, git_sha=%s, "
            "parent_registry_base_url=%s, leaf_registry_base_url=%s, semantic_group_id=%s",
            os.getenv("BUILD_MARKER", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
            self.parent_registry_base_url,
            self.leaf_registry_base_url,
            semantic_group_id or "",
        )
        # Resolve intersection mode: "one" = pick one from intersection, "all" = use all in intersection.
        # Default from env SEMANTIC_GROUP_RESOLVE_INTERSECTION_MODE (one | all).
        self.resolve_intersection_mode = (
            resolve_intersection_mode
            or os.getenv("SEMANTIC_GROUP_RESOLVE_INTERSECTION_MODE", "all")
        ).strip().lower()
        if self.resolve_intersection_mode not in ("one", "all"):
            self.resolve_intersection_mode = "one"
        # Resolved (member_info, agent_card) for A2A calls; filled by resolve_agents_for_semantic_group()
        # member_info is SemanticDomainInfo for leaf groups, SemanticGroupInfo for parent groups.
        self.group_agent_cards: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]] = []
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
        exception_occurred = False
        try:
            yield
        except Exception as e:
            exception_occurred = True
            self.state = AgentState.ERROR
            raise e
        finally:
            if not exception_occurred:
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


    async def invoke_common(self, knowledge: str = "") -> LLMResult:
        """
        Invoke LLM for one step. knowledge: 背景知识，来自 get_knowledge()（如 A2A 拉取的领域知识），
        会填入 prompt 的「背景知识」部分；为空时表示无额外背景知识。
        """
        current_task = self.metadata.get('current_task', '')

        system_template = COMMON_NEXT_STEP_PROMPT_GROUP_ZH
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
        knowledge_for_prompt = knowledge.strip() if knowledge else "（无）"
        current_tasks_status_str = self.format_tasks_status(self.current_tasks_status.tasks if self.current_tasks_status else [])
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_task", "current_time", "knowledge"],
            partial_variables={"current_tasks_status": current_tasks_status_str, "terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="biz-expert-common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_task": self.query, "current_time": current_time, "knowledge": knowledge_for_prompt},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.debug(f" === ExpertAgent.invoke_common, answer = {answer}")

        data_dict = self.format_llm_output(answer)

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
            name="biz-expert-requery",
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
                "requery": "",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === ExpertAgent.invoke_requery , llm_result = {llm_result}")

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
            name="biz-expert-observe_common",
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

        data_dict = self.format_llm_output(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === ExpertAgent.observe_common , llm_result = {llm_result}")

        return llm_result

    def _agent_url_from_semantic_domain(self, dd_namespace: str, dd_name: str) -> str:
        """
        Build A2A agent URL from semantic domain's dd_namespace and dd_name (K8s internal).
        DAC Service 名称为 dac-<dac.Name>，与 execution-engine 约定一致。
        """
        service_name = f"dac-{dd_name}"
        return f"http://{service_name}.{dd_namespace}.svc.cluster.local:10100"

    def _get_member_name(self, sd: SemanticDomainInfo) -> Optional[str]:
        """
        Get agent name from semantic domain for matching with registry.
        Prefer name from agent_card (JSON), else dd_name, else semantic_domain_id.
        """
        if not sd:
            return None
        if sd.agent_card and isinstance(sd.agent_card, str):
            s = sd.agent_card.strip()
            if s:
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        n = data.get("name")
                        if n and isinstance(n, str):
                            return n.strip()
                except (json.JSONDecodeError, TypeError):
                    pass
        if sd.dd_name and isinstance(sd.dd_name, str):
            return sd.dd_name.strip()
        if sd.semantic_domain_id and isinstance(sd.semantic_domain_id, str):
            return sd.semantic_domain_id.strip()
        return None

    async def resolve_agents_for_semantic_group(self) -> None:
        """
        Load semantic group + member semantic domains (or child groups) from data services.
        For leaf groups: find intersection of SD members with registered agents.
        For non-leaf groups: find child group expert-agent instances in registry.
        """
        if not self.semantic_group_id:
            return
        self.group_agent_cards = []
        try:
            async with self.data_services_client.session_context() as client:
                result = await client.get_semantic_group_with_members(self.semantic_group_id)
            if not result:
                logger.info("get_semantic_group_with_members returned None for group_id=%s", self.semantic_group_id)
                return

            is_non_leaf = bool(result.child_groups)
            selected_registry = self.parent_registry_base_url if is_non_leaf else self.leaf_registry_base_url
            logger.info(
                "[RegistrySelect] semantic_group_id=%s, is_non_leaf=%s, selected_registry=%s",
                self.semantic_group_id,
                is_non_leaf,
                selected_registry,
            )
            registry_client = AgentRegistryClient(base_url=selected_registry)
            registered_cards = await registry_client.get_registered_agent_cards()
            registered_by_name: Dict[str, AgentCard] = {}
            for ac in registered_cards:
                n = (getattr(ac, "name", None) or "").strip()
                if n:
                    registered_by_name[n] = ac

            if result.child_groups:
                await self._resolve_child_group_agents(result.child_groups, registered_by_name)
                return

            if not result.members:
                logger.info("get_semantic_group_with_members returned no members for group_id=%s", self.semantic_group_id)
                return

            # --- Below is the existing leaf-group resolution logic (unchanged) ---
            logger.info("Semantic group has %s members; registry has %s agent(s) (by name): %s", len(result.members), len(registered_by_name), list(registered_by_name.keys()))
            # Intersection: (sd, agent_card) for each member that matches a registered agent.
            #
            # Two-pass matching to prevent prefix-fallback from stealing deterministic-hash agents:
            #   Pass 1: Exact match (Priority 1) + deterministic hash match (Priority 2)
            #           — locks in agents whose names are predictable from dd_namespace/dd_name
            #   Pass 2: Prefix fallback (Priority 3) for remaining unmatched members
            #           — handles old agents with random suffixes (e.g., created from UI)
            intersection: List[Tuple[SemanticDomainInfo, AgentCard]] = []
            assigned_reg_names: set = set()

            # Collect valid members with parsed attributes
            parsed_members: List[Tuple[int, SemanticDomainInfo, str, str, str, str]] = []
            for i, member in enumerate(result.members):
                if not member.semantic_domain:
                    continue
                sd = member.semantic_domain
                member_name = self._get_member_name(sd)
                ns, dd_name = (sd.dd_namespace or "").strip(), (sd.dd_name or "").strip()
                dt = (sd.descriptor_type or "").strip()
                logger.info("Group member [%s]: name=%s dd_namespace=%s dd_name=%s descriptor_type=%s", i + 1, member_name or "(none)", ns, dd_name, dt or "(none)")
                if not member_name:
                    logger.info("Skip group member: no name from sd_id=%s", sd.semantic_domain_id)
                    continue
                parsed_members.append((i, sd, member_name, ns, dd_name, dt))

            # Pass 1: exact match + deterministic hash match
            pass1_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                agent_card = registered_by_name.get(member_name)
                match_type = "exact"
                if agent_card:
                    assigned_reg_names.add(member_name)
                elif ns and dd_name:
                    dd_suffix = hashlib.sha256(f"{ns}/{dd_name}".encode()).hexdigest()[:8]
                    expected_name = f"{member_name}-dd-{dd_suffix}"
                    agent_card = registered_by_name.get(expected_name)
                    if agent_card:
                        match_type = "dd-hash"
                        assigned_reg_names.add(expected_name)
                        logger.info("Deterministic hash match: member name=%s dd=%s/%s -> registry agent name=%s", member_name, ns, dd_name, expected_name)
                if agent_card:
                    pass1_matched[idx] = (sd, agent_card, match_type)

            # Pass 1.5: description-based matching for members not matched in Pass 1.
            # When multiple members share the same base name (e.g., both from
            # agent_card JSON "name": "EcommerceTransactionAgent") but correspond
            # to different data descriptors, the description field — generated by
            # the data-sinker LLM for each data source — is typically unique and
            # preserved unchanged through DAC creation into the registered AgentCard.
            pass15_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            unmatched_after_pass1 = [
                (idx, sd, member_name, ns, dd_name, dt)
                for idx, sd, member_name, ns, dd_name, dt in parsed_members
                if idx not in pass1_matched
            ]
            if unmatched_after_pass1:
                for idx, sd, member_name, ns, dd_name, dt in unmatched_after_pass1:
                    sd_desc = self._get_agent_description(sd).lower()
                    if not sd_desc:
                        continue
                    suffix_pattern = f"{member_name}-dd-"
                    for reg_name, reg_card in registered_by_name.items():
                        if reg_name in assigned_reg_names:
                            continue
                        if not reg_name.startswith(suffix_pattern):
                            continue
                        reg_desc = (getattr(reg_card, "description", None) or "").strip().lower()
                        if reg_desc and reg_desc == sd_desc:
                            pass15_matched[idx] = (sd, reg_card, "description")
                            assigned_reg_names.add(reg_name)
                            logger.info("Description match: member dd_name=%s -> registry agent name=%s", dd_name, reg_name)
                            break

            # Pass 2: prefix fallback for members not matched in Pass 1 or Pass 1.5
            pass2_matched: Dict[int, Tuple[SemanticDomainInfo, AgentCard, str]] = {}
            # Detect base-name ambiguity for warning
            unmatched_base_names: Dict[str, int] = {}
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                if idx in pass1_matched or idx in pass15_matched:
                    continue
                unmatched_base_names[member_name] = unmatched_base_names.get(member_name, 0) + 1
            ambiguous_base_names = {n for n, c in unmatched_base_names.items() if c > 1}

            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                if idx in pass1_matched or idx in pass15_matched:
                    continue
                suffix_pattern = f"{member_name}-dd-"
                agent_card = None
                for reg_name, reg_card in registered_by_name.items():
                    if reg_name in assigned_reg_names:
                        continue
                    if reg_name.startswith(suffix_pattern):
                        agent_card = reg_card
                        assigned_reg_names.add(reg_name)
                        if member_name in ambiguous_base_names:
                            logger.warning(
                                "AMBIGUOUS prefix fallback: member dd_name=%s (base name=%s) has %d unmatched members with same base name. "
                                "Pairing with registry agent %s may be INCORRECT — consider updating agent_card in semantic domain to include full agent name.",
                                dd_name, member_name, unmatched_base_names[member_name], reg_name)
                        else:
                            logger.info("Prefix fallback match: member name=%s -> registry agent name=%s", member_name, reg_name)
                        break
                if agent_card:
                    pass2_matched[idx] = (sd, agent_card, "dd-prefix-fallback")
                else:
                    logger.info("Skip group member: name=%s not in registry (tried exact, dd-hash, description, prefix-fallback)", member_name)

            # Merge results in original member order
            for idx, sd, member_name, ns, dd_name, dt in parsed_members:
                entry = pass1_matched.get(idx) or pass15_matched.get(idx) or pass2_matched.get(idx)
                if entry:
                    sd_val, agent_card, match_type = entry
                    intersection.append((sd_val, agent_card))
                    logger.info("In intersection (%s match): member name=%s -> registry agent name=%s url=%s", match_type, member_name, getattr(agent_card, "name", ""), getattr(agent_card, "url", ""))
            # Branch: pick one or use all according to resolve_intersection_mode
            if intersection:
                if self.resolve_intersection_mode == "all":
                    # Deduplicate by agent URL so the same agent is not called multiple times
                    seen_urls: set = set()
                    deduped: List[Tuple[SemanticDomainInfo, AgentCard]] = []
                    for sd, ac in intersection:
                        url = (getattr(ac, "url", None) or "").strip().rstrip("/")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            deduped.append((sd, ac))
                        else:
                            logger.debug("Skip duplicate agent url in intersection (mode=all): %s", url or "(empty)")
                    self.group_agent_cards = deduped
                    logger.info("Using all from intersection (mode=all, %s unique agent(s) after dedup by URL): %s", len(self.group_agent_cards), "; ".join(getattr(ac, "url", "") or "" for _, ac in self.group_agent_cards))
                else:
                    self.group_agent_cards = [intersection[0]]
                    sd0, ac0 = intersection[0]
                    logger.info("Picked one from intersection (mode=one, %s total): name=%s url=%s", len(intersection), getattr(ac0, "name", ""), getattr(ac0, "url", ""))
            else:
                logger.info("Resolved 0 of %s group members (no name match with registry).", len(result.members))
        except Exception as e:
            logger.error("resolve_agents_for_semantic_group failed: %s", e)

    async def _resolve_child_group_agents(
        self,
        child_groups: List[SemanticGroupInfo],
        registered_by_name: Dict[str, "AgentCard"],
    ) -> None:
        """
        For non-leaf groups: resolve child group expert-agent SG instances in the registry.
        Each child group has its own DAC/Pod registered as an agent with a name pattern:
        {baseName}-sg-{suffix}. We match using the agent_card JSON name from the child group.
        """
        logger.info("Resolving %d child group(s) as composite agents", len(child_groups))
        for child in child_groups:
            child_name = self._get_child_group_agent_name(child)
            if not child_name:
                logger.info("Skip child group %s: no agent name", child.id)
                continue

            agent_card = None
            sg_prefix = f"{child_name}-sg-"

            if child_name in registered_by_name:
                agent_card = registered_by_name[child_name]
            else:
                for reg_name, reg_card in registered_by_name.items():
                    if reg_name.startswith(sg_prefix):
                        agent_card = reg_card
                        logger.info("Child group '%s' matched registry agent '%s' by -sg- prefix",
                                    child_name, reg_name)
                        break

            if agent_card:
                self.group_agent_cards.append((child, agent_card))
                logger.info("Resolved child group '%s' -> agent '%s' (url=%s)",
                            child.group_name,
                            getattr(agent_card, 'name', ''),
                            getattr(agent_card, 'url', ''))
            else:
                logger.warning("Child group '%s' (name=%s) not found in registry",
                               child.group_name, child_name)

        logger.info("Resolved %d child group agent(s)", len(self.group_agent_cards))

    @staticmethod
    def _get_child_group_agent_name(child) -> str:
        """Extract the agent name from a SemanticGroupInfo's agent_card JSON."""
        agent_card_str = getattr(child, 'agent_card', None) or ""
        if agent_card_str and isinstance(agent_card_str, str):
            try:
                data = json.loads(agent_card_str.strip())
                if isinstance(data, dict):
                    name = data.get("name", "")
                    if name and isinstance(name, str):
                        return name.strip()
            except (json.JSONDecodeError, TypeError):
                pass
        return getattr(child, 'group_name', '') or ""

    def _get_response_text_from_chunk(self, chunk: Any) -> str:
        """
        Extract artifact text from A2A streaming chunk (artifact-update).
        Matches orchestrator-agent and routing-agent: result.kind == 'artifact-update', artifact.parts[0].text.
        """
        data = chunk.model_dump(mode='json', exclude_none=True) if hasattr(chunk, 'model_dump') else (chunk if isinstance(chunk, dict) else {})
        result = data.get('result')
        if result is None or result.get('kind') != 'artifact-update':
            return ""
        artifact = result.get('artifact')
        if not artifact:
            return ""
        parts = artifact.get('parts')
        if not parts or len(parts) == 0 or not isinstance(parts[0], dict):
            return ""
        text = parts[0].get('text')
        return text if text else ""

    async def _fetch_knowledge_from_agent(
        self,
        httpx_client: httpx.AsyncClient,
        send_message_payload: Dict[str, Any],
        sd: SemanticDomainInfo,
        agent_card: AgentCard,
    ) -> Tuple[SemanticDomainInfo, str]:
        """
        Call one domain agent via A2A and return (sd, aggregated_text). On error returns (sd, "").
        """
        try:
            client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
            streaming_request = SendStreamingMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(**send_message_payload),
            )
            stream_response = client.send_message_streaming(streaming_request)
            agent_texts: List[str] = []
            async for chunk in stream_response:
                result = self._get_response_text_from_chunk(chunk)
                if result != "":
                    agent_texts.append(result)
            text = " ".join(agent_texts) if agent_texts else ""
            return (sd, text)
        except Exception as e:
            logger.warning("A2A call failed for agent %s: %s", getattr(agent_card, 'url', ''), e)
            return (sd, "")

    def _get_agent_description(self, sd: SemanticDomainInfo) -> str:
        """从 agent_card JSON 中提取 agent 的 description 字段。"""
        if sd.agent_card and isinstance(sd.agent_card, str):
            s = sd.agent_card.strip()
            if s:
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        desc = data.get("description", "")
                        if desc and isinstance(desc, str):
                            return desc.strip()
                except (json.JSONDecodeError, TypeError):
                    pass
        return ""

    # descriptor_type 对应的角色说明：以 semantic domain 的 descriptor_type 为权威来源，
    # 明确每个 agent 适合干什么。AgentCard.description 通常不会说明这些，因此 planner 必须依赖此映射。
    _DESCRIPTOR_TYPE_ROLE: Dict[str, str] = {
        "code": "Retrieves and analyzes source code from code repositories. Contains business logic, data models, "
                "field mappings, and table relationships. Provides foundational context for structured agents. Run in earlier phases.",
        "unstructured": "Retrieves and analyzes unstructured documents (API docs, design docs, manuals). Provides foundational context. Run in earlier phases.",
        "structured": "Queries structured data (SQL, ChatBI, data analysis, charts). Often benefits from code/document context. Run in later phases.",
        "group": "A composite child group agent that encapsulates an entire sub-domain. It has its own internal agents "
                 "and planning. Treat it as a black-box expert for its domain. Include if the user query overlaps with "
                 "its domain description. Can run in any phase; no context_from is typically needed.",
    }

    def _get_role_by_descriptor_type(self, member: Union[SemanticDomainInfo, SemanticGroupInfo]) -> str:
        """
        根据 member 的 descriptor_type 明确 agent 角色。
        member 可以是 SemanticDomainInfo（叶子组成员）或 SemanticGroupInfo（子组）。
        AgentCard 不会具体说明 agent 是擅长代码分析等，因此 planner 必须以 descriptor_type 为权威来源。
        structured-xxx（如 structured-mysql）归为 structured 角色。
        """
        dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or ""
        if dt in self._DESCRIPTOR_TYPE_ROLE:
            return self._DESCRIPTOR_TYPE_ROLE[dt]
        if dt.startswith("structured-"):
            return self._DESCRIPTOR_TYPE_ROLE["structured"]
        if "unstructured" in dt:
            return self._DESCRIPTOR_TYPE_ROLE["unstructured"]
        return f"Capability: {dt or 'unknown'}. Role not predefined."

    def _build_name_to_agent_map(self) -> Dict[str, Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
        """构建 agent_name -> (member_info, AgentCard) 的映射。"""
        name_to_agent: Dict[str, Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]] = {}
        for sd, ac in self.group_agent_cards:
            agent_name = getattr(ac, "name", "") or ""
            if agent_name:
                name_to_agent[agent_name] = (sd, ac)
        return name_to_agent

    @staticmethod
    def _agent_display_name(full_name: str, name_to_agent: Dict[str, Tuple[Union["SemanticDomainInfo", "SemanticGroupInfo"], "AgentCard"]]) -> str:
        """Return a human-readable label: BaseName(ns/dd_name:type) or BaseName(group:name) for logging."""
        short = full_name.split("-dd-")[0] if "-dd-" in full_name else full_name
        entry = name_to_agent.get(full_name)
        if not entry:
            return short
        member = entry[0]
        dt = (getattr(member, 'descriptor_type', '') or "").strip()
        if dt == "group":
            gname = (getattr(member, 'group_name', '') or "").strip()
            return f"{short}(group:{gname})" if gname else f"{short}(group)"
        ns = (getattr(member, 'dd_namespace', '') or "").strip()
        dd = (getattr(member, 'dd_name', '') or "").strip()
        return f"{short}({ns}/{dd}:{dt})" if ns and dd else short

    async def _plan_execution_order(self) -> List[Dict[str, Any]]:
        """
        使用 LLM 分析所有 agent 的能力描述，动态决定执行顺序和上下文传递关系。

        返回执行计划列表，每个元素代表一个执行阶段：
        [
            {"phase": 1, "agents": ["CodeAgent", "DocAgent"], "context_from": []},
            {"phase": 2, "agents": ["ChatBIAgent"], "context_from": ["CodeAgent", "DocAgent"]}
        ]

        如果 LLM 调用失败或返回无效 JSON，回退到默认策略：所有 agent 在 Phase 1 并行执行。
        """
        all_names = [getattr(ac, "name", "") or "(unknown)" for _, ac in self.group_agent_cards]
        fallback_plan = [{"phase": 1, "agents": all_names, "context_from": []}]

        # 只有 1 个 agent 时无需 LLM 规划
        if len(self.group_agent_cards) <= 1:
            logger.info("[ExecutionPlanner] Only %d agent(s), skip LLM planning", len(self.group_agent_cards))
            return fallback_plan

        # 收集每个 agent 的元数据。以 descriptor_type 为权威来源明确每个 agent 适合干什么，
        # AgentCard.description 通常不会说明这些，故不依赖。
        agent_info_lines: List[str] = []
        for i, (member, ac) in enumerate(self.group_agent_cards, 1):
            agent_name = getattr(ac, "name", "") or "(unknown)"
            dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or "unknown"
            role = self._get_role_by_descriptor_type(member)
            agent_info_lines.append(
                f"{i}. Name: {agent_name}\n"
                f"   descriptor_type: {dt}\n"
                f"   Suitable for: {role}"
            )

        agent_list_str = "\n\n".join(agent_info_lines)

        system_prompt = (
            "You are an intelligent orchestrator that plans the execution order of multiple AI agents.\n"
            "Each agent's role is defined by its descriptor_type (from semantic domain). Use this as the authoritative source.\n\n"
            "descriptor_type reference:\n"
            "- code: Retrieves/analyzes source code from repositories. Contains business logic, field mappings, "
            "validation rules, data models, and table relationships that are NOT in the database schema. "
            "Useful when: (1) user wants to see code/implementation, OR (2) a structured agent also exists and "
            "the code context can help it generate more accurate SQL (business logic lives in code, not in DB).\n"
            "- unstructured: Retrieves/analyzes documents (API docs, design docs, manuals). "
            "ONLY useful when the user wants to look up documentation or specifications.\n"
            "- structured (including structured-mysql, structured-postgres, etc.): Queries databases, generates SQL, "
            "data analysis, charts. ONLY useful when the user wants to query actual data, get statistics, or generate reports.\n"
            "- group: A composite child-group agent that encapsulates an entire sub-domain with its own internal agents. "
            "Treat it as a black-box domain expert. INCLUDE if the user query overlaps with its domain description. "
            "It runs independently — no context_from is typically needed unless multiple group agents produce "
            "complementary results.\n\n"
            "You MUST think step by step (Chain-of-Thought) and write your reasoning into the \"reasoning\" field.\n\n"
            "## Thinking Steps (write into the \"reasoning\" field)\n\n"
            "Step 1 — Extract Intent: What is the user's core intent? Strip away filler words and identify "
            "the key action (query data? view code? read docs? mixed?).\n\n"
            "Step 2 — Match Capabilities: For each available agent, does its descriptor_type match the intent? "
            "Write out your judgment for EVERY agent (include or exclude, with a brief reason).\n\n"
            "Step 3 — Apply Co-existence Rule: If BOTH code and structured agents exist:\n"
            "  - If the query involves data querying (SQL, statistics, reports, data analysis), "
            "INCLUDE BOTH: code agent in Phase 1 (provides business logic context), "
            "structured agent in Phase 2 with context_from code agent (generates more accurate SQL). "
            "Business logic (soft-delete flags, status filters, computed fields, table joins) lives in code, not in DB schema.\n"
            "  - If the query is ONLY about code/implementation with NO data query intent, EXCLUDE structured agent.\n"
            "  - Only EXCLUDE code agent from a data query if NO structured agent exists in the group.\n\n"
            "Step 4 — Determine Exclusions:\n"
            "  - API docs/parameters/error codes → EXCLUDE structured agents\n"
            "  - Deployment/installation manuals → EXCLUDE code and structured agents\n"
            "  - Pure code questions (no data intent) → EXCLUDE structured agents\n"
            "  - The query spans multiple domains (e.g., \"check the code AND query the data\") → INCLUDE all relevant\n"
            "  - The query is genuinely ambiguous → INCLUDE rather than exclude\n\n"
            "Step 5 — Plan Phases: For included agents, determine execution order:\n"
            "  - Foundational context providers (code, documents) → earlier phases\n"
            "  - Context consumers (SQL generation, data analysis) → later phases with context_from\n"
            "  - Independent agents within the same phase run in parallel\n"
            "  - context_from must only reference agents from earlier phases\n\n"
            "## Output Format\n"
            "Output ONLY a valid JSON object (no markdown, no explanation, no extra text):\n"
            "{\n"
            '  "reasoning": "Step 1: [intent analysis]. Step 2: [per-agent judgment]. '
            'Step 3: [co-existence check]. Step 4: [exclusion decisions]. Step 5: [phase planning].",\n'
            '  "execution_plan": [\n'
            '    {"phase": 1, "agents": ["AgentNameA", "AgentNameB"], "context_from": []},\n'
            '    {"phase": 2, "agents": ["AgentNameC"], "context_from": ["AgentNameA"]}\n'
            "  ],\n"
            '  "excluded_agents": [\n'
            '    {"name": "AgentNameD", "reason": "User query is about API parameters; database querying is not needed"}\n'
            "  ]\n"
            "}\n\n"
            "Important:\n"
            "- The \"reasoning\" field MUST contain your step-by-step thinking following all 5 steps. Do NOT skip it.\n"
            "- Every agent MUST appear either in execution_plan or in excluded_agents, not both.\n"
            "- excluded_agents can be an empty list if all agents are relevant.\n"
            "- Only keep excluded_agents empty when the query genuinely needs ALL agent types.\n"
            "- Including unnecessary agents wastes resources and slows down response time. Be precise."
        )

        human_content = f"User Query: {self.query}\n\nAvailable Agents:\n{agent_list_str}"

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content),
            ]
            logger.info("[ExecutionPlanner] LLM 规划开始 | agent 数: %d", len(self.group_agent_cards))
            response = await asyncio.wait_for(self.llm.ainvoke(messages), timeout=30.0)
            raw_text = response.content if hasattr(response, 'content') else str(response)
            logger.debug("[ExecutionPlanner] LLM raw response: %s", raw_text[:1000])

            # 复用 format_llm_output 进行 JSON 提取和清洗（处理 markdown 代码块、引号等问题）
            plan_data = self.format_llm_output(response)
            if not plan_data or not isinstance(plan_data, dict):
                logger.warning("[ExecutionPlanner] format_llm_output 返回无效，使用 fallback")
                return fallback_plan

            reasoning = plan_data.get("reasoning", "")
            self._last_planning_reasoning = reasoning
            if reasoning:
                logger.info("[ExecutionPlanner] LLM reasoning: %s", reasoning)

            execution_plan = plan_data.get("execution_plan", [])

            if not isinstance(execution_plan, list) or len(execution_plan) == 0:
                logger.warning("[ExecutionPlanner] execution_plan 为空或无效，使用 fallback")
                return fallback_plan

            # 解析 excluded_agents：LLM 判定与用户问题不相关的 agent
            excluded_agents_raw = plan_data.get("excluded_agents", [])
            excluded_names: set = set()
            excluded_reasons: Dict[str, str] = {}
            if isinstance(excluded_agents_raw, list):
                for item in excluded_agents_raw:
                    if isinstance(item, dict):
                        name = (item.get("name") or "").strip()
                        reason = (item.get("reason") or "").strip()
                        if name:
                            excluded_names.add(name)
                            excluded_reasons[name] = reason

            # 验证计划：区分"被排除"和"被遗漏"的 agent
            planned_names: set = set()
            for phase_info in execution_plan:
                for name in phase_info.get("agents", []):
                    planned_names.add(name)

            all_names_set = set(all_names)
            not_in_plan = all_names_set - planned_names
            truly_missing = not_in_plan - excluded_names
            if truly_missing:
                logger.warning("[ExecutionPlanner] 计划遗漏 agent（非排除）: %s，已补入 Phase 1", truly_missing)
                phase1_found = False
                for phase_info in execution_plan:
                    if phase_info.get("phase") == 1:
                        phase_info["agents"].extend(list(truly_missing))
                        phase1_found = True
                        break
                if not phase1_found:
                    execution_plan.insert(0, {"phase": 0, "agents": list(truly_missing), "context_from": []})

            # 按 phase 排序
            execution_plan.sort(key=lambda x: x.get("phase", 1))

            # 输出直观的执行计划（包含 dd 信息以区分同名 agent）
            _nta = self._build_name_to_agent_map()
            plan_lines = ["[ExecutionPlanner] 执行计划:"]
            for phase_info in execution_plan:
                p = phase_info.get("phase", 0)
                agents = phase_info.get("agents", [])
                ctx = phase_info.get("context_from", [])
                agents_display = [self._agent_display_name(a, _nta) for a in agents]
                if ctx:
                    ctx_display = [self._agent_display_name(c, _nta) for c in ctx]
                    plan_lines.append(f"  Phase {p}: {', '.join(agents_display)} (上下文来自: {', '.join(ctx_display)})")
                else:
                    plan_lines.append(f"  Phase {p}: {', '.join(agents_display)}")
            if excluded_names:
                plan_lines.append("  排除的 agent:")
                for name in excluded_names:
                    display = self._agent_display_name(name, _nta)
                    reason = excluded_reasons.get(name, "(未提供原因)")
                    plan_lines.append(f"    - {display}: {reason}")
            logger.info("\n".join(plan_lines))

            return execution_plan

        except Exception as e:
            logger.warning("[ExecutionPlanner] LLM 规划失败: %s，使用 fallback (全部 Phase 1 并行)", e)
            return fallback_plan

    def _build_send_message_payload(self, query_text: str, extra_context: str = "") -> Dict[str, Any]:
        """构建 A2A 发送消息的 payload。extra_context 通过 metadata 传递，不污染 query。"""
        metadata: Dict[str, Any] = {
            'user_id': self.metadata.get('user_id', ''),
            'agent_id': self.metadata.get('agent_id', ''),
            'run_id': self.metadata.get('run_id', ''),
            'trace_id': self.metadata.get('trace_id', ''),
            'answer_model': 'original',
        }
        if extra_context:
            metadata['extra_context'] = extra_context
        return {
            'message': {
                'role': 'user',
                'parts': [{'type': 'text', 'text': query_text}],
                'messageId': uuid4().hex,
            },
            'metadata': metadata,
        }

    def _format_agent_results(
        self,
        agents: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]],
        results: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], str]],
        start_idx: int = 1,
    ) -> List[str]:
        """
        将 agent 返回的结果格式化为结构化的知识块列表，并打印日志。
        返回 knowledge_parts 列表。
        """
        knowledge_parts: List[str] = []
        for i, ((member, agent_card), (_, text)) in enumerate(zip(agents, results)):
            idx = start_idx + i
            agent_name = getattr(agent_card, "name", "") or "(no name)"
            agent_short = agent_name.split("-dd-")[0] if "-dd-" in agent_name else agent_name
            dt = (getattr(member, 'descriptor_type', '') or "").strip().lower() or "(unknown)"
            if dt == "group":
                member_label = f"group/{getattr(member, 'group_name', '') or 'unknown'}"
            else:
                ns = getattr(member, 'dd_namespace', '') or ''
                dd = getattr(member, 'dd_name', '') or getattr(member, 'semantic_domain_id', '') or 'sd'
                member_label = f"{ns}/{dd}"
            char_len = len(text) if text else 0
            preview = (text[:120] + "..." if len(text) > 120 else text) if text else "(空)"
            preview = preview.replace("\n", " ").strip()

            logger.info("[知识块 %s] %s (%s) | %d 字符 | %s", idx, agent_short, member_label, char_len, preview)

            if text:
                block = (
                    f"【智能体 {idx}】\n"
                    f"名称: {agent_name}\n"
                    f"领域: {member_label}\n"
                    f"类型: {dt}\n"
                    f"知识/回答:\n{text}"
                )
                knowledge_parts.append(block)
        return knowledge_parts

    async def get_knowledge(self) -> str:
        """
        If this agent is bound to a semantic group, call all resolved domain agents via A2A.

        执行策略（LLM 驱动的动态分阶段执行）：
        1. 调用 LLM 分析所有 agent 的能力，生成执行计划（哪些 agent 先执行、哪些后执行、
           后执行的 agent 需要哪些先执行 agent 的结果作为上下文）
        2. 按阶段顺序执行：同阶段内的 agent 并行执行
        3. 后续阶段的 agent 根据计划中的 context_from 选择性地接收先前 agent 的结果

        如果 LLM 规划失败，回退到所有 agent 并行执行、不传递上下文的安全默认策略。
        """
        if not self.group_agent_cards:
            return ""

        query = self.query
        name_to_agent = self._build_name_to_agent_map()

        logger.info("[SemanticGroup] get_knowledge 开始 | 组内 agent 数: %d", len(self.group_agent_cards))

        # ===== Step 1: LLM 驱动的执行规划 =====
        execution_plan = await self._plan_execution_order()

        # ===== Step 2: 按阶段执行 =====
        logger.info("[SemanticGroup] 按计划执行，共 %d 阶段", len(execution_plan))
        all_knowledge_parts: List[str] = []
        # 存储每个 agent 的格式化结果（与 _format_agent_results 输出的 block 一致），
        # 供后续阶段的 context_from 选择性传递使用
        agent_results_by_name: Dict[str, str] = {}
        global_idx = 1

        # 复用同一个 httpx.AsyncClient，避免每个阶段重复创建/销毁连接
        async with httpx.AsyncClient(timeout=120.0) as httpx_client:
            for phase_info in execution_plan:
                phase_num = phase_info.get("phase", 1)
                phase_agent_names = phase_info.get("agents", [])
                context_from_names = phase_info.get("context_from", [])

                agents_display = [self._agent_display_name(a, name_to_agent) for a in phase_agent_names]
                ctx_display = [self._agent_display_name(c, name_to_agent) for c in context_from_names] if context_from_names else []
                if ctx_display:
                    logger.info("[Phase %s] 执行: %s | 上下文来自: %s", phase_num, ", ".join(agents_display), ", ".join(ctx_display))
                else:
                    logger.info("[Phase %s] 执行: %s", phase_num, ", ".join(agents_display))

                # 解析本阶段需要执行的 agent
                phase_agents: List[Tuple[SemanticDomainInfo, AgentCard]] = []
                for name in phase_agent_names:
                    if name in name_to_agent:
                        phase_agents.append(name_to_agent[name])
                    else:
                        logger.warning("[Phase %s] Agent '%s' from execution plan not found in name_to_agent map, skipping", phase_num, name)

                if not phase_agents:
                    logger.info("[Phase %s] No valid agents to execute, skipping", phase_num)
                    continue

                # 构建 extra_context：选择性附加先前 agent 的结果，通过 metadata 传递
                context_parts: List[str] = []
                for ctx_name in context_from_names:
                    if ctx_name in agent_results_by_name and agent_results_by_name[ctx_name]:
                        context_parts.append(agent_results_by_name[ctx_name])
                    else:
                        # fallback: LLM 可能返回简称，按 -dd- 前缀匹配
                        for k in agent_results_by_name:
                            if k.startswith(ctx_name + "-dd-"):
                                context_parts.append(agent_results_by_name[k])
                                break

                extra_context = ""
                if context_parts:
                    extra_context = "\n\n".join(context_parts)
                    ctx_summary = ", ".join(
                        f"{self._agent_display_name(n, name_to_agent)}({len(c)}字)"
                        for n, c in zip(context_from_names, context_parts)
                    )
                    logger.info("[Phase %s] extra_context: %d 字 | 来源: %s", phase_num, len(extra_context), ctx_summary)
                    _preview = extra_context[:400].replace("\n", " ").strip() + ("..." if len(extra_context) > 400 else "")
                    logger.info("[Phase %s] extra_context 预览: %s", phase_num, _preview)
                elif context_from_names:
                    logger.info("[Phase %s] context_from 未找到有效结果，不传递 extra_context", phase_num)

                # query 保持原始用户问题，extra_context 通过 metadata 传递
                payload = self._build_send_message_payload(query, extra_context=extra_context)

                tasks = [
                    self._fetch_knowledge_from_agent(httpx_client, payload, sd, ac)
                    for sd, ac in phase_agents
                ]
                results: List[Tuple[SemanticDomainInfo, str]] = await asyncio.gather(*tasks, return_exceptions=False)

                # 格式化结果并存储
                parts = self._format_agent_results(phase_agents, results, start_idx=global_idx)
                all_knowledge_parts.extend(parts)

                # 将格式化后的知识块存入 agent_results_by_name，供后续阶段 context_from 使用
                part_idx = 0
                for (sd, ac), (_, text) in zip(phase_agents, results):
                    agent_name = getattr(ac, "name", "") or "(unknown)"
                    if text and part_idx < len(parts):
                        agent_results_by_name[agent_name] = parts[part_idx]
                        part_idx += 1

                ok_count = sum(1 for (_, t) in results if t)
                logger.info("[Phase %s] 完成: %d/%d 有内容", phase_num, ok_count, len(results))
                global_idx += len(phase_agents)

        logger.info("[SemanticGroup] get_knowledge 完成 | 总知识块数: %d", len(all_knowledge_parts))
        return "\n\n".join(all_knowledge_parts) if all_knowledge_parts else ""

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

        try:
            knowledge = await self.get_knowledge()
            return knowledge
        except Exception as e:
            logger.error(f"step error : {e}")
            return f"No relevant knowledge available to answer the question: {self.original_query}"

    async def step_old(self) -> str:
        """Execute a single step with streaming support."""

        try:
            knowledge = await self.get_knowledge()
            llm_result = await self.invoke_common(knowledge=knowledge)
            if llm_result:
                if hasattr(llm_result, 'conclusion') and llm_result.conclusion == "terminate":
                    current_tasks_status_str = self.format_tasks_status(self.current_tasks_status.tasks if self.current_tasks_status else [])
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
        except Exception as e:
            # If any issues are encountered during execution, regenerate the question and proceed to the next step loop, including SQL execution errors and re-querying.
            logger.error(f"step error : {e}")
            self.state = AgentState.IDLE
            self.save_step_status(self.query, f"step error : {e}")
            requery = await self.invoke_requery()
            if requery.conclusion == "terminate" and requery.requery:
                self.query = requery.requery
                self._update_task_description(requery.requery)
            return f"No relevant knowledge available to answer the question: {self.original_query}, will try a different question!"

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

        # 在 orchestrate.py 文件的第 613-631 行：
        # send_message_payload: dict[str, Any] = {
        #     'message': {
        #         'role': 'user',
        #         'parts': [
        #             {'type': 'text', 'text': query}
        #         ],
        #         'messageId': uuid4().hex,
        #     },
        #     'metadata': {
        #         'user_id': self.metadata['user_id'],
        #         'agent_id': self.metadata['agent_id'],
        #         'run_id': self.metadata['run_id'],
        #         'trace_id': self.metadata['trace_id'],
        #         'memory': memory,
        #         'current_tasks_status': current_tasks_status,
        #         'current_task': f"current task id: [{task_id}], task description: {query} ",
        #         'current_task_id': f"{task_id}",
        #     },
        # }


        logger.debug(f"************** agent run, query: {self.query} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if self.query:
            self.update_memory("user", self.query)

        # Resolve semantic group members -> agent registry for A2A (get_knowledge will use group_agent_cards)
        if self.semantic_group_id:
            await self.resolve_agents_for_semantic_group()

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
                
                step_result = f"{step_result_str}\n\nanswer:\n{step_result}\n"

                yield step_result

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class ExpertAgentExecutorSemanticGroup(AgentExecutor):
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
        semantic_group_id:str = None,
        data_services_url: str = None,
        max_steps:int = 5

    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.semantic_group_id=semantic_group_id
        self.data_services_url=data_services_url
        self.stream_enabled = stream
        self.max_steps = max_steps

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()

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
            semantic_group_id=self.semantic_group_id,
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

        try:
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
        finally:
            await agent.data_services_client.close()

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')