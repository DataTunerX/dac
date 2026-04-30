"""Unit tests for ``skill_sdk.tool.tavily_extract``."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from skill_sdk.tool.tavily_extract import (
    DEFAULT_EXTRACT_TIMEOUT_SECONDS,
    TavilyExtractError,
    TavilyExtractSettings,
    clear_tavily_extract_cache,
    run_tavily_extract,
    tavily_extract_as_json_str,
)


def _no_cache_settings(**kwargs: object) -> TavilyExtractSettings:
    base: dict[str, object] = {
        "api_key": "test-key",
        "cache_ttl_minutes": 0.0,
        "timeout_seconds": 5.0,
    }
    base.update(kwargs)
    return TavilyExtractSettings(**base)  # type: ignore[arg-type]


class TestRunTavilyExtract(unittest.TestCase):
    def setUp(self) -> None:
        clear_tavily_extract_cache()

    def test_missing_api_key(self) -> None:
        old_key = os.environ.pop("TAVILY_API_KEY", None)
        try:
            with self.assertRaises(TavilyExtractError) as ctx:
                run_tavily_extract(
                    ["https://a.example"],
                    settings=TavilyExtractSettings(
                        api_key=None,
                        cache_ttl_minutes=0.0,
                        timeout_seconds=5.0,
                    ),
                )
        finally:
            if old_key is not None:
                os.environ["TAVILY_API_KEY"] = old_key
        self.assertIn("API key", str(ctx.exception))

    def test_empty_urls(self) -> None:
        with self.assertRaises(TavilyExtractError) as ctx:
            run_tavily_extract([], settings=_no_cache_settings())
        self.assertIn("at least one URL", str(ctx.exception))

    def test_too_many_urls(self) -> None:
        with self.assertRaises(TavilyExtractError) as ctx:
            run_tavily_extract([f"https://x{i}.example" for i in range(25)], settings=_no_cache_settings())
        self.assertIn("at most 20", str(ctx.exception))

    def test_chunks_require_query(self) -> None:
        with self.assertRaises(TavilyExtractError) as ctx:
            run_tavily_extract(
                ["https://a.example"],
                chunks_per_source=2,
                settings=_no_cache_settings(),
            )
        self.assertIn("query when chunks", str(ctx.exception))

    def test_chunks_bool_rejected(self) -> None:
        with self.assertRaises(TavilyExtractError):
            run_tavily_extract(
                ["https://a.example"],
                query="q",
                chunks_per_source=True,  # type: ignore[arg-type]
                settings=_no_cache_settings(),
            )

    @patch("skill_sdk.tool.tavily_extract.requests.post")
    def test_success_maps_results(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "results": [
                {
                    "url": "https://a.example",
                    "raw_content": "raw r",
                    "content": "clean c",
                    "images": ["https://a.example/i.png"],
                }
            ],
            "failed_results": [{"url": "https://bad.example", "error": "timeout"}],
        }
        mock_post.return_value = mock_resp

        out = run_tavily_extract(
            ["https://a.example"],
            query="q",
            extract_depth="advanced",
            chunks_per_source=2,
            include_images=True,
            settings=_no_cache_settings(),
        )

        self.assertNotIn("cached", out)
        self.assertEqual(out["provider"], "tavily")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["externalContent"]["source"], "web_fetch")
        self.assertIn("failedResults", out)
        r0 = out["results"][0]
        self.assertEqual(r0["url"], "https://a.example")
        self.assertIn("<<<EXTERNAL_UNTRUSTED_CONTENT", r0["rawContent"])
        self.assertIn("<<<EXTERNAL_UNTRUSTED_CONTENT", r0["content"])
        self.assertIn("i.png", r0["images"][0])

        call = mock_post.call_args
        self.assertIn("/extract", call[0][0])
        body = json.loads(call[1]["data"])
        self.assertEqual(body["urls"], ["https://a.example"])
        self.assertEqual(body["query"], "q")
        self.assertEqual(body["extract_depth"], "advanced")
        self.assertEqual(body["chunks_per_source"], 2)
        self.assertTrue(body["include_images"])
        self.assertIn("X-Client-Source", call[1]["headers"])

    @patch("skill_sdk.tool.tavily_extract.requests.post")
    def test_cache_hit(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp
        settings = TavilyExtractSettings(
            api_key="k",
            cache_ttl_minutes=15.0,
            timeout_seconds=5.0,
        )
        first = run_tavily_extract(["https://x.example"], settings=settings)
        second = run_tavily_extract(["https://x.example"], settings=settings)
        self.assertNotIn("cached", first)
        self.assertTrue(second.get("cached"))
        self.assertEqual(mock_post.call_count, 1)

    @patch("skill_sdk.tool.tavily_extract.requests.post", side_effect=requests.ConnectionError("boom"))
    def test_request_exception(self, _mock: MagicMock) -> None:
        with self.assertRaises(TavilyExtractError) as ctx:
            run_tavily_extract(["https://a.example"], settings=_no_cache_settings())
        self.assertIn("request failed", str(ctx.exception).lower())

    @patch("skill_sdk.tool.tavily_extract.requests.post")
    def test_as_json_str(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp
        raw = tavily_extract_as_json_str(["https://a.example"], settings=_no_cache_settings())
        data = json.loads(raw)
        self.assertEqual(data["provider"], "tavily")
