import json
import logging
import sys
from pathlib import Path
import click
import httpx
import uvicorn
import os
import threading
import time
from typing import Any, AsyncIterable, Dict, Literal, List, Optional, Union
from pydantic import BaseModel, Field
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from typing_extensions import override
from a2a.types import (
    AgentCard,
    AgentExtension,
    AgentSkill,
)
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from .redis_registry import RedisRegistry, HeartbeatService
import atexit
import signal
from .orchestrator_agent_semantic_domain import OrchestratorAgentExecutorSemanticDomain
from .orchestrator_agent_semantic_group import OrchestratorAgentExecutorSemanticGroup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

AgentRegistry = os.getenv("AgentRegistry", "expert-registry.dac.svc.cluster.local::10100")


def _check_semantic_group_root_status(
    data_source_type: str,
    semantic_group_id: str,
    data_services_url: str,
    timeout: float = 10.0,
) -> tuple[Optional[bool], Optional[str], str]:
    """Return root status for semantic group.

    Returns:
        (is_root, parent_id, reason)
        - is_root=True/False when check is conclusive
        - is_root=None when check is unknown/failed
    """
    if data_source_type != "SemanticGroup":
        return True, None, "not_semantic_group_mode"
    if not semantic_group_id:
        return None, None, "missing_semantic_group_id"
    try:
        check_url = f"{data_services_url}/semantic_groups/{semantic_group_id}"
        resp = httpx.get(check_url, timeout=timeout)
        if resp.status_code == 200:
            group_data = resp.json().get("data", {})
            parent_id = group_data.get("parent_id")
            return parent_id is None, parent_id, "ok"
        return None, None, f"http_{resp.status_code}"
    except Exception as e:
        return None, None, f"exception:{e}"


class RootMembershipReconciler(threading.Thread):
    """Periodic root-membership reconciler for orchestrator registration."""

    def __init__(
        self,
        *,
        data_source_type: str,
        semantic_group_id: str,
        data_services_url: str,
        root_check_fail_policy: str,
        auto_promote_root: bool,
        register_agent_enabled: bool,
        agent_card: AgentCard,
        heartbeat_service: Optional[HeartbeatService],
        interval_sec: int = 30,
        check_timeout: float = 10.0,
        summary_every: int = 0,
    ):
        super().__init__(daemon=True)
        self.data_source_type = data_source_type
        self.semantic_group_id = semantic_group_id
        self.data_services_url = data_services_url
        self.root_check_fail_policy = root_check_fail_policy
        self.auto_promote_root = auto_promote_root
        self.register_agent_enabled = register_agent_enabled
        self.agent_card = agent_card
        self.heartbeat_service = heartbeat_service
        self.interval_sec = interval_sec
        self.check_timeout = check_timeout
        self.summary_every = summary_every
        self._running = False
        self._is_registered = False
        self._last_status_sig: Optional[tuple[Optional[bool], Optional[str], bool]] = None
        self._check_count = 0

    def set_registered_state(self, value: bool):
        self._is_registered = value

    def stop(self):
        self._running = False

    def _register(self):
        if not self.heartbeat_service:
            return
        if self.heartbeat_service.register_agent(self.agent_card):
            self._is_registered = True
            logger.info(
                "[RootReconcile] Registered agent because group is root. group_id=%s, agent=%s",
                self.semantic_group_id, self.agent_card.name
            )
        else:
            logger.error(
                "[RootReconcile] Failed to register agent. group_id=%s, agent=%s",
                self.semantic_group_id, self.agent_card.name
            )

    def _unregister(self, reason: str):
        if not self.heartbeat_service:
            return
        self.heartbeat_service.unregister_agent(self.agent_card.url)
        self._is_registered = False
        logger.warning(
            "[RootReconcile] Unregistered agent. reason=%s, group_id=%s, agent=%s",
            reason, self.semantic_group_id, self.agent_card.name
        )

    def run(self):
        # Only SemanticGroup mode needs reconciliation.
        if self.data_source_type != "SemanticGroup":
            return
        self._running = True
        logger.info(
            "[RootReconcile] Started. interval=%ss, fail_policy=%s, auto_promote_root=%s",
            self.interval_sec, self.root_check_fail_policy, self.auto_promote_root
        )
        while self._running:
            try:
                self._check_count += 1
                is_root, parent_id, reason = _check_semantic_group_root_status(
                    self.data_source_type,
                    self.semantic_group_id,
                    self.data_services_url,
                    timeout=self.check_timeout,
                )
                status_sig = (is_root, parent_id, self._is_registered)
                if self._last_status_sig != status_sig:
                    logger.info(
                        "[RootReconcile] Status changed: is_root=%s, parent_id=%s, reason=%s, registered=%s, group_id=%s",
                        is_root, parent_id, reason, self._is_registered, self.semantic_group_id
                    )
                    self._last_status_sig = status_sig
                elif self.summary_every > 0 and self._check_count % self.summary_every == 0:
                    logger.info(
                        "[RootReconcile] Summary: checks=%d, is_root=%s, parent_id=%s, registered=%s, group_id=%s",
                        self._check_count, is_root, parent_id, self._is_registered, self.semantic_group_id
                    )
                else:
                    logger.debug(
                        "[RootReconcile] Stable: is_root=%s, parent_id=%s, reason=%s, registered=%s, group_id=%s",
                        is_root, parent_id, reason, self._is_registered, self.semantic_group_id
                    )

                if is_root is None:
                    # Strict default: if root status is unknown and currently registered, remove it to avoid pollution.
                    if self.root_check_fail_policy == "fail_close" and self._is_registered:
                        self._unregister(reason=f"unknown_root_status:{reason}")
                elif is_root and not self._is_registered and self.register_agent_enabled and self.auto_promote_root:
                    self._register()
                elif (not is_root) and self._is_registered:
                    self._unregister(reason=f"group_became_non_root(parent_id={parent_id})")

            except Exception as e:
                logger.error("[RootReconcile] Loop exception: %s", e, exc_info=True)
            time.sleep(self.interval_sec)

        logger.info("[RootReconcile] Stopped. group_id=%s", self.semantic_group_id)


def _attach_semantic_group_extension(agent_card: AgentCard, semantic_group_id: str):
    """Attach semantic group contract to AgentCard capabilities.extensions."""
    if not semantic_group_id:
        return
    ext_uri = "dac.semantic_group"
    ext_obj = AgentExtension(
        uri=ext_uri,
        description="DAC semantic group metadata for routing",
        required=False,
        params={
            "dac.semantic_group_id": semantic_group_id,
            "dac.data_source_type": "SemanticGroup",
        },
    )
    caps = getattr(agent_card, "capabilities", None)
    if isinstance(caps, dict):
        ext_list = caps.get("extensions") or []
        ext_list = [e for e in ext_list if not (isinstance(e, dict) and e.get("uri") == ext_uri)]
        ext_list.append(ext_obj.model_dump(exclude_none=True))
        caps["extensions"] = ext_list
    elif caps is not None:
        ext_list = getattr(caps, "extensions", None) or []
        normalized = []
        for e in ext_list:
            uri = getattr(e, "uri", None) if not isinstance(e, dict) else e.get("uri")
            if uri == ext_uri:
                continue
            normalized.append(e)
        normalized.append(ext_obj)
        setattr(caps, "extensions", normalized)
    logger.info(
        "Agent extension contract ready: uri=%s, semantic_group_id=%s, data_source_type=SemanticGroup",
        ext_uri,
        semantic_group_id,
    )

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
        logger.info(
            "Runtime build info: hostname=%s, pod_name=%s, app_version=%s, image=%s, image_tag=%s, git_sha=%s",
            os.getenv("HOSTNAME", "unknown"),
            os.getenv("POD_NAME", "unknown"),
            os.getenv("APP_VERSION", "unknown"),
            os.getenv("IMAGE", "unknown"),
            os.getenv("IMAGE_TAG", "unknown"),
            os.getenv("GIT_SHA", "unknown"),
        )

        enable_history = os.getenv('Enable_History',"disable")
        logger.info(f"enable_history is: {enable_history}")

        data_source_type = os.getenv('DataSourceType',"SemanticGroup")
        logger.info(f"DataSourceType is: {data_source_type}")

        #dataservices
        data_services_url = os.getenv('DataServicesURL',"http://data-services.dac.svc.cluster.local:8000")
        
        # Root check policy: fail_close (default) avoids registry pollution on uncertain checks.
        root_check_fail_policy = os.getenv("ROOT_CHECK_FAIL_POLICY", "fail_close").strip().lower()
        if root_check_fail_policy not in ("fail_open", "fail_close"):
            logger.warning("Invalid ROOT_CHECK_FAIL_POLICY=%s, fallback to fail_close", root_check_fail_policy)
            root_check_fail_policy = "fail_close"

        semantic_group_id_for_check = os.getenv('SemanticGroupID', "")
        if data_source_type == "SemanticGroup":
            # IMPORTANT: attach extension BEFORE registry registration, otherwise
            # registry may store a stale card with extensions=None.
            _attach_semantic_group_extension(agent_card, semantic_group_id_for_check)

        is_root_group, parent_id, root_check_reason = _check_semantic_group_root_status(
            data_source_type=data_source_type,
            semantic_group_id=semantic_group_id_for_check,
            data_services_url=data_services_url,
            timeout=10.0,
        )
        if is_root_group is None:
            is_root_group = (root_check_fail_policy == "fail_open")
            logger.warning(
                "Root status unknown for group=%s (reason=%s). policy=%s -> register=%s",
                semantic_group_id_for_check, root_check_reason, root_check_fail_policy, is_root_group
            )
        elif is_root_group:
            logger.info(
                "SemanticGroup %s is ROOT (parent_id=%s), register=%s",
                semantic_group_id_for_check, parent_id, is_root_group
            )
        else:
            logger.info(
                "SemanticGroup %s is NON-ROOT (parent_id=%s), register=%s",
                semantic_group_id_for_check, parent_id, is_root_group
            )

        # Default: register agent to Redis. Set REGISTER_AGENT=false/0/no to skip registration.
        register_agent = (os.getenv("REGISTER_AGENT", "true").strip().lower() not in ("false", "0", "no"))
        registry: Optional[RedisRegistry] = None
        heartbeat_service: Optional[HeartbeatService] = None
        reconciler: Optional[RootMembershipReconciler] = None
        registered_now = False

        if not register_agent:
            logger.info("REGISTER_AGENT is disabled, agent will not register to Redis")
        else:
            # Build registry services even if startup registration is skipped,
            # so runtime reconciliation can promote/demote safely.
            registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)
            heartbeat_service = HeartbeatService(registry, interval=heartbeat_interval)
            heartbeat_service.start()

            if is_root_group:
                registered_now = heartbeat_service.register_agent(agent_card)
                if registered_now:
                    logger.info("Agent registered to Redis with heartbeat (interval: %ss)", heartbeat_interval)
                else:
                    logger.error("Failed to register agent to Redis")
            else:
                logger.info(
                    "Startup skip registration (non-root or unknown under fail_close). group=%s, reason=%s",
                    semantic_group_id_for_check, root_check_reason
                )

            enable_root_reconcile = os.getenv("ENABLE_ROOT_RECONCILE", "true").strip().lower() in ("true", "1", "yes")
            root_reconcile_interval_sec = int(os.getenv("ROOT_RECONCILE_INTERVAL_SEC", "30"))
            root_reconcile_timeout_sec = float(os.getenv("ROOT_RECONCILE_TIMEOUT_SEC", "10"))
            root_reconcile_auto_promote = os.getenv("ROOT_RECONCILE_AUTO_PROMOTE", "true").strip().lower() in ("true", "1", "yes")
            root_reconcile_summary_every = int(os.getenv("ROOT_RECONCILE_SUMMARY_EVERY", "0"))
            if enable_root_reconcile:
                reconciler = RootMembershipReconciler(
                    data_source_type=data_source_type,
                    semantic_group_id=semantic_group_id_for_check,
                    data_services_url=data_services_url,
                    root_check_fail_policy=root_check_fail_policy,
                    auto_promote_root=root_reconcile_auto_promote,
                    register_agent_enabled=register_agent,
                    agent_card=agent_card,
                    heartbeat_service=heartbeat_service,
                    interval_sec=root_reconcile_interval_sec,
                    check_timeout=root_reconcile_timeout_sec,
                    summary_every=root_reconcile_summary_every,
                )
                reconciler.set_registered_state(registered_now)
                reconciler.start()

            def _graceful_shutdown():
                if reconciler is not None:
                    reconciler.stop()
                if heartbeat_service is not None:
                    heartbeat_service.graceful_shutdown(agent_card.url)
                elif registry is not None:
                    registry.graceful_shutdown(agent_card.url)

            signal.signal(signal.SIGTERM, lambda s, f: _graceful_shutdown())
            signal.signal(signal.SIGINT, lambda s, f: _graceful_shutdown())  # Ctrl+C
            atexit.register(_graceful_shutdown)

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
                agent_executor=OrchestratorAgentExecutorSemanticDomain(
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
                    max_loops=max_loops,
                    agent_card=agent_card
                ),
                task_store=InMemoryTaskStore(),
                push_config_store=push_config_store,
                push_sender= push_sender
            )

        if data_source_type == "SemanticGroup":
            semantic_group_id = os.getenv('SemanticGroupID',"")
            logger.info(f"SemanticGroupID is: {semantic_group_id}")

            request_handler = DefaultRequestHandler(
            agent_executor=OrchestratorAgentExecutorSemanticGroup(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                semantic_group_id=semantic_group_id,
                debug=debug,
                data_services_url=data_services_url,
                enable_history=enable_history,
                agent_id=agent_card.name,
                max_loops=max_loops,
                agent_card=agent_card
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
