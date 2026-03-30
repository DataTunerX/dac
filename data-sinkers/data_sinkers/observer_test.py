"""
DD Sync Observer - 全功能点模拟测试（本文件 37 场景）

更深边界与 K8s 注入等见 observer_deep_test.py（另 62 场景，与本文合计 99）。
与实现计划文档对齐的契约测试见 observer_plan_contract_test.py（Signature by-dd、main sleep、run_cycle Client 等）。

测试场景覆盖：
1. _parse_schedule - 各类间隔格式
2. _get_connection_config - 各 source type 的 connection 构建
3. _detect_*_change - MySQL/Postgres/Code/MinIO/Fileserver 变更检测（mock）
4. detect_source_change - Signature 拉取、响应格式、source 路由
5. run_cycle - 完整周期（mock K8s + Signature API）
6. fingerprint 一致性 - Observer 与 data-sinker 指纹算法一致（DB 仅表结构）
"""
import hashlib
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from data_sinkers.observer import (
    _parse_schedule,
    _get_connection_config,
    SYNC_REQUESTED_AT_ANNOTATION,
    detect_source_change,
    run_cycle,
)
from data_sinkers.fingerprint.fingerprint import (
    FingerprintBuilder,
    get_remote_commit_sha,
)


# ============= 1. _parse_schedule =============
class TestParseSchedule:
    def test_seconds(self):
        assert _parse_schedule("60") == 60
        assert _parse_schedule("3600") == 3600

    def test_hours(self):
        assert _parse_schedule("6h") == 6 * 3600
        assert _parse_schedule("1h") == 3600

    def test_minutes(self):
        assert _parse_schedule("30m") == 30 * 60
        assert _parse_schedule("5m") == 300

    def test_default(self):
        assert _parse_schedule("") == 6 * 3600
        assert _parse_schedule("  ") == 6 * 3600

    def test_invalid_fallback(self):
        assert _parse_schedule("x") == 6 * 3600

    def test_plain_number_as_seconds(self):
        assert _parse_schedule("120") == 120


# ============= 2. _get_connection_config =============
class TestGetConnectionConfig:
    def test_mysql(self):
        cfg = _get_connection_config("mysql", {"host": "db1", "database": "mydb"})
        assert cfg["host"] == "db1"
        assert cfg["port"] == 3306
        assert cfg["database"] == "mydb"
        assert cfg["user"] == "root"

    def test_postgres(self):
        cfg = _get_connection_config("postgres", {"port": "5433"})
        assert cfg["port"] == 5433
        assert cfg["user"] == "postgres"

    def test_github(self):
        cfg = _get_connection_config("github", {"codeRepoPath": "https://github.com/a/b"})
        assert cfg["codeRepoPath"] == "https://github.com/a/b"
        assert cfg["codeRepoBranch"] == "main"

    def test_gitee(self):
        cfg = _get_connection_config("gitee", {"codeRepoPath": "https://gitee.com/a/b"})
        assert cfg["codeRepoPath"] == "https://gitee.com/a/b"

    def test_gitlab(self):
        cfg = _get_connection_config("gitlab", {})
        assert "codeRepoPath" in cfg
        assert cfg["codeRepoBranch"] == "main"

    def test_minio(self):
        cfg = _get_connection_config("minio", {"bucket": "mybucket", "host": "minio:9000"})
        assert cfg["bucket"] == "mybucket"
        assert cfg["host"] == "minio:9000"

    def test_fileserver(self):
        cfg = _get_connection_config("fileserver", metadata={"host": "fs", "port": 8080})
        assert cfg.get("host") == "fs" or "host" in cfg


# ============= 3. Fingerprint 模块 =============
class TestFingerprintBuilder:
    def test_db_fingerprint_without_row_counts(self):
        b = FingerprintBuilder()
        s = b.generate_db_fingerprint_summary("mysql", [{"table_name": "t1"}])
        assert "data_type" in s
        assert "tables_schema" in s
        assert "table_row_counts" not in s
        h = b.generate_fingerprint_id(s)
        assert len(h) == 32

    def test_db_fingerprint_schema_change_changes_hash(self):
        b = FingerprintBuilder()
        s = b.generate_db_fingerprint_summary("mysql", [{"a": 1}])
        s2 = b.generate_db_fingerprint_summary("mysql", [{"a": 2}])
        assert b.generate_fingerprint_id(s) != b.generate_fingerprint_id(s2)

    def test_code_fingerprint_without_commit_sha(self):
        b = FingerprintBuilder()
        s = b.generate_code_fingerprint_summary("github", {"codeRepoPath": "x", "codeRepoBranch": "main"})
        assert "connection_information" in s
        assert "commit_sha" not in s

    def test_code_fingerprint_with_commit_sha(self):
        b = FingerprintBuilder()
        s = b.generate_code_fingerprint_summary("github", {"path": "x"}, "abc123")
        assert "commit_sha" in s
        assert "abc123" in s

    def test_object_list_fingerprint(self):
        b = FingerprintBuilder()
        s = b.generate_object_list_fingerprint_summary("minio", {"bucket": "b"}, "hash1")
        assert "object_list_hash" in s
        assert "hash1" in s


class TestGetRemoteCommitSha:
    def test_invalid_url_returns_none(self):
        r = get_remote_commit_sha("https://invalid-not-exist-xyz.local/repo.git", "main")
        assert r is None

    def test_empty_url_returns_none(self):
        with patch("subprocess.run") as m:
            m.side_effect = Exception("no git")
            r = get_remote_commit_sha("", "main")
        assert r is None


# ============= 4. detect_source_change - 路由与 Signature 响应 =============
class TestDetectSourceChange:
    def test_mysql_no_signature_no_change(self):
        with patch("data_sinkers.observer._detect_mysql_change", return_value=False):
            mock_client = MagicMock()
            mock_client.search_signatures_by_dd.return_value = {"data": [], "count": 0}
            source = {"type": "mysql", "name": "m1", "metadata": {}, "extract": {"tables": []}}
            result = detect_source_change("ns", "dd", source, mock_client)
        assert result is False

    def test_code_merge_code_repo(self):
        mock_client = MagicMock()
        mock_client.search_signatures_by_dd.return_value = {
            "data": [{"fingerprint": "abc123"}],
            "count": 1,
        }
        source = {
            "type": "github",
            "name": "g1",
            "metadata": {},
            "codeRepo": {
                "codeRepoPath": "https://github.com/foo/bar",
                "codeRepoBranch": "main",
                "codeRepoToken": "",
            },
        }
        with patch("data_sinkers.observer._detect_code_change") as mock_detect:
            mock_detect.return_value = False
            detect_source_change("ns", "dd", source, mock_client)
            mock_detect.assert_called_once()
            call_args = mock_detect.call_args[0]
            assert call_args[0] == "github"
            conn = call_args[1]
            assert conn.get("codeRepoPath") == "https://github.com/foo/bar"

    def test_postgres_routing(self):
        mock_client = MagicMock()
        mock_client.search_signatures_by_dd.return_value = {"data": [{"fingerprint": "f1"}], "count": 1}
        source = {"type": "postgres", "metadata": {}, "extract": {"tables": ["t1"]}}
        with patch("data_sinkers.observer._detect_postgres_change") as m:
            m.return_value = False
            detect_source_change("ns", "dd", source, mock_client)
            m.assert_called_once()
            assert m.call_args[0][1] == ["t1"]

    def test_minio_routing_with_files(self):
        mock_client = MagicMock()
        mock_client.search_signatures_by_dd.return_value = {"data": [{"fingerprint": "f1"}], "count": 1}
        source = {"type": "minio", "metadata": {"bucket": "b"}, "extract": {"files": ["a.pdf", "b.pdf"]}}
        with patch("data_sinkers.observer._detect_minio_change") as m:
            m.return_value = False
            detect_source_change("ns", "dd", source, mock_client)
            m.assert_called_once()
            assert m.call_args[0][1] == ["a.pdf", "b.pdf"]

    def test_fileserver_changed_detected(self):
        """Fileserver 无外部依赖，可直接测试指纹变化检测"""
        mock_client = MagicMock()
        source = {
            "type": "fileserver",
            "metadata": {"host": "localhost", "port": 8000},
            "extract": {"files": ["a.pdf"]},
        }
        metadata = dict(source.get("metadata") or {})
        code_repo = source.get("codeRepo") or {}
        metadata.update({
            "codeRepoPath": code_repo.get("codeRepoPath") or metadata.get("codeRepoPath"),
            "codeRepoBranch": code_repo.get("codeRepoBranch") or metadata.get("codeRepoBranch", "main"),
            "codeRepoToken": code_repo.get("codeRepoToken") or metadata.get("codeRepoToken", ""),
        })
        conn = _get_connection_config("fileserver", metadata)
        b = FingerprintBuilder()
        payload = {"host": conn.get("host"), "port": conn.get("port"), "files": ["a.pdf"]}
        obj_hash = hashlib.md5(json.dumps(payload).encode()).hexdigest()
        s = b.generate_object_list_fingerprint_summary("fileserver", conn, obj_hash)
        stored_hash = b.generate_fingerprint_id(s)

        mock_client.search_signatures_by_dd.return_value = {"data": [{"fingerprint": stored_hash}], "count": 1}
        result = detect_source_change("ns", "dd", source, mock_client)
        assert result is False  # 相同指纹

        # 不同指纹 -> change
        mock_client.search_signatures_by_dd.return_value = {"data": [{"fingerprint": "wrong_hash"}], "count": 1}
        result = detect_source_change("ns", "dd", source, mock_client)
        assert result is True

    def test_signature_api_response_formats(self):
        """兼容 data / records 等多种响应格式"""
        mock_client = MagicMock()
        source = {"type": "fileserver", "metadata": {"host": "h", "port": 8000}, "extract": {"files": []}}
        metadata = dict(source.get("metadata") or {})
        code_repo = source.get("codeRepo") or {}
        metadata.update({
            "codeRepoPath": code_repo.get("codeRepoPath") or metadata.get("codeRepoPath"),
            "codeRepoBranch": code_repo.get("codeRepoBranch") or metadata.get("codeRepoBranch", "main"),
            "codeRepoToken": code_repo.get("codeRepoToken") or metadata.get("codeRepoToken", ""),
        })
        conn = _get_connection_config("fileserver", metadata)
        b = FingerprintBuilder()
        payload = {"host": conn.get("host"), "port": conn.get("port"), "files": []}
        obj_hash = hashlib.md5(json.dumps(payload).encode()).hexdigest()
        s = b.generate_object_list_fingerprint_summary("fileserver", conn, obj_hash)
        h = b.generate_fingerprint_id(s)

        for resp_format in [
            {"data": [{"fingerprint": h}]},
            {"records": [{"fingerprint": h}]},
        ]:
            mock_client.search_signatures_by_dd.return_value = resp_format
            result = detect_source_change("ns", "dd", source, mock_client)
            assert result is False


# ============= 5. run_cycle =============
class TestRunCycle:
    _dd_desc = "ns_dd"

    def test_no_dd_skips(self):
        with patch("data_sinkers.observer._get_dd_via_http", return_value=None):
            assert run_cycle("ns", "dd", "http://localhost:8000", self._dd_desc) is False

    def test_no_sources_skips(self):
        with patch(
            "data_sinkers.observer._get_dd_via_http",
            return_value={"spec": {"sources": []}},
        ):
            assert run_cycle("ns", "dd", "http://localhost:8000", self._dd_desc) is False

    def test_change_triggers_patch(self):
        dd = {"spec": {"sources": [{"type": "fileserver", "metadata": {"host": "h", "port": 8000}, "extract": {"files": []}}]}}
        with patch("data_sinkers.observer._get_dd_via_http", return_value=dd):
            with patch("data_sinkers.observer.detect_source_change", return_value=True):
                with patch(
                    "data_sinkers.observer._patch_dd_annotation_via_http",
                    return_value=True,
                ) as mock_patch:
                    result = run_cycle("ns", "dd", "http://localhost:8000", self._dd_desc)
        assert result is True
        mock_patch.assert_called_once()
        args = mock_patch.call_args[0]
        assert args[0] == "http://localhost:8000"
        assert args[1] == "ns"
        assert args[2] == "dd"
        assert args[3] == self._dd_desc
        assert args[4] == SYNC_REQUESTED_AT_ANNOTATION
        assert "T" in args[5] and "Z" in args[5]

    def test_no_change_no_patch(self):
        dd = {"spec": {"sources": [{"type": "mysql", "metadata": {}, "extract": {}}]}}
        with patch("data_sinkers.observer._get_dd_via_http", return_value=dd):
            with patch("data_sinkers.observer.detect_source_change", return_value=False):
                with patch("data_sinkers.observer._patch_dd_annotation_via_http") as mock_patch:
                    result = run_cycle("ns", "dd", "http://localhost:8000", self._dd_desc)
        assert result is False
        mock_patch.assert_not_called()


# ============= 6. _detect_* 变更检测逻辑（mock 底层） =============
class TestDetectMySQLChange:
    def test_no_stored_fingerprint_returns_false(self):
        from data_sinkers.observer import _detect_mysql_change
        with patch("data_sinkers.readers.mysql.mysql_reader.MySQLReader") as MockReader:
            mock_reader = MagicMock()
            mock_reader.schema.return_value = [{"table_name": "t1", "columns": []}]
            mock_reader.close = MagicMock()
            MockReader.return_value = mock_reader
            with patch("data_sinkers.prompts.mysql.format_schema_to_markdown_with_all_tables", return_value=[]):
                result = _detect_mysql_change({"host": "h", "user": "u", "password": "p", "database": "d"}, [], None)
        assert result is False

    def test_same_fingerprint_returns_false(self):
        from data_sinkers.observer import _detect_mysql_change
        b = FingerprintBuilder()
        schema_md = [{"table_name": "t1", "table_schema": "x"}]
        s = b.generate_db_fingerprint_summary("mysql", schema_md)
        h = b.generate_fingerprint_id(s)
        with patch("data_sinkers.readers.mysql.mysql_reader.MySQLReader") as MockReader:
            mock_reader = MagicMock()
            mock_reader.schema.return_value = [{"table_name": "t1", "columns": []}]
            mock_reader.close = MagicMock()
            MockReader.return_value = mock_reader
            with patch("data_sinkers.prompts.mysql.format_schema_to_markdown_with_all_tables", return_value=schema_md):
                result = _detect_mysql_change({"host": "h", "user": "u", "password": "p", "database": "d"}, ["t1"], h)
        assert result is False


class TestDetectCodeChange:
    def test_commit_sha_in_fingerprint(self):
        from data_sinkers.observer import _detect_code_change
        with patch("data_sinkers.observer.get_remote_commit_sha", return_value="abc123"):
            b = FingerprintBuilder()
            conn = {"codeRepoPath": "https://github.com/a/b", "codeRepoBranch": "main"}
            s = b.generate_code_fingerprint_summary("github", conn, "abc123")
            stored = b.generate_fingerprint_id(s)
            result = _detect_code_change("github", conn, stored)
        assert result is False

    def test_different_commit_triggers_change(self):
        from data_sinkers.observer import _detect_code_change
        with patch("data_sinkers.observer.get_remote_commit_sha", return_value="newsha"):
            conn = {"codeRepoPath": "x", "codeRepoBranch": "main"}
            # stored 是旧 commit 的 hash
            b = FingerprintBuilder()
            s_old = b.generate_code_fingerprint_summary("github", conn, "oldsha")
            stored = b.generate_fingerprint_id(s_old)
            result = _detect_code_change("github", conn, stored)
        assert result is True


class TestDetectFileserverChange:
    def test_same_config_same_files_no_change(self):
        from data_sinkers.observer import _detect_fileserver_change
        b = FingerprintBuilder()
        conn = {"host": "h", "port": 8000}
        payload = {"host": "h", "port": 8000, "files": ["a.pdf"]}
        obj_hash = hashlib.md5(json.dumps(payload).encode()).hexdigest()
        s = b.generate_object_list_fingerprint_summary("fileserver", conn, obj_hash)
        stored = b.generate_fingerprint_id(s)
        result = _detect_fileserver_change(conn, ["a.pdf"], stored)
        assert result is False

    def test_files_list_changed_triggers_change(self):
        from data_sinkers.observer import _detect_fileserver_change
        b = FingerprintBuilder()
        conn = {"host": "h", "port": 8000}
        payload = {"host": "h", "port": 8000, "files": ["a.pdf"]}
        obj_hash = hashlib.md5(json.dumps(payload).encode()).hexdigest()
        s = b.generate_object_list_fingerprint_summary("fileserver", conn, obj_hash)
        stored = b.generate_fingerprint_id(s)
        result = _detect_fileserver_change(conn, ["a.pdf", "b.pdf"], stored)
        assert result is True


# ============= 7. main 入口验证 =============
class TestMain:
    def test_missing_env_exits(self):
        with patch.dict(os.environ, {"DD_NAMESPACE": "", "DD_NAME": ""}, clear=False):
            with pytest.raises(SystemExit):
                import data_sinkers.observer as obs
                obs.main()
