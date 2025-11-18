# model_sdk.py
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from abc import ABC, abstractmethod
import logging
import asyncio
from .base import BaseLLM, BaseEmbedding, BaseRerank
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk

# openai_compatible
from ..models.openai_compatible.embedding import OpenAICompatibleEmbedding
from ..models.openai_compatible.llm import OpenAICompatibleLLM
from ..models.openai_compatible.rerank import OpenAICompatibleRerank

# azure
from ..models.azure.embedding import AzureOpenAIEmbedding

# infinity
from ..models.infinity.embedding import InfinityEmbedding

# dashscope
from ..models.dashscope.embedding import DashScopeEmbedding


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


# =====================
# 模型管理器
# =====================

class ModelManager:
    _providers = {
        'llm': {},
        'embedding': {},
        'rerank': {}
    }
    
    @classmethod
    def register_provider(
        cls,
        model_type: str,
        provider: str,
        model_class: Type[Union[BaseLLM, BaseEmbedding, BaseRerank]]
    ):
        cls._providers[model_type][provider] = model_class
    
    def get_llm(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        **kwargs: Any
    ) -> BaseLLM:
        if provider not in self._providers['llm']:
            raise ValueError(f"Unsupported provider: {provider}")
        return self._providers['llm'][provider](
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
    
    def get_embedding(
        self,
        provider: str,
        **kwargs: Any
    ) -> BaseEmbedding:
        if provider not in self._providers['embedding']:
            raise ValueError(f"Unsupported provider: {provider}")
        return self._providers['embedding'][provider](
            provider=provider,
            **kwargs
        )

    def get_rerank(
        self,
        provider: str,
        model_name: str,
        model_config: Dict[str, Any],
    ) -> BaseRerank:
        if provider not in self._providers['rerank']:
            raise ValueError(f"Unsupported rerank provider: {provider}")
        return self._providers['rerank'][provider](
            provider=provider,
            model_name=model_name,
            model_settings=model_config
        )


# =====================
# 初始化注册
# =====================

def initialize_providers():

    # openai_compatible
    ModelManager.register_provider('llm', 'openai_compatible', OpenAICompatibleLLM)
    ModelManager.register_provider('embedding', 'openai_compatible', OpenAICompatibleEmbedding)
    ModelManager.register_provider('rerank', 'openai_compatible', OpenAICompatibleRerank)

    # azure
    ModelManager.register_provider('embedding', 'azure', AzureOpenAIEmbedding)

    # infinity
    ModelManager.register_provider('embedding', 'infinity', InfinityEmbedding)

    # dashscope
    ModelManager.register_provider('embedding', 'dashscope', DashScopeEmbedding)


initialize_providers()

