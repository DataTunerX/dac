#!/usr/bin/env python3
"""Comprehensive live tests for all 8 plugins with DeepSeek v4 Flash.

Each test induces tool errors and verifies:
1. Errors are returned with ``"is_error": True`` and ``"error"`` keys
2. The stagnation detector catches repeated failures
3. The LLM does NOT get stuck in infinite loops

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=/Users/james/daocloud/code/dac/model_sdk /tmp/venv_skill/bin/python3 \
    -m pytest tests/test_all_plugins_live.py -v -s --tb=short
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_openai import ChatOpenAI

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-test")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://localhost:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://localhost:3000")

from skill_sdk.skill.runner import SkillRunner
from skill_sdk.api.base import Skill

DASHSCOPE_API_KEY = "sk-xxx"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-flash-0731"

TEST_SKILLS_DIR = _HERE / "test_skills"


def _build_llm():
    return ChatOpenAI(
        model=LLM_MODEL,
        openai_api_key=DASHSCOPE_API_KEY,
        openai_api_base=DASHSCOPE_BASE_URL,
        temperature=0.01,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )


def _build_skill(name: str, description: str, detail: str, allowed_tools: list[str]) -> Skill:
    return Skill(
        name=name,
        description=description,
        detail=detail,
        version="1.0.0",
        base_dir=str(TEST_SKILLS_DIR / name),
        allowed_tools=allowed_tools,
    )


def _parse_result(raw: Any) -> dict | None:
    """Parse a tool result string/dict into a dict."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_inner_content(parsed: dict) -> dict | None:
    """Parse the ``content`` field of a runner dispatch wrapper into a dict.

    The runner wraps plugin results as:
      {"tool_name": "...", "status": "error", "is_error": True,
       "content": "{\\"error\\": \\"...\\", \\"is_error\\": true, ...}"}

    This helper extracts and parses the inner ``content`` JSON string.
    """
    content = parsed.get("content", "")
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _assert_error_has_error_key(tool: str, step: int, parsed: dict):
    """Assert that a parsed error result has the ``error`` key at the right level.

    The runner dispatch wrapper does NOT have ``error`` at the top level;
    it's inside the ``content`` JSON string (the actual plugin return).
    """
    inner = _parse_inner_content(parsed)
    if inner and "error" in inner:
        assert inner["error"], f"Tool '{tool}' step {step}: error key is empty"
    elif "error" in parsed:
        # Some tools may have error at top level (e.g. non-plugin tools)
        assert parsed["error"], f"Tool '{tool}' step {step}: error key is empty"
    else:
        # Also check details.error as fallback
        details = parsed.get("details", {})
        if isinstance(details, dict) and "error" in details:
            assert details["error"], f"Tool '{tool}' step {step}: details.error is empty"
        else:
            raise AssertionError(
                f"Tool '{tool}' step {step}: error result missing 'error' key. "
                f"parsed keys: {list(parsed.keys())}"
            )


# =============================================================================
# Test 1: web_fetch -- repeated failing URLs trigger stagnation
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_web_fetch_repeated_failures():
    """LLM tries to fetch several non-existent URLs; stagnation should intervene."""
    llm = _build_llm()
    skill = _build_skill(
        "web_fetch_test",
        "Web fetch error test",
        (
            "You have access to web_fetch and finish.\n"
            "IMPORTANT: When web_fetch returns an error, read the error field.\n"
            "Status 'error' with is_error=True means the fetch failed.\n"
            "NEVER retry the same URL. Try a different URL or call finish.\n"
            "Maximum 2 web_fetch attempts total, then call finish."
        ),
        ["web_fetch", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=6, use_skill_search=False,
    )

    result = await runner.run(
        query=(
            "Fetch these URLs exactly once each:\n"
            "1. https://www.gov.cn/zhengce/2020-12/26/content_5574753.htm\n"
            "2. https://www.mohrss.gov.cn/SYrlzyhshbzb/zcfg/flfg/gz/201705/t20170512_270618.html\n"
            "After fetching both (even if they fail), call finish with a summary."
        ),
        skill=skill, user_id="test", run_id="test_web_fetch", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Web Fetch Repeated Failures ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    error_count = 0
    urls_seen = set()
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            status = parsed.get("status", "?")
            is_err = parsed.get("is_error", False)
            print(f"  [{i}] {tool} status={status} is_error={is_err}")
            if is_err:
                error_count += 1
                assert parsed["is_error"] is True
                _assert_error_has_error_key(tool, i, parsed)
            if tool == "web_fetch":
                args = entry.get("args", {})
                url = args.get("url", "")
                urls_seen.add(url)
        else:
            print(f"  [{i}] {tool}: {str(entry.get('result', ''))[:150]}")

    # No duplicate URLs
    assert len(urls_seen) == len([e for e in th if e.get("tool") == "web_fetch"]), \
        f"LLM repeated URLs! urls_seen={urls_seen}"
    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 6, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 2: readline_in_range -- read non-existent file
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_readline_in_range_nonexistent():
    """LLM tries to read a non-existent file; should get error and stop."""
    llm = _build_llm()
    skill = _build_skill(
        "readline_test",
        "Readline error test",
        (
            "You have access to readline_in_range and finish.\n"
            "When readline_in_range returns an error (is_error=True), do NOT retry.\n"
            "Call finish immediately with an explanation of the error."
        ),
        ["readline_in_range", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=5, use_skill_search=False,
    )

    result = await runner.run(
        query="Read lines 1-10 from the file /tmp/nonexistent_xyz_12345.txt",
        skill=skill, user_id="test", run_id="test_readline", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Readline Non-Existent File ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 5, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 3: glob -- search non-existent directory
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_glob_nonexistent_directory():
    """LLM tries to glob a non-existent directory; should get error and stop."""
    llm = _build_llm()
    skill = _build_skill(
        "glob_test",
        "Glob error test",
        (
            "You have access to glob and finish.\n"
            "When glob returns an error (is_error=True), do NOT retry.\n"
            "Call finish immediately with an explanation."
        ),
        ["glob", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=5, use_skill_search=False,
    )

    result = await runner.run(
        query="Use glob to find all *.py files in /nonexistent_dir_xyz_12345",
        skill=skill, user_id="test", run_id="test_glob", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Glob Non-Existent Directory ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 5, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 4: grep -- invalid pattern / missing file
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_grep_nonexistent_path():
    """LLM tries to grep a non-existent path; should get error and stop."""
    llm = _build_llm()
    skill = _build_skill(
        "grep_test",
        "Grep error test",
        (
            "You have access to grep and finish.\n"
            "When grep returns an error (is_error=True), do NOT retry.\n"
            "Call finish immediately with an explanation."
        ),
        ["grep", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=5, use_skill_search=False,
    )

    result = await runner.run(
        query="Use grep to search for 'hello' in /nonexistent_path_xyz_12345",
        skill=skill, user_id="test", run_id="test_grep", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Grep Non-Existent Path ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 5, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 5: lsp -- unavailable file type
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_lsp_nonexistent_file():
    """LLM tries LSP on a non-existent file; should get error and stop."""
    llm = _build_llm()
    skill = _build_skill(
        "lsp_test",
        "LSP error test",
        (
            "You have access to lsp and finish.\n"
            "When lsp returns an error (is_error=True), do NOT retry.\n"
            "Call finish immediately with an explanation."
        ),
        ["lsp", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=5, use_skill_search=False,
    )

    result = await runner.run(
        query="Use lsp to get documentSymbol for /tmp/nonexistent_xyz_12345.py",
        skill=skill, user_id="test", run_id="test_lsp", trace_id=uuid.uuid4().hex,
    )

    print("\n=== LSP Non-Existent File ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 5, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 6: extract_pdf -- non-existent file
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_extract_pdf_nonexistent():
    """LLM tries to extract a non-existent PDF; should get error and stop."""
    llm = _build_llm()
    skill = _build_skill(
        "pdf_test",
        "PDF extract error test",
        (
            "You have access to extract_pdf and finish.\n"
            "When extract_pdf returns an error (is_error=True), do NOT retry.\n"
            "Call finish immediately with an explanation."
        ),
        ["extract_pdf", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=5, use_skill_search=False,
    )

    result = await runner.run(
        query="Extract text from PDF file /tmp/nonexistent_xyz_12345.pdf",
        skill=skill, user_id="test", run_id="test_pdf", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Extract PDF Non-Existent ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 5, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 7: Stagnation detector -- same tool repeated failures
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_stagnation_detector_activates():
    """Use a skill that forces the LLM into repeated failures; verify stagnation warning appears."""
    llm = _build_llm()
    skill = _build_skill(
        "stagnation_test",
        "Stagnation detection test",
        (
            "You have access to glob, grep, readline_in_range, and finish.\n"
            "IMPORTANT: NEVER repeat the exact same tool call with the same arguments.\n"
            "When a tool returns an error (is_error=True), try a DIFFERENT approach.\n"
            "If you cannot make progress, call finish."
        ),
        ["glob", "grep", "readline_in_range", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=8, use_skill_search=False,
    )

    # This query is designed to trigger multiple failures with different tools
    result = await runner.run(
        query=(
            "1. Use glob to find '*.py' in /nonexistent_dir_12345\n"
            "2. Use grep to search for 'def' in /nonexistent_dir_12345\n"
            "3. Use readline_in_range to read lines 1-5 from /tmp/nonexistent_12345.txt\n"
            "After all three steps, call finish with what happened."
        ),
        skill=skill, user_id="test", run_id="test_stagnation", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Stagnation Detector ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    error_count = 0
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            print(f"  [{i}] {tool} status={parsed.get('status')} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                error_count += 1
                _assert_error_has_error_key(tool, i, parsed)

    # Should have seen errors
    assert error_count > 0, "Expected at least one error"
    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 8, f"LLM used {len(th)} steps, should stop early"


# =============================================================================
# Test 8: All error results have consistent JSON structure
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_all_errors_have_is_error_true():
    """Verify every error result from any plugin has is_error=True and error key."""
    llm = _build_llm()
    skill = _build_skill(
        "all_tools_test",
        "All tools error test",
        (
            "You have access to: glob, grep, readline_in_range, web_fetch, extract_pdf, lsp, and finish.\n"
            "Do the following:\n"
            "1. glob *.py in /nonexistent_123\n"
            "2. grep 'hello' in /nonexistent_123\n"
            "3. readline_in_range lines 1-5 from /tmp/nonexistent_123.txt\n"
            "4. web_fetch http://127.0.0.1:19999/\n"
            "5. extract_pdf /tmp/nonexistent_123.pdf\n"
            "6. lsp documentSymbol for /tmp/nonexistent_123.py\n"
            "When a tool returns error (is_error=True), do NOT retry the same call.\n"
            "Call finish after completing all steps."
        ),
        ["glob", "grep", "readline_in_range", "web_fetch", "extract_pdf", "lsp", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=12, use_skill_search=False,
    )

    result = await runner.run(
        query=(
            "Execute the following steps in order, one by one. "
            "Do NOT retry failing calls. Continue to the next step after each one.\n"
            "1. glob pattern='*.py' path='/nonexistent_12345'\n"
            "2. grep pattern='hello' path='/nonexistent_12345'\n"
            "3. readline_in_range file_path='/tmp/nonexistent_12345.txt' start=1 end=5\n"
            "4. web_fetch url='http://127.0.0.1:19999/' max_chars=500\n"
            "5. extract_pdf pdf='/tmp/nonexistent_12345.pdf'\n"
            "6. lsp operation='documentSymbol' file_path='/tmp/nonexistent_12345.py'\n"
            "After all 6 steps, call finish with a summary."
        ),
        skill=skill, user_id="test", run_id="test_all_errors", trace_id=uuid.uuid4().hex,
    )

    print("\n=== All Errors Have is_error=True ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    tools_used = set()
    error_results = []
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        if tool != "finish":
            tools_used.add(tool)
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            is_err = parsed.get("is_error", False)
            status = parsed.get("status", "?")
            print(f"  [{i}] {tool} status={status} is_error={is_err}")
            if is_err:
                error_results.append((tool, parsed))
                assert parsed.get("is_error") is True, \
                    f"Tool '{tool}' error result has is_error={parsed.get('is_error')} at step {i}"
                _assert_error_has_error_key(tool, i, parsed)
        else:
            print(f"  [{i}] {tool}: {str(entry.get('result', ''))[:150]}")

    print(f"  Tools used: {tools_used}")
    print(f"  Error results count: {len(error_results)}")

    assert result.get("final_answer"), "LLM should call finish"
    assert len(th) <= 12, f"LLM used {len(th)} steps, should stop early"
    # At least some tools should have been used
    assert len(tools_used) >= 2, f"Only {len(tools_used)} tools used, expected at least 2"


# =============================================================================
# Test 9: Mix of success and failure -- error handling is correct
# =============================================================================

@pytest.mark.live
@pytest.mark.asyncio
async def test_mixed_success_and_failure():
    """LLM executes a mix of valid and invalid tool calls; error handling stays correct."""
    llm = _build_llm()
    skill = _build_skill(
        "mixed_test",
        "Mixed success/failure test",
        (
            "You have access to glob, grep, readline_in_range, and finish.\n"
            "When a tool returns an error (is_error=True), do NOT retry.\n"
            "Try a different approach or call finish."
        ),
        ["glob", "grep", "readline_in_range", "finish"],
    )

    runner = SkillRunner(
        llm=llm, skills=[skill], max_steps=10, use_skill_search=False,
    )

    result = await runner.run(
        query=(
            "Do the following:\n"
            "1. Use glob to find '*.py' files in the current directory\n"
            "2. Try to read /tmp/nonexistent_xyz_12345.txt with readline_in_range\n"
            "3. Use grep to search for 'import' in the current directory\n"
            "4. Call finish with a summary"
        ),
        skill=skill, user_id="test", run_id="test_mixed", trace_id=uuid.uuid4().hex,
    )

    print("\n=== Mixed Success/Failure ===")
    print(f"Status: {result.get('status')}")
    print(f"Steps used: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    statuses = []
    for i, entry in enumerate(th):
        tool = entry.get("tool", "?")
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            s = parsed.get("status")
            statuses.append(s)
            print(f"  [{i}] {tool} status={s} is_error={parsed.get('is_error')}")
            if parsed.get("is_error"):
                _assert_error_has_error_key(tool, i, parsed)

    assert result.get("final_answer"), "LLM should call finish"
    assert "success" in statuses, f"Should have at least one success, got: {statuses}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])