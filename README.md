# Jobs-Finder

Jobs-Finder is a lightweight Windows-first assistant for Afghanistan job search and application preparation.

It helps one user answer:

> Which Afghanistan vacancies are relevant to my verified CV/profile, why do they fit, and what application package should I review before applying?

## What it does

1. Finds Afghanistan-relevant vacancies from maintained sources.
2. Normalizes and deduplicates vacancies.
3. Extracts practical requirements: education, license/registration, experience, languages, location, deadline, documents, application URL/email, subject/reference.
4. Compares the vacancy against the verified profile/CV evidence.
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

Jobs-Finder is not an ATS, recruiter bot, form-submission bot, email monitor, interview platform, or generic global job-board aggregator.

It does **not**:

- submit applications automatically
- bypass CAPTCHA, login, MFA, or employer security controls
- invent experience, license numbers, documents, dates, achievements, references, or skills
- silently run continuous scans when the dashboard starts
- monitor email or perform follow-up automation

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

Python support is intentionally conservative. The code was validated in this (Linux) development environment on Python 3.11. The dependency set is lightweight. `run_jobs_finder.bat` itself has not been executed on an actual Windows machine as part of this validation (this development environment has no Windows host) -- its logic has only been reviewed, not run end-to-end on Windows. If installation fails on another Python version, use Python 3.11 or 3.12 and rerun the launcher.

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

This has been run and verified on Linux. It has not been executed on Windows
in this repository's development; the Windows one-click start script is
reviewed for correctness but is not a substitute for actually running it on
a Windows machine.

## Profile/CV setup

`profile.yaml` is the source of truth. Copy `profile.yaml.example` and edit only verified facts.

Important rules:

- Leave missing facts blank or marked `Needs verification`.
- Do not enter license numbers, issue dates, expiry dates, certificates, references, or experience years unless verified.
- Optional CV/PDF text can support evidence, but it must not silently replace profile facts.

You can build a draft profile from a CV for review:

```bash
python main.py import-cv path/to/cv.pdf --profile profile.yaml
```

Then manually review `profile.yaml` before scanning or preparing documents.

## Find jobs

CLI:

```bash
python main.py find
python main.py recommended
python main.py jobs
```

Dashboard:

1. Open the app.
2. Optionally use **My Profile → Import a CV** to generate a draft profile, then review each field under **Verification review** and press **Mark verified** only for facts you personally confirm. Nothing from a CV import is ever shown as verified until you explicitly confirm it.
3. Press **Find Jobs**.
4. Review **Recommended**.
5. Select a vacancy and press **Prepare package**.
6. Review the generated files.
7. Open the official route and apply manually.

The **Settings** tab shows the current, non-editable system configuration (active sources, ACBAR scan budget, and the fact that background scanning and automatic submission are both disabled) -- it has no fake controls.

## Source status semantics

Jobs-Finder distinguishes market results from technical failures:

- `SCAN_COMPLETE` — reachable sources returned relevant jobs.
- `NO_RELEVANT_JOBS_FOUND` — reachable sources were scanned and no relevant current roles were found.
- `PARTIAL_SCAN` — at least one source worked and at least one source failed.
- `SOURCES_UNAVAILABLE` — all active sources were unreachable.
- `SCAN_FAILED` — no active source configuration was available.

A result of zero jobs is never used to claim the Afghanistan market is empty when sources were unreachable.

## Active sources

Maintained active sources are intentionally few:

- **Tier A: ACBAR Jobs** — core Afghanistan NGO/INGO job board. Each scan walks listing pages with bounded, documented pagination (`job_sources.acbar.max_pages`, default 6) and stops automatically once a page returns no new vacancies; detail pages are fetched with a bounded concurrency limit (`max_detail_concurrency`, default 5) and a per-request timeout. This is a deliberate performance/safety budget, not a claim that the entire ACBAR archive is scanned on every run. See `profile.yaml.example` to adjust it.
- **Tier B: ReliefWeb Afghanistan jobs** — secondary humanitarian source filtered for health/medical/public-health terms.

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

Employer-facing generated documents (tailored CV and cover letter — TXT, and the DOCX/PDF renders of the same text) only print explicitly verified facts in factual sections: professional summary, experience, competencies, certifications/training, education, license/registration, Medical Exit Exam, languages, and vacancy-fit highlights. There is no hardcoded applicant description. Unverified profile/CV items are never silently promoted into factual content — they are listed in the package's review warnings instead, so nothing is lost and nothing unconfirmed is claimed.

### Contact/identity rule

Contact data (name, email, phone, location) from `profile.personal` is display data for the applicant's own application: it is printed in generated documents even while still a draft (for example right after a CV import), so the user can review it in place and legitimate contact data is never suppressed or invented. Display never implies verification — contact/identity facts only become verified evidence for matching via an explicit `personal.verified: true`. Known placeholder values are replaced with `CONFIRM BEFORE SUBMISSION`, and while `personal.verified` is not `true`, the application package keeps a visible "confirm identity/contact" blocker.

## Troubleshooting

### The dashboard does not open

Check whether port 8080 is already in use. You can set a different port:

```powershell
$env:JOBS_FINDER_PORT=8081
.\run_jobs_finder.bat
```

### The scan says sources unavailable

This means the app could not reach active live sources from your network/environment. It does not mean there are no jobs. Try again later or open ACBAR/ReliefWeb manually.

### Python package installation fails

If installation fails, use Python 3.11 or 3.12, delete `.venv`, and rerun `run_jobs_finder.bat`.
