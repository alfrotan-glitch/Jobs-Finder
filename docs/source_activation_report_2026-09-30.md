# Afghanistan health/NGO source activation report — 2026-09-30

Scope: highest-value `NOT_IMPLEMENTED` / `LIMITED` registry sources for Dr. Frotan's Afghanistan medical, health, nutrition, NGO/INGO, and programme-management profile. No login, CAPTCHA, MFA, Cloudflare, robot/security bypass, or application submission was attempted.

## Newly activated / improved official sources

| Source | Status | Technology | Evidence / validation | Notes |
| --- | --- | --- | --- | --- |
| IOM Recruitment | `ACTIVE` | Oracle Recruiting Cloud public Candidate Experience API (`oracle_hcm_api`) | Official IOM gateway linked to Oracle site `CX_1001`; public list/detail APIs exposed Afghanistan requisition `22777`, `Supply Chain Assistant`, Herat/Jalalabad/Kandahar/Mazar-I-Sharif, posted 2026-09-20, closing 2026-10-04. | Current sample is Afghanistan-relevant but operations/supply-chain rather than medical; matcher marks fit separately. Apply/profile flow may require account. |
| Norwegian Refugee Council Careers | `ACTIVE` | Oracle Recruiting Cloud public Candidate Experience API (`oracle_hcm_api`) | Official NRC careers page links to Oracle site `CX_2019`; public list/detail APIs exposed requisition `21597`, `Humanitarian Access & Safety Manager Afghanistan`, Kabul, closing 2026-09-30. | Public vacancy details are parseable; apply flow may require candidate account. Freshness filtering handles same-day/closed jobs. |
| Aga Khan Health Services Afghanistan (AKHS-A) | `ACTIVE` | Static/Odoo public career pages via reusable registry static adapter with detail-page enrichment | Official `https://akhs.odoo.com/jobs` showed current `Nutrition Counselor` and `Surgeon` vacancies; detail pages were public and carried requirements, dates, and application/profile route. | Activated as the AKDN/AKHS-A Afghanistan health source. Central AKDN careers pages were not used because they were not accessible in verification. |
| French Medical Institute for Mothers and Children (FMIC) | `ACTIVE` | Static/SharePoint-style public vacancy pages via reusable registry static adapter with detail-page enrichment | Official FMIC vacancies page listed `Medical Officer`; detail page included closing date 2026-10-05, vacancy `FMIC/HR/571`, medical/AMC requirements, and Google Forms application route. | High-provenance official hospital source. |

## Sources kept LIMITED / NOT_IMPLEMENTED / INACCESSIBLE

| Source | Registry status | Reason |
| --- | --- | --- |
| HealthNet TPO / Health Works | `NOT_IMPLEMENTED` | Official homepage is reachable and confirms Afghanistan health work, but no official public vacancy route was verified. `https://healthnettpo.org/en/vacancies` returned Page not found; `healthworks.org/jobs` and `/careers` were parked/Sedo pages. Third-party job-board signals are not enough for official activation. |
| Relief International Careers | `LIMITED` | Official SmartRecruiters career page is publicly fetchable and exposes job/detail pages, but no current official Afghanistan health/medical/program vacancy was verified on that route. A current RI health Quality-of-Care vacancy was validated from Wazifaha with medium provenance only. |
| Danish Refugee Council Careers | `LIMITED` | Official DRC jobs page is public and parser-feasible, but no current Afghanistan vacancy appeared in the fetched list; not activated without a real Afghanistan vacancy to parse/normalize. |
| International Rescue Committee Careers | `INACCESSIBLE` | Official Cornerstone/IRC careers routes failed or returned `WebContentNotFound` in verification. Third-party snippets are not used as official source. |
| CURE International Afghanistan | `INACCESSIBLE` | Official CURE careers URLs failed to fetch; only third-party/historical Afghanistan snippets were found. No official public vacancy extraction route verified. |
| Central AKDN careers | Not separately activated | Central AKDN pages returned server errors in verification. The official AKHS-A Odoo source was activated instead. |

## Real vacancy pipeline validation samples

Detailed machine-readable validation is saved at `docs/newly_activated_source_validation_2026-09-30.json`.

Each sample was run through: `RawVacancy -> Normalize -> Validate -> Job -> Deduplicate -> Freshness -> Requirements -> Match Profile -> Existing review-first workflow (no submission)`.

| Source | Real vacancy | Normalized valid | Fresh on 2026-09-30 | Match/readiness result |
| --- | --- | --- | --- | --- |
| FMIC | Medical Officer — Kabul — closes 2026-10-05 | Yes | Yes | `READY_TO_APPLY`; no application submitted |
| AKHS-A | Surgeon — Kabul — closes 2026-10-10 | Yes | Yes | `NEEDS_VERIFICATION`; specialist-surgeon credential requires user verification |
| IOM | Supply Chain Assistant — Herat/Jalalabad/Kandahar/Mazar-I-Sharif — closes 2026-10-04 | Yes | Yes | `NOT_ELIGIBLE` / low relevance for Dr. Frotan's medical profile |
| NRC | Humanitarian Access & Safety Manager Afghanistan — Kabul — closes 2026-09-30 | Yes | Yes on the run date | `READY_TO_APPLY` by extracted requirements but low profile relevance; should be reviewed before any application |
| Relief International via Wazifaha | Quality of Care and Capacity Building Officer — Nimruz — closes 2026-10-04 | Yes | Yes | `NEEDS_VERIFICATION`; medium-provenance board source, employer route/instructions preserved |

Deduplication check in the validation artifact used one intentional duplicate and reduced 6 inputs to 5 unique vacancies while preserving source URLs.

## Implementation notes

- Added reusable `oracle_hcm_api` registry method and runtime mapping.
- Added reusable Oracle HCM discovery for public Oracle Candidate Experience list/detail endpoints.
- Extended reusable registry static source handling with optional detail-page enrichment, rather than adding one-off scrapers per employer.
- Preserved source provenance, source URLs, original vacancy URL, application route, closing date, and adapter reliability metadata.
- Added focused tests for Oracle HCM parsing/provenance, static detail-page enrichment, and specialist-surgeon requirement handling.

## Test result

Full suite on 2026-09-30:

```text
.venv/bin/python -m pytest -q
222 passed, 1 skipped in 24.28s
```

A live direct Python/cURL network smoke test in this sandbox hit TLS EOF errors for external HTTPS hosts and returned zero live adapter results; adapter failures were logged and graceful. Official page/API content was verified with Arena `fetch_page` before normalization pipeline validation. No bypass was attempted.

## Remaining discovery gaps

- Find HealthNet TPO's current official vacancy channel, if one exists.
- Recheck RI SmartRecruiters when a current Afghanistan health/program vacancy appears; add a dedicated SmartRecruiters adapter only if reusable across registry sources.
- Recheck DRC official jobs page until an Afghanistan vacancy appears for parser validation.
- Recheck IRC official Cornerstone/careers route from an environment where it is publicly accessible.
- Recheck CURE official careers access and Afghanistan hospital vacancy route.
