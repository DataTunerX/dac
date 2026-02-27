import time
import uuid
import logging
import os
from typing import Optional

import redis

logger = logging.getLogger("distributed_lock")

DEFAULT_LOCK_TTL = 600          # Lock auto-expires after 600s (10 min) to prevent deadlocks
DEFAULT_ACQUIRE_TIMEOUT = 660   # Wait up to 660s (11 min) trying to acquire the lock
DEFAULT_RETRY_INTERVAL = 3      # Poll every 3s while waiting for the lock
DEFAULT_REDIS_DB_LOCK = 6       # Dedicated Redis DB for locks

SEMANTIC_GROUP_LOCK_KEY = "dac:semantic_group:global_lock"

# Lua script for atomic compare-and-delete (safe release)
_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def _build_redis_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
    db: Optional[int] = None,
) -> redis.Redis:
    """
    Build a Redis client from explicit args or environment variables.
    Reuses the same REDIS_HOST / REDIS_PORT / REDIS_PASSWORD env vars
    that are already configured for Celery.
    """
    _host = host or os.getenv("REDIS_HOST", "localhost")
    _port = int(port or os.getenv("REDIS_PORT", "6379"))
    _password = password or os.getenv("REDIS_PASSWORD") or None
    _db = int(db if db is not None else os.getenv("REDIS_DB_LOCK", str(DEFAULT_REDIS_DB_LOCK)))

    return redis.Redis(
        host=_host,
        port=_port,
        password=_password,
        db=_db,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )


class DistributedLock:
    """
    Redis-based distributed lock using SET NX EX pattern.

    Usage as a context manager::

        lock = DistributedLock(redis_client, "my_lock_key")
        with lock:
            # critical section – only one process enters here at a time
            ...

    Or acquire / release manually::

        if lock.acquire():
            try:
                ...
            finally:
                lock.release()
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        lock_key: str = SEMANTIC_GROUP_LOCK_KEY,
        lock_ttl: int = DEFAULT_LOCK_TTL,
        acquire_timeout: int = DEFAULT_ACQUIRE_TIMEOUT,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
    ):
        self._redis = redis_client
        self._lock_key = lock_key
        self._lock_ttl = lock_ttl
        self._acquire_timeout = acquire_timeout
        self._retry_interval = retry_interval
        self._lock_value: Optional[str] = None

    def try_acquire(self) -> bool:
        """
        Non-blocking: attempt to acquire the lock exactly once.
        Returns True on success, False if lock is already held.
        """
        self._lock_value = str(uuid.uuid4())
        acquired = self._redis.set(
            self._lock_key,
            self._lock_value,
            nx=True,
            ex=self._lock_ttl,
        )
        if acquired:
            logger.info(
                "Distributed lock acquired (non-blocking): key=%s, value=%s, ttl=%ds",
                self._lock_key, self._lock_value, self._lock_ttl,
            )
            return True

        holder_ttl = self._redis.ttl(self._lock_key)
        logger.info(
            "Lock already held, skipping: key=%s, holder TTL=%ss",
            self._lock_key, holder_ttl,
        )
        self._lock_value = None
        return False

    def acquire(self) -> bool:
        """
        Try to acquire the distributed lock, blocking up to *acquire_timeout*
        seconds.  Returns True on success, False on timeout.
        """
        self._lock_value = str(uuid.uuid4())
        deadline = time.monotonic() + self._acquire_timeout

        while True:
            acquired = self._redis.set(
                self._lock_key,
                self._lock_value,
                nx=True,
                ex=self._lock_ttl,
            )
            if acquired:
                logger.info(
                    "Distributed lock acquired: key=%s, value=%s, ttl=%ds",
                    self._lock_key, self._lock_value, self._lock_ttl,
                )
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Failed to acquire distributed lock within %ds: key=%s",
                    self._acquire_timeout, self._lock_key,
                )
                return False

            holder_ttl = self._redis.ttl(self._lock_key)
            logger.info(
                "Waiting for distributed lock: key=%s, holder TTL=%ss, remaining wait=%.1fs",
                self._lock_key, holder_ttl, remaining,
            )
            time.sleep(min(self._retry_interval, remaining))

    def release(self) -> bool:
        """
        Release the lock **only if we still own it** (compare-and-delete via
        Lua script to avoid releasing another process's lock).
        """
        if not self._lock_value:
            return False

        result = self._redis.eval(_RELEASE_LUA, 1, self._lock_key, self._lock_value)
        if result:
            logger.info(
                "Distributed lock released: key=%s, value=%s",
                self._lock_key, self._lock_value,
            )
        else:
            logger.warning(
                "Distributed lock release skipped (not owner or expired): key=%s, value=%s",
                self._lock_key, self._lock_value,
            )
        self._lock_value = None
        return bool(result)

    # -- context-manager protocol --

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(
                f"Could not acquire distributed lock '{self._lock_key}' "
                f"within {self._acquire_timeout}s"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def get_semantic_group_lock(
    lock_ttl: int = DEFAULT_LOCK_TTL,
    acquire_timeout: int = DEFAULT_ACQUIRE_TIMEOUT,
    retry_interval: float = DEFAULT_RETRY_INTERVAL,
) -> DistributedLock:
    """
    Convenience factory: builds a DistributedLock for the global
    semantic-group critical section.
    """
    client = _build_redis_client()
    return DistributedLock(
        redis_client=client,
        lock_key=SEMANTIC_GROUP_LOCK_KEY,
        lock_ttl=lock_ttl,
        acquire_timeout=acquire_timeout,
        retry_interval=retry_interval,
    )


