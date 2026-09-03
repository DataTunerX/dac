"""ToolPlugin subclass for tavily_search."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)


class TavilySearchInput(BaseModel):
    """Input schema for ``tavily_search`` tool."""

    query: str = Field(
        min_length=1,
        description="Tavily 搜索查询：关键词或简短问题",
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="返回条数 1-20，缺省与 SDK 一致",
    )
    search_depth: Literal["basic", "advanced"] | None = None
    topic: Literal["general", "news", "finance"] | None = None
    include_answer: bool = False
    time_range: Literal["day", "week", "month", "year"] | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None


class TavilySearchPlugin(ToolPlugin):
    """Tavily web search tool."""

    name = "tavily_search"
    description = (
        "Tavily 联网搜索。API Key 与基址仅从进程环境读取"
        "（TAVILY_API_KEY / TAVILY_BASE_URL），不通过本工具参数传递。"
        "返回 JSON 字符串。"
    )
    args_schema = TavilySearchInput

    def execute(self, **kwargs) -> str:
        from skill_sdk.tool.tavily_search import TavilySearchError, run_tavily_search

        query = str(kwargs.get("query", "")).strip()
        if not query:
            return self._format_error("tavily_search requires a non-empty query.")

        kw: dict[str, Any] = {
            "include_answer": bool(kwargs.get("include_answer", False)),
        }
        max_results = kwargs.get("max_results")
        if max_results is not None:
            kw["max_results"] = max_results
        search_depth = kwargs.get("search_depth")
        if search_depth is not None:
            kw["search_depth"] = search_depth
        topic = kwargs.get("topic")
        if topic is not None:
            kw["topic"] = topic
        time_range = kwargs.get("time_range")
        if time_range is not None:
            kw["time_range"] = time_range

        inc = [
            x.strip()
            for x in (kwargs.get("include_domains") or [])
            if x and str(x).strip()
        ]
        exc = [
            x.strip()
            for x in (kwargs.get("exclude_domains") or [])
            if x and str(x).strip()
        ]
        if inc:
            kw["include_domains"] = inc
        if exc:
            kw["exclude_domains"] = exc

        try:
            out = run_tavily_search(query, **kw)
        except TavilySearchError as exc:
            return self._format_error(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("tavily_search unexpected error")
            return self._format_error(f"tavily_search failed: {exc}")
        return _tavily_json_dumps(out)


def _tavily_json_dumps(payload: dict[str, Any], *, max_chars: int = 48000) -> str:
    """Serialize Tavily tool output; shrink results if the JSON would exceed max_chars."""
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= max_chars:
        return raw
    results = payload.get("results")
    if isinstance(results, list) and results:
        slim = {
            **payload,
            "results": results[: min(3, len(results))],
            "_truncated": True,
            "_truncation_note": "results truncated to first 3 due to size cap",
        }
        raw2 = json.dumps(slim, ensure_ascii=False)
        if len(raw2) <= max_chars:
            return raw2
    return json.dumps(
        {
            "error": "tavily response too large to return; narrow query/urls or reduce max_results",
            "is_error": True,
            "provider": payload.get("provider"),
            "count": payload.get("count"),
        },
        ensure_ascii=False,
    )
