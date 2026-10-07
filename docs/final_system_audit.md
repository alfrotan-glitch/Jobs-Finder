# Release audit — Jobs-Finder

**Audit date:** 2026-10-07 UTC
**Scope:** canonical profile, privacy, source provenance, matching/readiness,
discovery, documents/packages, dashboard state, persistence, tests, and
cross-platform CI configuration.

## Executive verdict

The local release gate is **passing**. The repository now has a complete,
verified public canonical profile for **Dr. Allah Yar Frotan**, an explicit
four-state profile-completeness contract, truthful source/application-route
semantics, strict readiness gating, and adversarial regression coverage.

The only non-local limitation is live official-source reachability from this
execution environment; it is recorded precisely below and is represented by
the system as `SOURCES_UNAVAILABLE`, not “no jobs found.” Remote GitHub CI
passed on the release pull request across its full Ubuntu/Windows matrix.

## Significant findings and remediation

| Finding | Root cause | Remediation |
| --- | --- | --- |
| The tracked canonical profile was structurally sparse despite tests passing. | Earlier tests exercised synthetic profiles and did not enforce the real profile’s required owner-supplied facts. | Completed `profile.yaml`; added `canonical_profile_completeness_report()` / `assert_canonical_profile_complete()` and a real-profile release test. The contract reports `VERIFIED`, `KNOWN_BUT_NON_PRECISE`, `NEEDS_VERIFICATION`, and `NOT_PROVIDED`, so it does not require invented dates, identifiers, or durations. |
| Reference PII was present in a tracked public file while labelled private. | Naming a field private did not create an actual repository/privacy boundary. | Removed reference-contact PII from the tracked profile. Added an explicit external private-reference boundary, repository ignore rules, a guarded external-only loader, and `docs/privacy.md`. Loading requires both a vacancy-specific reference requirement and explicit owner approval; normal flows never invoke it. |
| A vacancy URL could become a fabricated `source_url`. | `canonical_source_fields()` and enrichment used vacancy/application URLs as fallback source provenance. | Removed that fallback and source-URL list fallback. `source_url`, `vacancy_url`, `application_url`, and `application_email` remain independent; missing source provenance stays missing. |
| Arbitrary linked job/careers URLs could be considered application routes. | URL extraction allowed weak URL-name terms and a generic first-link fallback. | Direct-form extraction now requires a recognised application endpoint or nearby explicit apply/submit instruction. A vacancy page alone is only a manual-review route. |
| Every word “subject” created an application-subject requirement. | The detector used a broad single-word regex. | It now requires email/application-subject context plus a title/reference/code instruction, including relevant Dari/Persian patterns. Policy/legal uses of “subject” are regression-tested. |
| Specialist roles could be treated as general-MD roles. | The role classifier lacked a specialist qualification family. | Pediatrician, General Surgeon, and Specialist Physician now produce `specialist_qualification_required`; a general MD is `NEEDS_VERIFICATION` until verified specialist evidence exists and is not recommended automatically. |
| Experience dimensions were conflated and dated subsets could act as a full career total. | Matching had limited duration keys; inferred date intervals were treated as exact totals. | Added health/nutrition and frontline lower-bound evidence plus qualitative public-health, humanitarian, supervision, coordination, emergency, and Afghanistan-field dimensions. Inferred dated work intervals are lower bounds; they cannot falsely prove or disprove a higher threshold. |
| Unknown vacancy deadline could leave an optimistic ready state. | No explicit closing-date requirement existed when extraction found no date. | A missing deadline is now an essential `NEEDS_VERIFICATION` blocker. Structured source date metadata is accepted when valid; passed dates remain `NOT_ELIGIBLE`. |
| Package UI showed unconditional completion checkmarks. | Dashboard package rendering inferred success from package presence rather than actual artifact paths/state. | Dashboard now displays authoritative package state and file-level `NOT CREATED` / `READY FOR REVIEW`; a manual-applied control is shown only for a review-ready package. Backend supports `NOT_CREATED`, `IN_PROGRESS`, `READY_FOR_REVIEW`, `NEEDS_USER_INPUT`, `BLOCKED`, and `FAILED` vocabulary. |
| Direct package creation could describe a proven-ineligible role too positively. | The lower-level package helper lacked an explicit blocked response. | It now returns `BLOCKED` without email/form output for `NOT_ELIGIBLE`; the normal orchestrator continues to refuse artifact generation. |

## Canonical-profile result

`profile.yaml` remains the only runtime applicant source. SQLite, browser
state, imported CV previews, generated CVs, application packages, caches, and
fixtures do not provide applicant facts to matching or document generation.

The release contract verifies:

- Dr. Allah Yar Frotan; Medical Doctor / Health & Nutrition Specialist; Kabul;
  verified email and phone;
- MD in Curative Medicine, Kabul Medical Science University, 2013–2020;
  completed Medical Exit Exam; verified valid medical registration status;
- verified `> 3` lower-bound clinical/health/nutrition/frontline experience;
- all five supplied employment records, with ACF dates intentionally blank;
- supplied medical, public-health, and management skills; language levels;
  seven supplied certificates; and humanitarian/field evidence dimensions;
- an actual external private-reference boundary.

It intentionally reports ACF dates and the overall lower-bound duration as
`KNOWN_BUT_NON_PRECISE`, and registration number/issue date/expiry/document
path as `NOT_PROVIDED`. No unsupported precision was added.

## Matching, readiness, and documents

`READY_TO_APPLY` requires all extracted essential/required checks to be met.
This includes source validity, compatible profession/qualifications, applicable
experience, location/residency/nationality/gender requirements, open deadline,
direct route, and exact subject/reference where explicitly required. Unknown
critical facts are `NEEDS_VERIFICATION`; known conflicts are `NOT_ELIGIBLE`.

Master-CV generation is position-neutral and only uses verified canonical
facts. Tailoring selects/reorders verified canonical facts, never mutates the
profile or master output. Generated packages are review artifacts only: no
submission, email sending, CAPTCHA/MFA/login bypass, recipient invention,
attachment invention, or application-evidence fabrication occurs.

## Discovery, accounting, and recommendation authority

ACBAR follows pagination to an observable empty page, reports repeated pages,
count mismatches, parse/detail failures, and explicit bounds as partial. The
ReliefWeb adapter’s configured one-page bound is explicitly `PARTIAL` when
reached. Source unavailability, partial scans, successful empty scans, and no
configured sources retain distinct overall statuses.

Recommendation selection has one authority in `utils.recommendations`; CLI,
dashboard, scan summaries, and persisted scan results consume its same ordered
collection. Broad discovery may retain roles for manual review, but
recommendations require a positive MD/public-health classification and
reviewable readiness.

## Security and privacy result

- No secrets, database, generated artifacts, private-reference store, or
  reference-contact PII are tracked. The owner-authorized canonical applicant
  identity/contact facts in `profile.yaml` are intentionally tracked.
- Generated documents and SQLite remain ignored by Git.
- Reference data cannot flow through canonical evidence, documents, package
  JSON, dashboard profile output, recommendations, or SQLite.
- CV imports are bounded, temporary previews and cannot overwrite canonical
  profile data.
- The local dashboard uses no-store, restrictive CSP/frame/referrer headers,
  no CORS opt-in, and same-origin protection for browser writes. It remains a
  loopback-first local tool, not an authenticated public service.

## Verification

The regression suite includes canonical-profile completeness, source-provenance
permutations, direct-route truthfulness, subject-detection adversarial cases,
role-family matrix, specialist qualification handling, dimensional experience,
deadline semantics, package blocking/state truthfulness, reference release
controls, and a real-profile end-to-end acceptance pipeline.

Run after remediation:

```text
python -m pytest -q                       279 passed, 1 upstream warning
python -m ruff check .                    passed
python -m compileall -q main.py dashboard utils tests   passed
node --check dashboard/static/app.js      passed
git diff --check                          passed
```

A no-persistence FastAPI `TestClient` dashboard/API smoke also passed for
`/`, `/api/health`, `/api/profile`, `/api/profile/details`, `/api/jobs`, and
`/api/recommended`; it confirmed the canonical summary identity and no
`professional_references` response field. The test suite warning is upstream:
Starlette deprecates its current `httpx` TestClient integration.

The GitHub Actions workflow runs the same lint, compile, JavaScript syntax, and
pytest checks on Ubuntu and Windows with Python 3.11 and 3.12. Pull request
[#21](https://github.com/alfrotan-glitch/Jobs-Finder/pull/21) passed all four
matrix jobs: Ubuntu 3.11/3.12 and Windows 3.11/3.12. The Windows launcher is
assertion-covered; this Linux audit did not execute an interactive Windows
desktop launcher.

## Live official-source validation

Read-only direct official-source probes at **2026-10-07T05:10:24+00:00**:

| Source | URL | Result | Affected validation |
| --- | --- | --- | --- |
| ACBAR | `https://www.acbar.org/en/jobs` | `httpx.ConnectError`: TLS/SSL connection closed (EOF), before HTTP response | Live listing/detail/pagination parsing could not be exercised. |
| ReliefWeb | `https://reliefweb.int/jobs?search=Afghanistan%20health%20medical%20nutrition` | `httpx.ConnectError`: TLS/SSL connection closed (EOF), before HTTP response | Live listing/detail/route parsing could not be exercised. |

A no-persistence full discovery invocation at
**2026-10-07T05:10:27+00:00** made one request to each adapter and returned
`SOURCES_UNAVAILABLE` with zero retained jobs. This is the correct resulting
system state; it is not a claim that no current jobs exist. Fixture-backed
pagination, detail, accounting, partial-scan, and unavailable-source tests
passed locally.

## Remaining limitation

Only the environment-level external TLS/SSL failure above prevents live source
content validation. All local safeguards and remote CI checks were completed;
retry live validation from a network that can reach the official sources.
