"""ToolPlugin subclass for extract_pdf."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from pydantic import BaseModel, Field

from skill_sdk.plugin.base import ToolPlugin

logger = logging.getLogger(__name__)


class PdfExtractInput(BaseModel):
    """Input schema for ``extract_pdf`` tool."""

    pdf: str | None = Field(
        default=None,
        description="单个 PDF：本地路径、file://、http(s) URL 或 data:application/pdf;base64,...",
    )
    pdfs: list[str] | None = Field(
        default=None,
        description="多个 PDF 源，与 pdf 可同时提供（会去重合并）；至少其一非空",
    )
    pages: str | None = Field(
        default=None,
        description='可选页码范围，如 "1-3,5"；省略则按 max_pages 处理文档前若干页',
    )
    max_bytes_mb: float = Field(default=10.0, ge=0.5, le=50.0, description="单个 PDF 最大字节数（MB）")
    max_pages: int = Field(default=20, ge=1, le=100, description="每个文档最多处理页数")
    min_text_chars: int = Field(
        default=10000,
        ge=0,
        le=2_000_000,
        description="提取文本总长达到该阈值则不再生成整页 PNG（省 token）；扫描版可改小以强制配图",
    )
    include_images: bool = Field(
        default=False,
        description="是否在结果中包含整页 PNG 的 base64；开启会显著增大返回体",
    )
    max_chars: int = Field(
        default=100000,
        ge=500,
        le=100000,
        description="每个 PDF 的 text 字段最大字符数（截断后返回）",
    )
    max_json_chars: int = Field(
        default=100000,
        ge=2000,
        le=120000,
        description="整段 JSON 输出上限；超出会去掉图片或进一步截断 text",
    )


def _trim_text(text: str, *, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...(truncated {len(text) - max_chars} chars)"


def _runner_pdf_vision_config_from_env():
    """Build PdfVisionConfig from env; pdf.py decides if vision can run."""
    from skill_sdk.tool.pdf import PdfVisionConfig

    raw_provider = os.environ.get("PDF_VISION_PROVIDER")
    provider = "" if raw_provider is None else raw_provider.strip()

    model = (os.environ.get("PDF_VISION_MODEL") or "").strip()

    ak = os.environ.get("PDF_VISION_API_KEY")
    api_key = ak.strip() if ak and ak.strip() else None

    bu = os.environ.get("PDF_VISION_BASE_URL")
    base_url = bu.strip() if bu and bu.strip() else None

    try:
        max_tokens = int(os.environ.get("PDF_VISION_MAX_TOKENS", "4096"))
    except ValueError:
        max_tokens = 4096

    return PdfVisionConfig(
        model=model,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
    )


def _runner_pdf_vision_prompt_from_env() -> str | None:
    for k in ("PDF_VISION_PROMPT", "PDF_PROMPT"):
        v = os.environ.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_pdf_tool_payload(
    *,
    pdf: str | None,
    pdfs: list[str] | None,
    pages: str | None,
    max_bytes_mb: float,
    max_pages: int,
    min_text_chars: int,
    include_images: bool,
    max_chars: int,
    max_json_chars: int,
) -> dict[str, Any]:
    """Build JSON-serializable dict for extract_pdf tool.

    Uses :func:`~skill_sdk.tool.pdf.extract_local_pdfs_with_vision` so multimodal is optional
    via env; multimodal feasibility is enforced in pdf.py.
    """
    from skill_sdk.tool.pdf import extract_local_pdfs_with_vision

    vision_cfg = _runner_pdf_vision_config_from_env()
    result = extract_local_pdfs_with_vision(
        prompt=_runner_pdf_vision_prompt_from_env(),
        vision=vision_cfg,
        pdf=pdf,
        pdfs=pdfs,
        pages=pages,
        max_bytes_mb=max_bytes_mb,
        max_pages=max_pages,
        min_text_chars=min_text_chars,
    )
    items = result.items
    per_answers = result.per_pdf_answers

    rows: list[dict[str, Any]] = []
    vision_cap = min(max_chars * 4, 100000)
    for idx, it in enumerate(items):
        imgs: list[dict[str, str]] = []
        if include_images:
            for raw, mime in it.extraction.images:
                imgs.append(
                    {
                        "mime_type": mime,
                        "data_base64": base64.standard_b64encode(raw).decode("ascii"),
                    }
                )
        v_ans = per_answers[idx] if idx < len(per_answers) else ""
        rows.append(
            {
                "source": it.source,
                "filename": it.filename,
                "text": _trim_text(it.extraction.text, max_chars=max_chars),
                "vision_answer": _trim_text(str(v_ans or ""), max_chars=vision_cap),
                "images": imgs,
                "stats": {
                    "text_chars": len(it.extraction.text),
                    "image_count": len(it.extraction.images),
                },
            },
        )

    payload: dict[str, Any] = {
        "items": rows,
        "combined_vision_answer": _trim_text(
            str(result.combined_answer or ""),
            max_chars=min(100000, max_json_chars // 3),
        ),
        "vision_backend_used": result.vision_backend_used,
    }
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= max_json_chars:
        return payload

    # Drop images first — main cause of oversized responses.
    if include_images:
        slim_rows: list[dict[str, Any]] = []
        for r in rows:
            slim_rows.append({**r, "images": []})
        payload = {
            "items": slim_rows,
            "combined_vision_answer": _trim_text(
                str(result.combined_answer or ""),
                max_chars=min(100000, max_json_chars // 3),
            ),
            "vision_backend_used": result.vision_backend_used,
            "_images_omitted": True,
            "_omission_reason": "JSON exceeded max_json_chars after extraction; retry with include_images=false or fewer PDFs/pages.",
        }
        raw2 = json.dumps(payload, ensure_ascii=False)
        if len(raw2) <= max_json_chars:
            return payload
        rows = slim_rows

    # Progressive text shrink
    for cap in (max(max_chars // 2, 500), 1500, 800, 500):
        shrunk = []
        for r in rows:
            t = str(r.get("text") or "")
            shrunk.append({**r, "text": _trim_text(t, max_chars=cap)})
        payload = {
            "items": shrunk,
            "combined_vision_answer": _trim_text(
                str(result.combined_answer or ""),
                max_chars=min(100000, max_json_chars // 3),
            ),
            "vision_backend_used": result.vision_backend_used,
            "_truncated": True,
            "_truncation_note": f"text per item capped to {cap} chars to fit max_json_chars",
        }
        if len(json.dumps(payload, ensure_ascii=False)) <= max_json_chars:
            return payload

    return {
        "items": [
            {**r, "text": _trim_text(str(r.get("text") or ""), max_chars=400)} for r in rows
        ],
        "combined_vision_answer": _trim_text(str(result.combined_answer or ""), max_chars=800),
        "vision_backend_used": result.vision_backend_used,
        "_truncated": True,
        "_truncation_note": "aggressive text truncation to fit max_json_chars",
    }


class ExtractPdfPlugin(ToolPlugin):
    """Extract text (and optionally images) from PDF files (local paths, file://, http(s) URLs, or data: URIs)."""

    name = "extract_pdf"
    description = (
        "从本地路径或 URL 加载 PDF：统一经 PyMuPDF 本地抽取文本 + 可选多模态视觉回答。"
        "多模态环境变量：PDF_VISION_MODEL、PDF_VISION_PROVIDER、PDF_VISION_API_KEY、"
        "PDF_VISION_BASE_URL。未配置完整时仅返回本地抽取结果。"
        "依赖 PyMuPDF（pymupdf）；失败时返回 {\"error\": ...}。"
    )
    args_schema = PdfExtractInput

    def execute(self, **kwargs) -> str:
        from skill_sdk.tool.pdf import PdfToolError

        try:
            payload = _extract_pdf_tool_payload(
                pdf=kwargs.get("pdf"),
                pdfs=kwargs.get("pdfs"),
                pages=kwargs.get("pages"),
                max_bytes_mb=float(kwargs.get("max_bytes_mb", 10.0)),
                max_pages=int(kwargs.get("max_pages", 20)),
                min_text_chars=int(kwargs.get("min_text_chars", 10000)),
                include_images=bool(kwargs.get("include_images", False)),
                max_chars=int(kwargs.get("max_chars", 100000)),
                max_json_chars=int(kwargs.get("max_json_chars", 100000)),
            )
        except PdfToolError as exc:
            return self._format_error(str(exc))
        except ImportError as exc:
            return self._format_error(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("extract_pdf failed")
            return self._format_error(f"extract_pdf failed: {exc}")

        return json.dumps(payload, ensure_ascii=False)
