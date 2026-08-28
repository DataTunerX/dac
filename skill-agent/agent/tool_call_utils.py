"""
共享的 tool-call 基础设施，供 skill_agent 中所有类复用。

提供：
- extract_tool_call_result() — 模块级函数，从 AIMessage 中提取工具调用参数
- invoke_llm_with_tool()       — 模块级 async 函数，封装 bind_tools + ainvoke + Langfuse

使用方式：
    from .tool_call_utils import invoke_llm_with_tool, extract_tool_call_result

    class MyAgent:
        def __init__(self):
            self.llm_non_stream = ...  # stream=False 的 LLM 实例
            self.metadata = {}

        async def some_method(self):
            result = await invoke_llm_with_tool(
                llm=self.llm_non_stream,
                tool=my_tool,
                messages=[...],
                tool_choice="my_tool",
                metadata=self.metadata,
                span_name="span-name",
            )
"""

from __future__ import annotations

import json
import logging
import re
import time as _time
from typing import Any, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


def extract_tool_call_result(ai_msg: Any, tool_name: str) -> Optional[dict]:
    """从 LLM 的 AIMessage 响应中提取指定工具调用的参数。

    LangChain 的 bind_tools 机制让 LLM 返回一个 AIMessage，其中 tool_calls 字段
    记录了 LLM 决定调用的工具名称和参数。遍历所有 tool_calls，找到匹配
    tool_name 的那一个，将其 args 解析为 dict 返回。

    部分本地部署的模型（如 vLLM 上的 gemma）即使带了 tool_choice，也可能把结构化
    结果当作普通 JSON 文本写进 content 而不发起 tool_call。此时回退到从 content 中
    解析 JSON，避免整次判定被当成失败（capability_check 会因此把 confidence 归零，
    导致该 agent 被路由丢弃）。

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
    return _parse_json_object_from_content(getattr(ai_msg, "content", None))


def _parse_json_object_from_content(content: Any) -> Optional[dict]:
    """从模型的自由文本回复里抢救出一个 JSON 对象（tool_call 缺失时的兜底）。

    支持裸 JSON 与 ```json 代码块包裹两种形式；解析失败返回 None。
    """
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    logger.warning(
        " === tool_call_utils: LLM returned JSON text instead of a tool call — "
        "recovered %d field(s) from content", len(parsed),
    )
    return parsed


async def invoke_llm_with_tool(
    *,
    llm: Any,
    tool: "StructuredTool",
    messages: list,
    metadata: dict,
    tool_choice: Optional[str] = None,
    span_name: str = "skill-tool-call",
    span_input: Optional[dict] = None,
) -> Optional[dict]:
    """使用 tool call 机制调用 LLM 并提取结构化输出。

    替代之前基于 prompt 要求 LLM 返回 JSON 字符串的方案，改用 LangChain 的
    bind_tools/tool_choice 机制强制 LLM 输出符合 Pydantic schema 的结构化数据。

    核心流程：
    1. 使用传入的 llm（非流式实例）绑定指定工具
    2. 调用 llm_with_tool.ainvoke() 获取 AIMessage 响应
    3. 在 Langfuse span 中记录耗时和输入/输出
    4. 从 AIMessage.tool_calls 中提取工具参数
    5. 如果 LLM 未调用工具（tool_calls 为空），返回 None

    Args:
        llm: 非流式 LLM 实例（stream=False）
        tool: 绑定的 LangChain StructuredTool，其 args_schema 为 Pydantic 模型
        messages: 发送给 LLM 的消息列表
        metadata: 包含 user_id, run_id, trace_id 的字典
        tool_choice: 指定 tool_choice 参数，强制 LLM 调用该工具
        span_name: Langfuse trace span 名称
        span_input: Langfuse span 的输入信息

    Returns:
        解析后的工具参数字典；如果 LLM 未调用工具，返回 None
    """
    # 延迟导入避免模块级循环依赖
    from langfuse.langchain import CallbackHandler as _LangfuseCb
    from langfuse import get_client as _get_langfuse_client

    _handler = _LangfuseCb()
    # 获取 Langfuse 客户端实例（而非模块）。start_as_current_span 是客户端实例的方法，
    # 直接 import langfuse 得到的是模块对象，模块没有此方法，会导致 AttributeError。
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
        logger.warning(
            " === tool_call_utils.invoke_llm_with_tool (%s): LLM did not call tool %s",
            span_name, tool.name,
        )
    return result