from .readers.mysql.mysql_reader import MySQLReader
from .readers.postgres.postgres_reader import PostgresReader
from .readers.fileserver.fileserver_reader import FileServerReader
from .readers.minio.minio_reader import MinIOReader

def get_reader(source_type: str, config: dict):
    """factory method to get reader"""
    readers = {
        'mysql': MySQLReader,
        'postgres': PostgresReader,
        'fileserver': FileServerReader,
        'minio': MinIOReader
    }
    if source_type not in readers:
        raise ValueError(f"data source type not support: {source_type}")
    return readers[source_type](config)