# Continuous Afghan Job Watcher implementation report — 2026-09-30

## Summary

Implemented a persistent, restart-safe Afghan Job Watcher around the existing source registry and discovery orchestrator. The watcher does not create a second discovery engine: scheduled/manual scans call the existing `discover_all_jobs()` pipeline, then persist canonical job state, detect material changes, run the deterministic matcher, create internal notifications, monitor deadlines, and record a scan audit.

Pipeline now supported:

```text
Source Registry → Scheduled Scan → Detect New/Changed Jobs → Normalize → Deduplicate → Expire Closed Jobs → Match Dr. Frotan → Prioritize → Notify → Prepare Application
```

No application submission is performed by the watcher.

## Persistent-state design

Persistent state is stored in the existing SQLite tracker database (`applications.db` by default), alongside the existing application tracker tables.

New watcher tables:

- `job_watch_vacancies`
  - canonical job ID
  - discovery job ID
  - title, organization, location
  - source URLs and source provenance
  - first discovered timestamp
  - last seen timestamp
  - last changed timestamp
  - posting date and closing date
  - current status / previous status
  - content fingerprint
  - requirements fingerprint
  - application route
  - last deterministic matching result
  - last notification timestamp
  - notification state
  - operational priority and explainable priority reasons
  - description and metadata snapshot
- `job_watch_notifications`
  - internal notification/event records with durable dedupe keys
- `job_watch_scans`
  - per-scan audit records with source attempts, failures, counts, and errors

Canonical IDs are derived from the existing deduplication candidate keys (`vacancy_keys()`), so the same vacancy is not duplicated on every scan and cross-source duplicates collapse to one canonical watcher vacancy.

## Change-detection behavior

The watcher distinguishes:

- `NEW`: canonical vacancy has never been persisted.
- `UPDATED`: known vacancy has a material change.
- `UNCHANGED`: known vacancy was seen again with the same material fingerprint.
- `CLOSED` / `EXPIRED`: source marks it closed or the parsed closing date has passed.

Material fields include:

- title
- organization
- location
- posting date
- closing date
- application route
- normalized description text
- requirements fingerprint

Source URL/provenance additions are merged and preserved but do not by themselves force a noisy material-update alert.

Temporary source failure or empty results never delete or close existing vacancies. Vacancies are expired by closing date or explicit closed status only.

## Matching and operational priority

The watcher reuses `utils.medical_matcher.match_job_against_profile()` and stores the existing deterministic `readiness_status`:

- `READY_TO_APPLY`
- `NEEDS_VERIFICATION`
- `NOT_ELIGIBLE`

Operational priority is deterministic and explainable. It is based on readiness, health/medical relevance, application route availability, deadline proximity, source reliability, and vacancy status. No AI score or black-box ranking was introduced.

Priority labels used internally include:

- `APPLY_TODAY`
- `APPLY_SOON`
- `READY`
- `VERIFY`
- `LOW`
- `CLOSED`

Each watcher vacancy stores the reason list used for the priority.

## Notification behavior

Internal durable notification events are now supported for:

- new `READY_TO_APPLY` job
- new `NEEDS_VERIFICATION` job
- deadline approaching
- material vacancy update
- vacancy closed/expired
- source failure
- optional application package prepared

Each event has a stable dedupe key. Re-running the same scan does not re-notify unchanged jobs or repeat the same deadline/source/update notification.

## Deadline behavior

Deadline thresholds are configurable, defaulting to:

```yaml
watcher:
  deadline_alert_days: [7, 3, 1]
```

The watcher issues only the most relevant threshold notification for the current date and records it durably. Expired vacancies are not shown as active/actionable.

## Scheduler design

`scheduler.py` now schedules the Afghan Job Watcher instead of a simple non-persistent discovery loop.

Effective config comes from `profile.yaml`:

```yaml
watcher:
  enabled: true
  scan_interval_hours: 6
  deadline_alert_days: [7, 3, 1]
  auto_prepare_ready_to_apply: false

schedule:
  job_watch_interval_hours: 6
  score_interval_minutes: 60
```

The scheduler keeps the old `discover` job ID for dashboard compatibility, but the job now runs `scheduled_job_watch_scan()`. Manual scans are available via CLI and API.

## Existing application workflow integration

The watcher writes canonical jobs into the existing `applications` tracker table and stores deterministic match results with `log_medical_match()`.

READY_TO_APPLY jobs can enter the existing review-first workflow through `prepare_application_for_watcher_job()`, which reuses:

- tailored CV generation
- cover-letter generation
- complete application package generation
- tracker document storage
- explicit confirmation gate for later submission

No application is submitted automatically. CAPTCHA, MFA, login, and site security are not bypassed.

## UI changes

The main UI stays simple:

- `Recommended`: shows new/actionable matching opportunities and readiness badges.
- `Jobs`: shows active discovered jobs.
- `Applications`: existing application tracking.
- `My Profile`: verified profile facts.
- `Settings`: scan frequency, deadline alert thresholds, and watcher preferences.
- `Advanced / System`: scan audits, adapter/source warnings, and notification diagnostics.

Technical source status and scan logs are kept out of the primary workflow.

## Real validation

Detailed validation is saved at `docs/job_watcher_validation_2026-09-30.json`.

Validation used currently verified Afghanistan vacancies from active/high-value sources:

- FMIC — `Medical Officer`
- AKHS-A — `Surgeon`
- IOM — `Supply Chain Assistant`
- NRC — `Humanitarian Access & Safety Manager Afghanistan`
- Relief International via Wazifaha — `Quality of Care and Capacity Building Officer`

Demonstrated successfully:

1. genuinely new vacancies
2. unchanged vacancy on repeat scan
3. duplicate across sources collapsed to one canonical job
4. changed field detection (`closing_date` and description)
5. closed/expired vacancy handling
6. `READY_TO_APPLY` match
7. `NEEDS_VERIFICATION` match
8. source failure that did not break the scan or remove successful results
9. application package generation with `no_submission_performed: true`

## Test result

Full suite after implementation:

```text
.venv/bin/python -m pytest -q
249 passed, 1 skipped, 1 warning in 26.80s
```

## Remaining limitations

- Python/httpx/cURL live HTTPS access in this sandbox still gets TLS EOF for some external sources; the adapters fail gracefully, and official evidence was validated with Arena fetch tools and stored validation payloads.
- The watcher records internal notifications only; external email/SMS/WhatsApp delivery is intentionally not mandatory and not implemented in this phase.
- Source-level success/failure audit is strongest for registry static and Oracle HCM sources; older legacy adapters expose coarser orchestrator-level audit labels.
- Automatic application-package preparation is configurable and disabled by default to avoid generating files unexpectedly.
