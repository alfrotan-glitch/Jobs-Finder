"""Canonical discovery source registry for Jobs-Finder.

This module is intentionally small and data-only.  Source adapters keep the
parsing logic, while source identity, official URLs, parser selectors, labels,
and operational defaults live here so they are not duplicated across the
backend, dashboard, profile builder, and documentation/tests.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "acbar": {
        "id": "acbar",
        "name": "ACBAR",
        "display_name": "ACBAR",
        "official_name": "ACBAR Jobs",
        "tier": "A",
        "fetcher": "discover_acbar_jobs",
        "active": True,
        "official_url": "https://www.acbar.org/en/jobs",
        "homepage_url": "https://www.acbar.org",
        "listing_url": "https://www.acbar.org/en/jobs",
        "host_aliases": ["acbar.org", "www.acbar.org", "server.acbar.org"],
        "selectors": {
            "listing_links": ['a[href*="/en/jobs/details/"]', 'a[href^="/jobs/"]'],
            "detail_title": "h1.job-title, h1.vacancy-title, [data-vacancy-title], h1",
        },
        "path_patterns": {
            "vacancy_id": r"/(?:en/)?jobs/(?:details/)?(\d+)(?:/|$)",
            "listing_path": r"(?:/en/jobs/details/\d+(?:/[^/]+)?|/jobs/\d+/[^/]+\.jsp)$",
        },
        "provenance_labels": {
            "listing": "ACBAR listing",
            "detail": "ACBAR detail",
        },
        "defaults": {
            "timeout_seconds": 25.0,
            "max_detail_concurrency": 5,
        },
        "settings_note": "Discovery follows ACBAR pagination until the site returns its real end. A listing-page or detail-page limit is applied only when explicitly configured and makes the scan partial.",
    },
    "reliefweb": {
        "id": "reliefweb",
        "name": "ReliefWeb",
        "display_name": "ReliefWeb",
        "official_name": "ReliefWeb Afghanistan jobs",
        "tier": "B",
        "fetcher": "discover_reliefweb_jobs",
        "active": True,
        "official_url": "https://reliefweb.int/jobs?search=Afghanistan%20health%20medical%20nutrition",
        "homepage_url": "https://reliefweb.int",
        "listing_url": "https://reliefweb.int/jobs?search=Afghanistan%20health%20medical%20nutrition",
        "host_aliases": ["reliefweb.int", "www.reliefweb.int"],
        "selectors": {
            "listing_links": ['a[href*="/job/"]'],
            "detail_title": "h1",
        },
        "provenance_labels": {
            "listing": "ReliefWeb listing",
            "detail": "ReliefWeb detail",
        },
        "defaults": {
            "timeout_seconds": 25.0,
            "limit": 20,
        },
    },
}


# ---------------------------------------------------------------------------
# Legacy CV-import budget cleanup
#
# Before the full-market change, the registry's ACBAR ``defaults`` contained a
# bounded pagination budget (``max_pages: 6`` and ``detail_limit: 30``). The CV
# importer (utils/profile_builder) copied ``source_defaults()`` VERBATIM into
# the generated profile.yaml, so every profile created by a CV import during
# that era still carries those literal values under ``job_sources.acbar`` and
# every real scan keeps reading them as an "explicitly configured" cap.
#
# The budget keys are removed ONLY when the whole override block is provably
# the untouched builder artifact: it must contain exactly the full legacy
# default key set, each with exactly the legacy default value. Any deviation
# (a changed value, an added key, or a partial key set) marks the block as a
# genuine user configuration and it is preserved bit-for-bit.
# ---------------------------------------------------------------------------

LEGACY_BUILDER_OPERATIONAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "acbar": {"timeout_seconds": 25.0, "detail_limit": 30, "max_pages": 6, "max_detail_concurrency": 5},
    "reliefweb": {"timeout_seconds": 25.0, "limit": 20},
}

LEGACY_BUILDER_BUDGET_KEYS: dict[str, tuple[str, ...]] = {
    # Keys that cap real discovery. ``timeout_seconds``/``max_detail_concurrency``
    # still equal the registry defaults, so leaving them is harmless; the budget
    # keys are what silently capped live scans at 6 pages / 30 detail pages.
    "acbar": ("max_pages", "detail_limit"),
    "reliefweb": (),
}


def normalize_source_overrides(source_id: str, overrides: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a ``job_sources.<id>`` block into (effective, removed_legacy_budget).

    ``removed_legacy_budget`` is non-empty only when the block is untouched
    builder output from the bounded-defaults era (see note above). Callers use
    the effective block for the scan and may surface the removal note so the
    behavior change is never silent.
    """
    if not isinstance(overrides, dict):
        return {}, {}
    budget_keys = LEGACY_BUILDER_BUDGET_KEYS.get(source_id, ())
    legacy = LEGACY_BUILDER_OPERATIONAL_DEFAULTS.get(source_id, {})
    if not budget_keys or not overrides:
        return dict(overrides), {}
    is_verbatim_builder_block = (
        set(overrides) == set(legacy)
        and all(overrides[key] == legacy[key] for key in legacy)
    )
    if not is_verbatim_builder_block:
        return dict(overrides), {}
    removed = {key: overrides[key] for key in budget_keys if key in overrides}
    effective = {key: value for key, value in overrides.items() if key not in budget_keys}
    return effective, removed


def normalize_profile_source_budgets(profile: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove untouched builder-era discovery budgets from a loaded profile.

    Returns ``(profile, notes)``; ``notes`` is a list of human-readable lines
    (one per source) describing exactly which keys were ignored and how to set
    them deliberately. The profile mapping is cleaned in place and also
    returned for convenience.
    """
    job_sources = profile.get("job_sources") if isinstance(profile, dict) else None
    if not isinstance(job_sources, dict):
        return profile, []
    notes: list[str] = []
    for source_id in list(job_sources):
        effective, removed = normalize_source_overrides(source_id, job_sources[source_id])
        if removed:
            job_sources[source_id] = effective
            detail = ", ".join(f"{key}={value}" for key, value in removed.items())
            notes.append(
                f"Ignored legacy CV-import scan budget for {source_id} ({detail}) in profile.yaml. "
                "These values were copied in by an older CV import, not set deliberately. "
                "To cap a scan on purpose, set the key explicitly yourself (a capped scan is reported PARTIAL)."
            )
    return profile, notes


def source_ids() -> list[str]:
    return list(SOURCE_REGISTRY.keys())


def get_source_spec(source_id: str) -> dict[str, Any]:
    """Return a copy of the registered source specification.

    Callers receive a copy to avoid accidental runtime mutation of the global
    registry. Tests that intentionally monkeypatch ``utils.discovery.
    SOURCE_REGISTRY`` still work because discovery imports and exposes the
    registry object directly.
    """
    return deepcopy(SOURCE_REGISTRY[source_id])


def active_source_specs() -> dict[str, dict[str, Any]]:
    return {source_id: get_source_spec(source_id) for source_id, spec in SOURCE_REGISTRY.items() if spec.get("active")}


def source_display_name(spec_or_id: str | dict[str, Any]) -> str:
    if isinstance(spec_or_id, dict):
        spec = spec_or_id
    else:
        spec = SOURCE_REGISTRY.get(spec_or_id, {})
    return str(spec.get("display_name") or spec.get("name") or spec.get("official_name") or spec.get("id") or "").strip()


def source_official_url(spec_or_id: str | dict[str, Any]) -> str:
    if isinstance(spec_or_id, dict):
        spec = spec_or_id
    else:
        spec = SOURCE_REGISTRY.get(spec_or_id, {})
    return str(spec.get("official_url") or spec.get("listing_url") or spec.get("homepage_url") or "").strip()


def source_defaults(source_id: str) -> dict[str, Any]:
    spec = SOURCE_REGISTRY.get(source_id, {})
    defaults = spec.get("defaults") if isinstance(spec.get("defaults"), dict) else {}
    return deepcopy(defaults)


def canonical_source_name(value: Any) -> str:
    """Return the registry display name for a known source token.

    Unknown values are returned as cleaned text.  This keeps validation strict
    (unknown/empty source names are still rejected elsewhere) without hard-
    coding source-name normalization inside matching code.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    lower = text.lower()
    for source_id, spec in SOURCE_REGISTRY.items():
        names = {
            source_id.lower(),
            str(spec.get("name") or "").lower(),
            str(spec.get("display_name") or "").lower(),
            str(spec.get("official_name") or "").lower(),
        }
        if lower in names:
            return source_display_name(spec)
    return text


def source_registry_for_settings() -> list[dict[str, Any]]:
    return [
        {
            "id": source_id,
            "name": source_display_name(spec),
            "official_name": spec.get("official_name") or source_display_name(spec),
            "tier": spec.get("tier", ""),
            "active": bool(spec.get("active")),
            "official_url": source_official_url(spec),
        }
        for source_id, spec in SOURCE_REGISTRY.items()
    ]
