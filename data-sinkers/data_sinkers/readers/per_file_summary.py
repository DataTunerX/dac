"""L2 per-file 富摘要：单文件 raw chunks → ``file_summary``(Refine) → 结构化 Document。

MinIO 与 FileServer 共用，供 L3 ``bucket_file_summary_map_reduce`` 消费。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

logger = logging.getLogger("per_file_summary")


def build_per_file_summary_document(
    file_analyzer: Any,
    documents: List[Document],
    *,
    file_uri: str,
    file_name: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Document]:
    """对单文件 chunks 调 ``file_analyzer.file_summary``（Refine），打包为 L3 输入 Document。

    Args:
        file_analyzer: 提供 ``file_summary(List) -> dict`` 的分析器（通常为 ``FileAnalyzer``）。
        documents: 该文件经 Processor 切块后的 Document 列表。
        file_uri:  canonical 路径，写入 ``metadata['source']`` / ``minio_path``（Map-Reduce 装箱用）。
        file_name: 展示用文件名；默认从 ``file_uri`` 取 basename。
        extra_metadata: 附加元数据（如 ``fileserver_endpoint``、``bucket``）。

    Returns:
        富摘要 Document；LLM 失败或无有效内容时返回 ``None``。
    """
    uri = str(file_uri or "").strip()
    if not uri or not documents:
        return None

    name = (file_name or os.path.basename(uri.split("?")[0].rstrip("/")) or uri).strip()

    try:
        fs_result = file_analyzer.file_summary(documents) or {}
    except Exception as sum_err:
        logger.warning("L2 per-file file_summary failed for %s: %s", uri, sum_err)
        return None

    summary_text = str(fs_result.get("summary") or "").strip()
    outline_text = str(fs_result.get("outline") or "").strip()

    doc_struct = fs_result.get("document_structure") or {}
    if not isinstance(doc_struct, dict):
        doc_struct = {}
    doc_type = str(doc_struct.get("document_type") or "").strip()
    raw_themes = doc_struct.get("main_themes") or []
    if isinstance(raw_themes, (list, tuple, set)):
        themes: List[str] = [str(t).strip() for t in raw_themes if str(t).strip()]
    else:
        themes = [str(raw_themes).strip()] if str(raw_themes).strip() else []

    if not (summary_text or outline_text or themes or doc_type):
        return None

    sections: List[str] = [f"【文件】{name}（{uri}）"]
    if doc_type:
        sections.append(f"【类型】{doc_type}")
    if themes:
        sections.append("【主题】" + "、".join(themes))
    if summary_text:
        sections.append(f"【摘要】{summary_text}")
    if outline_text:
        sections.append("【大纲】\n" + outline_text)

    page_content = "\n".join(sections)

    meta: Dict[str, Any] = {
        "file_name": name,
        "source": uri,
        # bucket_summary_map_reduce.documents_to_file_entries 优先 minio_path，其次 source
        "minio_path": uri,
        "file_path": uri,
        "summary": summary_text,
        "outline": outline_text,
        "document_type": doc_type,
        "main_themes": themes,
    }
    if extra_metadata:
        meta.update(extra_metadata)

    logger.info(
        "[L2|PerFileSummary] uri=%s summary_len=%d outline_len=%d themes=%d page_content_len=%d",
        uri,
        len(summary_text),
        len(outline_text),
        len(themes),
        len(page_content),
    )
    return Document(page_content=page_content, metadata=meta)
