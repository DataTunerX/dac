"""Integration tests: code-agent LSP env + real LSP startup + goToDefinition.

Requires LSP binaries on PATH (as in code-agent Docker image):
  gopls, basedpyright-langserver, jdtls (optional for Java case)

Run:
    cd dac/code-agent
    pytest tests/test_lsp_read_code_integration.py -v -s

Skip automatically when binaries or fixtures are missing.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from agent.lsp_repo_detect import select_lsp_servers_with_workspaces
from agent.skill_runner_service import configure_skill_runtime_env

_CODE_AGENT_ROOT = Path(__file__).resolve().parents[1]
_DAC_ROOT = _CODE_AGENT_ROOT.parent
_SKILL_SDK_FIXTURES = _DAC_ROOT / "skill_sdk" / "tests" / "fixtures"
_GO_FIXTURE = _SKILL_SDK_FIXTURES / "go-project"
_PY_FIXTURE = _SKILL_SDK_FIXTURES / "py-project"


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


HAS_GOPLS = _has("gopls")
HAS_BASEDPYRIGHT = _has("basedpyright-langserver")
HAS_JDTLS = _has("jdtls")
HAS_FIXTURES = _GO_FIXTURE.is_dir() and _PY_FIXTURE.is_dir()

pytestmark = pytest.mark.integration


def _find_symbol(filepath: Path, symbol: str, *, line_hint: str | None = None) -> tuple[int, int]:
    """1-based (line, character) for identifier ``symbol``."""
    lines = filepath.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line_hint is not None and line_hint not in line:
            continue
        idx = line.find(symbol)
        if idx == -1:
            continue
        before = line[idx - 1] if idx > 0 else " "
        after = line[idx + len(symbol)] if idx + len(symbol) < len(line) else " "
        if before.isalnum() or before == "_" or after.isalnum() or after == "_":
            continue
        return (i + 1, idx + 1)
    raise ValueError(f"symbol {symbol!r} not found in {filepath}")


def _parse_lsp_output(output: str) -> dict[str, Any]:
    return json.loads(output) if isinstance(output, str) else output


def _assert_definition_ok(result: dict[str, Any], *, expect_file_fragment: str) -> None:
    assert "error" not in result, result.get("error")
    formatted = result.get("result") or ""
    assert formatted, "empty LSP result"
    assert "Defined in" in formatted or "definitions" in formatted.lower(), formatted
    assert expect_file_fragment in formatted, formatted
    assert (result.get("resultCount") or 0) >= 1, result


@pytest.fixture
def lsp_plugin():
    """Real LSP manager + plugin; tears down after each test."""
    from skill_sdk.tool.lsp_plugin import LspPlugin, reset_manager

    reset_manager()
    os.environ.setdefault("SKILL_SDK_LSP_INDEX_WAIT_MS", "8000")
    plugin = LspPlugin()
    yield plugin
    reset_manager()


def _apply_code_agent_lsp_env(repo_root: str) -> None:
    """Use code-agent startup path: WORKSPACE_FOLDER + SKILL_SDK_LSP_SERVERS."""
    from skill_sdk.tool.lsp_plugin import reset_manager

    reset_manager()
    os.environ.pop("WORKSPACE_FOLDER", None)
    os.environ.pop("SKILL_SDK_LSP_SERVERS", None)
    configure_skill_runtime_env({"repo": repo_root})
    resolved = str(Path(repo_root).resolve())
    assert os.environ.get("WORKSPACE_FOLDER") == resolved
    cfg_raw = os.environ.get("SKILL_SDK_LSP_SERVERS", "")
    assert cfg_raw.strip(), "SKILL_SDK_LSP_SERVERS not set"
    cfg = json.loads(cfg_raw)
    for _name, entry in cfg.items():
        assert entry.get("workspaceFolder") == resolved


@pytest.fixture
def helloworld_monorepo() -> str:
    """Single clone root with java/ and python/ submodules (user scenario)."""
    tmp = tempfile.mkdtemp(prefix="helloworld-it-")
    try:
        root = Path(tmp) / "helloworld"
        root.mkdir()
        java_dir = root / "java"
        py_dir = root / "python"
        java_dir.mkdir()
        py_dir.mkdir()
        (java_dir / "App.java").write_text(
            "public class App {\n"
            "    public static void greet() { System.out.println(\"hi\"); }\n"
            "    public static void main(String[] args) { greet(); }\n"
            "}\n",
            encoding="utf-8",
        )
        (py_dir / "core.py").write_text(
            "class RequestHandler:\n"
            "    def handle(self, msg: str) -> str:\n"
            "        return msg\n\n"
            "def run() -> None:\n"
            "    RequestHandler().handle('ok')\n",
            encoding="utf-8",
        )
        yield str(root.resolve())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class TestCodeAgentLspEnv:
    def test_monorepo_env_selects_java_and_python_lsp_same_root(self, helloworld_monorepo):
        from skill_sdk.tool.lsp_plugin import reset_manager

        reset_manager()
        os.environ.pop("WORKSPACE_FOLDER", None)
        os.environ.pop("SKILL_SDK_LSP_SERVERS", None)
        configure_skill_runtime_env({"repo": helloworld_monorepo})
        selected = select_lsp_servers_with_workspaces([helloworld_monorepo])
        names = {e.name for e in selected}
        assert "basedpyright" in names
        if HAS_JDTLS:
            assert "jdtls" in names
        for entry in selected:
            assert entry.workspace_folder == helloworld_monorepo

        payload = json.loads(os.environ["SKILL_SDK_LSP_SERVERS"])
        for entry in payload.values():
            assert entry["workspaceFolder"] == helloworld_monorepo


@pytest.mark.skipif(not HAS_BASEDPYRIGHT, reason="basedpyright-langserver not on PATH")
class TestGoToDefinitionPython:
    def test_monorepo_python_definition(self, lsp_plugin, helloworld_monorepo):
        _apply_code_agent_lsp_env(helloworld_monorepo)
        py_file = Path(helloworld_monorepo) / "python" / "core.py"
        line, char = _find_symbol(py_file, "RequestHandler", line_hint="class RequestHandler")
        out = lsp_plugin.execute(
            operation="goToDefinition",
            file_path=str(py_file),
            line=line,
            character=char,
        )
        _assert_definition_ok(_parse_lsp_output(out), expect_file_fragment="core.py")

    @pytest.mark.skipif(not HAS_FIXTURES, reason="skill_sdk py fixture missing")
    def test_skill_sdk_py_fixture_definition(self, lsp_plugin):
        repo_root = str(_PY_FIXTURE.resolve())
        _apply_code_agent_lsp_env(repo_root)
        core = _PY_FIXTURE / "core.py"
        line, char = _find_symbol(core, "AdvancedProcessor", line_hint="class AdvancedProcessor")
        out = lsp_plugin.execute(
            operation="goToDefinition",
            file_path=str(core),
            line=line,
            character=char,
        )
        _assert_definition_ok(_parse_lsp_output(out), expect_file_fragment="core.py")


@pytest.mark.skipif(not HAS_JDTLS, reason="jdtls not on PATH")
class TestGoToDefinitionJava:
    def test_monorepo_java_definition(self, lsp_plugin, helloworld_monorepo):
        _apply_code_agent_lsp_env(helloworld_monorepo)
        java_file = Path(helloworld_monorepo) / "java" / "App.java"
        line, char = _find_symbol(java_file, "greet", line_hint="greet();")
        out = lsp_plugin.execute(
            operation="goToDefinition",
            file_path=str(java_file),
            line=line,
            character=char,
        )
        _assert_definition_ok(_parse_lsp_output(out), expect_file_fragment="App.java")


@pytest.mark.skipif(not HAS_GOPLS, reason="gopls not on PATH")
@pytest.mark.skipif(not HAS_FIXTURES, reason="skill_sdk go fixture missing")
class TestGoToDefinitionGo:
    def test_skill_sdk_go_fixture_definition(self, lsp_plugin):
        repo_root = str(_GO_FIXTURE.resolve())
        _apply_code_agent_lsp_env(repo_root)
        main_go = _GO_FIXTURE / "main.go"
        line, char = _find_symbol(main_go, "TransformData")
        out = lsp_plugin.execute(
            operation="goToDefinition",
            file_path=str(main_go),
            line=line,
            character=char,
        )
        _assert_definition_ok(_parse_lsp_output(out), expect_file_fragment="main.go")

    def test_go_cross_file_definition(self, lsp_plugin):
        repo_root = str(_GO_FIXTURE.resolve())
        _apply_code_agent_lsp_env(repo_root)
        handler = _GO_FIXTURE / "handler.go"
        line, char = _find_symbol(handler, "HandleRequest", line_hint="helper.HandleRequest")
        out = lsp_plugin.execute(
            operation="goToDefinition",
            file_path=str(handler),
            line=line,
            character=char,
        )
        result = _parse_lsp_output(out)
        _assert_definition_ok(result, expect_file_fragment="main.go")
