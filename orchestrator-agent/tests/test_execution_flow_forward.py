import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_own_expert_upstream_skip_returns_text_and_empty_ef():
    """Skip after NONE upstream must stay a 2-tuple; a bare str crashes execute_collaborative."""
    ex = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    skip_text = sg.DEPENDENT_TASK_SKIP_MARKER + "上游依赖任务未返回有效数据"
    ex._llm_dependent_query_refine_enabled = MagicMock(return_value=True)
    ex._llm_refine_dependent_task_query = AsyncMock(return_value=skip_text)
    ex._log_data_flow = MagicMock()

    card = MagicMock()
    card.name = "user-sg"
    card.url = "http://localhost:10101"
    agent = MagicMock()
    agent._is_local_skill_task = MagicMock(return_value=False)
    agent.agent_cards = [card]

    task = sg.PlannerTask(
        id=2,
        description="根据用户ID查询用户详情",
        agent="user-sg",
        depends_on=[1],
    )

    result, expert_ef_tasks = await ex._execute_own_task_via_expert(
        task,
        "u",
        "r",
        "t",
        MagicMock(),
        agent,
        prior_task_results={1: sg.NONE_TASK_UNASSIGNED_RESULT},
        collaboration_original_query="根据订单号查购买用户详情",
    )

    assert result == skip_text
    assert expert_ef_tasks == []


def test_dag_enforcement_defaults_off(monkeypatch):
    monkeypatch.delenv("CROSS_SG_ENFORCE_DAG", raising=False)
    ex = object.__new__(sg.OrchestratorAgentExecutorSemanticGroup)
    assert ex._dag_enforcement_enabled() is False
    monkeypatch.setenv("CROSS_SG_ENFORCE_DAG", "true")
    assert ex._dag_enforcement_enabled() is True
