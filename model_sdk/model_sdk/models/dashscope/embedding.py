from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from ...api.base import BaseEmbedding
from langchain_community.embeddings import DashScopeEmbeddings
import logging
import os
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class DashScopeEmbedding(BaseEmbedding):
    
    def __init__(
        self,
        provider: str,
        **kwargs
    ):
        model_kwargs = kwargs.copy()
        super().__init__()
        self.provider = provider
        self.model_kwargs = model_kwargs
        self.client = DashScopeEmbeddings(
            **self.model_kwargs
        )

    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.client.embed_documents(texts)
    
    def embed_query(self, text: str) -> List[float]:
        return self.client.embed_query(text)
    
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """分批处理文档嵌入，避免超出API批量限制"""
        if not texts:
            return []
        
        batch_size = 10  # DashScope的最大批量限制
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                # 处理当前批次
                batch_embeddings = await self.client.aembed_documents(batch)
                all_embeddings.extend(batch_embeddings)
                
                # 可选：添加小延迟避免速率限制
                if i + batch_size < len(texts):  # 如果不是最后一批
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                # 记录错误并继续处理其他批次，或根据需求抛出异常
                logger.error(f"处理批次 {i//batch_size + 1} 时出错: {e}")
                raise
        
        return all_embeddings
    
    async def aembed_query(self, text: str) -> List[float]:
        return await self.client.aembed_query(text)