"""Utility functions for the Python fixture project."""

from typing import Any


def format_output(data: str, prefix: str = "") -> str:
    """Format output with an optional prefix."""
    if prefix:
        return f"{prefix}: {data}"
    return data


def sanitize_input(data: Any) -> str:
    """Sanitize input data to string."""
    return str(data).strip()


def batch_process(items: list[str], batch_size: int = 10) -> list[str]:
    """Process items in batches."""
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results.extend([f"processed_{item}" for item in batch])
    return results
