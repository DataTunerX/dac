from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from ...api.base import BaseLLM
import logging
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk
from pydantic import Field


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    """An LLM implementation for OpenAI-compatible APIs."""
    
    api_key: str = Field(..., description="The API key for the OpenAI-compatible service")
    base_url: str = Field(..., description="The base URL for the API")
    model_kwargs: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Model parameters including temperature, max_tokens, etc."
    )

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        **kwargs: Any
    ):
        # Initialize model_kwargs with any additional kwargs
        model_kwargs = kwargs.copy()
        
        super().__init__(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            model_kwargs=model_kwargs
        )
        self._openai_client = self._create_openai_client()

    def _create_openai_client(self) -> ChatOpenAI:
        """Create and configure the OpenAI-compatible client."""
        try:
            return ChatOpenAI(
                model=self.model,
                openai_api_key=self.api_key,
                base_url=self.base_url,
                **self.model_kwargs
            )
        except Exception as e:
            logger.error(f"Failed to create OpenAI client: {str(e)}")
            raise

    def _prepare_kwargs(
        self, 
        stop: Optional[List[str]] = None, 
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Prepare the final kwargs for API calls."""
        final_kwargs = self.model_kwargs.copy()
        final_kwargs.update(kwargs)
        if stop is not None:
            final_kwargs["stop"] = stop
        return final_kwargs

    def _call_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Call the API synchronously."""
        try:
            final_kwargs = self._prepare_kwargs(stop=stop, **kwargs)
            response = self._openai_client.invoke(messages, **final_kwargs)
            return ChatResult(generations=[ChatGeneration(message=response)])
        except Exception as e:
            logger.error(f"API call failed: {str(e)}")
            raise

    async def _acall_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Call the API asynchronously."""
        try:
            final_kwargs = self._prepare_kwargs(stop=stop, **kwargs)
            response = await self._openai_client.ainvoke(messages, **final_kwargs)
            return ChatResult(generations=[ChatGeneration(message=response)])
        except Exception as e:
            logger.error(f"Async API call failed: {str(e)}")
            raise

    def _call_streaming_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Call the streaming API synchronously."""
        try:
            final_kwargs = self._prepare_kwargs(stop=stop, **kwargs)
            for chunk in self._openai_client.stream(messages, **final_kwargs):
                if run_manager:
                    run_manager.on_llm_new_token(chunk.content)
                yield ChatGenerationChunk(message=AIMessageChunk(content=chunk.content))
        except Exception as e:
            logger.error(f"Streaming API call failed: {str(e)}")
            raise

    async def _acall_streaming_api(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Call the streaming API asynchronously."""
        try:
            final_kwargs = self._prepare_kwargs(stop=stop, **kwargs)
            async for chunk in self._openai_client.astream(messages, **final_kwargs):
                if run_manager:
                    await run_manager.on_llm_new_token(chunk.content)
                yield ChatGenerationChunk(message=AIMessageChunk(content=chunk.content))
        except Exception as e:
            logger.error(f"Async streaming API call failed: {str(e)}")
            raise