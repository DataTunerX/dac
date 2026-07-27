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
import threading
from typing import Any, Dict, Literal, List, Optional, Union
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from typing_extensions import override
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from .redis_registry import RedisRegistry, HeartbeatService
from .skill_agent import SkillAgentExecutor
from .skill_download import download_skills
from .skill_sync import start_watcher
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
@click.option('--max-steps', 'max_steps',default=2, type=int, help='max steps to run')
def main(host, port, agent_card, redis_host, redis_port, redis_db, password, provider, api_key, base_url, model, temperature, heartbeat_interval, stream, max_steps):
    """Starts an Agent server."""
    try:
        # Pull skill zip packs from skill-hub based on the SKILLS env var
        # BEFORE the SkillAgentExecutor is built, so LOCAL_SKILLS_DIR
        # (/app/skills/) is populated by the time preload_skill_runner()
        # scans it. No-op when SKILLS is unset or empty.
        try:
            download_skills()
        except Exception:  # noqa: BLE001
            logger.exception("[SkillDownload] startup download raised — continuing")

        if not agent_card:
            raise ValueError('Agent card is required')
        with Path.open(agent_card) as file:
            data = json.load(file)
        agent_card = AgentCard(**data)
        agent_host = os.getenv('Agent_Host',"192.168.xxx.xxx")
        agent_port = os.getenv('Agent_Port',"20002")
        agent_card.name = os.getenv('Agent_Name',"SkillAgent")
        agent_card.url = f'http://{agent_host}:{agent_port}'
        # NOTE: agent_card.description / agent_card.skills are intentionally NOT
        # populated from env vars / static JSON here. They are regenerated after
        # SkillRunner preload from the actually-loaded skill inventory — mirrors
        # orchestrator_agent_semantic_domain._build_local_skill_card so the card
        # reflects real capabilities instead of a hand-written blurb.

        httpx_client = httpx.AsyncClient()
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)

        skill_executor = SkillAgentExecutor(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            stream=stream,
            temperature=temperature,
            max_steps=max_steps,
        )
        # Eagerly initialise the process-wide SkillRunner so the full skill
        # inventory is printed at startup (instead of lazily on the first
        # request). Safe no-op when ENABLE_LOCAL_SKILLS=false.
        try:
            skill_executor.preload_skill_runner()
        except Exception:  # noqa: BLE001
            logger.exception(
                "[LocalSkill][Init] preload_skill_runner raised — continuing without LocalSkill"
            )
        # Release the SkillRunner (including any temp dirs from SkillLoader)
        # on process exit. Safe no-op when the feature is off.
        atexit.register(skill_executor.shutdown_skill_runner)

        # Compose agent_card.description / skills from the loaded skill
        # inventory. When the runner could not load anything, fall back to the
        # description in agent_card.json so the card is never empty.
        dynamic_description, dynamic_skills = skill_executor.build_dynamic_agent_card_fields()
        if dynamic_skills:
            agent_card.description = dynamic_description
            agent_card.skills = dynamic_skills
            logger.info(
                "[LocalSkill][Card] agent_card refreshed from loaded inventory: "
                "skills=%d description_chars=%d",
                len(dynamic_skills), len(dynamic_description),
            )
        else:
            fallback_desc = data.get("description") or dynamic_description
            agent_card.description = fallback_desc
            raw_skills = data.get("skills") or []
            agent_card.skills = [AgentSkill(**s) for s in raw_skills]
            logger.warning(
                "[LocalSkill][Card] no skills loaded — falling back to agent_card.json "
                "(static_skills=%d)", len(agent_card.skills),
            )

        skill_executor.agent_card = agent_card

        logger.info(f"agent_card is: {agent_card}")

        # Default: register agent to Redis. Set REGISTER_AGENT=false/0/no to skip registration.
        # On SIGTERM/SIGINT/atexit, unregister via HeartbeatService (same pattern as
        # orchestrator_agent/server.py): that removes the agent from the in-memory
        # heartbeat list *and* Redis. Calling only RedisRegistry.graceful_shutdown
        # leaves HeartbeatService._agents populated, so auto-recovery re-registers
        # the agent within ~30s and the registry entry can appear "stuck" after pod stop.
        register_agent = (os.getenv("REGISTER_AGENT", "true").strip().lower() not in ("false", "0", "no"))
        registry: Optional[RedisRegistry] = None
        heartbeat_service: Optional[HeartbeatService] = None
        if not register_agent:
            logger.info("REGISTER_AGENT is disabled, agent will not register to Redis")
        else:
            registry = RedisRegistry(host=redis_host, port=redis_port, db=redis_db, password=password)
            heartbeat_service = HeartbeatService(registry, interval=heartbeat_interval)
            heartbeat_service.start()
            if heartbeat_service.register_agent(agent_card):
                logger.info(
                    "Agent registered to Redis with heartbeat (interval: %ss)",
                    heartbeat_interval,
                )
            else:
                logger.error("Failed to register agent to Redis")

            def _graceful_shutdown():
                if heartbeat_service is not None:
                    heartbeat_service.graceful_shutdown(agent_card.url)
                elif registry is not None:
                    registry.graceful_shutdown(agent_card.url)

            signal.signal(signal.SIGTERM, lambda s, f: _graceful_shutdown())
            signal.signal(signal.SIGINT, lambda s, f: _graceful_shutdown())  # Ctrl+C
            atexit.register(_graceful_shutdown)

        request_handler = DefaultRequestHandler(
            agent_executor=skill_executor,
            task_store=InMemoryTaskStore(),
            push_config_store=push_config_store,
            push_sender= push_sender
        )

        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        # ------------------------------------------------------------------
        # Start the skill-hub watcher: when a skill is pushed/updated on the
        # hub, pull it, hot-reload the SkillRunner, refresh the AgentCard, and
        # re-register so the orchestrator sees the new capability without a
        # restart. Disabled via SKILL_SYNC_ENABLED=false / SKILL_SYNC_INTERVAL<=0.
        # ------------------------------------------------------------------
        _sync_lock = threading.Lock()

        def _on_skills_changed(changed):
            with _sync_lock:
                logger.info(
                    "[SkillSync] applying %d change(s): %s",
                    len(changed), ", ".join(changed),
                )
                try:
                    skill_executor.reload_skill_runner()
                except Exception:  # noqa: BLE001
                    logger.exception("[SkillSync] reload_skill_runner failed")
                    return
                try:
                    desc, skills = skill_executor.build_dynamic_agent_card_fields()
                    if skills:
                        agent_card.description = desc
                        agent_card.skills = skills
                except Exception:  # noqa: BLE001
                    logger.exception("[SkillSync] rebuilding agent card failed")
                # Re-register so the refreshed card (new skill list) is pushed to
                # Redis. HeartbeatService.register_agent updates its in-memory
                # copy too, so heartbeats keep advertising the new card.
                try:
                    if heartbeat_service is not None:
                        heartbeat_service.register_agent(agent_card)
                    elif registry is not None:
                        registry.register_agent(agent_card)
                    logger.info(
                        "[SkillSync] agent card refreshed and re-registered "
                        "(skills=%d)", len(agent_card.skills or []),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[SkillSync] re-registration failed")

        watcher = None
        try:
            watcher = start_watcher(
                _on_skills_changed,
                initial_versions=skill_executor.get_loaded_skill_versions(),
            )
            if watcher is not None:
                atexit.register(watcher.stop)
        except Exception:  # noqa: BLE001
            logger.exception("[SkillSync] failed to start watcher — continuing")

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