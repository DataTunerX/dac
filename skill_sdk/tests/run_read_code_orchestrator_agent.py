"""Live read-code test against orchestrator-agent with DashScope deepseek-v4-flash.

Targets a repo with large Python modules (e.g. orchestrator_agent_semantic_group.py
~8k lines) so readline windowing can be exercised.

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  OPENAI_API_KEY='sk-...' PYTHONPATH=. python tests/run_read_code_orchestrator_agent.py

  # directed query example:
  PYTHONPATH=. python tests/run_read_code_orchestrator_agent.py \\
    '分析 orchestrator_agent/orchestrator_agent_semantic_group.py 里 semantic group 的核心流程'
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
_REPO = Path("/Users/james/daocloud/code/dac/orchestrator-agent")

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
    f"请分析 {_REPO} 这个代码仓库，弄清楚 orchestrator-agent 的整体工作原理："
    "它如何编排/调度 Agent、如何与 registry / data services / A2A / skill 协作，"
    "核心模块（尤其是 semantic group / semantic domain）如何分工，关键数据流是什么。"
    "请基于实际代码给出结构化说明；大文件请按窗口分段阅读，不要一次读整文件。"
    "拆窗时单窗尽量贴近 max_lines（可略保守）；跨度不超过上限则一次读完，禁止无故拆成百行级小窗。"
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


def _parse_result(raw: str) -> dict | None:
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def summarize_tool_history(tool_history: list) -> dict:
    used = []
    blocked = []
    readline_windows: list[dict] = []
    readline_rejected: list[dict] = []
    document_symbol_calls: list[dict] = []
    for entry in tool_history or []:
        name = entry.get("tool")
        if not name:
            continue
        used.append(name)
        result = str(entry.get("result") or "")
        args = entry.get("args") or {}
        if "blocked_by_policy" in result or "is not allowed for skill" in result:
            blocked.append({"tool": name, "result": result[:300]})
        if name == "lsp":
            op = args.get("operation") or args.get("Operation")
            if op == "documentSymbol" or (
                isinstance(result, str) and "Document symbols" in result
            ):
                parsed = _parse_result(result)
                body = ""
                if parsed and isinstance(parsed.get("result"), str):
                    body = parsed["result"]
                elif isinstance(result, str):
                    body = result
                filtered = "filtered by" in body
                no_match = "No document symbols matching filter" in body
                document_symbol_calls.append(
                    {
                        "file_path": args.get("file_path") or args.get("filePath"),
                        "symbol_name": args.get("symbol_name"),
                        "line": args.get("line"),
                        "filtered": filtered,
                        "no_match": no_match,
                        "result_chars": len(body),
                        "result_preview": body[:240].replace("\n", " | "),
                    }
                )
        if name == "readline_in_range":
            parsed = _parse_result(result)
            if parsed and "error" in parsed:
                readline_rejected.append(
                    {
                        "args": {
                            "file_path": args.get("file_path"),
                            "start": args.get("start"),
                            "end": args.get("end"),
                        },
                        "error": str(parsed.get("error"))[:240],
                    }
                )
            elif parsed:
                readline_windows.append(
                    {
                        "file_path": args.get("file_path"),
                        "start": parsed.get("start"),
                        "end": parsed.get("end"),
                        "window_lines": parsed.get("window_lines")
                        or parsed.get("total_lines"),
                        "next_start": parsed.get("next_start"),
                        "truncated_to_window": parsed.get("truncated_to_window"),
                        "max_lines": parsed.get("max_lines"),
                    }
                )
    return {
        "tools_called": used,
        "unique_tools": sorted(set(used)),
        "disallowed_tools_seen": sorted(set(used) - ALLOWED_READ_CODE),
        "policy_blocks": blocked,
        "readline_windows": readline_windows,
        "readline_rejected": readline_rejected,
        "document_symbol_calls": document_symbol_calls,
    }


async def main(query: str) -> None:
    if not _REPO.is_dir():
        raise SystemExit(f"missing repo: {_REPO}")

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
        empty_tool_retry=1,
        use_skill_search=True,
    )

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
            run_id=f"read-code-orch-{trace_id[:8]}",
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

    bad = summary["disallowed_tools_seen"]
    if bad:
        raise SystemExit(f"FAIL: disallowed tools were invoked: {bad}")
    if not any(
        t in summary["unique_tools"]
        for t in ("grep", "glob", "lsp", "readline_in_range")
    ):
        raise SystemExit(
            f"FAIL: expected code-reading tools, got {summary['unique_tools']}"
        )

    # Soft check: successful readline windows should respect max_lines.
    for win in summary["readline_windows"]:
        wl = win.get("window_lines")
        max_lines = win.get("max_lines") or 1000
        if isinstance(wl, int) and wl > max_lines:
            raise SystemExit(
                f"FAIL: readline window_lines={wl} exceeds max_lines={max_lines}: {win}"
            )

    print("ALLOW-LIST CHECK: PASS")
    if summary["readline_windows"]:
        print(
            f"READLINE WINDOW CHECK: PASS "
            f"({len(summary['readline_windows'])} window(s), "
            f"{len(summary['readline_rejected'])} rejected)"
        )

    docs = summary.get("document_symbol_calls") or []
    if docs:
        filtered_n = sum(1 for d in docs if d.get("filtered") or d.get("symbol_name"))
        unfiltered_large = [
            d
            for d in docs
            if not d.get("filtered")
            and not d.get("symbol_name")
            and (d.get("result_chars") or 0) > 4000
        ]
        print(
            f"DOCUMENT_SYMBOL CHECK: {len(docs)} call(s), "
            f"{filtered_n} filtered/named, "
            f"{len(unfiltered_large)} large unfiltered dumps"
        )
        if unfiltered_large:
            print(
                "WARN: large unfiltered documentSymbol dump(s) detected — "
                "prefer symbol_name/line on big files:"
            )
            for d in unfiltered_large:
                print(" ", dump(d))
    else:
        print("DOCUMENT_SYMBOL CHECK: no documentSymbol calls in this run")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Live read-code test against orchestrator-agent"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=os.environ.get("QUERY") or DEFAULT_QUERY,
        help="要问 read-code 的问题；也可用环境变量 QUERY",
    )
    args = parser.parse_args()
    asyncio.run(main(args.query))
