"""Unit tests for text extraction — no HTTP, no DB, no LibreOffice."""
import asyncio
import io

import pytest
from pypdf import PdfWriter

from app.models.exceptions import UnsupportedFileTypeError
from app.services.text_service import _pdf_to_text, extract_text


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_plain_text_decoded():
    assert asyncio.run(extract_text("привіт\n".encode(), "text/plain")) == "привіт\n"


def test_csv_decoded():
    assert asyncio.run(extract_text(b"a,b\n1,2\n", "text/csv")) == "a,b\n1,2\n"


def test_pdf_no_text_returns_empty():
    # A blank page has no extractable text -> empty string, not a crash.
    assert _pdf_to_text(_blank_pdf()) == ""


def test_pdf_dispatch():
    assert asyncio.run(extract_text(_blank_pdf(), "application/pdf")) == ""


def test_image_unsupported():
    with pytest.raises(UnsupportedFileTypeError):
        asyncio.run(extract_text(b"\x89PNG", "image/png"))
