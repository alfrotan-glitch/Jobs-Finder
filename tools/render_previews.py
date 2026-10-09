"""Read-only applicant preview/validation tool, preserving PR #25's CLI.

Uses production generation functions and the existing pdfplumber/PDFium stack,
not a second renderer. All generated files stay in ignored local output. No
profile writes, discovery, job persistence, employer contact or submissions.

    python tools/render_previews.py --all --out generated/cv-validation
    python tools/render_previews.py --pdf documents/example.pdf --dpi 130
    python tools/render_previews.py --all --verify-docx

--verify-docx requires native LibreOffice on PATH or --libreoffice PATH. For the
sandbox's local WASM alternative, see docs/cv_integration_validation.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from utils.documents import prepare_application_bundle, write_master_cv
from utils.medical_matcher import match_job_against_profile
from utils.profile import canonical_profile_path, load_canonical_profile

FAMILIES = {
    "medical": ("Medical Officer", "Clinical care, IPC, HMIS reporting and registration"),
    "nutrition": ("Health and Nutrition Supervisor", "IMAM/CMAM, TFU, IYCF, supervision and supply forecasting"),
    "hmis": ("HMIS Officer", "DHIS2, health data management and reporting quality"),
    "coordination": ("Public Health Programme Coordinator", "BPHS/EPHS, MoPH coordination and emergency response"),
    "safeguarding": ("Safeguarding Officer", "Safeguarding, PSEA and child protection"),
}
SECTIONS = [
    "PROFESSIONAL SUMMARY", "CORE PROFESSIONAL COMPETENCIES", "PROFESSIONAL EXPERIENCE",
    "EDUCATION", "PROFESSIONAL REGISTRATION", "MEDICAL EXIT EXAMINATION",
    "PROFESSIONAL TRAINING & CERTIFICATIONS", "LANGUAGES", "REFERENCES",
]


def normalized(text: str) -> str:
    # Writer may wrap an existing hyphenated word at its hyphen. Join only
    # that physical line break, not words or source punctuation generally.
    text = re.sub(r"(?<=[\w])([-–])\n\s*(?=\w)", r"\1", text)
    return " ".join(text.split()).replace(" — ", " ")


def render_pdf(pdf: Path, out_dir: Path, dpi: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with pdfplumber.open(pdf) as document:
        for number, page in enumerate(document.pages, 1):
            path = out_dir / f"{pdf.stem}_p{number}.png"
            page.to_image(resolution=dpi).save(path)
            paths.append(path)
    return paths


def inspect_pdf(path: Path, model: dict) -> dict:
    """Fail on evidence loss or visible-layout defects, including Writer output.

    This is an independent rendered-output check, not a substitute for opening
    every PNG. Facts are checked in order; no source words are discarded.
    """
    with pdfplumber.open(path) as document:
        page_texts = [normalized(page.extract_text() or "") for page in document.pages]
        text = " ".join(page_texts)
        values = [model["name"], model["headline"], model["profile"], *model["contact_lines"]]
        for key in ("education", "registration", "exit_exam", "certifications", "references"):
            values.extend(model[key])
        for group in model["expertise"]:
            values.extend([group["group"], *group["items"]])
        for name, level in model["languages"]:
            values.extend([name, level])
        for role in model["experience"]:
            header = [role[k] for k in ("role", "org", "loc", "dates") if role[k]]
            values.extend([*header, *role["bullets"]])
            start = " ".join(role["bullets"][0].split()[:12]) if role["bullets"] else ""
            assert any(all(normalized(v) in page for v in [*header, start]) for page in page_texts), role["role"]
        for value in values:
            assert normalized(value) in text, f"Missing evidence in {path.name}: {value}"
        assert "(cid:" not in text and "\ufffd" not in text, "Undefined glyph"
        for labels in (SECTIONS, [role["role"] for role in model["experience"]]):
            positions = [text.index(label) for label in labels]
            assert positions == sorted(positions), "Section or chronology order changed"
        pages = []
        for number, page in enumerate(document.pages, 1):
            assert abs(page.width - 595.28) < .2 and abs(page.height - 841.89) < .2, "Not A4"
            assert all(49 <= c["x0"] < c["x1"] <= page.width - 49 for c in page.chars if c["text"].strip()), "Horizontal clipping"
            assert all(42 <= c["top"] < c["bottom"] <= page.height - 16 for c in page.chars), "Vertical clipping"
            footer = page.crop((0, page.height - 40, page.width, page.height))
            assert re.findall(r"Page\s+\d+", footer.extract_text() or "") == [f"Page {number}"], "Broken PAGE field"
            page_word = next(w for w in footer.extract_words() if w["text"] == "Page")
            assert page_word["x0"] > page.width * .8, "Footer tab stopped at an inherited centre tab"
            assert all(abs(c["size"] - 7) < .15 for c in footer.chars), "Field result inherited body font size"
            body = page.crop((0, 0, page.width, page.height - 45))
            lines = body.extract_text_lines()
            assert lines and lines[-1]["text"] not in SECTIONS, "Orphaned heading"
            for first, second in pairwise(lines):
                assert first["bottom"] <= second["top"] + .5, "Overlapping text lines"
            for line in lines:
                if line["text"] in SECTIONS:
                    assert any(abs(e["top"] - line["bottom"]) < 12 and e["width"] > page.width * .7 for e in page.edges if e["orientation"] == "h"), "Missing section divider"
            # Supplied year ranges must not wrap into separate years in Writer.
            for education in model["education"]:
                for span in re.findall(r"\d{4}–\d{4}", education):
                    if span in page_texts[number - 1]:
                        assert any(span in line["text"] for line in lines), "Split education year range"
            fill = (lines[-1]["bottom"] - lines[0]["top"]) / (page.height - 90)
            pages.append({"page": number, "body_span": round(fill, 3), "lines": len(lines)})
        if len(pages) > 1:
            assert pages[-1]["body_span"] >= .4, "Sparse final page"
        return {"producer": document.metadata.get("Producer"), "pages": pages}


def generate_cases(out: Path, all_families: bool) -> dict:
    profile = load_canonical_profile(required=True)
    source_before = canonical_profile_path().read_bytes()
    master = write_master_cv(profile, out_dir=out / "master")
    cases = {"master": {"paths": master["generated_paths"], "model": master["master_cv_model"]}}
    master_bytes = {key: Path(path).read_bytes() for key, path in master["generated_paths"].items()}
    warnings = {"master": master["review_warnings"]}
    for key, (title, requirements) in (FAMILIES.items() if all_families else []):
        job = {
            "id": f"preview-{key}", "title": title, "company": "Preview Organization",
            "location": "Afghanistan", "url": f"https://preview.example.org/{key}",
            "apply_url": "hr@example.org", "metadata": {"closing_date": "2026-12-31"},
            "description": f"Medical Doctor accepted. {requirements} required. Apply to hr@example.org by 2026-12-31.",
        }
        report = match_job_against_profile(job, profile).to_dict()
        bundle = prepare_application_bundle(job, profile, report, out_dir=out / key)
        cases[key] = {"paths": bundle["generated_paths"]["tailored_cv"], "model": bundle["tailored_cv_model"]}
        warnings[key] = bundle["review_warnings"]
    assert canonical_profile_path().read_bytes() == source_before
    assert all(Path(master["generated_paths"][key]).read_bytes() == data for key, data in master_bytes.items())
    (out / "review-warnings.json").write_text(json.dumps(warnings, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "profile.sha256").write_text(hashlib.sha256(source_before).hexdigest(), encoding="ascii")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Rasterize an existing PDF instead of generating CVs.")
    parser.add_argument("--all", action="store_true", help="Also generate the representative vacancy families.")
    parser.add_argument("--out", type=Path, default=Path("generated/cv-validation"))
    parser.add_argument("--dpi", type=int, default=110)
    parser.add_argument("--inspect-docx", action="store_true", help="Inspect/rasterize existing DOCX-converted PDFs against cases.json (WASM workflow).")
    parser.add_argument("--verify-docx", action="store_true", help="Convert DOCX with native LibreOffice; fail if unavailable.")
    parser.add_argument("--libreoffice", default=shutil.which("libreoffice") or shutil.which("soffice"))
    args = parser.parse_args()
    if not 72 <= args.dpi <= 300:
        parser.error("--dpi must be 72..300")
    if args.verify_docx and not args.libreoffice:
        parser.error("--verify-docx requires LibreOffice; see the documented WASM alternative")
    if args.pdf:
        for path in render_pdf(args.pdf, args.out, args.dpi):
            print(path)
        return 0
    if args.inspect_docx:
        cases = json.loads((args.out / "cases.json").read_text(encoding="utf-8"))
        assert (args.out / "profile.sha256").read_text() == hashlib.sha256(canonical_profile_path().read_bytes()).hexdigest()
    else:
        cases = generate_cases(args.out, args.all)
    metrics = {}
    for key, case in cases.items():
        pdf = Path(case["paths"]["pdf"])
        metrics[key] = {"pdf": inspect_pdf(pdf, case["model"])}
        render_pdf(pdf, pdf.parent / "pdf-pages", args.dpi)
        if args.verify_docx:
            converted_dir = pdf.parent / "libreoffice"
            converted_dir.mkdir(parents=True, exist_ok=True)
            command = [args.libreoffice, "-env:UserInstallation=" + (args.out / "lo-profile").resolve().as_uri(),
                       "--headless", "--convert-to", "pdf", "--outdir", str(converted_dir), case["paths"]["docx"]]
            subprocess.run(command, check=True, timeout=90)
        if args.verify_docx or args.inspect_docx:
            converted_dir = pdf.parent / "libreoffice"
            converted = converted_dir / pdf.name
            metrics[key]["docx"] = inspect_pdf(converted, case["model"])
            render_pdf(converted, converted_dir / "pages", args.dpi)
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
