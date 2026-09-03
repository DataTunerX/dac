"""Live read-code test against agent-registry with DashScope deepseek-v4-flash.

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  OPENAI_API_KEY='sk-...' PYTHONPATH=. python tests/run_read_code_agent_registry.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
_REPO = Path("/Users/james/daocloud/code/dac/agent-registry")

sys.path.insert(0, str(_SDK_ROOT))

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

# Point LSP / tools at the target repo
os.environ["WORKSPACE_FOLDER"] = str(_REPO)
os.environ.setdefault(
    "SKILL_SDK_LSP_SERVERS",
    json.dumps(
        {
            "basedpyright": {
                "command": "basedpyright-langserver",
                "extensionToLanguage": {".py": "python"},
                "args": ["--stdio"],
                "startupTimeoutMs": 30000,
                "workspaceFolder": str(_REPO),
            }
        }
    ),
)

from model_sdk import ModelManager
from skill_sdk.skill.loader import SkillLoader
from skill_sdk.skill.runner import SkillRunner

DASHSCOPE_API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    "sk-xxx",
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

ALLOWED_READ_CODE = {"glob", "grep", "lsp", "readline_in_range", "finish"}

DEFAULT_QUERY = (
    f"请分析 {_REPO} 这个代码仓库，弄清楚 agent-registry 的整体工作原理："
    "它如何注册/发现 Agent、如何与 Redis / 向量库 / API / MCP 协作，"
    "核心数据流是什么。请基于实际代码给出结构化说明。"
)


def build_llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def summarize_tool_history(tool_history: list) -> dict:
    used = []
    blocked = []
    first_idx = {}
    for entry in tool_history or []:
        name = entry.get("tool")
        if not name:
            continue
        used.append(name)
        first_idx.setdefault(name, len(used) - 1)
        result = str(entry.get("result") or "")
        if "blocked_by_policy" in result or "is not allowed for skill" in result:
            blocked.append({"tool": name, "result": result[:300]})
    return {
        "tools_called": used,
        "unique_tools": sorted(set(used)),
        "tool_counts": {t: used.count(t) for t in sorted(set(used))},
        "first_index": first_idx,
        "disallowed_tools_seen": sorted(set(used) - ALLOWED_READ_CODE),
        "policy_blocks": blocked,
    }


async def main(query: str) -> None:
    print("=" * 72)
    print(f"model={LLM_MODEL}")
    print(f"repo={_REPO}")
    print(f"query={query}")
    print("=" * 72)

    llm = build_llm()
    runner = SkillRunner(
        llm=llm,
        max_steps=25,
        cmd_timeout_sec=60,
        use_skill_search=True,
    )

    # Prefer loading only read-code so the test focuses on tool allow-list + reading.
    zip_path = _SDK_ROOT / "skills" / "read-code.zip"
    with SkillLoader() as loader:
        if zip_path.is_file():
            skill = loader.load(zip_path)
            skills = [skill]
        else:
            raise SystemExit(f"missing skill zip: {zip_path}")

    runner.set_skills(skills)
    print(f"loaded skills: {[s.name for s in skills]}")
    print(f"read-code allowed_tools={skill.allowed_tools}")
    bound = sorted(t.name for t in runner._tools_for_skill(skill))
    print(f"read-code bound tools={bound}")

    trace_id = uuid.uuid4().hex
    try:
        result = await runner.run(
            query=query,
            skill=skill,
            user_id="live-test",
            run_id=f"read-code-{trace_id[:8]}",
            trace_id=trace_id,
        )
    finally:
        runner.close()

    summary = summarize_tool_history(result.get("tool_history") or [])
    print("\n" + "=" * 72)
    print("RESULT STATUS:", result.get("status"))
    print("SKILL:", result.get("skill"))
    print("TOOL SUMMARY:", dump(summary))
    print("-" * 72)
    print("FINAL ANSWER:\n", result.get("final_answer"))
    print("=" * 72)

    # Assertions for allow-list effectiveness
    bad = summary["disallowed_tools_seen"]
    if bad:
        raise SystemExit(f"FAIL: disallowed tools were invoked: {bad}")
    if not any(t in summary["unique_tools"] for t in ("grep", "glob", "lsp", "readline_in_range")):
        raise SystemExit(f"FAIL: expected code-reading tools, got {summary['unique_tools']}")
    print("ALLOW-LIST CHECK: PASS")

    # Soft signal only: broad queries often benefit from grep, but skill no longer mandates it.
    is_broad = any(
        k in query for k in ("整体", "工作原理", "如何注册", "怎么工作", "架构")
    )
    if is_broad:
        fi = summary["first_index"]
        if "grep" not in summary["unique_tools"]:
            print(
                "BROAD-QUERY NOTE: no grep used "
                f"(allowed when entry files are clear); first_index={fi}"
            )
        else:
            first_grep = fi.get("grep", 10**9)
            first_lsp = fi.get("lsp", 10**9)
            first_src = next(
                (
                    i
                    for i, t in enumerate(summary["tools_called"])
                    if t == "readline_in_range"
                ),
                10**9,
            )
            # Informative only — do not fail the run.
            if min(first_lsp, first_src) < first_grep:
                print(
                    "BROAD-QUERY NOTE: some reads occurred before grep "
                    f"(first_index={fi}); OK if non-source or planned"
                )
            else:
                print("BROAD-QUERY GREP ORDER: grep before heavy source tools")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live read-code test against agent-registry")
    parser.add_argument(
        "query",
        nargs="?",
        default=os.environ.get("QUERY") or DEFAULT_QUERY,
        help="要问 read-code 的问题；也可用环境变量 QUERY",
    )
    args = parser.parse_args()
    asyncio.run(main(args.query))
