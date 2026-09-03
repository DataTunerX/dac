import json
import os
import redis
import socket
import threading
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List, Any, Tuple
from urllib.parse import urlparse
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


    @staticmethod
    def _heartbeat_timeout_sec() -> float:
        raw = (
            os.getenv("HEARTBEAT_TIMEOUT_SEC", "").strip()
            or os.getenv("REGISTRY_HEARTBEAT_TIMEOUT_SEC", "").strip()
            or "30"
        )
        try:
            return max(5.0, float(raw))
        except ValueError:
            return 30.0

    def remove_agent(self, agent_url: str, *, reason: str = "") -> bool:
        """Delete one agent card + heartbeat + sentinel (authoritative purge)."""
        if not agent_url:
            return False
        try:
            pipe = self.redis.pipeline()
            pipe.hdel(self.registry_key, agent_url)
            pipe.zrem(self.heartbeat_key, agent_url)
            pipe.delete(f"{self.registry_key}:{agent_url}")
            results = pipe.execute()
            self.agents = [a for a in self.agents if a.url != agent_url]
            logger.info(
                "Removed agent from registry | url=%s reason=%s results=%s",
                agent_url,
                reason or "explicit",
                results,
            )
            return True
        except redis.RedisError as e:
            logger.error("remove_agent failed | url=%s err=%s", agent_url, e)
            return False

    # It is uniformly called by the agent registry, not cleaned up by each individual agent.
    def cleanup_expired(self) -> int:
        """Remove agents whose heartbeat is missing or older than HEARTBEAT_TIMEOUT_SEC.

        Hash-only orphans (card present, no ZSET score) used to crash the sweep via
        ``fromtimestamp(None)`` and were never expired — leaving ghost cards forever.
        """
        expired = 0
        logger.info("== Starting cleanup_expired ==")

        agent_urls = set(self.redis.hkeys(self.registry_key))
        heartbeat_urls = set(self.redis.zrange(self.heartbeat_key, 0, -1))
        all_urls = agent_urls.union(heartbeat_urls)
        logger.info("Total agents to check: %d", len(all_urls))

        current_time = datetime.now().timestamp()
        heartbeat_timeout = self._heartbeat_timeout_sec()
        expired_agents: set[str] = set()

        for url in all_urls:
            last_heartbeat = self.redis.zscore(self.heartbeat_key, url)
            if last_heartbeat is None:
                # Card without heartbeat (or heartbeat without card) is inconsistent → purge.
                logger.warning(
                    "Expired agents heartbeat check | url=%s last_heartbeat=missing "
                    "heartbeat_expired=True reason=missing_score",
                    url,
                )
                expired_agents.add(url)
                continue

            age = current_time - float(last_heartbeat)
            heartbeat_expired = age > heartbeat_timeout
            readable_time = datetime.fromtimestamp(float(last_heartbeat)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            logger.info(
                "Expired agents heartbeat check | url=%s last_heartbeat=%s age=%.1fs "
                "timeout=%.1fs heartbeat_expired=%s",
                url,
                readable_time,
                age,
                heartbeat_timeout,
                heartbeat_expired,
            )
            if heartbeat_expired:
                expired_agents.add(url)

        logger.info("Expired agents count to clean: %d", len(expired_agents))
        logger.info("Expired agents url to clean: %s", expired_agents)

        if expired_agents:
            pipe = self.redis.pipeline()
            for url in expired_agents:
                pipe.hdel(self.registry_key, url)
                pipe.zrem(self.heartbeat_key, url)
                pipe.delete(f"{self.registry_key}:{url}")
                expired += 1
            pipe.execute()
            logger.info("Cleaned %d expired agents", expired)
            self.agents = [a for a in self.agents if a.url not in expired_agents]

        return expired

    @staticmethod
    def probe_agent_reachable(
        agent_url: str,
        *,
        timeout_sec: float = 3.0,
    ) -> Tuple[bool, str]:
        """TCP reachability check for a registered agent URL (DNS + connect)."""
        parsed = urlparse(agent_url or "")
        host = parsed.hostname
        if not host:
            return False, "invalid_url"
        port = parsed.port or (443 if (parsed.scheme or "").lower() == "https" else 80)
        try:
            with socket.create_connection((host, int(port)), timeout=timeout_sec):
                return True, "ok"
        except socket.gaierror as e:
            return False, f"dns:{e}"
        except OSError as e:
            return False, f"connect:{e}"

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
                prefix = f"__keyspace@{self.db}__:{self.registry_key}:"
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
# Agents actually expire after HEARTBEAT_TIMEOUT_SEC (default 30) without a heartbeat,
# but it can take up to cleanup interval before they are cleaned up.
# Optional TCP reachability: DNS/connect failures purge after N consecutive fails.
class CleanupService(threading.Thread):
    def __init__(self, registry: RedisRegistry, interval=None):
        super().__init__(daemon=True)
        self.registry = registry
        if interval is None:
            raw = os.getenv("REGISTRY_CLEANUP_INTERVAL_SEC", "60").strip() or "60"
            try:
                interval = max(5, int(raw))
            except ValueError:
                interval = 60
        self.interval = interval
        self._running = False
        self._reach_fail_counts: Dict[str, int] = {}

    @staticmethod
    def _reachability_enabled() -> bool:
        return os.getenv("REGISTRY_REACHABILITY_CHECK", "true").strip().lower() not in (
            "false",
            "0",
            "no",
        )

    @staticmethod
    def _reachability_fail_threshold() -> int:
        raw = os.getenv("REGISTRY_REACHABILITY_FAILS", "2").strip() or "2"
        try:
            return max(1, int(raw))
        except ValueError:
            return 2

    @staticmethod
    def _reachability_timeout_sec() -> float:
        raw = os.getenv("REGISTRY_REACHABILITY_TIMEOUT_SEC", "3").strip() or "3"
        try:
            return max(0.5, float(raw))
        except ValueError:
            return 3.0

    def _purge_unreachable(self) -> int:
        if not self._reachability_enabled():
            return 0
        threshold = self._reachability_fail_threshold()
        timeout = self._reachability_timeout_sec()
        purged = 0
        # Snapshot from Redis hash so we do not rely only on in-memory list.
        urls = list(self.registry.redis.hkeys(self.registry.registry_key))
        live = set(urls)
        for url in urls:
            ok, reason = self.registry.probe_agent_reachable(url, timeout_sec=timeout)
            if ok:
                self._reach_fail_counts.pop(url, None)
                continue
            # DNS failures are definitive ghost cards — purge on first failure.
            immediate = reason.startswith("dns:") or reason == "invalid_url"
            count = self._reach_fail_counts.get(url, 0) + 1
            self._reach_fail_counts[url] = count
            logger.warning(
                "Registry reachability fail | url=%s reason=%s fails=%d/%d immediate=%s",
                url,
                reason,
                count,
                threshold,
                immediate,
            )
            if immediate or count >= threshold:
                if self.registry.remove_agent(url, reason=f"unreachable:{reason}"):
                    purged += 1
                self._reach_fail_counts.pop(url, None)
        # Drop counters for agents already gone.
        for stale in list(self._reach_fail_counts):
            if stale not in live:
                self._reach_fail_counts.pop(stale, None)
        return purged

    def run(self):
        self._running = True
        logger.info(
            "CleanupService started | interval=%ss heartbeat_timeout=%ss "
            "reachability=%s fail_threshold=%d",
            self.interval,
            self.registry._heartbeat_timeout_sec(),
            self._reachability_enabled(),
            self._reachability_fail_threshold(),
        )
        while self._running:
            try:
                cleaned = self.registry.cleanup_expired()
                unreachable = self._purge_unreachable()
                if cleaned > 0 or unreachable > 0:
                    logger.info(
                        "Cleanup pass done | heartbeat_expired=%d unreachable=%d",
                        cleaned,
                        unreachable,
                    )
                time.sleep(self.interval)
            except Exception as e:
                logger.error("Cleanup thread error: %s", e, exc_info=True)
                time.sleep(30)

    def stop(self):
        self._running = False

