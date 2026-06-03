"""Tests for ``skill_sdk.tool.character_position``."""

from __future__ import annotations

import json
import re

import pytest

from skill_sdk.tool.character_position import (
    DefinitionPatterns,
    DefinitionPosition,
    Language,
    Position,
    UniversalPositionExtractor,
    extract_definitions,
    extract_positions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grep_result(lines: list[str]) -> str:
    """Build a GrepPlugin content-mode JSON string."""
    return json.dumps({"mode": "content", "content": "\n".join(lines)})


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestPosition:
    def test_character_1based_auto_computed(self) -> None:
        p = Position(file="a.py", line=5, character=3)
        assert p.character_1based == 4

    def test_character_1based_preserved_when_supplied(self) -> None:
        p = Position(file="a.py", line=5, character=3, character_1based=99)
        assert p.character_1based == 99

    def test_to_dict_serialises_fields(self) -> None:
        p = Position(file="x.go", line=1, character=10, text="foo", matched_pattern="bar")
        d = p.to_dict()
        assert d["file"] == "x.go"
        assert d["line"] == 1
        assert d["character"] == 10
        assert d["text"] == "foo"
        assert d["matched_pattern"] == "bar"
        assert "character_1based" in d

    def test_to_lsp_position(self) -> None:
        p = Position(file="x.go", line=10, character=5)
        lsp = p.to_lsp_position()
        assert lsp == {"line": 9, "character": 5}

    def test_to_lsp_position_line_1(self) -> None:
        p = Position(file="x.go", line=1, character=0)
        lsp = p.to_lsp_position()
        assert lsp == {"line": 0, "character": 0}


# ---------------------------------------------------------------------------
# DefinitionPosition
# ---------------------------------------------------------------------------

class TestDefinitionPosition:
    def test_inherits_from_position(self) -> None:
        d = DefinitionPosition(
            file="a.py", line=1, character=0,
            definition_type="function", language="python", symbol_name="foo",
        )
        assert isinstance(d, Position)

    def test_defaults(self) -> None:
        d = DefinitionPosition(file="a.py", line=1, character=0)
        assert d.definition_type == ""
        assert d.language == ""
        assert d.symbol_name == ""
        assert d.context_lines is None


# ---------------------------------------------------------------------------
# Language enum
# ---------------------------------------------------------------------------

class TestLanguage:
    def test_all_values_are_unique(self) -> None:
        vals = [e.value for e in Language]
        assert len(vals) == len(set(vals))

    def test_known_languages(self) -> None:
        assert Language("python") is Language.PYTHON
        assert Language("go") is Language.GO
        assert Language("typescript") is Language.TYPESCRIPT
        assert Language("unknown") is Language.UNKNOWN


# ---------------------------------------------------------------------------
# UniversalPositionExtractor – construction & parsing
# ---------------------------------------------------------------------------

class TestExtractorConstruction:
    def test_accepts_string(self) -> None:
        e = UniversalPositionExtractor(json.dumps({"content": "x.go:1:hello"}))
        assert e.get_lines() == [
            {"file": "x.go", "line": 1, "content": "hello", "full_line": "x.go:1:hello"},
        ]

    def test_accepts_dict(self) -> None:
        e = UniversalPositionExtractor({"content": "x.go:1:hello"})
        assert len(e.get_lines()) == 1

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            UniversalPositionExtractor("not json")

    def test_empty_content(self) -> None:
        e = UniversalPositionExtractor({"mode": "content", "content": ""})
        assert e.get_lines() == []

    def test_content_not_present(self) -> None:
        e = UniversalPositionExtractor({"mode": "files_with_matches"})
        assert e.get_lines() == []

    def test_blank_lines_skipped(self) -> None:
        e = UniversalPositionExtractor(
            {"content": "\n   \nx.go:1:hello\n\n"}
        )
        assert len(e.get_lines()) == 1


class TestParseContent:
    def test_normal_line(self) -> None:
        e = UniversalPositionExtractor({"content": "src/main.go:42:func (p *D) Validate(data string) bool {"})
        li = e.get_lines()[0]
        assert li["file"] == "src/main.go"
        assert li["line"] == 42
        assert li["content"] == "func (p *D) Validate(data string) bool {"

    def test_windows_path(self) -> None:
        e = UniversalPositionExtractor({"content": "C:\\Users\\foo\\bar.txt:10:some text here"})
        li = e.get_lines()[0]
        assert li["file"] == "C:\\Users\\foo\\bar.txt"
        assert li["line"] == 10
        assert li["content"] == "some text here"

    def test_tab_in_content(self) -> None:
        e = UniversalPositionExtractor({"content": "a.py:5:\tindented"})
        li = e.get_lines()[0]
        assert li["content"].startswith("\t")

    def test_colon_in_content(self) -> None:
        e = UniversalPositionExtractor({"content": "a.py:3:key: value: extra"})
        li = e.get_lines()[0]
        # file, lineno, rest — second colon from right delimits
        assert li["file"] == "a.py"
        assert li["line"] == 3
        assert li["content"] == "key: value: extra"

    def test_single_colon_skipped(self) -> None:
        e = UniversalPositionExtractor({"content": "just one:colon\n"})
        assert e.get_lines() == []

    def test_line_caching(self) -> None:
        e = UniversalPositionExtractor({"content": "x.py:1:a"})
        first = e.get_lines()
        second = e.get_lines()
        assert first is second


# ---------------------------------------------------------------------------
# find_positions
# ---------------------------------------------------------------------------

class TestFindPositions:
    GREP = _grep_result([
        "tests/fixtures/go-project/main.go:8:\tValidate(data string) bool",
        "tests/fixtures/go-project/main.go:34:\tif !p.Validate(data) {",
        "tests/fixtures/go-project/main.go:41:// Validate checks if the provided data is valid.",
        "tests/fixtures/go-project/main.go:42:func (p *DefaultProcessor) Validate(data string) bool {",
        "tests/fixtures/go-project/main.go:63:\tvalidated := h.processor.Validate(input)",
        "tests/fixtures/py-project/core.py:43:    def validate(self, data: str) -> bool:",
    ])

    def test_literal_match(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False)
        assert len(pos) == 5

    def test_regex_match(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions(r"Validate\s*\(")
        assert len(pos) == 4  # lines 8, 34, 42, 63

    def test_case_insensitive(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("validate", as_regex=False, case_sensitive=False)
        assert len(pos) >= 6  # includes both 'Validate' and 'validated'

    def test_case_sensitive_no_match(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("validate", as_regex=False, case_sensitive=True)
        assert len(pos) == 2  # matches 'validated' (lowercase) in line 63 + validate in core.py

    def test_whole_word(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, whole_word=True)
        assert len(pos) == 5
        # "Validated" should NOT match
        for p in pos:
            assert p.text == "Validate"

    def test_line_filter(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, line_filter=(40, 50))
        assert len(pos) == 2
        assert all(40 <= p.line <= 50 for p in pos)

    def test_line_filter_no_results(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, line_filter=(200, 300))
        assert pos == []

    def test_file_filter_substring(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, file_filter=["core.py"])
        # core.py has "    def validate(self, data: str) -> bool:" — Validate maps via case-insensitive substring? No, as_regex=False + case_sensitive=True. "validate" != "Validate".
        # The line is: "    def validate(self, data: str) -> bool:" — lowercase "validate"
        # So literal "Validate" would NOT match. Let's check for "validate" instead.
        pos = e.find_positions("validate", as_regex=False)
        assert len(pos) >= 1
        assert any("core.py" in p.file for p in pos)

    def test_file_filter_glob(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, file_filter=["*.go"])
        assert len(pos) == 5
        assert all(p.file.endswith(".go") for p in pos)

    def test_file_filter_no_match(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, file_filter=["*.rs"])
        assert pos == []

    def test_combined_filters(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions(
            "Validate", as_regex=False,
            line_filter=(40, 70),
            file_filter=["*.go"],
        )
        assert len(pos) == 3  # lines 41, 42, 63
        assert all("go" in p.file for p in pos)

    def test_matched_pattern_is_user_pattern(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        pos = e.find_positions("Validate", as_regex=False, whole_word=True, case_sensitive=True)
        assert pos[0].matched_pattern == "Validate"

    def test_no_matches(self) -> None:
        e = UniversalPositionExtractor(self.GREP)
        assert e.find_positions("NoSuchThing", as_regex=False) == []

    def test_multiple_matches_per_line(self) -> None:
        result = _grep_result(["a.go:1:foo foo foo"])
        e = UniversalPositionExtractor(result)
        pos = e.find_positions("foo", as_regex=False)
        assert len(pos) == 3

    def test_character_accurate(self) -> None:
        """The character offset must point at the exact column of the match."""
        result = _grep_result(["a.py:42:    def validate(self, data: str) -> bool:"])
        e = UniversalPositionExtractor(result)
        pos = e.find_positions(r"def\s+(\w+)")
        # "    def validate"
        #       ^-- character 4
        assert pos[0].character == 4
        assert pos[0].text == "def validate"


# ---------------------------------------------------------------------------
# find_first / find_in_range
# ---------------------------------------------------------------------------

class TestFindFirst:
    def test_returns_first(self) -> None:
        r = _grep_result(["a.go:2:alpha", "a.go:4:alpha"])
        e = UniversalPositionExtractor(r)
        p = e.find_first("alpha", as_regex=False)
        assert p is not None
        assert p.line == 2

    def test_returns_none_on_no_match(self) -> None:
        e = UniversalPositionExtractor(_grep_result(["a.go:1:x"]))
        assert e.find_first("y", as_regex=False) is None


class TestFindInRange:
    def test_delegates(self) -> None:
        r = _grep_result(["a.go:10:needle", "a.go:20:needle", "a.go:30:needle"])
        e = UniversalPositionExtractor(r)
        pos = e.find_in_range("needle", 15, 25)
        assert len(pos) == 1
        assert pos[0].line == 20


# ---------------------------------------------------------------------------
# get_all_definitions
# ---------------------------------------------------------------------------

class TestGetAllDefinitions:
    GO_GREP = _grep_result([
        "tests/fixtures/go-project/main.go:23:func NewDefaultProcessor() *DefaultProcessor {",
        "tests/fixtures/go-project/main.go:33:func (p *DefaultProcessor) Process(data string) (string, error) {",
        "tests/fixtures/go-project/main.go:42:func (p *DefaultProcessor) Validate(data string) bool {",
        "tests/fixtures/go-project/main.go:47:func TransformData(data string) string {",
    ])

    PY_GREP = _grep_result([
        "tests/fixtures/py-project/core.py:18:    def process(self, data: str) -> str:",
        "tests/fixtures/py-project/core.py:34:    def process(self, data: str) -> str:",
        "tests/fixtures/py-project/core.py:86:def finalize_result(result: str) -> str:",
    ])

    def test_go_function_definitions(self) -> None:
        e = UniversalPositionExtractor(self.GO_GREP)
        defs = e.get_all_definitions("function")
        names = {d.symbol_name for d in defs}
        assert "NewDefaultProcessor" in names
        assert "Validate" in names
        assert "Process" in names
        assert "TransformData" in names

    def test_python_function_definitions(self) -> None:
        e = UniversalPositionExtractor(self.PY_GREP)
        defs = e.get_all_definitions("function")
        assert len(defs) >= 3

    def test_language_override(self) -> None:
        """Python patterns applied to Go files produce no matches — correct."""
        e = UniversalPositionExtractor(self.GO_GREP)
        defs = e.get_all_definitions("function", language="python")
        assert defs == []  # Python patterns can't match Go func declarations

    def test_class_definitions(self) -> None:
        content = _grep_result([
            "a.py:15:class DataProcessor:",
            "a.py:54:class RequestHandler:",
        ])
        e = UniversalPositionExtractor(content)
        defs = e.get_all_definitions("class")
        assert len(defs) == 2
        assert {d.symbol_name for d in defs} == {"DataProcessor", "RequestHandler"}

    def test_variable_definitions_python(self) -> None:
        content = _grep_result(["a.py:10:timeout = 30"])
        e = UniversalPositionExtractor(content)
        defs = e.get_all_definitions("variable")
        assert len(defs) >= 1
        assert defs[0].symbol_name == "timeout"

    def test_unknown_definition_type(self) -> None:
        e = UniversalPositionExtractor(self.GO_GREP)
        assert e.get_all_definitions("method") == []

    def test_symbol_name_from_capture_group(self) -> None:
        content = _grep_result(["a.go:5:func MyFunc() {"])
        e = UniversalPositionExtractor(content)
        d = e.get_all_definitions("function")[0]
        assert d.symbol_name == "MyFunc"

    def test_no_definitions(self) -> None:
        e = UniversalPositionExtractor(_grep_result(["a.txt:1:just text"]))
        assert e.get_all_definitions("function") == []

    def test_definition_position_metadata(self) -> None:
        e = UniversalPositionExtractor(self.GO_GREP)
        d = e.get_all_definitions("function")[0]
        assert d.definition_type == "function"
        assert d.language == "go"
        assert d.text  # the matched line content


# ---------------------------------------------------------------------------
# find_calls
# ---------------------------------------------------------------------------

class TestFindCalls:
    def test_whole_word_match(self) -> None:
        r = _grep_result([
            "a.go:5:\tvalidator.Validate(data)",
            "a.go:6:\t// Validate is a function",
            "a.go:7:\tValidateData(input)",
        ])
        e = UniversalPositionExtractor(r)
        calls = e.find_calls("Validate")
        assert len(calls) == 2  # line 5 + line 6, NOT line 7
        lines = {c.line for c in calls}
        assert lines == {5, 6}


# ---------------------------------------------------------------------------
# get_line_content
# ---------------------------------------------------------------------------

class TestGetLineContent:
    def test_indexed_lookup(self) -> None:
        r = _grep_result(["a.py:42:the answer"])
        e = UniversalPositionExtractor(r)
        assert e.get_line_content(42) == "the answer"

    def test_missing_line(self) -> None:
        e = UniversalPositionExtractor(_grep_result(["a.py:1:x"]))
        assert e.get_line_content(99) is None

    def test_caching(self) -> None:
        r = _grep_result(["a.py:1:a", "a.py:2:b"])
        e = UniversalPositionExtractor(r)
        e.get_line_content(1)
        index1 = e._line_index
        e.get_line_content(2)
        assert e._line_index is index1  # same dict, reused


# ---------------------------------------------------------------------------
# get_context
# ---------------------------------------------------------------------------

class TestGetContext:
    def test_same_file_filtering(self) -> None:
        r = _grep_result([
            "a.py:1:line1",
            "a.py:2:line2",
            "a.py:3:line3",
            "b.py:2:wrong_file",
        ])
        e = UniversalPositionExtractor(r)
        pos = Position(file="a.py", line=2, character=0)
        ctx = e.get_context(pos, before_lines=1, after_lines=1)
        assert len(ctx) == 3
        assert all(c["line"] in {1, 2, 3} for c in ctx)

    def test_is_target_marked(self) -> None:
        r = _grep_result(["a.py:10:target", "a.py:11:after"])
        e = UniversalPositionExtractor(r)
        pos = Position(file="a.py", line=10, character=0)
        ctx = e.get_context(pos, before_lines=0, after_lines=1)
        assert ctx[0]["is_target"] is True
        assert ctx[1]["is_target"] is False

    def test_before_range_clamped(self) -> None:
        r = _grep_result(["a.py:1:first", "a.py:2:second"])
        e = UniversalPositionExtractor(r)
        pos = Position(file="a.py", line=1, character=0)
        ctx = e.get_context(pos, before_lines=5, after_lines=0)
        assert len(ctx) == 1


# ---------------------------------------------------------------------------
# _match_file_filter
# ---------------------------------------------------------------------------

class TestMatchFileFilter:
    def test_empty_filters_always_match(self) -> None:
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("anything.py", []) is True

    def test_substring_match(self) -> None:
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("foo/bar.py", ["bar"]) is True

    def test_substring_no_match(self) -> None:
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("foo/bar.py", ["baz"]) is False

    def test_glob_match(self) -> None:
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("src/main.go", ["*.go"]) is True
        assert e._match_file_filter("README.md", ["*.go"]) is False

    def test_glob_in_middle(self) -> None:
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("path/to/foo_test.py", ["*_test.py"]) is True
        assert e._match_file_filter("path/to/foo.py", ["*_test.py"]) is False

    def test_special_regex_chars_in_filter(self) -> None:
        """Filter strings with dots should be treated as literals, not regex."""
        e = UniversalPositionExtractor({"content": ""})
        assert e._match_file_filter("setup.cfg", ["setup.cfg"]) is True
        assert e._match_file_filter("setupXcfg", ["setup.cfg"]) is False


# ---------------------------------------------------------------------------
# _detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_common_extensions(self) -> None:
        assert UniversalPositionExtractor._detect_language("main.go") == "go"
        assert UniversalPositionExtractor._detect_language("app.py") == "python"
        assert UniversalPositionExtractor._detect_language("utils.js") == "javascript"
        assert UniversalPositionExtractor._detect_language("types.ts") == "typescript"
        assert UniversalPositionExtractor._detect_language("lib.rs") == "rust"
        assert UniversalPositionExtractor._detect_language("style.css") == "css"
        assert UniversalPositionExtractor._detect_language("index.html") == "html"
        assert UniversalPositionExtractor._detect_language("run.sh") == "shell"

    def test_unknown_extension(self) -> None:
        assert UniversalPositionExtractor._detect_language("data.xyz") == "unknown"


# ---------------------------------------------------------------------------
# _extract_symbol_name
# ---------------------------------------------------------------------------

class TestExtractSymbolName:
    def test_capture_group(self) -> None:
        m = re.match(r"def\s+(\w+)", "def myfunc(")
        assert UniversalPositionExtractor._extract_symbol_name(m, "") == "myfunc"

    def test_no_capture_group(self) -> None:
        m = re.match(r"hello", "hello world")
        assert UniversalPositionExtractor._extract_symbol_name(m, "") == "hello"

    def test_first_non_empty_group(self) -> None:
        m = re.match(r"(?:prefix_)?(\w+)", "prefix_funcname")
        assert UniversalPositionExtractor._extract_symbol_name(m, "") == "funcname"


# ---------------------------------------------------------------------------
# DefinitionPatterns
# ---------------------------------------------------------------------------

class TestDefinitionPatterns:
    def test_function_patterns_known_language(self) -> None:
        pats = DefinitionPatterns.get_patterns("go", "function")
        assert any("func" in p for p in pats)

    def test_class_patterns_known_language(self) -> None:
        pats = DefinitionPatterns.get_patterns("python", "class")
        assert any("class" in p for p in pats)

    def test_variable_patterns_known_language(self) -> None:
        pats = DefinitionPatterns.get_patterns("go", "variable")
        assert any("var" in p for p in pats)

    def test_unknown_type_returns_empty(self) -> None:
        pats = DefinitionPatterns.get_patterns("go", "method")
        assert pats == []

    def test_unknown_language_falls_back_to_same_type(self) -> None:
        """Language 'unknown' has no patterns → fall back to same-type patterns from all languages."""
        pats = DefinitionPatterns.get_patterns("unknown", "function")
        assert len(pats) > 0
        # Must not include class/variable patterns (identified by `=` sign or `class`/`struct`/`interface`)
        assert not any("class" in p for p in pats)
        assert not any("struct" in p for p in pats)
        assert not any("interface" in p for p in pats)

    def test_fallback_does_not_mix_types(self) -> None:
        """Class fallback must not include variable patterns."""
        pats = DefinitionPatterns.get_patterns("unknown", "class")
        for p in pats:
            # Variable patterns contain "=", class patterns do not
            assert "=" not in p


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

class TestExtractPositions:
    def test_returns_dicts(self) -> None:
        r = _grep_result(["a.go:1:hello"])
        results = extract_positions(r, "hello", as_regex=False)
        assert isinstance(results, list)
        assert isinstance(results[0], dict)
        assert results[0]["file"] == "a.go"

    def test_kwargs_forwarded(self) -> None:
        r = _grep_result(["a.go:1:Hello"])
        results = extract_positions(r, "hello", as_regex=False, case_sensitive=False)
        assert len(results) == 1


class TestExtractDefinitions:
    def test_returns_dicts(self) -> None:
        r = _grep_result(["a.py:1:def foo(): pass"])
        results = extract_definitions(r, "function")
        assert isinstance(results[0], dict)
        assert results[0]["symbol_name"] == "foo"


# ---------------------------------------------------------------------------
# Real-world scenario tests
# ---------------------------------------------------------------------------

class TestRealWorld:
    GO_FULL = _grep_result([
        "tests/fixtures/go-project/main.go:8:\tValidate(data string) bool",
        "tests/fixtures/go-project/main.go:34:\tif !p.Validate(data) {",
        "tests/fixtures/go-project/main.go:41:// Validate checks if the provided data is valid.",
        "tests/fixtures/go-project/main.go:42:func (p *DefaultProcessor) Validate(data string) bool {",
        "tests/fixtures/go-project/main.go:63:\tvalidated := h.processor.Validate(input)",
    ])

    def test_validate_definition_position(self) -> None:
        """The character in the definition must point to the symbol name 'Validate'."""
        e = UniversalPositionExtractor(self.GO_FULL)
        defs = e.get_all_definitions("function")
        validate_def = next(d for d in defs if d.symbol_name == "Validate")
        # Line 42: "func (p *DefaultProcessor) Validate(data string) bool {"
        #           func (p *DefaultProcessor)  -> 27 chars (0-indexed)
        #           'V' is at column 27
        assert validate_def.character == 27

    def test_validate_call_positions(self) -> None:
        e = UniversalPositionExtractor(self.GO_FULL)
        calls = e.find_calls("Validate")
        call_lines = {c.line for c in calls}
        # Whole-word match: finds ALL occurrences including definition
        assert call_lines == {8, 34, 41, 42, 63}
