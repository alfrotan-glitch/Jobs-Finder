# Afghan MD Job Assistant

A local, review-first job-search assistant for a medical doctor looking for medical and public-health vacancies in Afghanistan.

The workflow is:

**Find → Understand → Match → Prepare → Review → Apply → Track**

It is intentionally not a generic job-search dashboard. It focuses on Afghan medical roles such as MD, MBBS, physician, medical officer, health officer, public health, PHC, BPHS/EPHS, HMIS, IMNCI, IMAM, nutrition, SRHR, IPC, and humanitarian/NGO health work.

## Safety rules

- AI is optional. Discovery, requirement extraction, eligibility matching, and draft documents work without AI.
- The profile and CV are the only sources for applicant facts.
- Missing evidence is shown as **Needs verification**, not as a fabricated claim.
- The app never invents qualifications, licenses, languages, locations, achievements, or experience.
- It never bypasses CAPTCHA, login, MFA, or site security.
- It never submits an application without explicit user confirmation.
- Default behavior is review-first: prepare drafts, open the real application page, and stop before final submission.

## What it does

1. Finds Afghanistan-first medical vacancies from high-value sources.
2. Deduplicates jobs and keeps the original source URL and application URL.
3. Extracts deterministic requirements from each vacancy:
   - MD / MBBS / physician / medical officer
   - license or registration
   - required clinical years
   - Afghanistan health-sector experience
   - BPHS / EPHS / PHC / HMIS / IMNCI / IMAM / nutrition / SRHR / IPC
   - NGO or humanitarian experience
   - reporting, supervision, management
   - English / Dari / Pashto
   - province, district, Kabul, field deployment
   - gender, nationality, and residency requirements
   - reference number, application email, application URL, required subject, closing date
4. Compares each requirement against verified profile/CV evidence.
5. Shows a table: **Required → Met / Not met / Needs verification**.
6. Prioritizes jobs as “Review first”, “Review soon”, “Needs verification”, “Low priority”, or “Closed” without pretending to predict hiring probability.
7. Generates a tailored CV draft and cover letter draft for review.
8. Opens the real application page and can assist with safe form filling.
9. Stops before final submission unless the user explicitly confirms.
10. Tracks prepared, opened, submitted, interviewing, offer, rejected, withdrawn, and archived applications.

## Install

### Requirements

- Python 3.11+
- Playwright browser binaries if you want browser-assisted form filling

### Local setup

```bash
git clone https://github.com/alfrotan-glitch/Jobs-Finder.git
cd Jobs-Finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp profile.yaml.example profile.yaml
```

If you have a text export or PDF of Dr. Frotan's CV, you can create the structured profile directly:

```bash
python main.py import-cv profiles/dr_allah_yar_frotan_source_cv.txt
```

To export the professional master CV after profile review:

```bash
python main.py create-master-cv --profile profiles/dr_allah_yar_frotan_profile.yaml --out-dir documents
```

Edit `profile.yaml` with your verified facts, especially:

- personal information
- medical education
- license/registration
- clinical experience years
- work history with dates
- skills and certificates
- languages
- location and preferred locations
- CV path

Then start the web app:

```bash
python main.py server --port 8080
```

Open <http://localhost:8080>.

## CLI usage

```bash
# Find and analyze Afghan medical jobs
python main.py discover

# Show jobs to look at today
python main.py recommended

# Generate tailored CV and cover letter drafts for a job
python main.py prepare JOB_ID

# Open the real application page
python main.py open JOB_ID

# Review-only form assistance; stops before submit
python main.py fill JOB_ID

# Allow final submit only after typed confirmation
python main.py fill JOB_ID --live

# Record a manually submitted application
python main.py mark-submitted JOB_ID

# View tracking statistics
python main.py stats
```

## Web navigation

The main navigation is simple:

- **Recommended** — answers “Which jobs should I look at today?”
- **Jobs** — all discovered jobs
- **Applications** — prepared/opened/submitted applications and follow-up states
- **My Profile** — verified applicant facts and CV evidence
- **Settings** — sources, optional AI, and safety settings

## Sources

Enabled by default:

- ACBAR / Afghan NGO job listings
- ReliefWeb Afghanistan health/humanitarian jobs
- User-configured official organization career pages
- User-configured ATS boards such as Greenhouse and Lever

Generic job boards are opt-in because they are often noisy and less relevant for Afghanistan medical roles.

## Optional AI

AI can be enabled in `profile.yaml`, but it is not required for basic operation.

```yaml
ai:
  enabled: false
  enable_document_refinement: false
```

When enabled, AI may help refine wording or analyze unusual forms. It must not add facts that are missing from the verified profile/CV.

## Data and provenance

The app stores tracking data in `applications.db` (SQLite). For each job it keeps:

- original source URL
- application URL or email
- extracted requirements
- deterministic match report
- evidence snippets from the vacancy and profile/CV
- generated draft documents
- application status and follow-up dates

This lets the user answer: **“Where did this information come from?”**

## Tests

Run:

```bash
python -m pytest
```

The tests cover CV parsing, deterministic requirement extraction, MD matching, missing evidence, experience requirements, duplicate jobs, closing dates, source failures, invalid application URLs, tailored documents, and application state transitions.

To replay the product validation against the real ACBAR Afghanistan vacancies captured during review, run:

```bash
python scripts/validate_real_vacancies.py
```

It writes a Markdown/JSON validation report and vacancy-specific tailored CV/cover-letter drafts under `documents/real_vacancy_validation/`. The validation checks source URL preservation, application destination preservation, requirement extraction, evidence-based `Met / Not met / Needs verification`, document generation, safe open tracking, and the guard that blocks submission without explicit confirmation.

Real public ATS form tests are skipped by default because they require network access and installed Playwright browsers. Run them with `RUN_REAL_FORMS=1 python -m pytest tests/test_real_forms.py` after `python -m playwright install chromium`.
