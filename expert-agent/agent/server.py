import json
import logging
import sys
from pathlib import Path
import click
import httpx
import uvicorn
import os
import atexit
import signal
from typing import Any, Dict, Literal, List, Optional, Union
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from typing_extensions import override
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from .redis_registry import RedisRegistry, HeartbeatService
from .expert_agent_semantic_domain import ExpertAgentExecutorSemanticDomain
from .expert_agent_semantic_group import ExpertAgentExecutorSemanticGroup
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=10101)
@click.option('--agent-card', 'agent_card', default='/app/agent_card/agent_card.json')
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
@click.option('--stream', 'stream', default=True, type=bool, help='Enable streaming mode to process step')
@click.option('--max-steps', 'max_steps',default=5, type=int, help='max steps to run')
def main(host, port, agent_card, redis_host, redis_port, redis_db, password, provider, api_key, base_url, model, temperature, heartbeat_interval, stream, max_steps):
    """Starts an Agent server."""
    try:
        if not agent_card:
            raise ValueError('Agent card is required')
        with Path.open(agent_card) as file:
            data = json.load(file)
        agent_card = AgentCard(**data)
        agent_host = os.getenv('Agent_Host',"192.168.xxx.xxx")
        agent_port = os.getenv('Agent_Port',"20002")
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

        data_source_type = os.getenv('DataSourceType',"SemanticGroup")
        logger.info(f"DataSourceType is: {data_source_type}")
        logger.info(
            "[VersionMarker][ExpertServer] build_marker=%s, app_version=%s, image_tag=%s, git_sha=%s, "
            "agent_registry_url=%s, agent_registry=%s, leaf_agent_registry=%s",
            os.getenv("BUILD_MARKER", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
            os.getenv("AgentRegistryURL", ""),
            os.getenv("AgentRegistry", ""),
            os.getenv("LeafAgentRegistry", ""),
        )

        #dataservices
        data_services_url = os.getenv('DataServicesURL',"http://data-services.dac.svc.cluster.local:8000")

        # Default: register agent to Redis. Set REGISTER_AGENT=false/0/no to skip registration.
        register_agent = (os.getenv("REGISTER_AGENT", "true").strip().lower() not in ("false", "0", "no"))
        if register_agent:
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
        else:
            logger.info("REGISTER_AGENT is disabled, agent will not register to Redis")


        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)

        request_handler = None

        if data_source_type == "SemanticDomain":

            dd_namespace = os.getenv('DD_NAMESPACE')
            logger.info(f"dd_namespace is: {dd_namespace}")

            data_descriptors_str = os.getenv('Data_Descriptor')
            data_descriptors = data_descriptors_str.split(",")
            logger.info(f"data_descriptors is: {data_descriptors}")

            descriptor_types_str = os.getenv('DescriptorTypes')
            descriptor_types = descriptor_types_str.split(";")
            logger.info(f"descriptor_types is: {descriptor_types}")
        
            request_handler = DefaultRequestHandler(
                agent_executor=ExpertAgentExecutorSemanticDomain(
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    stream=stream,
                    temperature=temperature,
                    data_descriptors=data_descriptors,
                    dd_namespace=dd_namespace,
                    descriptor_types=descriptor_types,
                    data_services_url=data_services_url,
                    max_steps=max_steps
                ),
                task_store=InMemoryTaskStore(),
                push_config_store=push_config_store,
                push_sender= push_sender
            )

        if data_source_type == "SemanticGroup":
            semantic_group_id = os.getenv('SemanticGroupID',"")
            logger.info(f"SemanticGroupID is: {semantic_group_id}")

            request_handler = DefaultRequestHandler(
                agent_executor=ExpertAgentExecutorSemanticGroup(
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    stream=stream,
                    temperature=temperature,
                    semantic_group_id=semantic_group_id,
                    data_services_url=data_services_url,
                    max_steps=max_steps
                ),
                task_store=InMemoryTaskStore(),
                push_config_store=push_config_store,
                push_sender= push_sender
            )

        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        logger.info(f'Starting server on {host}:{port}')
        logger.info(f'LLM Configuration: provider={provider}, model={model}, temperature={temperature}, stream={stream}')

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