from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from ...api.base import BaseEmbedding
from langchain_openai import AzureOpenAIEmbeddings
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class AzureOpenAIEmbedding(BaseEmbedding):
    
    def __init__(
        self,
        provider: str,
        **kwargs
    ):
        model_kwargs = kwargs.copy()
        super().__init__()
        self.provider = provider
        self.model_kwargs = model_kwargs
        os.environ["AZURE_OPENAI_ENDPOINT"] = self.model_kwargs.get("azure_endpoint", "")
        os.environ["AZURE_OPENAI_API_KEY"] = self.model_kwargs.get("api_key", "")
        self.client = AzureOpenAIEmbeddings(
            **self.model_kwargs
        )

    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.client.embed_documents(texts)
    
    def embed_query(self, text: str) -> List[float]:
        return self.client.embed_query(text)
    
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self.client.aembed_documents(texts)
    
    async def aembed_query(self, text: str) -> List[float]:
        return await self.client.aembed_query(text)