"""Phase 0.6: a capability-check or pre-plan request must not rebroadcast.

Observed on `test-cluster`: routing checked 13 agents, then each of the three
pre-plan candidates ran its own 13-agent capability broadcast, so one user query
cost roughly 52 capability model calls.

Run::

    cd /path/to/dac/skill-agent
    python -m pytest tests/test_nested_broadcast_suppression.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod in (
    "skill_sdk", "skill_sdk.skill", "skill_sdk.skill.runner",
    "skill_sdk.tool", "skill_sdk.tool.code_execution",
    "langfuse", "langfuse.langchain", "langfuse._client",
    "model_sdk", "model_sdk.api", "model_sdk.api.model_manager",
    "agent.broadcast_capability_check", "agent.agent_card_resolve",
    "agent.agentregistry_client", "agent.dataservices_client",
    "agent.tool_call_utils",
):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules["agent.broadcast_capability_check"].ROUTING_AGENT_POOL_KEY = "routing_agent_pool"

from agent.skill_agent import (  # noqa: E402
    SUPPRESS_NESTED_BROADCAST_KEY,
    SkillAgentExecutor,
)


def _executor(metadata: dict) -> SkillAgentExecutor:
    inst = object.__new__(SkillAgentExecutor)
    object.__setattr__(inst, "metadata", metadata)
    return inst


class TestNestedBroadcastSuppression:
    def test_rebroadcast_allowed_by_default(self) -> None:
        executor = _executor({})
        with patch.dict("os.environ", {}, clear=False):
            assert executor._nested_broadcast_suppressed() is False
            assert executor._sg_capability_rebroadcast_enabled() is True

    def test_request_metadata_suppresses_rebroadcast(self) -> None:
        executor = _executor({SUPPRESS_NESTED_BROADCAST_KEY: True})
        assert executor._nested_broadcast_suppressed() is True
        assert executor._sg_capability_rebroadcast_enabled() is False

    def test_metadata_false_leaves_rebroadcast_enabled(self) -> None:
        executor = _executor({SUPPRESS_NESTED_BROADCAST_KEY: False})
        assert executor._nested_broadcast_suppressed() is False
        assert executor._sg_capability_rebroadcast_enabled() is True

    def test_agent_side_env_can_suppress_independently(self) -> None:
        executor = _executor({})
        with patch.dict(
            "os.environ", {"SKILL_AGENT_SUPPRESS_NESTED_BROADCAST": "true"}, clear=False
        ):
            assert executor._nested_broadcast_suppressed() is True
            assert executor._sg_capability_rebroadcast_enabled() is False

    def test_suppression_wins_over_the_legacy_enable_flag(self) -> None:
        executor = _executor({SUPPRESS_NESTED_BROADCAST_KEY: True})
        with patch.dict(
            "os.environ", {"ENABLE_SG_CAPABILITY_REBROADCAST": "true"}, clear=False
        ):
            assert executor._sg_capability_rebroadcast_enabled() is False

    def test_missing_metadata_is_not_an_error(self) -> None:
        executor = _executor(None)  # type: ignore[arg-type]
        assert executor._nested_broadcast_suppressed() is False


class TestRoutingPoolIsRequestScoped:
    """The executor is process-wide; a pool must not outlive its request.

    Pre-plan requests carry no pool, so without a reset a candidate would plan
    against collaborators selected for an unrelated earlier query.
    """

    def _executor_with_pool(self, pool: list) -> SkillAgentExecutor:
        inst = object.__new__(SkillAgentExecutor)
        object.__setattr__(inst, "metadata", {})
        object.__setattr__(inst, "_routing_agent_pool", pool)
        object.__setattr__(inst, "_routing_skip_broadcast_used", True)
        return inst

    def test_request_without_a_pool_clears_the_previous_one(self) -> None:
        executor = self._executor_with_pool([{"agent_name": "Stale-Agent"}])
        with patch(
            "agent.skill_agent.sg_broadcast.parse_routing_agent_pool", return_value=[]
        ):
            executor._init_routing_pool_from_metadata({"run_id": "new-request"})
        assert executor._routing_agent_pool == []
        assert executor._routing_skip_broadcast_used is False

    def test_pre_plan_request_clears_the_pool_before_the_fast_path(self) -> None:
        """The real path: `execute` returns through the pre-plan fast path.

        Resetting inside the post-fast-path setup would never run for pre-plan
        requests, which carry no pool of their own.
        """
        import inspect

        from agent.skill_agent_turn import SkillAgentExecutorWithTurns

        for klass in (SkillAgentExecutor, SkillAgentExecutorWithTurns):
            source = inspect.getsource(klass.execute)
            reset_at = source.find("_init_routing_pool_from_metadata")
            fast_path_at = source.find("handle_pre_make_plan")
            assert reset_at != -1, f"{klass.__name__} never resets the routing pool"
            assert fast_path_at != -1
            assert reset_at < fast_path_at, (
                f"{klass.__name__} returns through the pre-plan fast path before "
                "resetting the routing pool"
            )

    def test_request_with_a_pool_replaces_the_previous_one(self) -> None:
        executor = self._executor_with_pool([{"agent_name": "Stale-Agent"}])
        fresh = [{"agent_name": "Fresh-Agent"}]
        with patch(
            "agent.skill_agent.sg_broadcast.parse_routing_agent_pool", return_value=fresh
        ):
            executor._init_routing_pool_from_metadata({"routing_agent_pool": fresh})
        assert executor._routing_agent_pool == fresh
