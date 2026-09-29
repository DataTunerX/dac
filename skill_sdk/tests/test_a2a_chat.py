"""A2A chat plugin: skill url binding, frame reduction, and runner dispatch."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from skill_sdk.api.base import Skill
from skill_sdk.skill.loader import SkillLoader
from skill_sdk.skill.runner import SkillRunner
from skill_sdk.tool.a2a_conversation import reduce_frames

_SDK_ROOT = Path(__file__).resolve().parents[1]
_SKILL_DIR = _SDK_ROOT / "skills" / "a2a-chat"


class TestParseA2aUrl(unittest.TestCase):
    def test_missing_is_empty(self) -> None:
        self.assertEqual(SkillLoader._parse_a2a_url({"version": "1"}), "")

    def test_reads_url(self) -> None:
        self.assertEqual(
            SkillLoader._parse_a2a_url({"a2a": {"url": "http://10.17.0.41:32490/"}}),
            "http://10.17.0.41:32490",
        )

    def test_rejects_non_http(self) -> None:
        with self.assertRaises(ValueError):
            SkillLoader._parse_a2a_url({"a2a": {"url": "ftp://example.com"}})

    def test_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError):
            SkillLoader._parse_a2a_url({"a2a": "http://example.com"})


class TestLoadA2aSkillDir(unittest.TestCase):
    def test_skill_dir_declares_server(self) -> None:
        meta = SkillLoader.read_meta_json(_SKILL_DIR)
        md = SkillLoader.read_skill_md(_SKILL_DIR)
        skill = SkillLoader.build_skill(meta, md, base_dir=_SKILL_DIR)
        self.assertEqual(skill.name, "a2a-chat")
        self.assertEqual(skill.allowed_tools, ["a2a_chat"])
        self.assertEqual(skill.a2a_url, "http://10.17.0.41:32490")


class TestRunnerBindsA2aChat(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = SkillRunner(llm=MagicMock())

    def test_omitted_without_url(self) -> None:
        skill = Skill(
            name="legacy",
            description="d",
            detail="b",
            version="1",
        )
        names = {t.name for t in self.runner._tools_for_skill(skill)}
        self.assertNotIn("a2a_chat", names)
        self.assertIn("web_fetch", names)
        self.assertIn("finish", names)
        self.assertFalse(self.runner._is_tool_allowed_for_skill(skill, "a2a_chat"))

    def test_bound_when_url_and_allow_list(self) -> None:
        skill = Skill(
            name="a2a-chat",
            description="d",
            detail="b",
            version="1",
            allowed_tools=["a2a_chat"],
            a2a_url="http://10.17.0.41:32490",
        )
        names = {t.name for t in self.runner._tools_for_skill(skill)}
        self.assertEqual(names, {"a2a_chat", "finish"})
        self.assertTrue(self.runner._is_tool_allowed_for_skill(skill, "a2a_chat"))

    def test_allow_list_without_url_does_not_bind(self) -> None:
        skill = Skill(
            name="a2a-chat",
            description="d",
            detail="b",
            version="1",
            allowed_tools=["a2a_chat"],
        )
        names = {t.name for t in self.runner._tools_for_skill(skill)}
        self.assertEqual(names, {"finish"})
        self.assertFalse(self.runner._is_tool_allowed_for_skill(skill, "a2a_chat"))


class TestReduceFrames(unittest.TestCase):
    def test_keeps_final_answer_and_drops_progress(self) -> None:
        progress = '[[DAC_PROGRESS]] {"event":"step","message":"working"}\n'
        answer = (
            '[[DAC_ANSWER]] {"event":"final_answer","payload":{"text":"订单已创建"}}\n'
        )
        self.assertEqual(reduce_frames([progress, answer]), "订单已创建")

    def test_summary_replaces_body(self) -> None:
        body = "中间过程\n"
        summary = '[[DAC_SUMMARY]] {"summary":"最终摘要"}\n'
        self.assertEqual(reduce_frames([body, summary]), "最终摘要")

    def test_plain_text(self) -> None:
        self.assertEqual(reduce_frames(["你好"]), "你好")


class TestDispatchInjectsUrl(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_passes_skill_url_not_model_args(self) -> None:
        runner = SkillRunner(llm=MagicMock())
        captured: dict = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)
            return "远程回复"

        with patch(
            "skill_sdk.tool.a2a_conversation.run_a2a_chat",
            fake_run,
        ):
            raw = await runner._dispatch_tool(
                "a2a_chat",
                {"message": "今天天气如何"},
                user_id="user-1",
                run_id="run-1",
                trace_id="trace-1",
                a2a_url="http://10.17.0.41:32490",
            )

        parsed = json.loads(raw)
        self.assertEqual(parsed["status"], "success")
        body = json.loads(parsed["content"])
        self.assertEqual(body["text"], "远程回复")
        self.assertEqual(body["url"], "http://10.17.0.41:32490")
        self.assertEqual(captured["base_url"], "http://10.17.0.41:32490")
        self.assertEqual(captured["message"], "今天天气如何")
        self.assertEqual(captured["user_id"], "user-1")
        self.assertEqual(captured["run_id"], "run-1")
        self.assertNotIn("url", captured)


class TestLoadZip(unittest.TestCase):
    def test_zip_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "a2a-chat.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for name in ("_meta.json", "SKILL.md"):
                    zf.write(_SKILL_DIR / name, arcname=name)
            with SkillLoader() as loader:
                skill = loader.load(zip_path)
        self.assertEqual(skill.a2a_url, "http://10.17.0.41:32490")
        self.assertEqual(skill.allowed_tools, ["a2a_chat"])


if __name__ == "__main__":
    unittest.main()
