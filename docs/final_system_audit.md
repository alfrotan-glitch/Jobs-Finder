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

The primary product output was subsequently re-audited as a document, not just
as a code path. The professional CV was previously too short and generic; it is
now comprehensive, specialized, and design-system-rendered from the same
verified evidence, with a dedicated CV-quality regression contract. That
finding and its remediation are recorded in the table and in the “Professional
CV result” section below.

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
| **The primary product output — the professional CV — was too short, generic, and under-specialized even though the release was technically green.** | Three compounding causes: (1) every canonical role had `bullets: []`, so each CV role was a title, an employer, and sometimes a date with no professional description at all; (2) the professional summary was one generated sentence listing at most five derived labels; (3) verified items were removed from the CV by "de-duplication" heuristics (`_safe_bullets` dropped any competency whose words were contained in another, and the derived-competency loop suppressed labels sharing an HMIS/clinical/quality/nutrition domain), so the specialized evidence that makes this a health/nutrition CV never reached the page. Tests were green because they asserted survival of *roles* and absence of *fabrication*, never the professional completeness of the rendered CV. | Added owner-confirmable, evidence-anchored `responsibilities` to all five canonical roles (scope wording only: no numbers, dates, achievements, places, or employers that the rest of the verified profile does not already record); rebuilt the content model around a grouped professional skills architecture, a substantive multi-sentence professional profile, and an evidence-complete competency set; replaced the de-duplication filters with pure ordering/grouping so tailoring only selects and reorders verified evidence; added the References section with the existing protected-reference boundary; restructured the Tailored CV to lead with experience; and rendered everything through the design system's PDF/DOCX writers with no fixed page limit. |
| The tailored CV could present a *less* relevant competency set than the reference it was derived from. | Tailoring rebuilt the competency list from a length-ranked evidence pool and dropped domain-overlapping items, so a vacancy could nudge a verified competency out of the CV entirely. | Competencies are now the canonical verified set, grouped and ordered by vacancy relevance: the same items always appear, only their position changes. `tests/test_cv_professional_quality.py` asserts the tailored competency set equals the profile's verified set for every vacancy family. |
| CV page/typography decisions were implicit, and a comprehensive CV could end with a nearly empty final page. | The renderer had one fixed type setting with no pagination strategy, and content was measured only by "does it fit". | The PDF writer now builds with the comfortable design setting, measures the fill ratio of the final page, and re-renders once at the compact setting of the same design system only when that removes a sparse trailing page. Verified CV content is never cut to satisfy a page count. |

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

## Professional CV result

The generated CV is now a real professional document rather than a compact
profile:

- **Comprehensive role descriptions.** Each of the five verified roles carries
  a professional scope description covering the dimensions that apply to it —
  clinical/nutrition responsibilities, supervision, coordination, reporting,
  systems used, field duties, safeguarding duties, and administrative or
  programme duties. Nothing numeric, dated, or achievement-shaped was added.
- **Grouped competency architecture.** Every verified competency is printed
  exactly once, grouped into Clinical & Medical Practice, Health & Nutrition
  Programming, Public Health Systems & Quality, Programme Coordination & Field
  Operations, Supervision & Capacity Building, Safeguarding, Protection &
  Compliance, and Supply Chain, Logistics & Administration.
- **Substantive professional profile.** Assembled only from verified evidence:
  degree with field and institution, exit exam, registration status, the
  lower-bound duration spelled out in words, the verified experience
  dimensions, the verified employers, the verified competency inventory, and
  the verified languages.
- **Complete credentials.** Education, Medical Exit Examination, Professional
  Registration, all seven certifications, and all three languages are present
  in every generated CV, including the tailored ones.
- **Protected references.** The CV prints "Available on request for shortlisted
  applications."; private referee contacts remain outside the repository and
  are only releasable through the vacancy-requirement plus explicit
  owner-approval boundary.

Measured output from the tracked profile: Master CV **2 pages** (~900 words of
content), tailored Medical Doctor CV **2 pages**, tailored Health & Nutrition
CV **2 pages** — each with no artificial page break, no truncation, and no
sparse trailing page. DOCX pagination uses real Word `PAGE` fields, and the
rendered text is fully extractable (ATS-readable) in PDF and DOCX.

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

The CV-quality contract (`tests/test_cv_professional_quality.py`) generates real
artifacts from the tracked profile and asserts: every verified role,
responsibility, certificate, and language survives into TXT, DOCX, and PDF; the
competency set is complete and grouped; the master CV is vacancy-neutral; the
tailored CVs are substantive and agree with each other on credentials; no
invented date, number, entity, or achievement appears; role responsibilities
introduce no new fact beyond the rest of the profile; the final page is not
sparse; and no reference contact data, license number, or internal vocabulary is
ever printed. A mutation check confirmed the fabricated-entity, fabricated-
number, fabricated-achievement, and fabricated-place guards all fail the build
when such content is introduced.

Run after remediation:

```text
python -m pytest -q                       298 passed, 1 upstream warning
python -m ruff check .                    All checks passed
python -m compileall -q main.py dashboard utils tests   passed
node --check dashboard/static/app.js      passed
git diff --check                          passed
```

A no-persistence FastAPI `TestClient` dashboard/API smoke also passed for
`/`, `/api/health`, `/api/profile`, `/api/profile/details`, `/api/jobs`,
`/api/recommended`, and the new `POST /api/master-cv`; it confirmed the
canonical summary identity, the generated Master CV artifacts, and no
`professional_references` response field. The dashboard Master CV action was
also exercised against a sandboxed canonical profile to prove it writes
TXT/DOCX/PDF without mutating `profile.yaml` and without any submission. The test suite warning is upstream:
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
