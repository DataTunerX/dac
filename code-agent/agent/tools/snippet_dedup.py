"""Line-range deduplication for hybrid search code snippet merging."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_LINE_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")

_SOURCE_LABELS = {
    "semantic": "SEMANTIC",
    "metadata": "METADATA_GREP",
    "local_grep": "LOCAL_GREP",
    "skill_grep": "SKILL_GREP",
    "skill_read_code": "READ_CODE_SKILL",
}

_ACTION_LABELS = {
    "replace_with_complete_block": "替换为更完整代码块",
    "skip_subset": "跳过（已被更大块覆盖）",
    "skip_duplicate_key": "跳过（重复键）",
}


def _source_label(source: Optional[str]) -> str:
    if not source:
        return "UNKNOWN"
    return _SOURCE_LABELS.get(source, str(source).upper())


def snippet_brief(snippet: Dict[str, Any]) -> Dict[str, str]:
    """Compact snippet identity for merge/dedup logs."""
    segment_type = str(snippet.get("segment_type") or snippet.get("type") or "unknown")
    return {
        "source": _source_label(snippet.get("source")),
        "name": str(snippet.get("name") or "unknown"),
        "file": str(snippet.get("file_path") or "unknown"),
        "line_no": str(snippet.get("line_no") or ""),
        "segment_type": segment_type,
    }


def format_snippet_ref(snippet: Dict[str, Any]) -> str:
    """Human-readable one-line snippet reference."""
    return _format_brief_ref(snippet_brief(snippet))


def _format_brief_ref(brief: Dict[str, str]) -> str:
    line_part = brief.get("line_no") or "?"
    return (
        f"{brief.get('source', 'UNKNOWN')} {brief.get('name', 'unknown')} "
        f"({brief.get('segment_type', 'unknown')}) "
        f"{brief.get('file', 'unknown')}:{line_part}"
    )


def parse_line_range(line_no: Any) -> Optional[Tuple[int, int]]:
    """Parse ``line_no`` like ``341-349``, ``365`` into ``(start, end)``."""
    if line_no is None:
        return None
    text = str(line_no).strip()
    if not text:
        return None
    match = _LINE_RANGE_RE.match(text)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) is not None else start
    if start > end:
        start, end = end, start
    return start, end


def range_contains(outer: Tuple[int, int], inner: Tuple[int, int]) -> bool:
    return outer[0] <= inner[0] and outer[1] >= inner[1]


def ranges_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def ranges_equal(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] == b[0] and a[1] == b[1]


def _content_line_count(snippet: Dict[str, Any]) -> int:
    content = snippet.get("code_content") or ""
    if not content.strip():
        return 0
    return len(content.splitlines())


def _range_line_count(line_range: Tuple[int, int]) -> int:
    return line_range[1] - line_range[0] + 1


def _content_covers_declared_range(
    snippet: Dict[str, Any],
    line_range: Tuple[int, int],
) -> bool:
    content_lines = _content_line_count(snippet)
    if content_lines == 0:
        return True
    return content_lines >= _range_line_count(line_range)


def _outer_safely_covers_inner(
    outer: Dict[str, Any],
    inner: Dict[str, Any],
    outer_range: Tuple[int, int],
    inner_range: Tuple[int, int],
) -> bool:
    if not range_contains(outer_range, inner_range):
        return False
    if not _content_covers_declared_range(outer, outer_range):
        return False
    inner_lines = _content_line_count(inner)
    if inner_lines == 0:
        return True
    outer_lines = _content_line_count(outer)
    if outer_lines == 0:
        return False
    return outer_lines >= inner_lines


def _annotate_also_found_by(existing: Dict[str, Any], source: Optional[str]) -> None:
    if not source:
        return
    also = existing.setdefault("also_found_by", [])
    if source not in also:
        also.append(source)


def _merge_superseded_metadata(
    container: Dict[str, Any],
    removed: Dict[str, Any],
    *,
    merge_overlap_sources: bool,
) -> None:
    superseded = container.setdefault("supersedes", [])
    entry = {
        "name": removed.get("name"),
        "line_no": removed.get("line_no"),
        "source": removed.get("source"),
    }
    if entry not in superseded:
        superseded.append(entry)

    reason = removed.get("relevance_reason")
    if reason:
        reasons = container.setdefault("superseded_relevance", [])
        if reason not in reasons:
            reasons.append(reason)

    business = removed.get("business_meaning")
    if business:
        meanings = container.setdefault("superseded_business_meaning", [])
        if business not in meanings:
            meanings.append(business)

    if merge_overlap_sources:
        _annotate_also_found_by(container, removed.get("source"))


def find_covering_snippet(
    new_snippet: Dict[str, Any],
    existing_snippets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the existing snippet that fully covers ``new_snippet``, if any."""
    new_file = new_snippet.get("file_path")
    new_range = parse_line_range(new_snippet.get("line_no", ""))
    if not new_file or not new_range:
        return None

    for existing in existing_snippets:
        if existing.get("file_path") != new_file:
            continue
        existing_range = parse_line_range(existing.get("line_no", ""))
        if not existing_range:
            continue
        if ranges_equal(existing_range, new_range):
            return existing
        if range_contains(existing_range, new_range):
            if _outer_safely_covers_inner(existing, new_snippet, existing_range, new_range):
                return existing
    return None


def should_skip_grep_snippet(
    new_snippet: Dict[str, Any],
    existing_snippets: List[Dict[str, Any]],
    *,
    merge_overlap_sources: bool = False,
) -> bool:
    """Conservative skip: only when an existing block already fully covers the grep snippet."""
    covering = find_covering_snippet(new_snippet, existing_snippets)
    if covering is not None and merge_overlap_sources:
        _annotate_also_found_by(covering, new_snippet.get("source"))
    return covering is not None


def _find_snippets_safely_contained_by(
    outer: Dict[str, Any],
    outer_range: Tuple[int, int],
    file_path: str,
    merged: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    contained: List[Dict[str, Any]] = []
    for existing in merged:
        if existing.get("file_path") != file_path:
            continue
        existing_range = parse_line_range(existing.get("line_no", ""))
        if not existing_range:
            continue
        if _outer_safely_covers_inner(outer, existing, outer_range, existing_range):
            contained.append(existing)
    return contained


def is_merge_overlap_sources_enabled() -> bool:
    return os.getenv("HYBRID_MERGE_OVERLAP_SOURCES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def merge_hybrid_code_snippets(
    semantic_snippets: List[Dict[str, Any]],
    grep_snippets: List[Dict[str, Any]],
    *,
    merge_overlap_sources: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], int, int, int, int, Dict[str, Any]]:
    """Merge semantic and grep snippets with conservative, completeness-first dedup."""
    if merge_overlap_sources is None:
        merge_overlap_sources = is_merge_overlap_sources_enabled()

    dedup_report: Dict[str, Any] = {
        "input_semantic_count": len(semantic_snippets),
        "input_grep_count": len(grep_snippets),
        "events": [],
    }

    seen_keys: set[tuple[str, str, str]] = set()
    merged: List[Dict[str, Any]] = []

    for snippet in semantic_snippets:
        key = (snippet["file_path"], snippet.get("name", ""), snippet.get("line_no", ""))
        if key in seen_keys:
            dedup_report["events"].append(
                {
                    "action": "skip_duplicate_key",
                    "removed": snippet_brief(snippet),
                    "reason": "semantic 输入中存在重复键 (file, name, line_no)",
                }
            )
            continue
        seen_keys.add(key)
        snippet["source"] = "semantic"
        merged.append(snippet)

    grep_only_count = 0
    overlap_skipped_count = 0
    overlap_replaced_count = 0

    for snippet in grep_snippets:
        key = (snippet["file_path"], snippet.get("name", ""), snippet.get("line_no", ""))
        if key in seen_keys:
            overlap_skipped_count += 1
            dedup_report["events"].append(
                {
                    "action": "skip_duplicate_key",
                    "removed": snippet_brief(snippet),
                    "reason": "与已合并片段键完全相同 (file, name, line_no)",
                }
            )
            continue

        covering = find_covering_snippet(snippet, merged)
        if covering is not None:
            overlap_skipped_count += 1
            if merge_overlap_sources:
                _annotate_also_found_by(covering, snippet.get("source"))
            dedup_report["events"].append(
                {
                    "action": "skip_subset",
                    "removed": snippet_brief(snippet),
                    "kept": snippet_brief(covering),
                    "reason": (
                        f"已有片段 {_format_brief_ref(snippet_brief(covering))} 已完整覆盖 "
                        f"{_format_brief_ref(snippet_brief(snippet))}"
                    ),
                }
            )
            continue

        new_file = snippet.get("file_path")
        new_range = parse_line_range(snippet.get("line_no", ""))
        if new_file and new_range:
            contained = _find_snippets_safely_contained_by(
                snippet, new_range, new_file, merged
            )
            for removed in contained:
                merged.remove(removed)
                _merge_superseded_metadata(
                    snippet,
                    removed,
                    merge_overlap_sources=merge_overlap_sources,
                )
                overlap_replaced_count += 1
                dedup_report["events"].append(
                    {
                        "action": "replace_with_complete_block",
                        "removed": snippet_brief(removed),
                        "kept": snippet_brief(snippet),
                        "reason": (
                            f"保留更完整块 {_format_brief_ref(snippet_brief(snippet))}，"
                            f"移除被包含的 {_format_brief_ref(snippet_brief(removed))}"
                        ),
                    }
                )

        seen_keys.add(key)
        if not snippet.get("source"):
            snippet["source"] = "metadata"
        merged.append(snippet)
        grep_only_count += 1

    semantic_count = sum(1 for row in merged if row.get("source") == "semantic")
    dedup_report.update(
        {
            "output_total": len(merged),
            "output_semantic_count": semantic_count,
            "output_grep_count": grep_only_count,
            "skipped_count": overlap_skipped_count,
            "replaced_count": overlap_replaced_count,
        }
    )
    return (
        merged,
        semantic_count,
        grep_only_count,
        overlap_skipped_count,
        overlap_replaced_count,
        dedup_report,
    )


def log_merge_dedup_report(
    logger: logging.Logger,
    dedup_report: Dict[str, Any],
) -> None:
    """Emit a human-readable hybrid merge / dedup report."""
    input_sem = dedup_report.get("input_semantic_count", 0)
    input_grep = dedup_report.get("input_grep_count", 0)
    output_total = dedup_report.get("output_total", 0)
    output_sem = dedup_report.get("output_semantic_count", 0)
    output_grep = dedup_report.get("output_grep_count", 0)
    skipped = dedup_report.get("skipped_count", 0)
    replaced = dedup_report.get("replaced_count", 0)
    events = dedup_report.get("events") or []

    logger.info("=" * 80)
    logger.info(
        "[HYBRID DEDUP] 合并去重: 输入 semantic=%d + grep/skill=%d => 输出 %d 条 "
        "(保留 semantic=%d, grep/skill=%d; 替换=%d, 跳过=%d)",
        input_sem,
        input_grep,
        output_total,
        output_sem,
        output_grep,
        replaced,
        skipped,
    )

    if not events:
        logger.info("[HYBRID DEDUP] 无去重事件（两路结果无重叠或无需合并）")
        logger.info("=" * 80)
        return

    replace_events = [e for e in events if e.get("action") == "replace_with_complete_block"]
    skip_subset_events = [e for e in events if e.get("action") == "skip_subset"]
    skip_dup_events = [e for e in events if e.get("action") == "skip_duplicate_key"]

    if replace_events:
        logger.info("[HYBRID DEDUP] 以下片段被更完整代码块替换（通常: SEMANTIC 方法 -> READ_CODE_SKILL 类块）:")
        for i, event in enumerate(replace_events, 1):
            removed = event.get("removed") or {}
            kept = event.get("kept") or {}
            logger.info(
                "  [%d] 移除 %s | 保留 %s",
                i,
                _format_brief_ref(removed),
                _format_brief_ref(kept),
            )

    if skip_subset_events:
        logger.info("[HYBRID DEDUP] 以下 grep/skill 片段被跳过（已有更大块覆盖）:")
        for i, event in enumerate(skip_subset_events, 1):
            removed = event.get("removed") or {}
            kept = event.get("kept") or {}
            logger.info(
                "  [%d] 跳过 %s | 已有 %s",
                i,
                _format_brief_ref(removed),
                _format_brief_ref(kept),
            )

    if skip_dup_events:
        logger.info("[HYBRID DEDUP] 以下片段因重复键被跳过:")
        for i, event in enumerate(skip_dup_events, 1):
            removed = event.get("removed") or {}
            logger.info("  [%d] 跳过 %s", i, _format_brief_ref(removed))

    logger.info("=" * 80)
