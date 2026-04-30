"""Unit tests for ``skill_sdk.tool.tavily_search``."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from skill_sdk.tool.tavily_search import (
    DEFAULT_TAVILY_BASE_URL,
    TavilySearchError,
    TavilySearchSettings,
    clear_tavily_search_cache,
    resolve_endpoint,
    resolve_tavily_api_key,
    resolve_tavily_base_url,
    run_tavily_search,
    tavily_search_as_json_str,
)


def _no_cache_settings(**kwargs: object) -> TavilySearchSettings:
    base: dict[str, object] = {
        "api_key": "test-key",
        "cache_ttl_minutes": 0.0,
        "timeout_seconds": 5.0,
    }
    base.update(kwargs)
    return TavilySearchSettings(**base)  # type: ignore[arg-type]


class TestTavilyResolveHelpers(unittest.TestCase):
    def test_resolve_endpoint_appends_path(self) -> None:
        self.assertEqual(
            resolve_endpoint("https://proxy.example/api/tavily", "/search"),
            "https://proxy.example/api/tavily/search",
        )
        self.assertEqual(
            resolve_endpoint("https://proxy.example/api/tavily/", "/extract"),
            "https://proxy.example/api/tavily/extract",
        )

    def test_resolve_endpoint_empty_uses_default_host(self) -> None:
        self.assertEqual(resolve_endpoint("", "/search"), f"{DEFAULT_TAVILY_BASE_URL}/search")

    def test_resolve_tavily_api_key_priority(self) -> None:
        settings = TavilySearchSettings(api_key="from-settings")
        self.assertEqual(
            resolve_tavily_api_key(api_key="  from-arg  ", settings=settings),
            "from-arg",
        )

    @patch.dict(os.environ, {"TAVILY_API_KEY": "from-env"}, clear=False)
    def test_resolve_tavily_api_key_falls_back_env(self) -> None:
        self.assertEqual(resolve_tavily_api_key(), "from-env")

    def test_resolve_tavily_base_url_priority(self) -> None:
        settings = TavilySearchSettings(base_url="https://cfg.example")
        self.assertEqual(
            resolve_tavily_base_url(base_url="https://arg.example", settings=settings),
            "https://arg.example",
        )

    @patch.dict(os.environ, {"TAVILY_BASE_URL": "https://env.example"}, clear=False)
    def test_resolve_tavily_base_url_falls_back_env(self) -> None:
        self.assertEqual(resolve_tavily_base_url(), "https://env.example")


class TestRunTavilySearch(unittest.TestCase):
    def setUp(self) -> None:
        clear_tavily_search_cache()

    def test_missing_api_key(self) -> None:
        old_key = os.environ.pop("TAVILY_API_KEY", None)
        try:
            with self.assertRaises(TavilySearchError) as ctx:
                run_tavily_search(
                    "hello",
                    settings=TavilySearchSettings(
                        api_key=None,
                        cache_ttl_minutes=0.0,
                        timeout_seconds=5.0,
                    ),
                )
        finally:
            if old_key is not None:
                os.environ["TAVILY_API_KEY"] = old_key
        self.assertIn("API key", str(ctx.exception))

    def test_empty_query(self) -> None:
        with self.assertRaises(TavilySearchError) as ctx:
            run_tavily_search("   ", settings=_no_cache_settings())
        self.assertIn("non-empty", str(ctx.exception))

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_success_maps_results_and_headers(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "T1",
                    "url": "https://a.example",
                    "content": "Snippet text",
                    "score": 0.9,
                    "published_date": "2024-01-01",
                }
            ],
            "answer": "Short answer",
        }
        mock_post.return_value = mock_resp

        out = run_tavily_search(
            "q1",
            max_results=3,
            search_depth="advanced",
            topic="news",
            include_answer=True,
            time_range="week",
            include_domains=["a.com"],
            exclude_domains=["b.com"],
            settings=_no_cache_settings(),
        )

        self.assertEqual(out["query"], "q1")
        self.assertEqual(out["provider"], "tavily")
        self.assertEqual(out["count"], 1)
        self.assertIn("tookMs", out)
        self.assertEqual(out["externalContent"]["provider"], "tavily")
        self.assertEqual(len(out["results"]), 1)
        row = out["results"][0]
        self.assertEqual(row["url"], "https://a.example")
        self.assertEqual(row["score"], 0.9)
        self.assertEqual(row["published"], "2024-01-01")
        self.assertIn("T1", row["title"])
        self.assertIn("Snippet text", row["snippet"])
        self.assertIn("answer", out)
        self.assertIn("Short answer", out["answer"])

        mock_post.assert_called_once()
        call_kw = mock_post.call_args.kwargs
        self.assertEqual(call_kw["headers"]["X-Client-Source"], "skill_sdk")
        self.assertTrue(call_kw["headers"]["Authorization"].startswith("Bearer "))
        body = json.loads(call_kw["data"])
        self.assertEqual(body["query"], "q1")
        self.assertEqual(body["max_results"], 3)
        self.assertEqual(body["search_depth"], "advanced")
        self.assertEqual(body["topic"], "news")
        self.assertTrue(body["include_answer"])
        self.assertEqual(body["time_range"], "week")
        self.assertEqual(body["include_domains"], ["a.com"])
        self.assertEqual(body["exclude_domains"], ["b.com"])

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_http_error_raises(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.reason = "Unauthorized"
        mock_resp.text = "nope"
        mock_post.return_value = mock_resp

        with self.assertRaises(TavilySearchError) as ctx:
            run_tavily_search("x", settings=_no_cache_settings())
        self.assertIn("401", str(ctx.exception))
        self.assertIn("nope", str(ctx.exception))

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_non_json_response_raises(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.side_effect = ValueError("not json")
        mock_post.return_value = mock_resp

        with self.assertRaises(TavilySearchError) as ctx:
            run_tavily_search("x", settings=_no_cache_settings())
        self.assertIn("non-JSON", str(ctx.exception))

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_non_dict_json_raises(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = []
        mock_post.return_value = mock_resp

        with self.assertRaises(TavilySearchError) as ctx:
            run_tavily_search("x", settings=_no_cache_settings())
        self.assertIn("unexpected JSON", str(ctx.exception))

    @patch("skill_sdk.tool.tavily_search.requests.post", side_effect=requests.ConnectionError("boom"))
    def test_request_exception_wraps(self, _mock_post: MagicMock) -> None:
        with self.assertRaises(TavilySearchError) as ctx:
            run_tavily_search("x", settings=_no_cache_settings())
        self.assertIn("request failed", str(ctx.exception).lower())

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_cache_second_call_skips_http(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp

        settings = TavilySearchSettings(api_key="k", cache_ttl_minutes=15.0, timeout_seconds=5.0)
        first = run_tavily_search("same", settings=settings)
        second = run_tavily_search("same", settings=settings)

        self.assertEqual(mock_post.call_count, 1)
        self.assertNotIn("cached", first)
        self.assertTrue(second.get("cached"))

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_max_results_clamped(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp

        run_tavily_search("q", max_results=99, settings=_no_cache_settings())
        body = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(body["max_results"], 20)


class TestTavilySearchAsJsonStr(unittest.TestCase):
    def setUp(self) -> None:
        clear_tavily_search_cache()

    @patch("skill_sdk.tool.tavily_search.requests.post")
    def test_round_trip_json(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp

        raw = tavily_search_as_json_str("hello", settings=_no_cache_settings())
        data = json.loads(raw)
        self.assertEqual(data["query"], "hello")
        self.assertEqual(data["provider"], "tavily")
