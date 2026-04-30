from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from typing import Any, Literal, Sequence

import requests

from skill_sdk.security.external_content import wrap_external_content
from skill_sdk.tool.tavily_search import (
    DEFAULT_TAVILY_BASE_URL,
    TavilySearchSettings,
    resolve_tavily_api_key,
    resolve_tavily_base_url,
    resolve_endpoint,
)

logger = logging.getLogger(__name__)

DEFAULT_EXTRACT_TIMEOUT_SECONDS = 60
DEFAULT_CACHE_TTL_MINUTES = 15
_CACHE_MAX_ENTRIES = 100
_MAX_URLS = 20

_EXTRACT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
ExtractDepth = Literal["basic", "advanced"]


class TavilyExtractError(Exception):
    """Raised when Tavily extract cannot complete (missing key, bad args, HTTP, invalid response)."""


@dataclass
class TavilyExtractSettings:
    """Defaults for :func:`run_tavily_extract` (env vars still apply when fields are None)."""

    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = DEFAULT_EXTRACT_TIMEOUT_SECONDS
    cache_ttl_minutes: float = DEFAULT_CACHE_TTL_MINUTES


def clear_tavily_extract_cache() -> None:
    _EXTRACT_CACHE.clear()


def _normalize_cache_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).lower()


def _cache_ttl_seconds(cache_ttl_minutes: float) -> float:
    return max(0.0, cache_ttl_minutes * 60.0)


def _to_search_settings(settings: TavilyExtractSettings | None) -> TavilySearchSettings | None:
    if settings is None:
        return None
    return TavilySearchSettings(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        cache_ttl_minutes=settings.cache_ttl_minutes,
    )


def _cache_get_extract(key: str, ttl_s: float) -> dict[str, Any] | None:
    if ttl_s <= 0:
        return None
    entry = _EXTRACT_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _EXTRACT_CACHE.pop(key, None)
        return None
    return value


def _cache_set_extract(key: str, value: dict[str, Any], ttl_s: float) -> None:
    if ttl_s <= 0:
        return
    if len(_EXTRACT_CACHE) >= _CACHE_MAX_ENTRIES:
        try:
            first = next(iter(_EXTRACT_CACHE))
            _EXTRACT_CACHE.pop(first, None)
        except StopIteration:
            pass
    _EXTRACT_CACHE[key] = (time.monotonic() + ttl_s, value)


def _wrap_fetch_no_warning(content: str) -> str:
    return wrap_external_content(content, source="web_fetch", include_warning=False)


def run_tavily_extract(
    urls: Sequence[str],
    *,
    query: str | None = None,
    extract_depth: ExtractDepth | None = None,
    chunks_per_source: int | None = None,
    include_images: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = None,
    settings: TavilyExtractSettings | None = None,
) -> dict[str, Any]:
    """
    Call Tavily ``POST /extract`` (Bearer API key).

    Credentials: ``api_key`` argument, then :attr:`TavilyExtractSettings.api_key`, then
    ``TAVILY_API_KEY``. Base URL: ``base_url``, then settings, then ``TAVILY_BASE_URL``, then
    ``https://api.tavily.com``.

    ``chunks_per_source`` (1-5) requires a non-empty ``query`` .
    """
    cfg = settings or TavilyExtractSettings()
    search_like = _to_search_settings(cfg)
    resolved_key = resolve_tavily_api_key(api_key=api_key, settings=search_like)
    if not resolved_key:
        raise TavilyExtractError(
            "tavily_extract needs a Tavily API key. Pass api_key=..., set TAVILY_API_KEY, "
            "or set TavilyExtractSettings.api_key.",
        )

    ulist = [u.strip() for u in urls if u and str(u).strip()]
    if not ulist:
        raise TavilyExtractError("tavily_extract requires at least one URL.")
    if len(ulist) > _MAX_URLS:
        raise TavilyExtractError(f"tavily_extract allows at most {_MAX_URLS} URLs per request.")

    q = (query or "").strip() or None
    chunks_n: int | None = None
    if chunks_per_source is not None:
        if isinstance(chunks_per_source, bool):
            raise TavilyExtractError("chunks_per_source must be an integer 1-5.")
        if not q:
            raise TavilyExtractError("tavily_extract requires query when chunks_per_source is set.")
        try:
            cps = float(chunks_per_source)
        except (TypeError, ValueError) as exc:
            raise TavilyExtractError("chunks_per_source must be an integer 1-5.") from exc
        if not math.isfinite(cps):
            raise TavilyExtractError("chunks_per_source must be an integer 1-5.")
        cpsi = int(cps)
        if cpsi < 1 or cpsi > 5 or cpsi != cps:
            raise TavilyExtractError("chunks_per_source must be an integer 1-5.")
        chunks_n = cpsi

    resolved_base = resolve_tavily_base_url(base_url=base_url, settings=search_like)

    timeout = (
        timeout_seconds
        if timeout_seconds is not None and timeout_seconds > 0
        else cfg.timeout_seconds
    )

    cache_payload: dict[str, Any] = {
        "type": "tavily-extract",
        "urls": ulist,
        "baseUrl": resolved_base,
        "query": q,
        "extractDepth": extract_depth,
        "chunksPerSource": chunks_per_source,
        "includeImages": bool(include_images),
    }
    cache_key = _normalize_cache_key(cache_payload)
    ttl_s = _cache_ttl_seconds(cfg.cache_ttl_minutes)
    cached = _cache_get_extract(cache_key, ttl_s)
    if cached is not None:
        return {**cached, "cached": True}

    body: dict[str, Any] = {"urls": ulist}
    if q:
        body["query"] = q
    if extract_depth:
        body["extract_depth"] = extract_depth
    if chunks_n is not None:
        body["chunks_per_source"] = chunks_n
    if include_images:
        body["include_images"] = True

    url = resolve_endpoint(resolved_base, "/extract")
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
        logger.debug("tavily_extract request failed: %s", exc)
        raise TavilyExtractError(f"Tavily Extract request failed: {exc}") from exc

    if not resp.ok:
        detail = (resp.text or "")[:64_000]
        raise TavilyExtractError(
            f"Tavily Extract API error ({resp.status_code}): {detail or resp.reason}",
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise TavilyExtractError("Tavily Extract returned non-JSON response.") from exc

    if not isinstance(payload, dict):
        raise TavilyExtractError("Tavily Extract returned unexpected JSON shape.")

    raw_results = payload.get("results")
    raw_list: list[Any] = raw_results if isinstance(raw_results, list) else []
    results: list[dict[str, Any]] = []
    for r in raw_list:
        if not isinstance(r, dict):
            continue
        url_s = r.get("url")
        raw_c = r.get("raw_content")
        item: dict[str, Any] = {
            "url": url_s if isinstance(url_s, str) else "",
            "rawContent": _wrap_fetch_no_warning(str(raw_c)) if isinstance(raw_c, str) else "",
        }
        content = r.get("content")
        if isinstance(content, str):
            item["content"] = _wrap_fetch_no_warning(content)
        imgs = r.get("images")
        if isinstance(imgs, list):
            out_imgs: list[str] = []
            for img in imgs:
                if isinstance(img, str):
                    out_imgs.append(_wrap_fetch_no_warning(img))
            if out_imgs:
                item["images"] = out_imgs
        results.append(item)

    failed_raw = payload.get("failed_results")
    failed_list = failed_raw if isinstance(failed_raw, list) else []
    took_ms = int((time.perf_counter() - start) * 1000)
    result: dict[str, Any] = {
        "provider": "tavily",
        "count": len(results),
        "tookMs": took_ms,
        "externalContent": {
            "untrusted": True,
            "source": "web_fetch",
            "provider": "tavily",
            "wrapped": True,
        },
        "results": results,
    }
    if failed_list:
        result["failedResults"] = failed_list

    _cache_set_extract(cache_key, result, ttl_s)
    return result


def tavily_extract_as_json_str(urls: Sequence[str], **kwargs: Any) -> str:
    """JSON-serialize :func:`run_tavily_extract` output (UTF-8, no ASCII escapes)."""
    return json.dumps(run_tavily_extract(urls, **kwargs), ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """CLI: one or more URLs; prints JSON to stdout (set TAVILY_API_KEY or pass --api-key)."""
    parser = argparse.ArgumentParser(
        description="Tavily URL content extract (TAVILY_API_KEY or --api-key).",
    )
    parser.add_argument("urls", nargs="+", help="One or more URLs to extract (max 20)")
    parser.add_argument("--query", default=None, help="Rerank chunks by relevance to this query")
    parser.add_argument(
        "--extract-depth",
        choices=["basic", "advanced"],
        default=None,
    )
    parser.add_argument(
        "--chunks-per-source",
        type=int,
        default=None,
        metavar="N",
        help="1-5; requires --query",
    )
    parser.add_argument("--include-images", action="store_true")
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--base-url",
        default=None,
        metavar="URL",
        help="Tavily base URL, else TAVILY_BASE_URL, else " + DEFAULT_TAVILY_BASE_URL,
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--pretty", action="store_true")
    ns = parser.parse_args(argv)

    kw: dict[str, Any] = {
        "query": ns.query,
        "extract_depth": ns.extract_depth,
        "chunks_per_source": ns.chunks_per_source,
        "include_images": ns.include_images,
        "timeout_seconds": ns.timeout,
    }
    if ns.api_key:
        kw["api_key"] = ns.api_key
    if ns.base_url:
        kw["base_url"] = ns.base_url
    kw = {k: v for k, v in kw.items() if v is not None}

    try:
        out = run_tavily_extract(ns.urls, **kw)
    except TavilyExtractError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    indent = 2 if ns.pretty else None
    print(json.dumps(out, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
