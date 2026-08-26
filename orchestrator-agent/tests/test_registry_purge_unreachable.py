"""Unit tests for probe-driven registry purge helpers."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator_agent.broadcast_capability_check as bcc


def test_is_unreachable_registry_error_detects_dns():
    assert bcc._is_unreachable_registry_error(
        OSError("[Errno -2] Name does not resolve")
    )
    assert bcc._is_unreachable_registry_error(
        ConnectionRefusedError("Connection refused")
    )
    assert not bcc._is_unreachable_registry_error(TimeoutError("read timed out"))
    assert not bcc._is_unreachable_registry_error(ValueError("bad json"))
