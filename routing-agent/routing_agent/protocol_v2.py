"""Boundary adapters between V2 contracts and the legacy routing engine.

Phase 1 makes routing understand the shared envelope without enabling V2 lead
selection.  Phase 3 can replace this legacy view once hard capability gates are
the active routing policy.
"""

from __future__ import annotations

from typing import Any, Dict

from agent_contracts import (
    CapabilityReportV2,
)
from agent_contracts import (
    capability_report_legacy_view as _shared_legacy_view,
)


def parse_capability_report(payload: Dict[str, Any]) -> CapabilityReportV2:
    """Parse a versioned report, rejecting malformed and unsupported versions."""

    return CapabilityReportV2.model_validate(payload)


def capability_report_legacy_view(report: CapabilityReportV2) -> Dict[str, Any]:
    """Project V2 feedback into fields consumed by the current routing path."""

    return _shared_legacy_view(report)
