"""共享的 tool-call 基础设施，供 expert_agent 中所有类复用。

提供：
- extract_tool_call_result() — 模块级函数，从 AIMessage 中提取工具调用参数
- invoke_llm_with_tool()       — 模块级 async 函数，封装 bind_tools + ainvoke + Langfuse

使用方式：
    from .tool_call_utils import invoke_llm_with_tool

    result = await invoke_llm_with_tool(
        llm=self.llm_non_stream,
        tool=my_tool,
        messages=[...],
        tool_choice="my_tool",
        metadata=self.metadata,
        fallback_formatter=self.format_llm_output,
        span_name="span-name",
    )
"""

from __future__ import annotations

import json
import logging
import time as _time
from typing import Any, Callable, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


def extract_tool_call_result(ai_msg: Any, tool_name: str) -> Optional[dict]:
    """从 LLM 的 AIMessage 响应中提取指定工具调用的参数。

    Args:
        ai_msg: LLM 返回的 AIMessage 对象。
        tool_name: 要查找的工具名称。

    Returns:
        解析后的工具参数字典；如果未找到对应工具调用或解析失败则返回 None。
    """
    tool_calls = getattr(ai_msg, "tool_calls", None) or []
    for call in tool_calls:
        if call.get("name") == tool_name:
            args = call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    return None
            return args if isinstance(args, dict) else {}
    return None


async def invoke_llm_with_tool(
    *,
    llm: Any,
    tool: "StructuredTool",
    messages: list,
    metadata: dict,
    fallback_formatter: Optional[Callable] = None,
    tool_choice: Optional[str] = None,
    span_name: str = "expert-tool-call",
    span_input: Optional[dict] = None,
) -> Optional[dict]:
    """使用 tool call 机制调用 LLM 并提取结构化输出。

    Args:
        llm: 非流式 LLM 实例（stream=False）
        tool: 绑定的 LangChain StructuredTool，其 args_schema 为 Pydantic 模型
        messages: 发送给 LLM 的消息列表
        metadata: 包含 user_id, run_id, trace_id 的字典
        fallback_formatter: 当 tool call 失败时的兜底函数，签名为 f(answer) -> dict
        tool_choice: 指定 tool_choice 参数，强制 LLM 调用该工具
        span_name: Langfuse trace span 名称
        span_input: Langfuse span 的输入信息

    Returns:
        解析后的工具参数字典；如果 LLM 未调用工具且 fallback 也失败，返回 None
    """
    from langfuse.langchain import CallbackHandler as _LangfuseCb
    from langfuse import get_client as _get_langfuse_client

    _handler = _LangfuseCb()
    _langfuse_client = _get_langfuse_client()

    try:
        if tool_choice:
            llm_with_tool = llm.bind_tools([tool], tool_choice=tool_choice)
        else:
            llm_with_tool = llm.bind_tools([tool])
    except TypeError:
        llm_with_tool = llm.bind_tools([tool])

    _md: dict[str, Any] = metadata or {}
    trace_id = _md.get("trace_id", "")
    user_id = _md.get("user_id", "")
    run_id = _md.get("run_id", "")

    _t0 = _time.monotonic()
    with _langfuse_client.start_as_current_span(
        name=span_name,
        trace_context={"trace_id": trace_id} if trace_id else {},
    ) as span:
        span.update_trace(
            user_id=user_id,
            session_id=run_id,
            input=span_input or {},
        )
        answer = await llm_with_tool.ainvoke(
            messages,
            config={"callbacks": [_handler]},
        )
        span.update_trace(
            output={
                "answer": str(answer.content)[:2000]
                if hasattr(answer, "content")
                else str(answer)[:2000]
            }
        )
    _langfuse_client.flush()
    _elapsed = round((_time.monotonic() - _t0) * 1000)

    result = extract_tool_call_result(answer, tool.name)
    ok = result is not None
    logger.info(
        " === tool_call_utils.invoke_llm_with_tool (%s) tool=%s ok=%s elapsed_ms=%s result=%s",
        span_name, tool.name, ok, _elapsed,
        json.dumps(result, ensure_ascii=False) if ok else "None",
    )
    if not ok:
        if fallback_formatter is not None:
            logger.warning(
                " === tool_call_utils.invoke_llm_with_tool (%s): LLM did not call tool %s, "
                "falling back to fallback_formatter",
                span_name, tool.name,
            )
            return fallback_formatter(answer)
        else:
            logger.warning(
                " === tool_call_utils.invoke_llm_with_tool (%s): LLM did not call tool %s",
                span_name, tool.name,
            )
            return None

    return result