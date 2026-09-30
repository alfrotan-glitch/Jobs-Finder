# Production readiness + UX polish report — 2026-09-30

## Goal

Make Jobs-Finder usable as a daily Afghan job assistant for Dr. Frotan:

> Show me the Afghan jobs that matter to me, tell me when a new one appears, explain why it matches, and help me prepare the application.

No new source expansion was done in this phase. Work focused on scheduler reliability, UI clarity, recommendation quality, application-state trust, and end-to-end validation.

## UX changes

### Recommended is now the home workflow

Recommended now emphasizes actionable items only:

1. New `Ready to Apply` jobs
2. Active `Ready to Apply` jobs with approaching deadlines
3. New `Needs Verification` jobs
4. Materially updated matching jobs

It excludes `Not Eligible`, expired, closed, and unchanged non-actionable jobs.

Each recommended card now shows:

- job title and organization
- location
- deadline
- readiness label (`Ready to Apply`, `Needs Verification`)
- concise match reasons
- application route type
- tailored CV readiness
- cover-letter readiness
- primary action: `Prepare application →`

### Jobs page

Jobs now has simple user-facing filters:

- Recommended
- All active
- Ready to Apply
- Needs Verification
- Closing Soon
- New
- Updated

Expired/closed jobs are excluded from the default active view.

### Applications page

Applications now separates preparation from submission:

- `Prepared` / `Ready to Review` / `Opened` are not treated as submitted.
- `Submitted` only appears after the explicit confirmation endpoint records it.
- The generic status PATCH endpoint now rejects `submitted` / `applied`; users must use the explicit confirmation flow.
- Rows show vacancy, employer, location, deadline, application route, document readiness, and submission state.

### My Profile

Added a confidence-building profile summary showing:

- Medical Doctor
- health/nutrition/program experience
- Afghanistan experience
- license/registration status
- languages
- key skills

It distinguishes `Verified` vs `Needs Verification` and keeps raw YAML/internal structure out of the normal UI.

### Settings

Settings now exposes simple controls for:

- watcher enabled/disabled
- scan interval
- deadline alert thresholds
- automatic application-package preparation
- application package output folder
- internal notification preferences

Settings are sanitized on save: invalid intervals are made safe, comma-separated deadline thresholds are normalized, and notification defaults are filled.

### Advanced / System

Technical information was moved/kept under Advanced/System:

- scheduler status and next run times
- scan audits
- notification log
- source registry summary and validation errors
- source failures/errors

Normal workflow screens avoid internal terms such as fingerprints, canonical keys, RawVacancy, NormalizedVacancy, adapters, or registry methods.

## Scheduler verification result

Validated with `docs/production_readiness_validation_2026-09-30.json`.

Evidence demonstrated:

- scheduler starts when configured
- configured interval is installed on the scheduler job
- duplicate setup does not create duplicate jobs
- scheduler executes a due watch scan
- persistent watcher state survives the scheduled scan
- notifications are generated/deduplicated
- scheduler remains running after a scan
- scheduler can shut down cleanly
- disabled scheduler removes scheduled jobs
- scheduled and manual watch use the same `run_job_watch_scan()` watcher path
- scan failures are caught and do not kill the scheduler

Additional regression coverage is in `tests/test_scheduler_lifecycle.py`.

## End-to-end workflow result

Validated with the current FMIC `Medical Officer` vacancy:

- source URL: `https://www.fmic.org.af/WorkWithUs/vacancies/Pages/Medical-Officer-2026.aspx`
- application route: Google Form from official FMIC detail page
- deadline: `2026-10-05`
- readiness: `READY_TO_APPLY`

Workflow executed:

```text
Discover → Persist → Match → Recommended → Explain match → Prepare tailored CV → Prepare cover letter → Generate review package → Open-route readiness → STOP before submission
```

Generated application package paths are recorded in `docs/production_readiness_validation_2026-09-30.json`. The tracker status remains `prepared`; no submitted/applied timestamp was created.

## Real smoke-test result

Smoke validation used currently validated active sources/vacancies:

- FMIC — `Medical Officer`
- AKHS-A — `Surgeon`
- IOM — `Supply Chain Assistant`

Arena `fetch_page` revalidated:

- FMIC `Medical Officer` detail page is live and includes AMC registration, clinical experience requirement, deadline, and Google Form route.
- AKHS-A `Surgeon` detail page is live and includes Specialist Surgeon requirement and closing date.

Smoke-test evidence:

- at least one real vacancy discovered
- at least one `READY_TO_APPLY` result
- at least one `NEEDS_VERIFICATION` result
- Recommended contained only actionable readiness states
- repeat scan produced no duplicate new notifications
- deadline displayed correctly
- tailored CV / cover letter / application package generated
- no application submitted
- scheduler lifecycle verified

`smoke_test_passed: true` in `docs/production_readiness_validation_2026-09-30.json`.

## Reliability fixes

- Scheduler disabled state now removes old jobs and stops the scheduler instead of leaving stale jobs installed.
- Scheduler settings are validated/coerced to safe values.
- Duplicate scheduler setup is prevented by removing/replacing known job IDs.
- Scheduler scan failures are caught and stored in status instead of killing the app.
- Watcher state now stores `last_change_type` for clearer New/Updated filtering.
- Recommended API now prefers watcher-backed actionable jobs.
- Recommended excludes expired/closed/not-eligible jobs.
- Existing prepared/review/opened/submitted application states are no longer overwritten by later scans/matches.
- API-level application status integrity now blocks direct `submitted`/`applied` updates without explicit confirmation.
- Source registry status and scan diagnostics are available under Advanced/System.

## Files changed in this pass

- `scheduler.py`
- `utils/job_watcher.py`
- `utils/tracker.py`
- `dashboard/server.py`
- `dashboard/static/app.js`
- `dashboard/static/style.css`
- `dashboard/templates/index.html`
- `profile.yaml.example`
- `README.md`
- `tests/test_scheduler_lifecycle.py`
- `tests/test_recommended_ux.py`
- `tests/test_job_watcher.py`
- `docs/production_readiness_validation_2026-09-30.json`
- `docs/production_readiness_report_2026-09-30.md`
- `docs/job_watcher_report_2026-09-30.md`
- `docs/source_registry_validation_2026-09-30.json`

## Complete test result

```text
.venv/bin/python -m pytest -q
249 passed, 1 skipped, 1 warning in 26.80s
```

The warning is a third-party FastAPI/Starlette `TestClient` deprecation warning and does not indicate an application failure.

## Remaining limitations

- Internal notifications are implemented; external email/SMS/WhatsApp notification delivery remains out of scope for this phase.
- Live Python/httpx access to some external HTTPS sites can still fail with TLS EOF in this sandbox, but failures are isolated and recorded.
- Some older discovery adapters provide coarse source audit labels; registry static and Oracle HCM sources provide better source-level diagnostics.
- The UI has been polished without a full redesign; future work could add richer accessibility testing and browser visual regression tests.
- Automatic application-package preparation remains disabled by default to avoid unexpected file generation.
