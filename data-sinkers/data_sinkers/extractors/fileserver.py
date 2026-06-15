import os
from typing import Dict, Any, List, Tuple

from langchain_core.documents import Document

from ..readers.fileserver.fileserver_reader import FileServerReader
from ..api.base import DocumentModel
from model_sdk import ModelManager
from ..fingerprint.fingerprint import compute_fileserver_object_list_hash
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fileserver_extractor")

manager = ModelManager()

_llm = None


def _get_fileserver_llm():
    """Lazy LLM init so unit tests can import this module without API env vars."""
    global _llm
    if _llm is None:
        _llm = manager.get_llm(
            provider=os.getenv("PROVIDER", "openai_compatible"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            model=os.getenv("Model"),
            temperature=0.01,
            extra_body={
                "enable_thinking": False
            },
        )
    return _llm


def extract_fileserver(
    reader: FileServerReader,
    descriptor: Dict[str, Any],
    extract: Dict[str, Any],
    prompts: Dict[str, Any],
) -> Tuple[List[DocumentModel], Dict[str, Any]]:
    """
    Extract FileServer files into DocumentModels + fingerprint sidecar.

    与 MinIO 一致的分层策略：
        L1/L2: ``FileServerReader.query_files`` — 每文件 chunks + ``file_summary``(Refine) 富摘要
        L3: ``FileAnalyzer.bucket_file_summary_map_reduce`` — 多 per-file 摘要 Map-Reduce 合成 ddd
    """
    from .base import FileAnalyzer

    files = extract.get("files")

    if files is None:
        raise ValueError("files is None - 'files' key not found in extract dictionary")

    if not isinstance(files, list):
        raise ValueError(f"files must be a list, got {type(files)}")

    file_analyzer = FileAnalyzer(_get_fileserver_llm(), max_workers=50, batch_size=50)

    lang_docs, per_file_summary_docs = reader.query_files(
        files,
        file_analyzer=file_analyzer,
    )

    results = [
        DocumentModel(page_content=d.page_content, metadata=dict(d.metadata or {}))
        for d in lang_docs
    ]

    logger.info(
        "extract_fileserver L1/L2: files=%d chunks=%d per_file_summaries=%d",
        len(files),
        len(results),
        len(per_file_summary_docs),
    )

    if per_file_summary_docs:
        summary_inputs: List[DocumentModel] = [
            DocumentModel(page_content=d.page_content, metadata=dict(d.metadata or {}))
            for d in per_file_summary_docs
        ]
        logger.info(
            "extract_fileserver L3 bucket synthesis: %d per-file summaries → bucket_file_summary_map_reduce",
            len(summary_inputs),
        )
        file_summary = file_analyzer.bucket_file_summary_map_reduce(summary_inputs)
        summary = (file_summary.get("summary") if file_summary else "") or ""
        outline = (file_summary.get("outline") if file_summary else "") or ""
    else:
        summary = ""
        outline = ""

    logger.info(
        "extract_fileserver bucket summary_len=%d outline_len=%d total_chunks=%d",
        len(summary),
        len(outline),
        len(results),
    )

    agent_card = file_analyzer.agent_card(outline) if outline else {}

    # 与 extract_minio 对齐：ddd 含 summary + outline
    ddd = f"{summary}\n\n{outline}" if (summary or outline) else summary

    object_list_hash = compute_fileserver_object_list_hash(reader.config, files)

    fingerprint_associated_info = {
        "ddd": ddd,
        "agent_card": agent_card,
        "object_list_hash": object_list_hash,
    }

    return results, fingerprint_associated_info
