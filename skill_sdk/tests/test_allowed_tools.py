"""Tests for skill ``allowed_tools`` allow-list (``_meta.json`` → Runner)."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from skill_sdk.api.base import Skill
from skill_sdk.skill.loader import SkillLoader, SkillMarkdownData
from skill_sdk.skill.runner import ALWAYS_ALLOWED_TOOLS, SkillRunner

_SDK_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_DIR = _SDK_ROOT / "skills"


class TestParseAllowedTools(unittest.TestCase):
    def test_missing_means_empty(self) -> None:
        self.assertEqual(SkillLoader._parse_allowed_tools({"version": "1"}), [])

    def test_list(self) -> None:
        self.assertEqual(
            SkillLoader._parse_allowed_tools(
                {"allowed_tools": ["glob", "grep", "glob", "  lsp  ", ""]}
            ),
            ["glob", "grep", "lsp"],
        )

    def test_string(self) -> None:
        self.assertEqual(
            SkillLoader._parse_allowed_tools({"allowed_tools": "glob, grep lsp"}),
            ["glob", "grep", "lsp"],
        )

    def test_invalid_type(self) -> None:
        with self.assertRaises(ValueError):
            SkillLoader._parse_allowed_tools({"allowed_tools": 123})


class TestBuildSkillAllowedTools(unittest.TestCase):
    def test_build_skill_reads_allowed_tools(self) -> None:
        md = SkillMarkdownData(
            name="read-code",
            description="desc",
            detail="body",
        )
        skill = SkillLoader.build_skill(
            {"version": "1.0.0", "allowed_tools": ["glob", "grep"]},
            md,
        )
        self.assertEqual(skill.allowed_tools, ["glob", "grep"])

    def test_build_skill_default_empty(self) -> None:
        md = SkillMarkdownData(name="x", description="d", detail="b")
        skill = SkillLoader.build_skill({"version": "1"}, md)
        self.assertEqual(skill.allowed_tools, [])


class TestLoadReadCodeMeta(unittest.TestCase):
    def test_read_code_dir_meta(self) -> None:
        skill_dir = _SKILLS_DIR / "read-code"
        if not skill_dir.is_dir():
            self.skipTest("skills/read-code not present")
        meta = SkillLoader.read_meta_json(skill_dir)
        md = SkillLoader.read_skill_md(skill_dir)
        skill = SkillLoader.build_skill(meta, md, base_dir=skill_dir)
        self.assertEqual(skill.name, "read-code")
        self.assertEqual(
            skill.allowed_tools,
            ["glob", "grep", "lsp", "readline_in_range"],
        )


class TestRunnerToolAllowList(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = SkillRunner(llm=MagicMock())

    def test_unrestricted_when_empty(self) -> None:
        skill = Skill(
            name="legacy",
            description="d",
            detail="b",
            version="1",
            allowed_tools=[],
        )
        self.assertIsNone(self.runner._resolve_allowed_tool_names(skill))
        tools = self.runner._tools_for_skill(skill)
        names = {t.name for t in tools}
        self.assertIn("plan_cmd", names)
        self.assertIn("finish", names)
        self.assertIn("web_fetch", names)
        self.assertTrue(self.runner._is_tool_allowed_for_skill(skill, "web_fetch"))

    def test_read_code_filters_tools(self) -> None:
        skill = Skill(
            name="read-code",
            description="d",
            detail="b",
            version="1",
            allowed_tools=["glob", "grep", "lsp", "readline_in_range"],
        )
        allowed = self.runner._resolve_allowed_tool_names(skill)
        assert allowed is not None
        self.assertTrue(ALWAYS_ALLOWED_TOOLS.issubset(allowed))
        self.assertIn("grep", allowed)
        self.assertNotIn("web_fetch", allowed)
        self.assertNotIn("plan_cmd", allowed)

        names = {t.name for t in self.runner._tools_for_skill(skill)}
        self.assertEqual(
            names,
            {"glob", "grep", "lsp", "readline_in_range", "finish"},
        )
        self.assertTrue(self.runner._is_tool_allowed_for_skill(skill, "grep"))
        self.assertTrue(self.runner._is_tool_allowed_for_skill(skill, "finish"))
        self.assertFalse(self.runner._is_tool_allowed_for_skill(skill, "web_fetch"))
        self.assertFalse(self.runner._is_tool_allowed_for_skill(skill, "plan_cmd"))
        self.assertFalse(self.runner._is_tool_allowed_for_skill(skill, "tavily_search"))

    def test_code_execution_allows_code_exec(self) -> None:
        skill = Skill(
            name="code_execution",
            description="d",
            detail="b",
            version="1",
            allowed_tools=["code_exec"],
        )
        # code_exec is only registered when code_execution is passed to SkillRunner
        runner = SkillRunner(llm=MagicMock(), code_execution=MagicMock())
        names = {t.name for t in runner._tools_for_skill(skill)}
        self.assertEqual(names, {"code_exec", "finish"})


class TestLoadZipAllowedTools(unittest.TestCase):
    def test_load_zip_with_allowed_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo-skill"
            root.mkdir()
            (root / "_meta.json").write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "slug": "demo-skill",
                        "allowed_tools": ["glob", "grep"],
                    }
                ),
                encoding="utf-8",
            )
            (root / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: demo\n---\n\nbody\n",
                encoding="utf-8",
            )
            zip_path = Path(tmp) / "demo-skill.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for path in root.rglob("*"):
                    if path.is_file():
                        zf.write(path, arcname=str(path.relative_to(tmp)))

            with SkillLoader() as loader:
                skill = loader.load(zip_path)
            self.assertEqual(skill.name, "demo-skill")
            self.assertEqual(skill.allowed_tools, ["glob", "grep"])


if __name__ == "__main__":
    unittest.main()
