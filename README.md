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
cp profile.yaml.example profile.yaml
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

`profile.yaml` at the repository root is the **only** production applicant record. The CLI, dashboard, matching, recommendations, readiness checks, and document/package generation all resolve that one file through the same profile repository. `profile.yaml.example` is a schema/template only; it is never loaded as applicant data or used as a fallback.

Important rules:

- Leave missing facts blank or marked `Needs verification`.
- Every claim, including experience duration, location preference, and deployment preference, needs its own adjacent literal `verified: true` before it is verified evidence.
- Do not enter license numbers, issue dates, expiry dates, certificates, references, or document paths unless you personally confirm them.
- The database stores vacancies, scans, match outputs, and packages — never a second applicant profile.
- Resume extraction caches are not used. A CV is not runtime applicant evidence.

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

It writes TXT, DOCX, and PDF files under ignored `documents/master_cv/`. The Master CV contains no vacancy, employer, target-role, or application wording; it is a general presentation of the canonical profile. `prepare` is the separate downstream step that analyzes one vacancy and creates a vacancy-specific CV without modifying either `profile.yaml` or the Master CV.

Professional references may be stored as private local metadata, but they are not matching, employment, or credential evidence and are never printed in the Master CV or a vacancy-specific CV by default. When a vacancy asks for references, the package presents a generic manual checklist; the owner decides whether to release approved contact details.

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
- **Package state** (`NOT_CREATED` / `READY_FOR_REVIEW` / `NEEDS_USER_INPUT`): whether a generated application package still has unresolved blockers (e.g. missing contact info or unresolved evidence). A package is never reported ready when it actually needs user input.
- **Application progress** (`FOUND` / `REVIEWED` / `PACKAGE_READY` / `PACKAGE_NEEDS_INPUT` / `APPLIED_MANUALLY`): the simple progress shown in the Applications tab. `PACKAGE_READY` is only ever used when the package state is `READY_FOR_REVIEW`; otherwise `PACKAGE_NEEDS_INPUT` is used so the UI never claims a package is ready when it still needs your input.

## Safety rules

The matching and document systems use:

- `Met`
- `Not met`
- `Needs verification`

Vacancies classified `NOT_ELIGIBLE` do not receive an application package.

Vacancies classified `NEEDS_VERIFICATION` keep visible warnings in the package so the user can verify facts before applying.

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
