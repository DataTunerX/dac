from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import requests

from skill_sdk.security.external_content import wrap_web_content

logger = logging.getLogger(__name__)

DEFAULT_TAVILY_BASE_URL = "https://api.tavily.com"
DEFAULT_SEARCH_COUNT = 5
DEFAULT_SEARCH_TIMEOUT_SECONDS = 30
DEFAULT_CACHE_TTL_MINUTES = 15
_CACHE_MAX_ENTRIES = 100

SearchDepth = Literal["basic", "advanced"]
Topic = Literal["general", "news", "finance"]
TimeRange = Literal["day", "week", "month", "year"]

_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class TavilySearchError(Exception):
    """Raised when Tavily search cannot complete (missing key, HTTP error, invalid response)."""


@dataclass
class TavilySearchSettings:
    """Defaults for :func:`run_tavily_search` (env vars still apply when fields are None)."""

    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS
    cache_ttl_minutes: float = DEFAULT_CACHE_TTL_MINUTES


def clear_tavily_search_cache() -> None:
    _SEARCH_CACHE.clear()


def _cache_ttl_seconds(settings: TavilySearchSettings) -> float:
    return max(0.0, settings.cache_ttl_minutes * 60.0)


def _cache_get(key: str, ttl_s: float) -> dict[str, Any] | None:
    if ttl_s <= 0:
        return None
    entry = _SEARCH_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _SEARCH_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: dict[str, Any], ttl_s: float) -> None:
    if ttl_s <= 0:
        return
    if len(_SEARCH_CACHE) >= _CACHE_MAX_ENTRIES:
        try:
            first = next(iter(_SEARCH_CACHE))
            _SEARCH_CACHE.pop(first, None)
        except StopIteration:
            pass
    _SEARCH_CACHE[key] = (time.monotonic() + ttl_s, value)


def _normalize_cache_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).lower()


def resolve_tavily_api_key(
    *,
    api_key: str | None = None,
    settings: TavilySearchSettings | None = None,
) -> str | None:
    for candidate in (
        (api_key or "").strip() or None,
        (settings.api_key if settings else None),
        (os.environ.get("TAVILY_API_KEY") or "").strip() or None,
    ):
        if candidate:
            return candidate.strip()
    return None


def resolve_tavily_base_url(
    *,
    base_url: str | None = None,
    settings: TavilySearchSettings | None = None,
) -> str:
    for candidate in (
        (base_url or "").strip() or None,
        (settings.base_url if settings and settings.base_url else None),
        (os.environ.get("TAVILY_BASE_URL") or "").strip() or None,
    ):
        if candidate:
            return candidate.strip()
    return DEFAULT_TAVILY_BASE_URL


def resolve_endpoint(base_url: str, pathname: str) -> str:
    trimmed = base_url.strip()
    if not trimmed:
        return f"{DEFAULT_TAVILY_BASE_URL}{pathname}"
    try:
        parsed = urlparse(trimmed if "://" in trimmed else f"https://{trimmed}")
        if not parsed.scheme or not parsed.netloc:
            return f"{DEFAULT_TAVILY_BASE_URL}{pathname}"
        new_path = (parsed.path or "").rstrip("/") + pathname
        return urlunparse(
            (parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment),
        )
    except Exception:
        return f"{DEFAULT_TAVILY_BASE_URL}{pathname}"


def run_tavily_search(
    query: str,
    *,
    search_depth: SearchDepth | None = None,
    topic: Topic | None = None,
    max_results: int | None = None,
    include_answer: bool = False,
    time_range: TimeRange | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = None,
    settings: TavilySearchSettings | None = None,
) -> dict[str, Any]:
    """
    Call Tavily ``POST /search`` (Bearer API key).

    Credentials: ``api_key`` argument, then :attr:`TavilySearchSettings.api_key`, then
    ``TAVILY_API_KEY``. Base URL: ``base_url``, then settings, then ``TAVILY_BASE_URL``, then
    ``https://api.tavily.com``.
    """
    cfg = settings or TavilySearchSettings()
    resolved_key = resolve_tavily_api_key(api_key=api_key, settings=cfg)
    if not resolved_key:
        raise TavilySearchError(
            "tavily_search needs a Tavily API key. Pass api_key=..., set TAVILY_API_KEY, "
            "or set TavilySearchSettings.api_key.",
        )

    q = (query or "").strip()
    if not q:
        raise TavilySearchError("tavily_search requires a non-empty query.")

    resolved_base = resolve_tavily_base_url(base_url=base_url, settings=cfg)
    if max_results is None:
        count = DEFAULT_SEARCH_COUNT
    else:
        try:
            n = float(max_results)
        except (TypeError, ValueError):
            count = DEFAULT_SEARCH_COUNT
        else:
            count = (
                max(1, min(20, int(n)))
                if math.isfinite(n)
                else DEFAULT_SEARCH_COUNT
            )

    timeout = (
        timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else cfg.timeout_seconds
    )

    inc_dom = [d for d in (include_domains or []) if d]
    exc_dom = [d for d in (exclude_domains or []) if d]

    cache_payload = {
        "type": "tavily-search",
        "q": q,
        "count": count,
        "baseUrl": resolved_base,
        "searchDepth": search_depth,
        "topic": topic,
        "includeAnswer": include_answer,
        "timeRange": time_range,
        "includeDomains": inc_dom or None,
        "excludeDomains": exc_dom or None,
    }
    cache_key = _normalize_cache_key(cache_payload)
    ttl_s = _cache_ttl_seconds(cfg)
    cached = _cache_get(cache_key, ttl_s)
    if cached is not None:
        return {**cached, "cached": True}

    body: dict[str, Any] = {"query": q, "max_results": count}
    if search_depth:
        body["search_depth"] = search_depth
    if topic:
        body["topic"] = topic
    if include_answer:
        body["include_answer"] = True
    if time_range:
        body["time_range"] = time_range
    if inc_dom:
        body["include_domains"] = inc_dom
    if exc_dom:
        body["exclude_domains"] = exc_dom

    url = resolve_endpoint(resolved_base, "/search")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
        "X-Client-Source": "skill_sdk",
    }

    start = time.perf_counter()
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(body),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.debug("tavily_search request failed: %s", exc)
        raise TavilySearchError(f"Tavily Search request failed: {exc}") from exc

    if not resp.ok:
        detail = (resp.text or "")[:64_000]
        raise TavilySearchError(
            f"Tavily Search API error ({resp.status_code}): {detail or resp.reason}",
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise TavilySearchError("Tavily Search returned non-JSON response.") from exc

    if not isinstance(payload, dict):
        raise TavilySearchError("Tavily Search returned unexpected JSON shape.")

    raw_results = payload.get("results")
    raw_list: list[Any] = raw_results if isinstance(raw_results, list) else []

    results: list[dict[str, Any]] = []
    for r in raw_list:
        if not isinstance(r, dict):
            continue
        title = r.get("title")
        url_s = r.get("url")
        content = r.get("content")
        score = r.get("score")
        pub = r.get("published_date")
        item: dict[str, Any] = {
            "title": wrap_web_content(title, "web_search") if isinstance(title, str) else "",
            "url": url_s if isinstance(url_s, str) else "",
            "snippet": wrap_web_content(content, "web_search") if isinstance(content, str) else "",
        }
        if isinstance(score, (int, float)):
            item["score"] = score
        if isinstance(pub, str):
            item["published"] = pub
        results.append(item)

    took_ms = int((time.perf_counter() - start) * 1000)
    result: dict[str, Any] = {
        "query": q,
        "provider": "tavily",
        "count": len(results),
        "tookMs": took_ms,
        "externalContent": {
            "untrusted": True,
            "source": "web_search",
            "provider": "tavily",
            "wrapped": True,
        },
        "results": results,
    }
    ans = payload.get("answer")
    if isinstance(ans, str) and ans:
        result["answer"] = wrap_web_content(ans, "web_search")

    _cache_set(cache_key, result, ttl_s)
    return result


def tavily_search_as_json_str(query: str, **kwargs: Any) -> str:
    """JSON-serialize :func:`run_tavily_search` output (UTF-8, no ASCII escapes)."""
    return json.dumps(run_tavily_search(query, **kwargs), ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: print :func:`run_tavily_search` result as JSON on stdout.

    Run from the ``skill_sdk`` install root, for example::

        python -m skill_sdk.tool.tavily_search \"your query\" --max-results 5
    """
    parser = argparse.ArgumentParser(
        description="Tavily web search (set TAVILY_API_KEY or pass --api-key).",
    )
    parser.add_argument("query", help="Search query string")
    parser.add_argument("--max-results", type=int, default=None, metavar="N")
    parser.add_argument("--api-key", default=None, help="Override TAVILY_API_KEY")
    parser.add_argument(
        "--base-url",
        default=None,
        metavar="URL",
        help=(
            "Tavily API base URL. If omitted, uses TAVILY_BASE_URL, else "
            f"{DEFAULT_TAVILY_BASE_URL} (same as run_tavily_search)."
        ),
    )
    parser.add_argument("--include-answer", action="store_true")
    parser.add_argument("--search-depth", choices=["basic", "advanced"], default=None)
    parser.add_argument("--topic", choices=["general", "news", "finance"], default=None)
    parser.add_argument(
        "--time-range",
        choices=["day", "week", "month", "year"],
        default=None,
    )
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout (seconds)")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    ns = parser.parse_args(argv)

    kw: dict[str, Any] = {
        "max_results": ns.max_results,
        "include_answer": ns.include_answer,
        "search_depth": ns.search_depth,
        "topic": ns.topic,
        "time_range": ns.time_range,
        "timeout_seconds": ns.timeout,
    }
    if ns.api_key:
        kw["api_key"] = ns.api_key
    if ns.base_url:
        kw["base_url"] = ns.base_url
    kw = {k: v for k, v in kw.items() if v is not None}

    try:
        out = run_tavily_search(ns.query, **kw)
    except TavilySearchError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    indent = 2 if ns.pretty else None
    print(json.dumps(out, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
