from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from ...api.base import BaseEmbedding
from langchain_openai import OpenAIEmbeddings
import logging
import os


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbedding(BaseEmbedding):
    
    def __init__(
        self,
        provider: str,
        **kwargs: Any
    ):
        # Initialize model_kwargs with any additional kwargs
        model_kwargs = kwargs.copy()

        # LangChain tokenizes client-side and posts integer token arrays by
        # default. Strictly OpenAI-compatible servers (Ollama, some vLLM
        # builds) only accept strings and answer 400 "invalid input type".
        # Sending raw text is portable; callers already truncate before
        # embedding. Set EMBEDDING_CHECK_CTX_LENGTH=true to restore the
        # tokenizing behaviour for backends that need it.
        _check_ctx = (os.getenv("EMBEDDING_CHECK_CTX_LENGTH") or "").strip().lower() in ("1", "true", "yes")
        model_kwargs.setdefault("check_embedding_ctx_length", _check_ctx)
        
        super().__init__()
        self.provider = provider
        self.model_kwargs = model_kwargs
        self.embedding_client = OpenAIEmbeddings(
                **self.model_kwargs
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embedding_client.embed_documents(texts)
    
    def embed_query(self, text: str) -> List[float]:
        return self.embedding_client.embed_query(text)
    
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self.embedding_client.aembed_documents(texts)
    
    async def aembed_query(self, text: str) -> List[float]:
        return await self.embedding_client.aembed_query(text)