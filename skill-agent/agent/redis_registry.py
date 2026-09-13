import json
import redis
import threading
import logging
import time
import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Any
from a2a.types import AgentCard
from agent_contracts import AgentRuntimeStatus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

class RedisRegistry:
    def __init__(self, host='localhost', port=6379, db=0, password=None, ssl=False):
        self.redis = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            ssl=ssl,
            decode_responses=True,
            socket_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True
        )
        self.registry_key = "expert_agents"
        self.heartbeat_key = "agent_heartbeats"
        self.runtime_status_key = "agent_runtime_status:v2"
        self.alias_key = "agent_aliases:v2"
        self.aliases_by_id_key = "agent_aliases_by_id:v2"
        self.lock = threading.Lock()

    def _serialize_agent(self, agent: AgentCard) -> str:
        if hasattr(agent, "model_dump_json"):
            return agent.model_dump_json()
        return agent.json() if hasattr(agent, "json") else json.dumps(agent.__dict__)

    def _deserialize_agent(self, data: str) -> AgentCard:
        return AgentCard(**json.loads(data))

    @staticmethod
    def _serialize_status(status: AgentRuntimeStatus) -> str:
        return status.model_dump_json()

    def register_agent(
        self,
        agent: AgentCard,
        runtime_status: Optional[AgentRuntimeStatus] = None,
    ) -> bool:
        agent_id = agent.url
        try:
            alias = str(agent.name).strip()
            existing_alias = (
                self.redis.hget(self.alias_key, alias.casefold()) if alias else None
            )
            if existing_alias and existing_alias != agent_id:
                logger.error(
                    "Registration rejected: alias %r already belongs to %s",
                    alias,
                    existing_alias,
                )
                return False
            previous_aliases = []
            raw_previous_aliases = self.redis.hget(
                self.aliases_by_id_key, agent_id
            )
            if raw_previous_aliases:
                try:
                    previous_aliases = json.loads(raw_previous_aliases)
                except (TypeError, ValueError):
                    logger.warning("Invalid prior alias record for %s", agent_id)
            pipe = self.redis.pipeline()
            pipe.hset(self.registry_key, agent_id, self._serialize_agent(agent))
            pipe.zadd(self.heartbeat_key, {agent_id: datetime.now().timestamp()})
            if alias:
                for previous_alias in previous_aliases:
                    normalized = str(previous_alias).strip().casefold()
                    if (
                        normalized
                        and normalized != alias.casefold()
                        and self.redis.hget(self.alias_key, normalized) == agent_id
                    ):
                        pipe.hdel(self.alias_key, normalized)
                pipe.hset(self.alias_key, alias.casefold(), agent_id)
                pipe.hset(
                    self.aliases_by_id_key,
                    agent_id,
                    json.dumps([alias], ensure_ascii=False),
                )
            if runtime_status is not None:
                pipe.hset(
                    self.runtime_status_key,
                    agent_id,
                    self._serialize_status(runtime_status),
                )
            pipe.set(f"{self.registry_key}:{agent_id}", "1")
            results = pipe.execute()
                
            for i, cmd in enumerate(["HSET", "ZADD"]):
                logger.info("%s result: %s", cmd, results[i])
                
            success = (results[0] >= 0 and results[1] >= 0)

            logger.info(f'=== register_agent is :{success}')
            return success
        except redis.RedisError as e:
            logger.error(f"Registration error: {e}")
            return False

    def unregister_agent(self, agent_url: str) -> bool:
        try:
            pipe = self.redis.pipeline()
            raw_aliases = self.redis.hget(self.aliases_by_id_key, agent_url)
            if raw_aliases:
                try:
                    aliases = json.loads(raw_aliases)
                except (TypeError, ValueError):
                    aliases = []
                for alias in aliases:
                    pipe.hdel(self.alias_key, str(alias).strip().casefold())
            pipe.hdel(self.aliases_by_id_key, agent_url)
            pipe.hdel(self.registry_key, agent_url)
            pipe.zrem(self.heartbeat_key, agent_url)
            pipe.hdel(self.runtime_status_key, agent_url)
            pipe.delete(f"{self.registry_key}:{agent_url}")
            results = pipe.execute()

            success = True
            logger.info(f'Agent unregistration succeeded: {agent_url} (results: {results})')
            return success
            
        except redis.RedisError as e:
            logger.error(f"Unregistration error: {e}")
            return False

    def is_agent_registered(self, agent_url: str) -> bool:
        try:
            return self.redis.hexists(self.registry_key, agent_url)
        except redis.RedisError as e:
            logger.error(f"Check registration error: {e}")
            return False

    def graceful_shutdown(self, agent_url: str):
        self.unregister_agent(agent_url)
        logger.info(f"Agent {agent_url} gracefully unregistered")


class HeartbeatService(threading.Thread):
    
    def __init__(self, registry: RedisRegistry, interval=10):
        super().__init__(daemon=True)
        self.registry = registry
        self.interval = interval
        self._running = False
        self._agents = {}
        self._runtime_statuses: Dict[str, AgentRuntimeStatus] = {}
        self.last_registration_check = time.time()
        self.registration_check_interval = 30

    def register_agent(
        self,
        agent: AgentCard,
        runtime_status: Optional[AgentRuntimeStatus] = None,
    ) -> bool:
        success = self.registry.register_agent(agent, runtime_status=runtime_status)
        if success:
            self._agents[agent.url] = agent
            if runtime_status is not None:
                self._runtime_statuses[agent.url] = runtime_status
            logger.info(f"Agent registered to heartbeat service: {agent.url}")
        return success

    def unregister_agent(self, agent_url: str) -> bool:
        if agent_url in self._agents:
            del self._agents[agent_url]
            logger.info(f"Agent removed from heartbeat service: {agent_url}")
        self._runtime_statuses.pop(agent_url, None)
        return self.registry.unregister_agent(agent_url)

    def run(self):
        self._running = True
        logger.info("Heartbeat service started with auto-recovery")
        
        while self._running:
            try:
                current_time = time.time()
                agent_urls = list(self._agents.keys())
                
                if not agent_urls:
                    logger.debug("No agents to heartbeat")
                    time.sleep(self.interval)
                    continue

                if current_time - self.last_registration_check > self.registration_check_interval:
                    self._check_and_recover_registration(agent_urls)
                    self.last_registration_check = current_time

                self._update_heartbeats(agent_urls)
                
                logger.debug(f"Heartbeat updated for {len(agent_urls)} agents")
                time.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"Heartbeat thread error: {e}")
                time.sleep(5)

    def _update_heartbeats(self, agent_urls: List[str]):
        try:
            timestamp = datetime.now().timestamp()
            pipe = self.registry.redis.pipeline()
            
            for agent_url in agent_urls:
                pipe.zadd(self.registry.heartbeat_key, {agent_url: timestamp})
                runtime_status = self._runtime_statuses.get(agent_url)
                if runtime_status is not None:
                    pipe.hset(
                        self.registry.runtime_status_key,
                        agent_url,
                        self.registry._serialize_status(runtime_status),
                    )
            
            results = pipe.execute()
            logger.debug(f"Heartbeat update results: {len(results)} operations")
            
        except redis.RedisError as e:
            logger.error(f"Heartbeat update failed: {e}")

    def _check_and_recover_registration(self, agent_urls: List[str]):
        try:
            if not agent_urls:
                return

            pipe = self.registry.redis.pipeline()
            for agent_url in agent_urls:
                pipe.hexists(self.registry.registry_key, agent_url)
            registration_status = pipe.execute()

            re_registered_count = 0
            for i, agent_url in enumerate(agent_urls):
                if not registration_status[i] and agent_url in self._agents:
                    agent_card = self._agents[agent_url]
                    if self.registry.register_agent(
                        agent_card,
                        runtime_status=self._runtime_statuses.get(agent_url),
                    ):
                        re_registered_count += 1
                        logger.warning(f"Auto-recovered registration for: {agent_url}")
                    else:
                        logger.error(f"Failed to auto-recover registration for: {agent_url}")
            
            if re_registered_count > 0:
                logger.info(f"Auto-recovery: re-registered {re_registered_count} agents")
                
        except Exception as e:
            logger.error(f"Registration recovery check failed: {e}")

    def stop(self):
        self._running = False
        logger.info("Heartbeat service stopped")

    def update_runtime_status(self, status: AgentRuntimeStatus) -> None:
        """Publish a readiness change without changing the registered card."""

        self._runtime_statuses[status.agent_url] = status
        self.registry.redis.hset(
            self.registry.runtime_status_key,
            status.agent_url,
            self.registry._serialize_status(status),
        )

    def graceful_shutdown(self, agent_url: str = None):
        if agent_url:
            self.unregister_agent(agent_url)
        else:
            for agent_url in list(self._agents.keys()):
                self.unregister_agent(agent_url)
            self.stop()
        logger.info("Graceful shutdown completed")
