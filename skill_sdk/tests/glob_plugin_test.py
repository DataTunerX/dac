"""Tests for ``skill_sdk.tool.glob_plugin``."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from skill_sdk.tool.glob_plugin import (
    GlobPlugin,
    extract_glob_base_directory,
    run_file_glob,
)


class TestExtractGlobBase(unittest.TestCase):
    def test_relative_pattern(self) -> None:
        self.assertEqual(extract_glob_base_directory("**/*.py"), ("", "**/*.py"))

    def test_absolute_unix(self) -> None:
        base, rel = extract_glob_base_directory("/*.txt")
        self.assertEqual(base, "/")
        self.assertEqual(rel, "*.txt")


class TestGlobPlugin(unittest.TestCase):
    def test_execute_finds_files_mtime_order(self) -> None:
        plug = GlobPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "old.txt"
            b = Path(tmp) / "new.txt"
            a.write_text("a", encoding="utf-8")
            time.sleep(0.02)
            b.write_text("b", encoding="utf-8")

            raw = plug.execute(pattern="*.txt", path=tmp)
            data = json.loads(raw)
            self.assertNotIn("error", data)
            self.assertEqual(data["numFiles"], 2)
            self.assertFalse(data["truncated"])
            names = [Path(p).name for p in data["filenames"]]
            # oldest first (matches Claude glob.ts comment)
            self.assertEqual(names, ["old.txt", "new.txt"])

    def test_execute_missing_dir(self) -> None:
        plug = GlobPlugin()
        raw = plug.execute(pattern="*", path="/nonexistent_dir_xyz_12345")
        data = json.loads(raw)
        self.assertIn("error", data)

    def test_run_file_glob_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                (Path(tmp) / f"f{i}.txt").write_text(str(i), encoding="utf-8")
            out = run_file_glob("*.txt", tmp, cwd_for_relative=tmp, limit=3, offset=0)
            self.assertTrue(out["truncated"])
            self.assertEqual(out["numFiles"], 3)


if __name__ == "__main__":
    unittest.main()
