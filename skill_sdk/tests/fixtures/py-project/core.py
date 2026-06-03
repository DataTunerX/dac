"""Core service module for the Python fixture project."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ServiceConfig:
    """Configuration for the service layer."""
    timeout: int = 30
    retries: int = 3
    endpoint: str = "http://localhost:8080"


class DataProcessor:
    """Base class for data processing operations."""

    def process(self, data: str) -> str:
        """Process raw data and return the result."""
        return f"processed: {data}"

    def validate(self, data: str) -> bool:
        """Validate input data."""
        return len(data) > 0


class AdvancedProcessor(DataProcessor):
    """Advanced processor with extended capabilities."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self._cache: dict = {}

    def process(self, data: str) -> str:
        """Process data with advanced logic."""
        if data in self._cache:
            return self._cache[data]
        result = super().process(data)
        enhanced = self._apply_enhancements(result)
        self._cache[data] = enhanced
        return enhanced

    def validate(self, data: str) -> bool:
        """Validate data with additional checks."""
        if not super().validate(data):
            return False
        return len(data) < 10000

    def _apply_enhancements(self, data: str) -> str:
        """Apply post-processing enhancements."""
        return f"[enhanced] {data}"


class RequestHandler:
    """Handles incoming API requests by delegating to the processor."""

    def __init__(self, processor: DataProcessor):
        self._processor = processor
        self._request_count = 0

    def handle(self, payload: str) -> str:
        """Handle a single request."""
        self._request_count += 1
        if not self._processor.validate(payload):
            raise ValueError(f"Invalid payload: {payload}")
        return self._processor.process(payload)

    @property
    def request_count(self) -> int:
        """Number of requests handled."""
        return self._request_count


def build_pipeline(
    config: ServiceConfig,
    handlers: Optional[List[RequestHandler]] = None,
) -> AdvancedProcessor:
    """Build the processing pipeline with the given configuration."""
    processor = AdvancedProcessor(config)
    # Rewire optional handlers onto this processor (DI-style fixtures for LSP).
    for handler in handlers or []:
        handler._processor = processor  # intentional fixture wiring
    return processor


def finalize_result(result: str) -> str:
    """Finalize and format the processing result."""
    return f"[ok] {result}"
