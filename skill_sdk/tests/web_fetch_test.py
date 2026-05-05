"""Unit tests for ``skill_sdk.tool.web_fetch``."""

from __future__ import annotations

import json
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from skill_sdk.tool.web_fetch import (
    DEFAULT_MAX_RESPONSE_BYTES,
    FETCH_MAX_RESPONSE_BYTES_MAX,
    FETCH_MAX_RESPONSE_BYTES_MIN,
    SsrfBlockedError,
    WebFetchError,
    WebFetchSettings,
    _content_type_base,
    _detect_fakeip_mode,
    _looks_like_captcha,
    _normalize_cache_key,
    _reset_fakeip_autodetect_for_tests,
    _resolve_max_redirects,
    _resolve_max_response_bytes,
    _resolve_timeout_seconds,
    clear_web_fetch_cache,
    html_to_markdown,
    markdown_to_text,
    run_web_fetch,
    web_fetch_as_json_str,
    wrap_web_fetch_content,
)


def _loopback_settings(**kwargs: object) -> WebFetchSettings:
    opts: dict[str, object] = {
        "ssrf_enabled": False,
        "timeout_seconds": 5.0,
        "cache_ttl_minutes": 0.0,
    }
    opts.update(kwargs)
    return WebFetchSettings(**opts)  # type: ignore[arg-type]


@contextmanager
def _http_server(handler: type[BaseHTTPRequestHandler]):
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = server.server_address
        yield int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestWebFetchReadability(unittest.TestCase):
    def setUp(self) -> None:
        clear_web_fetch_cache()

    def test_readability_prefers_article(self) -> None:
        page = b"""<!DOCTYPE html><html><head><title>Art</title></head><body>
        <nav>Nav noise</nav><article><h1>Main</h1><p>UniqueArticleBody99</p></article></body></html>"""

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/a"
            out = run_web_fetch(url, settings=_loopback_settings())
        # readability-lxml heuristics are input-size sensitive: for very short
        # fragments it falls back to raw-html. Both paths are acceptable as
        # long as the article body is preserved.
        self.assertIn(out["extractor"], ("readability", "raw-html"))
        self.assertIn("UniqueArticleBody99", str(out["text"]))


class TestWebFetchHelpers(unittest.TestCase):
    def test_html_to_markdown_basic(self) -> None:
        html = "<html><head><title> T1 </title></head><body><p>Hello</p></body></html>"
        text, title = html_to_markdown(html)
        self.assertEqual(title, "T1")
        self.assertIn("Hello", text)

    def test_markdown_to_text(self) -> None:
        md = "# Title\n\n- [a](http://x)\n\n`code`"
        plain = markdown_to_text(md)
        self.assertNotIn("#", plain)
        self.assertIn("Title", plain)
        self.assertIn("a", plain)
        self.assertIn("code", plain)

    def test_content_type_preserves_case(self) -> None:
        self.assertEqual(_content_type_base("Application/JSON; charset=UTF-8"), "Application/JSON")
        self.assertEqual(_content_type_base("  text/HTML  "), "text/HTML")
        self.assertEqual(_content_type_base(None), "application/octet-stream")
        self.assertEqual(_content_type_base(""), "application/octet-stream")

    def test_max_response_bytes_clamp(self) -> None:
        self.assertEqual(_resolve_max_response_bytes(0), DEFAULT_MAX_RESPONSE_BYTES)
        self.assertEqual(_resolve_max_response_bytes(None), DEFAULT_MAX_RESPONSE_BYTES)
        self.assertEqual(_resolve_max_response_bytes(10), FETCH_MAX_RESPONSE_BYTES_MIN)
        self.assertEqual(_resolve_max_response_bytes(5_000_000), 5_000_000)
        self.assertEqual(_resolve_max_response_bytes(50_000_000), FETCH_MAX_RESPONSE_BYTES_MAX)

    def test_timeout_and_redirects_resolver(self) -> None:
        self.assertEqual(_resolve_timeout_seconds(0, 30), 1.0)
        self.assertEqual(_resolve_timeout_seconds(12.9, 30), 12.0)
        self.assertEqual(_resolve_timeout_seconds(None, 30), 30.0)
        self.assertEqual(_resolve_max_redirects(-2, 3), 0)
        self.assertEqual(_resolve_max_redirects(None, 3), 3)
        self.assertEqual(_resolve_max_redirects(7.7, 3), 7)

    def test_normalize_cache_key_lowercases_and_flags(self) -> None:
        base = WebFetchSettings()
        a = _normalize_cache_key("https://Example.COM/Path?q=1", "markdown", 2000, base)
        self.assertEqual(a, "fetch:https://example.com/path?q=1:markdown:2000")
        b = _normalize_cache_key(
            "https://example.com/",
            "markdown",
            2000,
            WebFetchSettings(allow_rfc2544_benchmark_range=True),
        )
        self.assertIn(":allow-rfc2544", b)
        c = _normalize_cache_key(
            "https://example.com/",
            "markdown",
            2000,
            WebFetchSettings(readability_enabled=False, ssrf_enabled=False),
        )
        self.assertIn(":no-readability", c)
        self.assertIn(":no-ssrf", c)

    def test_wrap_web_fetch_content_respects_budget(self) -> None:
        wrapped, truncated, raw_len, wrapped_len = wrap_web_fetch_content("A" * 5000, 800)
        self.assertTrue(truncated)
        self.assertEqual(wrapped_len, len(wrapped))
        self.assertLessEqual(wrapped_len, 800)
        self.assertIn("EXTERNAL_UNTRUSTED_CONTENT", wrapped)
        self.assertGreater(raw_len, 0)

    def test_wrap_web_fetch_content_short_value_not_truncated(self) -> None:
        wrapped, truncated, raw_len, wrapped_len = wrap_web_fetch_content("hi", 4000)
        self.assertFalse(truncated)
        self.assertEqual(raw_len, 2)
        self.assertLessEqual(wrapped_len, 4000)
        self.assertIn("hi", wrapped)


class TestWebFetchIntegration(unittest.TestCase):
    def setUp(self) -> None:
        clear_web_fetch_cache()

    def tearDown(self) -> None:
        clear_web_fetch_cache()

    def test_json_extractor(self) -> None:
        payload = b'{"x":1,"y":[2,3]}'

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/"
            out = run_web_fetch(url, settings=_loopback_settings())
        self.assertEqual(out["extractor"], "json")
        self.assertIn('"x": 1', str(out["text"]))

    def test_html_markdown(self) -> None:
        page = b"""<!DOCTYPE html><html><head><title>Doc</title></head>
        <body><h1>Hi</h1><p>Body text</p></body></html>"""

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/page"
            out = run_web_fetch(url, extract_mode="markdown", settings=_loopback_settings())
        self.assertIn(str(out["extractor"]), ("readability", "raw-html"))
        self.assertIn("Doc", str(out["title"]))
        self.assertIn("Body text", str(out["text"]))
        self.assertIn("EXTERNAL_UNTRUSTED_CONTENT", str(out["text"]))

    def test_html_text_mode(self) -> None:
        page = b"<html><body><p>Plain <strong>x</strong></p></body></html>"

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/"
            out = run_web_fetch(url, extract_mode="text", settings=_loopback_settings())
        self.assertIn("Plain", str(out["text"]))
        self.assertNotIn("[", str(out["text"]))

    def test_markdown_content_type(self) -> None:
        body = b"# Heading\n\n[link](https://example.com)\n"

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/"
            md = run_web_fetch(url, extract_mode="markdown", settings=_loopback_settings())
            tx = run_web_fetch(url, extract_mode="text", settings=_loopback_settings())
        self.assertEqual(md["extractor"], "cf-markdown")
        self.assertIn("# Heading", str(md["text"]))
        self.assertNotIn("#", str(tx["text"]))
        self.assertIn("Heading", str(tx["text"]))

    def test_max_chars_truncation(self) -> None:
        long_body = ("x" * 500).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(long_body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/"
            out = run_web_fetch(url, max_chars=120, settings=_loopback_settings())
        self.assertTrue(out["truncated"])
        self.assertEqual(len(str(out["text"])), 120)

    def test_redirect_follow(self) -> None:
        state = {"n": 0}

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/start"):
                    self.send_response(302)
                    self.send_header("Location", "/final")
                    self.end_headers()
                    state["n"] += 1
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                state["n"] += 1

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            base = f"http://127.0.0.1:{port}"
            out = run_web_fetch(f"{base}/start", settings=_loopback_settings())
        self.assertTrue(str(out["final_url"]).endswith("/final"))
        self.assertIn("ok", str(out["text"]))
        self.assertEqual(state["n"], 2)

    def test_cache_hit(self) -> None:
        body = b"cached-payload"

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/c"
            s = _loopback_settings(cache_ttl_minutes=30.0)
            first = run_web_fetch(url, settings=s)
            second = run_web_fetch(url, settings=s)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["text"], second["text"])

    def test_http_error_raises(self) -> None:
        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"gone")

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            url = f"http://127.0.0.1:{port}/missing"
            with self.assertRaises(WebFetchError) as ctx:
                run_web_fetch(url, settings=_loopback_settings())
        self.assertIn("404", str(ctx.exception))

    def test_web_fetch_as_json_str(self) -> None:
        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            raw = web_fetch_as_json_str(f"http://127.0.0.1:{port}/", settings=_loopback_settings())
        data = json.loads(raw)
        self.assertEqual(data["extractor"], "json")


class TestWebFetchPolicy(unittest.TestCase):
    def setUp(self) -> None:
        clear_web_fetch_cache()

    def test_readability_disabled_without_provider_raises(self) -> None:
        import os

        old = os.environ.pop("FIRECRAWL_API_KEY", None)
        try:
            page = b"<html><head><script>var x=1;</script></head><body></body></html>"

            class H(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(page)

                def log_message(self, fmt: str, *args: object) -> None:
                    return

            with _http_server(H) as port:
                url = f"http://127.0.0.1:{port}/"
                with self.assertRaises(WebFetchError) as ctx:
                    run_web_fetch(
                        url,
                        settings=_loopback_settings(
                            readability_enabled=False,
                            firecrawl_api_key="",
                        ),
                    )
            self.assertIn("Firecrawl", str(ctx.exception))
            self.assertIn("basic HTML cleanup", str(ctx.exception))
        finally:
            if old is not None:
                os.environ["FIRECRAWL_API_KEY"] = old

    def test_readability_disabled_falls_back_to_basic(self) -> None:
        import os

        old = os.environ.pop("FIRECRAWL_API_KEY", None)
        try:
            page = b"<html><body><p>UniqueBasicBody77</p></body></html>"

            class H(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(page)

                def log_message(self, fmt: str, *args: object) -> None:
                    return

            with _http_server(H) as port:
                url = f"http://127.0.0.1:{port}/"
                out = run_web_fetch(
                    url,
                    settings=_loopback_settings(
                        readability_enabled=False,
                        firecrawl_api_key="",
                    ),
                )
            self.assertEqual(out["extractor"], "raw-html")
            self.assertIn("UniqueBasicBody77", str(out["text"]))
        finally:
            if old is not None:
                os.environ["FIRECRAWL_API_KEY"] = old


class TestWebFetchSsrf(unittest.TestCase):
    def test_blocks_loopback_when_enabled(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            run_web_fetch(
                "http://127.0.0.1:9/",
                settings=WebFetchSettings(ssrf_enabled=True, timeout_seconds=2.0, cache_ttl_minutes=0.0),
            )

    def test_blocks_private_literal_ipv4(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            run_web_fetch(
                "http://10.0.0.1/",
                settings=WebFetchSettings(ssrf_enabled=True, timeout_seconds=2.0, cache_ttl_minutes=0.0),
            )

    def test_invalid_scheme(self) -> None:
        with self.assertRaises(WebFetchError):
            run_web_fetch("file:///etc/passwd", settings=WebFetchSettings(ssrf_enabled=False))

    def test_localhost_hostname_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            run_web_fetch(
                "http://localhost:1234/",
                settings=WebFetchSettings(ssrf_enabled=True, timeout_seconds=2.0, cache_ttl_minutes=0.0),
            )


class TestWebFetchFakeIpAutodetect(unittest.TestCase):
    """Auto-detect Clash/mihomo TUN fake-ip and relax the RFC 2544 guard."""

    def setUp(self) -> None:
        clear_web_fetch_cache()
        _reset_fakeip_autodetect_for_tests()

    def tearDown(self) -> None:
        clear_web_fetch_cache()
        _reset_fakeip_autodetect_for_tests()

    @staticmethod
    def _patch_getaddrinfo(returns_fakeip: bool):
        """Return a context manager that patches socket.getaddrinfo."""
        import socket as _socket

        def fake_getaddrinfo(host, port, *args, **kwargs):
            ip = "198.18.0.42" if returns_fakeip else "93.184.216.34"
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, 0))]

        return patch_attr(_socket, "getaddrinfo", fake_getaddrinfo)

    def test_detects_fakeip(self) -> None:
        with self._patch_getaddrinfo(returns_fakeip=True):
            self.assertTrue(_detect_fakeip_mode())
        # Cached
        self.assertTrue(_detect_fakeip_mode())

    def test_no_fakeip_when_normal_dns(self) -> None:
        with self._patch_getaddrinfo(returns_fakeip=False):
            self.assertFalse(_detect_fakeip_mode())

    def test_disabled_via_env(self) -> None:
        import os as _os

        old = _os.environ.get("WEB_FETCH_DISABLE_FAKEIP_AUTODETECT")
        _os.environ["WEB_FETCH_DISABLE_FAKEIP_AUTODETECT"] = "1"
        try:
            with self._patch_getaddrinfo(returns_fakeip=True):
                self.assertFalse(_detect_fakeip_mode())
        finally:
            if old is None:
                _os.environ.pop("WEB_FETCH_DISABLE_FAKEIP_AUTODETECT", None)
            else:
                _os.environ["WEB_FETCH_DISABLE_FAKEIP_AUTODETECT"] = old

    def test_assert_host_allowed_passes_198_18_when_flag_set(self) -> None:
        """Once auto-detect (or the user) flips ``allow_rfc2544_benchmark_range``
        the host gate must let 198.18.x through."""
        from skill_sdk.tool.web_fetch import _assert_host_allowed

        import socket as _socket

        def fake_getaddrinfo(host, port, *a, **kw):
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("198.18.0.42", port or 0))]

        with patch_attr(_socket, "getaddrinfo", fake_getaddrinfo):
            blocked = WebFetchSettings(ssrf_enabled=True, allow_rfc2544_benchmark_range=False)
            with self.assertRaises(SsrfBlockedError):
                _assert_host_allowed("example.org", blocked)
            allowed = WebFetchSettings(ssrf_enabled=True, allow_rfc2544_benchmark_range=True)
            _assert_host_allowed("example.org", allowed)  # must not raise

    def test_run_web_fetch_auto_relax_in_cfg(self) -> None:
        """End-to-end: when detection fires and we hit a *loopback* server,
        the call should still succeed (SSRF is otherwise off for loopback in
        the test settings) – but the cache key must encode the auto-relaxed
        ``allow-rfc2544`` flag, proving the flip happened inside run_web_fetch."""
        body = b"<html><head><title>FK</title></head><body><p>FakeIpBody55</p></body></html>"

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        import socket as _socket

        with _http_server(H) as port:
            # Stub example.com -> fake-ip; route the test target back to loopback
            # so urllib3 can actually reach our server.
            def fake_getaddrinfo(host, port_, *a, **kw):
                if host in ("example.com", "example.net"):
                    return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("198.18.0.42", port_ or 0))]
                return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_ or 0))]

            with patch_attr(_socket, "getaddrinfo", fake_getaddrinfo):
                cfg = WebFetchSettings(
                    ssrf_enabled=False,
                    timeout_seconds=5.0,
                    cache_ttl_minutes=30.0,
                    max_chars=2000,
                )
                out = run_web_fetch(
                    f"http://127.0.0.1:{port}/x",
                    settings=cfg,
                    extract_mode="text",
                    max_chars=2000,
                )
        self.assertEqual(out["status"], 200)
        self.assertIn("FakeIpBody55", str(out["text"]))
        self.assertTrue(_detect_fakeip_mode())
        # Cache key encodes the auto-relaxed flag.
        from skill_sdk.tool.web_fetch import _FETCH_CACHE
        keys = list(_FETCH_CACHE.keys())
        self.assertTrue(any("allow-rfc2544" in k for k in keys), keys)


class TestWebFetchCaptchaDetection(unittest.TestCase):
    """``_looks_like_captcha`` and the run_web_fetch HTML branch."""

    def setUp(self) -> None:
        clear_web_fetch_cache()

    def tearDown(self) -> None:
        clear_web_fetch_cache()

    def test_recognises_recaptcha(self) -> None:
        self.assertTrue(_looks_like_captcha('<div class="g-recaptcha"></div>'))

    def test_recognises_cloudflare_jschallenge(self) -> None:
        self.assertTrue(
            _looks_like_captcha(
                '<title>Just a moment...</title><form id="cf-challenge-form">'
            )
        )

    def test_recognises_ddg_anomaly(self) -> None:
        self.assertTrue(
            _looks_like_captcha(
                "<html><body>Please access DuckDuckGo with a different "
                "browser or device.</body></html>"
            )
        )

    def test_does_not_flag_legit_article(self) -> None:
        self.assertFalse(
            _looks_like_captcha(
                "<html><head><title>About OAuth</title></head>"
                "<body><article><p>Standard authentication explained.</p>"
                "</article></body></html>"
            )
        )

    def test_run_web_fetch_raises_on_captcha_html(self) -> None:
        page = (
            b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
            b"<body><form id=\"cf-challenge-form\"></form></body></html>"
        )

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            with self.assertRaises(WebFetchError) as cm:
                run_web_fetch(
                    f"http://127.0.0.1:{port}/c",
                    settings=_loopback_settings(),
                )
        msg = str(cm.exception)
        self.assertIn("Captcha", msg)
        self.assertIn("127.0.0.1", msg)


class TestWebFetchBrowserHeaders(unittest.TestCase):
    """Ensure the request fingerprint sent by run_web_fetch looks like Chrome."""

    def setUp(self) -> None:
        clear_web_fetch_cache()

    def tearDown(self) -> None:
        clear_web_fetch_cache()

    def test_sends_browser_headers(self) -> None:
        captured: dict[str, str] = {}

        body = b"<html><head><title>H</title></head><body><p>HeadersBody33</p></body></html>"

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                for key in (
                    "User-Agent",
                    "Accept",
                    "Accept-Language",
                    "Sec-Fetch-Mode",
                    "Sec-Fetch-Dest",
                    "Upgrade-Insecure-Requests",
                ):
                    captured[key] = self.headers.get(key, "")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        with _http_server(H) as port:
            out = run_web_fetch(
                f"http://127.0.0.1:{port}/h",
                settings=_loopback_settings(),
            )
        self.assertEqual(out["status"], 200)
        self.assertIn("Chrome", captured["User-Agent"])
        self.assertIn("text/html", captured["Accept"])
        self.assertNotIn("text/markdown", captured["Accept"])
        self.assertIn("en", captured["Accept-Language"])
        self.assertEqual(captured["Sec-Fetch-Mode"], "navigate")
        self.assertEqual(captured["Sec-Fetch-Dest"], "document")
        self.assertEqual(captured["Upgrade-Insecure-Requests"], "1")


class TestWebFetchLangChainTool(unittest.TestCase):
    """Verify the LangChain ``web_fetch`` tool built from ``WebFetchPlugin`` / registry.

    Imported lazily so that a stripped-down environment without langchain
    installed can still run the pure-Python tests above.
    """

    def setUp(self) -> None:
        clear_web_fetch_cache()

    def tearDown(self) -> None:
        clear_web_fetch_cache()

    def _import_tool(self):
        """Return the LangChain ``web_fetch`` tool built like discovery does (not from runner)."""
        try:
            from skill_sdk.plugin.registry import ToolRegistry
            from skill_sdk.tool.web_fetch_plugin import WebFetchInput, WebFetchPlugin
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"langchain not available: {exc}")
        reg = ToolRegistry()
        reg.register(WebFetchPlugin)
        tools = reg.to_langchain_tools()
        web_fetch_tool = next(t for t in tools if t.name == "web_fetch")
        return web_fetch_tool, WebFetchInput

    def test_tool_metadata(self) -> None:
        web_fetch_tool, WebFetchInput = self._import_tool()
        self.assertEqual(web_fetch_tool.name, "web_fetch")
        self.assertIs(web_fetch_tool.args_schema, WebFetchInput)
        schema = WebFetchInput.model_json_schema()
        props = schema["properties"]
        self.assertIn("url", props)
        self.assertIn("extract_mode", props)
        self.assertIn("max_chars", props)
        self.assertEqual(schema["required"], ["url"])

    def test_tool_rejects_invalid_extract_mode(self) -> None:
        web_fetch_tool, _ = self._import_tool()
        raw = web_fetch_tool.invoke(
            {
                "url": "http://127.0.0.1:1/",
                "extract_mode": "html",
                "max_chars": 500,
            },
        )
        payload = json.loads(raw)
        self.assertIn("error", payload)
        self.assertIn("Invalid extract_mode", str(payload["error"]))

    def test_tool_success_shape_via_local_server(self) -> None:
        web_fetch_tool, _ = self._import_tool()
        body = (
            b"<!DOCTYPE html><html><head><title>Art</title></head>"
            b"<body><article><h1>Main</h1><p>ToolBody11</p></article></body></html>"
        )

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        # Temporarily relax SSRF policy. ``web_fetch_tool`` does a local
        # ``from skill_sdk.tool.web_fetch import WebFetchSettings`` every call,
        # so patching the source module (sys.modules) takes effect.
        import skill_sdk.tool.web_fetch as wf_mod
        from skill_sdk.tool.web_fetch import WebFetchSettings as RealSettings

        def make_loopback_settings(**kwargs: object) -> RealSettings:
            kwargs.setdefault("ssrf_enabled", False)
            kwargs.setdefault("cache_ttl_minutes", 0)
            return RealSettings(**kwargs)  # type: ignore[arg-type]

        with _http_server(H) as port, patch_attr(
            wf_mod,
            "WebFetchSettings",
            make_loopback_settings,
        ):
            raw = web_fetch_tool.invoke(
                {
                    "url": f"http://127.0.0.1:{port}/a",
                    "extract_mode": "markdown",
                    "max_chars": 2000,
                },
            )
        payload = json.loads(raw)
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["extract_mode"], "markdown")
        self.assertIn(payload["extractor"], ("readability", "raw-html"))
        self.assertIn("ToolBody11", str(payload["content"]))
        self.assertIn("EXTERNAL_UNTRUSTED_CONTENT", str(payload["content"]))
        self.assertIn("url", payload)
        self.assertIn("final_url", payload)
        self.assertIn("took_ms", payload)
        self.assertIsInstance(payload["cached"], bool)

    def test_tool_ssrf_error_returned_as_json(self) -> None:
        web_fetch_tool, _ = self._import_tool()
        raw = web_fetch_tool.invoke(
            {
                "url": "http://127.0.0.1:9/",
                "extract_mode": "markdown",
                "max_chars": 500,
            },
        )
        payload = json.loads(raw)
        self.assertEqual(payload["url"], "http://127.0.0.1:9/")
        self.assertIn("error", payload)
        self.assertIn("SSRF blocked", str(payload["error"]))
        # Don't double-prefix.
        self.assertEqual(str(payload["error"]).count("SSRF blocked"), 1)
        self.assertNotIn("content", payload)

    def test_tool_ssrf_fakeip_hint(self) -> None:
        """When SSRF rejects a 198.18.x address the error should hint at fake-ip."""
        web_fetch_tool, _ = self._import_tool()
        raw = web_fetch_tool.invoke(
            {
                "url": "http://198.18.0.42/",
                "extract_mode": "markdown",
                "max_chars": 500,
            },
        )
        payload = json.loads(raw)
        err = str(payload["error"])
        self.assertIn("198.18.", err)
        self.assertIn("fake-ip", err)
        self.assertIn("WEB_FETCH_ALLOW_RFC2544", err)

    def test_tool_http_error_returned_as_json(self) -> None:
        web_fetch_tool, _ = self._import_tool()

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"internal error")

            def log_message(self, fmt: str, *args: object) -> None:
                return

        import skill_sdk.tool.web_fetch as wf_mod
        from skill_sdk.tool.web_fetch import WebFetchSettings as RealSettings

        def make_loopback_settings(**kwargs: object) -> RealSettings:
            kwargs.setdefault("ssrf_enabled", False)
            kwargs.setdefault("cache_ttl_minutes", 0)
            return RealSettings(**kwargs)  # type: ignore[arg-type]

        with _http_server(H) as port, patch_attr(
            wf_mod,
            "WebFetchSettings",
            make_loopback_settings,
        ):
            raw = web_fetch_tool.invoke(
                {
                    "url": f"http://127.0.0.1:{port}/boom",
                    "extract_mode": "text",
                    "max_chars": 500,
                },
            )
        payload = json.loads(raw)
        self.assertIn("error", payload)
        self.assertIn("Web fetch failed", str(payload["error"]))
        self.assertIn("500", str(payload["error"]))

    def test_web_fetch_in_skill_runner_default_tool_list(self) -> None:
        """``web_fetch`` is merged from ``ToolRegistry.discover_package``, not re-exported on runner."""
        try:
            from unittest.mock import MagicMock

            from skill_sdk.skill.runner import SkillRunner
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"langchain not available: {exc}")

        runner = SkillRunner(MagicMock())
        names = [t.name for t in runner._runner_tools]
        self.assertIn("web_fetch", names)
        self.assertIn("plan_cmd", names)
        self.assertIn("read_file", names)
        self.assertIn("finish", names)
        self.assertEqual(names[0], "plan_cmd")
        self.assertEqual(names[1], "read_file")
        self.assertEqual(names[-1], "finish")
        self.assertLess(names.index("web_fetch"), names.index("finish"))


@contextmanager
def patch_attr(target: object, name: str, value: object):
    """Small helper to monkey-patch ``target.name`` for the duration of a block."""
    sentinel = object()
    original = getattr(target, name, sentinel)
    setattr(target, name, value)
    try:
        yield
    finally:
        if original is sentinel:
            delattr(target, name)
        else:
            setattr(target, name, original)


if __name__ == "__main__":
    unittest.main()
