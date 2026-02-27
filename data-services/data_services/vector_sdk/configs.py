import os

class VectorConfig:
    PGVECTOR_HOST = os.getenv("PGVECTOR_HOST", "localhost")
    PGVECTOR_PORT = int(os.getenv("PGVECTOR_PORT", 5432))
    PGVECTOR_USER = os.getenv("PGVECTOR_USER", "postgres")
    PGVECTOR_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "postgres")
    PGVECTOR_DATABASE = os.getenv("PGVECTOR_DATABASE", "postgres")
    PGVECTOR_MIN_CONNECTION = int(os.getenv("PGVECTOR_MIN_CONNECTION", 1))
    PGVECTOR_MAX_CONNECTION = int(os.getenv("PGVECTOR_MAX_CONNECTION", 5))
    PGVECTOR_PG_BIGM = bool(os.getenv("PGVECTOR_PG_BIGM", False))


vector_config = VectorConfig()
