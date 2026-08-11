from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

import yaml
from pydantic import BaseModel, Field

from skill_sdk.api.base import Skill, SkillScript


class SkillMarkdownData(BaseModel):
    """Parsed ``SKILL.md``: fixed YAML frontmatter, remainder is ``detail``."""

    name: str = Field(..., description="From frontmatter ``name``")
    description: str = Field(..., description="From frontmatter ``description``")
    detail: str = Field(..., description="Markdown body after the closing ``---``")


class SkillLoader:
    """
    Skill pack workflow (published layout):

    1. :meth:`extract_zip` — unpack archive to a folder.
    2. :meth:`read_meta_json` — read ``_meta.json`` (``slug``, ``version``, …).
    3. :meth:`read_skill_md` — read ``SKILL.md`` (fixed frontmatter + body as ``detail``).
    4. :meth:`build_skill` — merge (2) and (3) into a :class:`~skill_sdk.api.base.Skill`.

    Bundled scripts are listed from ``<skill_dir>/scripts/`` (same directory as ``SKILL.md``)
    via :meth:`discover_scripts`.

    Use :meth:`load` for a single archive, or :meth:`from_dir_load_skills` to load every
    ``*.zip`` under a directory into a list of :class:`~skill_sdk.api.base.Skill`.
    """

    def __init__(self) -> None:
        self._temp_dirs: list[Path] = []

    def close(self) -> None:
        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._temp_dirs.clear()

    def __enter__(self) -> SkillLoader:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _norm_zip_name(name: str) -> str:
        return name.replace("\\", "/")

    @staticmethod
    def _find_skill_root(extract_root: Path) -> Path:
        """Directory that directly contains ``_meta.json`` (extract root or one subfolder)."""
        root = Path(extract_root).resolve()
        if (root / "_meta.json").is_file():
            return root
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "_meta.json").is_file():
                return child.resolve()
        raise FileNotFoundError(
            f"No _meta.json under {root} (expected at root or in a single subdirectory)"
        )

    @staticmethod
    def _parse_skill_md_frontmatter(content: str) -> SkillMarkdownData:
        """
        Fixed format: file starts with ``---``, YAML block, closing ``---`` line;
        everything after that belongs to ``detail``.
        """
        if not content.startswith("---"):
            raise ValueError("SKILL.md must begin with '---' (YAML frontmatter)")

        lines = content.splitlines(keepends=True)
        i = 1
        fm_buf: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.strip() == "---":
                break
            fm_buf.append(line)
            i += 1
        else:
            raise ValueError("SKILL.md frontmatter is not closed with a '---' line")

        fm_text = "".join(fm_buf)
        data = yaml.safe_load(fm_text) or {}
        if not isinstance(data, dict):
            raise ValueError("SKILL.md frontmatter must parse to a mapping")
        if "name" not in data:
            raise KeyError("SKILL.md frontmatter missing required field 'name'")
        if "description" not in data:
            raise KeyError("SKILL.md frontmatter missing required field 'description'")

        detail = "".join(lines[i + 1 :])
        return SkillMarkdownData(
            name=str(data["name"]),
            description=str(data["description"]),
            detail=detail.lstrip("\n"),
        )

    @staticmethod
    def _scripts_folder(skill_dir: Path) -> Path:
        """``scripts`` directory next to ``SKILL.md`` (under the skill root)."""
        return Path(skill_dir) / "scripts"

    _EXT_INTERPRETERS: dict[str, str] = {
        ".py": "python3",
        ".py3": "python3",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "zsh",
        ".js": "node",
        ".mjs": "node",
        ".cjs": "node",
        ".rb": "ruby",
        ".pl": "perl",
        ".php": "php",
        ".ts": "ts-node",
    }

    @staticmethod
    def _detect_interpreter(path: Path) -> str:
        """Pick a recommended interpreter by suffix first, then shebang."""
        suffix = path.suffix.lower()
        if suffix in SkillLoader._EXT_INTERPRETERS:
            return SkillLoader._EXT_INTERPRETERS[suffix]

        try:
            with open(path, "rb") as fh:
                first = fh.readline(512)
        except OSError:
            return ""

        if not first.startswith(b"#!"):
            return ""
        shebang = first[2:].decode("utf-8", errors="ignore").strip()
        if not shebang:
            return ""
        parts = shebang.split()
        executable = Path(parts[0]).name
        if executable == "env" and len(parts) >= 2:
            return parts[1]
        return executable

    @staticmethod
    def discover_scripts(skill_dir: str | Path) -> list[SkillScript]:
        """
        List regular files under ``<skill_dir>/scripts/`` recursively, sorted by
        relative path.

        ``script_name`` is the path **relative to** ``scripts/`` (e.g. ``activator.sh``
        or ``nested/deep.sh``), so nested helpers are distinguishable.
        ``script_path`` is the absolute path on disk.
        ``interpreter`` is inferred from the file suffix, falling back to the
        shebang line.

        Hidden files / directories (leading ``.``) are skipped at every level.
        """
        folder = SkillLoader._scripts_folder(skill_dir)
        if not folder.is_dir():
            return []

        def _iter_files(root: Path):
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel_parts = path.relative_to(root).parts
                if any(part.startswith(".") for part in rel_parts):
                    continue
                yield path

        out: list[SkillScript] = []
        for path in sorted(
            _iter_files(folder),
            key=lambda p: str(p.relative_to(folder)).lower(),
        ):
            rel_name = str(path.relative_to(folder))
            out.append(
                SkillScript(
                    script_name=rel_name,
                    script_path=str(path.resolve()),
                    interpreter=SkillLoader._detect_interpreter(path),
                )
            )
        return out

    _SKILL_ROOT_RESERVED: frozenset[str] = frozenset({"scripts", "__pycache__"})

    @staticmethod
    def discover_resource_dirs(skill_dir: str | Path) -> list[str]:
        """List non-empty, non-reserved top-level sub-directories alongside ``scripts/``.

        Returns just the relative directory names (e.g. ``["assets", "hooks",
        "references"]``), sorted alphabetically. Useful for advertising bundled
        docs / configs to a runtime without hard-coding conventions.
        """
        root = Path(skill_dir)
        if not root.is_dir():
            return []
        names: list[str] = []
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in SkillLoader._SKILL_ROOT_RESERVED:
                continue
            if not any(child.rglob("*")):
                continue
            names.append(child.name)
        return names

    @staticmethod
    def extract_zip(
        zip_source: str | Path | BinaryIO,
        dest_folder: str | Path,
    ) -> Path:
        """
        Extract the entire zip into ``dest_folder`` (paths normalized; rejects ``..``).

        ``zip_source`` may be a path or a binary stream readable by :class:`zipfile.ZipFile`.
        """
        dest = Path(dest_folder).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_source, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = SkillLoader._norm_zip_name(info.filename)
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError(f"Unsafe zip entry: {info.filename!r}")
                target = (dest / name).resolve()
                if dest not in target.parents and target != dest:
                    raise ValueError(f"Zip entry escapes extract dir: {info.filename!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        return dest

    @staticmethod
    def read_meta_json(skill_dir: str | Path) -> dict[str, Any]:
        """Load and parse ``<skill_dir>/_meta.json``."""
        path = Path(skill_dir) / "_meta.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing _meta.json: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("_meta.json must contain a JSON object")
        return data

    @staticmethod
    def read_skill_md(skill_dir: str | Path) -> SkillMarkdownData:
        """Read ``<skill_dir>/SKILL.md`` and split fixed frontmatter vs ``detail`` body."""
        path = Path(skill_dir) / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"Missing SKILL.md: {path}")
        return SkillLoader._parse_skill_md_frontmatter(path.read_text(encoding="utf-8"))

    @staticmethod
    def build_skill(
        meta: dict[str, Any],
        md: SkillMarkdownData,
        *,
        scripts: list[SkillScript] | None = None,
        base_dir: str | Path | None = None,
        resource_dirs: list[str] | None = None,
    ) -> Skill:
        """
        Combine ``_meta.json`` and parsed ``SKILL.md``.

        ``version`` comes from ``meta``; ``name`` / ``description`` / ``detail`` from ``md``.
        Optional ``scripts`` default to empty; pass the result of :meth:`discover_scripts`
        when building a skill manually. ``base_dir`` should point at the extracted
        skill root so callers (e.g. a ReAct runner) can resolve relative asset
        paths referenced from ``SKILL.md``. ``resource_dirs`` lists sibling
        directories next to ``scripts/`` (see :meth:`discover_resource_dirs`).
        """
        if "version" not in meta:
            raise KeyError("_meta.json missing required field 'version'")

        return Skill(
            name=md.name,
            description=md.description,
            detail=md.detail,
            version=str(meta["version"]),
            scripts=list(scripts) if scripts is not None else [],
            base_dir=str(Path(base_dir).resolve()) if base_dir else "",
            resource_dirs=list(resource_dirs) if resource_dirs is not None else [],
            allowed_tools=SkillLoader._parse_allowed_tools(meta),
        )

    @staticmethod
    def _parse_allowed_tools(meta: dict[str, Any]) -> list[str]:
        """Parse ``allowed_tools`` from ``_meta.json``.

        Missing / null / empty → ``[]`` (unrestricted).
        Accepts a JSON list of strings, or a single whitespace/comma-separated string.
        """
        raw = meta.get("allowed_tools")
        if raw is None:
            return []
        if isinstance(raw, str):
            parts = [
                p.strip()
                for p in raw.replace(",", " ").split()
                if p.strip()
            ]
            return parts
        if isinstance(raw, list):
            out: list[str] = []
            seen: set[str] = set()
            for item in raw:
                name = str(item or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(name)
            return out
        raise ValueError(
            "allowed_tools must be a list of strings or a string, "
            f"got {type(raw).__name__}"
        )

    def load(
        self,
        zip_source: str | Path | BinaryIO,
        *,
        extract_to: Path | None = None,
    ) -> Skill:
        """
        Extract zip, locate skill root (``_meta.json``), then run steps 2–4.

        If ``extract_to`` is omitted, uses a temporary directory tracked until :meth:`close`.
        """
        if extract_to is None:
            extract_to = Path(tempfile.mkdtemp(prefix="skill_sdk_"))
            self._temp_dirs.append(extract_to)
        else:
            extract_to = Path(extract_to)
            extract_to.mkdir(parents=True, exist_ok=True)

        self.extract_zip(zip_source, extract_to)

        skill_root = SkillLoader._find_skill_root(extract_to)
        meta = self.read_meta_json(skill_root)
        md = self.read_skill_md(skill_root)

        scripts = SkillLoader.discover_scripts(skill_root)
        resource_dirs = SkillLoader.discover_resource_dirs(skill_root)
        return self.build_skill(
            meta,
            md,
            scripts=scripts,
            base_dir=skill_root,
            resource_dirs=resource_dirs,
        )

    def from_dir_load_skills(self, skills_dir: str | Path) -> list[Skill]:
        """
        Load every ``*.zip`` file under ``skills_dir`` into a ``list`` of :class:`~skill_sdk.api.base.Skill`.

        Archives are processed in sorted order (case-insensitive by filename). Each zip
        uses :meth:`load` with its own temporary extract directory; call :meth:`close`
        when done to remove those directories.
        """
        d = Path(skills_dir).resolve()
        if not d.is_dir():
            raise NotADirectoryError(f"Not a directory: {d}")
        zips = sorted(
            (p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".zip"),
            key=lambda p: p.name.lower(),
        )
        return [self.load(p) for p in zips]
