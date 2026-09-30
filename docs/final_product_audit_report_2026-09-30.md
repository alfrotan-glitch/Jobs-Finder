# Final Product Audit — Jobs-Finder

Date: 2026-09-30  
Audience: Dr. Allah Yar Frotan daily Afghanistan job search workflow

## PRODUCT STATUS

**READY_WITH_MINOR_LIMITATIONS**

Jobs-Finder is now a coherent, reliable, and usable product for Dr. Frotan’s normal daily Afghan job search, provided it is used as designed: **review-first, Afghanistan-first, health/medical-sector-first, and manual-submission-only**.

The audit found and fixed concrete defects that could affect daily use. After those fixes, the full regression suite and final audit smoke validation pass.

## Verified

### Product lifecycle

Verified the lifecycle from:

`Source Registry → Discovery → Normalize → Deduplicate → Freshness → Match → Recommended → Job Detail → Prepare Application → Review → Open/verify Application Route → User Submission → Track Application`

Key verified behaviors:

- Source records keep provenance and original URLs.
- Deduplication merges duplicate signals into one canonical vacancy while retaining known source URLs.
- Freshness/deadline logic removes expired vacancies from actionable views.
- Matching separates `READY_TO_APPLY`, `NEEDS_VERIFICATION`, and `NOT_ELIGIBLE`.
- Recommended focuses on actionable health/medical jobs instead of all discovered jobs.
- Preparing documents moves a job to `prepared`, not `submitted`.
- Later scans do not overwrite a prepared application back to a generic matched/discovered state.
- Submission state requires explicit confirmation and records no submission timestamp unless confirmed.

### Discovery and source registry

Final validation artifact: `docs/final_product_audit_validation_2026-09-30.json`

- Source registry records: **36**
- Registry validation issues: **0**
- Sources currently marked `ACTIVE`: **11**
  - `acbar`
  - `unjobs_afghanistan`
  - `unicef_careers`
  - `iom_recruit`
  - `dacaar_jobs`
  - `nrc_careers`
  - `akdn_careers`
  - `moph_vacancies`
  - `ku_vacancies`
  - `fmic`
  - `afghan_wireless`
- Sources enabled for autonomous discovery: **15**
- Blocked/inaccessible/limited sources remain recorded as such rather than being force-enabled.
- Simulated source failure completed safely and did **not** close existing jobs.

### Matching against Dr. Frotan profile facts

Verified matching remains conservative:

- Owner-confirmed Medical Exit Exam and valid medical professional registration are treated as verified.
- No license/registration number, certificate number, issue date, expiry date, or reference is invented.
- Specific requested numbers/documents remain `NEEDS_VERIFICATION` / user input.
- Female-only requirements are handled as hard requirements; female-preference wording is distinct in tests.
- Patient registration is not treated as professional medical registration.
- Health/public-health education is not incorrectly rejected.
- Surgeon/surgical roles are now treated as medical relevance signals.

### Application documents

Inspected generated packages for different real-world vacancy types:

- FMIC **Medical Officer** package:
  - Correct title/employer/deadline/application route retained.
  - Tailored to medical officer, infection control, patient safety, clinical/hospital experience.
  - Status remains `prepared`.
  - No submission timestamp.
  - No invented sensitive identifiers.
- AKHS-A **Surgeon** package:
  - Correctly remains `NEEDS_VERIFICATION` because specialist/surgeon qualification evidence is not invented.
  - Package now surfaces verification warnings before submission.
  - No invented specialist credential.
- Existing real-vacancy validation script also generated review packages for five representative Afghanistan health vacancies and blocked submission without explicit confirmation.

### Watcher/scheduler and persistent state

Verified with direct SQLite inspection in the final audit validation:

- Duplicate application groups: **0**
- Orphan watcher rows: **0**
- Invalid statuses: **0**
- Submitted/applied rows in audit smoke DB: **0**
- Submitted without timestamp: **0**
- Missing watcher provenance rows: **0**
- Notifications pointing to deleted jobs: **0**
- Expired actionable rows: **0**
- Impossible watcher timestamps: **0**

### UI/API safety

Verified safety negative cases:

- Tracker transition to `submitted` without explicit confirmation: **blocked**
- Generic API status patch to `submitted`: **HTTP 400**
- Legacy assisted apply endpoint with wrong confirmation: **HTTP 400**
- Autonomous/YOLO mode remains disabled with HTTP 410.
- Review packages explicitly state no application was submitted.

## Fixed during audit

1. **Non-health `NEEDS_VERIFICATION` jobs could appear as actionable/recommended.**
   - Example: a generic IOM Supply Chain Assistant could be classified as `NEEDS_VERIFICATION` and surfaced to the user despite no clear medical/health relevance.
   - Fixed by making non-medical/non-health vacancies `LOW` operational priority unless they are truly `READY_TO_APPLY`, and excluding `LOW`/`CLOSED` watcher jobs from Recommended/actionable views.
   - Regression test added.

2. **Application packages did not surface unmet/unverified requirements clearly enough.**
   - Example: a Surgeon package could be prepared while the specialist qualification remained `NEEDS_VERIFICATION`, but the package text did not make that blocker visible.
   - Fixed by adding review warnings, missing items, and user actions for `NEEDS_VERIFICATION` / `NOT_MET` requirements in generated application packages.
   - Regression test added.

3. **Surgeon/surgical vacancies were not consistently recognized as medical relevance.**
   - Fixed by adding surgeon/surgery/surgical terms to medical relevance detection.
   - Regression test added.

## Remaining limitations

These are normal operational limits, not blockers to daily use:

- External job sites can change layout, go offline, require login, block TLS, or add CAPTCHA/MFA. Jobs-Finder records such failures and does not bypass security controls.
- Some registry sources are intentionally `LIMITED`, `BLOCKED`, `INACCESSIBLE`, or `NOT_IMPLEMENTED`; they should not be treated as working until independently validated.
- The app prepares and tracks applications but does **not** submit them automatically. Dr. Frotan must review all documents and submit manually on the employer route.
- Private profile/CV files are intentionally not committed to the repository; local daily use requires the real profile/CV data to be present in the workspace/runtime environment.
- Legacy disabled autonomous code remains behind a hard HTTP 410 guard; it is not user-facing and cannot run through the API, but it is still a future cleanup candidate.

## Test result exact counts

Commands run during final audit:

- `.venv/bin/python -m pytest -q`  
  **252 passed, 1 skipped, 1 warning in 26.74s**
- `PYTHONPATH=. .venv/bin/python scripts/final_product_audit_validation.py`  
  **smoke_test_passed=True**
- `PYTHONPATH=. .venv/bin/python scripts/validate_real_vacancies.py`  
  **completed successfully**, generated machine-readable and Markdown evidence under `documents/real_vacancy_validation/`
- `git ls-files '*.py' | xargs .venv/bin/python -m py_compile`  
  **passed with no output**
- `node --check dashboard/static/app.js`  
  **passed with no output**

Known warning:

- One `StarletteDeprecationWarning` from `fastapi.testclient` / `httpx`; it does not indicate a product failure.

## Real-world validation exact scenarios

From `docs/final_product_audit_validation_2026-09-30.json`:

1. **READY_TO_APPLY**
   - FMIC Medical Officer
   - Readiness: `READY_TO_APPLY`
   - Operational priority: `READY`
   - Closing date: `2026-10-05`
   - Application route retained: Google Form URL

2. **NEEDS_VERIFICATION**
   - AKHS-A Surgeon
   - Readiness: `NEEDS_VERIFICATION`
   - Operational priority: `VERIFY`
   - Reason: specialist/surgeon qualification must be verified; not invented.

3. **NOT_ELIGIBLE**
   - Relief International Female Medical Doctor
   - Readiness: `NOT_ELIGIBLE`
   - Reason: hard female-only requirement conflicts with profile gender.

4. **Non-health noise exclusion**
   - IOM Supply Chain Assistant
   - Readiness: `NEEDS_VERIFICATION`
   - Operational priority: `LOW`
   - Excluded from Recommended/actionable views.

5. **Duplicate merge**
   - Initial scan: **6 discovered**, **5 deduplicated**
   - FMIC duplicate signal merged into the canonical vacancy.
   - Canonical vacancy retained multiple source/application URLs.

6. **Repeat unchanged scan**
   - Repeat scan: **5 unchanged**, **0 updated**, **0 new**

7. **Material update**
   - FMIC description update detected.
   - Update scan: **1 updated**, changed field: `description`
   - Prepared application status preserved.

8. **Expired/closed vacancy**
   - Expired Health NGO Medical Officer
   - Closing date: `2026-09-20`
   - Current status: `EXPIRED`
   - Operational priority: `CLOSED`
   - Removed from actionable list.

9. **Source failure isolation**
   - Simulated source failure: `blocked_source_fixture`
   - Scan status: `COMPLETED`
   - Discovered count: `0`
   - Existing FMIC vacancy stayed `ACTIVE`.

10. **Safe final workflow**
    - FMIC package generated.
    - Tracker status after package: `prepared`
    - Final status after later scans: `prepared`
    - `submitted_at`: `null`
    - `no_submission_timestamp`: `true`
    - Package flag `no_submission_performed`: `true`

11. **Safety negative cases**
    - Submitted transition without confirmation: blocked.
    - API status patch to submitted: HTTP 400.
    - Assisted apply with wrong confirmation: HTTP 400.

## Files changed during this final audit

Audit-specific source/test/artifact changes:

- `utils/job_watcher.py`
- `utils/tracker.py`
- `utils/documents.py`
- `utils/medical_requirements.py`
- `tests/test_recommended_ux.py`
- `tests/test_cv_documents_tracker.py`
- `tests/test_medical_requirements.py`
- `scripts/final_product_audit_validation.py`
- `docs/final_product_audit_validation_2026-09-30.json`
- `docs/final_product_audit_report_2026-09-30.md`

Note: the working tree also contains broader uncommitted source-registry/discovery/watcher/production-readiness work from earlier phases of the same session.

## Recommended next action

Use Jobs-Finder for normal daily operation:

1. Keep Dr. Frotan’s real private profile/CV available locally.
2. Run discovery/watcher scans daily.
3. Start from **Recommended**.
4. Review each job detail and generated package.
5. Open the employer application route manually.
6. Submit only after Dr. Frotan explicitly confirms the final application content.

No new development phase is required before normal daily use.
