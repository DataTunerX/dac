"""
Unit tests: code-repo fingerprint must be identical for observer vs data-sinker-job
when given the same merged metadata + commit SHA (no network).

Run from repo root `dac/data-sinkers`:
  PYTHONPATH=. python -m unittest data_sinkers.fingerprint.test_code_fingerprint_parity -v
"""
from __future__ import annotations

import unittest
from unittest.mock import patch
from typing import Any, Dict

from data_sinkers.connection_config import DataSourceType, get_connection_config
from data_sinkers.fingerprint.fingerprint import (
    FingerprintBuilder,
    compute_fileserver_object_list_hash,
    compute_minio_object_list_hash,
    fingerprint_id_for_unstructured,
    normalize_code_connection_for_fingerprint,
    resolve_code_commit_sha_for_fingerprint,
)
from data_sinkers.source_helpers import merge_code_repo_into_metadata


def _observer_merge_code_repo(metadata: Dict[str, Any], code_repo: Dict[str, Any]) -> Dict[str, Any]:
    """Mirrors observer.detect_source_change merge (spec.sources[].metadata + codeRepo)."""
    m = dict(metadata or {})
    if isinstance(code_repo, dict):
        m.update(
            {
                "codeRepoPath": code_repo.get("codeRepoPath") or m.get("codeRepoPath"),
                "codeRepoBranch": code_repo.get("codeRepoBranch")
                or m.get("codeRepoBranch", "main"),
                "codeRepoToken": code_repo.get("codeRepoToken") or m.get("codeRepoToken", ""),
            }
        )
    return m


def _observer_code_connection_config(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Mirrors observer._get_connection_config for github/gitee/gitlab."""
    return {
        "codeRepoPath": metadata.get("codeRepoPath", ""),
        "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
        "token": metadata.get("codeRepoToken", ""),
    }


def _fp_id(builder: FingerprintBuilder, data_type: Any, conn: Dict[str, Any], sha: str | None) -> str:
    summary = builder.generate_code_fingerprint_summary(data_type, conn, sha)
    return builder.generate_fingerprint_id(summary)


class TestCodeFingerprintParity(unittest.TestCase):
    """Ensures job + observer paths collapse to one MD5 for equivalent inputs."""

    def setUp(self) -> None:
        self.builder = FingerprintBuilder()

    def test_enum_string_data_type_same_hash(self) -> None:
        conn = {
            "codeRepoPath": "https://gitee.com/org/repo",
            "codeRepoBranch": "main",
            "token": "",
        }
        sha = "deadbeef" * 5
        h_job = _fp_id(self.builder, DataSourceType.GITEE, conn, sha)
        h_obs = _fp_id(self.builder, "gitee", conn, sha)
        self.assertEqual(h_job, h_obs)

    def test_job_connection_config_matches_observer_dict_for_empty_metadata(self) -> None:
        meta: Dict[str, Any] = {}
        job_c = get_connection_config(DataSourceType.GITEE, meta)
        obs_c = _observer_code_connection_config(meta)
        self.assertEqual(job_c, obs_c)

    def test_key_order_and_token_alias_normalize_to_same_id(self) -> None:
        sha = "a" * 40
        c1 = {
            "codeRepoBranch": "dev",
            "codeRepoPath": "https://github.com/x/y",
            "token": "tok",
        }
        c2 = {
            "codeRepoPath": "https://github.com/x/y",
            "codeRepoToken": "tok",
            "codeRepoBranch": "dev",
        }
        h1 = _fp_id(self.builder, "github", c1, sha)
        h2 = _fp_id(self.builder, "github", c2, sha)
        self.assertEqual(h1, h2)

    def test_trailing_slash_on_path_same_id(self) -> None:
        sha = "b" * 40
        a = _fp_id(
            self.builder,
            "gitlab",
            {
                "codeRepoPath": "https://gitlab.com/a/b",
                "codeRepoBranch": "main",
                "token": "",
            },
            sha,
        )
        b = _fp_id(
            self.builder,
            "gitlab",
            {
                "codeRepoPath": "https://gitlab.com/a/b/",
                "codeRepoBranch": "main",
                "token": "",
            },
            sha,
        )
        self.assertEqual(a, b)

    def test_merge_metadata_observer_vs_helpers_same_hash(self) -> None:
        metadata = {"codeRepoBranch": "feat", "codeRepoToken": "t"}
        code_repo: Dict[str, Any] = {"codeRepoPath": "https://gitee.com/o/r"}
        m_obs = _observer_merge_code_repo(metadata, code_repo)
        m_job = merge_code_repo_into_metadata(metadata, code_repo)
        self.assertEqual(m_obs, m_job)
        sha = "c" * 40
        h_obs = _fp_id(
            self.builder, "gitee", _observer_code_connection_config(m_obs), sha
        )
        h_job = _fp_id(
            self.builder,
            DataSourceType.GITEE,
            get_connection_config(DataSourceType.GITEE, m_job),
            sha,
        )
        self.assertEqual(h_obs, h_job)

    def test_commit_sha_omitted_both_ways_same_id(self) -> None:
        conn = {
            "codeRepoPath": "https://gitee.com/o/r",
            "codeRepoBranch": "main",
            "token": "",
        }
        h1 = _fp_id(self.builder, DataSourceType.GITEE, conn, None)
        h2 = _fp_id(self.builder, "gitee", conn, None)
        self.assertEqual(h1, h2)

    def test_sort_keys_stable_across_calls(self) -> None:
        """Same inputs must yield identical summary string every time."""
        conn = {
            "codeRepoPath": "https://gitee.com/o/r",
            "codeRepoBranch": "main",
            "token": "x",
        }
        s1 = self.builder.generate_code_fingerprint_summary(
            "gitee", conn, "d" * 40
        )
        s2 = self.builder.generate_code_fingerprint_summary(
            "gitee", conn, "d" * 40
        )
        self.assertEqual(s1, s2)
        # Top-level keys alphabetical: commit_sha, connection_information, data_type
        self.assertLess(s1.index('"commit_sha"'), s1.index('"connection_information"'))
        self.assertLess(s1.index('"connection_information"'), s1.index('"data_type"'))

    def test_normalize_function_matches_embedded_summary_shape(self) -> None:
        raw = {"codeRepoPath": "  https://x/y  ", "codeRepoBranch": "  main ", "codeRepoToken": ""}
        norm = normalize_code_connection_for_fingerprint(raw)
        self.assertEqual(
            norm,
            {
                "codeRepoBranch": "main",
                "codeRepoPath": "https://x/y",
                "token": "",
            },
        )

    def test_resolve_commit_remote_wins(self) -> None:
        with patch(
            "data_sinkers.fingerprint.fingerprint.get_remote_commit_sha",
            return_value="remote111",
        ):
            r = resolve_code_commit_sha_for_fingerprint(
                "https://gitee.com/a/b",
                "main",
                None,
                resolved_head_sha="local222",
                stored_commit_sha="stored333",
            )
        self.assertEqual(r, "remote111")

    def test_resolve_commit_fallback_chain(self) -> None:
        with patch(
            "data_sinkers.fingerprint.fingerprint.get_remote_commit_sha",
            return_value=None,
        ):
            r = resolve_code_commit_sha_for_fingerprint(
                "u", "main", None, resolved_head_sha="local222", stored_commit_sha="stored333"
            )
        self.assertEqual(r, "local222")
        with patch(
            "data_sinkers.fingerprint.fingerprint.get_remote_commit_sha",
            return_value=None,
        ):
            r2 = resolve_code_commit_sha_for_fingerprint(
                "u", "main", None, resolved_head_sha=None, stored_commit_sha="stored333"
            )
        self.assertEqual(r2, "stored333")

    def test_observer_job_same_id_when_remote_fails_shared_stored_sha(self) -> None:
        """After sync, metadata code_commit_sha matches resolved_head used by job; observer uses stored when ls-remote fails."""
        conn = {
            "codeRepoPath": "https://gitee.com/o/r",
            "codeRepoBranch": "main",
            "token": "",
        }
        head = "f" * 40
        with patch(
            "data_sinkers.fingerprint.fingerprint.get_remote_commit_sha",
            return_value=None,
        ):
            job_sha = resolve_code_commit_sha_for_fingerprint(
                conn["codeRepoPath"], conn["codeRepoBranch"], None,
                resolved_head_sha=head, stored_commit_sha=None,
            )
            obs_sha = resolve_code_commit_sha_for_fingerprint(
                conn["codeRepoPath"], conn["codeRepoBranch"], None,
                resolved_head_sha=None, stored_commit_sha=head,
            )
        self.assertEqual(job_sha, obs_sha)
        h1 = _fp_id(self.builder, "gitee", conn, job_sha)
        h2 = _fp_id(self.builder, DataSourceType.GITEE, conn, obs_sha)
        self.assertEqual(h1, h2)


class _FakeStat:
    __slots__ = ("etag", "size")

    def __init__(self, etag: str = "", size: int = 0) -> None:
        self.etag = etag
        self.size = size


class _FakeMinioConn:
    def stat_object(self, bucket: str, name: str):
        if name == "missing":
            raise RuntimeError("no object")
        return _FakeStat(f"etag-{name}", len(name))


class TestUnstructuredFingerprintShared(unittest.TestCase):
    """Observer, extractors, and job must share compute_* + fingerprint_id_for_unstructured."""

    def test_minio_hash_and_id_match_direct_builder(self) -> None:
        conn = {
            "host": "h",
            "access_key": "a",
            "secret_key": "s",
            "bucket": "bkt",
            "secure": False,
        }
        files = ["z", "a"]
        h = compute_minio_object_list_hash("bkt", files, _FakeMinioConn())
        self.assertIsNotNone(h)
        fid_shared = fingerprint_id_for_unstructured(DataSourceType.MINIO, conn, h)
        b = FingerprintBuilder()
        fid_direct = b.generate_fingerprint_id(
            b.generate_object_list_fingerprint_summary("minio", conn, h)
        )
        self.assertEqual(fid_shared, fid_direct)

    def test_fileserver_hash_matches_observer_payload(self) -> None:
        conn = {"host": "localhost", "port": 8000}
        files = ["b", "a"]
        h = compute_fileserver_object_list_hash(conn, files)
        self.assertIsNotNone(h)
        fid = fingerprint_id_for_unstructured("fileserver", conn, h)
        b = FingerprintBuilder()
        self.assertEqual(
            fid,
            b.generate_fingerprint_id(
                b.generate_object_list_fingerprint_summary(
                    DataSourceType.FILESERVER, conn, h
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
