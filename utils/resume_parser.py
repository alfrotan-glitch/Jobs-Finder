"""
CV / resume text extraction and structured evidence helpers.

Basic operation is deterministic and local. PDF parsing uses pdfplumber when
available; plain text and Markdown CVs are supported without optional packages.
The parser never writes inferred facts into profile.yaml.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv"}


def extract_resume_text(resume_path: str) -> str:
    """
    Extract text from a PDF or text CV.
    Returns cached text if the file hasn't changed.
    """
    if not resume_path:
        return ""
    path = Path(resume_path).expanduser()
    if not path.exists() or not path.is_file():
        return ""

    try:
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    cache_file = CACHE_DIR / f"resume_{file_hash}.txt"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="replace")

    text = ""
    if path.suffix.lower() in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif path.suffix.lower() == ".pdf":
        text = _extract_pdf_text(path)
    else:
        # Last-resort text read for unusual but text-like uploads.
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            text = ""

    if text:
        cache_file.write_text(text, encoding="utf-8")
    return text


def _extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        print("  ⚠ pdfplumber not installed. Run: pip install pdfplumber")
        return ""

    chunks: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    chunks.append(page_text)
    except Exception as e:
        print(f"  ⚠ Failed to parse resume: {e}")
        return ""
    return "\n".join(chunks)
