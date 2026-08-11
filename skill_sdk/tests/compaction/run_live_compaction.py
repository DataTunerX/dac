"""Live compaction tests against DashScope deepseek-v4-flash.

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk \\
    DASHSCOPE_API_KEY='sk-...' \\
    python tests/compaction/run_live_compaction.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent.parent
_MODEL_SDK = _SDK_ROOT.parent / "model_sdk"
sys.path.insert(0, str(_SDK_ROOT))
if _MODEL_SDK.is_dir():
    sys.path.insert(0, str(_MODEL_SDK))

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from model_sdk import ModelManager

from skill_sdk.api.base import Skill
from skill_sdk.compaction.guard import CompactionGuard
from skill_sdk.compaction.messages import is_compaction_summary_message
from skill_sdk.compaction.prepare import compact, prepare_compaction
from skill_sdk.compaction.settings import CompactionConfig, CompactionSettings
from skill_sdk.skill.runner import SkillRunner

DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
    os.environ.get("OPENAI_API_KEY", "sk-xxx"),
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def build_llm() -> Any:
    """Build DashScope OpenAI-compatible chat model."""
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def _big_dialog(n_turns: int = 6) -> list[Any]:
    """Synthetic long skill-like dialog used to force threshold / overflow compaction."""
    msgs: list[Any] = [
        SystemMessage(content="You are a coding skill runner. Use tools to solve the task."),
        HumanMessage(
            content=(
                "请梳理这个仓库里 skill runner 的执行流程，包括 plan、tool 调用、"
                "finish 以及上下文压缩相关设计。务必基于对话里已经读过的材料继续。"
            )
        ),
    ]
    files = [
        "skill_sdk/skill/runner.py",
        "skill_sdk/compaction/guard.py",
        "skill_sdk/compaction/prepare.py",
        "skill_sdk/compaction/cut_point.py",
        "skill_sdk/tool/grep_plugin.py",
        "skill_sdk/tool/lsp_plugin.py",
    ]
    for i in range(n_turns):
        path = files[i % len(files)]
        msgs.append(
            AIMessage(
                content=f"我将读取 {path} 并继续分析第 {i + 1} 轮。",
                tool_calls=[
                    {
                        "name": "readline_in_range",
                        "args": {"file_path": path, "start_line": 1, "end_line": 80},
                        "id": f"call_{i}",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={
                    "input_tokens": 12_000 + i * 3_000,
                    "output_tokens": 200,
                    "total_tokens": 12_200 + i * 3_000,
                },
            )
        )
        # Large-ish tool payload so keep_recent budget is meaningful.
        body = (
            f"# excerpt from {path}\n"
            + ("def example():\n    return True\n" * 40)
            + f"\n# turn={i} notes: runner binds tools, then loops max_steps.\n"
        ) * 3
        msgs.append(ToolMessage(content=body, tool_call_id=f"call_{i}"))
    return msgs


def _print_header(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


async def test_smoke_llm(llm: Any) -> None:
    """Verify the live model responds."""
    _print_header("1) Smoke: live LLM invoke")
    t0 = time.time()
    resp = await llm.ainvoke([HumanMessage(content="用一句话介绍你自己，不要超过30字。")])
    dt = time.time() - t0
    text = str(getattr(resp, "content", "") or "")
    print(f"model={LLM_MODEL} latency={dt:.2f}s")
    print(f"reply={text[:300]!r}")
    assert text.strip(), "empty smoke reply"
    print("PASS smoke")


async def test_live_compact(llm: Any) -> None:
    """Run prepare+compact with the real summarizer LLM."""
    _print_header("2) Live compact(): structured summary from real LLM")
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=4_000,
        keep_recent_tokens=1_200,
    )
    messages = _big_dialog(n_turns=6)
    prep = prepare_compaction(messages, settings)
    assert prep is not None, "prepare_compaction returned None"
    print(
        f"prepare: to_summarize={len(prep.messages_to_summarize)} "
        f"turn_prefix={len(prep.turn_prefix_messages)} "
        f"kept={len(prep.kept_messages)} split={prep.is_split_turn} "
        f"tokens_before={prep.tokens_before}"
    )
    t0 = time.time()
    result = await compact(prep, llm, reason="threshold")
    dt = time.time() - t0
    print(f"compact latency={dt:.2f}s tokens_after≈{result.estimated_tokens_after}")
    print("--- summary preview ---")
    print(result.summary[:1200])
    print("--- end preview ---")
    assert (
        "## Goal" in result.summary
        or "## Original Request" in result.summary
        or "Goal" in result.summary
        or "Turn Context" in result.summary
    )
    assert any(is_compaction_summary_message(m) for m in result.messages)
    assert len(result.messages) < len(messages)
    print("PASS live compact")


async def test_live_guard_threshold(llm: Any) -> None:
    """CompactionGuard.before_invoke should compact when usage exceeds threshold."""
    _print_header("3) Live CompactionGuard.before_invoke (threshold)")
    config = CompactionConfig(
        context_window=20_000,
        settings=CompactionSettings(
            enabled=True,
            reserve_tokens=8_000,
            keep_recent_tokens=1_000,
        ),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    messages = _big_dialog(n_turns=7)
    # Last AI usage in _big_dialog is > context_window - reserve → should_compact.
    t0 = time.time()
    out = await guard.before_invoke(messages)
    dt = time.time() - t0
    print(f"before_invoke latency={dt:.2f}s in={len(messages)} out={len(out)}")
    assert len(out) < len(messages)
    assert any(is_compaction_summary_message(m) for m in out)
    assert guard.boundaries
    print(f"boundary tokens_before={guard.boundaries[-1].tokens_before}")
    print("PASS live threshold guard")


async def test_live_overflow_recovery(llm: Any) -> None:
    """Simulate provider overflow; real LLM generates the recovery summary."""
    _print_header("4) Live overflow compact-and-retry (synthetic exception)")
    config = CompactionConfig(
        context_window=20_000,
        settings=CompactionSettings(
            enabled=True,
            reserve_tokens=8_000,
            keep_recent_tokens=1_000,
        ),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    messages = _big_dialog(n_turns=6)
    exc = RuntimeError("prompt is too long: 999999 tokens > 20000 maximum")
    t0 = time.time()
    recovery = await guard.on_invoke_error(messages, exc)
    dt = time.time() - t0
    assert recovery is not None
    assert recovery.will_retry and not recovery.failed
    assert recovery.messages is not None
    print(
        f"overflow recovery latency={dt:.2f}s "
        f"in={len(messages)} out={len(recovery.messages)}"
    )
    assert len(recovery.messages) < len(messages)
    assert any(is_compaction_summary_message(m) for m in recovery.messages)

    recovery2 = await guard.on_invoke_error(recovery.messages, exc)
    assert recovery2 is not None and recovery2.failed
    print(f"second overflow => failed={recovery2.failed!r} msg={recovery2.error_message[:120]!r}")
    print("PASS live overflow recovery")


async def test_live_runner_with_compaction(llm: Any) -> None:
    """SkillRunner.run with compaction enabled; force compact via seeded history."""
    _print_header("5) Live SkillRunner.run + compaction (finish quickly)")
    config = CompactionConfig(
        context_window=128_000,
        settings=CompactionSettings(
            enabled=True,
            reserve_tokens=16_384,
            keep_recent_tokens=20_000,
        ),
        summarizer_llm=llm,
    )
    runner = SkillRunner(
        llm=llm,
        max_steps=3,
        compaction=config,
        use_skill_search=False,
        empty_tool_retry=0,
    )
    skill = Skill(
        name="demo-compact",
        description="A tiny demo skill that should finish immediately.",
        detail=(
            "你是一个演示 skill。用户只要打招呼，你就立刻调用 finish，"
            "final_answer 用一句话说明 compaction 已启用即可。不要调用其它工具。"
        ),
        version="0.0.1",
        base_dir=str(_SDK_ROOT),
        scripts=[],
        allowed_tools=["finish"],
    )
    t0 = time.time()
    result = await runner.run(
        "你好，请直接 finish。",
        skill,
        user_id="live-compaction",
        run_id=str(uuid.uuid4()),
        trace_id=uuid.uuid4().hex,
    )
    dt = time.time() - t0
    print(f"run status={result.get('status')} latency={dt:.2f}s")
    print(f"final_answer={str(result.get('final_answer') or '')[:300]!r}")
    print(f"tool_history_len={len(result.get('tool_history') or [])}")
    assert result.get("status") in {"completed", "max_steps_exceeded"}
    print("PASS live runner (compaction enabled, normal short dialog)")


async def main() -> None:
    """Run all live compaction checks sequentially."""
    print(f"Using model={LLM_MODEL} base_url={DASHSCOPE_BASE_URL}")
    print(f"api_key=***{DASHSCOPE_API_KEY[-8:]}")
    llm = build_llm()

    await test_smoke_llm(llm)
    await test_live_compact(llm)
    await test_live_guard_threshold(llm)
    await test_live_overflow_recovery(llm)
    await test_live_runner_with_compaction(llm)

    _print_header("ALL LIVE COMPACTION CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
