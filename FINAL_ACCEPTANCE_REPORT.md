# Jobs-Finder — Final Acceptance Report

Role executed: final acceptance engineer / security reviewer / product owner / data-integrity
auditor / UX reviewer / release engineer. This was a repair/hardening pass over the existing
implementation — no rewrite, no new parallel architecture, no feature deletion for size reduction.

## 1. Defects found

Evidence integrity:
1. `profile.py` `_add_personal`, `_add_skills_and_certificates`, `infer_years_from_history` used
   truthiness/blacklist logic instead of the canonical tri-state/verified-flag parser, so
   placeholder text and bare presence could leak into "resolved" evidence.
2. `willing_to_relocate` / `field_deployment` had no canonical yes/no/unresolved parser — a
   placeholder string could be coerced to a Python truthy/falsy value.
3. `work_history` years were inferable from entries with no explicit per-entry `verified: true`.
4. **`ProfileEvidence.add()` silently dropped a later, explicitly verified fact if an earlier
   unverified mention of the same value/source already existed** (same (value, source) dedup key
   ignored the `verified` flag). This made a skill/certificate item with `verified: true` become
   invisible whenever the same text also appeared as a plain (unverified) string — a real,
   previously-undetected defect, caught by a new regression test this session.
5. Structured medical-education evidence text leaked the internal `verified` flag's literal value
   (`"False"`/`"True"`) and unresolved placeholder field values (e.g. `institution: "Needs
   verification"`) directly into evidence quotes shown to the user.
6. `utils/documents.py` `_stringify_item()` joined dict fields (degree/institution/dates/etc.)
   without filtering unresolved placeholders, so a confirmed `verified: true` education/work
   entry whose other fields were still placeholders could print literal "Needs verification" text
   into a generated CV/cover letter.
7. `profile_builder.py` (CV import) could, in principle, ever reach a state where a CV-derived fact
   was marked verified — fixed in a prior part of this engagement; re-confirmed intact this
   session with a new dedicated regression-test file.
8. `documents.py` EDUCATION/LICENSE/EXAM sections and cover-letter sentences could print
   unverified facts as confirmed claims — fixed in a prior part of this engagement; re-confirmed
   intact and extended with new regression tests this session.
9. `utils/discovery.py` ACBAR pagination was a hardcoded 3-page list with unbounded, fully
   sequential detail-page fetches (no concurrency bound, no documented budget).
10. `dashboard/server.py` claimed a fake `version="3.0"` in two places; `utils/discovery.py`'s
    `DEFAULT_USER_AGENT` carried the same fake version suffix.
11. `utils/tracker.py` `update_tailored_resume()` always set `status=PACKAGE_READY` regardless of
    whether the generated package actually reported `NEEDS_USER_INPUT` — eligibility, package
    state, and application progress were conflated into one status column.
12. `profile.yaml.example` contained real PII (name "Allah Yar Frotan", email
    `alfrotan@gmail.com`, phone `+93766462006`).
13. `profile_builder.py`'s `job_sources.acbar` schema (`max_pages`/`max_detail_concurrency`) had
    no corresponding support in `discovery.py` and was undocumented in `profile.yaml.example`.
14. No browser-based way existed for a nontechnical user to import a CV, see per-fact
    Verified/Needs verification/Missing status, or explicitly confirm an individual fact without
    editing YAML — `dashboard/server.py` only exposed a raw profile summary.
15. `docs/source_registry.md` had a duplicated clause ("...are not counted as active parser-backed
    sources and are not counted as active parser-backed sources").
16. Minor dead imports: `main.py` (`json`), `utils/medical_requirements.py` (`datetime`),
    `utils/resume_parser.py` (`Any`) — found via `pyflakes`.
17. `README.md`'s Windows-validation sentence did not explicitly state that `run_jobs_finder.bat`
    itself was never executed on an actual Windows machine in this (Linux-only) environment.

No defect was found that required a project rewrite, a new framework, or deletion of a genuinely
used capability.

## 2. Repairs

- Canonical evidence contract (`utils/profile.py`): `is_unresolved_value`, `parse_tristate`,
  `is_verified_flag`, `UNRESOLVED_TOKENS`/`YES_TOKENS`/`NO_TOKENS`, `ProfileEvidence.has_verified()`
  now used consistently across `_add_personal`, `_add_structured_education`, `_add_license`,
  `_add_medical_exit_exam`, `_add_languages`, `_add_skills_and_certificates`,
  `_add_experience_years`, and `infer_years_from_history`. `ProfileEvidence.add()` now **upgrades**
  an existing unverified entry in place when a verified add for the same value/source arrives,
  instead of silently dropping it. Structured-education evidence text now excludes the internal
  `verified` key and any unresolved placeholder field value.
- `utils/documents.py`: `_stringify_item()` now skips unresolved placeholder field values so they
  can never be printed as if confirmed. EDUCATION/LICENSE/EXAM CV sections and cover-letter
  license/exam/language sentences remain gated on genuine verification
  (`_verified_dict_items`, `evidence.has_verified`, `_requirement_met`,
  `_language_lines(verified_only=True)`).
- `utils/document_design.py`: removed 3 overclaiming "verified" taglines; updated the module
  docstring to accurately describe the handoff contract with `documents.py`. The section labels
  "Verified Medical Basis" / "Education & Verified Medical Credentials" were traced end-to-end
  (parsed strictly from the EDUCATION / LICENSE / MEDICAL EXIT EXAM sections of the already-gated
  tailored text) and confirmed accurate — left unchanged.
- `utils/discovery.py`: `discover_acbar_jobs()` rewritten with bounded, documented pagination
  (`max_pages`, default 6; stops automatically once a page returns no new vacancy links) and
  bounded concurrent detail fetches (`max_detail_concurrency`, default 5, via `asyncio.Semaphore`
  + `asyncio.gather`), each still subject to the existing per-request `timeout_seconds`. An
  explicit `job_sources.acbar.urls` list still overrides auto-pagination for a pinned page set.
  Removed the fake version suffix from `DEFAULT_USER_AGENT`.
- `utils/tracker.py`: added a `package_status` column (migrated via `ALTER TABLE` for existing
  DBs) and a `PACKAGE_NEEDS_INPUT` status constant. `update_tailored_resume()` now reads the
  package's own `package_status` and only reports `PACKAGE_READY` when it is not
  `NEEDS_USER_INPUT`; otherwise it reports `PACKAGE_NEEDS_INPUT`. Eligibility (`readiness`
  column), package state (`package_status` column), and application progress (`status` column)
  are now explicitly documented as three distinct concepts in the module docstring.
- `dashboard/server.py`: removed fake `version="3.0"`. Added `GET /api/profile/review` (backend
  computes Verified/Needs verification/Missing per fact — UI only renders it), `POST
  /api/profile/confirm` (allow-listed fields only: `medical_education`, `license_registration`,
  `medical_exit_exam`, `language:<name>` with a required resolved proficiency level — never
  invents a fact, only flips an explicit `verified` flag the user confirms), `POST /api/import-cv`
  (reuses the existing `build_profile_from_cv_file`, backs up any existing `profile.yaml` to
  `profile.yaml.bak` next to it, stores the upload under `resumes/`), and `GET /api/settings` (a
  truthful, read-only view of the current ACBAR/ReliefWeb budget and the fact that background
  scanning and automatic submission are both disabled — no fake controls).
- `dashboard/static/app.js` / `dashboard/templates/index.html`: added CV import UI, a
  verification-review list with per-fact "Mark verified" buttons (language confirmation prompts
  for a proficiency level, since a bare `verified: true` next to a placeholder level is
  deliberately treated as unresolved), a real Settings view, and extended the Applications-tab
  filter/mark-applied logic to include `PACKAGE_NEEDS_INPUT`.
- `profile.yaml.example`: replaced all real PII with placeholders; documented the
  `max_pages`/`max_detail_concurrency` ACBAR config and the `verified: true` convention inline.
- `docs/source_registry.md` / `README.md`: fixed the duplicated clause; documented the ACBAR
  pagination/concurrency budget, the three-state tracker model, the CV import → review → confirm
  workflow, and clarified the Windows launcher was reviewed but not executed on a real Windows
  host in this (Linux) environment.
- `requirements.txt`: added `python-multipart` (required by FastAPI for the new file-upload
  endpoint) — still lightweight, verified by the existing `test_requirements_are_lightweight`.
- Removed the three dead imports found by `pyflakes`.

## 3. Features preserved

All existing user-facing capability was kept: scan (ACBAR + ReliefWeb), deterministic matching
(`READY_TO_APPLY`/`NEEDS_VERIFICATION`/`NOT_ELIGIBLE`), tailored CV/cover-letter generation in
TXT/DOCX/PDF, the application-package checklist and warnings, the official-route open-and-apply
flow, manual-application confirmation with exact-text confirmation, the CLI (`find`, `recommended`,
`jobs`, `stats`, `reset`, `prepare`, `open`, `mark-applied`, `import-cv`, `server`), the dashboard,
and the Windows one-click launcher. Nothing was deleted to "look clean."

## 4. Files (retained/deleted/consolidated)

No files were deleted or consolidated. All existing modules (`utils/profile.py`,
`utils/profile_builder.py`, `utils/documents.py`, `utils/document_design.py`,
`utils/discovery.py`, `utils/medical_matcher.py`, `utils/medical_requirements.py`,
`utils/resume_parser.py`, `utils/tracker.py`, `dashboard/server.py`, `dashboard/static/*`,
`dashboard/templates/index.html`, `main.py`) have a real, current purpose and were retained.
3 dead imports removed (`json` in `main.py`; `datetime` in `medical_requirements.py`; `Any` in
`resume_parser.py`) — mechanical, no behavior change. 4 new test files added (see §10). 1 new
top-level report file added (`FINAL_ACCEPTANCE_REPORT.md`, this document).

## 5. Evidence model

Canonical rule, enforced everywhere: a fact is verified only when `is_verified_flag(value) is
True` (a literal Python `True`, nothing else) on an explicit `verified` field — or, for the two
documented owner-typed scalar exceptions (`clinical_experience.years`,
`ngo_humanitarian_experience.years`, which `profile_builder.py` never populates from a CV), simple
non-placeholder presence. Yes/No preference fields (`willing_to_relocate`, `field_deployment`) go
through `parse_tristate()`, which returns `True`/`False` only for recognised tokens and `None`
(unresolved, never added as evidence) for anything else, including "Needs verification",
"Unknown", "Unconfirmed", "Pending". CV import (`profile_builder.py`) can never set any `verified`
field to `True` — proven by a dedicated regression test using a synthetic CV claiming an MD,
license/registration, fluent English, 5 years of experience, and certificates, none of which
becomes verified or satisfies a matcher requirement. The one latent correctness bug found this
session — `ProfileEvidence.add()`'s dedup silently discarding a verified entry shadowed by an
earlier unverified one — is fixed and covered by a new regression test.

## 6. Discovery

ACBAR: bounded, documented pagination (`max_pages`, default 6, stop-on-no-new-vacancies) replaces
the old hardcoded 3-page list; detail-page fetches are now concurrency-bounded
(`max_detail_concurrency`, default 5) instead of fully sequential and unbounded; an explicit
`job_sources.acbar.urls` override still works for pinning a page set. All of this is covered by 4
new tests (stop-on-no-new-vacancies, max_pages cap respected, concurrency bound respected, explicit
URL override). ReliefWeb path untouched (already bounded by `limit`/`timeout_seconds`). Scan status
semantics (`NO_RELEVANT_JOBS_FOUND`/`PARTIAL_SCAN`/`SOURCES_UNAVAILABLE`/`SCAN_FAILED`/
`SCAN_COMPLETE`) were already correct and remain covered by the original 5 discovery tests plus the
new pagination/concurrency tests — a scan failure is never reported as zero jobs.

## 7. Documents

CV/cover-letter generation never promotes unverified facts to confirmed claims: EDUCATION only
lists `_verified_dict_items()`-filtered entries, LICENSE/REGISTRATION and MEDICAL EXIT EXAM CV
sections and cover-letter sentences are gated on `evidence.has_verified()` / `_requirement_met()`,
and the cover-letter language sentence only claims "verified language profile" when a language is
explicitly `verified: true` with a resolved level (otherwise neutral wording is used). No license
numbers, dates, or documents are invented. `_stringify_item()` now also filters unresolved
placeholder field values out of any dict-based CV line (education/work-history), so a confirmed
entry can never still display a literal "Needs verification" as if it were real data. 7 new
regression tests target exactly these invariants (education gating both ways, license/exam/
language cover-letter wording both ways, and placeholder-token absence from all generated text).

## 8. Tracker

Three concepts are now explicitly separate and documented: Eligibility (`readiness` column:
`READY_TO_APPLY`/`NEEDS_VERIFICATION`/`NOT_ELIGIBLE`), Package state (new `package_status` column:
`NOT_CREATED`/`READY_FOR_REVIEW`/`NEEDS_USER_INPUT`, literally copied from the generated package),
and Application progress (`status` column, now including `PACKAGE_NEEDS_INPUT` alongside
`FOUND`/`REVIEWED`/`PACKAGE_READY`/`APPLIED_MANUALLY`). `PACKAGE_READY` is never set when the
underlying package reports `NEEDS_USER_INPUT`. New vacancies default to `package_status =
NOT_CREATED`. 3 new regression tests cover: a `NEEDS_USER_INPUT` package maps to
`PACKAGE_NEEDS_INPUT` (not `PACKAGE_READY`), a `READY_FOR_REVIEW` package maps to `PACKAGE_READY`,
and new vacancies default to `NOT_CREATED`.

## 9. UI

The dashboard remains display/collect-only; all judgement stays backend-authoritative. Added:
**My Profile → Import a CV** (creates a DRAFT, backs up any existing profile), **Verification
review** (lists every evidence-bearing fact with a backend-computed Verified/Needs
verification/Missing status and a one-click "Mark verified" button for the facts with a safe,
unambiguous confirm path — medical education, license/registration, medical exit exam, and
per-language with a required proficiency level), and a truthful **Settings** page showing the
actual ACBAR/ReliefWeb scan budget and that background scanning and automatic submission are both
disabled (no fake toggles). The Applications tab now also surfaces `PACKAGE_NEEDS_INPUT` vacancies
and allows marking them applied. No matching/verification/eligibility logic was duplicated in
JavaScript — every status shown comes directly from a backend endpoint.

Known, deliberate scope limit: nationality, location, and the relocate/deployment preferences are
shown in the review list but still require a direct `profile.yaml` edit to verify (no generic
free-text confirm endpoint was added for them, to avoid building an open-ended profile editor
beyond what the brief's named CV-import test scenario — MD, license, English, experience,
certificates — requires).

## 10. Tests

`tests/test_discovery.py`, `tests/test_documents.py`, `tests/test_matching.py`,
`tests/test_security_invariants.py`, `tests/test_tracker_and_launcher.py` (original 23 tests,
PII-sanitized and fixture-corrected this engagement) plus four new files added this session:
`tests/test_evidence_contract.py` (11 tests: tri-state parsing, `is_verified_flag`,
`is_unresolved_value`, relocation/deployment resolution, work-history verified-entry gating,
skills verification upgrade-not-shadowed, structured-education text leak absence),
`tests/test_cv_import_never_verifies.py` (4 tests: synthetic MD/license/English/5yr/certificates
CV never produces a verified flag or a `READY_TO_APPLY`/`NOT_ELIGIBLE` matcher result),
`tests/test_document_verification_gating.py` (7 tests: EDUCATION inclusion/exclusion, cover-letter
license/exam/language wording both verified and unverified, no raw placeholder tokens in generated
text), and `tests/test_dashboard_api.py` (12 tests: health has no fake version, profile/review
endpoints, CV import creates a review-needed draft and backs up an existing profile, confirm
endpoint allow-list and language+level requirement, settings reflects the real budget, `/api/find`
requires a profile). 3 new tests added to `tests/test_discovery.py` (pagination/concurrency/
override) and 3 to `tests/test_tracker_and_launcher.py` (package-state separation).

**Result: 23 → 66 tests, all passing** (`pytest -q` from the repo root with the project `.venv`).

## 11. Windows

`run_jobs_finder.bat` was reviewed (directory/venv/requirements handling, host/port env overrides,
no scan/automation on startup) but **not executed on an actual Windows machine** — this
development environment is Linux-only. README now says this explicitly rather than implying
Windows execution was verified.

## 12. Git

Only two branches exist: `main` (remote tip `b98b02e`) and this session's working branch
`arena/01a0f684-jobs-finder` (based on `ca56c5a`, which is content-identical to `main`'s tip — the
repo is a shallow clone, which initially made `git merge-base` report no common ancestor; a direct
diff confirmed the two commits are identical in content). No other Arena branch names from the
original brief exist as distinct refs in this repository. No branch was deleted, since there is no
stray branch to delete — `main` is canonical and this working branch is the only other one, pushed
to `origin/arena/01a0f684-jobs-finder` and opened as PR #3 against `main`.

## 13. Final acceptance decision

**ACCEPTED**

No critical evidence-integrity defect remains open. The one genuine latent defect discovered during
this pass (`ProfileEvidence.add()` dedup silently dropping a verified entry) is fixed and covered
by a regression test. CV import is proven (by test, using the brief's own named scenario) to never
auto-verify any fact. Document generation is proven to never promote unverified evidence to a
confirmed claim. Discovery uses a bounded, documented, tested pagination/concurrency budget instead
of an arbitrary hardcoded limit, and never converts a technical failure into "zero jobs". The
tracker now has three explicitly separate, tested states instead of one conflated status. The
dashboard gained a real, backend-authoritative CV-import → review → confirm workflow requiring no
YAML knowledge for the brief's named credential types, plus a truthful Settings page. profile.yaml.example
and the test fixtures no longer contain real PII. The known scope limit (profile fields without a
one-click confirm endpoint — nationality/location/relocation/deployment) is a deliberate,
documented minimal-scope decision, not an integrity defect, since those facts still correctly show
as "Missing"/"Needs verification" rather than being silently verified.
