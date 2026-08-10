"""Tests for the retry mechanism in doc-agent tool_call_utils."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from agent.tool_call_utils import (
    invoke_llm_with_tool,
    validate_pydantic,
    extract_tool_call_result,
)


class SimpleModel(BaseModel):
    name: str = Field(default="default", description="A name")
    value: int = Field(default=0, description="A value")


class TestValidatePydanticDocAgent:
    def test_valid_dict_passes(self):
        v = validate_pydantic(SimpleModel)
        assert v({"name": "test", "value": 42}) is True

    def test_empty_dict_passes_all_optional(self):
        v = validate_pydantic(SimpleModel)
        assert v({}) is True

    def test_none_fails(self):
        v = validate_pydantic(SimpleModel)
        assert v(None) is False


class TestExtractRejectsSchemaWrapper:
    def test_schema_wrapper_rejected(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "my_tool", "args": {"properties": {}}}]
        result = extract_tool_call_result(msg, "my_tool")
        assert result is None


class TestInvokeRetryDocAgent:
    def _make_tool(self, model_cls):
        return StructuredTool(
            name="test_tool",
            description="Test tool",
            args_schema=model_cls,
            func=None,
            coroutine=None,
        )

    def _make_llm(self, responses):
        call_count = [0]

        async def mock_ainvoke(messages, config=None):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx] if idx < len(responses) else responses[-1]

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MagicMock()
        mock_llm.bind_tools.return_value.ainvoke = mock_ainvoke
        return mock_llm

    def _make_bad_response(self):
        response = MagicMock()
        response.content = "test"
        response.tool_calls = [{"name": "test_tool", "args": {"properties": {}}}]
        return response

    def _make_ok_response(self, args):
        response = MagicMock()
        response.content = "test"
        response.tool_calls = [{"name": "test_tool", "args": args}]
        return response

    @pytest.mark.asyncio
    async def test_retry_on_schema_wrapper(self):
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_bad_response(),
            self._make_ok_response({"name": "test", "value": 42}),
        ])

        with patch("langfuse.get_client"), patch("langfuse.langchain.CallbackHandler"):
            result = await invoke_llm_with_tool(
                llm=llm,
                tool=tool,
                messages=[],
                metadata={},
                retry=2,
            )

        assert result == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_retry_exhausted_with_fallback(self):
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_bad_response(),
            self._make_bad_response(),
            self._make_bad_response(),
        ])

        def fallback(answer):
            return {"name": "fallback", "value": -1}

        with patch("langfuse.get_client"), patch("langfuse.langchain.CallbackHandler"):
            result = await invoke_llm_with_tool(
                llm=llm,
                tool=tool,
                messages=[],
                metadata={},
                retry=2,
                fallback_formatter=fallback,
            )

        assert result == {"name": "fallback", "value": -1}

    @pytest.mark.asyncio
    async def test_backward_compatible_no_retry_params(self):
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_ok_response({"name": "test", "value": 42}),
        ])

        with patch("langfuse.get_client"), patch("langfuse.langchain.CallbackHandler"):
            result = await invoke_llm_with_tool(
                llm=llm,
                tool=tool,
                messages=[],
                metadata={},
            )

        assert result == {"name": "test", "value": 42}