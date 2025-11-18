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
        # Each thread uses an independent connection.
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
        self._enable_keyspace_notifications()
        self._load_initial_agents()

    def _enable_keyspace_notifications(self):
        try:
            self.redis.config_set('notify-keyspace-events', 'AKE')
            logger.info("Redis keyspace notifications enabled with AKE")
        except redis.ResponseError as e:
            logger.error(f"Could not enable keyspace notifications: {e}")
            logger.error("Please run manually: redis-cli config set notify-keyspace-events AKE")

    def _load_initial_agents(self):
        self.agents = self.list_agents()
        logger.info(f"Loaded {len(self.agents)} agents from Redis")

    def _update_agents_on_event(self, event_type: str, agent_url: str, agent: Optional[AgentCard]):
        """Update the in-memory agents list based on events."""
        if event_type == "add":
            if agent and not any(a.url == agent_url for a in self.agents):
                self.agents.append(agent)
                logger.info(f"Added agent: {agent_url}, self.agents={self.agents}")
        elif event_type == "remove":
            self.agents = [a for a in self.agents if a.url != agent_url]
            logger.info(f"Removed agent: {agent_url}, , self.agents={self.agents}")

    def _serialize_agent(self, agent: AgentCard) -> str:
        return agent.json() if hasattr(agent, 'json') else json.dumps(agent.__dict__)

    def _deserialize_agent(self, data: str) -> AgentCard:
        return AgentCard(**json.loads(data))

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

    def get_agents(self) -> List[AgentCard]:
        return self.agents

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


    # It is uniformly called by the agent registry, not cleaned up by each individual agent.
    def cleanup_expired(self) -> int:
        expired = 0
        # with self.lock:
        logger.info("== Starting cleanup_expired ==")

        # 1. Retrieve all Agent URLs and their TTL status.
        agent_urls = set(self.redis.hkeys(self.registry_key))
        heartbeat_urls = set(self.redis.zrange(self.heartbeat_key, 0, -1))
            
        # All URLs that need to be checked (combining URLs from both the registry and heartbeat tables).
        all_urls = agent_urls.union(heartbeat_urls)
        logger.info(f"Total agents to check: {len(all_urls)}")

        # 2. Check for agents with expired TTL or heartbeat timeout.
        current_time = datetime.now().timestamp()
        heartbeat_timeout = 30
        expired_agents = set()

        # Check the TTL in the registry and the last heartbeat time in the heartbeat table.
        for url in all_urls:
            # Check if the heartbeat has timed out.
            last_heartbeat = self.redis.zscore(self.heartbeat_key, url)
            heartbeat_expired = (last_heartbeat is not None) and (current_time - last_heartbeat > heartbeat_timeout)

            readable_time = datetime.fromtimestamp(last_heartbeat).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Expired agents heartbeat check， url:{url} , last_heartbeat : {readable_time},  {last_heartbeat}, heartbeat_expired={heartbeat_expired}")
            # If the heartbeat times out, mark it for cleanup.
            if heartbeat_expired:
                expired_agents.add(url)

        logger.info(f"Expired agents count to clean: {len(expired_agents)}")
        logger.info(f"Expired agents url to clean: {expired_agents}")

        # 3. Batch cleanup of three parts of data.
        if expired_agents:
            pipe = self.redis.pipeline()
            for url in expired_agents:
                pipe.hdel(self.registry_key, url)
                pipe.zrem(self.heartbeat_key, url)
                pipe.delete(f"{self.registry_key}:{url}")
                expired += 1
            pipe.execute()
            logger.info(f"Cleaned {expired} expired agents")

            # 4. Update the in-memory agents list (ensuring consistency).
            self.agents = [a for a in self.agents if a.url not in expired_agents]

        return expired

    def _parse_agent_url_from_channel(self, channel: str) -> Optional[str]:
        if not channel:
            return None
        
        # example channel: "__keyspace@0__:expert_agents:http://agent1"
        parts = channel.split(':')

        logger.info(f'====parts = {parts}')
        if len(parts) < 3:  # __keyspace@0__, expert_agents, http://agent1
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
        """
        :param callback: func(event_type, agent_url, agent)
        :param event_types: ["add", "remove"]
        :param patterns: 
        """
        def _parse_agent_url(message: dict) -> Optional[str]:
            if message['channel'].startswith('__keyevent@'):
                return message['data']
            
            channel = message['channel']
            # channel is :   __keyspace@0__:expert_agents:http://192.168.xxx.xxx:20002/
            # logger.info(f'channel === {channel}')
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
                    # Create pubsub on initial connection or when reconnection is required.
                    if pubsub is None:
                        pubsub = self.redis.pubsub()
                        pubsub.psubscribe(f"__keyspace@{self.db}__:{self.registry_key}:*")
                        logger.info("PubSub connection has been established.")
                        retry_delay = 1

                    for message in pubsub.listen():
                        if not getattr(thread, "running", True):
                            break

                        logger.debug(f"===watch_changes , 1. message = {message}")

                        if not isinstance(message, dict) or message.get('type') != 'pmessage':
                            continue

                        logger.debug(f"===watch_changes , 2. message = {message}")

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
                            logger.error(f"Callback execution failed.: {e}", exc_info=True)

                except (redis.ConnectionError, redis.TimeoutError) as e:
                    logger.error(f"Redis connection exception: {e}, closing old connection and retrying in 5 seconds...")
                    if pubsub:
                        try:
                            pubsub.close()
                        except:
                            pass
                    pubsub = None
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                except Exception as e:
                    logger.error(f"Listening thread exception.: {e}", exc_info=True)
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


# It is uniformly called by the agent registry, not cleaned up by each individual agent.
# The CleanupService (runs every 60 seconds by default) will ultimately clean up expired agents.
# Agents actually expire after interval * 3 = 30 seconds without a heartbeat, but it can take up to 60 seconds maximum before they are cleaned up.
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

