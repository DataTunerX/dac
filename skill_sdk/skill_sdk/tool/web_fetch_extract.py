from __future__ import annotations

import re
from collections.abc import Callable

READABILITY_MAX_HTML_CHARS = 1_000_000
READABILITY_MAX_ESTIMATED_NESTING_DEPTH = 3000

_HIDDEN_CLASS_NAMES = frozenset(
    {
        "sr-only",
        "visually-hidden",
        "d-none",
        "hidden",
        "invisible",
        "screen-reader-only",
        "offscreen",
    },
)

_ALWAYS_REMOVE_TAGS = frozenset(
    {"meta", "template", "svg", "canvas", "iframe", "object", "embed"},
)

_INVISIBLE_UNICODE_RE = re.compile(
    r"[\u200B-\u200F\u202A-\u202E\u2060-\u2064\u206A-\u206F\uFEFF\u00AD\U000E0000-\U000E007F]",
)


def strip_invisible_unicode(text: str) -> str:
    return _INVISIBLE_UNICODE_RE.sub("", text)


def _normalize_lower(s: str) -> str:
    return s.strip().lower()


def _has_hidden_class(class_name: str) -> bool:
    classes = _normalize_lower(class_name).split()
    return any(c in _HIDDEN_CLASS_NAMES for c in classes)


def _is_style_hidden(style: str) -> bool:
    s = style or ""
    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("display", re.compile(r"^\s*none\s*$", re.I)),
        ("visibility", re.compile(r"^\s*hidden\s*$", re.I)),
        ("opacity", re.compile(r"^\s*0\s*$")),
        ("font-size", re.compile(r"^\s*0(px|em|rem|pt|%)?\s*$", re.I)),
        ("text-indent", re.compile(r"^\s*-\d{4,}px\s*$")),
        ("color", re.compile(r"^\s*transparent\s*$", re.I)),
        (
            "color",
            re.compile(
                r"^\s*rgba\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*0(?:\.0+)?\s*\)\s*$",
                re.I,
            ),
        ),
    ]
    for prop, pat in patterns:
        m = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)", s, re.I)
        if m and pat.search(m.group(1)):
            return True
    clip = re.search(r"(?:^|;)\s*clip-path\s*:\s*([^;]+)", s, re.I)
    if clip and not re.match(r"^\s*none\s*$", clip.group(1), re.I):
        if re.search(r"inset\s*\(\s*(?:0*\.\d+|[1-9]\d*(?:\.\d+)?)%", clip.group(1), re.I):
            return True
    transform = re.search(r"(?:^|;)\s*transform\s*:\s*([^;]+)", s, re.I)
    if transform:
        t = transform.group(1)
        if re.search(r"scale\s*\(\s*0\s*\)", t, re.I):
            return True
        if re.search(r"translateX\s*\(\s*-\d{4,}px\s*\)", t, re.I):
            return True
    width = re.search(r"(?:^|;)\s*width\s*:\s*([^;]+)", s, re.I)
    height = re.search(r"(?:^|;)\s*height\s*:\s*([^;]+)", s, re.I)
    overflow = re.search(r"(?:^|;)\s*overflow\s*:\s*([^;]+)", s, re.I)
    if (
        width
        and re.match(r"^\s*0(px)?\s*$", width.group(1), re.I)
        and height
        and re.match(r"^\s*0(px)?\s*$", height.group(1), re.I)
        and overflow
        and re.match(r"^\s*hidden\s*$", overflow.group(1), re.I)
    ):
        return True
    left = re.search(r"(?:^|;)\s*left\s*:\s*([^;]+)", s, re.I)
    top = re.search(r"(?:^|;)\s*top\s*:\s*([^;]+)", s, re.I)
    if left and re.match(r"^\s*-\d{4,}px\s*$", left.group(1), re.I):
        return True
    if top and re.match(r"^\s*-\d{4,}px\s*$", top.group(1), re.I):
        return True
    return False


def _should_remove_element(tag) -> bool:  # noqa: ANN001
    from bs4 import NavigableString  # noqa: PLC0415

    if isinstance(tag, NavigableString) or not getattr(tag, "name", None):
        return False
    name = str(tag.name).lower()
    if name in _ALWAYS_REMOVE_TAGS:
        return True
    if name == "input":
        t = tag.get("type")
        if t and str(t).lower() == "hidden":
            return True
    if tag.get("aria-hidden") == "true":
        return True
    if tag.has_attr("hidden"):
        return True
    cls = tag.get("class")
    if cls:
        class_str = " ".join(cls) if isinstance(cls, list) else str(cls)
        if _has_hidden_class(class_str):
            return True
    style = tag.get("style")
    if style and _is_style_hidden(str(style)):
        return True
    return False


def sanitize_html(html: str) -> str:
    from bs4 import BeautifulSoup  # noqa: PLC0415

    sanitized = re.sub(r"<!--[\s\S]*?-->", "", html)
    try:
        soup = BeautifulSoup(sanitized, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(sanitized, "html.parser")
        except Exception:
            return sanitized
    for el in list(soup.find_all(True)):
        try:
            if _should_remove_element(el):
                el.decompose()
        except Exception:
            continue
    return str(soup)


def exceeds_estimated_html_nesting_depth(html: str, max_depth: int) -> bool:
    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    depth = 0
    length = len(html)
    i = 0
    while i < length:
        if html[i] != "<":
            i += 1
            continue
        if i + 1 >= length:
            break
        nxt = ord(html[i + 1])
        if nxt in (33, 63):  # ! ?
            i += 1
            continue
        j = i + 1
        closing = False
        if j < length and html[j] == "/":
            closing = True
            j += 1
        while j < length and html[j] <= " ":
            j += 1
        name_start = j
        while j < length:
            c = ord(html[j])
            is_name = (
                (65 <= c <= 90)
                or (97 <= c <= 122)
                or (48 <= c <= 57)
                or c in (58, 45)  # : -
            )
            if not is_name:
                break
            j += 1
        tag_name = html[name_start:j].lower()
        if not tag_name:
            i += 1
            continue
        if closing:
            depth = max(0, depth - 1)
            i += 1
            continue
        if tag_name in void_tags:
            i += 1
            continue
        self_closing = False
        for k in range(j, min(length, j + 200)):
            if html[k] == ">":
                if k > 0 and html[k - 1] == "/":
                    self_closing = True
                break
        if self_closing:
            i += 1
            continue
        depth += 1
        if depth > max_depth:
            return True
        i += 1
    return False


def extract_readable_readability(
    html: str,
    *,
    page_url: str,
    extract_mode: str,
    html_to_markdown: Callable[[str], tuple[str, str | None]],
    markdown_to_text: Callable[[str], str],
    normalize_ws: Callable[[str], str],
) -> tuple[str, str | None, str] | None:
    """Return (text, title, extractor) or None if Readability fails."""
    try:
        from readability.readability import Document  # noqa: PLC0415
        from lxml import html as lhtml  # noqa: PLC0415
    except ImportError:
        return None

    clean = sanitize_html(html)
    if len(clean) > READABILITY_MAX_HTML_CHARS or exceeds_estimated_html_nesting_depth(
        clean,
        READABILITY_MAX_ESTIMATED_NESTING_DEPTH,
    ):
        return None
    try:
        doc = Document(clean, url=page_url or "")
        summary_html = doc.summary(html_partial=True)
        short_title = doc.short_title()
        title_attr = getattr(doc, "title", None)
        if callable(title_attr):
            long_title = title_attr()
        else:
            long_title = title_attr
    except Exception:
        return None
    if not summary_html or not str(summary_html).strip():
        return None
    title = None
    if short_title and str(short_title).strip():
        title = str(short_title).strip()
    elif long_title and str(long_title).strip():
        title = str(long_title).strip()
    try:
        tree = lhtml.fromstring(summary_html)
        text_content = normalize_ws(strip_invisible_unicode("".join(tree.itertext())))
    except Exception:
        return None
    if extract_mode == "text":
        if not text_content:
            return None
        return text_content, title, "readability"
    md_text, md_title = html_to_markdown(summary_html)
    out_title = title or md_title
    out = strip_invisible_unicode(md_text)
    if not out:
        return None
    return out, out_title, "readability"
