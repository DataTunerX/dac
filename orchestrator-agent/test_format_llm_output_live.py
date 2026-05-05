"""Live end-to-end test of the planner JSON recovery chain.

Calls the real LLM with a query designed to trigger the "unescaped inner quote"
failure mode (user query contains a literal JSON fragment like
``{"category":"手机"}``), captures the raw output, then feeds it through
``PlannerAgent.format_llm_output`` to confirm the recovery chain produces a
valid plan dict.

Run with:

    cd dac/orchestrator-agent
    .venv/bin/python test_format_llm_output_live.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

from langchain_core.messages import HumanMessage, SystemMessage
from model_sdk import ModelManager

from orchestrator_agent.orchestrator_agent_semantic_group import (
    PlannerAgent,
    _escape_known_string_field_inner_quotes,
)


API_KEY = "sk-xxx"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


CANDIDATE_MODELS = [
    "glm-5.1",
    "glm-4.5",
    "glm-4-plus",
    "deepseek-v3.2",
    "qwen3-max",
]


def build_llm(model: str):
    manager = ModelManager()
    return manager.get_llm(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=model,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


# ---------------------------------------------------------------------------
# 1) Prompt that strongly biases the LLM toward inlining the user's JSON
#    fragment verbatim into the string values — triggering the "unescaped
#    inner quotes" failure mode.
# ---------------------------------------------------------------------------
PLANNER_SYS_PROMPT = """你是一位任务规划师。严格按照如下 JSON 结构返回一个计划（只返回 JSON，不要任何额外说明）：

{
  "thought_process": "...",
  "original_query": "<用户原话，必须和用户输入完全一致，不得改写>",
  "tasks": [
    {"id": 1, "description": "<任务描述，忠实反映用户意图>", "agent": "LocalSkill", "depends_on": []},
    {"id": 2, "description": "...", "agent": "EcommerceAgent", "depends_on": [1]}
  ]
}

要求：
- original_query 字段必须原样保留用户原话里的所有字符，包括 JSON 片段里的双引号。
- 至少两个任务。
"""


QUERIES = [
    '请将 JSON {"category":"手机","scope":"订单系统"} 格式化（缩进可读）并读出 category 的值。然后，在订单系统中查询商品种类等于该值的商品有哪些。',
    '把字符串 {"id":42,"name":"Alice"} 美化后读出 name 字段，然后在用户系统查一下该 name 的最近登录时间。',
]


async def call_llm(llm, query: str):
    t0 = time.perf_counter()
    msg = await llm.ainvoke(
        [SystemMessage(content=PLANNER_SYS_PROMPT), HumanMessage(content=query)]
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return msg, elapsed_ms


class _DummyPlanner(PlannerAgent):
    """Minimal subclass so we can reuse format_llm_output without running __init__."""

    def __init__(self):
        pass


def _try_parse_direct(content: str):
    try:
        return json.loads(content), None
    except Exception as e:  # noqa: BLE001
        return None, repr(e)


def report(title: str, content: str):
    sep = "=" * 80
    print(f"\n{sep}\n{title}\n{sep}")
    print(content)


def _corrupt_unescape(raw: str) -> str:
    """Simulate the real-world LLM bug: strip the backslashes that escape
    inner double quotes inside known string field values.

    We reproduce the exact failure mode seen in production: the LLM puts a
    JSON fragment from the user query into ``original_query`` / ``description``
    but *forgets* to escape the inner ``"`` — i.e. writes ``"..."`` instead of
    ``\\"...\\"``.
    """
    fields = (
        "original_query", "description", "thought_process",
        "reason", "rationale", "final_answer",
    )
    import re as _re
    pattern_fields = "|".join(_re.escape(f) for f in fields)
    pattern = _re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'
        r'((?:\\"|[^"\n])*?)'
        r'("[ \t]*,?[ \t]*$)',
        _re.MULTILINE,
    )
    def _repl(m):
        head, body, tail = m.group(1), m.group(2), m.group(3)
        body = body.replace('\\"', '"')
        return head + body + tail
    return pattern.sub(_repl, raw)


async def test_one(llm, query: str, planner: _DummyPlanner):
    print("\n" + "#" * 80)
    print(f"# QUERY: {query}")
    print("#" * 80)
    msg, elapsed_ms = await call_llm(llm, query)
    raw = msg.content
    report(f"RAW LLM OUTPUT ({elapsed_ms} ms, {len(raw)} chars)", raw)

    results = []

    # --- Variant A: the pristine LLM output (happy path) -----------------
    print("\n--- Variant A: raw LLM output ---")
    ok_a = _run_parse(planner, raw)
    results.append(("raw", ok_a))

    # --- Variant B: strip code fences and un-escape inner quotes to
    #               reproduce the production failure mode exactly. -------
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    corrupted = _corrupt_unescape(cleaned)
    if corrupted == cleaned:
        print("\n--- Variant B: could not synthesize unescaped-quote payload "
              "(LLM output had no \\\" to strip); skipping ---")
    else:
        print("\n--- Variant B: synthetic unescaped-quotes (reproduces production bug) ---")
        report(f"CORRUPTED PAYLOAD ({len(corrupted)} chars)", corrupted)
        try:
            json.loads(corrupted)
            print("   (sanity check) corrupted payload unexpectedly valid JSON — "
                  "not exercising the bug path")
        except Exception as e:  # noqa: BLE001
            print(f"   (sanity check) corrupted payload rejected by json.loads: {e}")
        ok_b = _run_parse(planner, corrupted)
        results.append(("corrupted", ok_b))

    return all(ok for _, ok in results)


def _run_parse(planner: _DummyPlanner, content: str) -> bool:
    direct, direct_err = _try_parse_direct(content)
    print(f"[direct json.loads] ok={direct is not None} err={direct_err}")

    after_escape = _escape_known_string_field_inner_quotes(content)
    print(f"[field-escape pre-pass] would_change_chars={len(after_escape) - len(content)}")

    answer_obj = SimpleNamespace(content=content)
    t0 = time.perf_counter()
    parsed = planner.format_llm_output(answer_obj)
    t1 = int((time.perf_counter() - t0) * 1000)

    if isinstance(parsed, dict):
        tasks = parsed.get("tasks")
        print(
            f"[format_llm_output] OK  ({t1} ms)  "
            f"keys={list(parsed.keys())}  tasks={len(tasks) if isinstance(tasks, list) else 'n/a'}"
        )
        print("  original_query ->", parsed.get("original_query"))
        if isinstance(tasks, list):
            for t in tasks:
                if isinstance(t, dict):
                    print(
                        f"    - task {t.get('id')}: agent={t.get('agent')!r} "
                        f"desc={t.get('description')!r}"
                    )
        return True
    else:
        print(f"[format_llm_output] FAIL ({t1} ms) — returned {parsed!r}")
        return False


async def main():
    chosen_model = None
    last_err = None
    for model in CANDIDATE_MODELS:
        try:
            llm = build_llm(model)
            test = await llm.ainvoke([HumanMessage(content="ping")])
            print(f"[model-probe] model={model!r} OK  reply_preview={str(test.content)[:40]!r}")
            chosen_model = model
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[model-probe] model={model!r} FAILED: {e}")
            continue

    if chosen_model is None:
        print("No usable model found. Last error:", last_err)
        sys.exit(1)

    print(f"\n### USING MODEL: {chosen_model} ###\n")
    llm = build_llm(chosen_model)
    planner = _DummyPlanner()

    results = []
    for q in QUERIES:
        try:
            ok = await test_one(llm, q, planner)
        except Exception as e:  # noqa: BLE001
            print(f"\n!! test raised: {e}")
            ok = False
        results.append((q, ok))

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for q, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {q[:70]}{'...' if len(q) > 70 else ''}")
    if not all(ok for _, ok in results):
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
