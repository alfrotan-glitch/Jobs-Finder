# Source Registry

Jobs-Finder intentionally maintains a small source set. The canonical runtime registry is `utils/source_registry.py`; dashboard settings, CV-import defaults, source adapters, and validation should read source identity, official URLs, parser selectors, labels, host aliases, and operational defaults from that registry rather than duplicating them.

## Source status vocabulary

Every scan reports each configured source as one of:

- `SCANNED` — the configured source budget completed successfully.
- `PARTIAL` — the source returned some data, but the configured budget/limit or recoverable detail-page errors mean the result is not a complete source scan.
- `UNAVAILABLE` — the source could not be reached or returned no successful response.
- `FAILED` — reserved for unexpected source-adapter failures.

A failed or unavailable source is never represented as "0 jobs". Overall scan status remains one of `NO_RELEVANT_JOBS_FOUND`, `PARTIAL_SCAN`, `SOURCES_UNAVAILABLE`, or `SCAN_FAILED` when the market scan was not complete.

## Tier A — Core active sources

- **ACBAR** (`official_name`: ACBAR Jobs) — primary Afghanistan NGO/INGO job board. Active discovery source. The maintained parser recognizes the current `/en/jobs/details/<id>/<slug>` cards and the official legacy `/jobs/<id>/<slug>.jsp` form, preserving whichever official URL was discovered while deduplicating the same numeric vacancy across registered ACBAR host aliases. **Stage 1** walks `?page=N` without a normal hard-coded page ceiling until ACBAR returns an empty listing page (`END_REACHED`), records every lightweight card, and cross-checks the final unique count against ACBAR’s visible “N jobs found” total. A repeated non-empty page is reported as `REPEATED_PAGE` / `PARTIAL`, never as completion. **Stage 2** enriches plausible health/medical or ambiguous roles; only clearly non-health titles skip detail fetching. `max_detail_concurrency` defaults to 5. `job_sources.acbar.max_pages` and `detail_limit` have no default value: if a user explicitly sets either one, the report names the cap and marks the scan `PARTIAL`. An explicit `job_sources.acbar.urls` list is likewise an intentionally scoped, partial scan.

## Tier B — Secondary active sources

- **ReliefWeb** (`official_name`: ReliefWeb Afghanistan jobs) — current public jobs search HTML, queried for Afghanistan health/medical/nutrition vacancies. Afghanistan cards are normalized and their public detail pages are enriched before medical relevance is decided. The scan is bounded by `job_sources.reliefweb.limit` (registry default 20). ReliefWeb API v1 is decommissioned and v2 requires an approved app name, so the project does not pretend to use an unavailable anonymous API.

## Manual official routes

UN public careers/routes and official employer pages are preserved as trustworthy application routes when discovered, but they are not counted as active parser-backed sources unless they are added to `utils/source_registry.py` with an adapter and tests.

A failed source never means the market is empty. Scan summaries retain per-source pages/listings attempted, discovered/parsed vacancies, duplicates, expired/stale exclusions, irrelevant exclusions, incompatible professional-role exclusions, relevant retained vacancies, application routes discovered, and concise error reasons.
