def get_reader(source_type: str, config: dict):
    """factory method to get reader (lazy imports keep status service lightweight)."""
    if source_type == "mysql":
        from .readers.mysql.mysql_reader import MySQLReader

        return MySQLReader(config)
    if source_type == "postgres":
        from .readers.postgres.postgres_reader import PostgresReader

        return PostgresReader(config)
    if source_type == "fileserver":
        from .readers.fileserver.fileserver_reader import FileServerReader

        return FileServerReader(config)
    if source_type == "minio":
        from .readers.minio.minio_reader import MinIOReader

        return MinIOReader(config)
    if source_type == "github":
        from .readers.code.github_reader import GitHubReader

        return GitHubReader(config)
    if source_type == "gitee":
        from .readers.code.gitee_reader import GiteeReader

        return GiteeReader(config)
    if source_type == "gitlab":
        from .readers.code.gitlab_reader import GitLabReader

        return GitLabReader(config)
    raise ValueError(f"data source type not support: {source_type}")