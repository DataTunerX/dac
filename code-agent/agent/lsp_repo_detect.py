"""Detect which LSP servers to start based on cloned repository contents.

Binary availability comes from the code-agent Docker image (``Dockerfile-amd64`` /
``Dockerfile-arm64``). That image pre-installs exactly these language servers:

- ``gopls``              — ``go install …/gopls`` → ``/usr/local/bin/gopls``
- ``basedpyright``       — ``npm install -g basedpyright`` → ``basedpyright-langserver``
- ``vtsls``              — ``npm install -g @vtsls/language-server`` → ``vtsls``
- ``jdtls``              — Eclipse JDT LS under ``/opt/jdtls`` → ``/usr/local/bin/jdtls``
- ``rust-analyzer``      — rustup component → ``/usr/local/bin/rust-analyzer``
- ``clangd``             — apt ``clangd``

Runtime policy: **scan cloned repos** → enable only servers whose languages/markers
appear in the tree → verify the corresponding binary is on ``PATH`` (always true in
the image; keeps local dev honest when a language is detected but the binary is missing).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Sequence, Set

logger = logging.getLogger(__name__)

# Directories skipped when scanning source files.
_SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "dist",
    "build",
    "target",
    ".idea",
    ".cursor",
    ".gradle",
    ".mvn",
    "third_party",
    "third-party",
})

try:
    _LSP_DETECT_MAX_FILES = int(os.getenv("LSP_DETECT_MAX_FILES", "100000"))
except ValueError:
    _LSP_DETECT_MAX_FILES = 100000


@dataclass(frozen=True)
class LspServerTemplate:
    command: str
    args: tuple[str, ...] = ()
    extension_to_language: dict[str, str] | None = None
    startup_timeout_ms: int = 120_000
    marker_files: tuple[str, ...] = ()


# 1:1 with LSP binaries installed in Dockerfile-amd64 / Dockerfile-arm64 (final stage).
LSP_SERVER_TEMPLATES: dict[str, LspServerTemplate] = {
    "gopls": LspServerTemplate(
        command="gopls",
        args=("serve",),
        extension_to_language={".go": "go"},
        marker_files=("go.mod", "go.work"),
    ),
    "basedpyright": LspServerTemplate(
        command="basedpyright-langserver",
        args=("--stdio",),
        extension_to_language={".py": "python", ".pyi": "python"},
    ),
    "clangd": LspServerTemplate(
        command="clangd",
        extension_to_language={
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
        },
    ),
    "rust-analyzer": LspServerTemplate(
        command="rust-analyzer",
        extension_to_language={".rs": "rust"},
        marker_files=("Cargo.toml", "Cargo.lock"),
    ),
    "jdtls": LspServerTemplate(
        command="jdtls",
        extension_to_language={".java": "java"},
        marker_files=("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"),
    ),
    "vtsls": LspServerTemplate(
        command="vtsls",
        args=("--stdio",),
        extension_to_language={
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".mjs": "javascript",
            ".cjs": "javascript",
        },
        marker_files=("package.json", "tsconfig.json", "jsconfig.json"),
    ),
}


def _normalize_roots(workspace_roots: Sequence[str]) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in workspace_roots:
        if not raw:
            continue
        path = Path(raw).resolve()
        key = str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        roots.append(path)
    return roots


def scan_repo_extensions_by_root(
    workspace_roots: Sequence[str],
    *,
    max_files: int = _LSP_DETECT_MAX_FILES,
) -> dict[str, Set[str]]:
    """Map each repo root → file extensions found under it."""
    by_root: dict[str, Set[str]] = {}
    files_seen = 0

    for root in _normalize_roots(workspace_roots):
        key = str(root)
        exts: Set[str] = set()
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for name in filenames:
                files_seen += 1
                if files_seen > max_files:
                    logger.warning(
                        "[LspDetect] hit LSP_DETECT_MAX_FILES=%d — stopping scan early",
                        max_files,
                    )
                    return by_root
                suffix = Path(name).suffix.lower()
                if suffix:
                    exts.add(suffix)
        by_root[key] = exts
    return by_root


def scan_repo_extensions(
    workspace_roots: Sequence[str],
    *,
    max_files: int = _LSP_DETECT_MAX_FILES,
) -> Set[str]:
    """Collect lowercase file extensions across all ``workspace_roots``."""
    merged: Set[str] = set()
    for exts in scan_repo_extensions_by_root(
        workspace_roots, max_files=max_files
    ).values():
        merged |= exts
    return merged


def scan_repo_markers_by_root(workspace_roots: Sequence[str]) -> dict[str, Set[str]]:
    """Map each repo root → marker filenames at root or one level down."""
    by_root: dict[str, Set[str]] = {}
    for root in _normalize_roots(workspace_roots):
        found: Set[str] = set()
        for entry in root.iterdir():
            if entry.is_file():
                found.add(entry.name)
        for sub in root.iterdir():
            if not sub.is_dir() or sub.name in _SKIP_DIR_NAMES:
                continue
            for entry in sub.iterdir():
                if entry.is_file():
                    found.add(entry.name)
        by_root[str(root)] = found
    return by_root


def scan_repo_markers(workspace_roots: Sequence[str]) -> Set[str]:
    """Return marker filenames found under any repo root."""
    merged: Set[str] = set()
    for markers in scan_repo_markers_by_root(workspace_roots).values():
        merged |= markers
    return merged


def _server_needed_for_repo(
    template: LspServerTemplate,
    *,
    repo_extensions: Set[str],
    repo_markers: Set[str],
) -> bool:
    exts = set(template.extension_to_language or {})
    if exts & repo_extensions:
        return True
    if template.marker_files and repo_markers.intersection(template.marker_files):
        return True
    return False


def _server_needed(
    name: str,
    template: LspServerTemplate,
    *,
    repo_extensions: Set[str],
    repo_markers: Set[str],
) -> bool:
    return _server_needed_for_repo(
        template, repo_extensions=repo_extensions, repo_markers=repo_markers
    )


@dataclass(frozen=True)
class SelectedLspServer:
    """An LSP server chosen because the repo contains matching source files."""

    name: str
    template: LspServerTemplate
    workspace_folder: str


def detect_lsp_servers_from_repo_code(
    workspace_roots: Sequence[str],
) -> list[SelectedLspServer]:
    """Select LSP servers **only** from cloned repository languages/markers."""
    roots = _normalize_roots(workspace_roots)
    if not roots:
        return []

    ext_by_root = scan_repo_extensions_by_root(roots)
    marker_by_root = scan_repo_markers_by_root(roots)
    all_extensions = set().union(*ext_by_root.values()) if ext_by_root else set()
    all_markers = set().union(*marker_by_root.values()) if marker_by_root else set()

    logger.info(
        "[LspDetect] scanned %d repo(s); extensions=%s markers=%s",
        len(roots),
        sorted(all_extensions)[:24],
        sorted(all_markers)[:12],
    )

    selected: list[SelectedLspServer] = []
    for name, template in LSP_SERVER_TEMPLATES.items():
        if not _server_needed(
            name, template, repo_extensions=all_extensions, repo_markers=all_markers
        ):
            continue
        workspace_folder = _clone_root_for_server(
            roots, template, ext_by_root, marker_by_root
        )
        selected.append(
            SelectedLspServer(
                name=name,
                template=template,
                workspace_folder=workspace_folder,
            )
        )

    logger.info(
        "[LspDetect] repo languages require LSP: %s",
        ", ".join(s.name for s in selected) if selected else "(none)",
    )
    return selected


def _clone_root_for_server(
    roots: list[Path],
    template: LspServerTemplate,
    ext_by_root: dict[str, Set[str]],
    marker_by_root: dict[str, Set[str]],
) -> str:
    """Return the cloned **repository root** for this LSP (never a submodule subdir).

    Example: ``helloworld/`` with ``java/`` and ``python/`` modules — both jdtls and
    basedpyright get ``…/helloworld``, not ``…/helloworld/java`` or ``…/python``.
    Language detection walks the full tree; workspace is always the clone root.
    """
    for root in roots:
        key = str(root.resolve())
        if _server_needed_for_repo(
            template,
            repo_extensions=ext_by_root.get(key, set()),
            repo_markers=marker_by_root.get(key, set()),
        ):
            return key
    return str(roots[0].resolve())


def select_lsp_servers_for_repos(
    workspace_roots: Sequence[str],
    *,
    which_command: Callable[[str], str | None] | None = None,
) -> Dict[str, LspServerTemplate]:
    """Return LSP templates to configure — decided by repo code, filtered by PATH."""
    import shutil

    which = which_command or shutil.which
    picked: Dict[str, LspServerTemplate] = {}

    for entry in detect_lsp_servers_from_repo_code(workspace_roots):
        if not which(entry.template.command):
            logger.warning(
                "[LspDetect] repo requires %s but %r not on PATH "
                "(install via code-agent Docker image)",
                entry.name,
                entry.template.command,
            )
            continue
        picked[entry.name] = entry.template

    logger.info(
        "[LspDetect] will start LSP servers: %s",
        ", ".join(picked.keys()) if picked else "(none)",
    )
    return picked


def select_lsp_servers_with_workspaces(
    workspace_roots: Sequence[str],
    *,
    which_command: Callable[[str], str | None] | None = None,
) -> list[SelectedLspServer]:
    """Like :func:`detect_lsp_servers_from_repo_code` but drops servers missing on PATH."""
    import shutil

    which = which_command or shutil.which
    out: list[SelectedLspServer] = []
    for entry in detect_lsp_servers_from_repo_code(workspace_roots):
        if which(entry.template.command):
            out.append(entry)
        else:
            logger.warning(
                "[LspDetect] repo requires %s but %r not on PATH",
                entry.name,
                entry.template.command,
            )
    return out
