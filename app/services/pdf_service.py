import asyncio
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.exceptions import PdfConversionError

SOFFICE_BIN = "soffice"
CONVERSION_TIMEOUT = 120  # seconds


async def convert_to_pdf(file_bytes: bytes, source_ext: str) -> bytes:
    """Convert an office document to PDF bytes via headless LibreOffice.

    `source_ext` is the file extension (e.g. ".docx") — derive it from the
    stored content_type, not the user's filename (see note below).
    """
    with TemporaryDirectory(prefix="lo-convert-") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / f"input{source_ext}"
        output_dir = tmp_dir / "out"
        output_dir.mkdir()
        profile_dir = tmp_dir / f"profile-{uuid.uuid4().hex}"

        input_path.write_bytes(file_bytes)

        cmd = [
            SOFFICE_BIN,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(input_path),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise PdfConversionError(
                f"LibreOffice binary '{SOFFICE_BIN}' not found"
            ) from exc
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=CONVERSION_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise PdfConversionError(f"LibreOffice timed out on {source_ext}")

        if proc.returncode != 0:
            raise PdfConversionError(
                f"LibreOffice exited {proc.returncode}: "
                f"{stderr.decode(errors='replace')[:500]}"
            )

        pdfs = list(output_dir.glob("*.pdf"))
        if not pdfs:
            # LibreOffice sometimes exits 0 but produces nothing — treat as failure.
            raise PdfConversionError(
                f"No PDF produced: {stderr.decode(errors='replace')[:500]}"
            )
        return pdfs[0].read_bytes()