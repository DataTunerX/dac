"""Unit tests for ``skill_sdk.tool.pdf`` (local extraction).

Loads ``pdf.py`` via importlib so tests do not require importing the full ``skill_sdk`` package.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent


def _load_pdf_module():
    path = _repo_root / "skill_sdk" / "tool" / "pdf.py"
    name = "_skill_sdk_tool_pdf_for_tests"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pdf module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pdf = _load_pdf_module()

PdfToolError = pdf.PdfToolError
PdfLocalItem = pdf.PdfLocalItem
extract_local_pdfs = pdf.extract_local_pdfs
extract_pdf_content = pdf.extract_pdf_content
load_pdf_bytes = pdf.load_pdf_bytes
local_extractions_as_json = pdf.local_extractions_as_json
parse_page_range = pdf.parse_page_range
resolve_pdf_inputs = pdf.resolve_pdf_inputs

try:
    import fitz  # noqa: F401
except ImportError:
    fitz = None


def _pdf_bytes_with_long_text(mod) -> bytes:
    doc = mod.fitz.open()
    page = doc.new_page()
    long_text = ("longword " * 80) + "\n" + ("moretext " * 80)
    r = mod.fitz.Rect(72, 72, page.rect.width - 72, page.rect.height - 72)
    page.insert_textbox(r, long_text, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _pdf_bytes_blank_page(mod) -> bytes:
    doc = mod.fitz.open()
    doc.new_page()
    out = doc.tobytes()
    doc.close()
    return out


class TestPdfParsers(unittest.TestCase):
    def test_parse_page_range(self) -> None:
        self.assertEqual(parse_page_range("1-3", 20), [1, 2, 3])
        self.assertEqual(parse_page_range("2,5", 20), [2, 5])
        self.assertEqual(parse_page_range("1", 1), [1])

    def test_parse_page_range_invalid(self) -> None:
        with self.assertRaises(PdfToolError):
            parse_page_range("0-1", 10)
        with self.assertRaises(PdfToolError):
            parse_page_range("2-1", 10)

    def test_resolve_pdf_inputs(self) -> None:
        self.assertEqual(resolve_pdf_inputs("/a.pdf", None), ["/a.pdf"])
        self.assertEqual(resolve_pdf_inputs(None, ["/a.pdf", "/a.pdf"]), ["/a.pdf"])
        self.assertEqual(resolve_pdf_inputs("/x", ["/y"]), ["/x", "/y"])
        with self.assertRaises(PdfToolError):
            resolve_pdf_inputs(None, None)


@unittest.skipUnless(fitz is not None, "pymupdf (fitz) not installed")
class TestPdfToolLocal(unittest.TestCase):
    def test_extract_text_no_images_when_enough_chars(self) -> None:
        buf = _pdf_bytes_with_long_text(pdf)
        ext = extract_pdf_content(buf, min_text_chars=200)
        self.assertGreaterEqual(len(ext.text.strip()), 200)
        self.assertEqual(ext.images, [])

    def test_extract_images_when_sparse_text(self) -> None:
        buf = _pdf_bytes_blank_page(pdf)
        ext = extract_pdf_content(buf, min_text_chars=200, max_pages=1)
        self.assertLess(len(ext.text.strip()), 200)
        self.assertEqual(len(ext.images), 1)
        png, mime = ext.images[0]
        self.assertEqual(mime, "image/png")
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_load_pdf_bytes_file(self) -> None:
        buf = _pdf_bytes_with_long_text(pdf)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(buf)
            path = f.name
        try:
            loaded, name = load_pdf_bytes(path, max_bytes=10 * 1024 * 1024)
            self.assertEqual(loaded, buf)
            self.assertTrue(name.endswith(".pdf"))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_pdf_bytes_data_url(self) -> None:
        raw = _pdf_bytes_blank_page(pdf)
        b64 = base64.standard_b64encode(raw).decode("ascii")
        uri = f"data:application/pdf;base64,{b64}"
        loaded, name = load_pdf_bytes(uri, max_bytes=10 * 1024 * 1024)
        self.assertEqual(loaded, raw)
        self.assertEqual(name, "inline.pdf")

    def test_extract_local_pdfs_from_path(self) -> None:
        buf = _pdf_bytes_with_long_text(pdf)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(buf)
            path = f.name
        try:
            items = extract_local_pdfs(pdf=path, min_text_chars=50)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].source, path)
            self.assertGreater(len(items[0].extraction.text), 50)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_local_extractions_as_json(self) -> None:
        buf = _pdf_bytes_blank_page(pdf)
        ext = extract_pdf_content(buf, min_text_chars=9999, max_pages=1)
        payload = local_extractions_as_json(
            [
                PdfLocalItem(
                    source="/tmp/x.pdf",
                    filename="x.pdf",
                    extraction=ext,
                ),
            ],
        )
        data = json.loads(payload)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["filename"], "x.pdf")
        self.assertIn("data_base64", data[0]["images"][0])
