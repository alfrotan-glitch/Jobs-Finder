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
        "settings_note": "Discovery follows ACBAR pagination until the site returns its real end and processes every relevant detail page with bounded concurrency.",
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
    raw_defaults = spec.get("defaults")
    defaults: dict[str, Any] = raw_defaults if isinstance(raw_defaults, dict) else {}
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
