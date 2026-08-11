"""Skill index — scans namespace directories and keeps an in-memory index.

The index is keyed by ``(namespace, name)`` and maps to a list of versions,
newest first. ``default`` is the built-in namespace whose files live either
directly under ``SKILLS_DIR`` (legacy images) or under ``SKILLS_DIR/default/``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skill_sdk.api.base import Skill
from skill_sdk.skill.loader import SkillLoader

from .models import DEFAULT_NAMESPACE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SkillVersion:
    """One concrete version + namespace of a skill on disk."""

    namespace: str
    version: str
    path: Path
    description: str


def version_key(raw: str) -> tuple[int, Any]:
    """Return a comparison key for a version string.

    Tries :class:`packaging.version.Version` (PEP 440) first so ``1.10``
    beats ``1.9`` properly, and falls back to a lexicographic tuple when
    the version is not parseable (e.g. git shas). Parseable versions
    always rank **above** unparseable ones.
    """
    try:
        from packaging.version import Version

        return (1, Version(raw))
    except Exception:  # noqa: BLE001
        return (0, raw)


class SkillIndex:
    """Loads skill ``*.zip`` packs from namespace directories and keeps an index.

    For every ``*.zip`` found, the loader resolves the skill's declared ``name``
    (from ``SKILL.md`` frontmatter) and ``version`` (from ``_meta.json``). Skills
    are grouped by ``(namespace, name)``; multiple versions of the same name are
    kept, newest first.
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).resolve()
        self._loader = SkillLoader()
        self._lock = threading.Lock()
        # (namespace, name) -> list[_SkillVersion] (newest first)
        self._ns_versions: dict[tuple[str, str], list[_SkillVersion]] = {}

    def _iter_namespace_zips(self):
        """Yield ``(namespace, zip_path)`` for every zip under ``skills_dir``.

        Layout:
        - ``skills_dir/default/`` holds the built-in ``default`` namespace.
        - Each other immediate sub-directory is a namespace of the same name.
        - ``*.zip`` files placed directly under ``skills_dir`` (legacy layout)
          are also treated as ``default`` for backward compatibility.
        """
        if not self.skills_dir.is_dir():
            return

        # default namespace: contents of skills_dir/default/ plus any legacy
        # *.zip sitting directly under skills_dir.
        default_dir = self.skills_dir / DEFAULT_NAMESPACE
        if default_dir.is_dir():
            for p in sorted(
                (
                    p
                    for p in default_dir.iterdir()
                    if p.is_file() and p.suffix.lower() == ".zip"
                ),
                key=lambda p: p.name.lower(),
            ):
                yield DEFAULT_NAMESPACE, p

        # Legacy: *.zip directly under skills_dir -> default namespace.
        for p in sorted(
            (
                p
                for p in self.skills_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".zip"
            ),
            key=lambda p: p.name.lower(),
        ):
            yield DEFAULT_NAMESPACE, p

        # Other namespace sub-directories.
        for child in sorted(
            (p for p in self.skills_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name.lower(),
        ):
            if child.name == DEFAULT_NAMESPACE:
                continue
            ns = child.name
            for p in sorted(
                (
                    p
                    for p in child.iterdir()
                    if p.is_file() and p.suffix.lower() == ".zip"
                ),
                key=lambda p: p.name.lower(),
            ):
                yield ns, p

    def reload(self) -> int:
        """Scan ``skills_dir`` and rebuild the ``(namespace, name) -> versions`` map.

        Returns the number of distinct ``(namespace, name)`` entries indexed.
        """
        with self._lock:
            if not self.skills_dir.is_dir():
                logger.warning(
                    "[SkillHub] skills_dir=%s does not exist (yet) — index is empty",
                    self.skills_dir,
                )
                self._ns_versions = {}
                return 0

            versions: dict[tuple[str, str], list[_SkillVersion]] = {}
            seen_keys: dict[tuple[str, str], Path] = {}
            for namespace, zip_path in self._iter_namespace_zips():
                try:
                    skill: Skill = self._loader.load(zip_path)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[SkillHub] failed to load skill zip %s — skipping",
                        zip_path,
                    )
                    continue

                name = (skill.name or "").strip()
                version = (skill.version or "").strip()
                if not name:
                    logger.warning(
                        "[SkillHub] skill from %s has empty name — skipping",
                        zip_path.name,
                    )
                    continue
                if not version:
                    logger.warning(
                        "[SkillHub] skill %s from %s has empty version — skipping",
                        name,
                        zip_path.name,
                    )
                    continue

                key = (namespace, name, version)
                if key in seen_keys:
                    logger.warning(
                        "[SkillHub] duplicate skill ns=%s name=%s version=%s "
                        "(first=%s, duplicate=%s) — keeping the first occurrence",
                        namespace,
                        name,
                        version,
                        seen_keys[key].name,
                        zip_path.name,
                    )
                    continue
                seen_keys[key] = zip_path

                versions.setdefault((namespace, name), []).append(
                    _SkillVersion(
                        namespace=namespace,
                        version=version,
                        path=zip_path,
                        description=skill.description or "",
                    )
                )

            # Sort each (namespace, name) group's versions newest-first so callers
            # can trust ``versions[key][0]`` to be the latest.
            for key, vs in versions.items():
                vs.sort(key=lambda v: version_key(v.version), reverse=True)

            self._ns_versions = versions
            total_versions = sum(len(v) for v in versions.values())
            logger.info(
                "[SkillHub] indexed %d skill(s) / %d version(s) from %s: %s",
                len(versions),
                total_versions,
                self.skills_dir,
                ", ".join(
                    f"{ns}/{n}@{vs[0].version}(+{len(vs) - 1})"
                    if len(vs) > 1
                    else f"{ns}/{n}@{vs[0].version}"
                    for (ns, n), vs in sorted(versions.items())
                )
                or "(none)",
            )
            return len(versions)

    def snapshot(self) -> dict[tuple[str, str], frozenset[str]]:
        """Capture the index as ``(namespace, name) -> set(versions)``.

        Used by the auto-watcher to diff against the state after a reload and log
        exactly which skills were added / removed / changed.
        """
        with self._lock:
            return {
                key: frozenset(v.version for v in vs)
                for key, vs in self._ns_versions.items()
                if vs
            }

    def list_namespaces(self) -> list[str]:
        """Return sorted namespaces present on disk.

        Combines namespaces that currently hold indexed skills with any namespace
        directories present under ``SKILLS_DIR`` (including freshly created but
        still-empty ones). ``default`` is always included for predictability.
        """
        with self._lock:
            ns_set = {ns for ns, _ in self._ns_versions.keys()}
            # Include namespace directories that exist on disk even if they have
            # no indexed skill yet (e.g. just created via POST /namespaces/{ns}).
            if self.skills_dir.is_dir():
                for child in self.skills_dir.iterdir():
                    if child.is_dir():
                        ns_set.add(child.name)
            # Always surface the built-in default namespace even if empty (e.g.
            # before the default/ dir is provisioned), so the list is predictable.
            ns_set.add(DEFAULT_NAMESPACE)
            return sorted(ns_set)

    def namespace_exists(self, namespace: str) -> bool:
        """Whether ``namespace`` is known (built-in, on disk, or indexed).

        ``default`` always exists. Other namespaces exist when their directory
        is present under ``SKILLS_DIR`` and/or they hold indexed skills.
        """
        return namespace in self.list_namespaces()

    def list_skills(self, namespace: str) -> list[dict[str, Any]]:
        """Return skill summaries for a single namespace (newest version each).

        ``download_url`` is namespace-aware: the default namespace keeps the legacy
        ``/{name}.zip`` path, other namespaces use ``/namespaces/{ns}/{name}.zip``.
        """
        with self._lock:
            out: list[dict[str, Any]] = []
            for key in sorted(self._ns_versions.keys()):
                ns, name = key
                if ns != namespace:
                    continue
                vs = self._ns_versions[key]
                if not vs:
                    continue
                latest = vs[0]
                if ns == DEFAULT_NAMESPACE:
                    download_url = f"/{name}.zip"
                else:
                    download_url = f"/namespaces/{ns}/skills/{name}.zip"
                out.append(
                    {
                        "name": name,
                        "namespace": ns,
                        "description": latest.description,
                        "version": latest.version,
                        "filename": latest.path.name,
                        "download_url": download_url,
                        "available_versions": [v.version for v in vs],
                    }
                )
            return out

    def resolve_zip(
        self, namespace: str, name: str, version: str | None = None
    ) -> Path | None:
        """Return the on-disk zip for ``(namespace, name)``.

        If ``version`` is ``None``/empty the latest known version is returned.
        Otherwise it must match one of the indexed versions exactly.
        """
        with self._lock:
            vs = self._ns_versions.get((namespace, name))
            if not vs:
                return None
            if not version:
                return vs[0].path
            for v in vs:
                if v.version == version:
                    return v.path
            return None

    def resolved_version(
        self, namespace: str, name: str, version: str | None = None
    ) -> str | None:
        """Return the concrete version string that would be served.

        Useful for logging and for reporting the served version back to clients
        (as a response header) when they requested "latest".
        """
        with self._lock:
            vs = self._ns_versions.get((namespace, name))
            if not vs:
                return None
            if not version:
                return vs[0].version
            for v in vs:
                if v.version == version:
                    return v.version
            return None

    def namespace_dir(self, namespace: str) -> Path:
        """Resolve the on-disk directory for a namespace.

        Every namespace (including the built-in ``default``) is its own
        sub-directory ``skills_dir/<ns>``. The default namespace directory is
        ``skills_dir/default`` and is provisioned at build time (Dockerfile) or
        lazily on first upload.
        """
        return self.skills_dir / namespace

    def namespace_visibility(self, namespace: str) -> str:
        """Return the visibility of a namespace.

        Hook point for future private-namespace support: today every namespace is
        ``public``. When private namespaces are introduced, swap this lookup for
        a real store lookup and gate upload/list/download behind it.
        """
        return "public"

    def close(self) -> None:
        try:
            self._loader.close()
        except Exception:  # noqa: BLE001
            logger.exception("[SkillHub] SkillLoader.close() raised")
