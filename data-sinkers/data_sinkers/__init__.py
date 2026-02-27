from .readers.mysql.mysql_reader import MySQLReader
from .readers.postgres.postgres_reader import PostgresReader
from .readers.fileserver.fileserver_reader import FileServerReader
from .readers.minio.minio_reader import MinIOReader
from .readers.code.github_reader import GitHubReader
from .readers.code.gitee_reader import GiteeReader
from .readers.code.gitlab_reader import GitLabReader

def get_reader(source_type: str, config: dict):
    """factory method to get reader"""
    readers = {
        'mysql': MySQLReader,
        'postgres': PostgresReader,
        'fileserver': FileServerReader,
        'minio': MinIOReader,
        'github': GitHubReader,
        'gitee': GiteeReader,
        'gitlab': GitLabReader
    }
    if source_type not in readers:
        raise ValueError(f"data source type not support: {source_type}")
    return readers[source_type](config)