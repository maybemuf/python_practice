import asyncio
import io

from pypdf import PdfReader

from app.models.exceptions import UnsupportedFileTypeError
from app.services.pdf_service import convert_to_pdf

# content_type -> extension, for the office formats LibreOffice converts to PDF.
OFFICE_EXTENSIONS: dict[str, str] = {
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

TEXT_CONTENT_TYPES = {"text/plain", "text/csv"}
PDF_CONTENT_TYPE = "application/pdf"


def _pdf_to_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = (page.extract_text() or "" for page in reader.pages)
    return "\n\n".join(p for p in pages if p.strip())


async def extract_text(file_bytes: bytes, content_type: str) -> str:
    """Extract plain text from a supported file. Office docs go through the
    existing LibreOffice->PDF path; PDFs are parsed with pypdf. Images aren't
    supported (no OCR)."""
    if content_type in TEXT_CONTENT_TYPES:
        return file_bytes.decode("utf-8", errors="replace")

    if content_type == PDF_CONTENT_TYPE:
        # pypdf is sync/CPU-bound — keep the event loop free.
        return await asyncio.to_thread(_pdf_to_text, file_bytes)

    if content_type in OFFICE_EXTENSIONS:
        pdf_bytes = await convert_to_pdf(file_bytes, OFFICE_EXTENSIONS[content_type])
        return await asyncio.to_thread(_pdf_to_text, pdf_bytes)

    raise UnsupportedFileTypeError(content_type)
