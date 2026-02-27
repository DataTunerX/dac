import json
import redis
import threading
import logging
import time
import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Any
from a2a.types import AgentCard

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
        self.lock = threading.Lock()

    def _serialize_agent(self, agent: AgentCard) -> str:
        return agent.json() if hasattr(agent, 'json') else json.dumps(agent.__dict__)

    def _deserialize_agent(self, data: str) -> AgentCard:
        return AgentCard(**json.loads(data))

    def register_agent(self, agent: AgentCard) -> bool:
        agent_id = agent.url
        try:
            pipe = self.redis.pipeline()
            pipe.hset(self.registry_key, agent_id, self._serialize_agent(agent))
            pipe.zadd(self.heartbeat_key, {agent_id: datetime.now().timestamp()})
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
            pipe.hdel(self.registry_key, agent_url)
            pipe.zrem(self.heartbeat_key, agent_url)
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
        self.last_registration_check = time.time()
        self.registration_check_interval = 30

    def register_agent(self, agent: AgentCard) -> bool:
        success = self.registry.register_agent(agent)
        if success:
            self._agents[agent.url] = agent
            logger.info(f"Agent registered to heartbeat service: {agent.url}")
        return success

    def unregister_agent(self, agent_url: str) -> bool:
        if agent_url in self._agents:
            del self._agents[agent_url]
            logger.info(f"Agent removed from heartbeat service: {agent_url}")
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
                    if self.registry.register_agent(agent_card):
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

    def graceful_shutdown(self, agent_url: str = None):
        if agent_url:
            self.unregister_agent(agent_url)
        else:
            for agent_url in list(self._agents.keys()):
                self.unregister_agent(agent_url)
            self.stop()
        logger.info("Graceful shutdown completed")
