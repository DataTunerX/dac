from enum import Enum
from pydantic import BaseModel
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from abc import ABC, abstractmethod
import logging
import asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk


# =====================
# 1. 基础模型接口（严格遵循LangChain模式）
# =====================

class BaseLLM(BaseChatModel, ABC):
    """严格遵循LangChain设计模式的LLM基类"""
    
    provider: str
    model: str
    
    @property
    def _llm_type(self) -> str:
        return f"{self.provider}_{self.model}"
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步生成实现"""
        return self._call_api(messages, stop, run_manager, **kwargs)

    
    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步生成实现""" 
        return await self._acall_api(messages, stop, run_manager, **kwargs)
        

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """同步流式实现"""
        return self._call_streaming_api(messages, stop, run_manager, **kwargs)

    
    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """异步流式实现"""
        async for chunk in self._acall_streaming_api(messages, stop, run_manager, **kwargs):
            yield chunk

    
    @abstractmethod
    def _call_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步API调用"""
        pass
    
    @abstractmethod
    async def _acall_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步API调用"""
        pass
    
    @abstractmethod
    def _call_streaming_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """同步流式API"""
        pass
    
    @abstractmethod
    async def _acall_streaming_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """异步流式API"""
        pass


class BaseEmbedding(Embeddings, ABC):
    """严格遵循LangChain模式的Embedding基类"""
    
    provider: str
    model: str
    
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """同步文档嵌入"""
        pass
    
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """同步查询嵌入"""
        pass
    
    @abstractmethod
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """异步文档嵌入"""
        pass
    
    @abstractmethod
    async def aembed_query(self, text: str) -> List[float]:
        """异步查询嵌入"""
        pass



class RerankDocument(BaseModel):
    """
    Model class for rerank document.
    """

    index: int
    text: str
    score: float


class RerankResult(BaseModel):
    """
    Model class for rerank result.
    """

    model: str
    docs: list[RerankDocument]



class BaseRerank(ABC):
    """与您现有架构一致的Rerank基类"""
    
    provider: str
    model_name: str
    model_settings: Dict[str, Any]
    
    @abstractmethod
    def invoke(
        self,
        query: str,
        docs: List[str],
        score_threshold: Optional[float] = None,
        top_n: Optional[int] = None,
    ) -> RerankResult:
        """同步rerank调用"""
        pass
    
    @abstractmethod
    async def ainvoke(
        self,
        query: str,
        docs: List[str],
        score_threshold: Optional[float] = None,
        top_n: Optional[int] = None,
    ) -> RerankResult:
        """异步rerank调用"""
        pass




class ModelType(Enum):
    """
    Enum class for model type.
    """

    LLM = "llm"
    TEXT_EMBEDDING = "text-embedding"
    RERANK = "rerank"
    SPEECH2TEXT = "speech2text"
    TTS = "tts"

    @classmethod
    def value_of(cls, origin_model_type: str) -> "ModelType":
        """
        Get model type from origin model type.

        :return: model type
        """
        if origin_model_type in {"text-generation", cls.LLM.value}:
            return cls.LLM
        elif origin_model_type in {"embeddings", cls.TEXT_EMBEDDING.value}:
            return cls.TEXT_EMBEDDING
        elif origin_model_type in {"reranking", cls.RERANK.value}:
            return cls.RERANK
        elif origin_model_type in {"speech2text", cls.SPEECH2TEXT.value}:
            return cls.SPEECH2TEXT
        elif origin_model_type in {"tts", cls.TTS.value}:
            return cls.TTS
        else:
            raise ValueError(f"invalid origin model type {origin_model_type}")

    def to_origin_model_type(self) -> str:
        """
        Get origin model type from model type.

        :return: origin model type
        """
        if self == self.LLM:
            return "text-generation"
        elif self == self.TEXT_EMBEDDING:
            return "embeddings"
        elif self == self.RERANK:
            return "reranking"
        elif self == self.SPEECH2TEXT:
            return "speech2text"
        elif self == self.TTS:
            return "tts"
        else:
            raise ValueError(f"invalid model type {self}")


class RerankModel():
    """
    Model class for large language model.
    """

    model_type: ModelType = ModelType.RERANK

class Speech2TextModel():
    """
    Model class for large language model.
    """

    model_type: ModelType = ModelType.SPEECH2TEXT


class TTSModel():
    """
    Model class for large language model.
    """

    model_type: ModelType = ModelType.TTS
