import logging

import pytest

from data_services.vector_sdk.cached_embedding import CacheEmbedding


class FailingEmbedding:
    def embed_documents(self, texts):
        raise RuntimeError("invalid input type")

    async def aembed_documents(self, texts):
        raise RuntimeError("invalid input type")


def test_document_embedding_logs_provider_error(caplog):
    embedding = CacheEmbedding(FailingEmbedding())

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="invalid input type"):
            embedding.embed_documents(["agent card"])

    assert "Failed to embed documents: invalid input type" in caplog.text
