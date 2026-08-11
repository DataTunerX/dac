"""Tests for the retry mechanism in tool_call_utils."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from agent.tool_call_utils import (
    invoke_llm_with_tool,
    validate_pydantic,
    extract_tool_call_result,
)


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------

class SimpleModel(BaseModel):
    name: str = Field(description="A name")
    value: int = Field(description="A value")


class OptionalModel(BaseModel):
    field: str = Field(default="default", description="Optional field")


class RequiredModel(BaseModel):
    required_field: str = Field(description="Required field")
    optional_field: str = Field(default="opt", description="Optional field")


# ---------------------------------------------------------------------------
# Tests for validate_pydantic
# ---------------------------------------------------------------------------

class TestValidatePydantic:
    def test_valid_dict_passes(self):
        v = validate_pydantic(SimpleModel)
        assert v({"name": "test", "value": 42}) is True

    def test_missing_field_fails(self):
        v = validate_pydantic(SimpleModel)
        assert v({"name": "test"}) is False

    def test_wrong_type_fails(self):
        v = validate_pydantic(SimpleModel)
        assert v({"name": "test", "value": "not_an_int"}) is False

    def test_none_fails(self):
        v = validate_pydantic(SimpleModel)
        assert v(None) is False

    def test_extra_field_passes(self):
        v = validate_pydantic(SimpleModel)
        assert v({"name": "test", "value": 42, "extra": "ignored"}) is True

    def test_optional_model(self):
        v = validate_pydantic(OptionalModel)
        assert v({}) is True
        assert v({"field": "custom"}) is True


# ---------------------------------------------------------------------------
# Tests for extract_tool_call_result
# ---------------------------------------------------------------------------

class TestExtractToolCallResult:
    def test_normal_args(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "my_tool", "args": {"key": "val"}}]
        result = extract_tool_call_result(msg, "my_tool")
        assert result == {"key": "val"}

    def test_string_args_parsed(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "my_tool", "args": '{"key": "val"}'}]
        result = extract_tool_call_result(msg, "my_tool")
        assert result == {"key": "val"}

    def test_schema_wrapper_rejected(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "my_tool", "args": {"properties": {}}}]
        result = extract_tool_call_result(msg, "my_tool")
        assert result is None

    def test_no_tool_calls(self):
        msg = MagicMock()
        msg.tool_calls = []
        result = extract_tool_call_result(msg, "my_tool")
        assert result is None

    def test_wrong_tool_name(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "other_tool", "args": {"key": "val"}}]
        result = extract_tool_call_result(msg, "my_tool")
        assert result is None


# ---------------------------------------------------------------------------
# Tests for invoke_llm_with_tool retry behavior
# ---------------------------------------------------------------------------

class TestInvokeLlmWithToolRetry:
    """Tests that retry actually re-invokes the LLM when output is invalid."""

    def _make_tool(self, model_cls):
        return StructuredTool(
            name="test_tool",
            description="Test tool",
            args_schema=model_cls,
            func=None,
            coroutine=None,
        )

    def _make_llm(self, responses):
        """Mock LLM that returns a sequence of AIMessage responses."""
        call_count = [0]

        async def mock_ainvoke(messages, config=None):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                resp = responses[idx]
                if isinstance(resp, Exception):
                    raise resp
                return resp
            return responses[-1]

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MagicMock()
        mock_llm.bind_tools.return_value.ainvoke = mock_ainvoke
        return mock_llm

    def _make_ok_response(self, args):
        """Make an AIMessage with a valid tool call."""
        response = MagicMock()
        response.content = "test"
        response.tool_calls = [{"name": "test_tool", "args": args}]
        return response

    def _make_bad_response(self):
        """Make an AIMessage with schema wrapper instead of args."""
        response = MagicMock()
        response.content = "test"
        response.tool_calls = [{"name": "test_tool", "args": {"properties": {}}}]
        return response

    def _make_missing_field_response(self):
        """Make an AIMessage with a tool call missing required fields."""
        response = MagicMock()
        response.content = "test"
        response.tool_calls = [{"name": "test_tool", "args": {"name": "only"}}]
        return response

    @pytest.mark.asyncio
    async def test_retry_on_schema_wrapper(self):
        """LLM first returns schema wrapper, then valid args → retry succeeds."""
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
                validate=validate_pydantic(SimpleModel),
            )

        assert result == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_retry_on_missing_field(self):
        """LLM first returns missing field, then valid args → retry succeeds."""
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_missing_field_response(),
            self._make_ok_response({"name": "test", "value": 42}),
        ])

        with patch("langfuse.get_client"), patch("langfuse.langchain.CallbackHandler"):
            result = await invoke_llm_with_tool(
                llm=llm,
                tool=tool,
                messages=[],
                metadata={},
                retry=2,
                validate=validate_pydantic(SimpleModel),
            )

        assert result == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_none(self):
        """All retries fail → returns None."""
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_bad_response(),
            self._make_bad_response(),
            self._make_bad_response(),
        ])

        with patch("langfuse.get_client"), patch("langfuse.langchain.CallbackHandler"):
            result = await invoke_llm_with_tool(
                llm=llm,
                tool=tool,
                messages=[],
                metadata={},
                retry=2,
                validate=validate_pydantic(SimpleModel),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_retry_0_no_retry(self):
        """With retry=0, first failure returns None immediately."""
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
                retry=0,
                validate=validate_pydantic(SimpleModel),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_validate_still_retries_on_extract_failure(self):
        """Without validate, retry still works on extract failure (schema wrapper)."""
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
    async def test_no_validate_no_retry_on_missing_field(self):
        """Without validate, missing field is NOT caught by extract, so no retry."""
        tool = self._make_tool(SimpleModel)
        llm = self._make_llm([
            self._make_missing_field_response(),
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

        # First attempt succeeds at extract level (it has args, just missing field),
        # so no retry — returns the incomplete dict.
        assert result == {"name": "only"}

    @pytest.mark.asyncio
    async def test_backward_compatible_no_retry_params(self):
        """Old callers without retry/validate params still work."""
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