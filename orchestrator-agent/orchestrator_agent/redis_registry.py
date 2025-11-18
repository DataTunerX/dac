import json
import redis
import threading
import time
import asyncio
import logging
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
        self.db = db
        self.registry_key = "expert_agents"
        self.heartbeat_key = "agent_heartbeats"
        self.lock = threading.Lock()
        self.agents: List[AgentCard] = []
        self._load_initial_agents()


    def _load_initial_agents(self):
        self.agents = self.list_agents()
        logger.info(f"Loaded {len(self.agents)} agents from Redis")

    def _update_agents_on_event(self, event_type: str, agent_url: str, agent: Optional[AgentCard]):
        if event_type == "add":
            if agent and not any(a.url == agent_url for a in self.agents):
                self.agents.append(agent)
                logger.info(f"Added agent: {agent_url}")
        elif event_type == "remove":
            self.agents = [a for a in self.agents if a.url != agent_url]
            logger.info(f"Removed agent: {agent_url}")

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

    def get_agent(self, agent_url: str) -> Optional[AgentCard]:
        if not self.redis.hexists(self.registry_key, agent_url):
            return None

        try:
            data = self.redis.hget(self.registry_key, agent_url)
            return self._deserialize_agent(data)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Deserialization error: {e}")
            return None


    async def aget_agent(self, agent_url: str) -> Optional[AgentCard]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self.get_agent, agent_url)
        except Exception as e:
            print(f"Async get_agent error: {e}")
            return None


    def list_agents(self) -> List[AgentCard]:
        active_agents = []
        for agent_url in self.redis.hkeys(self.registry_key):
            agent = self.get_agent(agent_url)
            if not agent:
                continue
                
            active_agents.append(agent)

        return active_agents


    async def alist_agents(self, filter_capabilities: Dict[str, str] = None) -> List[AgentCard]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self.list_agents, filter_capabilities)
        except Exception as e:
            print(f"Async list_agents error: {e}")
            return []

    def cleanup_expired(self) -> int:
        expired = 0
        logger.info("== Starting cleanup_expired ==")

        agent_urls = set(self.redis.hkeys(self.registry_key))
        heartbeat_urls = set(self.redis.zrange(self.heartbeat_key, 0, -1))

        all_urls = agent_urls.union(heartbeat_urls)
        logger.info(f"Total agents to check: {len(all_urls)}")

        current_time = datetime.now().timestamp()
        heartbeat_timeout = 30
        expired_agents = set()

        for url in all_urls:
            last_heartbeat = self.redis.zscore(self.heartbeat_key, url)
            heartbeat_expired = (last_heartbeat is not None) and (current_time - last_heartbeat > heartbeat_timeout)

            readable_time = datetime.fromtimestamp(last_heartbeat).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Expired agents heartbeat check， url:{url} , last_heartbeat : {readable_time},  {last_heartbeat}, heartbeat_expired={heartbeat_expired}")
            if heartbeat_expired:
                expired_agents.add(url)

        logger.info(f"Expired agents count to clean: {len(expired_agents)}")
        logger.info(f"Expired agents url to clean: {expired_agents}")

        if expired_agents:
            pipe = self.redis.pipeline()
            for url in expired_agents:
                pipe.hdel(self.registry_key, url)
                pipe.zrem(self.heartbeat_key, url)
                pipe.delete(f"{self.registry_key}:{url}")
                expired += 1
            pipe.execute()
            logger.info(f"Cleaned {expired} expired agents")
            self.agents = [a for a in self.agents if a.url not in expired_agents]

        return expired

    def _parse_agent_url_from_channel(self, channel: str) -> Optional[str]:
        if not channel:
            return None

        parts = channel.split(':')

        logger.info(f'====parts = {parts}')
        if len(parts) < 3:
            return None

        registry_part = parts[-2]
        if registry_part != "expert_agents":
            return None
        
        return parts[-1]


    def watch_changes(
        self,
        callback: callable,
        event_types: List[str] = ["add", "remove"],
        patterns: List[str] = None
    ) -> threading.Thread:

        def _parse_agent_url(message: dict) -> Optional[str]:

            if message['channel'].startswith('__keyevent@'):
                return message['data']
            
            channel = message['channel']

            if f":{self.registry_key}:" in channel:
                prefix = "__keyspace@0__:expert_agents:"
                url = channel[len(prefix):]
                return url
            return None

        def listener():
            pubsub = None
            retry_delay = 1

            while getattr(thread, "running", True):
                try:
                    if pubsub is None:
                        pubsub = self.redis.pubsub()
                        pubsub.psubscribe(f"__keyspace@{self.db}:{self.registry_key}:*")
                        logger.info("PubSub connection established")
                        retry_delay = 1

                    for message in pubsub.listen():
                        if not getattr(thread, "running", True):
                            break

                        if not isinstance(message, dict) or message.get('type') != 'pmessage':
                            continue

                        agent_url = _parse_agent_url(message)
                        if not agent_url:
                            continue

                        event_data = message['data']
                        if event_data == 'set':
                            event = "add"
                        elif event_data == 'del':
                            event = "remove"
                        else:
                            continue

                        try:
                            agent = self.get_agent(agent_url) if event == "add" else None
                            self._update_agents_on_event(event, agent_url, agent)
                            result = callback(event, agent_url, agent)
                            if asyncio.iscoroutine(result):
                                asyncio.create_task(result)
                        except Exception as e:
                            logger.error(f"Callback execution failed: {e}", exc_info=True)

                except (redis.ConnectionError, redis.TimeoutError) as e:
                    logger.error(f"Redis connection exception: {e}, closing old connection and retrying in 5 seconds...")
                    if pubsub:
                        try:
                            pubsub.close()
                        except:
                            pass
                    pubsub = None
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)  # 指数退避，最大30秒
                except Exception as e:
                    logger.error(f"Monitoring thread exception: {e}", exc_info=True)
                    time.sleep(1)

            if pubsub:
                try:
                    pubsub.close()
                except:
                    pass

        thread = threading.Thread(target=listener, daemon=True)
        thread.running = True
        thread.start()
        return thread


# Called uniformly by agent registry, not cleaned up by each agent individually.
# CleanupService (runs every 60 seconds by default) will ultimately clean up expired Agents.
# Agents actually expire after no heartbeat for interval * 3 = 30 seconds, but can take up to 60 seconds to be cleaned.
class CleanupService(threading.Thread):
    def __init__(self, registry: RedisRegistry, interval=60):
        super().__init__(daemon=True)
        self.registry = registry
        self.interval = interval
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                cleaned = self.registry.cleanup_expired()
                if cleaned > 0:
                    print(f"Cleaned {cleaned} expired agents")
                time.sleep(self.interval)
            except Exception as e:
                print(f"Cleanup thread error: {e}")
                time.sleep(30)

    def stop(self):
        self._running = False


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
