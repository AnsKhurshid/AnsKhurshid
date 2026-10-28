"""DOCX -> PDF via LibreOffice (headless). Returns None when unavailable; never raises for missing tools."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from jobagent.utils.files import atomic_write_bytes

log = logging.getLogger("jobagent.resume.pdf")


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_to_pdf(docx_path: Path, pdf_path: Path, timeout: int = 120) -> tuple[Path | None, str | None]:
    exe = soffice()
    if not exe:
        return None, "LibreOffice not installed"
    with tempfile.TemporaryDirectory() as tmp:
        # A private profile dir avoids clashes with a running LibreOffice instance.
        cmd = [exe, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--convert-to", "pdf",
               "--outdir", tmp, str(docx_path)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "PDF conversion timed out"
        out = Path(tmp) / (docx_path.stem + ".pdf")
        if proc.returncode != 0 or not out.exists():
            log.warning("PDF conversion failed: %s", (proc.stderr or proc.stdout)[-500:])
            return None, "PDF conversion failed"
        atomic_write_bytes(pdf_path, out.read_bytes())
    return pdf_path, None
