"""Tests for skill_search subsystem."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel, Field

from skill_sdk.api.base import Skill
from skill_sdk.skill.skill_search import (
    MAX_PER_BATCH,
    _format_skill_for_prompt,
    _parse_batch_result,
    _split_into_batches,
    run_skill_search,
)


# ---------------------------------------------------------------------------
# Fake skills for testing
# ---------------------------------------------------------------------------

_FAKE_SKILL_A = Skill(
    name="code-search",
    description="Search code files using grep and regex patterns.",
    version="1.0.0",
    detail="",
    scripts=[],
)

_FAKE_SKILL_B = Skill(
    name="extract-pdf",
    description="Extract text and images from PDF documents.",
    version="1.0.0",
    detail="",
    scripts=[],
)

_FAKE_SKILL_C = Skill(
    name="web-fetch",
    description="Fetch web page content and extract text.",
    version="1.0.0",
    detail="",
    scripts=[],
)

_FAKE_SKILL_D = Skill(
    name="template-renderer",
    description="Render Jinja2 templates with context data.",
    version="1.0.0",
    detail="",
    scripts=[],
)


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------

class TestFormatSkillForPrompt(unittest.TestCase):
    def test_basic_format(self) -> None:
        result = _format_skill_for_prompt(_FAKE_SKILL_A)
        self.assertIn("name: code-search", result)
        self.assertIn("Search code files", result)

    def test_includes_description(self) -> None:
        result = _format_skill_for_prompt(_FAKE_SKILL_B)
        self.assertIn("name: extract-pdf", result)
        self.assertIn("Extract text and images", result)


class TestSplitIntoBatches(unittest.TestCase):
    def test_empty(self) -> None:
        batches = _split_into_batches([], batch_size=100)
        self.assertEqual(batches, [])

    def test_single_batch(self) -> None:
        skills = [_FAKE_SKILL_A, _FAKE_SKILL_B, _FAKE_SKILL_C]
        batches = _split_into_batches(skills, batch_size=100)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)

    def test_multiple_batches(self) -> None:
        skills = [_FAKE_SKILL_A, _FAKE_SKILL_B, _FAKE_SKILL_C, _FAKE_SKILL_D] * 50  # 200 items
        batches = _split_into_batches(skills, batch_size=80)
        self.assertEqual(len(batches), 3)
        self.assertEqual(len(batches[0]), 80)
        self.assertEqual(len(batches[1]), 80)
        self.assertEqual(len(batches[2]), 40)


class TestParseBatchResult(unittest.TestCase):
    def test_plain_array_of_objects(self) -> None:
        result = _parse_batch_result(
            '[{"name": "a", "score": 85, "reason": "good match"}, {"name": "b", "score": 60, "reason": "ok"}]'
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[0]["score"], 85)
        self.assertEqual(result[0]["reason"], "good match")
        self.assertEqual(result[1]["name"], "b")
        self.assertEqual(result[1]["score"], 60)

    def test_markdown_code_block(self) -> None:
        result = _parse_batch_result(
            '```json\n[{"name": "a", "score": 90, "reason": "x"}]\n```'
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[0]["score"], 90)

    def test_empty_array(self) -> None:
        result = _parse_batch_result("[]")
        self.assertEqual(result, [])

    def test_extra_text(self) -> None:
        result = _parse_batch_result(
            'some text [{"name": "a", "score": 70, "reason": "ok"}] more text'
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "a")

    def test_invalid_json(self) -> None:
        result = _parse_batch_result("not json at all")
        self.assertIsNone(result)

    def test_single_object_not_array(self) -> None:
        result = _parse_batch_result('{"name": "a", "score": 80, "reason": "x"}')
        self.assertIsNone(result)

    def test_legacy_string_array(self) -> None:
        result = _parse_batch_result('["a", "b", "c"]')
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[0]["score"], 80)  # default score for legacy format
        self.assertEqual(result[0]["reason"], "")

    def test_score_clamped(self) -> None:
        result = _parse_batch_result(
            '[{"name": "a", "score": 150, "reason": "x"}, {"name": "b", "score": -10, "reason": "y"}]'
        )
        self.assertEqual(result[0]["score"], 100)
        self.assertEqual(result[1]["score"], 0)

    def test_missing_score_and_reason(self) -> None:
        result = _parse_batch_result('[{"name": "a"}]')
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[0]["score"], 0)
        self.assertEqual(result[0]["reason"], "")


# ---------------------------------------------------------------------------
# Unit tests: run_skill_search (with mocked LLM)
# ---------------------------------------------------------------------------

class TestRunSkillSearch(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.skills = [_FAKE_SKILL_A, _FAKE_SKILL_B, _FAKE_SKILL_C, _FAKE_SKILL_D]

    def _make_llm(self, batch_content: str, selector_content: str = "") -> AsyncMock:
        """Return a mock LLM that returns *batch_content* for the BATCH call(s)
        and *selector_content* for the SELECTOR call."""
        mock_llm = AsyncMock()

        def _side_effect(*args, **kwargs):
            resp = MagicMock()
            # The first call(s) are BATCH; the last is SELECTOR
            # We distinguish by looking at the system message content
            messages = kwargs.get("input", [])
            if args:
                messages = args[0] if isinstance(args[0], list) else [args[0]]
            # Simple heuristic: if content looks like {"skill": ...} it's SELECTOR
            resp.content = selector_content if selector_content else batch_content
            return resp

        # For simplicity, we just return the batch content for all calls,
        # but the selector-only tests use a different mock.
        if selector_content:
            mock_llm.ainvoke = AsyncMock(side_effect=_side_effect)
        else:
            mock_resp = MagicMock()
            mock_resp.content = batch_content
            mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        return mock_llm

    async def test_search_returns_candidates(self) -> None:
        mock_llm = AsyncMock()
        batch_resp = MagicMock()
        batch_resp.content = '[{"name": "code-search", "score": 90, "reason": "good"}, {"name": "extract-pdf", "score": 70, "reason": "ok"}]'
        selector_resp = MagicMock()
        selector_resp.content = '{"skill": "code-search", "score": 95, "reason": "best match"}'
        mock_llm.ainvoke = AsyncMock(side_effect=[batch_resp, selector_resp])

        result = await run_skill_search(
            llm=mock_llm,
            query="search text in code",
            skills=self.skills,
            batch_size=100,
            max_concurrent_batches=2,
        )

        self.assertTrue(result["found"])
        self.assertEqual(result["selected_skill"], "code-search")
        self.assertEqual(result["score"], 95)
        self.assertIn("description", result["candidates"][0])
        self.assertIn("score", result["candidates"][0])
        self.assertIn("reason", result["candidates"][0])
        # Verify candidates sorted by score descending
        self.assertGreaterEqual(result["candidates"][0]["score"], result["candidates"][1]["score"])

    async def test_search_empty_skills(self) -> None:
        mock_llm = AsyncMock()
        result = await run_skill_search(llm=mock_llm, query="test", skills=[])
        self.assertFalse(result["found"])
        self.assertIsNone(result["selected_skill"])
        self.assertEqual(result["candidates"], [])

    async def test_search_deduplicates(self) -> None:
        mock_llm = AsyncMock()
        batch_resp = MagicMock()
        batch_resp.content = '[{"name": "code-search", "score": 90, "reason": "x"}, {"name": "code-search", "score": 80, "reason": "x"}, {"name": "extract-pdf", "score": 70, "reason": "x"}]'
        selector_resp = MagicMock()
        selector_resp.content = '{"skill": "code-search", "score": 90, "reason": "top"}'
        mock_llm.ainvoke = AsyncMock(side_effect=[batch_resp, selector_resp])

        result = await run_skill_search(
            llm=mock_llm,
            query="test",
            skills=self.skills,
            batch_size=100,
        )

        self.assertEqual(len(result["candidates"]), 2)

    async def test_search_empty_llm_response(self) -> None:
        mock_llm = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.content = "[]"
        mock_llm.ainvoke.return_value = mock_resp

        result = await run_skill_search(llm=mock_llm, query="test", skills=self.skills)
        self.assertFalse(result["found"])
        self.assertIsNone(result["selected_skill"])
        self.assertEqual(len(result["candidates"]), 0)

    async def test_search_invalid_llm_response(self) -> None:
        mock_llm = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.content = "no, none of these are relevant"
        mock_llm.ainvoke.return_value = mock_resp

        result = await run_skill_search(llm=mock_llm, query="test", skills=self.skills)
        self.assertFalse(result["found"])
        self.assertIsNone(result["selected_skill"])

    async def test_search_multiple_batches(self) -> None:
        """Verify that multiple batches are processed concurrently."""
        all_skills = [_FAKE_SKILL_A, _FAKE_SKILL_B, _FAKE_SKILL_C, _FAKE_SKILL_D] * 50

        mock_llm = AsyncMock()
        batch_resp = MagicMock()
        batch_resp.content = '[{"name": "code-search", "score": 90, "reason": "x"}, {"name": "web-fetch", "score": 80, "reason": "x"}]'
        selector_resp = MagicMock()
        selector_resp.content = '{"skill": "code-search", "score": 95, "reason": "best"}'
        # 3 batch calls + 1 selector call = 4 total
        mock_llm.ainvoke = AsyncMock(side_effect=[batch_resp, batch_resp, batch_resp, selector_resp])

        result = await run_skill_search(
            llm=mock_llm,
            query="test",
            skills=all_skills,
            batch_size=80,
            max_concurrent_batches=2,
        )

        # 200 skills / 80 per batch = 3 batches, each returning 2 names
        # After dedup: 2 unique candidates, selector picks 1
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["selected_skill"], "code-search")
        # 3 batch calls + 1 selector call = 4 total
        self.assertEqual(mock_llm.ainvoke.call_count, 4)


# ---------------------------------------------------------------------------
# Integration tests: SkillRunner with use_skill_search
# ---------------------------------------------------------------------------

class TestSkillRunnerSkillSearchMode(unittest.TestCase):
    """Verify that SkillRunner correctly handles use_skill_search flag."""

    def setUp(self) -> None:
        from skill_sdk.skill.runner import SkillRunner

        mock_llm = MagicMock()
        self.mock_llm = mock_llm
        self.SkillRunner = SkillRunner

    def test_use_skill_search_false_binds_all_tools(self) -> None:
        """Default mode: all tools are bound (no change from before)."""
        runner = self.SkillRunner(
            llm=self.mock_llm,
            use_skill_search=False,
        )
        names = {t.name for t in runner._runner_tools}
        self.assertIn("plan_cmd", names)
        self.assertIn("finish", names)

    def test_use_skill_search_true_also_binds_all_tools(self) -> None:
        """In skill_search mode, all tools are still bound (no tool filtering needed)."""
        runner = self.SkillRunner(
            llm=self.mock_llm,
            use_skill_search=True,
        )
        names = {t.name for t in runner._runner_tools}
        self.assertIn("plan_cmd", names)
        self.assertIn("finish", names)

    def test_use_skill_search_default_true(self) -> None:
        """Default use_skill_search is True for the new skill_search mode."""
        runner = self.SkillRunner(
            llm=self.mock_llm,
        )
        self.assertTrue(runner.use_skill_search)

    def test_skill_search_params(self) -> None:
        """Verify skill_search params are set correctly."""
        runner = self.SkillRunner(
            llm=self.mock_llm,
            use_skill_search=True,
            skill_search_batch_size=200,
            skill_search_max_concurrent=10,
            skill_search_max_steps=8,
        )
        self.assertTrue(runner.use_skill_search)
        self.assertEqual(runner.skill_search_batch_size, 200)
        self.assertEqual(runner.skill_search_max_concurrent, 10)
        self.assertEqual(runner.skill_search_max_steps, 8)


if __name__ == "__main__":
    unittest.main()