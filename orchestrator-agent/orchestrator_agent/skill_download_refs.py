"""Skill reference parsing helpers for SKILLS env (incremental module).

Supports:
  - Legacy string list: '["weather","web_fetch"]' → default namespace, latest
  - Object list from skill DAC / SG skillPolicy:
    '[{"namespace":"team-a","name":"report","version":"1.0.0"}]'
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "default"


@dataclass(frozen=True)
class SkillRef:
    """A downloadable skill-hub package reference."""

    name: str
    namespace: str = DEFAULT_NAMESPACE
    version: str = ""

    def download_path(self) -> str:
        """Relative URL path (no leading hub base)."""
        filename = f"{self.name}.zip"
        # default + no version keeps legacy agent path used by biz-skill-agent
        if self.namespace == DEFAULT_NAMESPACE and not self.version:
            return f"/skills/{filename}"
        if self.namespace == DEFAULT_NAMESPACE:
            return f"/skills/{filename}?version={self.version}"
        if self.version:
            return f"/namespaces/{self.namespace}/skills/{filename}?version={self.version}"
        return f"/namespaces/{self.namespace}/skills/{filename}"


def sanitize_skill_name(name: str) -> Optional[str]:
    """Reject names that would escape the target directory."""
    name = name.strip()
    if not name:
        return None
    if name.endswith(".zip"):
        name = name[:-4]
    if "/" in name or "\\" in name or name in {".", ".."}:
        logger.warning("[SkillDownload] Skipping unsafe skill name: %r", name)
        return None
    return name


def _ref_from_item(item: Any) -> Optional[SkillRef]:
    if isinstance(item, dict):
        raw_name = str(item.get("name") or "").strip()
        name = sanitize_skill_name(raw_name)
        if not name:
            return None
        ns = str(item.get("namespace") or DEFAULT_NAMESPACE).strip() or DEFAULT_NAMESPACE
        version = str(item.get("version") or "").strip()
        return SkillRef(name=name, namespace=ns, version=version)
    # Legacy: plain string skill name → default namespace, latest
    name = sanitize_skill_name(str(item))
    if not name:
        return None
    return SkillRef(name=name, namespace=DEFAULT_NAMESPACE, version="")


def parse_skills_env(raw: Optional[str]) -> List[SkillRef]:
    """Parse SKILLS env into SkillRef list (object or legacy string formats)."""
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                refs: List[SkillRef] = []
                for item in parsed:
                    ref = _ref_from_item(item)
                    if ref:
                        refs.append(ref)
                logger.info(
                    "[SkillDownload] Parsed SKILLS JSON list: count=%d (object_or_string)",
                    len(refs),
                )
                return refs
        except json.JSONDecodeError:
            logger.warning(
                "[SkillDownload] SKILLS looked like JSON but failed to parse; "
                "falling back to delimiter split. raw=%r",
                raw,
            )

    refs = []
    for piece in re.split(r"[\s,;]+", raw):
        ref = _ref_from_item(piece)
        if ref:
            refs.append(ref)
    return refs


def dedupe_refs(refs: Sequence[SkillRef]) -> List[SkillRef]:
    """Dedupe by name (DAC constraint: name unique even across namespaces)."""
    seen: set[str] = set()
    out: List[SkillRef] = []
    for r in refs:
        if r.name in seen:
            logger.warning(
                "[SkillDownload] Duplicate skill name %r skipped (ns=%s version=%r)",
                r.name,
                r.namespace,
                r.version,
            )
            continue
        seen.add(r.name)
        out.append(r)
    return out
