"""
CV / resume text extraction and structured evidence helpers.

Basic operation is deterministic and local. PDF parsing uses pdfplumber when
available; plain text and Markdown CVs are supported without optional packages.
The parser never writes inferred facts into profile.yaml.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

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
    if path.suffix.lower() == ".docx":
        return _extract_docx_text(path)
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


def _extract_docx_text(path: Path) -> str:
    """Read Word CV paragraphs and tables in document order, without macros.

    The uploaded DOCX is private, never cached or stored in the applicant
    profile. ZIP bounds prevent decompression bombs even for a small upload.
    All extracted facts remain unverified until the owner confirms them.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        with ZipFile(path) as archive:
            parts = archive.infolist()
            if len(parts) > 1500 or sum(item.file_size for item in parts) > 24 * 1024 * 1024:
                raise ValueError("Word CV has too many or excessively large internal files.")
            if not any(item.filename == "word/document.xml" for item in parts):
                raise ValueError("Not a valid Word DOCX document.")
        doc = Document(path)
    except (BadZipFile, OSError, KeyError, ValueError) as exc:
        raise ValueError("Unable to read the Word CV. Check that it is a valid .docx file.") from exc

    lines: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                lines.append(text)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = []
                for cell in row.cells:
                    # A cell can contain several paragraphs. Word may repeat
                    # merged-cell values; deduplicate within each row only.
                    value = "\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
                    if value and value not in cells:
                        cells.append(value)
                lines.extend(cells)
    return "\n".join(lines)[:120_000]
