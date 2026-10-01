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

Python support is intentionally conservative. The code was validated in this environment on Python 3.11. The dependency set is lightweight and avoids JobSpy/NumPy/Playwright, but Python 3.13 could not be executed in this Linux sandbox; if a package installer fails on Python 3.13, install Python 3.12 or 3.11 alongside it and rerun the launcher.

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
2. Press **Find Jobs**.
3. Review **Recommended**.
4. Select a vacancy and press **Prepare package**.
5. Review the generated files.
6. Open the official route and apply manually.

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

- **Tier A: ACBAR Jobs** — core Afghanistan NGO/INGO job board.
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

## Safety rules

The matching and document systems use:

- `Met`
- `Not met`
- `Needs verification`

Vacancies classified `NOT_ELIGIBLE` do not receive an application package.

Vacancies classified `NEEDS_VERIFICATION` keep visible warnings in the package so the user can verify facts before applying.

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

This final product removed JobSpy, NumPy, Playwright, Stagehand, APScheduler, and email-monitoring dependencies. If installation still fails on Python 3.13, install Python 3.12 or 3.11 alongside it, delete `.venv`, and rerun `run_jobs_finder.bat`.
