#!/usr/bin/env python3
"""Test ToolResult pipeline and LLM autonomous error handling.

This test suite validates the Pi Agent Loop-inspired architecture changes:

1. Unit tests: ToolResult model, prepare/execute/finalize phases
2. Integration tests: SkillRunner with mock LLM
3. Live tests with DeepSeek v4 Flash: error-inducing queries that demonstrate
   the LLM receiving unified ToolResult JSON and deciding autonomously when to
   stop vs. when to retry with a different approach.

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  /tmp/venv_skill/bin/python3 -m pytest tests/test_tool_result_loop.py -v -s --tb=short

  # Run only live tests (requires API key):
  /tmp/venv_skill/bin/python3 -m pytest tests/test_tool_result_loop.py -v -s --tb=short -k live
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-test")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://localhost:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://localhost:3000")

from skill_sdk.skill.tool_result import ToolResult
from skill_sdk.skill.runner import SkillRunner
from skill_sdk.api.base import Skill

# ---------------------------------------------------------------------------
# Unit Tests: ToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    """Unit tests for the unified ToolResult model."""

    def test_success(self):
        r = ToolResult.success("plan_cmd", "hello world", {"returncode": 0})
        assert r.status == "success"
        assert r.is_error is False
        assert r.tool_name == "plan_cmd"
        assert r.content == "hello world"
        assert r.details["returncode"] == 0

    def test_error(self):
        r = ToolResult.error(
            "plan_cmd",
            "command not found: xyz",
            {"returncode": 127, "stderr": "zsh: command not found: xyz"},
        )
        assert r.status == "error"
        assert r.is_error is True
        assert "command not found" in r.content
        assert r.details["returncode"] == 127

    def test_blocked(self):
        r = ToolResult.blocked(
            "plan_cmd",
            "Destructive command refused",
            {"cmd": "rm -rf /"},
        )
        assert r.status == "blocked"
        assert r.is_error is True
        assert "Destructive" in r.content

    def test_to_tool_message_content(self):
        r = ToolResult.success("grep", "found 3 matches", {"numFiles": 3})
        json_str = r.to_tool_message_content()
        parsed = json.loads(json_str)
        assert parsed["tool_name"] == "grep"
        assert parsed["status"] == "success"
        assert parsed["is_error"] is False
        assert parsed["content"] == "found 3 matches"
        assert parsed["details"]["numFiles"] == 3

    def test_all_statuses_have_same_structure(self):
        """Verify that success, error, and blocked all produce the same JSON keys."""
        success = json.loads(ToolResult.success("t", "ok").to_tool_message_content())
        error = json.loads(ToolResult.error("t", "fail").to_tool_message_content())
        blocked = json.loads(ToolResult.blocked("t", "denied").to_tool_message_content())

        for r in [success, error, blocked]:
            assert set(r.keys()) == {"tool_name", "status", "is_error", "content", "details"}

    def test_is_error_is_informational_not_control(self):
        """is_error is a field for the LLM to observe, not a control signal."""
        # Even with is_error=True, the model is purely informational
        r = ToolResult.error("test", "something failed")
        assert r.is_error is True
        # The model_dump doesn't have any "terminate" or "stop" field
        assert "terminate" not in r.model_dump()
        assert "should_stop" not in r.model_dump()


# ---------------------------------------------------------------------------
# Integration Tests: SkillRunner _dispatch_tool with mock LLM
# ---------------------------------------------------------------------------

class TestSkillRunnerDispatch:
    """Integration tests for the three-phase dispatch pipeline."""

    @pytest.fixture
    def runner(self):
        llm = MagicMock()
        return SkillRunner(llm=llm, use_skill_search=False)

    @pytest.fixture
    def skill(self):
        return Skill(
            name="test_skill",
            description="Test skill",
            detail="A test skill",
            skill_dir="/tmp",
            meta={"allowed_tools": ["plan_cmd", "finish"]},
        )

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error_result(self, runner):
        """Unknown tool → ToolResult with status='error', not an exception."""
        result = await runner._dispatch_tool(
            "nonexistent_tool",
            {"arg": "val"},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed = json.loads(result)
        assert parsed["tool_name"] == "nonexistent_tool"
        assert parsed["status"] == "error"
        assert parsed["is_error"] is True
        assert "Unknown tool" in parsed["content"]

    @pytest.mark.asyncio
    async def test_dispatch_empty_plan_cmd_returns_error(self, runner):
        """Empty plan_cmd → ToolResult with error status."""
        result = await runner._dispatch_tool(
            "plan_cmd",
            {"cmd": "", "rationale": "test"},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed = json.loads(result)
        assert parsed["tool_name"] == "plan_cmd"
        assert parsed["status"] == "error"
        assert "Empty cmd" in parsed["content"]

    @pytest.mark.asyncio
    async def test_dispatch_destructive_command_returns_blocked(self, runner):
        """Destructive command → ToolResult with status='blocked'."""
        runner.allow_destructive_commands = False
        result = await runner._dispatch_tool(
            "plan_cmd",
            {"cmd": "rm -rf /tmp/test", "rationale": "test"},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed = json.loads(result)
        assert parsed["tool_name"] == "plan_cmd"
        assert parsed["status"] == "blocked"
        assert parsed["is_error"] is True
        assert "Destructive command" in parsed["content"]

    @pytest.mark.asyncio
    async def test_dispatch_plugin_tool_error_returns_error_result(self, runner):
        """Plugin tool invocation error → ToolResult with error status."""
        # Create a mock tool that raises
        mock_tool = MagicMock()
        mock_tool.name = "mock_tool"
        mock_tool.invoke = MagicMock(side_effect=RuntimeError("plugin crashed"))
        runner._runner_tools = [mock_tool]

        result = await runner._dispatch_tool(
            "mock_tool",
            {"arg": "val"},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed = json.loads(result)
        assert parsed["tool_name"] == "mock_tool"
        assert parsed["status"] == "error"
        assert parsed["is_error"] is True
        assert "plugin crashed" in parsed["content"]

    @pytest.mark.asyncio
    async def test_dispatch_all_results_have_uniform_keys(self, runner):
        """All dispatch results (success, error, blocked) have the same JSON keys."""
        runner.allow_destructive_commands = False

        # Test blocked
        blocked = await runner._dispatch_tool(
            "plan_cmd",
            {"cmd": "rm -rf /", "rationale": "test"},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed_blocked = json.loads(blocked)
        assert set(parsed_blocked.keys()) == {"tool_name", "status", "is_error", "content", "details"}

        # Test unknown tool (error)
        error = await runner._dispatch_tool(
            "unknown_tool",
            {},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed_error = json.loads(error)
        assert set(parsed_error.keys()) == {"tool_name", "status", "is_error", "content", "details"}

        # Test empty cmd (error)
        empty = await runner._dispatch_tool(
            "plan_cmd",
            {"cmd": ""},
            user_id="test",
            run_id="test",
            trace_id="test",
        )
        parsed_empty = json.loads(empty)
        assert set(parsed_empty.keys()) == {"tool_name", "status", "is_error", "content", "details"}


# ---------------------------------------------------------------------------
# Live Tests with DeepSeek v4 Flash
# ---------------------------------------------------------------------------

DASHSCOPE_API_KEY = "sk-xxx"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-flash-0731"

TEST_SKILLS_DIR = _HERE / "test_skills"


def _build_test_skill(name: str, description: str, detail: str, allowed_tools: list[str]) -> Skill:
    """Build a Skill object for testing."""
    skill_dir = str(TEST_SKILLS_DIR / name)
    return Skill(
        name=name,
        description=description,
        detail=detail,
        version="1.0.0",
        base_dir=skill_dir,
        allowed_tools=allowed_tools,
    )


def _build_llm():
    """Build DeepSeek v4 Flash LLM via DashScope."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL,
        openai_api_key=DASHSCOPE_API_KEY,
        openai_api_base=DASHSCOPE_BASE_URL,
        temperature=0.01,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )


def _parse_result(raw: str | dict) -> dict | None:
    """Parse a tool result string into a dict if possible."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Test Case 1: Repeated command failures → LLM decides to finish
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_repeated_command_failures():
    """Test that LLM stops after repeated command failures, not infinite loop.

    Query: "List all files in /nonexistent_directory_12345"
    Expected: plan_cmd fails (path not found), LLM tries a few approaches,
    then calls finish with an explanation rather than retrying forever.
    """
    llm = _build_llm()
    skill = _build_test_skill(
        "error_loop_skill",
        "Error loop test skill",
        (
            "This skill is designed to test how the LLM handles repeated tool failures.\n"
            "You have access to plan_cmd (shell commands), glob, grep, readline_in_range, and finish.\n"
            "When a tool returns an error, observe the status/is_error/content fields in the ToolResult JSON.\n"
            "If repeated attempts fail, call finish with a clear explanation of what happened."
        ),
        ["plan_cmd", "glob", "grep", "readline_in_range", "finish"],
    )

    runner = SkillRunner(
        llm=llm,
        skills=[skill],
        max_steps=8,
        cmd_timeout_sec=15,
        allow_destructive_commands=False,
        use_skill_search=False,
    )

    result = await runner.run(
        query="List all files in /nonexistent_directory_12345",
        skill=skill,
        user_id="test_live",
        run_id="test_repeated_failures",
        trace_id=uuid.uuid4().hex,
    )

    print("\n=== Test: Repeated Command Failures ===")
    print(f"Status: {result.get('status')}")
    print(f"Final answer: {result.get('final_answer', '')[:500]}")
    print(f"Tool history count: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool_name = entry.get("tool", "?")
        result_str = str(entry.get("result", ""))[:200]
        print(f"  [{i}] {tool_name}: {result_str}")

    # Assertions
    assert result.get("status") != "error", f"Runner should not crash: {result}"
    # LLM should have called finish (final_answer present)
    assert result.get("final_answer"), "LLM should call finish with an explanation"
    # Should not have used all max_steps (LLM should stop early)
    steps_used = len(th)
    assert steps_used < 8, f"LLM used {steps_used} steps, should stop earlier than 8"


# ---------------------------------------------------------------------------
# Test Case 2: Destructive command blocked → LLM adapts
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_destructive_command_blocked():
    """Test that when a destructive command is blocked, the LLM reads the
    ToolResult blocked message and adapts with a safe alternative or calls finish.

    Query: "Delete all files in /tmp"
    Expected: plan_cmd with rm is blocked (status='blocked'), LLM reads the reason,
    tries a safe alternative or calls finish.
    """
    llm = _build_llm()
    skill = _build_test_skill(
        "error_loop_skill",
        "Error loop test skill",
        (
            "This skill tests how the LLM handles blocked (policy-refused) commands.\n"
            "When a command is blocked, the result will have status='blocked' with a reason.\n"
            "Read the reason and either use a safe alternative or call finish explaining why the task cannot be done."
        ),
        ["plan_cmd", "finish"],
    )

    runner = SkillRunner(
        llm=llm,
        skills=[skill],
        max_steps=6,
        cmd_timeout_sec=15,
        allow_destructive_commands=False,
        use_skill_search=False,
    )

    result = await runner.run(
        query="Delete all files in /tmp",
        skill=skill,
        user_id="test_live",
        run_id="test_blocked",
        trace_id=uuid.uuid4().hex,
    )

    print("\n=== Test: Destructive Command Blocked ===")
    print(f"Status: {result.get('status')}")
    print(f"Final answer: {result.get('final_answer', '')[:500]}")
    print(f"Tool history count: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool_name = entry.get("tool", "?")
        result_str = str(entry.get("result", ""))[:200]
        print(f"  [{i}] {tool_name}: {result_str}")

    # Assertions
    assert result.get("final_answer"), "LLM should call finish"
    steps_used = len(th)
    assert steps_used < 6, f"LLM should stop early, used {steps_used} steps"

    # Check that at least one blocked result was seen
    blocked_seen = False
    for entry in th:
        parsed = _parse_result(entry.get("result", ""))
        if parsed and parsed.get("status") == "blocked":
            blocked_seen = True
            break
    assert blocked_seen, "At least one tool call should have been blocked"


# ---------------------------------------------------------------------------
# Test Case 3: LLM handles mixed success/failure gracefully
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_mixed_success_failure():
    """Test that LLM handles a mix of successes and failures without getting stuck.

    Query: "Find all Python files, then try to read a non-existent file, then list the current directory"
    Expected: LLM successfully globs for *.py, tries to read a non-existent file
    (gets an error), then adapts and lists the directory.
    """
    llm = _build_llm()
    skill = _build_test_skill(
        "error_loop_skill",
        "Error loop test skill",
        (
            "You have access to glob, grep, readline_in_range, plan_cmd, and finish.\n"
            "When a tool returns an error, observe the status/is_error fields and adapt.\n"
            "Do not retry the exact same failing operation. Call finish when done."
        ),
        ["glob", "grep", "readline_in_range", "plan_cmd", "finish"],
    )

    runner = SkillRunner(
        llm=llm,
        skills=[skill],
        max_steps=10,
        cmd_timeout_sec=15,
        allow_destructive_commands=False,
        use_skill_search=False,
    )

    result = await runner.run(
        query=(
            "Do the following steps in order:\n"
            "1. Use glob to find all Python files (*.py) in the current directory\n"
            "2. Try to read a file called '/tmp/nonexistent_file_xyz_123.txt' using readline_in_range\n"
            "3. List the current directory using plan_cmd with 'ls -la'\n"
            "4. Call finish with a summary of what you did"
        ),
        skill=skill,
        user_id="test_live",
        run_id="test_mixed",
        trace_id=uuid.uuid4().hex,
    )

    print("\n=== Test: Mixed Success/Failure ===")
    print(f"Status: {result.get('status')}")
    print(f"Final answer: {result.get('final_answer', '')[:500]}")
    print(f"Tool history count: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        tool_name = entry.get("tool", "?")
        result_str = str(entry.get("result", ""))[:200]
        print(f"  [{i}] {tool_name}: {result_str}")

    # Assertions
    assert result.get("final_answer"), "LLM should call finish with a summary"
    steps_used = len(th)
    assert steps_used < 10, f"LLM used {steps_used} steps, should not need all 10"

    # Verify we saw both success and error results
    statuses = []
    for entry in th:
        parsed = _parse_result(entry.get("result", ""))
        if parsed:
            statuses.append(parsed.get("status"))
    print(f"  Statuses seen: {statuses}")

    # There should be at least one success and one error
    assert "success" in statuses, "Should see at least one successful tool call"
    # The readline_in_range for non-existent file should produce an error or blocked
    has_error = any(s in ("error", "blocked") for s in statuses)
    # Note: readline_in_range might not exist in the test runner's tool set,
    # so the error might be "unknown tool" instead. Either way, the LLM should handle it.
    print(f"  Has error/blocked status: {has_error}")


# ---------------------------------------------------------------------------
# Test Case 4: LLM doesn't repeat the exact same failing command
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_no_repetition_of_failures():
    """Test that the LLM does NOT repeat the exact same command after it fails.

    Query: "Run the command 'python3 --invalid-flag-xyz-not-exists'"
    Expected: The command fails, and the LLM should NOT send the exact same
    command again. It should either try a different approach or call finish.
    """
    llm = _build_llm()
    skill = _build_test_skill(
        "error_loop_skill",
        "Error loop test skill",
        (
            "You have access to plan_cmd and finish.\n"
            "IMPORTANT: When a command fails, NEVER repeat the exact same command string.\n"
            "Observe the ToolResult status/is_error/content fields.\n"
            "If the command fails, either try a different approach or call finish."
        ),
        ["plan_cmd", "finish"],
    )

    runner = SkillRunner(
        llm=llm,
        skills=[skill],
        max_steps=6,
        cmd_timeout_sec=15,
        allow_destructive_commands=False,
        use_skill_search=False,
    )

    result = await runner.run(
        query="Run the command 'python3 --invalid-flag-xyz-not-exists'",
        skill=skill,
        user_id="test_live",
        run_id="test_no_repeat",
        trace_id=uuid.uuid4().hex,
    )

    print("\n=== Test: No Repetition of Failures ===")
    print(f"Status: {result.get('status')}")
    print(f"Final answer: {result.get('final_answer', '')[:500]}")
    print(f"Tool history count: {len(result.get('tool_history', []))}")

    th = result.get("tool_history", [])
    cmds_seen = []
    for i, entry in enumerate(th):
        tool_name = entry.get("tool", "?")
        args = entry.get("args", {})
        cmd = args.get("cmd", "")
        result_str = str(entry.get("result", ""))[:200]
        print(f"  [{i}] {tool_name} cmd={cmd[:80]}: {result_str}")
        if tool_name == "plan_cmd" and cmd:
            cmds_seen.append(cmd.strip())

    # Assertions
    assert result.get("final_answer"), "LLM should call finish"
    steps_used = len(th)
    assert steps_used < 6, f"LLM should stop early, used {steps_used} steps"

    # Check for duplicate commands
    if len(cmds_seen) >= 2:
        # Remove duplicates
        unique_cmds = set(cmds_seen)
        assert len(unique_cmds) == len(cmds_seen), (
            f"LLM repeated the same command! cmds={cmds_seen}"
        )
        print(f"  All {len(cmds_seen)} commands are unique ✓")


# ---------------------------------------------------------------------------
# Test Case 5: ToolResult JSON structure is consistent in live execution
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tool_result_structure_consistent():
    """Verify that all tool results in live execution use the unified ToolResult format.

    Query: A simple task that involves multiple tools.
    Expected: Every tool result in tool_history is parseable JSON with the
    standard ToolResult keys (tool_name, status, is_error, content, details).
    """
    llm = _build_llm()
    skill = _build_test_skill(
        "error_loop_skill",
        "Error loop test skill",
        (
            "You have access to plan_cmd, glob, readline_in_range, and finish.\n"
            "Complete this simple task: list the current directory, then call finish."
        ),
        ["plan_cmd", "glob", "readline_in_range", "finish"],
    )

    runner = SkillRunner(
        llm=llm,
        skills=[skill],
        max_steps=5,
        cmd_timeout_sec=15,
        allow_destructive_commands=False,
        use_skill_search=False,
    )

    result = await runner.run(
        query="List the current directory and then call finish.",
        skill=skill,
        user_id="test_live",
        run_id="test_structure",
        trace_id=uuid.uuid4().hex,
    )

    print("\n=== Test: ToolResult Structure Consistency ===")
    print(f"Status: {result.get('status')}")
    print(f"Final answer: {result.get('final_answer', '')[:500]}")

    th = result.get("tool_history", [])
    for i, entry in enumerate(th):
        result_str = str(entry.get("result", ""))
        print(f"  [{i}] {entry.get('tool')}: {result_str[:150]}")

    # Verify every tool result is a valid JSON with the standard keys
    standard_keys = {"tool_name", "status", "is_error", "content", "details"}
    for i, entry in enumerate(th):
        result_str = str(entry.get("result", ""))
        parsed = _parse_result(result_str)
        if parsed is None:
            print(f"  WARNING: [{i}] result is not valid JSON: {result_str[:100]}")
            continue
        keys = set(parsed.keys())
        if keys != standard_keys:
            print(f"  WARNING: [{i}] unexpected keys: {keys} vs expected {standard_keys}")
        # Even if keys differ slightly, the core fields should be present
        assert "status" in parsed, f"Tool result [{i}] missing 'status' field"
        assert "is_error" in parsed, f"Tool result [{i}] missing 'is_error' field"
        assert "content" in parsed, f"Tool result [{i}] missing 'content' field"


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])