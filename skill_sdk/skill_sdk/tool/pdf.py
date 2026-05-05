"""Local PDF helpers: OCR-style text extraction, optional raster-to-PNG, and optional vision LLM calls.

Plain extraction uses PyMuPDF. When extracted text is shorter than ``min_text_chars``, pages are
rendered to PNG bytes. The unified entry point is :func:`extract_local_pdfs_with_vision` with
:class:`PdfVisionConfig`; :func:`vision_backend_ready` decides whether multimodal APIs run (missing
model, provider, or API key ⇒ local path only).

Use ``provider="openai"`` or ``provider="dashscope"`` (``DASHSCOPE_API_KEY``) for Alibaba Modal
compatible OpenAI APIs (e.g. ``qwen-vl-ocr-latest`` with raster ``data:image`` URLs).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

DEFAULT_MAX_PDFS = 10
DEFAULT_MAX_BYTES_MB = 10.0
DEFAULT_MAX_PAGES = 500
# Intentionally high for workflows that prioritize page→PNG raster over raw text length.
# Callers always override via ``extract_pdf_content(..., min_text_chars=...)``.
PDF_MIN_TEXT_CHARS = 10000
PDF_MAX_PIXELS = 4_000_000
DEFAULT_TIMEOUT_S = 30.0


class PdfToolError(Exception):
    """Raised when local PDF loading or extraction fails."""


@dataclass
class PdfExtractedContent:
    text: str
    """Flattened page text."""
    images: list[tuple[bytes, str]] = field(default_factory=list)
    """PNG bytes and mime type pairs (typically image/png)."""


@dataclass
class PdfLocalItem:
    """Single PDF load + extraction."""

    source: str
    """Path or URI as provided by the caller."""
    filename: str
    """Suggested display basename."""
    extraction: PdfExtractedContent


# DashScope (Modal / 阿里云) Beijing compatible endpoint; Singapore / US URLs in Aliyun docs.
DEFAULT_DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# Matches ModelScope / 「魔搭」OCR multimodal snippets for ``qwen-vl-ocr-latest`` etc.
DEFAULT_QWEN_VL_IMAGE_MIN_PIXELS = 32 * 32 * 3
DEFAULT_QWEN_VL_IMAGE_MAX_PIXELS = 32 * 32 * 8192

DEFAULT_VISION_USER_PROMPT = "请用中文简要描述这一页的主要内容。"

_SUPPORTED_VISION_PROVIDERS = frozenset(("openai", "openai_compatible", "dashscope"))


@dataclass
class PdfVisionConfig:
    """Vision Chat Completions: OpenAI, OpenAI-compatible gateways, or Alibaba DashScope compatible-mode."""

    model: str = ""
    provider: str = ""
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4096
    timeout_seconds: float = 120.0
    max_images_per_request: int = 20
    """Split large page batches into multiple vision calls; results are merged."""
    qwen_vl_min_pixels: int = DEFAULT_QWEN_VL_IMAGE_MIN_PIXELS
    """Passed on each raster image block for Alibaba ``qwen-vl-ocr-latest`` DashScope multimodal API."""
    qwen_vl_max_pixels: int = DEFAULT_QWEN_VL_IMAGE_MAX_PIXELS
    """Passed on each raster image block (see ``max_pixels`` in DashScope OCR examples)."""


@dataclass
class PdfVisionResult:
    """Output of :func:`extract_local_pdfs_with_vision`."""

    items: list[PdfLocalItem]
    per_pdf_answers: list[str]
    combined_answer: str
    vision_backend_used: bool = False


def vision_backend_ready(cfg: PdfVisionConfig | None) -> bool:
    """Return True iff multimodal can be served: model, provider, and API key are all usable.

    When False, :func:`extract_local_pdfs_with_vision` only performs local PyMuPDF extraction
    (and may still rasterize pages when text is short); it will not call external vision APIs.
    """
    if cfg is None:
        return False
    if not (cfg.model or "").strip():
        return False
    prov = (cfg.provider or "").strip().lower()
    if not prov or prov not in _SUPPORTED_VISION_PROVIDERS:
        return False
    explicit = (cfg.api_key or "").strip()
    if explicit:
        return True
    if prov == "dashscope":
        return bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def resolve_pdf_inputs(pdf: str | None, pdfs: list[str] | None) -> list[str]:
    """Merge ``pdf`` and ``pdfs``, dedupe, trim; at least one path/URI required."""
    candidates: list[str] = []
    if isinstance(pdf, str) and pdf.strip():
        candidates.append(pdf.strip())
    if isinstance(pdfs, list):
        candidates.extend(p for p in pdfs if isinstance(p, str) and p.strip())
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    if not out:
        raise PdfToolError("pdf required: provide a path or URL to a PDF document")
    if len(out) > DEFAULT_MAX_PDFS:
        raise PdfToolError(
            f"Too many PDFs: {len(out)} provided, maximum is {DEFAULT_MAX_PDFS}.",
        )
    return out


def parse_page_range(range_str: str, max_pages: int) -> list[int]:
    """Parse e.g. ``1-5``, ``3``, ``1-3,7-9`` into sorted 1-based page numbers."""
    pages: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue
        dm = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if dm:
            start, end = int(dm.group(1)), int(dm.group(2))
            if start < 1 or end < start:
                raise PdfToolError(f'Invalid page range: "{part}"')
            for i in range(start, min(end, max_pages) + 1):
                pages.add(i)
        else:
            num = int(part)
            if num < 1:
                raise PdfToolError(f'Invalid page number: "{part}"')
            if num <= max_pages:
                pages.add(num)
    return sorted(pages)


def _local_fs_path(spec: str) -> str:
    s = spec.strip()
    if s.lower().startswith("file://"):
        parsed = urlparse(s)
        return str(Path(url2pathname(parsed.path)))
    if s.startswith("~"):
        return str(Path(s).expanduser())
    return s


def _disallowed_scheme_reason(spec: str) -> str | None:
    t = spec.strip()
    if re.match(r"^[a-zA-Z]:[\\/]", t):
        return None
    m = re.match(r"^[a-z][a-z0-9+.-]*:", t)
    if not m:
        return None
    sc = m.group(0).rstrip(":").lower()
    if sc in ("http", "https", "file", "data"):
        return None
    return (
        f"Unsupported PDF reference: {spec.strip()}. "
        "Use a file path, file:// URL, http(s) URL, or data: URL."
    )


def load_pdf_bytes(source: str, *, max_bytes: int) -> tuple[bytes, str]:
    """Load PDF bytes from path, ``file://``, ``http(s)``, or ``data:`` URL."""
    reason = _disallowed_scheme_reason(source)
    if reason:
        raise PdfToolError(reason)

    t = source.strip()
    if t.lower().startswith("data:"):
        try:
            header, b64 = t.split(",", 1)
        except ValueError as e:
            raise PdfToolError("Invalid data: URL") from e
        if "base64" not in header:
            raise PdfToolError("Only base64 data: URLs are supported for PDF")
        raw = base64.b64decode(b64)
        if len(raw) > max_bytes:
            raise PdfToolError(f"PDF exceeds max size ({max_bytes} bytes)")
        return raw, "inline.pdf"

    if re.match(r"^https?://", t, re.I):
        r = requests.get(
            t,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "skill-sdk-pdf-local/1.0"},
            stream=True,
        )
        r.raise_for_status()
        buf = io.BytesIO()
        n = 0
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            n += len(chunk)
            if n > max_bytes:
                raise PdfToolError(f"PDF exceeds max size ({max_bytes} bytes)")
            buf.write(chunk)
        name = Path(urlparse(t).path or "document.pdf").name or "document.pdf"
        return buf.getvalue(), name

    path = _local_fs_path(t)
    p = Path(path)
    if not p.is_file():
        raise PdfToolError(f"PDF file not found: {path}")
    data = p.read_bytes()
    if len(data) > max_bytes:
        raise PdfToolError(f"PDF exceeds max size ({max_bytes} bytes)")
    return data, p.name


def extract_pdf_content(
    buffer: bytes,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_pixels: int = PDF_MAX_PIXELS,
    min_text_chars: int = PDF_MIN_TEXT_CHARS,
    page_numbers: list[int] | None = None,
    log_label: str = "",
) -> PdfExtractedContent:
    """Extract text; if shorter than ``min_text_chars``, rasterize pages to PNG (same thresholds as OpenClaw)."""
    if fitz is None:
        raise ImportError(
            "PyMuPDF (pymupdf) is required. Install with: pip install pymupdf",
        )
    doc = fitz.open(stream=buffer, filetype="pdf")
    try:
        n_pages = doc.page_count
        if page_numbers:
            effective = [p for p in page_numbers if 1 <= p <= n_pages][:max_pages]
            if not effective:
                raise PdfToolError(
                    "pages resolved to no in-range pages for this document; "
                    "omit pages or choose valid page numbers.",
                )
        else:
            effective = list(range(1, min(n_pages, max_pages) + 1))

        text_parts: list[str] = []
        per_page_text_len: list[tuple[int, int]] = []
        for pn in effective:
            page = doc.load_page(pn - 1)
            part = page.get_text("text") or ""
            per_page_text_len.append((pn, len(part)))
            text_parts.append(part)
        text = "\n\n".join(text_parts).strip()
        agg_len = len(text)
        label = (log_label or "").strip() or "(no-label)"
        at_or_above = agg_len >= min_text_chars
        branch = "text_only_skip_raster" if at_or_above else "raster_png"
        logger.info(
            "pdf.extract label=%r doc_page_count=%s effective_page_nums=%s "
            "per_page_text_len=%s aggregated_text_len=%s min_text_chars=%s branch=%s "
            "note=aggregated_len_is_sum_of_pages_joined_newlines_Vision_needs_branch_raster_png",
            label,
            n_pages,
            effective,
            per_page_text_len,
            agg_len,
            min_text_chars,
            branch,
        )
        if at_or_above:
            return PdfExtractedContent(text=text, images=[])

        images: list[tuple[bytes, str]] = []
        for pn in effective:
            page = doc.load_page(pn - 1)
            rect = page.rect
            page_px = max(1.0, rect.width * rect.height)
            scale = min(1.0, (max_pixels / page_px) ** 0.5)
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png = pix.tobytes("png")
            images.append((png, "image/png"))
        png_bytes = sum(len(raw) for raw, _ in images)
        logger.info(
            "pdf.extract label=%r raster_done png_count=%s approx_total_png_bytes=%s",
            label,
            len(images),
            png_bytes,
        )
        return PdfExtractedContent(text=text, images=images)
    finally:
        doc.close()


def extract_local_pdfs(
    *,
    pdf: str | None = None,
    pdfs: list[str] | None = None,
    pages: str | None = None,
    max_bytes_mb: float = DEFAULT_MAX_BYTES_MB,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_pixels: int = PDF_MAX_PIXELS,
    min_text_chars: int = PDF_MIN_TEXT_CHARS,
) -> list[PdfLocalItem]:
    """Resolve inputs, load bytes per source, run :func:`extract_pdf_content` on each.

    ``pages``: page range string; only affects extraction when set (subset of pages processed).
    """
    merged = resolve_pdf_inputs(pdf, pdfs)
    max_bytes = int(max_bytes_mb * 1024 * 1024)
    page_nums: list[int] | None = None
    if pages and pages.strip():
        parsed = parse_page_range(pages.strip(), max_pages)
        if not parsed:
            raise PdfToolError(
                f"pages range did not select any valid page numbers (each must be 1..{max_pages}).",
            )
        page_nums = parsed

    out: list[PdfLocalItem] = []
    for src in merged:
        buf, fname = load_pdf_bytes(src, max_bytes=max_bytes)
        ext = extract_pdf_content(
            buf,
            max_pages=max_pages,
            max_pixels=max_pixels,
            min_text_chars=min_text_chars,
            page_numbers=page_nums,
            log_label=fname,
        )
        out.append(PdfLocalItem(source=src, filename=fname, extraction=ext))
    return out


def _resolve_vision_api_key(cfg: PdfVisionConfig) -> str:
    explicit = (cfg.api_key or "").strip()
    if explicit:
        return explicit
    prov = cfg.provider.strip().lower()
    if prov == "dashscope":
        raw = os.environ.get("DASHSCOPE_API_KEY", "")
        key = raw.strip()
        if not key:
            raise PdfToolError(
                "PdfVisionConfig.api_key unset and DASHSCOPE_API_KEY not in environment "
                "(provider=dashscope).",
            )
        return key
    raw = os.environ.get("OPENAI_API_KEY", "")
    key = raw.strip()
    if not key:
        raise PdfToolError(
            "PdfVisionConfig.api_key unset and OPENAI_API_KEY not in environment "
            '(use provider="dashscope" and DASHSCOPE_API_KEY for Alibaba Modal / 兼容模式).',
        )
    return key


def _openai_client(cfg: PdfVisionConfig):
    api_key = _resolve_vision_api_key(cfg)
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "The ``openai`` package is required for extract_local_pdfs_with_vision. "
            "Install with: pip install openai",
        ) from e
    prov = cfg.provider.strip().lower()
    base_url: str | None = None
    if cfg.base_url and cfg.base_url.strip():
        base_url = cfg.base_url.strip().rstrip("/")
    elif prov == "dashscope":
        base_url = DEFAULT_DASHSCOPE_COMPATIBLE_BASE_URL.rstrip("/")

    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": cfg.timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _dashscope_style_image_part(
    raw: bytes,
    mime: str,
    cfg: PdfVisionConfig,
) -> dict[str, Any]:
    """One content element as in Alibaba DashScope OCR / ``qwen-vl`` compatible-mode docs."""
    m = (mime or "image/png").strip()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    part: dict[str, Any] = {
        "type": "image_url",
        "image_url": {"url": f"data:{m};base64,{b64}"},
        "min_pixels": int(cfg.qwen_vl_min_pixels),
        "max_pixels": int(cfg.qwen_vl_max_pixels),
    }
    return part


def _openai_compat_image_part(raw: bytes, mime: str) -> dict[str, Any]:
    m = (mime or "image/png").strip()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{m};base64,{b64}"}}


def _complete_vision_pngs_openai(
    *,
    user_prompt: str,
    sparse_ocr_text: str,
    png_list: list[tuple[bytes, str]],
    cfg: PdfVisionConfig,
) -> str:
    """One or more vision completions; batches when ``png_list`` exceeds ``max_images_per_request``."""
    if not png_list:
        return ""
    client = _openai_client(cfg)
    cap = max(1, int(cfg.max_images_per_request))

    batches: list[list[tuple[bytes, str]]] = [
        png_list[i : i + cap] for i in range(0, len(png_list), cap)
    ]

    dashscope = cfg.provider.strip().lower() == "dashscope"
    partials: list[str] = []
    nb = len(batches)
    for bi, batch in enumerate(batches):
        ocr = sparse_ocr_text.strip()
        head = ""
        if ocr:
            head = "[OCR from PDF layout; may be incomplete]\n" + ocr[:8000] + "\n\n"
        if nb > 1:
            head += f"[Raster pages batch {bi + 1} of {nb} — {len(batch)} images]\n"

        if dashscope:
            # Match 魔搭 / DashScope: images first, then text prompt (``qwen-vl-ocr-latest`` style).
            parts_ds: list[dict[str, Any]] = []
            for raw, mime in batch:
                parts_ds.append(_dashscope_style_image_part(raw, mime, cfg))
            parts_ds.append({"type": "text", "text": head + user_prompt})
            messages = [{"role": "user", "content": parts_ds}]
        else:
            parts: list[dict[str, Any]] = []
            parts.append({"type": "text", "text": head + user_prompt})
            for raw, mime in batch:
                parts.append(_openai_compat_image_part(raw, mime))
            messages = [
                {
                    "role": "system",
                    "content": "You read document pages shown as raster images and follow the user's task.",
                },
                {"role": "user", "content": parts},
            ]

        rsp = client.chat.completions.create(
            model=cfg.model,
            messages=messages,
            max_tokens=cfg.max_tokens,
        )
        tx = (rsp.choices[0].message.content or "").strip()
        if not tx:
            raise PdfToolError(f"Vision model returned empty text (batch {bi + 1} of {nb}).")
        partials.append(tx)

    if len(partials) == 1:
        return partials[0]

    merge_lines = "\n\n".join(f"--- partial {i + 1} ---\n{p}" for i, p in enumerate(partials))
    merge_prompt = (
        "Merge the following partial analyses (from sequential image batches of the same PDF) "
        "into one coherent answer. Preserve important details.\n\n" + merge_lines
    )
    rsp_m = client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": "You merge overlapping partial analyses reliably."},
            {"role": "user", "content": merge_prompt},
        ],
        max_tokens=cfg.max_tokens,
    )
    merged = (rsp_m.choices[0].message.content or "").strip()
    if not merged:
        raise PdfToolError("Vision merge step returned empty text.")
    return merged


def extract_local_pdfs_with_vision(
    *,
    prompt: str | None = None,
    vision: PdfVisionConfig | None = None,
    pdf: str | None = None,
    pdfs: list[str] | None = None,
    pages: str | None = None,
    max_bytes_mb: float = DEFAULT_MAX_BYTES_MB,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_pixels: int = PDF_MAX_PIXELS,
    min_text_chars: int = PDF_MIN_TEXT_CHARS,
) -> PdfVisionResult:
    """Load PDFs locally (PyMuPDF), then optionally send raster pages to a vision LM.

    Multimodal calls run only when :func:`vision_backend_ready` passes *and* the document was
    short enough that :func:`extract_pdf_content` produced PNGs. Missing API keys, ``model``, or
    ``provider`` all skip the remote call and stay on the local path (``vision_backend_used`` False).
    """
    effective_prompt = (prompt or "").strip() or DEFAULT_VISION_USER_PROMPT

    items = extract_local_pdfs(
        pdf=pdf,
        pdfs=pdfs,
        pages=pages,
        max_bytes_mb=max_bytes_mb,
        max_pages=max_pages,
        max_pixels=max_pixels,
        min_text_chars=min_text_chars,
    )

    ready = vision_backend_ready(vision)
    per_pdf_answers: list[str] = []
    vision_backend_used = False

    logger.info(
        "pdf.vision_gate vision_backend_ready=%s min_text_chars=%s pdf_sources=%s",
        ready,
        min_text_chars,
        len(items),
    )

    for it in items:
        ext = it.extraction
        n_png = len(ext.images)
        will_call = bool(ready and vision is not None and n_png)
        if not will_call:
            skip: list[str] = []
            if not ready:
                skip.append("vision_backend_ready_false_check_PDF_VISION_model_provider_api_key")
            if vision is None:
                skip.append("vision_cfg_none")
            if not n_png:
                skip.append(
                    "no_png_because_aggregated_text_len>="
                    + str(min_text_chars)
                    + "_or_py_extract_empty_use_higher_min_text_chars_to_force_raster",
                )
            logger.info(
                "pdf.vision_skip filename=%r text_len=%s png_count=%s will_call_vision=false reasons=%s",
                it.filename,
                len(ext.text),
                n_png,
                "; ".join(skip) if skip else "(unknown)",
            )
        if ready and vision is not None and ext.images:
            logger.info(
                "pdf.vision_call filename=%r png_count=%s user_prompt_chars=%s",
                it.filename,
                n_png,
                len(effective_prompt),
            )
            per_pdf_answers.append(
                _complete_vision_pngs_openai(
                    user_prompt=effective_prompt,
                    sparse_ocr_text=ext.text,
                    png_list=ext.images,
                    cfg=vision,
                )
            )
            vision_backend_used = True
        else:
            per_pdf_answers.append("")

    blocks = [ans.strip() for ans in per_pdf_answers if ans and ans.strip()]
    if len(items) == 1:
        combined_answer = blocks[0] if blocks else ""
    else:
        chunks = []
        for it, ans in zip(items, per_pdf_answers, strict=True):
            a = ans.strip()
            if a:
                chunks.append(f"### {it.filename}\n{a}")
        combined_answer = "\n\n".join(chunks)

    return PdfVisionResult(
        items=items,
        per_pdf_answers=per_pdf_answers,
        combined_answer=combined_answer,
        vision_backend_used=vision_backend_used,
    )


def pdf_vision_result_as_json(obj: PdfVisionResult, *, indent: int = 2) -> str:
    """JSON summary (no PNG blobs)."""

    payload: dict[str, Any] = {
        "combined_answer": obj.combined_answer,
        "vision_backend_used": obj.vision_backend_used,
        "per_pdf": [
            {
                "filename": it.filename,
                "source": it.source,
                "answer": ans,
                "text_chars": len(it.extraction.text),
                "image_count": len(it.extraction.images),
            }
            for it, ans in zip(obj.items, obj.per_pdf_answers, strict=True)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=indent)


def local_extractions_as_json(items: list[PdfLocalItem], *, indent: int = 2) -> str:
    """Serialize results to JSON (PNG payloads as standard base64 strings)."""

    def _item(obj: PdfLocalItem) -> dict[str, Any]:
        imgs = []
        for raw, mime in obj.extraction.images:
            imgs.append({"mime_type": mime, "data_base64": base64.standard_b64encode(raw).decode("ascii")})
        return {
            "source": obj.source,
            "filename": obj.filename,
            "text": obj.extraction.text,
            "images": imgs,
            "stats": {
                "text_chars": len(obj.extraction.text),
                "image_count": len(obj.extraction.images),
            },
        }

    payload = [_item(x) for x in items]
    return json.dumps(payload, ensure_ascii=False, indent=indent)
