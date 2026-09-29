"""Load skills/a2a-chat.zip and send one stateless A2A message through SkillRunner.

Usage (from the skill_sdk repo root):

    python tests/run_a2a_chat_skill.py
    python tests/run_a2a_chat_skill.py --message "你好"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

_SDK_ROOT = Path(__file__).resolve().parents[1]
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

from skill_sdk.skill.loader import SkillLoader
from skill_sdk.skill.runner import SkillRunner

_ZIP_PATH = _SDK_ROOT / "skills" / "a2a-chat.zip"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exercise a2a-chat.zip via skill_sdk")
    parser.add_argument(
        "--message",
        default="你好，请用一两句话介绍你能做什么。",
        help="User message sent to the A2A server declared in the skill.",
    )
    parser.add_argument(
        "--zip",
        default=str(_ZIP_PATH),
        help="Path to the skill zip.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    zip_path = Path(args.zip)
    if not zip_path.is_file():
        print(f"skill zip not found: {zip_path}", file=sys.stderr)
        return 1

    with SkillLoader() as loader:
        skill = loader.load(zip_path)

    print(f"skill={skill.name} version={skill.version}")
    print(f"a2a_url={skill.a2a_url}")
    print(f"allowed_tools={skill.allowed_tools}")

    runner = SkillRunner(llm=None, use_skill_search=False)
    try:
        names = sorted(t.name for t in runner._tools_for_skill(skill))
        print(f"bound_tools={names}")
        if "a2a_chat" not in names:
            print("a2a_chat was not bound", file=sys.stderr)
            return 1

        raw = await runner._dispatch_tool(
            "a2a_chat",
            {"message": args.message},
            user_id="skill-sdk-a2a-test",
            run_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
            a2a_url=skill.a2a_url,
        )
    finally:
        runner.close()

    parsed = json.loads(raw)
    print(f"status={parsed.get('status')} is_error={parsed.get('is_error')}")
    content = parsed.get("content") or ""
    try:
        body = json.loads(content)
    except json.JSONDecodeError:
        body = {"text": content}
    if isinstance(body, dict) and body.get("text"):
        print("--- reply ---")
        print(body["text"])
    else:
        print(content)
    return 0 if parsed.get("status") == "success" and not parsed.get("is_error") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
