"""Tests for repo-aware LSP server selection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.lsp_repo_detect import select_lsp_servers_for_repos, select_lsp_servers_with_workspaces
from agent.skill_runner_service import build_skill_sdk_lsp_servers_json


def _fake_which(all_bins: set[str]):
    def which(cmd: str) -> str | None:
        return f"/usr/bin/{cmd}" if cmd in all_bins else None

    return which


def test_python_repo_selects_basedpyright_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
        selected = select_lsp_servers_for_repos(
            [str(root)],
            which_command=_fake_which({"basedpyright-langserver", "gopls"}),
        )
        assert list(selected.keys()) == ["basedpyright"]


def test_go_repo_selects_gopls_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.go").write_text("package main\n", encoding="utf-8")
        (root / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n", encoding="utf-8")
        selected = select_lsp_servers_for_repos(
            [str(root)],
            which_command=_fake_which({"basedpyright-langserver", "gopls"}),
        )
        assert list(selected.keys()) == ["gopls"]


def test_go_mod_without_go_files_still_selects_gopls():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n", encoding="utf-8")
        selected = select_lsp_servers_for_repos(
            [str(root)],
            which_command=_fake_which({"gopls"}),
        )
        assert "gopls" in selected


def test_empty_repo_selects_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        selected = select_lsp_servers_for_repos(
            [tmp],
            which_command=_fake_which({"gopls", "basedpyright-langserver"}),
        )
        assert selected == {}


def test_code_agent_repo_selects_python_lsp():
    root = Path(__file__).resolve().parents[1]
    which = _fake_which({"basedpyright-langserver", "gopls", "clangd", "vtsls"})
    selected = select_lsp_servers_with_workspaces([str(root)], which_command=which)
    assert "basedpyright" in {e.name for e in selected}
    assert "gopls" not in {e.name for e in selected}
    entry = next(e for e in selected if e.name == "basedpyright")
    assert Path(entry.workspace_folder).resolve() == root.resolve()


def test_monorepo_java_python_modules_share_repo_root():
    """helloworld with java/ and python/ submodules → both LSP, same clone root."""
    with tempfile.TemporaryDirectory() as tmp:
        helloworld = Path(tmp) / "helloworld"
        helloworld.mkdir()
        (helloworld / "java").mkdir()
        (helloworld / "python").mkdir()
        (helloworld / "java" / "App.java").write_text("class App {}\n", encoding="utf-8")
        (helloworld / "python" / "main.py").write_text("print(1)\n", encoding="utf-8")
        repo_root = str(helloworld.resolve())

        which = _fake_which({"basedpyright-langserver", "jdtls"})
        selected = select_lsp_servers_with_workspaces([repo_root], which_command=which)
        assert {e.name for e in selected} == {"basedpyright", "jdtls"}
        assert {e.workspace_folder for e in selected} == {repo_root}

        payload = json.loads(
            build_skill_sdk_lsp_servers_json([repo_root], repo_root=repo_root)
        )
        assert set(payload.keys()) == {"basedpyright", "jdtls"}
        assert payload["basedpyright"]["workspaceFolder"] == repo_root
        assert payload["jdtls"]["workspaceFolder"] == repo_root
