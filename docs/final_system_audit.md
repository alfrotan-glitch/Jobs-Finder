# Final system audit — Jobs-Finder

**Audit date:** 2026-10-06
**Repository:** `alfrotan-glitch/Jobs-Finder`  
**Working branch:** `arena/01a10495-jobs-finder`

## 1. Scope and branch decision

The repository and branch topology were inspected before repair work.

| Check | Result |
| --- | --- |
| `main` at audit start | `81bf555e140536bb8537d32dcbb92652d53cc91c` |
| Working branch at audit start | `81bf555e140536bb8537d32dcbb92652d53cc91c` |
| Merge base | the same commit |
| `main...arena/01a10495-jobs-finder` divergence at audit start | `0 0` |
| Integration decision | No merge, fork, repository, or duplicate profile was needed. Repairs belong directly on the existing Arena branch. |

The audit covers the production CLI/dashboard, canonical profile handling, CV import, matching, document generation, discovery/source reporting, tracker/recommendation accounting, tests, configuration, and documentation.

Before the final push, the remote copy of this same fixed Arena branch was fetched and found to contain two concurrent canonical-profile commits (`3e5aa58`, `19e88b7`) not present in the initially mounted local ref. They were merge-integrated into this branch; the audited content was retained and the complete checks below were rerun after the merge.

## 2. Canonical applicant architecture

`profile.yaml` in the project root is now the sole production applicant record. Runtime callers reach it through `utils.paths.CANONICAL_PROFILE_PATH` and the repository API in `utils.profile`:

- `load_canonical_profile()` is the only production loader.
- `save_canonical_profile()` atomically writes only that path and accepts no caller-selected path.
- `profile.yaml.example` is a schema/template only, never a fallback.
- The SQLite database is a vacancy/scan/package store, not an applicant-profile store.
- The local `profile.yaml` remains Git-ignored; it was not added to the commit.

The owner-supplied canonical profile, when mounted in a private local runtime, is for **Dr. Allah Yar Frotan**, Medical Doctor (MD) and Health & Nutrition Specialist in Kabul, Afghanistan. It contains the supplied contact data, MD education, valid registration/license status without invented identifiers or dates, verified Medical Exit Exam, five supplied roles, seven supplied certificates/trainings, and verified Dari/Persian, English, and Pashto levels. The acceptance checkout intentionally does not include that ignored private file; the real-profile integration assertion therefore skips there rather than manufacturing a fallback profile.

Conservative omissions are intentional:

- no registration/license number, issue date, expiry date, or document path;
- no dates for either ACF role;
- no invented exact aggregate experience duration;
- no invented current employer or current title;
- no unconfirmed nationality, gender, relocation, or field-deployment assertion.

## 3. Verification and evidence repairs

The codebase now enforces one literal verification rule: only an adjacent Boolean `verified: true` counts. String values such as `"true"`, `"yes"`, `1`, missing flags, and placeholder text do not count.

Notable repairs:

1. **Experience lower bounds are preserved.** `> 3` is stored as a verified lower-bound claim, not silently converted into exactly three years. It can satisfy a three-year minimum; it cannot prove five years, which is reported as `Needs verification`, not `Not met`.
2. **Medical exams are distinct.** A vacancy requiring a **Medical Council Exam** produces an independent essential requirement and is not satisfied by verified **Medical Exit Exam** evidence. A vacancy that actually says “exit exam” can use exit-exam evidence.
3. **Work history and competency evidence remain per-item.** Dated work is counted only when that entry is explicitly verified; overlapping dated intervals are merged rather than double counted.
4. **Dashboard confirmation is atomic.** The dashboard refuses to bulk-verify a multi-entry education list. A one-click confirmation can affect only the one safe field/entry; otherwise the owner must review entries individually in the canonical file.
5. **Personal data in documents is evidence-gated.** Employer-facing name, email, phone, location, and LinkedIn data require their own personal verification flag. Unverified/missing name, email, and phone are replaced by `CONFIRM BEFORE SUBMISSION`; unverified location/LinkedIn is omitted. Package readiness remains blocked until identity/contact review is complete.

## 4. CV import and sample-data isolation

CV import is intentionally limited to an in-memory `DRAFT` preview:

- dashboard uploads are accepted only as supported PDF/plain-text formats, streamed through an 8 MiB limit, and held in a system temporary directory only for extraction;
- no imported CV path, cache, backup, YAML profile, or database applicant record is created;
- no extracted fact can be marked verified by the importer;
- draft previews are rejected by matching and document generation;
- stale `resume_<hash>.txt` cache content is not trusted as input.

The synthetic CV fixture is retained only at `tests/fixtures/sample_jane_doe_cv.txt`. Regression coverage scans repository text to ensure that fixture identity does not appear in production files or generated production content.

## 5. Matching behavior

`utils.medical_requirements.py` and `utils.medical_matcher.py` were audited and hardened for deterministic, conservative assessment:

- MD/medical education, registration/license, Medical Exit Exam, council exam, experience, language, role family, location, nationality/residency, gender, deadline, source validity, and application route remain distinct checks.
- A known conflict such as a verified gender mismatch or an incompatible regulated profession remains `NOT_ELIGIBLE`.
- Unknown or unverified evidence remains `NEEDS_VERIFICATION`; it is not promoted to a match and is not incorrectly treated as a proven failure.
- Generic health words do not automatically make a programme/operations vacancy recommended. Recommendation requires both reviewable readiness and a positively compatible MD/public-health role classification.
- The match report contains requirement evidence/provenance and does not use a single opaque score.

## 6. Documents and application packages

Tailoring is selection, ordering, and emphasis of verified evidence only. It does not alter the input profile mapping or write a vacancy-specific version of the master profile.

The document pipeline:

- rejects `DRAFT` imported profiles;
- excludes unverified education, work history, skills, certificates, languages, license, and exit-exam claims from employer-facing factual content;
- uses generic safe text or review warnings where evidence is unavailable;
- checks current profile evidence again before putting registration/exit-exam claims into a cover letter, so a stale match report cannot become a second evidence store;
- creates review-first TXT/DOCX/PDF CV and cover-letter artifacts plus package/checklist files;
- refuses packages for deterministic `NOT_ELIGIBLE` vacancies;
- never sends email, submits forms, bypasses CAPTCHA/MFA/login, or marks an application applied without explicit user confirmation.

Three different role packages were regression-tested against one master mapping; each tailored output varied while the source profile stayed byte-for-byte unchanged.

## 7. Dashboard, CLI, and database

The CLI and dashboard both use the canonical profile repository and the shared recommendation orchestration.

The dashboard was runtime-smoke-tested with the local profile:

- `GET /` — HTTP 200
- `GET /api/health` — HTTP 200
- `GET /api/profile` — HTTP 200
- `GET /api/profile/details` — HTTP 200
- `GET /api/profile/review` — HTTP 200
- `GET /api/settings` — HTTP 200

The settings response confirmed that background scanning and automatic submission are disabled. The dashboard does not keep a separate mutable applicant profile.

Browser-facing dashboard hardening is also enforced centrally:

- Swagger/ReDoc/OpenAPI endpoints are disabled; the supported interfaces are the dashboard and CLI;
- every dashboard response is marked `no-store`/private and carries CSP, anti-frame, no-referrer, no-sniff, and restrictive browser-permission headers;
- the dashboard does not enable CORS, and foreign-origin/referer state-changing browser requests are rejected before they can start a scan, alter verification, prepare a package, or mark an application;
- these are defence-in-depth privacy controls for the loopback-first workstation app, not authentication. Public/shared-network deployment still requires real access control and TLS.

Recommendation accounting has one authority in `utils.recommendations`:

- scan recommendations are collected once from `(job, match)` pairs;
- `recommended_from_scan == len(scan.recommendations)` is structural;
- CLI scan output, dashboard scan response/activity, and persisted scan collection use that same list;
- the stored-history view applies the same recommendation gate and ordering;
- recommendation API responses include a saved-scan timestamp/status context (or an explicit stored-history origin), and the dashboard visibly labels that provenance rather than implying a live refresh.

## 8. Discovery and source status

The maintained source registry contains ACBAR and ReliefWeb with explicit official URLs and source adapters.

### ACBAR

Normal ACBAR discovery requests successive listing pages until an actual empty listing page reports `END_REACHED`. It has no normal page-count or detail-count ceiling. It tracks parse failures, repeated pages, reported-listing-count mismatches, listing/detail request failures, explicit URL scopes, and bounded detail concurrency. Any inability to reach a real end is represented as partial/failure rather than “zero jobs.”

### ReliefWeb

ReliefWeb is accurately documented as a bounded one-result-page secondary route, not a full pagination crawler. The default bound is 20. If the first result page reaches that bound, the source reports `RESULT_LIMIT_REACHED` and the overall scan is partial; fewer results are only the observable end of that one-page route.

No live external market scan was run for this audit. The final acceptance gate also attempted read-only connectivity probes to the official ACBAR and ReliefWeb listing URLs; both ended with a TLS/SSL EOF connection error in this environment, before vacancy data was parsed or stored. Therefore this report makes **no claim** that there were zero jobs or that the live Afghanistan job market was empty. Network/source failure must remain an environment limitation (`SOURCES_UNAVAILABLE`, `PARTIAL_SCAN`, or `SCAN_FAILED` as applicable), not a market conclusion.

## 9. Tests and static/runtime checks

Executed in this checkout using a freshly created project `.venv` on Python 3.11:

| Check | Result |
| --- | --- |
| Targeted dashboard/canonical-profile/provenance/security regressions | **39 passed, 1 skipped** |
| Final full suite without a private `profile.yaml` mounted | **239 passed, 1 skipped** in 9.53 s (the skip is the intentionally local real-profile integration assertion) |
| Ruff | `python -m ruff check .` — **passed** |
| Bytecode compilation | `python -m compileall -q main.py dashboard utils tests` — **passed** |
| Dashboard JavaScript syntax | `node --check dashboard/static/app.js` — **passed** |
| Patch whitespace | `git diff --check` — **passed** |
| Dashboard endpoint smoke without a private profile | **passed**: root, health, profile, recommendations, and scan endpoints returned HTTP 200; profile reported absent rather than loading a fallback |
| CI configuration | The cross-platform GitHub Actions matrix now runs Ruff, Python compilation, JavaScript syntax validation, and pytest before reporting success. |

The test run emitted one upstream FastAPI/Starlette TestClient deprecation warning about the installed `httpx` integration. It did not fail tests.

No direct Windows filesystem checkout or interactive Windows-launcher execution was performed in this Linux audit environment. Existing CI/launcher contract tests were run, but that is not represented as a direct Windows runtime validation.

## 10. Remaining limits and user actions

1. `profile.yaml` is private local data. Before use, the owner should review it directly and only add future facts, dates, identifiers, documents, or preferences when confirmed.
2. A Medical Council Exam requirement remains deliberately unresolved unless the applicant provides verified council-exam evidence or the vacancy explicitly establishes equivalence to the Medical Exit Exam.
3. The exact duration beyond `> 3` years remains intentionally unasserted. Higher thresholds require verified exact/adequate evidence.
4. ReliefWeb coverage is bounded by design and clearly marked partial when the configured first-page bound is reached.
5. Generated packages are review artifacts only; the applicant must verify every warning and submit manually.
6. Live discovery results are time- and network-dependent. A source outage must never be interpreted as “0 jobs.”
