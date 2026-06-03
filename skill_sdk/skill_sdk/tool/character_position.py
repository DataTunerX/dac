import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum, unique

# ============================================================================
# Data models
# ============================================================================

@dataclass
class Position:
    """Source position within a file.

    Fields:
        file: Absolute or relative file path.
        line: 1-based line number.
        character: 0-based column offset within the line.
        character_1based: 1-based column (auto-computed from *character*).
        text: The matched text.
        matched_pattern: The user-supplied pattern that produced this match.
    """
    file: str
    line: int
    character: int  # 0-based column
    character_1based: int = 0  # 1-based column
    text: str = ""
    matched_pattern: str = ""

    def __post_init__(self):
        if self.character_1based == 0:
            self.character_1based = self.character + 1

    def to_dict(self) -> dict:
        return asdict(self)

    def to_lsp_position(self) -> dict:
        """Convert to an LSP ``Position`` literal."""
        return {
            "line": self.line - 1,  # LSP uses 0-based lines
            "character": self.character,
        }


@dataclass
class DefinitionPosition(Position):
    """Position of a symbol definition (function, class, variable, ...).

    Fields:
        definition_type: ``'function'``, ``'class'``, or ``'variable'``.
        language: Detected language (e.g. ``'go'``, ``'python'``).
        symbol_name: Extracted symbol identifier.
        context_lines: Surrounding source lines (when populated).
    """
    definition_type: str = ""
    language: str = ""
    symbol_name: str = ""
    context_lines: Optional[List[dict]] = None


@unique
class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    JAVA = "java"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    RUBY = "ruby"
    PHP = "php"
    SWIFT = "swift"
    KOTLIN = "kotlin"
    CSHARP = "csharp"
    HTML = "html"
    CSS = "css"
    SHELL = "shell"
    UNKNOWN = "unknown"


# ============================================================================
# Core extractor
# ============================================================================

class UniversalPositionExtractor:
    """Extract character-accurate positions from GrepPlugin JSON output."""
    
    def __init__(self, grep_json: Union[str, dict]):
        """*grep_json* may be a JSON string or already-parsed dict from
        :class:`~skill_sdk.tool.grep_plugin.GrepPlugin`.
        """
        if isinstance(grep_json, str):
            self.data = json.loads(grep_json)
        else:
            self.data = grep_json
        
        self._parsed_lines = None
        self._line_index: Optional[Dict[int, str]] = None

    _LINE_BOUNDARY = re.compile(r':(\d+):')

    def get_lines(self) -> List[dict]:
        """Return parsed line data."""
        if self._parsed_lines is None:
            self._parsed_lines = self._parse_content()
        return self._parsed_lines
    
    def _parse_content(self) -> List[dict]:
        """Parse the content field into structured line data.

        The format is ``file:lineno:content``.  Column-sensitive — leading
        whitespace in *content* is preserved so that character offsets are
        accurate.

        Handles Windows paths (``C:\\foo\\bar.txt:10:text``) and colons
        appearing inside the content itself (e.g. Go ``:=`` assignments
        or Python ``: str`` type annotations).
        """
        results = []
        text = self.data.get('content', '')

        for line in text.split('\n'):
            if not line.strip():
                continue

            # Find the rightmost  :<digits>:  boundary — this is the
            # separator between the line number and the actual content.
            matches = list(self._LINE_BOUNDARY.finditer(line))
            if not matches:
                continue

            m = matches[-1]
            results.append({
                'file': line[:m.start()],
                'line': int(m.group(1)),
                'content': line[m.end():].rstrip('\r'),
                'full_line': line.rstrip('\r'),
            })

        return results
    
    def find_positions(
        self,
        pattern: str,
        as_regex: bool = True,
        case_sensitive: bool = True,
        whole_word: bool = False,
        line_filter: Optional[Tuple[int, int]] = None,
        file_filter: Optional[List[str]] = None
    ) -> List[Position]:
        """Find all positions matching *pattern* across parsed lines.

        Args:
            pattern: Search pattern
            as_regex: Treat *pattern* as a regex
            case_sensitive: Case-sensitive matching
            whole_word: Match whole words only
            line_filter: (start, end) line range
            file_filter: File paths to include (supports ``*`` wildcard)

        Returns:
            List of ``Position`` objects.
        """
        user_pattern = pattern

        if not as_regex:
            pattern = re.escape(pattern)

        if whole_word:
            pattern = rf'\b{pattern}\b'

        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        results = []
        for line_info in self.get_lines():
            if line_filter and not (line_filter[0] <= line_info['line'] <= line_filter[1]):
                continue

            if file_filter and not self._match_file_filter(line_info['file'], file_filter):
                continue

            content = line_info['content']
            for match in regex.finditer(content):
                results.append(Position(
                    file=line_info['file'],
                    line=line_info['line'],
                    character=match.start(),
                    text=match.group(),
                    matched_pattern=user_pattern,
                ))

        return results
    
    def find_first(self, pattern: str, **kwargs) -> Optional[Position]:
        """Return the first matching position, or ``None``."""
        positions = self.find_positions(pattern, **kwargs)
        return positions[0] if positions else None

    def find_in_range(
        self,
        pattern: str,
        start_line: int,
        end_line: int,
        **kwargs,
    ) -> List[Position]:
        """Find positions within [*start_line*, *end_line*] (inclusive)."""
        return self.find_positions(pattern, line_filter=(start_line, end_line), **kwargs)
    
    def get_all_definitions(
        self,
        definition_type: str = 'function',
        language: Optional[str] = None,
    ) -> List[DefinitionPosition]:
        """Extract all definition positions of the given type.

        Args:
            definition_type: One of ``'function'``, ``'class'``, ``'variable'``.
            language: Language override; auto-detected from extension when ``None``.

        Returns:
            List of ``DefinitionPosition`` objects.
        """
        results = []

        for line_info in self.get_lines():
            lang = language or self._detect_language(line_info['file'])
            patterns = DefinitionPatterns.get_patterns(lang, definition_type)

            content = line_info['content']
            for pattern in patterns:
                match = re.search(pattern, content)
                if not match:
                    continue

                symbol_name = self._extract_symbol_name(match, content)
                match_start = match.start()

                if match.groups():
                    for group in match.groups():
                        if group:
                            pos = content.find(group, match_start)
                            if pos >= 0:
                                match_start = pos
                                symbol_name = group
                                break

                results.append(DefinitionPosition(
                    file=line_info['file'],
                    line=line_info['line'],
                    character=match_start,
                    text=content,
                    matched_pattern=pattern,
                    definition_type=definition_type,
                    language=lang,
                    symbol_name=symbol_name,
                ))
                break  # first matching pattern wins

        return results

    def find_calls(self, symbol_name: str) -> List[Position]:
        """Find all call sites of *symbol_name* (whole-word match)."""
        return self.find_positions(
            rf'\b{re.escape(symbol_name)}\b',
            as_regex=True,
        )

    def get_line_content(self, line_number: int) -> Optional[str]:
        """Return the text of *line_number*, or ``None``."""
        if self._line_index is None:
            self._line_index = {
                li['line']: li['content'] for li in self.get_lines()
            }
        return self._line_index.get(line_number)
    
    def get_context(
        self,
        position: Position,
        before_lines: int = 2,
        after_lines: int = 2,
    ) -> List[dict]:
        """Return surrounding lines from the same file as *position*."""
        context = []
        target_line = position.line

        for line_info in self.get_lines():
            if line_info['file'] != position.file:
                continue
            if (
                target_line - before_lines
                <= line_info['line']
                <= target_line + after_lines
            ):
                context.append({
                    'line': line_info['line'],
                    'content': line_info['content'],
                    'is_target': line_info['line'] == target_line,
                })

        return context
    
    def _match_file_filter(self, filepath: str, filters: List[str]) -> bool:
        """Return ``True`` if *filepath* matches any filter pattern."""
        if not filters:
            return True

        for f in filters:
            if '*' in f:
                # Simple glob-style: convert * to .* regex
                pattern = re.escape(f).replace(r'\*', '.*')
                if re.search(pattern, filepath):
                    return True
            elif f in filepath:
                return True
        return False
    
    # ---------------------------------------------------------------
    # Language detection
    # ---------------------------------------------------------------

    _EXT_TO_LANG = {
        '.py': Language.PYTHON.value,
        '.js': Language.JAVASCRIPT.value,
        '.mjs': Language.JAVASCRIPT.value,
        '.ts': Language.TYPESCRIPT.value,
        '.tsx': Language.TYPESCRIPT.value,
        '.go': Language.GO.value,
        '.java': Language.JAVA.value,
        '.rs': Language.RUST.value,
        '.c': Language.C.value,
        '.h': Language.C.value,
        '.cpp': Language.CPP.value,
        '.cc': Language.CPP.value,
        '.cxx': Language.CPP.value,
        '.hpp': Language.CPP.value,
        '.rb': Language.RUBY.value,
        '.erb': Language.RUBY.value,
        '.php': Language.PHP.value,
        '.swift': Language.SWIFT.value,
        '.kt': Language.KOTLIN.value,
        '.kts': Language.KOTLIN.value,
        '.cs': Language.CSHARP.value,
        '.html': Language.HTML.value,
        '.htm': Language.HTML.value,
        '.css': Language.CSS.value,
        '.scss': Language.CSS.value,
        '.sh': Language.SHELL.value,
        '.bash': Language.SHELL.value,
        '.zsh': Language.SHELL.value,
    }

    @classmethod
    def _detect_language(cls, filename: str) -> str:
        """Detect a file's language from its extension."""
        ext = Path(filename).suffix.lower()
        return cls._EXT_TO_LANG.get(ext, Language.UNKNOWN.value)
    
    @staticmethod
    def _extract_symbol_name(match: re.Match, content: str) -> str:
        """Return the first non-empty capture group or the full match."""
        if match.groups():
            for group in match.groups():
                if group:
                    return group
        return match.group(0)


# ============================================================================
# Definition patterns by language
# ============================================================================

class DefinitionPatterns:
    """Regex patterns for function, class, and variable definitions per language."""

    # Function definitions
    FUNCTION_PATTERNS = {
        Language.PYTHON.value: [
            r'^\s*def\s+(\w+)\s*\(',
            r'^\s*async\s+def\s+(\w+)\s*\(',
        ],
        Language.JAVASCRIPT.value: [
            r'^function\s+(\w+)\s*\(',
            r'^const\s+(\w+)\s*=\s*function',
            r'^const\s+(\w+)\s*=\s*\(.*?\)\s*=>',
            r'^function\s*\(.*?\)\s*\{',  # 匿名函数
        ],
        Language.TYPESCRIPT.value: [
            r'^function\s+(\w+)\s*\(',
            r'^const\s+(\w+)\s*=\s*\(.*?\)\s*=>',
            r'^public\s+(\w+)\s*\(',
            r'^private\s+(\w+)\s*\(',
        ],
        Language.GO.value: [
            r'^func\s+(\w+)\s*\(',
            r'^func\s+\([^)]+\)\s+(\w+)\s*\(',
        ],
        Language.JAVA.value: [
            r'^(?:public|private|protected)?\s*(?:static)?\s*(?:\w+)\s+(\w+)\s*\(',
        ],
        Language.RUST.value: [
            r'^fn\s+(\w+)\s*\(',
            r'^pub\s+fn\s+(\w+)\s*\(',
        ],
        Language.C.value: [
            r'^(?:\w+)\s+(\w+)\s*\(',
        ],
        Language.CPP.value: [
            r'^(?:virtual\s+)?(?:\w+)\s+(\w+)\s*\(',
            r'^(?:\w+)\s+(\w+)::\w+\s*\(',
        ],
        Language.RUBY.value: [
            r'^def\s+(\w+)',
            r'^def\s+self\.(\w+)',
        ],
        Language.PHP.value: [
            r'^function\s+(\w+)\s*\(',
        ],
        Language.SWIFT.value: [
            r'^func\s+(\w+)\s*\(',
        ],
        Language.KOTLIN.value: [
            r'^fun\s+(\w+)\s*\(',
        ],
        Language.CSHARP.value: [
            r'^(?:public|private|protected|internal)?\s*(?:static)?\s*(?:\w+)\s+(\w+)\s*\(',
        ],
    }
    
    # Class / type definitions
    CLASS_PATTERNS = {
        Language.PYTHON.value: [r'^\s*class\s+(\w+)'],
        Language.JAVASCRIPT.value: [r'^class\s+(\w+)'],
        Language.TYPESCRIPT.value: [r'^class\s+(\w+)', r'^interface\s+(\w+)'],
        Language.GO.value: [r'^type\s+(\w+)\s+struct', r'^type\s+(\w+)\s+interface'],
        Language.JAVA.value: [r'^(?:public|private)?\s*(?:abstract)?\s*class\s+(\w+)'],
        Language.RUST.value: [r'^struct\s+(\w+)', r'^enum\s+(\w+)', r'^trait\s+(\w+)'],
        Language.CPP.value: [r'^class\s+(\w+)', r'^struct\s+(\w+)'],
        Language.CSHARP.value: [r'^(?:public|private|internal)?\s*class\s+(\w+)'],
    }
    
    # Variable definitions
    VARIABLE_PATTERNS = {
        Language.GO.value: [r'^var\s+(\w+)'],
        Language.JAVASCRIPT.value: [r'^(?:const|let|var)\s+(\w+)\s*='],
        Language.TYPESCRIPT.value: [r'^(?:const|let|var)\s+(\w+)\s*[:=]'],
        Language.PYTHON.value: [r'^(\w+)\s*='],
        Language.RUST.value: [r'^let\s+(\w+)'],
    }
    
    @classmethod
    def get_patterns(cls, language: str, definition_type: str) -> List[str]:
        """Return patterns for *language* / *definition_type*.

        If the language is not configured for the requested type, fall back
        to patterns of the **same type** from all known languages.
        """
        type_map = {
            'function': cls.FUNCTION_PATTERNS,
            'class': cls.CLASS_PATTERNS,
            'variable': cls.VARIABLE_PATTERNS,
        }
        patterns = type_map.get(definition_type, {}).get(language, [])

        if not patterns and definition_type in type_map:
            # Same type, any language
            for lang_pats in type_map[definition_type].values():
                patterns.extend(lang_pats)

        return patterns


# ============================================================================
# Convenience functions
# ============================================================================

def extract_positions(
    grep_result: Union[str, dict],
    pattern: str,
    as_regex: bool = True,
    **kwargs,
) -> List[dict]:
    """Shortcut: build an extractor from *grep_result* and return dicts."""
    extractor = UniversalPositionExtractor(grep_result)
    return [p.to_dict() for p in extractor.find_positions(pattern, as_regex=as_regex, **kwargs)]


def extract_definitions(
    grep_result: Union[str, dict],
    definition_type: str = 'function',
    language: Optional[str] = None,
) -> List[dict]:
    """Shortcut: extract all definitions of a given type as dicts."""
    extractor = UniversalPositionExtractor(grep_result)
    return [d.to_dict() for d in extractor.get_all_definitions(definition_type, language)]


# ============================================================================
# Demo
# ============================================================================

def main():
    _DEMO = json.dumps({
        "mode": "content",
        "content": (
            "tests/fixtures/go-project/main.go:8:\tValidate(data string) bool\n"
            "tests/fixtures/go-project/main.go:34:\tif !p.Validate(data) {\n"
            "tests/fixtures/go-project/main.go:41:// Validate checks if the provided data is valid.\n"
            "tests/fixtures/go-project/main.go:42:func (p *DefaultProcessor) Validate(data string) bool {\n"
            "tests/fixtures/go-project/main.go:63:\tvalidated := h.processor.Validate(input)"
        ),
    })

    extractor = UniversalPositionExtractor(_DEMO)

    # 1. Find all literal "Validate" positions
    print("=== Find all 'Validate' positions ===")
    for pos in extractor.find_positions("Validate", as_regex=False):
        print(f"  {pos.file}:{pos.line}:{pos.character} -> '{pos.text}'")

    # 2. Find function definitions
    print("\n=== Function definitions ===")
    for d in extractor.get_all_definitions('function'):
        print(f"  {d.file}:{d.line}:{d.character} -> function '{d.symbol_name}'")
        print(f"    Line: {d.text}")

    # 3. Context around first definition
    defs = extractor.get_all_definitions('function')
    if defs:
        print("\n=== Context around first definition ===")
        for ctx in extractor.get_context(defs[0], before_lines=1, after_lines=2):
            marker = ">>> " if ctx['is_target'] else "    "
            print(f"  {marker}{ctx['line']}: {ctx['content']}")

    # 4. Convenience function
    print("\n=== Convenience function ===")
    for pos in extract_positions(_DEMO, r'Validate\s*\('):
        print(f"  Found at {pos['file']}:{pos['line']}:{pos['character']}")

    # 5. Range search
    print("\n=== Lines 40-45 ===")
    for pos in extractor.find_in_range("Validate", 40, 45):
        print(f"  {pos.file}:{pos.line}:{pos.character}")

    # 6. Call sites
    print("\n=== Call sites ===")
    for call in extractor.find_calls("Validate"):
        print(f"  {call.file}:{call.line}:{call.character} -> call to Validate")


if __name__ == "__main__":
    main()