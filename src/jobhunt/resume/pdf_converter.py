"""
PDF generation from DOCX using LibreOffice
"""
import subprocess
import os
import shutil
from pathlib import Path


def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> bool:
    """
    Convert DOCX to PDF using LibreOffice in headless mode.

    Args:
        docx_path: Path to the input DOCX file
        pdf_path: Path where the PDF should be saved

    Returns:
        True if conversion successful

    Raises:
        RuntimeError: If LibreOffice is not installed or conversion fails.
    """
    if not shutil.which('libreoffice'):
        raise RuntimeError(
            "LibreOffice is not installed. Install with: brew install libreoffice"
        )

    outdir = os.path.abspath(os.path.dirname(pdf_path) or ".")
    os.makedirs(outdir, exist_ok=True)

    cmd = [
        'libreoffice',
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', outdir,
        docx_path,
    ]

    subprocess.run(cmd, capture_output=True, text=True, check=True)

    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF was not created at {pdf_path}")

    return True


def is_libreoffice_available() -> bool:
    return shutil.which('libreoffice') is not None
