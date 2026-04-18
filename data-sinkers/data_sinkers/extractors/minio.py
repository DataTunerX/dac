import json
import os
from typing import Dict, Any, Optional, List, Sequence

from langchain_core.documents import Document

from ..client.knowledge_pyramid_client import KnowledgePyramidClient
from ..client.unstructured_files_client import UnstructuredFilesClient
from ..readers.minio.minio_reader import MinIOReader
from ..api.base import DocumentModel
from model_sdk import ModelManager
from .base import FileAnalyzer
from ..fingerprint.fingerprint import compute_minio_bucket_object_list_hash
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minio_extractor")

# Must match chunk metadata in readers/minio/minio_reader.py query_one()
_MINIO_SOURCE_METADATA_KEY = "source"


def delete_minio_objects_from_pyramid_and_inventory(
    *,
    collection_name: str,
    bucket: str,
    dd_namespace: str,
    dd_name: str,
    object_names: Sequence[str],
    knowledge_pyramid_client: KnowledgePyramidClient,
    unstructured_files_client: UnstructuredFilesClient,
) -> None:
    """
    Incremental AddOrUpdate: for each object key, remove pyramid chunks where
    metadata[source] == minio://bucket/key and delete the matching unstructured_files row.
    """
    for obj_name in object_names:
        if not obj_name or str(obj_name).endswith("/"):
            continue
        source_value = f"minio://{bucket}/{obj_name}"
        try:
            pyramid_resp = knowledge_pyramid_client.delete_by_metadata_field(
                collection_name,
                _MINIO_SOURCE_METADATA_KEY,
                source_value,
            )
            logger.info(
                "[data-sinker] minio_cleanup pyramid_delete_by_metadata status=success "
                "collection=%s dd=%s/%s source=%r response=%s",
                collection_name,
                dd_namespace,
                dd_name,
                source_value,
                json.dumps(pyramid_resp, ensure_ascii=False) if isinstance(pyramid_resp, dict) else str(pyramid_resp)[:500],
            )
        except Exception as e:
            logger.warning(
                "[data-sinker] minio_cleanup pyramid_delete_by_metadata status=failed "
                "collection=%s dd=%s/%s source=%r error=%s",
                collection_name,
                dd_namespace,
                dd_name,
                source_value,
                e,
            )
        try:
            inv_resp = unstructured_files_client.delete_unstructured_file_by_object(
                dd_namespace,
                dd_name,
                bucket,
                source_value,
            )
            logger.info(
                "[data-sinker] minio_cleanup unstructured_delete_by_object status=success "
                "dd=%s/%s bucket=%s source=%r response=%s",
                dd_namespace,
                dd_name,
                bucket,
                source_value,
                json.dumps(inv_resp, ensure_ascii=False) if isinstance(inv_resp, dict) else str(inv_resp)[:500],
            )
        except Exception as e:
            logger.warning(
                "[data-sinker] minio_cleanup unstructured_delete_by_object status=failed "
                "dd=%s/%s bucket=%s source=%r error=%s",
                dd_namespace,
                dd_name,
                bucket,
                source_value,
                e,
            )


manager = ModelManager()

llm = manager.get_llm(
    provider=os.getenv("PROVIDER","openai_compatible"),
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model=os.getenv("Model"),
    temperature=0.01,
    extra_body={
        "enable_thinking": False
    },
)

def _attach_per_file_summaries_to_descriptors(
    minio_file_descriptors: List[Dict[str, Any]],
    per_file_summary_docs: List[Document],
) -> None:
    """
    Copy each file's LLM summary (``page_content``) into the matching descriptor entry,
    keyed by ``minio_path``. Descriptors whose file was not summarized in this run are
    left untouched so data-services can preserve any previously stored summary.
    """
    if not per_file_summary_docs or not minio_file_descriptors:
        return
    path_to_summary: Dict[str, str] = {}
    for d in per_file_summary_docs:
        meta = d.metadata or {}
        mp = str(meta.get("minio_path") or "").strip()
        text = str(getattr(d, "page_content", "") or "").strip()
        if mp and text:
            path_to_summary[mp] = text
    if not path_to_summary:
        return
    for desc in minio_file_descriptors:
        mp = str(desc.get("minio_path") or "").strip()
        s = path_to_summary.get(mp)
        if s:
            desc["file_summary"] = s


def _build_bucket_summary_docs(
    minio_file_descriptors: List[Dict[str, Any]],
    fresh_summary_docs: List[Document],
    stored_summaries_by_path: Dict[str, str],
):
    """
    Build one summary Document per **live bucket file** for bucket-level ``ddd`` synthesis.

    Precedence per ``minio_path``:
      1. Freshly computed summary from this run (added / modified files).
      2. Previously persisted ``file_summary`` in data-services (unchanged files).
      3. If neither, the file is skipped and counted as ``missing``.

    This preserves the full-bucket view across incremental runs, so SD/KG are rebuilt
    from *all* files' summaries, not only the delta.

    Returns ``(docs, fresh_count, reused_count, missing_count)``.
    """
    fresh_by_path: Dict[str, Document] = {}
    for d in fresh_summary_docs:
        mp = str((d.metadata or {}).get("minio_path") or "").strip()
        text = str(getattr(d, "page_content", "") or "").strip()
        if mp and text:
            fresh_by_path[mp] = d

    docs: List[Document] = []
    fresh_count = 0
    reused_count = 0
    missing_count = 0
    for desc in minio_file_descriptors:
        mp = str(desc.get("minio_path") or "").strip()
        if not mp:
            continue
        if mp in fresh_by_path:
            docs.append(fresh_by_path[mp])
            fresh_count += 1
            continue
        stored_text = stored_summaries_by_path.get(mp)
        if stored_text:
            docs.append(
                Document(
                    page_content=stored_text,
                    metadata={
                        "minio_path": mp,
                        "source": mp,
                        "file_name": desc.get("file_name") or "",
                        "bucket": desc.get("bucket") or "",
                        "summary_source": "stored",
                    },
                )
            )
            reused_count += 1
        else:
            missing_count += 1
    return docs, fresh_count, reused_count, missing_count


def extract_minio(
    reader: MinIOReader,
    descriptor: Dict[str, Any],
    extract: Dict[str, Any],
    prompts: Dict[str, Any],
    objects_for_document_query: Optional[Sequence[str]] = None,
    unstructured_files_client: Optional[UnstructuredFilesClient] = None,
) -> List[DocumentModel]:
    """
    Extract MinIO bucket content into DocumentModels + fingerprint sidecar.

    ``objects_for_document_query``:
        - ``None``: read and chunk **all** objects (legacy full sync).
        - empty sequence: read **no** object bodies (inventory / hash only).
        - non-empty: only chunk listed object keys (incremental body read).
    Full ``minio_file_descriptors`` for unstructured_files upsert always come from bucket listing
    (no per-file download), via :meth:`MinIOReader.build_file_descriptors_for_bucket`.

    Summarization strategy (bucket-scoped, delta-read):
        1. :meth:`MinIOReader.query` summarizes **each file independently** for the files
           actually read this run (full sync: all files; incremental: only added/modified).
        2. For incremental runs, the per-file summaries of *unchanged* files are fetched from
           data-services via ``unstructured_files_client.list_unstructured_files`` so the
           bucket-level ``ddd`` / ``agent_card`` are synthesized over the **whole bucket**
           (freshly-computed summaries override any stored summary for the same ``minio_path``).
        3. Each file's freshly-computed summary is written back into its matching
           ``minio_file_descriptors`` row as ``file_summary`` for persistence.
    """
    dd_namespace = str(descriptor.get("namespace") or "").strip()
    dd_name = str(descriptor.get("name") or "").strip()

    minio_file_descriptors = reader.build_file_descriptors_for_bucket(dd_namespace, dd_name)

    bucket = reader.config.get("bucket")
    object_list_hash = compute_minio_bucket_object_list_hash(bucket, reader.client.conn)

    file_analyzer = FileAnalyzer(llm, max_workers=50, batch_size=50)

    per_file_summary_docs: List[Document] = []
    if objects_for_document_query is not None:
        objs = [str(o) for o in objects_for_document_query if o and not str(o).endswith("/")]
        if objs:
            lang_docs, _partial, per_file_summary_docs = reader.query(
                prefix="", recursive=True, objects=objs, file_analyzer=file_analyzer
            )
            results = [DocumentModel(page_content=d.page_content, metadata=dict(d.metadata or {})) for d in lang_docs]
        else:
            results = []
    else:
        lang_docs, _partial, per_file_summary_docs = reader.query(
            prefix="", recursive=True, objects=None, file_analyzer=file_analyzer
        )
        results = [DocumentModel(page_content=d.page_content, metadata=dict(d.metadata or {})) for d in lang_docs]

    _attach_per_file_summaries_to_descriptors(minio_file_descriptors, per_file_summary_docs)

    # Pull persisted summaries for files we did not re-read this run (incremental re-sync)
    # so the bucket-level summary covers the whole bucket, not just the delta.
    stored_summaries_by_path: Dict[str, str] = {}
    if unstructured_files_client is not None and minio_file_descriptors:
        try:
            stored_summaries_by_path = reader.fetch_saved_inventory_file_summaries(
                dd_namespace, dd_name, unstructured_files_client
            )
        except Exception as e:
            logger.warning(
                "fetch_saved_inventory_file_summaries failed for dd=%s/%s: %s",
                dd_namespace,
                dd_name,
                e,
            )

    bucket_summary_docs, fresh_count, reused_count, missing_count = _build_bucket_summary_docs(
        minio_file_descriptors, per_file_summary_docs, stored_summaries_by_path
    )

    if bucket_summary_docs:
        summary_inputs: List[DocumentModel] = [
            DocumentModel(page_content=d.page_content, metadata=dict(d.metadata or {}))
            for d in bucket_summary_docs
        ]
        file_summary = file_analyzer.file_summary(summary_inputs)
        summary = (file_summary.get("summary") if file_summary else "") or ""
        outline = (file_summary.get("outline") if file_summary else "") or ""
    else:
        # Bucket is empty or has no summaries at all (e.g. first-ever run that read nothing).
        summary = ""
        outline = ""

    logger.info(
        "extract_minio bucket summary_len=%d outline_len=%d fresh=%d reused_stored=%d missing=%d total_live_files=%d",
        len(summary),
        len(outline),
        fresh_count,
        reused_count,
        missing_count,
        len(minio_file_descriptors),
    )

    logger.info(f"extract_minio, summary: {summary}")

    logger.info(f"extract_minio, outline: {outline}")

    agent_card = file_analyzer.agent_card(outline) if outline else {}

    ddd = f"{summary}\n\n{outline}" if (summary or outline) else ""

    fingerprint_associated_info = {
        "ddd": ddd,
        "agent_card": agent_card,
        "object_list_hash": object_list_hash,
        "minio_file_descriptors": minio_file_descriptors,
    }

    return results, fingerprint_associated_info