from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT.parent / "agent-contracts"
for path in (ROOT, CONTRACTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from routing_agent.protocol_v2 import (  # noqa: E402
    capability_report_legacy_view,
    parse_capability_report,
)


def _payload() -> dict:
    return {
        "protocol_version": "multi-agent-v2",
        "agent_id": "agent://art",
        "agent_name": "Art-Agent",
        "capability_manifest_version": "manifest-2",
        "runtime_status_ref": {"readiness_generation": 4},
        "lead": {
            "eligible": False,
            "ownership": "secondary",
            "reason": "Can provide iconographic evidence only.",
        },
        "contributions": [
            {
                "contribution_id": "iconography",
                "requirement_ids": ["r2"],
                "operations": ["extract", "interpret"],
                "produced_output_schemas": ["dac.claim-evidence/v1"],
            }
        ],
        "fit_score": 0.71,
    }


def test_routing_consumes_shared_v2_report() -> None:
    report = parse_capability_report(_payload())
    legacy = capability_report_legacy_view(report)
    assert legacy["can_handle"] is False
    assert legacy["can_contribute"] is True
    assert legacy["confidence"] == 0.71
    assert "iconography" in legacy["contribution"]
    assert legacy["execution_hint"]["protocol_version"] == "multi-agent-v2"


def test_routing_rejects_unsupported_major() -> None:
    payload = _payload()
    payload["protocol_version"] = "multi-agent-v3"
    with pytest.raises(ValidationError, match="unsupported protocol major"):
        parse_capability_report(payload)
