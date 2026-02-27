import logging
from typing import Any, Optional
from sqlalchemy.exc import IntegrityError
from langchain_core.embeddings import Embeddings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class CacheEmbedding(Embeddings):
    def __init__(self, model_instance: Embeddings, user: Optional[str] = None) -> None:
        self._model_instance = model_instance
        self._user = user

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed search docs in batches of 10."""
        try:
            return self._model_instance.embed_documents(texts)
        except Exception as ex:
            logging.exception(f"Failed to async embed documents texts")
            raise ex


    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async embed search docs in batches of 10."""
        try:
            return await self._model_instance.aembed_documents(texts)
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
