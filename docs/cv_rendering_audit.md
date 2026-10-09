# CV rendering remediation — inspected output, 9 October 2026

## Scope and evidence

Started from latest fetched `origin/main`, `2abf79e` (the merged application-subject fix). Work stays on the session branch `arena/db816076-jobs-finder`. The subject rules were not reimplemented or edited.

Inspected the canonical profile, `utils/documents.py`, `utils/document_design.py`, dashboard Master-CV and prepare routes, and document/evidence/privacy/immutability tests. Generated the **real canonical applicant's** Master CV before editing, in TXT, DOCX and PDF. Rasterized and visually inspected **both baseline PDF pages**, and read DOCX paragraphs, styles, page dimensions, footer XML and extracted text. The README was not used as proof of rendered quality.

The canonical `profile.yaml` is unchanged. SHA-256 before/after:

```
dcc48dcc67e686afc262f66715e155f5fc9c7ce65df96f710764c6c1d3dfd510
```

All generated files and page images are local under ignored `generated/cv-audit/`; no applicant artifacts are committed. This audit records observations, not additional applicant evidence.

## What was wrong in the actual baseline

* The 107-word summary repeated the education/registration/exam, employer list and technical competency inventory immediately printed again below. It delayed the useful experience evidence.
* The Master CV preserved source-list order, putting the 2020 COVID role before the 2020–2021 communications role. Vacancy CVs could reorder roles by relevance rather than maintain a reliable chronology. Missing end dates also sorted as if current employment.
* PDF headings requested `borderBottomWidth`, but ReportLab Paragraph does not draw that border. Both baseline pages contained **only the footer rule**, not the promised section dividers.
* The PDF mixed serif role headings with sans body text; small, light employer/location/date metadata was flattened onto a pipe-delimited line. The result was visually weak despite complete content.
* DOCX was **US Letter**, while PDF was A4. It requested Aptos/Georgia instead of the Linux PDF's DejaVu fonts, with independent sizes/spacing. The supposed 8.9 pt Word body became **8.5 pt** because Word font sizes use half-point units.
* The DOCX footer's fixed 7.2-inch right tab exceeded its text width. Competency paragraphs lacked keep-together control and styles did not expose a semantic section/role heading hierarchy.
* PDF's former compact setting reduced type to as little as 7.8 pt. Inherited `BodyText.spaceBefore` also interfered with the intended spacing, making the apparent scale different from the effective layout.

The baseline was not empty or wholly unstyled. Its failure was repetitive content, small metadata, missing separators, inconsistent format geometry and insufficient hierarchy—not missing applicant evidence that could safely be invented.

## Changes

* One flowing A4 CV column, 18 mm side margins, 16/17 mm top/bottom margins, 25 pt sans name, navy hierarchy, teal title/header rule and restrained section dividers.
* Shared DOCX/PDF scale: 10.5 pt body and competencies, 11 pt roles, 9.5 pt metadata, 9 pt contacts. Word uses the PDF's installed sans family on the generating machine. PDF embeds the available TrueType font; existing platform fallbacks remain supported.
* Real PDF section-rule flowables are kept with the heading and first content. Word uses paragraph borders, Heading 1/2-based section/role styles, widow control, keep-with-next header chains and keep-together paragraphs. Bullets use hanging indents; competency separators do not begin wrapped lines.
* Roles, bold employers/dates and locations are separate readable lines. Roles remain newest-first in **both** Master and tailored CVs. Sorting is stable, uses only supplied dates, and does not alter source data or turn missing dates into Present.
* The generated Master summary is now 44 words rather than 107. Education, credentials, employer details and all competencies still appear in their appropriate sections. Explicitly verified owner-written summaries remain verbatim. Cover-letter prose retains its separate full-context behavior.
* Tailoring still ranks verified competency groups and responsibilities, and selects relevant verified scope for the summary; chronology and underlying facts remain fixed.
* Real page-number fields in Word, right tab calculated from usable width, field-update request and properly sized footer text. PDF page numbers are drawn for each actual page.
* Sparse-page retry changes whitespace only, not font sizes. It is accepted only if it removes a page; otherwise the comfortable layout is restored. Both renderers receive the chosen scale. There is no hard page limit or forced page break.

## Final visual inspection

Regenerated the real Master CV and four representative tailored CVs through the existing APIs (synthetic vacancy requirements, **real verified applicant evidence**): Medical Officer, Health and Nutrition Supervisor, Provincial Public Health Coordinator, and Safeguarding Officer. Rasterized every CV PDF page at 130 dpi and visually inspected **all 10 final pages**, not just extracted text.

| Output | Pages | Page 1 body span | Page 2 body span |
| --- | ---: | ---: | ---: |
| Master | 2 | 88.2% | 74.4% |
| Medical Officer | 2 | 90.1% | 74.4% |
| Health and Nutrition Supervisor | 2 | 90.1% | 74.4% |
| Provincial Public Health Coordinator | 2 | 90.1% | 74.4% |
| Safeguarding Officer | 2 | 90.1% | 74.4% |

Span is the vertical range of body glyphs divided by page height minus 90 pt, excluding the footer; it is a density diagnostic, not a claim that this fraction of the page contains ink.

Observed on every final CV:

* Readable contact line, clear navy headings, actual thin section rules and restrained teal accents; no sidebars, icons or floating text.
* No clipped lines, overlapping text, missing glyphs, orphaned section headings or role headers separated from their first responsibility.
* The first three chronological roles fit on page 1. Page 2 starts with the complete COVID response role, followed by administration, education, registration, exam, training, languages and references. This is natural flow, not a programmed break.
* All five roles, six supported responsibilities, seven training entries, verified competency groups, education, registration status, Medical Exit Examination and three languages survive TXT/DOCX/PDF extraction. The absent TBT location is **not invented**.
* Pages 1 and 2 have correct visible numbering and separated footers. The last page has substantial content rather than a few stranded lines.
* Vacancy emphasis is visible: nutrition and safeguarding groups move to the top for their respective vacancies; safeguarding's supported focal-point responsibility leads within the latest role. Dates remain chronological.

DOCX final inspection found 52 main-body paragraphs, no layout tables or text boxes, A4 dimensions, 10.5 pt DejaVu Sans body, semantic heading styles, keep controls, section borders and a dynamic PAGE field within the usable width. TXT remains a readable 447-word complete Master CV.

## Verification / owner review

No new duty, achievement, date, credential, license number or reference contact was added. Verification flags and all existing evidence gates remain unchanged. Unsupported responsibilities continue to be excluded and returned in owner-facing review warnings.

The authoritative separate owner-review list remains [`held_responsibility_review.md`](held_responsibility_review.md): **24 held drafts**, advisory recommendations **15 EDIT / 9 DISCARD / 0 CONFIRM**. `python tools/export_responsibility_review.py --check` passed. That vocabulary check is not evidence and does not authorize any held claim. No second review list or alternate profile was created.

## Automated validation

Environment: Linux, Python 3.11.2 virtual environment; dependencies installed from the project's `requirements.txt` and `requirements-dev.txt`; ReportLab 5.0.1, python-docx 1.2.0, pdfplumber 0.11.10, PDFium rasterization, installed DejaVu fonts. Node 22.22.3.

* `python -m pytest -q`: **412 passed**, one upstream Starlette/httpx deprecation warning.
* `python -m ruff check .`: passed.
* `python -m compileall -q main.py dashboard utils tests`: passed.
* `node --check dashboard/static/app.js`: passed.
* `git diff --check`: passed.
* Held-responsibility review freshness check: passed.

Added real-output regressions for all-format evidence preservation, chronological order, PDF glyph bounds/line separation, real section rules, heading and role continuity, page density, numbering, Word structure and shared typography, safe compaction/restoration, long multi-page role headers/history, dashboard routes, and canonical/Master artifact immutability across all four vacancy families. Existing verification, privacy, literal-Boolean gating, subject, reference-boundary and long-document tests also pass. The old tests requiring a 90-word summary/source-list chronology were updated to the requested concise/reverse-chronological contract—not used to justify retaining repetition or incorrect dates.

## Reproduce the inspection

From the repository root, install the supported dependencies in a virtual environment, then run the following with that environment's Python. On Windows use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

```python
from datetime import date
from pathlib import Path
import pdfplumber
from docx import Document
from tests.test_cv_rendering_pipeline import vacancy
from utils.documents import prepare_application_bundle, write_master_cv
from utils.medical_matcher import match_job_against_profile
from utils.profile import load_canonical_profile

root = Path("generated/cv-audit/reproduced")
profile = load_canonical_profile(required=True)
master = write_master_cv(profile, out_dir=root / "master")
outputs = [master["generated_paths"]]
for i in range(4):
    job = vacancy(i)  # isolated representative requirements, never saved as jobs
    report = match_job_against_profile(job, profile, today=date(2026, 10, 9)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=root / f"tailored-{i}")
    outputs.append(bundle["generated_paths"]["tailored_cv"])
for paths in outputs:
    path = Path(paths["pdf"])
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            page.to_image(resolution=130).save(path.with_name(f"page-{number}.png"))
    doc = Document(paths["docx"])
    path.with_name("docx-extracted.txt").write_text(
        "\n".join(p.text for p in doc.paragraphs), encoding="utf-8"
    )
```

Inspect every resulting image and extracted document, not only the test exit status. The dashboard reaches the same rendering functions via `POST /api/master-cv` and `POST /api/jobs/{job_id}/prepare`; no alternate/sample-only renderer was added.

## Remaining limitations

* No Microsoft Word or LibreOffice layout engine was available in this sandbox. DOCX structure/text were inspected, but its **rendered pagination was not visually certified**. Font substitution and different Word engines can change line breaks; check the DOCX in the recipient's editor. PDF is the visually inspected print artifact.
* Local checks ran on Linux/Python 3.11. The repository's existing CI covers Linux/Windows with Python 3.11/3.12; local results do not establish those remote results in advance.
* Text geometry checks are useful guards, not a proof of visual quality for every possible future profile, script, font or unusually long unbroken string. No claim of universal ATS certification or guaranteed recruitment competitiveness is made.
* Stronger achievement-oriented content requires new applicant evidence. The design deliberately does not fill the 24 held-duty gaps with plausible-sounding claims.
