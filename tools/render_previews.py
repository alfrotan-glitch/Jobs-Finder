"""Local visual-inspection tooling for the Jobs-Finder document design system.

This is a **developer-only, read-only** helper: it renders the generated CV /
cover-letter PDFs to PNG so a human can eyeball typography, hierarchy, spacing
and pagination. It never edits ``profile.yaml``, never changes the renderers,
and never submits anything.

The deterministic structural contract lives in the test-suite (see
``tests/test_cv_professional_quality.py``), which inspects the *real* PDF/DOCX
artifacts with ``pdfplumber`` and ``python-docx``. Visual regression testing in
CI would require shipping a heavyweight rasterizer/font stack, so per the
project convention this tool provides the reproducible *local* visual check
instead, and is optional: it degrades gracefully when its only extra dependency
(``pymupdf``) is not installed.

Usage::

    # Render the position-neutral Master CV (regenerates it first):
    python tools/render_previews.py

    # Render a specific generated PDF at a chosen DPI into a folder:
    python tools/render_previews.py --pdf documents/master_cv/<name>.pdf --dpi 130 --out .arena/previews

    # Render the Master CV plus tailored CVs for the representative families:
    python tools/render_previews.py --all

Output PNGs are written under an ignored directory (``*.png`` and ``documents/``
are both git-ignored) so no personal data or raster artifacts are ever staged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _require_pymupdf():
    try:
        import pymupdf
    except Exception:
        try:  # older wheel exposes the module as ``fitz``
            import fitz as pymupdf  # type: ignore
        except Exception:
            return None
    return pymupdf


def render_pdf(pdf: Path, out_dir: Path, dpi: int) -> list[Path]:
    pymupdf = _require_pymupdf()
    if pymupdf is None:
        print(
            "pymupdf is not installed; visual preview skipped.\n"
            "Install it for local inspection only (not a runtime requirement):\n"
            "    python -m pip install pymupdf",
            file=sys.stderr,
        )
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with pymupdf.open(str(pdf)) as doc:
        for index, page in enumerate(doc, 1):
            target = out_dir / f"{pdf.stem}_p{index}.png"
            page.get_pixmap(dpi=dpi).save(str(target))
            written.append(target)
    return written


def _master_pdf() -> Path:
    from utils.documents import write_master_cv
    from utils.profile import load_canonical_profile

    profile = load_canonical_profile(required=True)
    return Path(write_master_cv(profile)["generated_paths"]["pdf"])


def _tailored_pdfs(out_base: Path) -> list[Path]:
    from utils.documents import prepare_application_bundle
    from utils.medical_matcher import match_job_against_profile
    from utils.profile import load_canonical_profile

    profile = load_canonical_profile(required=True)
    families = {
        "medical": "Medical Doctor required. IPC, clinical audit, HMIS reporting. Apply to hr@example.org.",
        "nutrition": "Health & Nutrition Supervisor. IMAM/CMAM, TFU/OTP, IYCF, HMIS/DHIS2, supply forecasting. Apply to hr@example.org.",
        "hmis": "HMIS Officer. DHIS2, health data management and quality, HMIS training. Apply to hr@example.org.",
        "coordination": "Public Health Programme Coordinator. BPHS/EPHS, MoPH coordination, supervision. Apply to hr@example.org.",
    }
    pdfs: list[Path] = []
    for key, description in families.items():
        job = {
            "id": f"preview-{key}",
            "title": description.split(".")[0],
            "company": "Preview Organization",
            "location": "Afghanistan",
            "url": f"https://preview.example.org/{key}",
            "apply_url": "hr@example.org",
            "description": description,
            "metadata": {"closing_date": "2026-12-31"},
        }
        report = match_job_against_profile(job, profile).to_dict()
        bundle = prepare_application_bundle(job, profile, report, out_dir=out_base)
        pdfs.append(Path(bundle["generated_paths"]["tailored_cv"]["pdf"]))
    return pdfs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Path to an existing generated PDF to preview.")
    parser.add_argument("--all", action="store_true", help="Also render tailored CVs for the representative vacancy families.")
    parser.add_argument("--dpi", type=int, default=110)
    parser.add_argument("--out", default=".arena/previews", help="Ignored output folder for PNGs.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    pdfs = [Path(args.pdf)] if args.pdf else [_master_pdf()]
    if args.all:
        pdfs += _tailored_pdfs(out_dir / "applications")

    total: list[Path] = []
    for pdf in pdfs:
        if not pdf.is_file():
            print(f"missing PDF: {pdf}", file=sys.stderr)
            continue
        total.extend(render_pdf(pdf, out_dir, args.dpi))

    if not total:
        return 2
    for path in total:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
