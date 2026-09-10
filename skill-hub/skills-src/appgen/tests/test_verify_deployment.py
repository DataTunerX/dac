from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_deployment as verify  # noqa: E402
from appgen_common import AppGenError  # noqa: E402


def ready_resource(version: str = "1.0.0") -> dict:
    return {
        "spec": {
            "skillPolicy": {
                "skills": [{
                    "name": "museum-label",
                    "namespace": "default",
                    "version": version,
                }]
            }
        },
        "status": {
            "conditions": [{"type": "Available", "status": "True"}],
            "endpoint": {
                "address": "dac-museum-label-agent.default.svc.cluster.local",
                "port": 10100,
            },
        },
    }


class VerifyDeploymentTests(unittest.TestCase):
    @patch.object(verify, "http_json")
    @patch.object(verify, "k8s_request")
    @patch.object(verify, "find_skill")
    def test_verifies_publication_binding_availability_and_runtime_card(
        self, find_skill, k8s_request, http_json
    ):
        find_skill.return_value = {
            "name": "museum-label",
            "version": "1.0.0",
            "available_versions": ["1.0.0"],
        }
        k8s_request.return_value = ready_resource()
        http_json.return_value = {
            "name": "Museum-Label-Agent",
            "skills": [{"id": "museum-label"}],
        }

        result = verify.verify_once("museum-label", "museum-label-agent", "1.0.0")

        self.assertTrue(result["ok"])
        self.assertTrue(result["skill"]["published"])
        self.assertTrue(result["agent"]["available"])
        self.assertTrue(result["agent"]["skill_loaded"])
        self.assertEqual(
            result["agent"]["endpoint"],
            "http://dac-museum-label-agent.default.svc.cluster.local:10100/.well-known/agent-card.json",
        )

    @patch.object(verify, "k8s_request")
    @patch.object(verify, "find_skill")
    def test_rejects_agent_bound_to_a_different_version(self, find_skill, k8s_request):
        find_skill.return_value = {
            "name": "museum-label",
            "version": "1.1.0",
            "available_versions": ["1.0.0", "1.1.0"],
        }
        k8s_request.return_value = ready_resource(version="1.0.0")

        with self.assertRaisesRegex(AppGenError, "is not bound"):
            verify.verify_once("museum-label", "museum-label-agent", "1.1.0")

    @patch.object(verify.time, "sleep")
    @patch.object(verify, "verify_once")
    def test_waits_through_transient_rollout_state(self, verify_once, sleep):
        verify_once.side_effect = [
            AppGenError("not Available yet"),
            {"ok": True, "skill": {}, "agent": {}},
        ]

        result = verify.wait_for_deployment(
            "museum-label", "museum-label-agent", "1.0.0", timeout=5, interval=0.1
        )

        self.assertEqual(result["attempts"], 2)
        sleep.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
