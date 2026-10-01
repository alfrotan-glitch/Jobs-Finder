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

- **ACBAR** (`official_name`: ACBAR Jobs) — primary Afghanistan NGO/INGO job board. Active discovery source. The maintained parser recognizes the current `/en/jobs/details/<id>/<slug>` cards and the official legacy `/jobs/<id>/<slug>.jsp` form, preserving whichever official URL was discovered while deduplicating the same numeric vacancy across registered ACBAR host aliases. Each scan uses a deliberate, documented budget rather than attempting to exhaustively mirror the site: listing pages are walked with `?page=N`, stopping once a page yields no new vacancy links, up to `job_sources.acbar.max_pages` (registry default 6). Detail requests are prioritized for obvious medical titles and then spent on terse cards so final relevance is decided after enrichment; they remain capped by `detail_limit` and `max_detail_concurrency` (registry defaults 30 and 5) with a per-request timeout. An explicit `job_sources.acbar.urls` list overrides auto-pagination.

## Tier B — Secondary active sources

- **ReliefWeb** (`official_name`: ReliefWeb Afghanistan jobs) — current public jobs search HTML, queried for Afghanistan health/medical/nutrition vacancies. Afghanistan cards are normalized and their public detail pages are enriched before medical relevance is decided. The scan is bounded by `job_sources.reliefweb.limit` (registry default 20). ReliefWeb API v1 is decommissioned and v2 requires an approved app name, so the project does not pretend to use an unavailable anonymous API.

## Manual official routes

UN public careers/routes and official employer pages are preserved as trustworthy application routes when discovered, but they are not counted as active parser-backed sources unless they are added to `utils/source_registry.py` with an adapter and tests.

A failed source never means the market is empty. Scan summaries retain per-source pages/listings attempted, discovered/parsed vacancies, duplicates, expired/stale exclusions, irrelevant exclusions, incompatible professional-role exclusions, relevant retained vacancies, application routes discovered, and concise error reasons.
