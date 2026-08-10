"""Verify DashScope API response/error shapes for token usage and overflow detection.

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk python tests/compaction/verify_api_shapes.py
"""

from __future__ import annotations

import asyncio, os, sys, traceback
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

from langchain_core.messages import HumanMessage, AIMessage
from model_sdk import ModelManager

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-xxx")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def build_llm() -> Any:
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def inspect_aimessage(msg: AIMessage) -> dict[str, Any]:
    """Inspect all metadata fields on an AIMessage."""
    info: dict[str, Any] = {}
    info["type"] = type(msg).__name__
    info["content_len"] = len(str(msg.content)) if msg.content else 0
    info["tool_calls"] = bool(getattr(msg, "tool_calls", None))

    um = getattr(msg, "usage_metadata", None)
    info["usage_metadata"] = dict(um) if um else None

    rm = getattr(msg, "response_metadata", None)
    info["response_metadata"] = dict(rm) if rm else None

    ak = getattr(msg, "additional_kwargs", None)
    info["additional_kwargs"] = dict(ak) if ak else None

    info["id"] = getattr(msg, "id", None)
    return info


async def verify_normal_response() -> None:
    """Verify token usage is correctly extracted from a normal response."""
    print("=" * 72)
    print("TEST 1: Token usage in normal response")
    print("=" * 72)

    llm = build_llm()
    messages = [HumanMessage(content="Say hello in exactly 3 words.")]
    resp = await llm.ainvoke(messages)

    info = inspect_aimessage(resp)
    print(f"  type: {info['type']}")
    print(f"  content: {resp.content}")
    print(f"  usage_metadata: {info['usage_metadata']}")
    print(f"  response_metadata: {info['response_metadata']}")
    print(f"  additional_kwargs: {info['additional_kwargs']}")
    print(f"  id: {info['id']}")

    from skill_sdk.compaction.tokens import usage_from_ai_message
    from skill_sdk.compaction.overflow import _finish_reason

    usage = usage_from_ai_message(resp)
    finish = _finish_reason(resp)

    print(f"\n  - usage_from_ai_message -> {usage}")
    print(f"  - finish_reason -> {finish!r}")

    if usage is None:
        print("\n  *** WARNING: usage_from_ai_message returned None!")
    elif usage.input <= 0:
        print("\n  *** WARNING: usage.input is zero!")
    else:
        print(f"\n  OK: input={usage.input} output={usage.output} total={usage.total_tokens}")


async def verify_overflow_exception() -> None:
    """Verify that a context overflow error is correctly detected."""
    print("\n" + "=" * 72)
    print("TEST 2: Overflow exception detection")
    print("=" * 72)

    llm = build_llm()
    huge_text = "This is a test message for context overflow detection. " * 5000
    messages = [HumanMessage(content=huge_text) for _ in range(50)]

    try:
        resp = await llm.ainvoke(messages)
        print(f"  Unexpected: response succeeded. content_len={len(str(resp.content))}")
    except Exception as exc:
        print(f"  Exception type: {type(exc).__name__}")
        print(f"  Exception module: {type(exc).__module__}")
        print(f"  str(exc)[:500]: {str(exc)[:500]}")

        for attr in ("message", "body", "response", "args", "status_code", "code", "type", "param", "request_id"):
            val = getattr(exc, attr, None)
            if val is not None:
                if isinstance(val, (str, int, float)):
                    print(f"  exc.{attr}: {str(val)[:300]}")
                elif isinstance(val, dict):
                    print(f"  exc.{attr} (dict): {str(val)[:300]}")
                else:
                    print(f"  exc.{attr} ({type(val).__name__}): {str(val)[:300]}")

        from skill_sdk.compaction.overflow import _exception_text, is_overflow_exception

        flat = _exception_text(exc)
        print(f"\n  _exception_text[:500]: {flat[:500]}")
        detected = is_overflow_exception(exc)
        print(f"  is_overflow_exception: {detected}")

        if not detected:
            print("\n  *** WARNING: Overflow was NOT detected!")
        else:
            print(f"\n  OK: overflow detected correctly.")


async def verify_silent_overflow() -> None:
    """Verify silent overflow detection with a simulated response."""
    print("\n" + "=" * 72)
    print("TEST 3: Silent overflow detection (simulated)")
    print("=" * 72)

    from skill_sdk.compaction.overflow import is_context_overflow_message, is_silent_overflow_success

    msg = AIMessage(
        content="The answer is done.",
        usage_metadata={"input_tokens": 50000, "output_tokens": 100, "total_tokens": 50100},
        response_metadata={"finish_reason": "stop"},
    )
    detected = is_context_overflow_message(msg, context_window=32000)
    silent = is_silent_overflow_success(msg, context_window=32000)
    print(f"  Simulated input_tokens=50000, window=32000")
    print(f"  is_context_overflow_message: {detected}")
    print(f"  is_silent_overflow_success: {silent}")
    if detected and silent:
        print("  OK: silent overflow detected.")
    else:
        print("  *** WARNING: silent overflow not detected!")


async def main() -> None:
    print(f"model={LLM_MODEL} base={DASHSCOPE_BASE_URL}")
    await verify_normal_response()
    await verify_overflow_exception()
    await verify_silent_overflow()
    print("\n" + "=" * 72)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())