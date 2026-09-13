"""Protocol version parsing and negotiation."""

from __future__ import annotations

import re

PROTOCOL_VERSION = "multi-agent-v2"
SUPPORTED_MAJOR = 2
_VERSION_RE = re.compile(r"^multi-agent-v(?P<major>[0-9]+)(?:\.(?P<minor>[0-9]+))?$")


class UnsupportedProtocolVersion(ValueError):
    """Raised when a message uses an unsupported protocol major version."""


def protocol_major(value: str) -> int:
    """Return the protocol major or raise for malformed values."""

    match = _VERSION_RE.fullmatch((value or "").strip())
    if not match:
        raise UnsupportedProtocolVersion(f"invalid protocol_version: {value!r}")
    return int(match.group("major"))


def ensure_supported_protocol(value: str) -> str:
    """Accept compatible minor versions and reject unsupported majors."""

    normalized = (value or "").strip()
    major = protocol_major(normalized)
    if major != SUPPORTED_MAJOR:
        raise UnsupportedProtocolVersion(
            f"unsupported protocol major v{major}; supported major is v{SUPPORTED_MAJOR}"
        )
    return normalized
