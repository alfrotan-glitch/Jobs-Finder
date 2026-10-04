"""
CV / resume text extraction and structured evidence helpers.

Basic operation is deterministic and local. PDF parsing uses pdfplumber when
available; plain text and Markdown CVs are supported without optional packages.
The parser never writes inferred facts into profile.yaml.
"""

from __future__ import annotations

from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv"}


def extract_resume_text(resume_path: str) -> str:
    """Extract text from the explicitly supplied CV file.

    Extraction is intentionally uncached.  A ``.cache/resume_<hash>.txt``
    file used to be trusted as an input merely because its name matched a CV
    hash.  That made stale or sample text capable of entering applicant
    matching.  Resume text is now read only from the file supplied to this
    function and is never a standalone applicant-profile source.
    """
    if not resume_path:
        return ""
    path = Path(resume_path).expanduser()
    if not path.exists() or not path.is_file():
        return ""

    if path.suffix.lower() in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_text(path)
    # Last-resort text read for unusual but text-like uploads.
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


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
