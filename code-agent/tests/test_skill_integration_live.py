#!/usr/bin/env python3
"""Live integration test: skill-hub + skill-sdk + deepseek-v4-flash."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SKILL_HUB = os.environ.get("SKILL_HUB_URL", "http://10.17.0.41:31899")
MODEL = os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def _require_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not key.strip() or key.strip() == "sk-xxx":
        raise SystemExit("Set DASHSCOPE_API_KEY (or OPENAI_API_KEY) for live LLM test.")
    return key.strip()


async def main() -> int:
    api_key = _require_api_key()
    skills_dir = Path(tempfile.mkdtemp(prefix="code-agent-skills-"))
    workspace = str(ROOT)

    os.environ.setdefault("SKILL_HUB_URL", SKILL_HUB)
    os.environ.setdefault("SKILLS_DOWNLOAD_DIR", str(skills_dir))
    os.environ.setdefault("LOCAL_SKILLS_DIR", str(skills_dir))
    os.environ.setdefault("ENABLE_LOCAL_SKILLS", "true")
    os.environ.setdefault("WORKSPACE_FOLDER", workspace)

    from agent.skill_download import download_skills
    from agent.skill_runner_service import (
        CodeAgentSkillRunnerService,
        configure_skill_runtime_env,
    )

    print("=== 1. skill-hub download ===")
    print(f"    hub: {SKILL_HUB}")
    paths = download_skills(skill_hub_url=SKILL_HUB, target_dir=str(skills_dir))
    print(f"    downloaded: {[str(p) for p in paths]}")
    if not paths:
        print("FAIL: no skills downloaded")
        return 1

    configure_skill_runtime_env({"code-agent": workspace})

    print("\n=== 2. SkillRunner preload (deepseek-v4-flash) ===")
    svc = CodeAgentSkillRunnerService(
        provider="openai_compatible",
        api_key=api_key,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
    )
    runner = svc.preload()
    if runner is None:
        print("FAIL: SkillRunner not initialised")
        return 1
    names = [getattr(s, "name", "") for s in (getattr(runner.lister, "skills", []) or [])]
    print(f"    loaded skills: {names}")

    print("\n=== 3. plan_and_run (read-code skill) ===")
    query = "在 code-agent 项目里，CodeAgentExecutor 类定义在哪个文件？只回答文件路径。"
    trace_id = secrets.token_hex(16)
    result = await runner.plan_and_run(
        query=query,
        user_id="test-user",
        run_id="test-run",
        trace_id=trace_id,
    )
    status = result.get("status")
    final_answer = str(result.get("final_answer") or "").strip()
    print(f"    status: {status}")
    print(f"    skill: {result.get('skill')}")

    print("\n=== 4. Result ===")
    preview = final_answer if len(final_answer) <= 1200 else final_answer[:1200] + "\n...(truncated)"
    print(preview)

    svc.shutdown()

    if status != "completed":
        print(f"\nFAIL: plan_and_run status={status}")
        return 1
    if "code_agent.py" in final_answer.lower() or "agent/code_agent" in final_answer:
        print("\nPASS: answer references code_agent.py")
        return 0
    print("\nWARN: answer did not mention code_agent.py — manual review needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
