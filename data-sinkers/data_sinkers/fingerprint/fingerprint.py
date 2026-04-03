import hashlib
import json
import logging
import subprocess
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Persisted on signature.metadata_content so observer can resolve the same commit_sha as job when ls-remote fails.
CODE_COMMIT_SHA_METADATA_KEY = "code_commit_sha"


def normalize_code_connection_for_fingerprint(connection_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Single canonical shape for code fingerprints. Observer and job must embed the same
    connection_information JSON (whitespace + key order stable via sort_keys on dumps).
    """
    path = (connection_info.get("codeRepoPath") or "").strip().rstrip("/")
    branch = (connection_info.get("codeRepoBranch") or "main").strip() or "main"
    token = (connection_info.get("token") or connection_info.get("codeRepoToken") or "") or ""
    return {
        "codeRepoBranch": branch,
        "codeRepoPath": path,
        "token": token,
    }


def get_remote_commit_sha(repo_url: str, branch: str = "main", token: Optional[str] = None) -> Optional[str]:
    """
    Get latest commit SHA of remote branch via git ls-remote (lightweight, no clone).
    Returns None on failure.
    """
    url = repo_url.rstrip("/")
    if url.endswith(".git"):
        url = url
    elif "/" in url:
        url = url + ".git"
    # For private repos: https://token@host/path
    if token and "@" not in url:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            url = f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"
    ref = f"refs/heads/{branch}" if branch else "HEAD"
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, ref],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.debug("git ls-remote failed: %s", result.stderr)
            return None
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) >= 1:
                return parts[0]
    except Exception as e:
        logger.warning("get_remote_commit_sha failed: %s", e)
    return None


def _strip_commit_sha(sha: Optional[str]) -> Optional[str]:
    if sha is None:
        return None
    if not isinstance(sha, str):
        return None
    s = sha.strip()
    return s or None


def resolve_code_commit_sha_for_fingerprint(
    repo_url: str,
    branch: str = "main",
    token: Optional[str] = None,
    *,
    resolved_head_sha: Optional[str] = None,
    stored_commit_sha: Optional[str] = None,
) -> Optional[str]:
    """
    Single resolution order for code-repo fingerprints. Observer and job must use this
    so the embedded commit_sha (and thus MD5) always match.

    1. git ls-remote (same as observer historically used alone).
    2. Local clone HEAD after extract (job only; observer passes None).
    3. Last synced value from signature.metadata_content[CODE_COMMIT_SHA_METADATA_KEY] (observer when ls-remote fails).

    When all are absent, returns None (summary omits commit_sha on both sides).
    """
    remote = _strip_commit_sha(get_remote_commit_sha(repo_url, branch, token))
    if remote:
        return remote
    local = _strip_commit_sha(resolved_head_sha)
    if local:
        return local
    return _strip_commit_sha(stored_commit_sha)


def _coerce_data_type_for_summary(data_type: Any) -> str:
    if hasattr(data_type, "value"):
        return str(data_type.value)
    return str(data_type)


def compute_fileserver_object_list_hash(
    connection_config: Dict[str, Any],
    extract_files: List[str],
) -> Optional[str]:
    """
    Single implementation for fileserver object_list_hash — observer and extractors must call this only.
    """
    try:
        payload = {
            "host": connection_config.get("host"),
            "port": connection_config.get("port"),
            "files": sorted(extract_files) if isinstance(extract_files, list) else [],
        }
        return hashlib.md5(json.dumps(payload).encode()).hexdigest()
    except Exception as e:
        logger.warning("compute_fileserver_object_list_hash failed: %s", e)
        return None


def compute_minio_object_list_hash(
    bucket: str,
    object_names: List[str],
    minio_client: Any,
) -> Optional[str]:
    """
    Hash a fixed list of object paths via ``stat_object`` (legacy / tests).

    For production MinIO sync, use ``compute_minio_bucket_object_list_hash`` so the fingerprint
    matches all objects in the bucket; ``extract.files`` is not used.
    """
    try:
        items = []
        for obj_name in object_names or []:
            try:
                stat = minio_client.stat_object(bucket, obj_name)
                items.append((obj_name, stat.etag or "", stat.size))
            except Exception:
                items.append((obj_name, "", 0))
        items.sort(key=lambda x: x[0])
        return hashlib.md5(json.dumps(items).encode()).hexdigest()
    except Exception as e:
        logger.warning("compute_minio_object_list_hash failed: %s", e)
        return None


def compute_minio_bucket_object_list_hash(
    bucket: str,
    minio_client: Any,
) -> Optional[str]:
    """
    MinIO object_list_hash over all objects in the bucket (full bucket; no prefix filter).

    Uses ``list_objects`` (path, etag, size) so job and observer agree; ``extract.files`` ignored.
    minio_client: ``minio.Minio`` (e.g. ``GeneralMinio.conn``).
    """
    try:
        items: List[tuple] = []
        for obj in minio_client.list_objects(bucket, prefix="", recursive=True):
            if getattr(obj, "is_dir", False):
                continue
            name = getattr(obj, "object_name", "") or ""
            if name.endswith("/"):
                continue
            etag = getattr(obj, "etag", None) or ""
            size = int(getattr(obj, "size", 0) or 0)
            items.append((name, etag, size))
        items.sort(key=lambda x: x[0])
        return hashlib.md5(json.dumps(items).encode()).hexdigest()
    except Exception as e:
        logger.warning("compute_minio_bucket_object_list_hash failed: %s", e)
        return None


def fingerprint_id_for_unstructured(
    data_type: Any,
    connection_config: Dict[str, Any],
    object_list_hash: Optional[str],
) -> str:
    """
    MD5 id for MinIO / fileserver — one code path for job and observer.
    """
    b = FingerprintBuilder()
    summary = b.generate_object_list_fingerprint_summary(
        data_type, connection_config, object_list_hash
    )
    return b.generate_fingerprint_id(summary)


class FingerprintBuilder:
    
    def generate_fingerprint_id(self, summary: str) -> str:
        """
        Generate fingerprint ID using MD5 hash
        
        Args:
            summary: Summary text
            
        Returns:
            MD5 hash value as fingerprint ID
        """
        return hashlib.md5(summary.encode()).hexdigest()


    def generate_db_fingerprint_summary(
        self,
        data_type: str,
        tables_schema_md_list: List[Any],
    ) -> str:
        """
        Generate fingerprint summary for database sources.
        Schema (DDL / structure) only — row counts are not part of the fingerprint.
        """
        summary: Dict[str, Any] = {
            "data_type": data_type,
            "tables_schema": tables_schema_md_list,
        }
        return json.dumps(summary, ensure_ascii=False, indent=4)

    def generate_code_fingerprint_summary(
        self,
        data_type: str,
        connection_info: Dict[str, Any],
        commit_sha: Optional[str] = None,
    ) -> str:
        """
        Generate fingerprint summary for code repo sources.
        Includes connection_information and optional commit_sha for change detection.
        """
        if hasattr(data_type, "value"):
            dt = str(data_type.value)
        else:
            dt = str(data_type)
        norm = normalize_code_connection_for_fingerprint(connection_info)
        summary: Dict[str, Any] = {
            "connection_information": norm,
            "data_type": dt,
        }
        if commit_sha:
            summary["commit_sha"] = commit_sha
        return json.dumps(summary, ensure_ascii=False, indent=4, sort_keys=True)

    def generate_object_list_fingerprint_summary(
        self,
        data_type: Any,
        connection_info: Dict[str, Any],
        object_list_hash: Optional[str] = None,
    ) -> str:
        """
        Generate fingerprint summary for MinIO/Fileserver.
        object_list_hash: hash of (path, etag/size) for each object.
        """
        dt = _coerce_data_type_for_summary(data_type)
        summary: Dict[str, Any] = {
            "data_type": dt,
            "connection_information": connection_info,
        }
        if object_list_hash:
            summary["object_list_hash"] = object_list_hash
        return json.dumps(summary, ensure_ascii=False, indent=4)
    
    