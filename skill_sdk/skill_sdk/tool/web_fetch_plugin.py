"""ToolPlugin subclass for web_fetch."""

from __future__ import annotations

import json
import logging
import os

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)


class WebFetchInput(BaseModel):
    """Input schema for ``web_fetch`` tool."""

    url: str = Field(
        description="要抓取的 HTTP/HTTPS URL（scheme 必须是 http 或 https）",
    )
    extract_mode: str = Field(
        default="markdown",
        description="抽取模式：'markdown'（默认，保留结构）或 'text'（纯文本，适合搜索结果）",
    )
    max_chars: int = Field(
        default=8000,
        ge=100,
        le=40000,
        description="返回正文的最大字符数（含安全包装），超过会截断",
    )


class WebFetchPlugin(ToolPlugin):
    """Fetch HTTP/HTTPS URLs with SSRF protection, Readability extraction, and external content wrapping."""

    name = "web_fetch"
    description = (
        "抓取一个网页并做 SSRF 防护、Readability 抽取与外部内容注入防护包装。"
        "返回 JSON 字符串：成功含 url/final_url/status/content_type/extractor/title/content；"
        "失败时含 url/error。"
    )
    args_schema = WebFetchInput

    def execute(self, **kwargs) -> str:
        from skill_sdk.tool.web_fetch import (
            SsrfBlockedError,
            WebFetchError,
            WebFetchSettings,
            run_web_fetch,
        )

        url = str(kwargs.get("url", "")).strip()
        extract_mode = str(kwargs.get("extract_mode", "markdown")).strip()
        max_chars = int(kwargs.get("max_chars", 8000))

        if not url:
            return json.dumps(
                {"url": url, "error": "URL is required"},
                ensure_ascii=False,
            )
        if extract_mode not in ("markdown", "text"):
            return json.dumps(
                {"url": url, "error": f"Invalid extract_mode: {extract_mode!r}"},
                ensure_ascii=False,
            )

        allow_rfc2544 = os.environ.get("WEB_FETCH_ALLOW_RFC2544", "").strip().lower() in (
            "1", "true", "yes",
        )

        cfg = WebFetchSettings(
            max_chars=max_chars,
            timeout_seconds=20,
            cache_ttl_minutes=10,
            allow_rfc2544_benchmark_range=allow_rfc2544,
        )
        try:
            out = run_web_fetch(
                url,
                extract_mode=extract_mode,  # type: ignore[arg-type]
                max_chars=max_chars,
                settings=cfg,
            )
        except SsrfBlockedError as exc:
            msg = str(exc)
            hint = ""
            if "198.18." in msg or "198.19." in msg:
                hint = (
                    " — looks like a Clash/mihomo TUN fake-ip resolver. "
                    "Restart the runner with WEB_FETCH_ALLOW_RFC2544=1, or "
                    "rely on auto-detect (which may have been disabled via "
                    "WEB_FETCH_DISABLE_FAKEIP_AUTODETECT)."
                )
            return json.dumps(
                {"url": url, "error": f"{msg}{hint}"},
                ensure_ascii=False,
            )
        except WebFetchError as exc:
            return json.dumps(
                {"url": url, "error": f"Web fetch failed: {exc}"},
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("web_fetch unexpected error")
            return json.dumps(
                {"url": url, "error": f"Web fetch error: {exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "url": out.get("url"),
                "final_url": out.get("final_url"),
                "status": out.get("status"),
                "content_type": out.get("content_type"),
                "extractor": out.get("extractor"),
                "extract_mode": out.get("extract_mode"),
                "title": out.get("title"),
                "content": out.get("text"),
                "truncated": out.get("truncated"),
                "cached": out.get("cached"),
                "took_ms": out.get("took_ms"),
            },
            ensure_ascii=False,
        )
