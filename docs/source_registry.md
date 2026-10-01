# Source Registry

Jobs-Finder intentionally maintains a small source set.

## Tier A — Core active sources

- **ACBAR Jobs** — primary Afghanistan NGO/INGO job board. Active discovery source. The maintained parser recognizes the current `/en/jobs/details/<id>/<slug>` cards and the official legacy `/jobs/<id>/<slug>.jsp` form, preserving whichever official URL was discovered while deduplicating the same numeric vacancy across `acbar.org`, `www.acbar.org`, and `server.acbar.org`. Each scan uses a deliberate, documented budget rather than attempting to exhaustively mirror the site: listing pages are walked with `?page=N`, stopping once a page yields no new vacancy links, up to `job_sources.acbar.max_pages` (default 6). Detail requests are prioritized for obvious medical titles and then spent on terse cards so final relevance is decided after enrichment; they remain capped by `detail_limit` and `max_detail_concurrency` (defaults 30 and 5) with a per-request timeout. An explicit `job_sources.acbar.urls` list overrides auto-pagination.

## Tier B — Secondary active sources

- **ReliefWeb Afghanistan jobs** — current public jobs search HTML, queried for Afghanistan health/medical/nutrition vacancies. Afghanistan cards are normalized and their public detail pages are enriched before medical relevance is decided. The scan is bounded by `job_sources.reliefweb.limit` (default 20). ReliefWeb API v1 is decommissioned and v2 requires an approved app name, so the project does not pretend to use an unavailable anonymous API.

## Manual official routes

- UN public careers/routes and official employer pages are preserved as trustworthy application routes when discovered, but they are not counted as active parser-backed sources.

A failed source never means the market is empty. The scan status distinguishes complete scans, partial scans, unavailable sources, and scan failures.
