"""Tests for ``skill_sdk.tool.grep_plugin``."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from skill_sdk.tool.grep_plugin import (
    GrepPlugin,
    _alt_is_banned,
    _content_match_stats,
    _is_broad_content_pattern,
    _narrow_content_pattern,
    _normalize_glob_value,
    _parse_rg_content_line,
    _resolve_grep_filters,
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


class TestRgContentLineParse(unittest.TestCase):
    def test_match_vs_context_separators(self) -> None:
        m = _parse_rg_content_line("/tmp/a.py:10:def foo():")
        self.assertEqual(m[:3], ("match", "/tmp/a.py", "10"))
        c = _parse_rg_content_line("/tmp/a.py-9-import os")
        self.assertEqual(c[:3], ("context", "/tmp/a.py", "9"))

    def test_timestamp_in_context_not_fake_match(self) -> None:
        """Regression: context body with 12:00:00 must not invent a fake path."""
        line = (
            '/repo/biz.md-63-        "timestamp": "2025-11-11T12:00:00"'
        )
        parsed = _parse_rg_content_line(line)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], "context")
        self.assertEqual(parsed[1], "/repo/biz.md")
        self.assertEqual(parsed[2], "63")
        matches, files = _content_match_stats([line])
        self.assertEqual(matches, 0)
        self.assertEqual(files, [])

    def test_stats_only_count_match_lines(self) -> None:
        lines = [
            "/tmp/a.py-9-prev",
            "/tmp/a.py:10:HIT",
            "/tmp/a.py-11-next",
            "--",
            '/tmp/b.md-1-        "timestamp": "2025-11-11T12:00:00"',
        ]
        matches, files = _content_match_stats(lines)
        self.assertEqual(matches, 1)
        self.assertEqual(files, ["/tmp/a.py"])

    def test_pathless_single_file_lines(self) -> None:
        """rg omits path on single-file search unless -H."""
        m = _parse_rg_content_line("9:from mcp.server.fastmcp import FastMCP")
        self.assertEqual(m[:3], ("match", "", "9"))
        c = _parse_rg_content_line("8-from datetime import datetime")
        self.assertEqual(c[:3], ("context", "", "8"))
        matches, files = _content_match_stats(
            [
                "8-from datetime import datetime",
                "9:from mcp.server.fastmcp import FastMCP",
                "10-from mcp.server.fastmcp.utilities.logging import get_logger",
            ]
        )
        self.assertEqual(matches, 1)
        self.assertEqual(files, [])


class TestBroadPatternDowngrade(unittest.TestCase):
    def test_kitchen_sink_detected(self) -> None:
        broad, why = _is_broad_content_pattern(
            r"FastAPI|@app\.|uvicorn|MCP|mcp|http|serve|run|port|host"
        )
        self.assertTrue(broad)
        self.assertTrue(why)

    def test_tight_pattern_not_broad(self) -> None:
        broad, _ = _is_broad_content_pattern(
            r"mcp-server|api-server|FastMCP|resource://"
        )
        self.assertFalse(broad)

    def test_narrow_drops_shapeless_alts(self) -> None:
        """Language-agnostic: bare short words / short paths / short flags."""
        pat = (
            r"FastMCP|mcp-server|api-server|FastAPI|@app\.|resource://|/search|"
            r"/register|/discover|/health|/api|def |class |var |fn |"
            r"--run|--transport|--host|--port|--api-host|--api-port"
        )
        new_pat, notes = _narrow_content_pattern(pat)
        self.assertTrue(notes)
        kept = set(new_pat.split("|"))
        for bad in ("def", "class", "var", "fn", "/api", "/health", "--host", "--port"):
            self.assertNotIn(bad, kept)
        self.assertIn("FastMCP", kept)
        self.assertLessEqual(len(kept), 6)

    def test_bare_short_word_banned_any_language(self) -> None:
        for alt in ("def", "class", "func", "fn", "var", "let", "type", "impl"):
            self.assertIsNotNone(_alt_is_banned(alt), alt)
        # Named definition-style alts stay
        self.assertIsNone(_alt_is_banned(r"def\s+cleanup_expired\s*\("))
        self.assertIsNone(_alt_is_banned(r"func\s+\(.*\)\s*Cleanup"))

    def test_tight_protocol_pattern_kept(self) -> None:
        pat = r"mcp-server|api-server|FastMCP|resource://|/search"
        new_pat, notes = _narrow_content_pattern(pat)
        self.assertEqual(new_pat, pat)
        self.assertEqual(notes, [])

    def test_execute_content_auto_narrows_kitchen_sink(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "server.py"
            f.write_text(
                "from mcp.server.fastmcp import FastMCP\n"
                "def foo():\n    pass\n"
                "class Bar:\n    pass\n",
                encoding="utf-8",
            )
            raw = plug.execute(
                pattern=(
                    r"FastMCP|/health|/api|def |class |--host|--port"
                ),
                path=str(f),
                output_mode="content",
            )
            data = json.loads(raw)
            self.assertNotIn("error", data)
            self.assertIn("hint", data)
            self.assertIn("FastMCP", data.get("pattern", "FastMCP"))
            self.assertEqual(data["numMatches"], 1)
            self.assertIn("FastMCP", data["content"])


class TestGlobNormalize(unittest.TestCase):
    def test_bare_ext_normalized(self) -> None:
        self.assertEqual(_normalize_glob_value("py"), "*.py")
        self.assertEqual(_normalize_glob_value(".go"), "*.go")
        self.assertEqual(_normalize_glob_value("**/*.ts"), "**/*.ts")

    def test_wrong_lang_glob_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("x\n", encoding="utf-8")
            g, ft, notes = _resolve_grep_filters(
                glob="**/*.go",
                file_type=None,
                search_root=tmp,
                output_mode="files_with_matches",
            )
            self.assertEqual(g, "*.py")
            self.assertIsNone(ft)
            self.assertTrue(any("instead" in n for n in notes))

    def test_content_dir_auto_source_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("x\n", encoding="utf-8")
            (Path(tmp) / "README.md").write_text("http run\n", encoding="utf-8")
            g, ft, notes = _resolve_grep_filters(
                glob=None,
                file_type=None,
                search_root=tmp,
                output_mode="content",
            )
            self.assertEqual(g, "*.py")
            self.assertIsNone(ft)
            self.assertTrue(any("auto glob" in n for n in notes))


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

    def test_dir_content_kitchen_sink_downgrades(self) -> None:
        """Repo-root content + http|run|port|host… → files_with_matches + hint."""
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "server.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
            )
            (Path(tmp) / "README.md").write_text("run the http server on port host\n", encoding="utf-8")
            raw = plug.execute(
                pattern=r"FastAPI|@app\.|uvicorn|MCP|mcp|http|serve|run|port|host",
                path=tmp,
                output_mode="content",
                case_insensitive=True,
                context_c=2,
            )
            data = json.loads(raw)
            self.assertEqual(data["mode"], "files_with_matches")
            self.assertEqual(data.get("downgraded_from"), "content")
            self.assertIn("hint", data)
            self.assertIn("kitchen-sink", data["hint"].lower() + data["hint"])
            self.assertNotIn("content", data)  # no content dump
            self.assertGreaterEqual(data.get("numFiles", 0), 1)

    def test_content_mode(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("alpha unique_beta_gamma delta\n", encoding="utf-8")
            raw = plug.execute(
                pattern="unique_beta_gamma",
                path=tmp,
                output_mode="content",
                context_c=0,
                head_limit=20,
            )
            data = json.loads(raw)
            self.assertEqual(data["mode"], "content")
            self.assertEqual(data["numMatches"], 1)
            self.assertEqual(data["numLines"], 1)
            self.assertEqual(data["numFiles"], 1)
            self.assertIn("unique_beta_gamma", data["content"])
            self.assertEqual(data["resultLen"], len(data["content"]))
            # Summary fields must precede content so truncated logs still show counts.
            keys = list(data.keys())
            self.assertLess(keys.index("numMatches"), keys.index("content"))
            self.assertLess(keys.index("numLines"), keys.index("content"))
            self.assertLess(keys.index("resultLen"), keys.index("content"))

    def test_content_on_single_file_counts_matches(self) -> None:
        """Regression: single-file rg used to omit path → numMatches stayed 0."""
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "server.py"
            f.write_text(
                "from datetime import datetime\n"
                "from mcp.server.fastmcp import FastMCP\n"
                "from fastapi import FastAPI\n",
                encoding="utf-8",
            )
            raw = plug.execute(
                pattern=r"FastMCP|FastAPI",
                path=str(f),
                output_mode="content",
                context_c=0,
            )
            data = json.loads(raw)
            self.assertGreaterEqual(data["numMatches"], 2)
            self.assertEqual(data["numFiles"], 1)
            self.assertTrue(data["filenames"])
            self.assertIn("FastMCP", data["content"])

    def test_execute_ignores_nonzero_context_c(self) -> None:
        """Plugin policy: context is always 0 even if the model asks for more."""
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text(
                "a\nb\nunique_hit_here\nc\nd\n", encoding="utf-8"
            )
            raw = plug.execute(
                pattern="unique_hit_here",
                path=tmp,
                output_mode="content",
                context_c=3,
                head_limit=50,
            )
            data = json.loads(raw)
            self.assertEqual(data["numMatches"], 1)
            self.assertEqual(data["numLines"], 1)

    def test_count_mode(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "t.rs").write_text("fn foo() {}\nfn foo() {}\n", encoding="utf-8")
            raw = plug.execute(pattern=r"\bfn\b", path=tmp, output_mode="count")
            data = json.loads(raw)
            self.assertEqual(data["mode"], "count")
            self.assertGreaterEqual(data["numMatches"], 2)

    def test_wrong_glob_rewritten_to_repo_language(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "server.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
            )
            raw = plug.execute(
                pattern="FastAPI",
                path=tmp,
                output_mode="content",
                context_c=0,
                glob="**/*.go",
            )
            data = json.loads(raw)
            self.assertGreaterEqual(data.get("numMatches"), 1)
            self.assertEqual(data.get("glob"), "*.py")
            notes = " ".join(data.get("filter_notes") or [])
            self.assertIn("instead", notes + (data.get("hint") or ""))

    def test_context_timestamps_do_not_corrupt_filenames(self) -> None:
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "note.md"
            md.write_text(
                'hello\nMCP server here\n  "timestamp": "2025-11-11T12:00:00"\n',
                encoding="utf-8",
            )
            raw = plug.execute(
                pattern="MCP",
                path=tmp,
                output_mode="content",
                context_c=0,
                head_limit=50,
            )
            data = json.loads(raw)
            self.assertGreaterEqual(data["numMatches"], 1)
            for fp in data["filenames"]:
                self.assertNotIn("timestamp", fp)
                self.assertFalse(re.search(r"-\d+-", fp), fp)

    def test_zero_matches_on_file_path_no_error_hint(self) -> None:
        """Single-file search: no auto glob rewrite; empty result needs no filter hint."""
        plug = GrepPlugin()
        with tempfile.TemporaryDirectory() as tmp:
            f = tmp / Path("a.py")
            f.write_text("hello\n", encoding="utf-8")
            raw = plug.execute(
                pattern="DefinitelyNotInFile_XYZ123",
                path=str(f),
                output_mode="content",
                context_c=0,
            )
            data = json.loads(raw)
            self.assertEqual(data.get("numMatches"), 0)
            self.assertNotIn("hint", data)
            self.assertNotIn("filter_notes", data)

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
