"""Unit tests for post-search batch LLM scoring and snippet selection.

Uses FakeLLM mocks — no real API calls. For live LLM E2E see test_snippet_llm_score_e2e.py.
"""


from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import pytest

from agent.tools.snippet_context_budget import (
    score_trigger_chars,
    select_snippets_by_score,
    should_score_and_select,
    total_snippet_chars,
)
from agent.tools.snippet_llm_score import (
    build_batch_score_prompt,
    score_snippet_batch,
    score_snippets_batch_parallel,
    split_snippets_into_batches,
)


def _snippet(name: str, code: str, **extra: Any) -> Dict[str, Any]:
    return {
        "file_path": f"src/{name}.py",
        "name": name,
        "line_no": "1-10",
        "code_content": code,
        "source": "skill_read_code",
        **extra,
    }


class _FakeLLM:
    def __init__(self, response: Dict[str, Any]):
        self.response = response
        self.calls: List[Any] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_FakeLLM":
        return self

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append(messages)

        class _Answer:
            content = __import__("json").dumps(self.response)
            tool_calls = [
                {
                    "name": "score_snippets",
                    "args": self.response,
                    "id": "call_1",
                }
            ]

        return _Answer()


def test_split_snippets_into_batches_keeps_whole_blocks():
    snippets = [_snippet(f"b{i}", "x" * 10) for i in range(12)]
    batches = split_snippets_into_batches(snippets, items_per_batch=5)
    assert len(batches) == 3
    assert len(batches[0]) == 5
    assert len(batches[1]) == 5
    assert len(batches[2]) == 2
    flat = [s for batch in batches for s in batch]
    assert flat == snippets


def test_should_score_and_select_below_trigger(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "60000")
    monkeypatch.setenv("SNIPPET_LLM_SCORE_ENABLED", "true")
    snippets = [_snippet("a", "x" * 1000)]
    assert total_snippet_chars(snippets) == 1000
    assert should_score_and_select(snippets) is False


def test_should_score_and_select_above_trigger(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "1000")
    monkeypatch.setenv("SNIPPET_LLM_SCORE_ENABLED", "true")
    snippets = [_snippet("a", "x" * 2000)]
    assert should_score_and_select(snippets) is True


def test_select_snippets_by_score_orders_and_limits(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "250")
    monkeypatch.setenv("CODE_SEARCH_MAX_SNIPPETS", "10")

    snippets = [
        {**_snippet("low", "a" * 100), "relevance_score": 2.0},
        {**_snippet("high", "b" * 100), "relevance_score": 9.0},
        {**_snippet("mid", "c" * 100), "relevance_score": 7.0},
        {**_snippet("noise", "d" * 100), "relevance_score": 3.0},
    ]
    selected, report = select_snippets_by_score(snippets)
    names = [s["name"] for s in selected]
    assert names == ["high", "mid"]
    assert report["dropped_limit"] == 2
    assert report["output_chars"] == 200


def test_build_batch_score_prompt_contains_all_snippet_ids():
    batch = [_snippet("A", "codeA"), _snippet("B", "codeB")]
    prompt = build_batch_score_prompt("统计销售额", batch)
    assert "snippet_id: 0" in prompt
    assert "snippet_id: 1" in prompt
    assert "codeA" in prompt
    assert "codeB" in prompt


@pytest.mark.asyncio
async def test_score_snippet_batch_writes_scores():
    batch = [_snippet("svc", "def run(): pass")]
    llm = _FakeLLM(
        {
            "scores": [
                {
                    "snippet_id": 0,
                    "relevance_score": 8.5,
                    "description": "核心服务逻辑",
                }
            ]
        }
    )
    await score_snippet_batch(batch, query="q", llm=llm, batch_index=1, batch_total=1)
    assert batch[0]["relevance_score"] == 8.5
    assert batch[0]["score_description"] == "核心服务逻辑"


@pytest.mark.asyncio
async def test_score_snippets_batch_parallel_multiple_batches():
    snippets = [_snippet(f"b{i}", f"code{i}") for i in range(6)]

    class _BatchLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools: Any, **kwargs: Any) -> "_BatchLLM":
            return self

        async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
            self.calls += 1
            import json

            prompt = messages[0].content if messages else ""
            count = prompt.count("snippet_id:")
            scores = [
                {
                    "snippet_id": i,
                    "relevance_score": 8.0,
                    "description": f"desc {i}",
                }
                for i in range(count)
            ]

            class _Answer:
                content = json.dumps({"scores": scores})
                tool_calls = [
                    {
                        "name": "score_snippets",
                        "args": {"scores": scores},
                        "id": "call_1",
                    }
                ]

            return _Answer()

    llm = _BatchLLM()
    result = await score_snippets_batch_parallel(
        snippets,
        query="q",
        llm=llm,
    )
    assert len(result) == 6
    assert llm.calls == 2  # batch_size default 5 -> [5,1]
    assert all(s.get("relevance_score") == 8.0 for s in result)


def test_score_trigger_chars_env(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "12345")
    assert score_trigger_chars() == 12345


def test_should_score_and_select_respects_disabled_flag(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "10")
    monkeypatch.setenv("SNIPPET_LLM_SCORE_ENABLED", "false")
    snippets = [_snippet("a", "x" * 100)]
    assert should_score_and_select(snippets) is False


def test_select_respects_max_snippets(monkeypatch):
    monkeypatch.setenv("CODE_SEARCH_SCORE_TRIGGER_CHARS", "100000")
    monkeypatch.setenv("CODE_SEARCH_MAX_SNIPPETS", "2")
    snippets = [
        {**_snippet("a", "a"), "relevance_score": 9.0},
        {**_snippet("b", "b"), "relevance_score": 8.0},
        {**_snippet("c", "c"), "relevance_score": 7.0},
    ]
    selected, report = select_snippets_by_score(snippets)
    assert len(selected) == 2
    assert [s["name"] for s in selected] == ["a", "b"]
    assert report["dropped_limit"] == 1
