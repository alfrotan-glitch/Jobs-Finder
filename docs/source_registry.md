# Afghanistan Job Source Registry

`docs/source_registry.json` is the maintained machine-readable registry for Afghanistan job discovery. The discovery flow is:

`Source Registry → Active Sources → Discover → Normalize → Validate → Deduplicate → Freshness/Deadline → Requirements → Match Profile → Existing Application Workflow`

ACBAR is one source in the registry, not the center of the system.

## How source status works

- `ACTIVE` — public source is usable by an implemented adapter and enabled only when `enabled_in_autonomous_discovery` is `true`.
- `LIMITED` — source exists and may be partially usable, but has constraints such as API approval, JavaScript-heavy pages, generic parsing, apply-login, or aggregator provenance.
- `BLOCKED` — public access is blocked by HTTP 403/login/CAPTCHA/access controls. Do not bypass.
- `INACCESSIBLE` — URL failed, returned 404/DNS errors, or otherwise could not be accessed.
- `NOT_IMPLEMENTED` — real source is known, but no safe implemented discovery method has been verified.

Only `ACTIVE` and selected `LIMITED` sources with `enabled_in_autonomous_discovery: true` are used by autonomous discovery.

## Required fields

Each registry record must include:

- `id`
- `organization_name`
- `source_category`
- `country_coverage`
- `official_website`
- `official_jobs_url`
- `discovery_method`
- `source_type`
- `afghanistan_relevance`
- `health_medical_relevance`
- `public_accessibility`
- `login_required`
- `captcha_blocking_status`
- `application_url_availability`
- `provenance_level`
- `reliability_status`
- `last_checked`
- `limitations`
- `notes`
- `enabled_in_autonomous_discovery`

Optional fields include `checked_by`, `last_check_result`, `adapter_config`, and `tags`.

## Safe update process

1. Verify the source is real and relevant before adding it.
2. Use the official employer/career page when available. Use aggregators only as discovery signals.
3. Do not invent URLs, APIs, application routes, deadlines, job counts, or source capabilities.
4. If access requires login, CAPTCHA, MFA, or security bypass, set `reliability_status` to `BLOCKED` or `LIMITED` and keep `enabled_in_autonomous_discovery` false.
5. If you have not actually checked the source, leave `last_checked` empty and say that it is not checked in `last_check_result`.
6. Set `provenance_level`:
   - `high` for official employer/government/UN career pages
   - `medium` for reputable job boards and humanitarian/UN aggregators
   - `low` for social/search snippets
   - `unknown` when unverified
7. Enable autonomous discovery only for sources handled by a supported method:
   - `acbar_html`
   - `reliefweb_api_or_html`
   - `unjobs_html`
   - `unicef_careers_html`
   - `registry_static_html`
   - `official_career_page_static`
   - `greenhouse_api`
   - `lever_api`
   - `jobspy_opt_in`
   - `oracle_hcm_api`
8. Run tests:

```bash
python -m pytest tests/test_source_registry.py tests/test_discovery_pipeline.py -q
python -m pytest -q
```

## Adding an official static career page

Use `registry_static_html` only when the public page exposes job links in HTML or enough text for deterministic parsing.

Example:

```json
{
  "id": "example_health_org",
  "organization_name": "Example Health Organization",
  "source_category": "health_nutrition_organization",
  "country_coverage": "Afghanistan",
  "official_website": "https://example.org/",
  "official_jobs_url": "https://example.org/careers",
  "discovery_method": "registry_static_html",
  "source_type": "official_employer_career_page",
  "afghanistan_relevance": "High: operates in Afghanistan",
  "health_medical_relevance": "High: clinical and public-health roles",
  "public_accessibility": "public",
  "login_required": false,
  "captcha_blocking_status": "none_observed",
  "application_url_availability": "yes",
  "provenance_level": "high",
  "reliability_status": "ACTIVE",
  "last_checked": "2026-09-30",
  "checked_by": "manual fetch",
  "last_check_result": "Public careers page exposed current job links.",
  "limitations": "Generic parser; verify application instructions before applying.",
  "notes": "Official employer source.",
  "enabled_in_autonomous_discovery": true,
  "adapter_config": {"require_afghanistan": false, "limit": 20},
  "tags": ["medical", "official"]
}
```

For global UN/INGO pages, set `adapter_config.require_afghanistan` to `true` so non-Afghanistan vacancies are skipped.

## Social sources

LinkedIn and Facebook are registered as blocked/limited discovery signals only. Jobs-Finder must not scrape or bypass login, CAPTCHA, MFA, robots/security restrictions, or any access controls. Future integration may only use public/legal content and should verify the official employer application route before treating a post as actionable.
