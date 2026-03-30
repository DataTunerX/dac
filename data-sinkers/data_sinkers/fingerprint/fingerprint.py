import hashlib
import json
import logging
import subprocess
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


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
        summary: Dict[str, Any] = {
            "data_type": data_type,
            "connection_information": connection_info,
        }
        if commit_sha:
            summary["commit_sha"] = commit_sha
        return json.dumps(summary, ensure_ascii=False, indent=4)

    def generate_object_list_fingerprint_summary(
        self,
        data_type: str,
        connection_info: Dict[str, Any],
        object_list_hash: Optional[str] = None,
    ) -> str:
        """
        Generate fingerprint summary for MinIO/Fileserver.
        object_list_hash: hash of (path, etag/size) for each object.
        """
        summary: Dict[str, Any] = {
            "data_type": data_type,
            "connection_information": connection_info,
        }
        if object_list_hash:
            summary["object_list_hash"] = object_list_hash
        return json.dumps(summary, ensure_ascii=False, indent=4)
    
    