# Final CV integration and rendered-output validation

Date: 9 October 2026. This supersedes the *environmental limitations* in the
[initial rendering audit](cv_rendering_audit.md), not its historical findings.
Final merge SHAs and exact-commit CI links are recorded in the
[PR #26 integration timeline](https://github.com/alfrotan-glitch/Jobs-Finder/pull/26).

## Verified starting state, not PR-description assumptions

Fetched `origin/main`: `2abf79ee6bd1e603370966ecbb13022c3ba2f93d`.
Working tree was clean on the existing session branch
`arena/db816076-jobs-finder`. No new working branch or PR was created.

| PR | Base | Head at initial inspection | State at inspection |
| --- | --- | --- | --- |
| #25 | `main` | `arena/7ccaf008-jobs-finder`, `9325e5d989df8d09f7ee4287ede4629748bda519` | Open, unmerged, mergeable; no reviews/comments |
| #26 | `main` | `arena/db816076-jobs-finder`, `bb23f3065b325e289a7c8a5e323a3aeeecda9469` | Open, unmerged, mergeable; no reviews/comments |

Both share merge-base `2abf79e`; neither contains the other. #25 has commits
`88e7768`, `9325e5d`; #26 initially has `b3696f2`, `8e7e995`, `bb23f30`.
Their four-job Windows/Linux Python 3.11/3.12 matrices were green:
[#25 run](https://github.com/alfrotan-glitch/Jobs-Finder/actions/runs/37909537709),
[#26 initial run](https://github.com/alfrotan-glitch/Jobs-Finder/actions/runs/37934264522).

GitHub reported `main` unprotected and merge commits allowed; the repository's
current tip is itself a PR merge commit. The detailed branch-protection endpoint
returned an integration-permission 403, but branch metadata reported no required
contexts. That is not treated as a reason to bypass CI: final integration waits
for the four test jobs **and** the new native Writer job. The user explicitly
authorized integration. No approval is invented, no force push is used, and no
shared history is rewritten.

## Reconciliation: one renderer, preserve valuable safeguards

| #25 improvement | Integrated disposition in #26 |
| --- | --- |
| Master chronology | Covered and extended by #26: Master **and tailored** chronology, stable ties, missing dates do not mean Present. #25 did not actually change tailored relevance-based role ordering despite its README claim. |
| Exact displayed role dates | Preserved in `test_master_cv_model_is_comprehensive_for_the_real_profile`. |
| Parse/rendered-date chronology guard | Covered by the independent literal rendered-date sequence above, plus all-format chronology and unknown-date regressions in `test_cv_rendering_pipeline.py`; no second date parser retained. |
| Summary de-duplication | Preserve #25's inventory-overlap guard in the real-profile test. #26's shorter generated summary supersedes #25's five-item keyword reprint; verified owner-written summaries remain untouched. |
| Long role/employer wrapping in PDF **and DOCX** | Preserve #25's test, in addition to #26's long multi-page geometry test. |
| Repeat rendering/source stability | Preserve #25's test comparing extracted TXT/PDF/DOCX content and the source mapping. |
| No orphan section headings | #26's stronger geometry guard covers every page, filters footer by coordinates rather than applicant name, and also checks role/first-duty continuity. |
| Two-line competency index | Superseded by #26's compact, bold-labelled groups with keep-together controls, actual section rules and larger readable type. The alternate index added vertical bulk and its Word label paragraph lacked keep-with-next. No second design variant retained. |
| Gold masthead hairline | Superseded by the inspected navy/teal CV identity and real teal header rule in both formats; gold is not added to the CV. Cover-letter styling/subject rules remain separate and unchanged. |
| `.arena/` ignore | Preserved. |
| `tools/render_previews.py` | Preserved and extended: same existing-PDF/Master/`--all`/DPI/output capabilities, using already-supported pdfplumber/PDFium instead of adding optional PyMuPDF. Includes HMIS and safeguarding variants and actual Writer-output validation. |
| README | Replaced conflicting prose with the actual integrated behavior and reproducible inspection commands. |

Thus #25 can be closed as superseded **after** #26 is merged and its changes are
verified on `main`. There is no need to merge both overlapping implementations.
Branches are retained for traceability rather than deleted during integration.

## Actual DOCX rendering resolved the previous limitation

No native `libreoffice`, `soffice`, Microsoft Word or Python 3.12 executable was
present in the Debian 12 sandbox. The permitted npm registry supplied a compatible
local Writer environment: `@matbee/libreoffice-converter@2.7.2`, MPL-2.0, containing
LibreOffice WebAssembly binaries. It was installed **only under ignored
`generated/word-render-env/`**, not as an application dependency. No cloud conversion
service was used. System DejaVu fonts were loaded into the engine.

The converted PDFs identify their producer as **LibreOfficeDev 24.8.8.0.0 (x86) /
LibreOffice Community**, creator Writer. This is real DOCX layout/conversion,
not rendering extracted text or pretending the native ReportLab PDF came from Word.

The first Writer rendering exposed three defects missed by the former XML-only checks:

1. The built-in Footer style's inherited centre tab intercepted the page label
   before the custom right tab. Fix: dedicated `CV Footer` based on Normal.
2. PAGE lacked a separator/cached result; Writer rendered the result at body size.
   Fix: a complete begin/instruction/separate/result/end field, with a 7 pt footer
   style and update-fields request. Both actual pages now show their correct number
   at the right edge. Footer rule is above the text, consistent with PDF.
3. The long education line split `2013–2020` between years. Fix: logically separate
   the supplied degree/field from institution/dates, keeping all original words in
   order and retaining the 10.5 pt body size. No typography shrink-to-fit, date
   replacement, or arbitrary page break was used.

All source components remain asserted: the education test ignores only the em-dash
separator replaced by a paragraph boundary, not any word, institution or date.
It also asserts lossless reconstruction of the source from the display lines.
The Writer checker independently rejects year ranges split across lines.

## Final files inspected

Production functions `write_master_cv` and `prepare_application_bundle`, called
by the dashboard, generated the **real canonical applicant** in TXT/DOCX/PDF for:
Master, Medical Officer, Health and Nutrition Supervisor, HMIS Officer, Public
Health Programme Coordinator, and Safeguarding Officer. Vacancy requirements are
isolated inspection fixtures, not real discovered jobs or employer communications.

For each of the six CVs, both native PDF pages and both Writer-rendered DOCX pages
were rasterized at 110 dpi and visually opened: **24 final pages inspected**.
All six TXT and DOCX evidence sets were also read/extracted and checked against
the same canonical model; all native and converted PDFs passed complete evidence,
chronology, geometry, field and density checks.

| Variant | Native PDF pages / body span | Writer DOCX pages / body span |
| --- | --- | --- |
| Master | 2 / 88.2%, 74.8% | 2 / 88.8%, 77.5% |
| Medical | 2 / 90.1%, 74.8% | 2 / 90.7%, 77.5% |
| Nutrition | 2 / 90.1%, 74.8% | 2 / 90.7%, 77.5% |
| HMIS | 2 / 90.1%, 74.8% | 2 / 90.7%, 77.5% |
| Coordination | 2 / 90.1%, 74.8% | 2 / 90.7%, 77.5% |
| Safeguarding | 2 / 90.1%, 74.8% | 2 / 90.7%, 77.5% |

Span is the vertical body-glyph range divided by page height minus 90 pt, not ink
coverage. These page counts describe the inspected profile, **not a renderer limit**.
Observed: consistent A4 navy/teal hierarchy and margins, readable contacts, real
rules, correctly sized/aligned page fields, readable hanging bullets, unbroken
education dates, natural chronology and page breaks, no clipping/overlap, undefined
glyphs, orphan headings/role headers, or sparse final page. Writer and ReportLab
have minor natural line-wrapping/spacing differences, not missing evidence.

Dashboard integration was separately exercised with TestClient, an isolated SQLite
job database and output root, and the **real canonical loader, matcher, persistence
functions and renderer**. `POST /api/master-cv` and `POST /api/jobs/{id}/prepare`
returned 200 and real new TXT/DOCX/PDF paths. Those files passed evidence and PDF
checks. The synthetic vacancy remained `PACKAGE_NEEDS_INPUT`, not applied; no
readiness safeguard was bypassed. The owner's real job database was not touched.

## Commands and validation

Local environment: Debian 12, Python 3.11.2 virtual environment, Node 22.22.3,
ReportLab 5.0.1, python-docx 1.2.0, pdfplumber 0.11.10; supported requirements files.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m compileall -q main.py dashboard utils tests tools
node --check dashboard/static/app.js
node --check tools/render_docx.mjs
git diff --check
.venv/bin/python tools/export_responsibility_review.py --check
```

Results: **421 tests passed**, one upstream Starlette/httpx deprecation warning;
all other checks passed. The full suite includes matching, readiness, package,
privacy, literal-Boolean verification, profile/Master immutability, fontless
fallback, long-history, dashboard and all-format evidence regressions. No failing
test is skipped and no useful assertion is removed to pass rendering checks.

Reproduce native PDF and DOCX/XML/text generation, plus Writer visual inspection:

```bash
.venv/bin/python tools/render_previews.py --all --out generated/cv-integration
npm install --prefix generated/word-render-env --ignore-scripts --no-audit --no-fund @matbee/libreoffice-converter@2.7.2
node tools/render_docx.mjs generated/cv-integration/cases.json
.venv/bin/python tools/render_previews.py --out generated/cv-integration --inspect-docx
```

`CV_LO_PREFIX` can point to another ignored installation prefix. The JS helper
awaits every conversion, writes locally, destroys the worker and exits explicitly
because this package leaves request-timeout timers active after destruction.
Open **every** `pdf-pages/*.png` and `libreoffice/pages/*.png`, not just the manifest.
Output also includes a local model manifest, validation metrics and separate
owner-review warnings. None is committed.

For native LibreOffice (the dedicated Ubuntu 24.04/Python 3.12 CI job):

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends -y libreoffice-writer fonts-dejavu-core
python tools/render_previews.py --all --verify-docx --dpi 110 --out generated/ci-cv-validation
```

The existing four test jobs retain Linux/Windows × Python 3.11/3.12. The fifth job
performs native Writer conversion and checks actual fields, page geometry,
dividers, density, year-range wrapping, role continuity and extracted evidence
for all six CVs. Applicant files are ephemeral on the runner: no public artifact
upload step is present. Exact final PR-head and main-merge runs are linked in the
PR timeline/final delivery rather than guessing future commit IDs in this file.

## Applicant truth and remaining limitations

`profile.yaml` remains byte-identical to original `main`, SHA-256
`dcc48dcc67e686afc262f66715e155f5fc9c7ce65df96f710764c6c1d3dfd510`.
All five roles, six verified responsibilities, registration status, Medical Exit
Exam, education, seven training entries, three languages and other verified skills
remain intact. All **24 held duty drafts** remain excluded and owner-visible in
the unchanged authoritative review report. No license numbers, dates, credentials,
achievements or reference contacts were added. No applications were submitted.

Microsoft Word itself is still unavailable. **DOCX visual verification is through
LibreOffice Writer**, not a claim of Microsoft Word certification. Another editor
or substituted font can reflow the document; the native PDF is the stable print
artifact. No universal ATS certification, employment guarantee or blanket guarantee
for every future profile/script/font is made. No applicant artifacts or optional
WASM binaries belong in Git.
