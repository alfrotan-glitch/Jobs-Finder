# Jobs-Finder

Jobs-Finder is a lightweight Windows-first assistant for Afghanistan job search and application preparation.

It helps one user answer:

> Which Afghanistan vacancies are relevant to my verified CV/profile, why do they fit, and what application package should I review before applying?

## What it does

1. Finds Afghanistan-relevant vacancies from maintained sources.
2. Normalizes and deduplicates vacancies.
3. Extracts practical requirements: education, license/registration, experience, languages, location, deadline, documents, application URL/email, subject/reference.
4. Compares the vacancy against verified canonical-profile evidence.
5. Classifies the vacancy as:
   - `READY_TO_APPLY`
   - `NEEDS_VERIFICATION`
   - `NOT_ELIGIBLE`
6. Explains the match in plain language.
7. Prepares a review-first application package:
   - tailored CV: TXT, DOCX, PDF
   - tailored cover letter: TXT, DOCX, PDF
   - application instructions/checklist
   - missing-fact warnings
   - official application URL or email
8. Opens the official application route for the user to complete manually.

## What it does not do

Jobs-Finder is not a recruiter bot, form-submission bot, email monitor, or generic global job-board aggregator.

It does **not**:

- submit applications automatically
- bypass CAPTCHA, login, MFA, or employer security controls
- invent experience, license numbers, documents, dates, achievements, references, or skills
- silently run continuous scans when the dashboard starts
- monitor email or perform post-submission automation

## Windows one-click start

From the repository folder, double-click:

```text
run_jobs_finder.bat
```

The launcher:

- uses this project directory
- creates exactly one project `.venv` if missing
- installs from `requirements.txt`
- starts only the dashboard
- opens <http://localhost:8080>
- does not run background scanning or submit applications

Python support is intentionally conservative: Python 3.11 and 3.12. The full test suite runs in GitHub Actions CI on both Linux (`ubuntu-latest`) and Windows (`windows-latest`) for both Python versions. `run_jobs_finder.bat` itself (the venv-creating launcher script) is not executed by CI -- its logic is reviewed and covered by assertions in the test suite, but it has not been run end-to-end on an interactive Windows desktop as part of this validation. If installation fails on another Python version, use Python 3.11 or 3.12 and rerun the launcher.

## Manual setup

The dashboard binds to `127.0.0.1` by default and is not exposed to the LAN. Choose a different host explicitly only when you understand the privacy implications.


```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# profile.yaml is already the tracked canonical applicant record.
python main.py server --host 127.0.0.1 --port 8080
```

Open <http://localhost:8080>.

## Running the tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

The same suite also runs automatically in GitHub Actions CI
(`.github/workflows/tests.yml`) on `ubuntu-latest` and `windows-latest`
with Python 3.11 and 3.12 for every push and pull request to `main`, so
test execution is verified on both Linux and Windows. Before pytest, CI also
runs Ruff, compiles the Python entry points/modules/tests, and checks the
dashboard JavaScript syntax with Node. The Windows one-click start script
(`run_jobs_finder.bat`) is reviewed and assertion-covered but is not itself
executed by CI.

## Profile/CV setup

`profile.yaml` at the repository root is the **only** production applicant record and is Git-tracked. It is the shared source used by the Agent workspace, GitHub, and a normal `git pull` in the Windows Desktop checkout. The CLI, dashboard, matching, recommendations, readiness checks, Master-CV generation, and document/package generation all resolve that one file through the same profile repository. `profile.yaml.example` is schema documentation only; it is never loaded as applicant data, copied as a runtime profile, or used as a fallback.

Important rules:

- Change the one tracked `profile.yaml` directly; commit and push it to synchronize the authorized canonical record between checkouts.
- Leave missing facts blank or marked `Needs verification`.
- Every claim, including experience duration, location preference, and deployment preference, needs its own adjacent literal `verified: true` before it is verified evidence.
- Do not invent license numbers, issue dates, expiry dates, document paths, credentials, or language levels.
- Professional reference contact data is **not stored in the tracked canonical profile or repository**. The canonical profile holds only a private-reference boundary. If the owner keeps a private reference file, it must be outside the repository, explicitly selected with `JOBS_FINDER_PRIVATE_REFERENCES_PATH`, and can only be read for a vacancy that explicitly requires references **and** after vacancy-specific owner approval. References are never matching evidence and are never automatically serialized into a CV, cover letter, dashboard response, SQLite record, or normal package.
- The database stores vacancies, scans, match outputs, and packages — never a second applicant profile.
- Resume extraction caches are not used. A CV is not runtime applicant evidence.

### Canonical-profile release contract

The release profile is checked by `utils.profile.assert_canonical_profile_complete()` and CI regression tests. It verifies the real identity/contact details, MD education (field, institution, and 2013–2020 dates), Medical Exit Exam, valid registration status, verified lower-bound clinical experience, supplied work history, medical/public-health/management skills, languages, certificates, humanitarian evidence, and the private-reference boundary.

The contract reports four distinct states instead of forcing fabricated precision:

- `VERIFIED` — explicitly verified fact;
- `KNOWN_BUT_NON_PRECISE` — verified fact with intentionally unknown exact dates/duration;
- `NEEDS_VERIFICATION` — evidence is absent or unverified;
- `NOT_PROVIDED` — optional precision (for example a license number or expiry date) is intentionally absent.

The current profile deliberately records `> 3` as a lower bound, has blank ACF-role dates, and has no license number/date/document path. Those are not defects to be filled with guesses.

CV import is a transient **preview only**; it cannot write or replace `profile.yaml`, create a backup/draft profile, retain an upload, or automatically verify anything:

```bash
python main.py import-cv path/to/cv.pdf
```

Review the output, then manually add only facts you personally confirm to canonical `profile.yaml` before scanning or preparing documents.

### Position-neutral Master CV

Generate or refresh the local Master CV only from verified canonical evidence:

```bash
python main.py master-cv
```

It writes TXT, DOCX, and PDF files under ignored `documents/master_cv/`. The Master CV contains no vacancy, employer, target-role, or application wording; it is a comprehensive, position-neutral presentation of the verified canonical profile. `prepare` is the separate downstream step that analyzes one vacancy and creates a vacancy-specific CV by selecting and reordering that same evidence — it modifies neither `profile.yaml` nor the Master CV.

The same Master CV is generated from the dashboard (**My Profile → Position-neutral Master CV → Generate Master CV**, `POST /api/master-cv`); it is a local write, never a submission.

#### Master CV architecture

The CV is deliberately comprehensive rather than short. Nothing verified is dropped to reduce page count, and the sections are ordered the way an international NGO / medical recruiters reads them:

1. **Header** — verified name, verified professional title, verified email/phone/location.
2. **Professional summary** — a substantive paragraph assembled only from verified evidence: the verified MD degree (field and institution), completed Medical Exit Examination, valid registration status, the verified duration *lower bound* spelled out in words ("more than three years"), the verified experience dimensions, the verified employers, the verified competency inventory, and the verified languages. Owners may override it with their own reviewed `professional_summary.text`.
3. **Core professional competencies** — a grouped skills architecture (Clinical & Medical Practice; Health & Nutrition Programming; Public Health Systems & Quality; Programme Coordination & Field Operations; Supervision & Capacity Building; Safeguarding, Protection & Compliance; Supply Chain, Logistics & Administration; plus an "Additional Professional Competencies" group for anything else), containing every verified competency exactly once as ATS-readable text.
4. **Professional experience** — every verified role with employer, location, and the dates exactly as supplied (blank ACF dates stay blank; supplied `2020-10` prints as "Oct 2020"), each with its **applicant-supported** professional scope. A detailed duty is printed only when the applicant actually supplied it; see the verification gate below.
5. **Education, Professional Registration, Medical Exit Examination, Professional Training & Certifications, Languages** — every verified credential, with the registration presented only as the verified status (never an invented number, authority, or date).
6. **References** — "Available on request for shortlisted applications." Private referee contacts are never printed; they can only be released through the vacancy-requirement + explicit-owner-approval boundary.

`responsibilities` in `profile.yaml` is the verification-gated professional description of each role: only `{text: ..., verified: true}` is confirmed experience, and the test suite enforces that each line introduces no number, no new named entity, place, employer, date, or achievement result beyond what the applicant supplied.

**A claim needs applicant evidence, not a plausible inference.** A role title ("Medical Doctor"), a verified skill ("Infection Prevention and Control"), a certificate, the sector's normal practice, or what the employer usually does are **not** evidence that the applicant performed a duty. The system therefore never derives a duty from them.

Detailed duties that were suggested rather than supplied are held in `needs_verification` on the role:

* preserved verbatim in `profile.yaml`, so nothing is lost;
* excluded from every generated document (Master CV, tailored CV, cover letter, package text and email) by the generator itself, not merely by convention;
* reported to the owner as a review warning, and displayed in the dashboard under *"Awaiting your confirmation — not used in any generated CV"*;
* published only when the owner moves the line to `responsibilities` with `verified: true`.

The shipped canonical profile therefore prints the duties the applicant's own CV documents for each role, and nothing else: where the applied duties cover only part of a held draft, only that part is printed, and the rest stays held. The CV stays comprehensive through the evidence that *is* verified — the applicant-supported responsibilities, the grouped competency inventory, all seven certifications, education, registration status, exit exam, languages, and every role.

#### Tailoring (downstream of the Master CV)

```
verified canonical profile
        → comprehensive position-neutral Master CV
        → vacancy analysis (matcher/extraction)
        → vacancy-specific selection + reordering
        → tailored CV + cover letter (TXT/DOCX/PDF)
```

Tailoring changes **order, grouping, and emphasis only**:

* a Medical Doctor vacancy leads with clinical and public-health/quality evidence;
* a Health/Nutrition vacancy leads with the nutrition programming group and nutrition-first responsibilities;
* coordination/programme roles lead with coordination, supervision, and reporting evidence;
* safeguarding roles lead with the verified safeguarding/PSEA/child-protection group, scope, and training.

The advertised vacancy title is the strongest relevance signal, and employer long-form wording maps to the verified acronym it names (`infection prevention and control` → `IPC`, `sexual exploitation` → `PSEA`, `health data management` → `HMIS`, `capacity building`, `clinical audit`, `field`, `protection`). Those mappings control **emphasis only** — they can never create evidence that does not already exist.

Every verified role, responsibility, certificate, language, and credential is still printed in every tailored CV, and the canonical profile plus the Master CV are re-asserted byte-for-byte unchanged in the test suite (`tests/test_cv_professional_quality.py`, `tests/test_tailoring_immutability.py`).

Professional reference contacts are outside the tracked canonical profile and are never printed in a Master CV or vacancy-specific CV. When a vacancy asks for references, the package presents a generic manual checklist; the owner may decide to release approved contacts through the documented external private-reference boundary.

### Local dashboard privacy

The dashboard is a local workstation interface, not a hosted multi-user service:

- It binds to `127.0.0.1` by default. Do not bind it to a shared or public network without adding real access control and a TLS reverse proxy.
- Browser responses use no-store cache headers, restrictive content/frame/referrer policies, and no CORS opt-in. State-changing browser requests with a foreign `Origin` or `Referer` are rejected.
- Interactive API documentation endpoints are disabled; the supported interface is the dashboard and the documented CLI.
- Dashboard CV previews accept PDF or plain-text formats only, stream the upload through an 8 MiB bound, process it in a temporary directory, and delete the temporary input before responding. This is a preview boundary, not a profile-import feature.

These browser protections reduce accidental local exposure; they are **not** authentication or a reason to expose the dashboard publicly.

## Find jobs

CLI:

```bash
python main.py find
python main.py recommended
python main.py jobs
```

Dashboard:

1. Open the app.
2. Optionally use **My Profile → Preview a CV** to inspect unverified proposed facts. It does not change your profile. Manually add any facts you personally confirm to `profile.yaml`, then use **Verification review** to set only the matching verified flag. Nothing from a CV import is ever shown as verified automatically.
3. Press **Find Jobs**.
4. Review **Recommended**.
5. Select a vacancy and press **Prepare package**.
6. Review the generated files.
7. Open the official route and apply manually.

The **Settings** tab shows the current, non-editable system configuration (active sources, ACBAR connection settings, ReliefWeb result limit, and the fact that background scanning and automatic submission are both disabled) -- it has no nonfunctional controls.

## Source status semantics

Jobs-Finder distinguishes market results from technical failures:

- `SCAN_COMPLETE` — reachable sources returned relevant jobs.
- `NO_RELEVANT_JOBS_FOUND` — reachable sources were scanned and no relevant current roles were found.
- `PARTIAL_SCAN` — at least one source worked, but a source failed, pagination could not reach its real end, or an explicitly configured page/detail limit deferred part of the scan.
- `SOURCES_UNAVAILABLE` — all active sources were unreachable.
- `SCAN_FAILED` — no active source configuration was available.

A result of zero jobs is never used to claim the Afghanistan market is empty when sources were unreachable.

## Active sources

Maintained active sources are intentionally few:

- **Tier A: ACBAR Jobs** — core Afghanistan NGO/INGO job board. Normal discovery follows `?page=N` until ACBAR returns a real empty listing page (`END_REACHED`), deduplicates all current cards, and cross-checks the discovered total against the count published by ACBAR. Detail pages are opened only for plausible health/medical candidates, with bounded concurrency (`max_detail_concurrency`, default 5) and a per-request timeout. The shipped profile does not configure ACBAR page or detail budgets; ACBAR completion is the source's real end page.
- **One recommendation authority** — `Recommended from this scan` is exactly the length of the recommendation collection the scan produced (`utils/recommendations.py`), and the CLI list, the dashboard Recommended view, and persisted scan activity all render that same collection; nothing recomputes recommendations independently. Dashboard/API recommendation responses carry explicit saved-scan timestamps (or a stored-history label), so historical results are never presented as a live market refresh. Broad discovery keeps programme/operations roles reviewable in the jobs list, but only roles with a positively MD/public-health-compatible classification are recommended.
- **Tier B: ReliefWeb Afghanistan jobs** — secondary humanitarian source filtered for health/medical/public-health terms. The maintained adapter currently requests one bounded result page (default `limit: 20`) and then opens the retained detail pages. If that page reaches the configured limit, the scan is explicitly reported `PARTIAL_SCAN` / `RESULT_LIMIT_REACHED`; it is not represented as ReliefWeb pagination completion. Fewer results than the bound are reported as the observable end of that one-page route.

Other official employer and UN routes are treated as trusted application routes when discovered, but not claimed as active parser-backed sources unless maintained.

### Provenance and direct-route rule

Every vacancy preserves four independent fields: `source_url` (official listing/home source), `vacancy_url` (the advertised vacancy page), `application_url` (a direct form), and `application_email`. A missing source URL remains **missing**; the system never substitutes the vacancy page. A vacancy page by itself is not a direct application route. `READY_TO_APPLY` requires a valid source provenance plus a source-provided direct email or application/form URL.

### CV design system

The shared renderer (`utils/document_design.py`, `jobs-finder-editorial-medical`) produces CVs in a single ATS-readable column: A4 paper, 18 mm side margins, a strong sans-serif name, navy hierarchy, restrained teal accents, real section dividers, and readable 10.5 pt body text. Employer/date lines are emphasized separately from locations and responsibility bullets. DOCX uses the same installed font family, typography and selected spacing scale as PDF, semantic heading styles, keep-with-next/widow controls, and a real PAGE field aligned within the text area. Native PDFs and LibreOffice-rendered DOCX pages are both inspected; Microsoft Word and font substitution may still paginate differently. TXT remains a complete readable mirror.

Master and tailored CV experience is **newest first**, sorted on supplied dates without changing the canonical source order. Blank dates never imply current employment. Tailoring ranks competency groups and responsibility bullets and emphasizes relevant verified scope in the summary; it does not shuffle chronology or add facts. Generated summaries avoid repeating the detailed education, credentials, employer list and competency inventory below. Verified owner-written summaries are preserved verbatim.

There are no icons, sidebars, text boxes, hard-coded page breaks or content cut-offs. Long verified records can extend beyond two pages. If safe whitespace reduction removes a nearly empty trailing page, both CV formats receive that spacing scale; font sizes never shrink. If it does not help, the comfortable layout is restored. Cover-letter rendering and application-subject rules are unchanged by this CV remediation.

See [the integration validation](docs/cv_integration_validation.md) for the PR #25/#26 reconciliation, PDF and LibreOffice DOCX visual checks, CI and reproduction commands. The [initial rendering audit](docs/cv_rendering_audit.md) records the earlier baseline. Generated applicant files remain local and ignored by Git.

For local previews, run `python tools/render_previews.py --all`. Add `--verify-docx` with native LibreOffice installed to validate and rasterize both formats; `--pdf path/to/file.pdf` previews an existing file. This preserves PR #25's preview utility using the project's existing PDFium dependencies. The documented optional WASM Writer workflow works when native LibreOffice is unavailable. These are inspection tools, not alternate production renderers. Generated files stay ignored, and CI does not publish applicant documents as artifacts.

## Application package output

Generated files are written under `documents/applications/` and are ignored by Git because they may contain personal data.

Each package includes:

- tailored CV in TXT/DOCX/PDF
- tailored cover letter in TXT/DOCX/PDF
- complete package instructions in TXT/JSON
- application data checklist
- required documents checklist
- missing fact warnings
- official application route

## Eligibility and package review

Three separate states are tracked and never confused with each other:

- **Eligibility** (`READY_TO_APPLY` / `NEEDS_VERIFICATION` / `NOT_ELIGIBLE`): whether the vacancy's requirements are currently met by verified evidence. It does not mean a package has been prepared.
- **Package state** (`NOT_CREATED` / `IN_PROGRESS` / `READY_FOR_REVIEW` / `NEEDS_USER_INPUT` / `BLOCKED` / `FAILED`): whether a generated application package exists and still has unresolved blockers. A package is never reported ready when it actually needs user input, is blocked, or failed. The dashboard shows file-level `NOT CREATED` versus `READY FOR REVIEW`, never optimistic checkmarks.
- **Application progress** (`FOUND` / `REVIEWED` / `PACKAGE_READY` / `PACKAGE_NEEDS_INPUT` / `APPLIED_MANUALLY`): the simple progress shown in the Applications tab. `PACKAGE_READY` is only ever used when the package state is `READY_FOR_REVIEW`; otherwise `PACKAGE_NEEDS_INPUT` is used so the UI never claims a package is ready when it still needs your input.

## Safety rules

The matching and document systems use:

- `Met`
- `Not met`
- `Needs verification`

Vacancies classified `NOT_ELIGIBLE` do not receive an application package.

Vacancies classified `NEEDS_VERIFICATION` keep visible warnings in the package so the user can verify facts before applying.

`READY_TO_APPLY` is intentionally strict: it requires verified compatibility with every extracted critical requirement, including professional role/qualification, applicable education/license/experience, location, explicit gender/nationality/residency constraints, a non-expired closing date, direct application route, and a required email subject/reference. A missing deadline, route, source provenance, or critical requirement is `NEEDS_VERIFICATION`, never an assumption that it is safe to proceed. The word `subject` alone is not enough: it must occur in an email/application-subject instruction (English or Dari/Persian).

### Document evidence gate

Employer-facing generated documents (tailored CV and cover letter — TXT, and the DOCX/PDF renders of the same text) only print explicitly verified canonical-profile facts in factual sections: professional summary, experience, competencies, certifications/training, education, license/registration, Medical Exit Exam, languages, and vacancy-fit highlights. There is no hardcoded applicant description. Unverified profile items are never silently promoted into factual content — they are listed in the package's review warnings instead, so nothing is lost and nothing unconfirmed is claimed.

### Contact/identity rule

Contact and identity data (name, email, phone, location) are applicant facts, not a document fallback. An employer-facing document prints each only after its own explicit `personal.verification.<field>: true` confirmation. Missing, unverified, or placeholder name/email/phone values become `CONFIRM BEFORE SUBMISSION`; unverified location is omitted. The application package remains blocked until identity/contact review is complete. A CV preview never contributes contact data to runtime documents.

## Troubleshooting

### The dashboard does not open

Check whether port 8080 is already in use. You can set a different port:

```powershell
$env:JOBS_FINDER_PORT=8081
.\run_jobs_finder.bat
```

### Auditing a Windows database lifecycle

If a scan needs lifecycle diagnostics, opt in without logging vacancy contents:

```powershell
$env:JOBS_FINDER_DB_DIAGNOSTICS = "1"
.\.venv\Scripts\python.exe main.py find 2> db-trace.log
Remove-Item Env:JOBS_FINDER_DB_DIAGNOSTICS
```

Each `JOBS_FINDER_DB_TRACE` record contains only the process ID, thread ID,
connection identity, canonical SQLite path, query-only flag, WAL/locking mode,
schema version, transaction state, operation, and phase. The scan path uses one
`BEGIN IMMEDIATE` transaction for each discovery/match pair; dashboard reads use
query-only connections against an existing schema and do not run schema/WAL
writes.

### The scan says sources unavailable

This means the app could not reach active discovery sources from your network or environment. It does not mean there are no jobs. Try again later or open ACBAR/ReliefWeb manually.

### Python package installation fails

If installation fails, use Python 3.11 or 3.12, delete `.venv`, and rerun `run_jobs_finder.bat`.
