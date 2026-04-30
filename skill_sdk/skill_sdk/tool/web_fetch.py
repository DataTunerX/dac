from __future__ import annotations

import html as html_module
import ipaddress
import json
import logging
import math
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

from skill_sdk.security.external_content import wrap_external_content, wrap_web_content
from skill_sdk.tool.web_fetch_extract import (
    extract_readable_readability,
    sanitize_html,
    strip_invisible_unicode,
)

ExtractMode = Literal["markdown", "text"]

DEFAULT_MAX_CHARS = 20_000
DEFAULT_MAX_RESPONSE_BYTES = 750_000
FETCH_MAX_RESPONSE_BYTES_MIN = 32_000
FETCH_MAX_RESPONSE_BYTES_MAX = 10_000_000
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_CACHE_TTL_MINUTES = 15
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_ERROR_MAX_CHARS = 4000
DEFAULT_ERROR_MAX_BYTES = 64_000
_CACHE_MAX_ENTRIES = 100

FIRECRAWL_ALLOWED_HOSTS = frozenset({"api.firecrawl.dev"})

_WRAPPER_OVERHEADS: tuple[int, int] | None = None


class WebFetchError(Exception):
    """Raised when ``web_fetch`` cannot complete (invalid input, SSRF, HTTP error, etc.)."""


class SsrfBlockedError(WebFetchError):
    """Raised when the resolved target is not allowed by the SSRF policy."""


@dataclass
class WebFetchSettings:
    max_chars: int = DEFAULT_MAX_CHARS
    max_chars_cap: int = DEFAULT_MAX_CHARS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_minutes: float = DEFAULT_CACHE_TTL_MINUTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    user_agent: str = DEFAULT_USER_AGENT
    ssrf_enabled: bool = True
    readability_enabled: bool = True
    allow_rfc2544_benchmark_range: bool = False
    firecrawl_api_key: str | None = None
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_only_main_content: bool = True
    firecrawl_timeout_seconds: float | None = None


_FETCH_CACHE: dict[str, tuple[float, dict[str, object]]] = {}


def clear_web_fetch_cache() -> None:
    _FETCH_CACHE.clear()


def _cache_ttl_ms(settings: WebFetchSettings) -> float:
    return max(0.0, settings.cache_ttl_minutes * 60_000)


def _cache_get(key: str, ttl_ms: float) -> dict[str, object] | None:
    if ttl_ms <= 0:
        return None
    entry = _FETCH_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _FETCH_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: dict[str, object], ttl_ms: float) -> None:
    if ttl_ms <= 0:
        return
    if len(_FETCH_CACHE) >= _CACHE_MAX_ENTRIES:
        try:
            first = next(iter(_FETCH_CACHE))
            _FETCH_CACHE.pop(first, None)
        except StopIteration:
            pass
    _FETCH_CACHE[key] = (time.monotonic() + ttl_ms / 1000.0, value)


def _normalize_cache_key(
    url: str,
    extract_mode: ExtractMode,
    max_chars: int,
    settings: WebFetchSettings,
) -> str:
    rfc = ":allow-rfc2544" if settings.allow_rfc2544_benchmark_range else ""
    rd = ":no-readability" if not settings.readability_enabled else ""
    ssrf = "" if settings.ssrf_enabled else ":no-ssrf"
    raw = f"fetch:{url}:{extract_mode}:{max_chars}{rfc}{rd}{ssrf}"
    return raw.lower()


def _clamp_max_chars(requested: int | None, fallback: int, cap: int) -> int:
    if requested is None:
        base_value: float = float(fallback)
    else:
        try:
            base_value = float(requested)
        except (TypeError, ValueError):
            base_value = float(fallback)
    if not math.isfinite(base_value):
        base_value = float(fallback)
    clamped = max(100, int(math.floor(base_value)))
    cap_value = max(100, int(math.floor(float(cap))))
    return min(clamped, cap_value)


def _resolve_timeout_seconds(value: float | None, fallback: float) -> float:
    if value is None or not math.isfinite(float(value)):
        v = float(fallback)
    else:
        v = float(value)
    return float(max(1, math.floor(v)))


def _resolve_max_redirects(value: int | None, fallback: int) -> int:
    if value is None:
        return max(0, int(fallback))
    try:
        v = float(value)
    except (TypeError, ValueError):
        return max(0, int(fallback))
    if not math.isfinite(v):
        return max(0, int(fallback))
    return max(0, int(math.floor(v)))


def _resolve_max_response_bytes(value: int | None) -> int:
    if value is None:
        return DEFAULT_MAX_RESPONSE_BYTES
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RESPONSE_BYTES
    if not math.isfinite(v) or v <= 0:
        return DEFAULT_MAX_RESPONSE_BYTES
    floored = int(math.floor(v))
    return min(FETCH_MAX_RESPONSE_BYTES_MAX, max(FETCH_MAX_RESPONSE_BYTES_MIN, floored))


def _parse_url(url: str) -> tuple[str, str | None]:
    raw = (url or "").strip()
    if not raw:
        raise WebFetchError("URL is required")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise WebFetchError("Invalid URL") from exc
    if parsed.scheme not in ("http", "https"):
        raise WebFetchError("Invalid URL: must be http or https")
    host = parsed.hostname
    if not host:
        raise WebFetchError("Invalid URL: missing host")
    return raw, host


def _ip_blocked(addr: str, *, allow_rfc2544_benchmark_range: bool) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if allow_rfc2544_benchmark_range and ip in ipaddress.ip_network("198.18.0.0/15"):
        return False
    if ip.version == 4:
        nets = (
            ipaddress.ip_network("0.0.0.0/8"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("192.0.0.0/24"),
            ipaddress.ip_network("192.0.2.0/24"),
            ipaddress.ip_network("192.88.99.0/24"),
            ipaddress.ip_network("198.18.0.0/15"),
            ipaddress.ip_network("198.51.100.0/24"),
            ipaddress.ip_network("203.0.113.0/24"),
            ipaddress.ip_network("224.0.0.0/4"),
            ipaddress.ip_network("240.0.0.0/4"),
        )
        return any(ip in net for net in nets)
    nets6 = (
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("ff00::/8"),
        ipaddress.ip_network("::/128"),
        ipaddress.ip_network("2001:db8::/32"),
    )
    if ip.is_multicast or ip.is_link_local or ip.is_loopback or ip.is_private:
        return True
    if ip.is_reserved:
        return True
    return any(ip in net for net in nets6)


def _assert_host_allowed(hostname: str, settings: WebFetchSettings) -> None:
    lowered = hostname.strip().lower()
    if lowered in ("localhost",) or lowered.endswith(".localhost"):
        raise SsrfBlockedError(f"SSRF blocked: host {hostname!r}")
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebFetchError(f"DNS resolution failed for host {hostname!r}") from exc
    if not infos:
        raise WebFetchError(f"No addresses returned for host {hostname!r}")
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if _ip_blocked(ip_str, allow_rfc2544_benchmark_range=settings.allow_rfc2544_benchmark_range):
            raise SsrfBlockedError(f"SSRF blocked: resolved {hostname!r} -> {ip_str}")


# ---------------------------------------------------------------------------
# Fake-IP TUN auto-detection
# ---------------------------------------------------------------------------
#
# Clash / mihomo / sing-box TUN drivers in "fake-ip" mode synthesise IPs in
# 198.18.0.0/15 (RFC 2544 benchmark range) for any public hostname, then
# intercept the TCP connection at the TUN layer and proxy the real upstream.
#
# Our default SSRF policy treats those addresses as forbidden, which – on a
# user laptop running a TUN proxy – incorrectly blocks legitimate public
# hosts (lite.duckduckgo.com, en.wikipedia.org, ...). Probe a stable IANA
# host once per process; if it resolves into 198.18.0.0/15, auto-relax the
# RFC 2544 guard for the rest of the process.
#
# Set ``WEB_FETCH_DISABLE_FAKEIP_AUTODETECT=1`` to opt out.
_FAKEIP_PROBE_HOSTS: tuple[str, ...] = ("example.com", "example.net")
_FAKEIP_AUTODETECT_RESULT: bool | None = None
_FAKEIP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _detect_fakeip_mode() -> bool:
    """Return True if local DNS appears to be in TUN fake-ip mode (cached)."""
    global _FAKEIP_AUTODETECT_RESULT
    if _FAKEIP_AUTODETECT_RESULT is not None:
        return _FAKEIP_AUTODETECT_RESULT
    if os.environ.get("WEB_FETCH_DISABLE_FAKEIP_AUTODETECT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _FAKEIP_AUTODETECT_RESULT = False
        return False
    for host in _FAKEIP_PROBE_HOSTS:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            continue
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, TypeError, IndexError):
                continue
            if ip in _FAKEIP_NETWORK:
                _FAKEIP_AUTODETECT_RESULT = True
                return True
    _FAKEIP_AUTODETECT_RESULT = False
    return False


def _reset_fakeip_autodetect_for_tests() -> None:
    """Clear the cached fake-ip detection result. Test-only."""
    global _FAKEIP_AUTODETECT_RESULT
    _FAKEIP_AUTODETECT_RESULT = None


# ---------------------------------------------------------------------------
# Anti-bot / captcha detection
# ---------------------------------------------------------------------------
#
# Search engines (DDG, Google, Bing) and Cloudflare-protected sites serve a
# captcha / "are you a human?" interstitial when our fingerprint looks like
# a bot. The HTML body is technically valid but contains no useful content,
# so Readability happily extracts "please complete the verification" as the
# article body and ships it to the LLM. Detect the common variants up front
# and surface a clear, actionable error instead.
_CAPTCHA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<title[^>]*>[^<]{0,120}(captcha|just a moment|verify you|are you a human)", re.IGNORECASE),
    re.compile(r"\b(g-recaptcha|h-captcha|hcaptcha|grecaptcha)\b", re.IGNORECASE),
    re.compile(r"data-(sitekey|hcaptcha-sitekey)\s*=", re.IGNORECASE),
    re.compile(r"cf-(challenge-form|chl-bypass|chl-opt|browser-verification)", re.IGNORECASE),
    re.compile(r"checking your browser before accessing", re.IGNORECASE),
    re.compile(r"please access duckduckgo with a different", re.IGNORECASE),
    re.compile(r"unusual traffic from your", re.IGNORECASE),
    re.compile(r"to continue, please type the characters", re.IGNORECASE),
)


def _looks_like_captcha(html: str) -> bool:
    """Heuristic: True if the HTML body looks like an anti-bot interstitial."""
    if not html:
        return False
    # Captcha pages are almost always small. Restrict scan to the first
    # 32KB to keep the cost bounded and avoid false positives from long
    # articles that *mention* the word "captcha".
    snippet = html[:32_000]
    return any(p.search(snippet) for p in _CAPTCHA_PATTERNS)


def truncate_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _normalize_ws(value: str) -> str:
    text = value.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _decode_entities(value: str) -> str:
    return html_module.unescape(value)


def _strip_tags(value: str) -> str:
    return _decode_entities(re.sub(r"<[^>]+>", "", value))


def html_to_markdown(html: str) -> tuple[str, str | None]:
    title_m = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.I)
    title: str | None = None
    if title_m:
        title = _normalize_ws(_strip_tags(title_m.group(1))) or None
    text = html
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", "", text, flags=re.I)

    def _link_repl(m: re.Match[str]) -> str:
        href, body = m.group(1), m.group(2)
        label = _normalize_ws(_strip_tags(body))
        if not label:
            return href
        return f"[{label}]({href})"

    text = re.sub(
        r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
        _link_repl,
        text,
        flags=re.I,
    )

    def _heading_repl(m: re.Match[str]) -> str:
        level = int(m.group(1))
        body = m.group(2)
        prefix = "#" * max(1, min(6, level))
        label = _normalize_ws(_strip_tags(body))
        return f"\n{prefix} {label}\n"

    text = re.sub(r"<h([1-6])[^>]*>([\s\S]*?)</h\1>", _heading_repl, text, flags=re.I)

    def _li_repl(m: re.Match[str]) -> str:
        label = _normalize_ws(_strip_tags(m.group(1)))
        return f"\n- {label}" if label else ""

    text = re.sub(r"<li[^>]*>([\s\S]*?)</li>", _li_repl, text, flags=re.I)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(
        r"</(p|div|section|article|header|footer|table|tr|ul|ol)>",
        "\n",
        text,
        flags=re.I,
    )
    text = _strip_tags(text)
    text = _normalize_ws(text)
    return text, title


def _strip_markdown_fenced_code_block(match: re.Match[str]) -> str:
    block = match.group(0)
    stripped = re.sub(r"```[^\n]*\n?", "", block)
    return stripped.replace("```", "")


def markdown_to_text(markdown: str) -> str:
    text = markdown
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", _strip_markdown_fenced_code_block, text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)
    return _normalize_ws(text)


def _content_type_base(value: str | None) -> str:
    """Return the trimmed media-type portion **preserving case**."""
    if not value:
        return "application/octet-stream"
    raw = value.split(";", 1)[0].strip()
    return raw or "application/octet-stream"


def _read_body_limited(resp: requests.Response, max_bytes: int) -> tuple[bytes, bool]:
    total = 0
    chunks: list[bytes] = []
    truncated = False
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            truncated = True
            allowed = len(chunk) - (total - max_bytes)
            if allowed > 0:
                chunks.append(chunk[:allowed])
            break
        chunks.append(chunk)
    return b"".join(chunks), truncated


def _get_wrapper_overheads() -> tuple[int, int]:
    global _WRAPPER_OVERHEADS
    if _WRAPPER_OVERHEADS is None:
        _WRAPPER_OVERHEADS = (
            len(wrap_web_content("", "web_fetch")),
            len(wrap_external_content("", source="web_fetch", include_warning=False)),
        )
    return _WRAPPER_OVERHEADS


def _wrap_web_fetch_field(value: str | None) -> str | None:
    if not value:
        return value
    return wrap_external_content(value, source="web_fetch", include_warning=False)


def wrap_web_fetch_content(
    value: str,
    max_chars: int,
) -> tuple[str, bool, int, int]:
    warn_len, no_warn_len = _get_wrapper_overheads()
    if max_chars <= 0:
        return "", True, 0, 0
    include_warning = max_chars >= warn_len
    wrapper_overhead = warn_len if include_warning else no_warn_len
    if wrapper_overhead > max_chars:
        minimal = wrap_web_content("", "web_fetch") if include_warning else wrap_external_content(
            "",
            source="web_fetch",
            include_warning=False,
        )
        truncated_wrapper, trunc = truncate_text(minimal, max_chars)
        return truncated_wrapper, True, 0, len(truncated_wrapper)
    max_inner = max(0, max_chars - wrapper_overhead)
    truncated_text, inner_trunc = truncate_text(value, max_inner)
    wrapped_text = (
        wrap_web_content(truncated_text, "web_fetch")
        if include_warning
        else wrap_external_content(truncated_text, source="web_fetch", include_warning=False)
    )
    if len(wrapped_text) > max_chars:
        excess = len(wrapped_text) - max_chars
        adjusted_max_inner = max(0, max_inner - excess)
        truncated_text, inner_trunc = truncate_text(value, adjusted_max_inner)
        wrapped_text = (
            wrap_web_content(truncated_text, "web_fetch")
            if include_warning
            else wrap_external_content(truncated_text, source="web_fetch", include_warning=False)
        )
    return wrapped_text, inner_trunc, len(truncated_text), len(wrapped_text)


def _format_web_fetch_error_detail(
    detail: str,
    *,
    content_type: str | None,
    max_chars: int,
) -> str:
    if not detail:
        return ""
    text = detail
    ct = (content_type or "").lower()
    if "text/html" in ct:
        rendered, t = html_to_markdown(detail)
        with_title = f"{t}\n{rendered}" if t else rendered
        text = markdown_to_text(with_title)
    trimmed = text.strip()
    out, _ = truncate_text(trimmed, max_chars)
    return out


def _extract_from_html_basic(body: str, extract_mode: ExtractMode) -> tuple[str, str | None, str]:
    clean = sanitize_html(body)
    md, title = html_to_markdown(clean)
    if extract_mode == "text":
        plain = strip_invisible_unicode(markdown_to_text(md)) or strip_invisible_unicode(
            _normalize_ws(_strip_tags(clean)),
        )
        return plain, title, "raw-html"
    text = strip_invisible_unicode(md)
    return text, title, "raw-html"


def _resolve_firecrawl_api_key(settings: WebFetchSettings) -> str | None:
    if settings.firecrawl_api_key and str(settings.firecrawl_api_key).strip():
        return str(settings.firecrawl_api_key).strip()
    v = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    return v or None


def _try_firecrawl_fetch(
    target_url: str,
    settings: WebFetchSettings,
) -> dict[str, object] | None:
    """Call Firecrawl ``/v2/scrape`` and return a normalized dict or ``None``.

    Returned dict keys: ``markdown``, ``title``, ``final_url``, ``status``.
    """
    key = _resolve_firecrawl_api_key(settings)
    if not key:
        return None
    base = (settings.firecrawl_base_url or "https://api.firecrawl.dev").strip().rstrip("/")
    p = urlparse(base)
    if p.scheme != "https" or not p.hostname or p.hostname not in FIRECRAWL_ALLOWED_HOSTS:
        raise WebFetchError(
            f"Firecrawl baseUrl host is not allowed: {getattr(p, 'hostname', None)!r}",
        )
    endpoint = f"https://{p.hostname}/v2/scrape"
    timeout = float(settings.firecrawl_timeout_seconds or settings.timeout_seconds)
    body = {
        "url": target_url,
        "formats": ["markdown"],
        "onlyMainContent": settings.firecrawl_only_main_content,
        "timeout": int(timeout * 1000),
    }
    try:
        r = requests.post(
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=min(timeout + 15.0, 120.0),
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    try:
        payload = r.json()
    except Exception:
        return None
    if payload.get("success") is False:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    md = data.get("markdown") or data.get("content")
    if not (isinstance(md, str) and md.strip()):
        return None
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    title = None
    mt = metadata.get("title") if isinstance(metadata, dict) else None
    if isinstance(mt, str) and mt.strip():
        title = mt.strip()
    final_url = target_url
    src = metadata.get("sourceURL") if isinstance(metadata, dict) else None
    if isinstance(src, str) and src.strip():
        final_url = src.strip()
    elif isinstance(data.get("url"), str) and data["url"].strip():
        final_url = data["url"].strip()
    status: int | None = None
    sc = metadata.get("statusCode") if isinstance(metadata, dict) else None
    if isinstance(sc, int):
        status = sc
    elif isinstance(data.get("statusCode"), int):
        status = int(data["statusCode"])
    return {
        "markdown": md.strip(),
        "title": title,
        "final_url": final_url,
        "status": status,
    }


def _build_firecrawl_payload(
    fc: dict[str, object],
    *,
    requested_url: str,
    extract_mode: ExtractMode,
    max_out: int,
    took_ms: int,
) -> dict[str, object]:
    md_raw = str(fc.get("markdown") or "")
    final_url = str(fc.get("final_url") or requested_url)
    status_val = fc.get("status")
    status_int = int(status_val) if isinstance(status_val, int) else 200
    text_body = markdown_to_text(md_raw) if extract_mode == "text" else md_raw
    text_body = strip_invisible_unicode(text_body)
    wrapped_warning = None
    wrapped_title = _wrap_web_fetch_field(fc.get("title") if isinstance(fc.get("title"), str) else None)
    wrapped, trunc, raw_len, wrapped_len = wrap_web_fetch_content(text_body or "", max_out)
    return {
        "url": requested_url,
        "final_url": final_url,
        "status": status_int,
        "content_type": "text/markdown",
        "title": wrapped_title,
        "extract_mode": extract_mode,
        "extractor": "firecrawl",
        "external_content": {"untrusted": True, "source": "web_fetch", "wrapped": True},
        "truncated": trunc,
        "length": wrapped_len,
        "raw_length": raw_len,
        "wrapped_length": wrapped_len,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "took_ms": took_ms,
        "text": wrapped,
        "warning": wrapped_warning,
        "cached": False,
    }


def _extract_html_pipeline(
    body: str,
    *,
    page_url: str,
    extract_mode: ExtractMode,
    settings: WebFetchSettings,
) -> tuple[str, str | None, str]:
    if settings.readability_enabled:
        rr = extract_readable_readability(
            body,
            page_url=page_url,
            extract_mode=extract_mode,
            html_to_markdown=html_to_markdown,
            markdown_to_text=markdown_to_text,
            normalize_ws=_normalize_ws,
        )
        if rr:
            return rr
        fc = _try_firecrawl_fetch(page_url, settings)
        if fc:
            md = str(fc["markdown"])
            title = fc.get("title")  # type: ignore[assignment]
            text = markdown_to_text(md) if extract_mode == "text" else md
            return text, title, "firecrawl"  # type: ignore[return-value]
        text, title, ext = _extract_from_html_basic(body, extract_mode)
        if not (text or "").strip():
            raise WebFetchError(
                "Web fetch extraction failed: Readability, Firecrawl, and basic HTML cleanup returned no content.",
            )
        return text, title, ext

    fc = _try_firecrawl_fetch(page_url, settings)
    if fc:
        md = str(fc["markdown"])
        title = fc.get("title")  # type: ignore[assignment]
        text = markdown_to_text(md) if extract_mode == "text" else md
        return text, title, "firecrawl"  # type: ignore[return-value]
    text, title, ext = _extract_from_html_basic(body, extract_mode)
    if not (text or "").strip():
        raise WebFetchError(
            "Web fetch extraction failed: Firecrawl and basic HTML cleanup returned no content.",
        )
    return text, title, ext


def _follow_get(
    session: requests.Session,
    start_url: str,
    *,
    settings: WebFetchSettings,
    headers: dict[str, str],
) -> tuple[requests.Response, str]:
    current = start_url
    for hop in range(settings.max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https"):
            raise WebFetchError("Redirect target must be http or https")
        host = parsed.hostname
        if not host:
            raise WebFetchError("Redirect target missing host")
        if settings.ssrf_enabled:
            _assert_host_allowed(host, settings)
        resp = session.get(
            current,
            headers=headers,
            timeout=settings.timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            if hop >= settings.max_redirects:
                resp.close()
                raise WebFetchError("Too many redirects")
            loc = resp.headers.get("Location") or resp.headers.get("location")
            resp.close()
            if not loc:
                raise WebFetchError("Redirect response missing Location header")
            current = urljoin(current, loc)
            continue
        return resp, current
    raise WebFetchError("Too many redirects")


def run_web_fetch(
    url: str,
    *,
    extract_mode: ExtractMode = "markdown",
    max_chars: int | None = None,
    settings: WebFetchSettings | None = None,
) -> dict[str, object]:
    base_cfg = settings or WebFetchSettings()
    from dataclasses import replace as _dc_replace  # noqa: PLC0415
    cfg = _dc_replace(
        base_cfg,
        max_response_bytes=_resolve_max_response_bytes(base_cfg.max_response_bytes),
        timeout_seconds=_resolve_timeout_seconds(base_cfg.timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
        max_redirects=_resolve_max_redirects(base_cfg.max_redirects, DEFAULT_MAX_REDIRECTS),
    )
    if not cfg.allow_rfc2544_benchmark_range and _detect_fakeip_mode():
        # Detection is cached after the first probe and has no security cost
        # when SSRF is disabled, but flipping the flag keeps cache keys and
        # SSRF behaviour consistent across calls in the same process.
        if cfg.ssrf_enabled:
            logger.warning(
                "web_fetch: detected Clash/mihomo TUN fake-ip DNS; auto-allowing "
                "RFC 2544 range (198.18.0.0/15). Set "
                "WEB_FETCH_DISABLE_FAKEIP_AUTODETECT=1 to opt out."
            )
        cfg = _dc_replace(cfg, allow_rfc2544_benchmark_range=True)
    max_out = _clamp_max_chars(max_chars, cfg.max_chars, cfg.max_chars_cap)
    cache_key = _normalize_cache_key(url.strip(), extract_mode, max_out, cfg)
    ttl_ms = _cache_ttl_ms(cfg)
    cached = _cache_get(cache_key, ttl_ms)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out

    canonical, _ = _parse_url(url)
    if cfg.ssrf_enabled:
        _, host0 = _parse_url(canonical)
        _assert_host_allowed(host0, cfg)

    # Browser-like fingerprint to reduce captcha rate from search engines
    # and Cloudflare-protected sites. Order and casing follow Chrome.
    headers = {
        "User-Agent": cfg.user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Connection": "keep-alive",
    }
    start = time.perf_counter()
    with requests.Session() as session:
        resp: requests.Response | None = None
        final_url = canonical
        try:
            try:
                resp, final_url = _follow_get(
                    session,
                    canonical,
                    settings=cfg,
                    headers=headers,
                )
            except SsrfBlockedError:
                raise
            except requests.RequestException as exc:
                fc = _try_firecrawl_fetch(canonical, cfg)
                if fc:
                    took_ms = int((time.perf_counter() - start) * 1000)
                    payload = _build_firecrawl_payload(
                        fc,
                        requested_url=canonical,
                        extract_mode=extract_mode,
                        max_out=max_out,
                        took_ms=took_ms,
                    )
                    store = dict(payload)
                    store.pop("cached", None)
                    _cache_set(cache_key, store, ttl_ms)
                    return payload
                raise WebFetchError(f"HTTP request failed: {exc}") from exc

            took_ms = int((time.perf_counter() - start) * 1000)
            if resp is None:
                raise WebFetchError("Internal: no response object after fetch")

            if not resp.ok:
                fc = _try_firecrawl_fetch(canonical, cfg)
                if fc:
                    resp.close()
                    resp = None
                    payload = _build_firecrawl_payload(
                        fc,
                        requested_url=canonical,
                        extract_mode=extract_mode,
                        max_out=max_out,
                        took_ms=took_ms,
                    )
                    store = dict(payload)
                    store.pop("cached", None)
                    _cache_set(cache_key, store, ttl_ms)
                    return payload

                try:
                    raw, _ = _read_body_limited(resp, DEFAULT_ERROR_MAX_BYTES)
                    detail = raw.decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                fmt = _format_web_fetch_error_detail(
                    detail,
                    content_type=resp.headers.get("content-type"),
                    max_chars=DEFAULT_ERROR_MAX_CHARS,
                )
                reason_str = str(resp.reason) if resp.reason else ""
                wrapped_detail, _, _, _ = wrap_web_fetch_content(
                    fmt or reason_str,
                    DEFAULT_ERROR_MAX_CHARS,
                )
                raise WebFetchError(
                    f"Web fetch failed ({resp.status_code}): {wrapped_detail}",
                )

            ct_header = resp.headers.get("Content-Type", "")
            base_ct = _content_type_base(ct_header)
            raw_bytes, body_truncated = _read_body_limited(resp, cfg.max_response_bytes)
            body = raw_bytes.decode("utf-8", errors="replace")

            title: str | None = None
            extractor = "raw"
            text = body
            warning: str | None = None
            if body_truncated:
                warning = f"Response body truncated after {cfg.max_response_bytes} bytes."

            ct_lower = base_ct.lower()
            if "text/markdown" in ct_lower:
                extractor = "cf-markdown"
                if extract_mode == "text":
                    text = markdown_to_text(body)
                text = strip_invisible_unicode(text)
            elif "text/html" in ct_lower:
                if _looks_like_captcha(body):
                    host = urlparse(final_url).hostname or "remote host"
                    raise WebFetchError(
                        f"Captcha / anti-bot challenge from {host} "
                        f"(status {resp.status_code}); the response is an interstitial, "
                        "not the requested page. Try a different source or backend."
                    )
                text, title, extractor = _extract_html_pipeline(
                    body,
                    page_url=final_url,
                    extract_mode=extract_mode,
                    settings=cfg,
                )
            elif "application/json" in ct_lower:
                try:
                    text = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
                    extractor = "json"
                except json.JSONDecodeError:
                    text = body
                    extractor = "raw"
            else:
                text = strip_invisible_unicode(body)
                extractor = "raw"

            wrapped_warning = _wrap_web_fetch_field(warning) if warning else None
            wrapped_title = _wrap_web_fetch_field(title)

            wrapped, trunc, raw_len, wrapped_len = wrap_web_fetch_content(
                text or "",
                max_out,
            )
            payload = {
                "url": canonical,
                "final_url": final_url,
                "status": resp.status_code,
                "content_type": base_ct,
                "title": wrapped_title,
                "extract_mode": extract_mode,
                "extractor": extractor,
                "external_content": {
                    "untrusted": True,
                    "source": "web_fetch",
                    "wrapped": True,
                },
                "truncated": trunc,
                "length": wrapped_len,
                "raw_length": raw_len,
                "wrapped_length": wrapped_len,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "took_ms": took_ms,
                "text": wrapped,
                "warning": wrapped_warning,
                "cached": False,
            }
            store = dict(payload)
            store.pop("cached", None)
            _cache_set(cache_key, store, ttl_ms)
            return payload
        finally:
            if resp is not None:
                resp.close()


def web_fetch_as_json_str(
    url: str,
    extract_mode: ExtractMode = "markdown",
    max_chars: int | None = None,
    *,
    settings: WebFetchSettings | None = None,
) -> str:
    data = run_web_fetch(url, extract_mode=extract_mode, max_chars=max_chars, settings=settings)
    return json.dumps(data, ensure_ascii=False)
