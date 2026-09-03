"""Unit tests for soft capability preference + coverage duty in SG ReAct."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest
from a2a.types import AgentCard

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.react import ReActRunner


def _card(name: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=name,
        url=f"http://{name}",
        version="1",
        capabilities={"streaming": True},
        skills=[],
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
    )


class _FakeLLM:
    def bind(self, **_kwargs):
        return self

    def bind_tools(self, tools, **_kwargs):
        return self


def _runner() -> ReActRunner:
    def _desc(member, card, _name_to_agent):
        return f"tool for {card.name}"

    async def _invoke(*_args, **_kwargs):
        return "ok"

    return ReActRunner(
        llm=_FakeLLM(),
        invoke_agent=_invoke,
        build_tool_description=_desc,
        agent_name="TestSG",
        compaction=None,
    )


def test_preference_section_and_tool_annotation_are_soft():
    runner = _runner()
    agents = [
        (SimpleNamespace(descriptor_type="structured"), _card("OrdersAgent")),
        (SimpleNamespace(descriptor_type="structured"), _card("StoreAgent")),
    ]
    pref = {
        "enabled": True,
        "execution_strategy": "single",
        "confidence": 0.93,
        "reason": "StoreAgent preferred by capability check",
        "preferred_handlers": ["StoreAgent"],
        "preferred_contributors": [],
        "member_evidence": [
            {
                "agent_name": "StoreAgent",
                "role": "handle",
                "confidence": 0.93,
                "matched_evidence": ["门店"],
                "reason": "store domain",
            }
        ],
    }

    section = runner._format_capability_preference_section(pref)
    assert "preferred_handlers: ['StoreAgent']" in section
    assert "soft guidance, not an exclusive allowlist" in section

    tools, tool_to_agent = runner._build_agent_tools(
        agents,
        {},
        capability_preference=pref,
    )
    agent_tools = [t for t in tools if t.name != "finish"]
    assert len(agent_tools) == 2
    assert "StoreAgent" in agent_tools[0].description or "store" in agent_tools[0].name
    assert any(
        t.description.startswith("[PREFERRED_HANDLER_BY_CAPABILITY_CHECK]")
        for t in agent_tools
    )
    assert runner._preferred_handler_tool_names(tool_to_agent, pref)
    # Full pool retained.
    assert {getattr(card, "name") for _m, card in tool_to_agent.values()} == {
        "OrdersAgent",
        "StoreAgent",
    }


@pytest.mark.asyncio
async def test_coverage_duty_blocks_finish_until_preferred_tried(monkeypatch):
    runner = _runner()
    agents = [
        (SimpleNamespace(descriptor_type="structured"), _card("WrongAgent")),
        (SimpleNamespace(descriptor_type="structured"), _card("RightAgent")),
    ]
    pref = {
        "enabled": True,
        "preferred_handlers": ["RightAgent"],
        "preferred_contributors": [],
        "execution_strategy": "single",
        "confidence": 0.9,
        "reason": "RightAgent preferred",
        "member_evidence": [],
    }

    class FakeAI:
        def __init__(self, tool_calls, content=""):
            self.tool_calls = tool_calls
            self.content = content

    # Step1: call wrong agent. Step2: try finish. Step3: call preferred. Step4: finish.
    script = [
        FakeAI(
            [
                {
                    "name": "structured_WrongAgent",
                    "args": {"query": "q"},
                    "id": "c1",
                }
            ],
            content="try wrong",
        ),
        FakeAI(
            [
                {
                    "name": "finish",
                    "args": {"final_answer": "cannot answer"},
                    "id": "c2",
                }
            ],
            content="finish early",
        ),
        FakeAI(
            [
                {
                    "name": "structured_RightAgent",
                    "args": {"query": "q"},
                    "id": "c3",
                }
            ],
            content="try preferred",
        ),
        FakeAI(
            [
                {
                    "name": "finish",
                    "args": {"final_answer": "answered by preferred"},
                    "id": "c4",
                }
            ],
            content="done",
        ),
    ]
    calls: List[str] = []

    async def fake_ainvoke(_llm, _messages, **_kwargs):
        if not script:
            raise AssertionError("unexpected extra LLM call")
        msg = script.pop(0)
        # Capture whether coverage nudge was injected before this decision.
        contents = [str(getattr(m, "content", "")) for m in _messages]
        if any("Coverage duty from prior capability preference" in c for c in contents):
            calls.append("after_coverage_nudge")
        else:
            calls.append(msg.content or msg.tool_calls[0]["name"])
        return msg

    invoked: List[str] = []

    async def fake_invoke(member, card, query, httpx_client=None, invoke_context=None):
        invoked.append(getattr(card, "name", ""))
        return f"result-from-{card.name}"

    runner.invoke_agent = fake_invoke
    monkeypatch.setattr(runner, "_ainvoke_ai_message", fake_ainvoke)
    monkeypatch.setattr(
        runner,
        "_emit_progress",
        AsyncNoop(),
    )

    # Patch make_tool_name to stable predictable names used above.
    monkeypatch.setattr(
        ReActRunner,
        "make_tool_name",
        classmethod(lambda cls, member, card: f"structured_{card.name}"),
    )

    result = await runner.run(
        user_query="need preferred data",
        prior_context="",
        agents=agents,
        name_to_agent={},
        react_max_steps=8,
        nudge_retries=0,
        capability_preference=pref,
    )

    assert "answered by preferred" in result
    assert "WrongAgent" in invoked
    assert "RightAgent" in invoked
    assert "after_coverage_nudge" in calls
    # Preferred was not skipped entirely.
    assert invoked.index("RightAgent") > invoked.index("WrongAgent")


class AsyncNoop:
    async def __call__(self, *args, **kwargs):
        return None
