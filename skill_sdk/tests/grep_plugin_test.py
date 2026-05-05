"""Tests for ``skill_sdk.tool.grep_plugin``."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skill_sdk.tool.grep_plugin import (
    GrepPlugin,
    apply_head_limit,
)


RG_MISSING = shutil.which("rg") is None


class TestApplyHeadLimit(unittest.TestCase):
    def test_default_cap_truncates(self) -> None:
        items = list(range(400))
        sliced, lim = apply_head_limit(items, None, offset=0)
        self.assertEqual(len(sliced), 250)
        self.assertEqual(lim, 250)

    def test_zero_means_unlimited(self) -> None:
        items = list(range(10))
        sliced, lim = apply_head_limit(items, 0, offset=0)
        self.assertEqual(len(sliced), 10)
        self.assertIsNone(lim)


@unittest.skipIf(RG_MISSING, "ripgrep (rg) not installed")
class TestGrepPluginRg(unittest.TestCase):
    def test_files_with_matches(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("hello NEEDLE_MARKER grep_test_aa\n", encoding="utf-8")
            (Path(tmp) / "b.py").write_text("# quiet\n", encoding="utf-8")
            raw = plug.execute(pattern=r"NEEDLE_MARKER grep_test_aa", path=tmp, head_limit=10)
            data = json.loads(raw)
            self.assertNotIn("error", data)
            self.assertEqual(data["mode"], "files_with_matches")
            self.assertEqual(data["numFiles"], 1)
            self.assertTrue(any(str(p).endswith("a.py") for p in data["filenames"]))

    def test_content_mode(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("alpha unique_beta_gamma delta\n", encoding="utf-8")
            raw = plug.execute(
                pattern="unique_beta_gamma",
                path=tmp,
                output_mode="content",
                head_limit=20,
            )
            data = json.loads(raw)
            self.assertEqual(data["mode"], "content")
            self.assertIn("unique_beta_gamma", data["content"])

    def test_count_mode(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "t.rs").write_text("fn foo() {}\nfn foo() {}\n", encoding="utf-8")
            raw = plug.execute(pattern=r"\bfn\b", path=tmp, output_mode="count")
            data = json.loads(raw)
            self.assertEqual(data["mode"], "count")
            self.assertGreaterEqual(data["numMatches"], 2)


class TestGrepPluginWithoutRg(unittest.TestCase):
    def test_reports_when_rg_missing(self) -> None:
        if not RG_MISSING:
            self.skipTest("rg present")

        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "z.py").write_text("x\n", encoding="utf-8")
            raw = plug.execute(pattern="x", path=tmp)
            data = json.loads(raw)
            self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
