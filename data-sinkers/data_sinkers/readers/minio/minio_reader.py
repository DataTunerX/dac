import json
import tempfile
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from minio.error import S3Error
from langchain_core.documents import Document
from .minio_conn import GeneralMinio
from ..base.base_reader import BaseDataReader
from ...file_processors.general import Processor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minio_reader")

UNSTRUCTURED_FILE_RECORD_KEY = "unstructured_file_record"


def _normalize_etag(raw: Any) -> str:
    if raw is None:
        return ""
    s = raw if isinstance(raw, str) else str(raw)
    return s.strip().strip('"')


def _file_descriptor_dict(bucket: str, object_name: str, file_size: int) -> Dict[str, Any]:
    """Stable fields for unstructured-files / inventory APIs."""
    return {
        "file_name": os.path.basename(object_name),
        "bucket": bucket,
        "minio_path": f"minio://{bucket}/{object_name}",
        "file_size": int(file_size),
    }


class MinIOReader(BaseDataReader):
    def _validate_config(self) -> None:
        required_keys = ['bucket', 'host', 'access_key', 'secret_key']
        for key in required_keys:
            assert key in self.config, f"Missing {key} configuration"

    def _connect(self) -> Any:

        logger.info(f"connect to minio: {self.config['host']}, access_key={self.config['access_key']}, secret_key={self.config['secret_key']}, bucket={self.config['bucket']}")
        return GeneralMinio(
            host=self.config['host'],
            access_key=self.config['access_key'],
            secret_key=self.config['secret_key']
        )

    def query_one(self, object_name: str, **kwargs) -> List[Document]:
        """
        Download file from MinIO to temporary file and return chunked Documents.

        Each returned Document's metadata includes ``unstructured_file_record``:
        ``file_name``, ``bucket``, ``minio_path``, ``file_size`` (for callers such as
        :meth:`query` to aggregate). On failure, returns ``[]``.

        Parameters:
            object_name: Object name in MinIO (including path)
            kwargs: May include additional parameters such as:
                   - bucket: Override bucket in config
                   - expires: Pre-signed URL expiration time (seconds)
        """
        bucket = kwargs.get('bucket', self.config['bucket'])

        temp_path = ""

        try:
            etag, size = "", 0
            try:
                st = self.client.conn.stat_object(bucket, object_name)
                etag = _normalize_etag(getattr(st, "etag", None) or "")
                size = int(getattr(st, "size", 0) or 0)
            except Exception as stat_err:
                logger.warning(
                    "stat_object failed bucket=%s object=%s: %s", bucket, object_name, stat_err
                )

            data = self.client.conn.get_object(bucket, object_name)
            file_data = data.read()

            filename = os.path.basename(object_name)
            if not size:
                size = len(file_data)

            descriptor = _file_descriptor_dict(bucket, object_name, size)

            suffix = os.path.splitext(filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(file_data)
                temp_path = tmp_file.name

            chunk_size = 1000
            splitter_type = "recursive"

            processor = Processor(
                chunk_size=chunk_size,
                chunk_overlap=chunk_size // 5,
                splitter_type=splitter_type
            )

            result = processor.process_file(temp_path)

            extra_meta: Dict[str, Any] = {
                "name": object_name,
                "minio_object_key": object_name,
                "minio_bucket": bucket,
                "source": f"minio://{bucket}/{object_name}",
                UNSTRUCTURED_FILE_RECORD_KEY: descriptor,
            }
            if etag:
                extra_meta["minio_etag"] = etag
            if size or etag:
                extra_meta["minio_size"] = size

            for doc in result:
                base = dict(doc.metadata) if doc.metadata else {}
                base.update(extra_meta)
                doc.metadata = base

            return result

        except S3Error as e:
            logger.error(f"MinIO error: {e}")
            return []
        except Exception as e:
            logger.error(f"file process error: {e}")
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def query(
        self,
        prefix: str = "",
        recursive: bool = True,
        objects: Optional[List[str]] = None,
        file_analyzer: Any = None,
        **kwargs,
    ) -> Tuple[List[Document], List[Dict[str, Any]], List[Document]]:
        """
        Read all files under bucket (supports filtering).

        Returns:
            (all_documents, file_descriptors, per_file_summaries)
              - ``all_documents``: chunked Documents across all processed files.
              - ``file_descriptors``: one dict per successfully processed object with keys
                ``file_name``, ``bucket``, ``minio_path``, ``file_size``.
              - ``per_file_summaries``: one Document per successfully processed file when
                ``file_analyzer`` is provided. ``page_content`` is the LLM-generated summary
                of that single file (computed from its own chunks only); ``metadata`` includes
                ``file_name``, ``bucket``, ``minio_path``, ``source`` (same as ``minio_path``),
                ``minio_object_key``, and optional ``outline``. Empty list when
                ``file_analyzer`` is None or no file produced a usable summary.

        Parameters:
            prefix: File prefix filter
            recursive: Whether to recursively process subdirectories
            objects: Specify list of objects to query, if provided only these objects will be queried
            file_analyzer: Any object exposing ``file_summary(List[Document]) -> dict`` with
                keys ``summary`` / ``outline`` (e.g. ``extractors.base.FileAnalyzer``). When
                supplied, each file's own chunks are summarized individually here so callers
                can aggregate per-file summaries instead of re-summarizing all raw chunks.
            kwargs: Additional parameters passed to query method
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents: List[Document] = []
        file_descriptors: List[Dict[str, Any]] = []
        per_file_summaries: List[Document] = []

        if objects is not None:
            file_objects = [obj for obj in objects if not obj.endswith('/')]
            logger.info(f"Using specified {len(file_objects)} objects for processing")
        else:
            objects_list = self.client.list_objects(prefix, recursive, bucket)
            logger.info(f"Found {len(objects_list)} objects to process")

            file_objects = [obj for obj in objects_list if not obj.endswith('/')]
            logger.info(f"Remaining {len(file_objects)} files after filtering")

        for i, obj_name in enumerate(file_objects):
            logger.info(f"Processing file {i+1}/{len(file_objects)}: {obj_name}")

            try:
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
                if documents:
                    rec = documents[0].metadata.get(UNSTRUCTURED_FILE_RECORD_KEY)
                    if isinstance(rec, dict) and rec:
                        file_descriptors.append(dict(rec))

                    if file_analyzer is not None:
                        summary_doc = self._summarize_single_file(
                            file_analyzer=file_analyzer,
                            obj_name=obj_name,
                            bucket=bucket,
                            documents=documents,
                        )
                        if summary_doc is not None:
                            per_file_summaries.append(summary_doc)

                logger.info(f"File {obj_name} processing completed, generated {len(documents)} document segments")

            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue

        return all_documents, file_descriptors, per_file_summaries

    @staticmethod
    def _summarize_single_file(
        file_analyzer: Any,
        obj_name: str,
        bucket: str,
        documents: List[Document],
    ) -> Optional[Document]:
        """
        Run ``file_analyzer.file_summary`` over a single file's chunks, then package the
        LLM output as a **richer** per-file summary Document whose ``page_content`` is a
        structured block containing file identity, document type, main themes, summary,
        and outline.

        Why richer than just ``summary``:
          - ``summary`` from ``file_summary`` is typically only 2-4 sentences (per its prompt).
          - Downstream bucket-level synthesis (``extract_minio``) does a second ``file_summary``
            pass over these per-file Documents. If we only carry the terse ``summary`` forward,
            the bucket-level LLM call is effectively summarizing already-heavily-distilled
            sentences, which degrades SD / agent_card / knowledge-graph quality.
          - The exact ``page_content`` string is also what gets persisted into
            ``unstructured_files.file_summary`` via
            :func:`_attach_per_file_summaries_to_descriptors`, so future incremental runs
            reusing stored summaries get the same rich representation (no silent downgrade).

        Returns ``None`` if the LLM call fails or produces no usable content at all.
        """
        try:
            fs_result = file_analyzer.file_summary(documents) or {}
        except Exception as sum_err:
            logger.warning("per-file file_summary failed for %s: %s", obj_name, sum_err)
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

        file_name = os.path.basename(obj_name)
        minio_path = f"minio://{bucket}/{obj_name}"

        sections: List[str] = [f"【文件】{file_name}（{minio_path}）"]
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
            "file_name": file_name,
            "bucket": bucket,
            "minio_path": minio_path,
            "source": minio_path,
            "minio_object_key": obj_name,
            # Keep the raw structured pieces accessible too, so callers that want a specific
            # field (e.g. just the summary) don't have to re-parse page_content.
            "summary": summary_text,
            "outline": outline_text,
            "document_type": doc_type,
            "main_themes": themes,
        }
        logger.info(
            "Generated per-file summary for %s (summary_len=%d outline_len=%d themes=%d type=%s page_content_len=%d)",
            obj_name,
            len(summary_text),
            len(outline_text),
            len(themes),
            doc_type or "-",
            len(page_content),
        )
        return Document(page_content=page_content, metadata=meta)

    def minio_path_to_object_key(self, minio_path: str) -> Optional[str]:
        """Strip ``minio://{bucket}/`` prefix; return object key or None if not matched."""
        bucket = str(self.config.get("bucket") or "")
        prefix = f"minio://{bucket}/"
        s = str(minio_path or "")
        if s.startswith(prefix):
            return s[len(prefix) :]
        return None

    def current_bucket_objects_meta(self) -> Dict[str, Tuple[str, int]]:
        """
        Live bucket view: object_name -> (etag, size). Matches fingerprint listing semantics
        (non-dir objects only).
        """
        bucket = self.config.get("bucket")
        meta: Dict[str, Tuple[str, int]] = {}
        for info in self.client.list_objects_with_info("", True, bucket):
            if info.get("is_dir"):
                continue
            name = str(info.get("object_name") or "")
            if not name or name.endswith("/"):
                continue
            etag = _normalize_etag(info.get("etag"))
            size = int(info.get("size") or 0)
            meta[name] = (etag, size)
        return meta

    def build_file_descriptors_for_bucket(self, dd_namespace: str, dd_name: str) -> List[Dict[str, Any]]:
        """
        One inventory row per bucket object from listing (no file body reads).
        Used for unstructured_files batch upsert and fingerprint object_list_hash context.
        """
        bucket = str(self.config.get("bucket") or "")
        out: List[Dict[str, Any]] = []
        for info in self.client.list_objects_with_info("", True, bucket):
            if info.get("is_dir"):
                continue
            name = str(info.get("object_name") or "")
            if not name or name.endswith("/"):
                continue
            size = int(info.get("size") or 0)
            d = dict(_file_descriptor_dict(bucket, name, size))
            d["dd_namespace"] = str(dd_namespace or "").strip()
            d["dd_name"] = str(dd_name or "").strip()
            out.append(d)
        out.sort(key=lambda x: x.get("minio_path") or "")
        return out

    def has_unstructured_inventory_baseline(self, dd_namespace: str, dd_name: str, uf_client: Any) -> bool:
        """True if data-services has at least one unstructured_files row for this DD."""
        resp = uf_client.list_unstructured_files(
            dd_namespace=dd_namespace, dd_name=dd_name, limit=1, offset=0
        )
        rows = resp.get("data") or []
        return bool(rows)

    def fetch_saved_inventory_object_sizes(self, dd_namespace: str, dd_name: str, uf_client: Any) -> Dict[str, int]:
        """Paginate GET /unstructured-files; map object key -> stored file_size."""
        limit = 500
        offset = 0
        out: Dict[str, int] = {}
        while True:
            resp = uf_client.list_unstructured_files(
                dd_namespace=dd_namespace, dd_name=dd_name, limit=limit, offset=offset
            )
            rows = resp.get("data") or []
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mp = row.get("minio_path")
                mp_str = str(mp or "").strip()
                key = self.minio_path_to_object_key(mp_str)
                if key is None:
                    if mp_str:
                        logger.warning(
                            "%s fetch_saved_inventory skip row id=%s minio_path=%r "
                            "(expected prefix minio://%s/…); row is ignored in diff so bucket deletions may not appear as removed",
                            "[minio_reader]",
                            row.get("id"),
                            mp_str,
                            self.config.get("bucket"),
                        )
                    continue
                out[key] = int(row.get("file_size") or 0)
            if len(rows) < limit:
                break
            offset += limit
        return out

    def fetch_saved_inventory_file_summaries(
        self, dd_namespace: str, dd_name: str, uf_client: Any
    ) -> Dict[str, str]:
        """
        Paginate GET /unstructured-files; return ``minio_path -> file_summary`` for every
        row whose ``file_summary`` is a non-empty string. Used by incremental re-sync to
        rebuild the bucket-level summary from the **full** inventory (persisted per-file
        summaries for unchanged files + freshly-computed summaries for added/modified ones).
        """
        limit = 500
        offset = 0
        out: Dict[str, str] = {}
        while True:
            resp = uf_client.list_unstructured_files(
                dd_namespace=dd_namespace, dd_name=dd_name, limit=limit, offset=offset
            )
            rows = resp.get("data") or []
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mp_str = str(row.get("minio_path") or "").strip()
                if not mp_str:
                    continue
                fs = row.get("file_summary")
                if isinstance(fs, str) and fs.strip():
                    out[mp_str] = fs.strip()
            if len(rows) < limit:
                break
            offset += limit
        logger.info(
            "[minio_reader] feature=fetch_saved_file_summaries dd=%s/%s fetched_with_summary=%d",
            dd_namespace,
            dd_name,
            len(out),
        )
        return out

    def diff_against_saved_inventory(
        self,
        dd_namespace: str,
        dd_name: str,
        uf_client: Any,
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Compare live bucket to last-synced unstructured_files inventory.

        Returns:
            (added, removed, modified) as sets of object names (keys).

        Modification is detected by **file_size** change only (inventory has no etag).
        """
        current = self.current_bucket_objects_meta()
        saved_sizes = self.fetch_saved_inventory_object_sizes(dd_namespace, dd_name, uf_client)
        current_keys = set(current.keys())
        saved_keys = set(saved_sizes.keys())

        # If you delete an object but deleted=[] here, usually either (1) listing still sees the object,
        # or (2) that object was never counted in saved_keys (minio_path did not parse — see fetch warnings).
        logger.info(
            "%s feature=minio_inventory_diff_counts dd_namespace=%r dd_name=%r "
            "current_bucket_objects=%d parsed_inventory_keys=%d",
            "[minio_reader]",
            dd_namespace,
            dd_name,
            len(current_keys),
            len(saved_keys),
        )

        added = current_keys - saved_keys
        removed = saved_keys - current_keys
        modified: Set[str] = set()
        for k in current_keys & saved_keys:
            if current[k][1] != saved_sizes[k]:
                modified.add(k)
        logger.info(
            "%s feature=minio_inventory_diff dd_namespace=%r dd_name=%r bucket=%r "
            "added=%s updated=%s deleted=%s counts_added=%d counts_updated=%d counts_deleted=%d",
            "[minio_reader]",
            dd_namespace,
            dd_name,
            self.config.get("bucket"),
            json.dumps(sorted(added), ensure_ascii=False),
            json.dumps(sorted(modified), ensure_ascii=False),
            json.dumps(sorted(removed), ensure_ascii=False),
            len(added),
            len(modified),
            len(removed),
        )
        return added, removed, modified

    def query_by_extension(self, extensions: List[str], prefix: str = "", recursive: bool = True, **kwargs) -> List[Document]:
        """
        Read files filtered by file extension

        Parameters:
            extensions: File extension list, such as ['.pdf', '.txt']
            prefix: Prefix filter
            recursive: Whether to recurse
            bucket: Specify bucket
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents: List[Document] = []

        objects = self.client.list_objects(prefix, recursive, bucket)

        filtered_objects = [
            obj for obj in objects
            if not obj.endswith('/') and any(obj.lower().endswith(ext.lower()) for ext in extensions)
        ]

        logger.info(f"Found {len(filtered_objects)} files matching extensions {extensions}")

        for obj_name in filtered_objects:
            try:
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue

        return all_documents

    def batch_query(self, object_names: List[str], **kwargs) -> List[Document]:
        """
        Batch process specified file list
        """
        bucket = kwargs.get('bucket', self.config['bucket'])
        all_documents: List[Document] = []

        for obj_name in object_names:
            try:
                documents = self.query_one(obj_name, bucket=bucket, **kwargs)
                all_documents.extend(documents)
            except Exception as e:
                logger.error(f"Error processing file {obj_name}: {e}")
                continue

        return all_documents

    def close(self) -> None:
        """MinIO connection does not require special close handling"""
        pass
