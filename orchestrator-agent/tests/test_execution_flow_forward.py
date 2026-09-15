import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator_agent.orchestrator_agent_semantic_group as sg


class _Updater:
    def __init__(self):
        self.artifacts = []

    async def add_artifact(self, parts, name):
        text = getattr(parts[0], "text", None) if parts else None
        self.artifacts.append((name, text))


def _ef_frame(execution_id: str = "own-1-user-agent-t1") -> str:
    payload = {
        "schema_version": "v1",
        "execution_id": execution_id,
        "turn": 1,
        "stage": "pre_exec",
        "agent": "user-agent",
        "role": "initiator",
        "task": "lookup",
        "result": "U001",
    }
    return "[[DAC_EXECUTION_FLOW]] " + json.dumps(payload, ensure_ascii=False) + "\n"


@pytest.mark.asyncio
async def test_stream_forwards_execution_flow_and_strips_from_body():
    updater = _Updater()

    async def chunks():
        yield _ef_frame()
        yield "knowledge line\n"

    body, tasks = await sg.OrchestratorAgent.stream_a2a_collect_forward_progress_frames(
        chunks(),
        lambda text: text,
        updater,
        "progress",
    )

    assert body == "knowledge line"
    assert len(tasks) == 1
    assert tasks[0].execution_id == "own-1-user-agent-t1"
    assert any(name == "execution-flow" and "own-1-user-agent-t1" in (text or "") for name, text in updater.artifacts)
    assert all(name != "progress" or "DAC_EXECUTION_FLOW" not in (text or "") for name, text in updater.artifacts)
