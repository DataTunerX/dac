"""Shared helpers for normalizing DD / data.json source payloads."""

from typing import Any, Dict


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
