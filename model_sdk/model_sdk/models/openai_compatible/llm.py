from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Sequence, Type, Union
from ...api.base import BaseLLM
import logging
import os
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.language_models import LanguageModelInput
from pydantic import Field


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

logger = logging.getLogger(__name__)


def _is_minimax_model(model: str) -> bool:
    """True if model id contains 'minimax' (case-insensitive, e.g. MiniMax-M2)."""
    return "minimax" in (model or "").lower()


# Models that reject any non-default ``temperature`` and answer 400
# "Unsupported value: 'temperature' does not support X with this model."
# Extend at runtime with TEMPERATURE_UNSUPPORTED_MODELS (comma-separated
# substrings) so a new model does not require rebuilding every agent image.
_TEMPERATURE_UNSUPPORTED_PREFIXES = ("o1", "o3", "o4")
_TEMPERATURE_UNSUPPORTED_SUBSTRINGS = ("gpt-5.6",)


def _rejects_custom_temperature(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    extra = tuple(
        p.strip().lower()
        for p in (os.getenv("TEMPERATURE_UNSUPPORTED_MODELS") or "").split(",")
        if p.strip()
    )
    if any(name.startswith(p) for p in _TEMPERATURE_UNSUPPORTED_PREFIXES):
        return True
    return any(p in name for p in _TEMPERATURE_UNSUPPORTED_SUBSTRINGS + extra)



# Models whose server-side default reasoning_effort is rejected when function
# tools are bound on /v1/chat/completions:
#   "Function tools with reasoning_effort are not supported for <model> in
#    /v1/chat/completions. To use function tools, use /v1/responses or set
#    reasoning_effort to 'none'."
# The parameter is never set by DAC -- the provider applies it by default -- so
# it has to be pinned to "none" explicitly whenever tools are bound. Without it
# every tool-using call 400s, which silently fails the routing capability check
# and makes every agent report that it cannot handle the query.
_REASONING_EFFORT_TOOL_CONFLICT_SUBSTRINGS = ("gpt-5.6",)


def _tools_conflict_with_reasoning_effort(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    extra = tuple(
        p.strip().lower()
        for p in (os.getenv("REASONING_EFFORT_TOOL_CONFLICT_MODELS") or "").split(",")
        if p.strip()
    )
    return any(p in name for p in _REASONING_EFFORT_TOOL_CONFLICT_SUBSTRINGS + extra)


def _strip_unsupported_temperature(kwargs: Dict[str, Any], model: str) -> None:
    """Drop ``temperature`` for models that only accept the default value."""
    if "temperature" in kwargs and _rejects_custom_temperature(model):
        removed = kwargs.pop("temperature")
        logger.info(
            "Dropped unsupported temperature=%s for model %s (only the default is accepted)",
            removed,
            model,
        )


def _strip_enable_thinking_from_extra_body(kwargs: Dict[str, Any], model: str) -> None:
    """MiniMax on DashScope compatible API only allows enable_thinking=True; omit the key instead."""
    if not _is_minimax_model(model):
        return
    extra = kwargs.get("extra_body")
    if not isinstance(extra, dict) or "enable_thinking" not in extra:
        return
    new_extra = {k: v for k, v in extra.items() if k != "enable_thinking"}
    if new_extra:
        kwargs["extra_body"] = new_extra
    else:
        kwargs.pop("extra_body", None)


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
        _strip_enable_thinking_from_extra_body(model_kwargs, model)
        _strip_unsupported_temperature(model_kwargs, model)

        super().__init__(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            model_kwargs=model_kwargs
        )
        self._openai_client = self._create_openai_client()

    def bind_tools(
        self,
        tools: Sequence[
            Union[Dict[str, Any], type, Callable[..., Any], Any]
        ],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Delegate tool binding to the underlying ChatOpenAI client."""
        if (
            _tools_conflict_with_reasoning_effort(self.model)
            and "reasoning_effort" not in kwargs
        ):
            kwargs["reasoning_effort"] = "none"
            logger.info(
                "Pinned reasoning_effort='none' for model %s: function tools are "
                "rejected on /v1/chat/completions with any other value",
                self.model,
            )
        return self._openai_client.bind_tools(
            tools, tool_choice=tool_choice, **kwargs
        )

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
        _strip_enable_thinking_from_extra_body(final_kwargs, self.model)
        _strip_unsupported_temperature(final_kwargs, self.model)
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