"""Recall code snippets via the full read-code skill agent (LLM + grep + LSP + readline).

Replaces the ripgrep-only ``SkillGrepSearcher`` slice: uses ``SkillRunner.run()``
with the read-code skill so the agent plans tool use semantically.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agent.skill_repo_cwd import use_code_repo_cwd

logger = logging.getLogger(__name__)

READ_CODE_SKILL_NAME = "read-code"

SCHEME_READ_CODE = "read_code_skill"
SCHEME_METADATA_LOCAL = "metadata_local"


def resolve_grep_recall_scheme(
    *,
    explicit: Optional[str] = None,
    use_local_grep: Optional[bool] = None,
    use_skill_grep: Optional[bool] = None,
) -> str:
    """Resolve grep recall scheme: read-code skill (default) or metadata+local."""
    if explicit:
        normalized = explicit.strip().lower().replace("-", "_")
        if normalized in (SCHEME_READ_CODE, "read_code", "skill", "read_code_skill"):
            return SCHEME_READ_CODE
        if normalized in (
            SCHEME_METADATA_LOCAL,
            "metadata_local",
            "metadata_grep",
            "metadata",
        ):
            return SCHEME_METADATA_LOCAL

    # Legacy flags: use_local_grep=True or use_skill_grep=False → metadata+local
    if use_local_grep is True or use_skill_grep is False:
        return SCHEME_METADATA_LOCAL

    raw = (
        os.getenv("GREP_RECALL_SCHEME")
        or os.getenv("SKILL_RECALL_SCHEME")
        or SCHEME_READ_CODE
    ).strip().lower().replace("-", "_")
    if raw in (SCHEME_METADATA_LOCAL, "metadata_local", "metadata_grep", "metadata"):
        return SCHEME_METADATA_LOCAL
    if raw in ("false", "0", "no", "off", "disabled"):
        return SCHEME_METADATA_LOCAL
    return SCHEME_READ_CODE


def is_skill_recall_enabled() -> bool:
    """True when default/env scheme is read-code skill."""
    return resolve_grep_recall_scheme() == SCHEME_READ_CODE


is_skill_grep_enabled = is_skill_recall_enabled

_SYMBOL_LINE_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|func|type|interface|struct|enum)\s+(\w+)",
    re.MULTILINE,
)


def _normalize_repo_path(file_path: str, code_paths: Sequence[str]) -> str:
    raw = (file_path or "").replace("\\", "/").strip()
    if not raw:
        return raw
    path = Path(raw)
    if path.is_absolute():
        for root in code_paths:
            try:
                return str(path.resolve().relative_to(Path(root).resolve())).replace("\\", "/")
            except ValueError:
                continue
        return raw.lstrip("/")
    return raw.lstrip("/")


def _guess_symbol_name(code_content: str) -> str:
    m = _SYMBOL_LINE_RE.search(code_content or "")
    return m.group(1) if m else "code_block"


def _parse_tool_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if not isinstance(result, str) or not result.strip():
        return {}
    try:
        parsed = json.loads(result)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def extract_code_snippets_from_tool_history(
    tool_history: Sequence[dict[str, Any]],
    *,
    query: str,
    code_paths: Optional[Sequence[str]] = None,
    max_snippets: int = 20,
) -> List[Dict[str, Any]]:
    """Build code-agent ``code_snippets`` from read-code ``tool_history``."""
    roots = list(code_paths or [])
    snippets: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for entry in tool_history:
        tool = entry.get("tool") or ""
        args = entry.get("args") or {}
        data = _parse_tool_result(entry.get("result"))

        if tool != "readline_in_range":
            continue
        if data.get("error"):
            continue

        content = (data.get("content") or "").strip()
        if not content:
            continue

        file_path = _normalize_repo_path(str(args.get("file_path") or ""), roots)
        start = data.get("start") or args.get("start") or ""
        end = data.get("end") or args.get("end") or ""
        if start and end and str(start) != str(end):
            line_no = f"{start}-{end}"
        elif start:
            line_no = str(start)
        else:
            line_no = ""

        name = _guess_symbol_name(content)
        dedup_key = (file_path, line_no, content.split("\n", 1)[0].strip())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        snippets.append(
            {
                "file_path": file_path,
                "segment_type": "skill_read",
                "name": name,
                "line_no": line_no,
                "relevance_reason": f"read-code skill 定位: {(query or '')[:120]}",
                "business_meaning": "",
                "code_content": content,
                "source": "skill_read_code",
            }
        )
        if len(snippets) >= max_snippets:
            break

    return snippets


def _build_recall_query(user_query: str) -> str:
    return (
        "请在当前代码仓库中定位与用户问题最相关的代码实现。\n"
        "必须使用 read-code skill 的工具链（grep / glob / lsp / readline_in_range）"
        "阅读关键代码片段；用 readline_in_range 读取完整函数或类体。\n"
        "任务目标仅为定位并读取代码，不要写总结性 final_answer；"
        "读完足够代码后调用 finish，final_answer 可简短说明已读取哪些文件/符号。\n\n"
        f"用户问题：{user_query}"
    )


def _resolve_read_code_skill(runner: Any) -> Any | None:
    lister = getattr(runner, "lister", None)
    if lister is None:
        return None
    candidates = lister.find_by_name(READ_CODE_SKILL_NAME, match="exact", case_insensitive=True)
    return candidates[0] if candidates else None


async def recall_via_read_code_skill(
    *,
    query: str,
    skill_runner: Any,
    user_id: str = "",
    run_id: str = "",
    trace_id: str = "",
    code_paths: Optional[Sequence[str]] = None,
    max_snippets: int = 20,
) -> Dict[str, Any]:
    """Run read-code skill agent and return normalized ``code_snippets``."""
    empty: Dict[str, Any] = {
        "code_snippets": [],
        "skill_recall_count": 0,
        "skill_status": "unavailable",
    }
    if not query or not skill_runner:
        return empty

    skill = _resolve_read_code_skill(skill_runner)
    if skill is None:
        logger.warning("[SkillRecall] read-code skill not loaded")
        return {**empty, "skill_status": "skill_not_loaded"}

    recall_query = _build_recall_query(query)
    logger.info("[SkillRecall] running read-code agent query=%r", query[:180])

    try:
        async with use_code_repo_cwd(list(code_paths or [])):
            result = await skill_runner.run(
                recall_query,
                skill,
                user_id=user_id or "",
                run_id=run_id or "",
                trace_id=trace_id or "",
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[SkillRecall] read-code run failed: %s", exc)
        return {**empty, "skill_status": "error", "error": str(exc)}

    status = str(result.get("status") or "")
    tool_history = result.get("tool_history") or []
    snippets = extract_code_snippets_from_tool_history(
        tool_history,
        query=query,
        code_paths=code_paths,
        max_snippets=max_snippets,
    )

    logger.info(
        "[SkillRecall] status=%s tool_steps=%d snippets=%d",
        status,
        len(tool_history),
        len(snippets),
    )

    return {
        "code_snippets": snippets,
        "skill_recall_count": len(snippets),
        "skill_status": status,
        "skill_result": result,
    }
