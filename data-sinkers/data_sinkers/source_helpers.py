"""Shared helpers for normalizing DD / data.json source payloads."""

from typing import Any, Dict, Optional


def merge_code_repo_into_metadata(metadata: Dict[str, Any], code_repo: Any) -> Dict[str, Any]:
    """
    Match DataDescriptor + observer behaviour: spec.sources[].codeRepo is merged into
    metadata before building connection config. Observer does this in detect_source_change;
    job previously used only source.metadata for get_connection_config, so
    generate_code_fingerprint_summary embedded a different connection_information than the
    observer — same commit_sha but perpetual Fingerprint changed / resync loops.
    """
    m = dict(metadata or {})
    if isinstance(code_repo, dict):
        m.update({
            "codeRepoPath": code_repo.get("codeRepoPath") or m.get("codeRepoPath"),
            "codeRepoBranch": code_repo.get("codeRepoBranch") or m.get("codeRepoBranch", "main"),
            "codeRepoToken": code_repo.get("codeRepoToken") or m.get("codeRepoToken", ""),
        })
    return m


def coerce_semantic_domain_text(fingerprint_associated_info: Dict[str, Any]) -> Optional[str]:
    """
    Normalize DDD text used for semantic_domain PUT and knowledge-graph extraction.

    - ``ddd`` should be a string; postgres historically set it to a dict (full ddd result).
    - If ``ddd`` is missing/empty but ``db_ddd`` / ``code_ddd`` exist, use those.
    """
    raw = (fingerprint_associated_info or {}).get("ddd")
    if isinstance(raw, dict):
        raw = raw.get("summary")
    if raw is not None:
        s = raw if isinstance(raw, str) else str(raw)
        if s.strip():
            return s
    for key in ("db_ddd", "code_ddd"):
        fb = (fingerprint_associated_info or {}).get(key)
        if fb is not None:
            s = fb if isinstance(fb, str) else str(fb)
            if s.strip():
                return s
    return None
