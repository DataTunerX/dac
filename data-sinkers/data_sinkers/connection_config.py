"""Lightweight source connection shapes; safe to import without clients or extractors."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class DataSourceType(str, Enum):
    MYSQL = "mysql"
    MINIO = "minio"
    POSTGRESQL = "postgres"
    FILESERVER = "fileserver"
    GITHUB = "github"
    GITEE = "gitee"
    GITLAB = "gitlab"


def get_connection_config(source_type: DataSourceType, metadata: Dict[str, Any]) -> Dict[str, Any]:
    config_map = {
        DataSourceType.MYSQL: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 3306),
            "user": metadata.get("user", "root"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", ""),
        },
        DataSourceType.POSTGRESQL: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 5432),
            "user": metadata.get("user", "postgres"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", "postgres"),
        },
        DataSourceType.MINIO: {
            "host": metadata.get("host", "localhost:9000"),
            "access_key": metadata.get("access_key", ""),
            "secret_key": metadata.get("secret_key", ""),
            "bucket": metadata.get("bucket", ""),
            "secure": metadata.get("secure", False),
        },
        DataSourceType.FILESERVER: {
            "host": metadata.get("host", "localhost"),
            "port": metadata.get("port", 8000),
        },
        # codeRepoPath default "" must match observer._get_connection_config (avoid job-only URLs).
        DataSourceType.GITHUB: {
            "codeRepoPath": metadata.get("codeRepoPath", ""),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        },
        DataSourceType.GITEE: {
            "codeRepoPath": metadata.get("codeRepoPath", ""),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        },
        DataSourceType.GITLAB: {
            "codeRepoPath": metadata.get("codeRepoPath", ""),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        },
    }
    return config_map.get(source_type, {})
