"""ToolPlugin subclass for tavily_extract."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin
from skill_sdk.tool.tavily_search_plugin import _tavily_json_dumps

logger = logging.getLogger(__name__)


class TavilyExtractInput(BaseModel):
    """Input schema for ``tavily_extract`` tool."""

    urls: list[str] = Field(
        min_length=1,
        max_length=20,
        description="要提取正文的 http(s) URL 列表，1-20 个",
    )
    query: str | None = Field(
        default=None,
        description="可选；与 chunks_per_source 联用时按相关性分块/重排",
    )
    extract_depth: Literal["basic", "advanced"] | None = None
    chunks_per_source: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="每 URL 块数 1-5；若设置则必须同时提供非空 query",
    )
    include_images: bool = False


class TavilyExtractPlugin(ToolPlugin):
    """Tavily URL content extraction tool."""

    name = "tavily_extract"
    description = (
        "Tavily 从 URL 列表提取正文。API Key 与基址仅从进程环境读取"
        "（TAVILY_API_KEY / TAVILY_BASE_URL），不通过本工具参数传递。"
        "返回 JSON 字符串。"
    )
    args_schema = TavilyExtractInput

    def execute(self, **kwargs) -> str:
        from skill_sdk.tool.tavily_extract import TavilyExtractError, run_tavily_extract

        urls = list(kwargs.get("urls") or [])
        cleaned = [u.strip() for u in urls if u and str(u).strip()]
        if not cleaned:
            return self._format_error("tavily_extract requires at least one URL.")

        query = (kwargs.get("query") or "").strip() or None
        kw: dict[str, Any] = {
            "query": query,
            "include_images": bool(kwargs.get("include_images", False)),
        }
        extract_depth = kwargs.get("extract_depth")
        if extract_depth is not None:
            kw["extract_depth"] = extract_depth
        chunks_per_source = kwargs.get("chunks_per_source")
        if chunks_per_source is not None:
            kw["chunks_per_source"] = chunks_per_source

        try:
            out = run_tavily_extract(cleaned, **kw)
        except TavilyExtractError as exc:
            return self._format_error(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("tavily_extract unexpected error")
            return self._format_error(f"tavily_extract failed: {exc}")
        return _tavily_json_dumps(out)
