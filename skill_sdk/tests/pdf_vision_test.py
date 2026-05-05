#!/usr/bin/env python3
"""
本地 PDF →（可选栅格 PNG）→ 阿里云魔搭 DashScope / OpenAI 多模态。

用法（在项目根 ``dac/skill_sdk`` 下）::

    cd /path/to/dac/skill_sdk
    pip install pymupdf openai
    python pdf_vision_demo.py

也可传参或使用环境变量，见下方 ``argparse`` 说明。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# 默认占位：可直接改这三个再 ``python pdf_vision_demo.py``，无需命令行
# -----------------------------------------------------------------------------
_DEFAULT_PDF = "/Users/james/daocloud/code/raytest/dac/tests-data/files/manual-1page.pdf"

_PREVIEW_CHARS = 500


def _print_pipeline_banner(*, items: list, combined_answer: str) -> None:
    """在真实内容（文本预览）前打印易读的管线类型：纯 PyMuPDF vs Vision 路径。"""
    sep = "=" * 72
    sub = "-" * 72

    any_png = any(len(it.extraction.images) > 0 for it in items)
    vision_answer = bool((combined_answer or "").strip())

    print()
    print(sep)
    print(" 管线 / 输出类型 ".center(72))
    print(sep)

    if not any_png:
        print(" [汇总] 类别：纯本地 PyMuPDF 文本（未栅格 PNG、非 Vision / 未多模态路径）")
        print(" [汇总] Vision：否 · 抽取文字长度 ≥ min_text_chars，不写 PNG、不调模型")
    elif vision_answer:
        print(" [汇总] 类别：Vision 管线（PyMuPDF + 栅格 PNG → 已向多模态提交图像）")
        print(" [汇总] Vision：是 · combined_answer 非空（见下文）")
    else:
        print(" [汇总] 类别：已走 Vision 路径（已有 PNG），但 combined_answer 为空 · 请查 API / 配额 / 报错")
        print(" [汇总] Vision：调用已尝试 · 模型正文为空")

    print(sub)
    for it in items:
        n_png = len(it.extraction.images)
        n_txt = len(it.extraction.text.strip())
        if n_png > 0:
            per = "Vision 管线：PyMuPDF 抽字 + 栅格 PNG → 多模态"
            tag = "vision"
        else:
            per = "仅 PyMuPDF 文本抽取（非 Vision，无 PNG）"
            tag = "pym_pdf_only"
        print(f" [{it.filename}] 管线标签={tag} · {per}")
        print(f"   · PyMuPDF 字数: {n_txt}  · PNG 张数: {n_png}")
    print(sep)
    print()


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF 本地栅格 + 多模态（OpenAI SDK 兼容阿里云）")
    parser.add_argument(
        "--pdf",
        default=os.environ.get("PDF_PATH", _DEFAULT_PDF),
        help="PDF 路径（也可用环境变量 PDF_PATH）",
    )
    parser.add_argument(
        "--provider",
        choices=("dashscope", "openai"),
        default=os.environ.get("PDF_VISION_PROVIDER", "dashscope"),
        help="dashscope：用 DASHSCOPE_API_KEY；openai：用 OPENAI_API_KEY",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PDF_VISION_MODEL", "qwen-vl-ocr-latest"),
        help="例如 qwen-vl-ocr-latest（魔搭 OCR）",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "PDF_VISION_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        help="兼容 OpenAI 的 base URL；provider=openai 可留空走官方 default",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PDF_VISION_API_KEY", ""),
        help="不传则从 DASHSCOPE_API_KEY（魔搭）或 OPENAI_API_KEY 读取",
    )
    parser.add_argument(
        "--prompt",
        default=os.environ.get("PDF_PROMPT", "请用中文简要描述这一页的主要内容。"),
        help="传给多模态模型的说明",
    )
    parser.add_argument(
        "--min-text-chars",
        type=int,
        default=int(os.environ.get("PDF_MIN_TEXT_CHARS", "100000")),
        help="拉大则易走 PNG 分支（ Raster + 看图），默认极大以偏向栅格图",
    )
    args = parser.parse_args()

    from skill_sdk.tool.pdf import PdfVisionConfig, extract_local_pdfs_with_vision

    pdf_arg = Path(args.pdf).expanduser()
    if not pdf_arg.is_file():
        print(f"[error] PDF 不存在: {pdf_arg}", file=sys.stderr)
        sys.exit(1)

    key = args.api_key.strip()
    if not key:
        if args.provider == "dashscope":
            key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
            if not key:
                print("[error] 请设置 --api-key 或环境变量 DASHSCOPE_API_KEY", file=sys.stderr)
                sys.exit(1)
        else:
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                print("[error] 请设置 --api-key 或环境变量 OPENAI_API_KEY", file=sys.stderr)
                sys.exit(1)

    base_url_clean = args.base_url.strip() or None
    if args.provider == "dashscope":
        cfg = PdfVisionConfig(
            model=args.model,
            provider="dashscope",
            api_key=key,
            base_url=base_url_clean,
            max_tokens=4096,
        )
    else:
        cfg = PdfVisionConfig(
            model=args.model,
            provider="openai",
            api_key=key,
            base_url=base_url_clean,
            max_tokens=4096,
        )

    print(f"[info] pdf={pdf_arg}")
    print(f"[info] provider={args.provider} model={cfg.model}")

    result = extract_local_pdfs_with_vision(
        prompt=args.prompt,
        vision=cfg,
        pdf=str(pdf_arg),
        min_text_chars=args.min_text_chars,
    )

    _print_pipeline_banner(items=result.items, combined_answer=result.combined_answer)

    print("\n--- extracted text preview (first %d chars per file) ---\n" % _PREVIEW_CHARS)
    for it in result.items:
        t = it.extraction.text.strip()
        head = t[:_PREVIEW_CHARS]
        truncated = len(t) > _PREVIEW_CHARS
        print(f">> {it.filename} (total_chars={len(t)})")
        print(head + (" [...]" if truncated else ""))
        print()

    print("\n--- combined_answer ---\n")
    print(result.combined_answer or "(空：本次未产出 PNG / 未调多模态；上文已打印本地抽取文本预览)")
    print("\n--- stats ---")
    for it in result.items:
        ex = it.extraction
        print(json.dumps({"file": it.filename, "text_chars": len(ex.text), "png_count": len(ex.images)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
