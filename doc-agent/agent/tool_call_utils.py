"""共享的 tool-call 基础设施，供 doc-agent 中所有类复用。

提供：
- extract_tool_call_result() — 模块级函数，从 AIMessage 中提取工具调用参数
- invoke_llm_with_tool()       — 模块级 async 函数，封装 bind_tools + ainvoke + Langfuse
- validate_pydantic()          — 模块级函数，创建 Pydantic 模型校验器供 retry 使用
- format_llm_output()          — 模块级函数，JSON 兜底解析器，兼容 LLM 非 tool-call 的 JSON 输出

使用方式：
    from .tool_call_utils import invoke_llm_with_tool, validate_pydantic, format_llm_output

    result = await invoke_llm_with_tool(
        llm=self.llm_non_stream,
        tool=my_tool,
        messages=[...],
        tool_choice="my_tool",
        metadata=self.metadata,
        fallback_formatter=format_llm_output,
        span_name="span-name",
        retry=2,
        validate=validate_pydantic(MyModel),
    )
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
import time as _time
from typing import Any, Callable, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON recovery helpers (mirrors expert-agent's format_llm_output cascade)
# ---------------------------------------------------------------------------

_EMBEDDED_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)

_BARE_JSON_OBJECT_RE = re.compile(
    r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
    re.DOTALL,
)


def _llm_output_text_from_message(answer: Any) -> str:
    """Normalize AIMessage content to a plain string."""
    c = getattr(answer, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for part in c:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text", "")
                parts.append(t if isinstance(t, str) else str(t))
            else:
                parts.append(str(part))
        return "".join(parts)
    if c is not None:
        return str(c)
    if isinstance(answer, str):
        return answer
    return str(answer)


def _strip_markdown_code_fences(text: str) -> str:
    """Remove leading ``` and trailing ``` from text."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    line1_end = t.find("\n", 3)
    if line1_end != -1:
        t = t[line1_end + 1:]
    else:
        t = t[3:].lstrip()
    t = t.rstrip()
    if t.endswith("```"):
        t = t[:-3].rstrip()
    return t


def format_llm_output(answer: Any) -> Optional[dict]:
    """Parse LLM plain-text output into a dict with heavy JSON tolerance.

    This mirrors the recovery cascade in expert-agent's ``format_llm_output``.
    When the LLM fails to produce a proper tool-call, this attempts to recover
    structured JSON from the raw text content.

    Returns None if all recovery levels fail.
    """
    raw = _llm_output_text_from_message(answer)
    if not raw or not raw.strip():
        return None

    # Level 1: direct JSON
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            logger.info(" === format_llm_output, recovered via direct JSON parse")
            return parsed
    except json.JSONDecodeError:
        pass

    # Level 2: strip markdown code fences
    cleaned = _strip_markdown_code_fences(raw)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            logger.info(" === format_llm_output, recovered via strip markdown fences")
            return parsed
    except json.JSONDecodeError:
        pass

    # Level 3: extract embedded JSON fence from mixed text
    match = _EMBEDDED_JSON_FENCE_RE.search(cleaned)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict):
                logger.info(" === format_llm_output, recovered via embedded JSON fence")
                return parsed
        except json.JSONDecodeError:
            pass

    # Level 4: extract bare JSON object from free-form text
    for m in _BARE_JSON_OBJECT_RE.finditer(cleaned):
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                logger.info(" === format_llm_output, recovered via bare JSON extraction")
                return parsed
        except json.JSONDecodeError:
            continue

    # Level 5: try json_repair library
    try:
        from json_repair import repair_json as _json_repair
        try:
            repaired = _json_repair(cleaned, return_objects=True)
            if isinstance(repaired, dict):
                logger.info(" === format_llm_output, recovered via json_repair")
                return repaired
            if isinstance(repaired, str):
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    logger.info(" === format_llm_output, recovered via json_repair (string)")
                    return parsed
        except Exception:
            pass
    except ImportError:
        pass

    # Level 6: ast.literal_eval
    try:
        parsed = ast.literal_eval(cleaned)
        if isinstance(parsed, dict):
            logger.info(" === format_llm_output, recovered via ast.literal_eval")
            return parsed
    except (ValueError, SyntaxError):
        pass

    # Level 7: replace single quotes with double quotes
    try:
        parsed = json.loads(cleaned.replace("'", '"'))
        if isinstance(parsed, dict):
            logger.info(" === format_llm_output, recovered via single→double quote replacement")
            return parsed
    except json.JSONDecodeError:
        pass

    logger.warning(
        " === format_llm_output, all recovery levels failed for text[:200]: %s",
        raw[:200],
    )
    return None


# ---------------------------------------------------------------------------
# Pydantic validation helper
# ---------------------------------------------------------------------------

def validate_pydantic(model_cls: type) -> Callable[[dict], bool]:
    """创建一个校验器，检查 dict 是否能成功构造给定的 Pydantic 模型。

    用于 invoke_llm_with_tool 的 validate 参数，当 LLM 返回的 dict 缺少必填字段
    或字段类型不匹配时，校验失败并触发 retry。

    Args:
        model_cls: Pydantic BaseModel 子类

    Returns:
        可调用对象，签名为 (dict) -> bool
    """
    def _validate(data_dict: dict) -> bool:
        if data_dict is None:
            return False
        try:
            model_cls(**data_dict)
            return True
        except Exception:
            return False
    return _validate


# ---------------------------------------------------------------------------
# Tool call extraction
# ---------------------------------------------------------------------------

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
            if not isinstance(args, dict):
                return None
            # LLM 幻觉：返回了 tool schema 外壳而非实际参数，例如 {"properties": {}}
            if set(args.keys()) == {"properties"}:
                logger.warning(
                    "[extract_tool_call_result] LLM returned schema wrapper instead of "
                    "actual args for tool %r: %s",
                    tool_name,
                    json.dumps(args, ensure_ascii=False)[:200],
                )
                return None
            return args
    return None


# ---------------------------------------------------------------------------
# Core invoke logic
# ---------------------------------------------------------------------------

async def _invoke_single_attempt(
    *,
    llm_with_tool: Any,
    tool_name: str,
    messages: list,
    metadata: dict,
    span_name: str,
    span_input: Optional[dict],
    attempt: int,
    max_attempts: int,
) -> tuple[Optional[dict], bool, Any, float]:
    """单次 LLM 调用，返回 (result_dict, ok, raw_answer, elapsed_ms)。

    raw_answer 是 LLM 返回的原始 AIMessage，用于 fallback_formatter 兜底恢复。
    """
    from langfuse.langchain import CallbackHandler as _LangfuseCb
    from langfuse import get_client as _get_langfuse_client

    _handler = _LangfuseCb()
    _langfuse_client = _get_langfuse_client()

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

    result = extract_tool_call_result(answer, tool_name)
    ok = result is not None

    logger.info(
        " === tool_call_utils.invoke_llm_with_tool (%s) tool=%s ok=%s "
        "elapsed_ms=%s attempt=%d/%d result=%s",
        span_name, tool_name, ok, _elapsed, attempt, max_attempts,
        json.dumps(result, ensure_ascii=False) if ok else "None",
    )

    return result, ok, answer, _elapsed


async def invoke_llm_with_tool(
    *,
    llm: Any,
    tool: "StructuredTool",
    messages: list,
    metadata: dict,
    fallback_formatter: Optional[Callable] = None,
    tool_choice: Optional[str] = None,
    span_name: str = "docagent-tool-call",
    span_input: Optional[dict] = None,
    retry: int = 0,
    validate: Optional[Callable[[dict], bool]] = None,
) -> Optional[dict]:
    """使用 tool call 机制调用 LLM 并提取结构化输出，支持 retry 和校验。

    Args:
        llm: 非流式 LLM 实例（stream=False）
        tool: 绑定的 LangChain StructuredTool，其 args_schema 为 Pydantic 模型
        messages: 发送给 LLM 的消息列表
        metadata: 包含 user_id, run_id, trace_id 的字典
        fallback_formatter: 当 tool call 失败时的兜底函数，签名为 f(answer) -> dict。
                            通常传 ``format_llm_output`` 即可。
        tool_choice: 指定 tool_choice 参数，强制 LLM 调用该工具
        span_name: Langfuse trace span 名称
        span_input: Langfuse span 的输入信息
        retry: 最大重试次数（默认 0，不重试）。当 extract 返回 None 或 validate 校验
               失败时触发重试。
        validate: 可选的校验函数，签名为 (dict) -> bool。通常用 validate_pydantic(Model)
                  创建。当校验失败时，如果 retry > 0 则重试。

    Returns:
        解析后的工具参数字典；如果所有重试均失败且 fallback 也失败，返回 None
    """
    try:
        if tool_choice:
            llm_with_tool = llm.bind_tools([tool], tool_choice=tool_choice)
        else:
            llm_with_tool = llm.bind_tools([tool])
    except TypeError:
        llm_with_tool = llm.bind_tools([tool])

    max_attempts = retry + 1
    last_result = None
    last_ok = False
    last_answer = None

    for attempt in range(1, max_attempts + 1):
        result, ok, answer, _elapsed = await _invoke_single_attempt(
            llm_with_tool=llm_with_tool,
            tool_name=tool.name,
            messages=messages,
            metadata=metadata,
            span_name=span_name,
            span_input=span_input,
            attempt=attempt,
            max_attempts=max_attempts,
        )

        last_result = result
        last_ok = ok
        last_answer = answer

        if ok and validate is not None:
            try:
                ok = validate(result)
            except Exception:
                ok = False
            last_ok = ok
            if not ok:
                logger.warning(
                    " === tool_call_utils.invoke_llm_with_tool (%s) tool=%s "
                    "result failed Pydantic validation (attempt %d/%d), retrying...",
                    span_name, tool.name, attempt, max_attempts,
                )

        if ok:
            return result

        if not ok and attempt < max_attempts:
            await asyncio.sleep(0.5)

    # 所有重试耗尽 — 尝试从原始 LLM 文本中恢复（expert-agent 模式）
    if not last_ok and last_answer is not None and fallback_formatter is not None:
        logger.warning(
            " === tool_call_utils.invoke_llm_with_tool (%s): all %d attempts failed "
            "for tool %s, attempting fallback_formatter from raw LLM text",
            span_name, max_attempts, tool.name,
        )
        recovered = fallback_formatter(last_answer)
        if recovered is not None:
            logger.info(
                " === tool_call_utils.invoke_llm_with_tool (%s): fallback_formatter "
                "recovered result from raw text",
                span_name,
            )
            return recovered

    if not last_ok:
        logger.warning(
            " === tool_call_utils.invoke_llm_with_tool (%s): all %d attempts failed "
            "for tool %s",
            span_name, max_attempts, tool.name,
        )
        return None

    return last_result