"""Unit tests for PlannerAgent make_plan_jsonstring fallback.

Run:
  cd dac/skill-agent
  python -m pytest tests/test_make_plan_jsonstring.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.skill_agent import (  # noqa: E402
    NONE_TASK_DESCRIPTION,
    PLANNER_COT_INSTRUCTIONS_ZH_HISTORY_JSONSTRING,
    PlannerAgent,
    PlannerTask,
    TaskList,
)
from pydantic import ValidationError  # noqa: E402


def _card(name: str, desc: str) -> SimpleNamespace:
    skill = SimpleNamespace(
        id=name, name=name, description=desc, tags=[], examples=[],
    )
    return SimpleNamespace(name=name, description=desc, skills=[skill])


USER = _card("user-agent", "查询用户信息，将姓名解析为用户ID。")
ORDER = _card("order-agent", "查询订单。只能按用户ID过滤。")


def _planner(**attrs) -> PlannerAgent:
    inst = object.__new__(PlannerAgent)
    defaults = {
        "make_plan_max_attempts": 3,
        "llm": AsyncMock(),
        "metadata": {},
        "agent_id": "user-agent",
        "agent_name": "PlannerAgent",
        "get_history": AsyncMock(return_value=""),
    }
    defaults.update(attrs)
    for key, value in defaults.items():
        object.__setattr__(inst, key, value)
    return inst


def _valid_plan() -> dict:
    return {
        "thought_process": "Step1-6: 先查用户ID再查订单。",
        "original_query": "查询张三买了什么",
        "tasks": [
            {
                "id": 1,
                "description": "查询张三的用户ID",
                "agent": "user-agent",
                "depends_on": [],
            },
            {
                "id": 2,
                "description": "根据上游用户ID查询购买的商品",
                "agent": "order-agent",
                "depends_on": [1],
            },
        ],
    }


class TestTaskListRejectsBlankFields:
    def test_blank_thought_process(self):
        with pytest.raises(ValidationError):
            TaskList(
                thought_process="  ",
                original_query="q",
                tasks=[PlannerTask(id=1, description="d", agent="user-agent", depends_on=[])],
            )

    def test_blank_description(self):
        with pytest.raises(ValidationError):
            PlannerTask(id=1, description="", agent="user-agent", depends_on=[])

    def test_blank_agent(self):
        with pytest.raises(ValidationError):
            PlannerTask(id=1, description="d", agent="   ", depends_on=[])

    def test_empty_depends_on_ok(self):
        t = PlannerTask(id=1, description="d", agent="user-agent", depends_on=[])
        assert t.depends_on == []


class TestFormatLlmOutput:
    def test_direct_json(self):
        p = _planner()
        msg = AIMessage(content=json.dumps(_valid_plan(), ensure_ascii=False))
        parsed = p.format_llm_output(msg)
        assert parsed["tasks"][0]["agent"] == "user-agent"

    def test_markdown_fence(self):
        p = _planner()
        body = json.dumps(_valid_plan(), ensure_ascii=False)
        msg = AIMessage(content=f"```json\n{body}\n```")
        parsed = p.format_llm_output(msg)
        assert parsed is not None
        assert len(parsed["tasks"]) == 2

    def test_multimodal_list_content(self):
        p = _planner()
        body = json.dumps(_valid_plan(), ensure_ascii=False)
        msg = AIMessage(content=[{"type": "text", "text": body}])
        parsed = p.format_llm_output(msg)
        assert parsed["original_query"] == "查询张三买了什么"

    def test_garbage_returns_none(self):
        p = _planner()
        assert p.format_llm_output(AIMessage(content="not json at all")) is None


class TestHydrateTaskList:
    def test_valid(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER, ORDER])
        plan, err = p._hydrate_task_list(_valid_plan(), "查询张三买了什么", names)
        assert err is None
        assert plan is not None
        assert [t.agent for t in plan.tasks] == ["user-agent", "order-agent"]
        assert plan.tasks[1].depends_on == [1]

    def test_missing_depends_on(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "x",
            "original_query": "q",
            "tasks": [{"id": 1, "description": "查用户", "agent": "user-agent"}],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert plan is None
        assert "depends_on" in (err or "")

    def test_unknown_agent(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "x",
            "original_query": "q",
            "tasks": [{
                "id": 1, "description": "d", "agent": "ghost-agent", "depends_on": [],
            }],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert plan is None
        assert "ghost-agent" in (err or "")

    def test_empty_description_rejected(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "x",
            "original_query": "q",
            "tasks": [{"id": 1, "description": "  ", "agent": "user-agent", "depends_on": []}],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert plan is None
        assert "description" in (err or "")

    def test_empty_agent_rejected(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "x",
            "original_query": "q",
            "tasks": [{"id": 1, "description": "查用户", "agent": "", "depends_on": []}],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert plan is None
        assert "agent" in (err or "")

    def test_empty_thought_process_rejected(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "   ",
            "original_query": "q",
            "tasks": [{"id": 1, "description": "查用户", "agent": "user-agent", "depends_on": []}],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert plan is None
        assert "thought_process" in (err or "")

    def test_empty_depends_on_allowed(self):
        p = _planner()
        names = p._valid_plan_agent_names([USER])
        raw = {
            "thought_process": "x",
            "original_query": "q",
            "tasks": [{"id": 1, "description": "查用户", "agent": "user-agent", "depends_on": []}],
        }
        plan, err = p._hydrate_task_list(raw, "q", names)
        assert err is None
        assert plan is not None
        assert plan.tasks[0].depends_on == []
        assert plan.thought_process.strip()
        assert plan.original_query.strip()
        assert plan.tasks[0].description.strip()
        assert plan.tasks[0].agent.strip()


class TestJsonstringPrompt:
    def test_template_formats(self):
        p = _planner()
        messages = p._format_plan_messages(
            system_template=PLANNER_COT_INSTRUCTIONS_ZH_HISTORY_JSONSTRING,
            query="查询张三买了什么",
            agent_cards=[USER, ORDER],
            group_memory="",
            information="",
            history="",
        )
        assert messages
        joined = "\n".join(str(m.content) for m in messages)
        assert "thought_process" in joined
        assert "depends_on" in joined
        assert "查询张三买了什么" in joined


@pytest.mark.asyncio
async def test_make_plan_jsonstring_parses_text_json():
    p = _planner()
    p.llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps(_valid_plan(), ensure_ascii=False))
    )
    plan = await p.make_plan_jsonstring("查询张三买了什么", [USER, ORDER])
    assert [t.agent for t in plan.tasks] == ["user-agent", "order-agent"]
    assert plan.thought_process.strip()
    assert plan.original_query.strip()
    assert all(t.description.strip() and t.agent.strip() for t in plan.tasks)
    assert p.llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_make_plan_jsonstring_retries_then_succeeds():
    p = _planner()
    p.llm.ainvoke = AsyncMock(
        side_effect=[
            AIMessage(content="sorry I cannot"),
            AIMessage(content=json.dumps(_valid_plan(), ensure_ascii=False)),
        ]
    )
    plan = await p.make_plan_jsonstring("查询张三买了什么", [USER, ORDER])
    assert plan.tasks[0].agent == "user-agent"
    assert p.llm.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_make_plan_jsonstring_all_fail_returns_none_task():
    p = _planner()
    p.llm.ainvoke = AsyncMock(return_value=AIMessage(content="nope"))
    plan = await p.make_plan_jsonstring("hello", [USER])
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "NONE"
    assert plan.tasks[0].description == NONE_TASK_DESCRIPTION.strip()
    assert p.llm.ainvoke.await_count == 3


@pytest.mark.asyncio
async def test_make_plan_uses_tool_path_when_valid():
    p = _planner()
    jsonstring = AsyncMock(side_effect=AssertionError("jsonstring must not run"))
    object.__setattr__(p, "make_plan_jsonstring", jsonstring)
    with patch("agent.skill_agent.invoke_llm_with_tool", AsyncMock(return_value=_valid_plan())):
        plan = await p.make_plan("查询张三买了什么", [USER, ORDER])
    assert plan.tasks[1].agent == "order-agent"
    jsonstring.assert_not_awaited()


@pytest.mark.asyncio
async def test_make_plan_falls_back_after_three_tool_errors():
    p = _planner()
    fallback, err = p._hydrate_task_list(
        _valid_plan(), "查询张三买了什么", p._valid_plan_agent_names([USER, ORDER])
    )
    assert err is None
    jsonstring = AsyncMock(return_value=fallback)
    object.__setattr__(p, "make_plan_jsonstring", jsonstring)
    with patch(
        "agent.skill_agent.invoke_llm_with_tool",
        AsyncMock(side_effect=RuntimeError("grammar compile timed out")),
    ) as mocked_tool:
        plan = await p.make_plan("查询张三买了什么", [USER, ORDER])
    assert plan is fallback
    assert mocked_tool.await_count == 3
    assert jsonstring.await_count == 1
    assert jsonstring.await_args.args[0] == "查询张三买了什么"
