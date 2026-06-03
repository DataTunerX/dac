import concurrent.futures
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, TypeVar


logger = logging.getLogger("code_analysis_runtime")

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_MAX_WORKERS = 8
DEFAULT_BATCH_SIZE = 20

try:
    from langchain_core.rate_limiters import InMemoryRateLimiter
except Exception:  # pragma: no cover - production image provides langchain-core
    InMemoryRateLimiter = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CodeAnalysisRuntimeConfig:
    max_workers: int = DEFAULT_MAX_WORKERS
    batch_size: int = DEFAULT_BATCH_SIZE
    module_max_workers: int = DEFAULT_MAX_WORKERS
    llm_max_concurrency: int = DEFAULT_MAX_WORKERS
    requests_per_second: float = 0.0
    max_bucket_size: int = DEFAULT_MAX_WORKERS
    rate_check_seconds: float = 0.1


class CodeAnalysisRuntime:
    """Shared execution budget for code repository analysis.

    Code analysis has several phases that call the LLM. This object keeps
    worker counts, in-flight request limits, and optional LangChain rate
    limiting in one place so phases cannot accidentally multiply concurrency.
    """

    def __init__(self, config: CodeAnalysisRuntimeConfig | None = None):
        self.config = config or CodeAnalysisRuntimeConfig()
        self.max_workers = max(1, self.config.max_workers)
        self.batch_size = max(1, self.config.batch_size)
        self.module_max_workers = max(1, self.config.module_max_workers)
        self._llm_sem = threading.BoundedSemaphore(
            max(1, self.config.llm_max_concurrency)
        )
        self._rate_limiter = self._build_rate_limiter()

    @classmethod
    def from_env(
        cls,
        *,
        default_max_workers: int = DEFAULT_MAX_WORKERS,
        default_batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> "CodeAnalysisRuntime":
        max_workers = _read_int_env("CODE_ANALYSIS_MAX_WORKERS", default_max_workers)
        batch_size = _read_int_env("CODE_ANALYSIS_BATCH_SIZE", default_batch_size)
        module_workers = _read_int_env("CODE_ANALYSIS_MODULE_MAX_WORKERS", max_workers)
        llm_concurrency = _read_int_env(
            "CODE_ANALYSIS_LLM_MAX_CONCURRENCY",
            max_workers,
        )
        requests_per_second = _read_float_env(
            "CODE_ANALYSIS_REQUESTS_PER_SECOND",
            0.0,
        )
        max_bucket_size = _read_int_env(
            "CODE_ANALYSIS_MAX_BUCKET_SIZE",
            max(1, max_workers),
        )
        rate_check_seconds = _read_float_env(
            "CODE_ANALYSIS_RATE_CHECK_SECONDS",
            0.1,
        )
        return cls(
            CodeAnalysisRuntimeConfig(
                max_workers=max_workers,
                batch_size=batch_size,
                module_max_workers=module_workers,
                llm_max_concurrency=llm_concurrency,
                requests_per_second=requests_per_second,
                max_bucket_size=max_bucket_size,
                rate_check_seconds=rate_check_seconds,
            )
        )

    def _build_rate_limiter(self) -> Any | None:
        if self.config.requests_per_second <= 0:
            return None
        if InMemoryRateLimiter is None:
            logger.warning(
                "CODE_ANALYSIS_REQUESTS_PER_SECOND is set, but LangChain "
                "InMemoryRateLimiter is unavailable; only concurrency limiting is active."
            )
            return None
        return InMemoryRateLimiter(
            requests_per_second=self.config.requests_per_second,
            check_every_n_seconds=max(0.01, self.config.rate_check_seconds),
            max_bucket_size=max(1, self.config.max_bucket_size),
        )

    def invoke_llm(self, llm: Any, messages: Any, *, label: str = "llm.invoke") -> Any:
        if self._rate_limiter is not None:
            try:
                self._rate_limiter.acquire(blocking=True)
            except TypeError:
                self._rate_limiter.acquire()

        wait_start = time.perf_counter()
        acquired = self._llm_sem.acquire(blocking=False)
        if not acquired:
            logger.info("Waiting for code-analysis LLM slot: %s", label)
            self._llm_sem.acquire()
        wait_ms = int((time.perf_counter() - wait_start) * 1000)
        if wait_ms >= 100:
            logger.info("Acquired code-analysis LLM slot after %dms: %s", wait_ms, label)

        try:
            return llm.invoke(messages)
        finally:
            self._llm_sem.release()

    def map_unordered(
        self,
        items: Iterable[T],
        fn: Callable[[T], R],
        *,
        label: str,
        max_workers: int | None = None,
    ) -> Iterator[tuple[T, R | None, BaseException | None]]:
        item_list = list(items)
        if not item_list:
            return

        worker_count = min(
            len(item_list),
            max(1, max_workers if max_workers is not None else self.max_workers),
        )
        logger.info(
            "Code analysis phase starting: label=%s items=%d workers=%d",
            label,
            len(item_list),
            worker_count,
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_item = {executor.submit(fn, item): item for item in item_list}
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    yield item, future.result(), None
                except BaseException as exc:  # noqa: BLE001
                    yield item, None, exc


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(1, default)
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using %d", name, raw, default)
        return max(1, default)


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using %.3f", name, raw, default)
        return default
