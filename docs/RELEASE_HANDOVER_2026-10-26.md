# Jobs-Finder — Final release-candidate handover (26 October 2026)

**Branch:** `main` — `alfrotan-glitch/Jobs-Finder`  
**Release decision:** **WINDOWS ACCEPTANCE PENDING / DO NOT CLAIM PRODUCTION APPROVAL**.

## What has been built and covered by automated tests

- The owner's official CV is accepted as the verified source: five work roles,
  24 owner-approved responsibilities, education, training, languages, medical
  registration, clinical and humanitarian experience, and professional skills.
  No duplicate reapproval of the attested original is needed.
- Owner-facing editable profile: add, edit or confirm new facts in My Profile;
  the same canonical record feeds job matching, CVs and letters.
- Tailored evidence-based CV and cover letter: TXT, searchable PDF and editable
  DOCX, ATS-friendly single column, executive or clinical styling. Role
  relevance determines presentation order without fabricated outcomes.
- Clear official application-route handling and concise email subject/body,
  exact requested PDF attachments, and **unsent** EML output. Applications
  are never sent automatically.
- Local SQLite archive export and checksum verification, preserving original
  data and generated documents. A **separate**, private referee-contact
  JSON export/import covers data excluded from the main ZIP.
- `Check_Jobs_Finder_Readiness.bat`: read-only local profile/Python/SQLite
  and synthetic DOCX/PDF smoke checks; reports status in ignored
  `generated/release_readiness.json`. This never scans vacancies or sends mail.

## Latest-commit automated release gate

The authoritative release evidence is the **latest** GitHub Actions run of
`.github/workflows/tests.yml` on `main`. All six jobs must succeed:
Python 3.11/3.12 on Windows/Linux plus Word and PDF rendering. Frontend
JavaScript tests and official-profile/no-fabrication/privacy tests run in CI.
Historical successful jobs do not substitute for the latest commit's status.

## Mandatory outstanding customer-acceptance gates

| Gate | Status / next evidence |
|---|---|
| GitHub repository privacy | **HOLD** — public at final audit; owner must change it to Private and review historical personal data exposure |
| Actual installation on the owner's Windows machine | **UNVERIFIED** — open real browser UI, edit/save/restart, verify data persistence |
| Three target applications | **UNVERIFIED IN LIVE UI** — inspect Provincial Coordinator, TFU Doctor, Health & Nutrition Supervisor document/EML packages |
| Local unsent email-client integration | **UNVERIFIED** — open EML with correct recipient, subject and exact PDF attachments, without sending |
| Local database backup/restore | **UNVERIFIED** — export and verify ZIP; perform restoration to a separate Windows folder |
| Referee backup | **CODE TESTED**, physical backup pending — export separate plaintext JSON, keep privately on second drive, test reimport |
| Current official vacancy sources | **UNVERIFIED LIVE** — ACBAR and ReliefWeb may be partial/unavailable |

## Safe Windows handover

1. Close the app. In the original Desktop checkout run
   `git status --short`. If tracked data such as `profile.yaml` changed,
   **do not reset or overwrite it**; back up and reconcile first.
2. Only when the working tree is clean, run `git pull --ff-only origin main`.
3. Launch `run_jobs_finder.bat`, then double-click
   `Check_Jobs_Finder_Readiness.bat`. Resolve BLOCK items.
4. Visually inspect fresh Word/PDF and unsent email drafts. Confirm the
   approved facts remain intact and no private referee PII appears.
5. Export verified data ZIP and the separately downloaded confidential
   JSON of private references onto a trusted second local drive.
6. Authorize customer/live use only after **all** applicable local and
   privacy gates have real evidence.

**No artificial achievements, fabricated credentials, silent submissions,
unstated availability claims, or perfection claims are allowed.**
