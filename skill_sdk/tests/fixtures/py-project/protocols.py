"""Structural typing examples (Protocol) for LSP / read-code fixtures."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProcessingBackend(Protocol):
    """Contract for pluggable processors (goToDefinition / interface-style navigation)."""

    def transform(self, payload: str) -> str:
        """Transform a single payload string."""
        ...


class UpperCaseBackend:
    """Nominal implementation of :class:`ProcessingBackend`."""

    def transform(self, payload: str) -> str:
        return payload.upper()


def run_through_backend(backend: ProcessingBackend, value: str) -> str:
    """Dispatch through a backend (reference site for findReferences)."""
    return backend.transform(value)
