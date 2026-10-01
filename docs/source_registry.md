# Source Registry

Jobs-Finder intentionally maintains a small source set.

## Tier A — Core active sources

- **ACBAR Jobs** — primary Afghanistan NGO/INGO job board. Active discovery source. Each scan uses a deliberate, documented budget rather than attempting to exhaustively mirror the site: listing pages are walked page by page, stopping automatically once a page yields no vacancy links not already seen, up to `job_sources.acbar.max_pages` (default 6, configurable in `profile.yaml`). Detail-page fetches are capped at `job_sources.acbar.max_detail_concurrency` concurrent requests (default 5) with a per-request timeout (`timeout_seconds`, default 25s), so a slow or unresponsive source cannot turn one scan into an unbounded wait. An explicit `job_sources.acbar.urls` list overrides auto-pagination entirely for a pinned set of pages.

## Tier B — Secondary active sources

- **ReliefWeb Afghanistan jobs** — humanitarian vacancies filtered for Afghanistan and health/public-health terms. Active but non-critical.

## Manual official routes

- UN public careers/routes and official employer pages are preserved as trustworthy application routes when discovered, but they are not counted as active parser-backed sources.

A failed source never means the market is empty. The scan status distinguishes complete scans, partial scans, unavailable sources, and scan failures.
