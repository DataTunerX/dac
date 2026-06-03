"""Unit tests for post-selection batch LLM scoring and knowledge block selection."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from agent.tools.knowledge_context_budget import (
    join_knowledge_blocks,
    score_trigger_chars,
    select_blocks_by_score,
    should_score_and_select,
    total_block_chars,
)
from agent.tools.knowledge_llm_score import (
    build_batch_score_prompt,
    score_knowledge_block_batch,
    score_knowledge_blocks_batch_parallel,
    split_blocks_into_batches,
)


def _block(block_id: str, text: str, **extra: Any) -> Dict[str, Any]:
    return {
        "id": block_id,
        "text": text,
        "metadata_value": f"summary-{block_id}",
        **extra,
    }


class _FakeLLM:
    def __init__(self, response: Dict[str, Any]):
        self.response = response
        self.calls: List[Any] = []

    async def ainvoke(self, messages: Any) -> Any:
        self.calls.append(messages)

        class _Answer:
            content = __import__("json").dumps(self.response)

        return _Answer()


def test_split_blocks_into_batches_keeps_whole_blocks():
    blocks = [_block(f"b{i}", "x" * 10) for i in range(12)]
    batches = split_blocks_into_batches(blocks, items_per_batch=5)
    assert len(batches) == 3
    assert len(batches[0]) == 5
    assert len(batches[1]) == 5
    assert len(batches[2]) == 2
    flat = [b for batch in batches for b in batch]
    assert flat == blocks


def test_should_score_and_select_below_trigger(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "60000")
    monkeypatch.setenv("DOC_KNOWLEDGE_LLM_SCORE_ENABLED", "true")
    blocks = [_block("a", "x" * 1000)]
    assert total_block_chars(blocks) == 1000
    assert should_score_and_select(blocks) is False


def test_should_score_and_select_above_trigger(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "1000")
    monkeypatch.setenv("DOC_KNOWLEDGE_LLM_SCORE_ENABLED", "true")
    blocks = [_block("a", "x" * 2000)]
    assert should_score_and_select(blocks) is True


def test_select_blocks_by_score_orders_and_limits(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "250")
    monkeypatch.setenv("DOC_KNOWLEDGE_MAX_BLOCKS", "10")

    blocks = [
        {**_block("low", "a" * 100), "relevance_score": 2.0},
        {**_block("high", "b" * 100), "relevance_score": 9.0},
        {**_block("mid", "c" * 100), "relevance_score": 7.0},
        {**_block("noise", "d" * 100), "relevance_score": 3.0},
    ]
    selected, report = select_blocks_by_score(blocks)
    ids = [b["id"] for b in selected]
    assert ids == ["high", "mid"]
    assert report["dropped_limit"] == 2
    assert report["output_chars"] == 200


def test_select_keeps_oversized_single_block_whole(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "100")
    monkeypatch.setenv("DOC_KNOWLEDGE_MAX_BLOCKS", "10")

    blocks = [{**_block("big", "x" * 500), "relevance_score": 9.0}]
    selected, report = select_blocks_by_score(blocks)
    assert len(selected) == 1
    assert len(selected[0]["text"]) == 500
    assert report["output_chars"] == 500


def test_join_knowledge_blocks_preserves_whole_blocks():
    blocks = [_block("a", "line1\nline2"), _block("b", "line3")]
    joined = join_knowledge_blocks(blocks)
    assert joined == "line1\nline2\nline3"


def test_build_batch_score_prompt_contains_all_block_ids():
    batch = [_block("A", "textA"), _block("B", "textB")]
    prompt = build_batch_score_prompt("退款流程", batch)
    assert "block_id: 0" in prompt
    assert "block_id: 1" in prompt
    assert "textA" in prompt
    assert "textB" in prompt


@pytest.mark.asyncio
async def test_score_knowledge_block_batch_writes_scores():
    batch = [_block("doc-1", "退款说明正文")]
    llm = _FakeLLM(
        {
            "scores": [
                {
                    "block_id": 0,
                    "relevance_score": 8.5,
                    "description": "核心退款流程",
                }
            ]
        }
    )
    await score_knowledge_block_batch(batch, query="q", llm=llm, batch_index=1, batch_total=1)
    assert batch[0]["relevance_score"] == 8.5
    assert batch[0]["score_description"] == "核心退款流程"


@pytest.mark.asyncio
async def test_get_text_by_ids_applies_score_select_when_over_budget(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "150")
    monkeypatch.setenv("DOC_KNOWLEDGE_LLM_SCORE_ENABLED", "true")

    from agent.dataservices_client import MetadataValuesResult

    result = MetadataValuesResult(
        status="success",
        data={
            "docs": [
                {"id": "a", "text": "a" * 100, "metadata_value": "sum-a"},
                {"id": "b", "text": "b" * 100, "metadata_value": "sum-b"},
                {"id": "c", "text": "c" * 100, "metadata_value": "sum-c"},
            ]
        },
    )

    class _BatchLLM:
        async def ainvoke(self, messages: Any) -> Any:
            import json

            prompt = messages[0].content if messages else ""
            count = prompt.count("block_id:")
            scores = [
                {
                    "block_id": i,
                    "relevance_score": [9.0, 8.0, 2.0][i],
                    "description": f"desc {i}",
                }
                for i in range(count)
            ]

            class _Answer:
                content = json.dumps({"scores": scores})

            return _Answer()

    text, meta = await result.get_text_by_ids(
        ["a", "b", "c"],
        query="问题",
        llm=_BatchLLM(),
        parse_output=lambda a: __import__("json").loads(getattr(a, "content")),
    )
    assert meta["score_select_applied"] is True
    assert "a" * 100 in text
    assert "b" * 100 not in text
    assert "c" * 100 not in text


@pytest.mark.asyncio
async def test_get_text_by_ids_skips_score_when_under_budget(monkeypatch):
    monkeypatch.setenv("DOC_KNOWLEDGE_SCORE_TRIGGER_CHARS", "10000")
    monkeypatch.setenv("DOC_KNOWLEDGE_LLM_SCORE_ENABLED", "true")

    from agent.dataservices_client import MetadataValuesResult

    result = MetadataValuesResult(
        status="success",
        data={"docs": [{"id": "a", "text": "hello", "metadata_value": "sum-a"}]},
    )

    class _FailLLM:
        async def ainvoke(self, prompt: str) -> Any:
            raise AssertionError("LLM should not be called when under budget")

    text, meta = await result.get_text_by_ids(
        ["a"],
        query="问题",
        llm=_FailLLM(),
    )
    assert text == "hello"
    assert meta["score_select_applied"] is False