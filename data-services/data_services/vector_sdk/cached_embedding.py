import logging
import os
from typing import Any, Optional
from sqlalchemy.exc import IntegrityError
from langchain_core.embeddings import Embeddings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)

# DashScope embedding allows up to 8192 tokens; cap document input to stay safely below.
DEFAULT_EMBEDDING_MAX_CHARS = 5000


def _embedding_max_chars() -> int:
    raw = os.getenv("EMBEDDING_MAX_INPUT_CHARS", str(DEFAULT_EMBEDDING_MAX_CHARS))
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_EMBEDDING_MAX_CHARS
    except (TypeError, ValueError):
        logger.warning(
            "Invalid EMBEDDING_MAX_INPUT_CHARS=%r, using default %d",
            raw,
            DEFAULT_EMBEDDING_MAX_CHARS,
        )
        return DEFAULT_EMBEDDING_MAX_CHARS


def truncate_text_for_embedding(text: str, max_chars: Optional[int] = None) -> str:
    """Truncate document text before embedding; empty input becomes a single space."""
    limit = max_chars if max_chars is not None else _embedding_max_chars()
    if not text or not text.strip():
        return " "
    if len(text) <= limit:
        return text
    return text[:limit]


def truncate_texts_for_embedding(texts: list[str], max_chars: Optional[int] = None) -> list[str]:
    limit = max_chars if max_chars is not None else _embedding_max_chars()
    truncated: list[str] = []
    for text in texts:
        original_len = len(text or "")
        truncated_text = truncate_text_for_embedding(text or "", max_chars=limit)
        if original_len > limit:
            logger.warning(
                "Truncated document text for embedding from %d to %d chars (limit=%d)",
                original_len,
                len(truncated_text),
                limit,
            )
        truncated.append(truncated_text)
    return truncated


class CacheEmbedding(Embeddings):
    def __init__(self, model_instance: Embeddings, user: Optional[str] = None) -> None:
        self._model_instance = model_instance
        self._user = user

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed search docs in batches of 10."""
        try:
            return self._model_instance.embed_documents(truncate_texts_for_embedding(texts))
        except Exception as ex:
            logging.exception(f"Failed to async embed documents texts")
            raise ex


    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async embed search docs in batches of 10."""
        try:
            return await self._model_instance.aembed_documents(truncate_texts_for_embedding(texts))
        except Exception as ex:
            logging.exception(f"Failed to async embed documents text")
            raise ex


    def embed_query(self, text: str) -> list[float]:
        """Embed query text."""
        try:
            return self._model_instance.embed_query(text)
        except Exception as ex:
            logging.exception(f"Failed to embed query text '{text[:10]}...({len(text)} chars)'")
            raise ex


    async def aembed_query(self, text: str) -> list[float]:
        """Async embed query text."""
        try:
            return await self._model_instance.aembed_query(text)
        except Exception as ex:
            logging.exception(f"Failed to async embed query text '{text[:10]}...({len(text)} chars)'")
            raise ex
