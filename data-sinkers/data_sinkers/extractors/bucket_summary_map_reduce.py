"""MinIO 桶级 L3 摘要：按 per-file 富摘要做 Map-Reduce 合成。

与 ``FileAnalyzer.file_summary``（L2 单文件 + Refine）分层配合：

- **L2**（``minio_reader._summarize_single_file``）：单文件 raw chunks → ``file_summary`` + Refine。
- **L3**（本模块）：多份 per-file 摘要 Document → 按文件切批 Map → Reduce 合并。

L3 **不再**对 per-file Document 调用 ``process_chunks_parallel`` / ``chunk_summary``，
避免重复蒸馏与文件溯源丢失。

日志统一前缀：``[桶级摘要|BucketSummary]``，便于在 Job 日志中检索完整处理链路。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from ..llm_invoke_retry import invoke_llm_with_json_retry, llm_json_parse_max_retries
from .context_budget import (
    bucket_summary_map_max_workers,
    bucket_summary_max_files_per_batch,
    bucket_summary_max_input_chars,
    chunk_entries_by_budget,
    format_entries_for_group_llm,
    total_entries_chars,
)

logger = logging.getLogger("bucket_summary_map_reduce")

# 与 semantic_domains 日志风格对齐，便于 grep Job 输出。
_LOG_PREFIX = "[桶级摘要|BucketSummary]"


def _log_begin(
    *,
    mode: str,
    file_count: int,
    total_chars: int,
    budget: int,
    max_files: int,
    batch_count: int,
) -> None:
    logger.info(
        "%s 开始 | mode=%s files=%d total_chars=%d budget=%d max_files_per_batch=%d batches=%d",
        _LOG_PREFIX,
        mode,
        file_count,
        total_chars,
        budget,
        max_files,
        batch_count,
    )


def _log_end(
    *,
    mode: str,
    elapsed_s: float,
    file_count: int,
    summary_len: int,
    outline_len: int,
) -> None:
    logger.info(
        "%s 完成 | mode=%s elapsed=%.1fs files=%d summary_len=%d outline_len=%d",
        _LOG_PREFIX,
        mode,
        elapsed_s,
        file_count,
        summary_len,
        outline_len,
    )


def documents_to_file_entries(documents: List[Any]) -> List[Dict[str, str]]:
    """将 L2 产出的 per-file Document 转为 Map-Reduce 装箱条目。

    每条 ``{file_path, file_summary}`` 与 ``context_budget.chunk_entries_by_budget``
    的输入格式一致；``file_path`` 优先取 ``minio_path``，其次 ``source`` / ``file_path``。
    """
    entries: List[Dict[str, str]] = []
    seen_paths: set[str] = set()

    for doc in documents or []:
        if doc is None:
            continue
        meta: Dict[str, Any] = {}
        page_content = ""
        if isinstance(doc, dict):
            meta = doc.get("metadata") or {}
            page_content = str(doc.get("page_content") or "")
        else:
            meta = dict(getattr(doc, "metadata", None) or {})
            page_content = str(getattr(doc, "page_content", "") or "")

        path = str(
            meta.get("minio_path") or meta.get("source") or meta.get("file_path") or ""
        ).strip()
        text = page_content.strip()
        if not path or not text or path in seen_paths:
            continue
        seen_paths.add(path)
        entries.append({"file_path": path, "file_summary": text})

    return entries


def _normalize_bucket_partial(raw: Any) -> Dict[str, Any]:
    """清洗 Map/Reduce 单次 LLM 产出的 partial 结构。"""
    if not isinstance(raw, dict):
        raw = {}

    doc_struct = raw.get("document_structure") or {}
    if not isinstance(doc_struct, dict):
        doc_struct = {}

    themes_raw = doc_struct.get("main_themes") or []
    if isinstance(themes_raw, (list, tuple, set)):
        themes = [str(t).strip() for t in themes_raw if str(t).strip()]
    else:
        themes = [str(themes_raw).strip()] if str(themes_raw).strip() else []

    files_raw = doc_struct.get("files_covered") or []
    if isinstance(files_raw, (list, tuple, set)):
        files_covered = [str(f).strip() for f in files_raw if str(f).strip()]
    else:
        files_covered = [str(files_raw).strip()] if str(files_raw).strip() else []

    return {
        "summary": str(raw.get("summary") or "").strip(),
        "outline": str(raw.get("outline") or "").strip(),
        "document_structure": {
            "main_themes": themes,
            "document_type": str(doc_struct.get("document_type") or "文档集合").strip(),
            "files_covered": files_covered,
        },
    }


def _validate_bucket_partial(partial: Dict[str, Any]) -> Optional[str]:
    """校验 partial 是否至少包含可用的 summary 或 outline。"""
    if partial.get("summary") or partial.get("outline"):
        return None
    return "summary 与 outline 均为空"


def _fallback_partial_from_entries(entries: List[Dict[str, str]]) -> Dict[str, Any]:
    """Map 批失败时的无 LLM 降级：拼接条目摘要，保留文件列表。"""
    paths = [e["file_path"] for e in entries]
    snippets = []
    for e in entries:
        snippet = e["file_summary"].replace("\n", " ").strip()
        if len(snippet) > 400:
            snippet = snippet[:397] + "..."
        snippets.append(snippet)
    return {
        "summary": "；".join(snippets)[:4000] if snippets else "",
        "outline": "\n".join(f"- {p}" for p in paths),
        "document_structure": {
            "main_themes": [],
            "document_type": "文档集合",
            "files_covered": paths,
        },
    }


def _format_partial_for_merge(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce 输入：去掉空字段，保持 JSON 紧凑。"""
    normalized = _normalize_bucket_partial(partial)
    return normalized


def format_bucket_partials_for_merge_llm(partials: List[Dict[str, Any]]) -> str:
    """多份 partial 序列化为 Reduce 阶段 human 消息 JSON。"""
    payload = [_format_partial_for_merge(p) for p in partials]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def estimate_bucket_partials_merge_chars(partials: List[Dict[str, Any]]) -> int:
    return len(format_bucket_partials_for_merge_llm(partials))


def chunk_bucket_partials_by_budget(
    partials: List[Dict[str, Any]],
    max_chars: int,
) -> List[List[Dict[str, Any]]]:
    """Reduce 阶段：partial JSON 列表超预算时切分为多片（贪心装箱）。"""
    if not partials:
        return []

    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_chars = 0

    for partial in partials:
        partial_chars = len(
            json.dumps(_format_partial_for_merge(partial), ensure_ascii=False)
        )
        separator = 2 if current else 0
        if current and current_chars + separator + partial_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
            partial_chars = len(
                json.dumps(_format_partial_for_merge(partial), ensure_ascii=False)
            )

        current.append(partial)
        current_chars += (2 if len(current) > 1 else 0) + partial_chars

    if current:
        chunks.append(current)

    return chunks


def premerge_bucket_partials(partials: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce 之前确定性合并（无 LLM）：拼接 summary、合并 themes/files_covered。"""
    if not partials:
        return _normalize_bucket_partial({})
    if len(partials) == 1:
        return _format_partial_for_merge(partials[0])

    summaries: List[str] = []
    outlines: List[str] = []
    themes: List[str] = []
    seen_themes: set[str] = set()
    files: List[str] = []
    seen_files: set[str] = set()
    doc_types: List[str] = []

    for partial in partials:
        norm = _format_partial_for_merge(partial)
        s = (norm.get("summary") or "").strip()
        if s:
            summaries.append(s)
        o = (norm.get("outline") or "").strip()
        if o:
            outlines.append(o)
        ds = norm.get("document_structure") or {}
        dt = str(ds.get("document_type") or "").strip()
        if dt and dt != "文档集合":
            doc_types.append(dt)
        for t in ds.get("main_themes") or []:
            key = t.strip().lower()
            if key and key not in seen_themes:
                seen_themes.add(key)
                themes.append(t.strip())
        for f in ds.get("files_covered") or []:
            if f and f not in seen_files:
                seen_files.add(f)
                files.append(f)

    return {
        "summary": "；".join(summaries),
        "outline": "\n\n".join(outlines),
        "document_structure": {
            "main_themes": themes,
            "document_type": doc_types[0] if doc_types else "文档集合",
            "files_covered": files,
        },
    }


def _build_map_prompt(batch_hint: Optional[str] = None) -> str:
    hint = ""
    if batch_hint:
        hint = f"\n**分批说明：** {batch_hint}\n"
    return f"""你是一位资深的文档架构师与知识库编辑。下面是一批**独立文件**的 per-file 摘要（每文件一条，已含路径与大纲片段）。
请仅基于本批材料，综合提炼出**本批**的结构化 partial 结果，供后续与其他批次 Reduce 合并为整个存储桶（bucket）的总视图。
{hint}
要求：
1. **summary**：2-5 句话概括本批文件共同/并列涵盖的业务主题与价值（中文）。
2. **outline**：多层级大纲（``1.`` / ``1.1`` 格式），覆盖本批各文件的核心要点；可标注关键文件路径。
3. **document_structure.main_themes**：本批主要主题词列表（3-8 个）。
4. **document_structure.document_type**：如「技术文档集」「产品规范集」等。
5. **document_structure.files_covered**：本批出现的全部文件路径（与输入一致，勿编造未提供的 path）。

**禁止**引用输入中未出现的文件路径。

输出格式（仅 JSON，无 Markdown 围栏）：
{{
  "summary": "...",
  "outline": "...",
  "document_structure": {{
    "main_themes": ["主题1", "主题2"],
    "document_type": "文档集合类型",
    "files_covered": ["minio://bucket/a.pdf", "..."]
  }}
}}"""


def _build_merge_prompt() -> str:
    return """你是一位资深的文档架构师。下面是一份存储桶（bucket）多批 partial 摘要的 JSON 数组。
请合并为**一份**覆盖全部文件的整体 bucket 视图。

要求：
1. **summary**：整体 3-6 句话，概括桶内全部文档的业务域、核心能力与知识范围。
2. **outline**：统一的多层级大纲，逻辑清晰（背景→能力→流程→规范等），合并去重，保留关键文件路径引用。
3. **document_structure.main_themes**：合并去重后的主题列表。
4. **document_structure.files_covered**：合并各批 files_covered，去重，顺序保持稳定。

输出格式（仅 JSON）：
{
  "summary": "...",
  "outline": "...",
  "document_structure": {
    "main_themes": ["..."],
    "document_type": "文档集合",
    "files_covered": ["..."]
  }
}"""


def _invoke_map_llm(
    llm: Any,
    entries: List[Dict[str, str]],
    *,
    format_llm_output: Callable[[Any], dict],
    label: str,
    batch_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Map 阶段：对本批 per-file 条目调用一次 LLM。"""
    human_body = format_entries_for_group_llm(entries)
    system_message = SystemMessage(content=_build_map_prompt(batch_hint))
    human_message = HumanMessage(
        content=f"以下为本批 per-file 摘要（File N. path，summary 格式）：\n\n{human_body}"
    )

    logger.info(
        "%s Map | label=%s files=%d input_chars=%d",
        _LOG_PREFIX,
        label,
        len(entries),
        len(human_body),
    )

    def _parse_map_response(response: Any) -> Dict[str, Any]:
        return _normalize_bucket_partial(format_llm_output(response))

    def _validate_map_partial(partial: Any) -> Optional[str]:
        if not isinstance(partial, dict):
            return f"expected dict, got {type(partial).__name__}"
        return _validate_bucket_partial(partial)

    partial = invoke_llm_with_json_retry(
        llm,
        [system_message, human_message],
        _parse_map_response,
        validate=_validate_map_partial,
        label=f"{_LOG_PREFIX} Map {label}",
    )
    if partial is not None and _validate_bucket_partial(partial) is None:
        logger.info(
            "%s Map 成功 | label=%s summary_len=%d outline_len=%d themes=%d files_covered=%d",
            _LOG_PREFIX,
            label,
            len(partial.get("summary") or ""),
            len(partial.get("outline") or ""),
            len((partial.get("document_structure") or {}).get("main_themes") or []),
            len((partial.get("document_structure") or {}).get("files_covered") or []),
        )
        return partial

    logger.error(
        "%s Map 重试 %d 次仍失败 label=%s，使用降级 partial",
        _LOG_PREFIX,
        llm_json_parse_max_retries(),
        label,
    )
    return _fallback_partial_from_entries(entries)


def _invoke_merge_llm(
    llm: Any,
    partial_results: List[Dict[str, Any]],
    *,
    format_llm_output: Callable[[Any], dict],
    label: str,
) -> Dict[str, Any]:
    """Reduce 阶段：合并多份 partial。"""
    merge_content = format_bucket_partials_for_merge_llm(partial_results)
    system_message = SystemMessage(content=_build_merge_prompt())
    human_message = HumanMessage(
        content=f"请合并以下各批次桶级 partial 摘要：\n\n{merge_content}"
    )

    logger.info(
        "%s Reduce | label=%s partials=%d input_chars=%d",
        _LOG_PREFIX,
        label,
        len(partial_results),
        len(merge_content),
    )

    def _parse_merge_response(response: Any) -> Dict[str, Any]:
        return _normalize_bucket_partial(format_llm_output(response))

    def _validate_merge_partial(partial: Any) -> Optional[str]:
        if not isinstance(partial, dict):
            return f"expected dict, got {type(partial).__name__}"
        return _validate_bucket_partial(partial)

    merged = invoke_llm_with_json_retry(
        llm,
        [system_message, human_message],
        _parse_merge_response,
        validate=_validate_merge_partial,
        label=f"{_LOG_PREFIX} Reduce {label}",
    )
    if merged is not None and _validate_bucket_partial(merged) is None:
        logger.info(
            "%s Reduce 成功 | label=%s summary_len=%d outline_len=%d",
            _LOG_PREFIX,
            label,
            len(merged.get("summary") or ""),
            len(merged.get("outline") or ""),
        )
        return merged

    logger.error(
        "%s Reduce 重试 %d 次仍失败 label=%s，使用确定性 premerge",
        _LOG_PREFIX,
        llm_json_parse_max_retries(),
        label,
    )
    return premerge_bucket_partials(partial_results)


def _merge_bucket_partials_recursive(
    llm: Any,
    partial_results: List[Dict[str, Any]],
    budget: int,
    format_llm_output: Callable[[Any], dict],
    depth: int = 0,
) -> Dict[str, Any]:
    """Reduce 递归：partial 合并 JSON 超预算时先分片合并再上层合并。"""
    if not partial_results:
        return _normalize_bucket_partial({})
    if len(partial_results) == 1:
        return _format_partial_for_merge(partial_results[0])

    merge_chars = estimate_bucket_partials_merge_chars(partial_results)
    if merge_chars <= budget:
        return _invoke_merge_llm(
            llm,
            partial_results,
            format_llm_output=format_llm_output,
            label=f"bucket-summary-merge-d{depth}",
        )

    chunks = chunk_bucket_partials_by_budget(partial_results, budget)
    logger.info(
        "%s Reduce 切分 | depth=%d partials=%d merge_chars=%d budget=%d split_into=%d",
        _LOG_PREFIX,
        depth,
        len(partial_results),
        merge_chars,
        budget,
        len(chunks),
    )

    merged_partials: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        if len(chunk) == 1:
            merged_partials.append(_format_partial_for_merge(chunk[0]))
            continue
        merged_partials.append(
            _invoke_merge_llm(
                llm,
                chunk,
                format_llm_output=format_llm_output,
                label=f"bucket-summary-merge-d{depth}-c{idx + 1}",
            )
        )

    if len(merged_partials) == 1:
        return merged_partials[0]
    return _merge_bucket_partials_recursive(
        llm,
        merged_partials,
        budget,
        format_llm_output,
        depth=depth + 1,
    )


def _to_file_summary_result(
    partial: Dict[str, Any],
    *,
    total_files: int,
) -> Dict[str, Any]:
    """与 ``FileAnalyzer.file_summary`` 返回值字段对齐，供 ``extract_minio`` 无感切换。"""
    norm = _normalize_bucket_partial(partial)
    ds = norm.get("document_structure") or {}
    themes = ds.get("main_themes") or []
    return {
        "summary": norm.get("summary") or "",
        "outline": norm.get("outline") or "",
        "analysis_logic": "",
        "overall_conclusion": "",
        "document_structure": {
            "total_sections": total_files,
            "main_themes": themes,
            "document_type": ds.get("document_type") or "文档集合",
        },
        "total_chunks": total_files,
        "processed_chunks": total_files,
        "bucket_summary_mode": "map_reduce",
    }


def run_bucket_file_summary_map_reduce(
    llm: Any,
    documents: List[Any],
    *,
    format_llm_output: Callable[[Any], dict],
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """L3 桶级合成入口：per-file 摘要 Document 列表 → bucket summary + outline。

    不调用 ``chunk_summary`` / ``process_chunks_parallel``；按文件路径切批 Map，
    再 Reduce 为与 ``file_summary`` 相同结构的 dict。
    """
    t0 = time.perf_counter()
    entries = documents_to_file_entries(documents)
    if not entries:
        logger.info("%s 跳过 | 无有效 per-file 条目", _LOG_PREFIX)
        return _to_file_summary_result({}, total_files=0)

    budget = bucket_summary_max_input_chars()
    max_files = bucket_summary_max_files_per_batch()
    workers = max_workers if max_workers is not None else bucket_summary_map_max_workers()
    total_chars = total_entries_chars(entries)

    # 单文件桶：一次 Map 即可，无需 Reduce。
    if len(entries) == 1:
        _log_begin(
            mode="SINGLE_FILE",
            file_count=1,
            total_chars=total_chars,
            budget=budget,
            max_files=max_files,
            batch_count=1,
        )
        partial = _invoke_map_llm(
            llm,
            entries,
            format_llm_output=format_llm_output,
            label="bucket-summary-map-single",
            batch_hint="当前桶内仅 1 个文件，输出即为最终 bucket 视图。",
        )
        result = _to_file_summary_result(partial, total_files=1)
        _log_end(
            mode="SINGLE_FILE",
            elapsed_s=time.perf_counter() - t0,
            file_count=1,
            summary_len=len(result.get("summary") or ""),
            outline_len=len(result.get("outline") or ""),
        )
        return result

    # 多文件但未超预算：单批 Map，仍走 Map prompt（保留 files_covered），跳过 Reduce。
    if total_chars <= budget and len(entries) <= max_files:
        _log_begin(
            mode="SINGLE_BATCH",
            file_count=len(entries),
            total_chars=total_chars,
            budget=budget,
            max_files=max_files,
            batch_count=1,
        )
        partial = _invoke_map_llm(
            llm,
            entries,
            format_llm_output=format_llm_output,
            label="bucket-summary-map-single-batch",
            batch_hint="当前为唯一一批，覆盖桶内全部文件。",
        )
        result = _to_file_summary_result(partial, total_files=len(entries))
        _log_end(
            mode="SINGLE_BATCH",
            elapsed_s=time.perf_counter() - t0,
            file_count=len(entries),
            summary_len=len(result.get("summary") or ""),
            outline_len=len(result.get("outline") or ""),
        )
        return result

    # 多批 Map-Reduce。
    batches = chunk_entries_by_budget(entries, budget, max_files)
    _log_begin(
        mode="MULTI_BATCH",
        file_count=len(entries),
        total_chars=total_chars,
        budget=budget,
        max_files=max_files,
        batch_count=len(batches),
    )
    for i, batch in enumerate(batches, 1):
        batch_chars = total_entries_chars(batch)
        paths_preview = ", ".join(e["file_path"] for e in batch[:3])
        if len(batch) > 3:
            paths_preview += f", ... (+{len(batch) - 3} more)"
        logger.info(
            "%s Map 计划 | batch=%d/%d files=%d chars=%d paths=[%s]",
            _LOG_PREFIX,
            i,
            len(batches),
            len(batch),
            batch_chars,
            paths_preview,
        )

    def _map_one(item: Tuple[int, List[Dict[str, str]]]) -> Dict[str, Any]:
        batch_idx, batch_entries = item
        hint = (
            f"当前为第 {batch_idx + 1}/{len(batches)} 批，只分析本批文件；"
            f"不要引用未提供的文件路径。"
        )
        return _invoke_map_llm(
            llm,
            batch_entries,
            format_llm_output=format_llm_output,
            label=f"bucket-summary-map-b{batch_idx + 1}",
            batch_hint=hint,
        )

    partial_results: List[Dict[str, Any]] = []
    batch_items = list(enumerate(batches))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(_map_one, item): item[0] for item in batch_items
        }
        # 按 batch_idx 排序，保证 Reduce 输入顺序稳定。
        indexed_results: Dict[int, Dict[str, Any]] = {}
        for future in as_completed(future_to_idx):
            batch_idx = future_to_idx[future]
            batch_entries = batches[batch_idx]
            try:
                indexed_results[batch_idx] = future.result()
            except Exception as exc:
                logger.error(
                    "%s Map 批失败 batch=%d/%d err=%s，使用降级 partial",
                    _LOG_PREFIX,
                    batch_idx + 1,
                    len(batches),
                    exc,
                    exc_info=True,
                )
                indexed_results[batch_idx] = _fallback_partial_from_entries(batch_entries)
        for idx in sorted(indexed_results):
            partial_results.append(indexed_results[idx])

    logger.info(
        "%s Map 全部完成 | batches=%d partials=%d → 进入 Reduce",
        _LOG_PREFIX,
        len(batches),
        len(partial_results),
    )

    if len(partial_results) == 1:
        final_partial = partial_results[0]
    else:
        final_partial = _merge_bucket_partials_recursive(
            llm,
            partial_results,
            budget,
            format_llm_output,
        )

    result = _to_file_summary_result(final_partial, total_files=len(entries))
    _log_end(
        mode="MULTI_BATCH",
        elapsed_s=time.perf_counter() - t0,
        file_count=len(entries),
        summary_len=len(result.get("summary") or ""),
        outline_len=len(result.get("outline") or ""),
    )
    return result
