"""Afghanistan job source registry access layer.

The registry is the maintained list of places Jobs-Finder may use to discover
Afghanistan vacancies.  It is intentionally data-driven: the discovery
orchestrator asks this module which sources are active instead of scattering
source lists throughout the codebase.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "docs" / "source_registry.json"
ACTIVE_DISCOVERY_STATUSES = {"ACTIVE", "LIMITED"}
BLOCKING_ACCESS_STATUSES = {"BLOCKED", "INACCESSIBLE", "NOT_IMPLEMENTED"}

REQUIRED_FIELDS = {
    "id",
    "organization_name",
    "source_category",
    "country_coverage",
    "official_website",
    "official_jobs_url",
    "discovery_method",
    "source_type",
    "afghanistan_relevance",
    "health_medical_relevance",
    "public_accessibility",
    "login_required",
    "captcha_blocking_status",
    "application_url_availability",
    "provenance_level",
    "reliability_status",
    "last_checked",
    "limitations",
    "notes",
    "enabled_in_autonomous_discovery",
}

VALID_STATUSES = {"ACTIVE", "LIMITED", "BLOCKED", "INACCESSIBLE", "NOT_IMPLEMENTED"}
VALID_PROVENANCE = {"high", "medium", "low", "unknown"}
SUPPORTED_AUTONOMOUS_METHODS = {
    "acbar_html",
    "reliefweb_api_or_html",
    "unjobs_html",
    "unicef_careers_html",
    "registry_static_html",
    "official_career_page_static",
    "greenhouse_api",
    "lever_api",
    "jobspy_opt_in",
    "oracle_hcm_api",
}


def registry_enabled(profile: dict[str, Any] | None) -> bool:
    """Return True only when the profile explicitly enables the registry.

    Older tests/profiles without a ``source_registry`` block keep legacy source
    behavior.  ``profile.yaml.example`` enables the registry for normal use.
    """
    cfg = (profile or {}).get("source_registry")
    return isinstance(cfg, dict) and cfg.get("enabled", True) is not False


def registry_path_from_profile(profile: dict[str, Any] | None, path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    cfg = (profile or {}).get("source_registry") if isinstance(profile, dict) else None
    if isinstance(cfg, dict) and cfg.get("path"):
        configured = Path(str(cfg["path"]))
        return configured if configured.is_absolute() else Path.cwd() / configured
    return REGISTRY_PATH


def canonical_url(value: str | None) -> str:
    """Normalize URLs for duplicate detection without losing real stored URLs."""
    if not value:
        return ""
    value = str(value).strip()
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = re.sub(r"/+$", "", parsed.path or "")
        return f"{host}{path}".lower()
    except Exception:
        return re.sub(r"\s+", "", value.lower().removeprefix("www."))


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["id"] = str(normalized.get("id", "")).strip().lower().replace(" ", "_")
    normalized["reliability_status"] = str(normalized.get("reliability_status", "NOT_IMPLEMENTED")).upper()
    normalized["provenance_level"] = str(normalized.get("provenance_level", "unknown")).lower()
    normalized.setdefault("adapter_config", {})
    normalized.setdefault("tags", [])
    normalized.setdefault("last_check_result", "")
    normalized.setdefault("checked_by", "")
    normalized.setdefault("enabled_in_autonomous_discovery", False)
    normalized["enabled_in_autonomous_discovery"] = bool(normalized["enabled_in_autonomous_discovery"])
    return normalized


def load_source_registry(path: str | Path | None = None, *, profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry_path = registry_path_from_profile(profile, path)
    records = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Source registry must be a list: {registry_path}")
    return [_normalize_record(record) for record in records]


def validate_source_registry(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_urls: dict[str, str] = {}
    for index, raw in enumerate(records):
        record = _normalize_record(raw)
        prefix = f"record[{index}] {record.get('id') or '<missing id>'}"
        missing = sorted(REQUIRED_FIELDS - set(record))
        if missing:
            errors.append(f"{prefix}: missing required fields: {', '.join(missing)}")
        if not record.get("id"):
            errors.append(f"{prefix}: empty id")
        elif record["id"] in seen_ids:
            errors.append(f"{prefix}: duplicate id {record['id']}")
        seen_ids.add(record.get("id", ""))
        status = record.get("reliability_status")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix}: invalid reliability_status {status!r}")
        if record.get("provenance_level") not in VALID_PROVENANCE:
            errors.append(f"{prefix}: invalid provenance_level {record.get('provenance_level')!r}")
        if record.get("enabled_in_autonomous_discovery") and record.get("discovery_method") not in SUPPORTED_AUTONOMOUS_METHODS:
            errors.append(f"{prefix}: enabled source uses unsupported discovery_method {record.get('discovery_method')!r}")
        if record.get("enabled_in_autonomous_discovery") and status in BLOCKING_ACCESS_STATUSES:
            errors.append(f"{prefix}: blocked/inaccessible/not_implemented source cannot be enabled")
        url_key = canonical_url(record.get("official_jobs_url") or record.get("official_website"))
        if url_key:
            if url_key in seen_urls:
                errors.append(f"{prefix}: duplicate jobs URL with {seen_urls[url_key]}: {record.get('official_jobs_url')}")
            else:
                seen_urls[url_key] = record.get("id", prefix)
        if not record.get("last_checked") and str(record.get("last_check_result", "")).lower().startswith("checked"):
            errors.append(f"{prefix}: last_check_result claims a check but last_checked is empty")
    return errors


def deduplicate_registry_sources(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records with duplicate ids/jobs URLs removed, preserving order."""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for raw in records:
        record = _normalize_record(raw)
        url_key = canonical_url(record.get("official_jobs_url") or record.get("official_website"))
        if record["id"] in seen_ids or (url_key and url_key in seen_urls):
            continue
        seen_ids.add(record["id"])
        if url_key:
            seen_urls.add(url_key)
        unique.append(record)
    return unique


def _profile_disabled_ids(profile: dict[str, Any] | None) -> set[str]:
    cfg = (profile or {}).get("source_registry") if isinstance(profile, dict) else None
    disabled = cfg.get("disabled_source_ids", []) if isinstance(cfg, dict) else []
    return {str(item).strip().lower() for item in disabled}


def _profile_enabled_ids(profile: dict[str, Any] | None) -> set[str]:
    cfg = (profile or {}).get("source_registry") if isinstance(profile, dict) else None
    enabled = cfg.get("enabled_source_ids", []) if isinstance(cfg, dict) else []
    return {str(item).strip().lower() for item in enabled}


def _legacy_source_enabled(profile: dict[str, Any] | None, record: dict[str, Any]) -> bool:
    sources = (profile or {}).get("job_sources", {}) if isinstance(profile, dict) else {}
    if not isinstance(sources, dict):
        return True
    legacy_key = record.get("adapter_config", {}).get("legacy_key") or record.get("id")
    configured = sources.get(legacy_key)
    if isinstance(configured, dict) and configured.get("enabled") is False:
        return False
    return True


def is_record_active(record: dict[str, Any], profile: dict[str, Any] | None = None) -> bool:
    record = _normalize_record(record)
    enabled_ids = _profile_enabled_ids(profile)
    if enabled_ids and record["id"] not in enabled_ids:
        return False
    if record["id"] in _profile_disabled_ids(profile):
        return False
    if not record.get("enabled_in_autonomous_discovery"):
        return False
    if record.get("reliability_status") not in ACTIVE_DISCOVERY_STATUSES:
        return False
    if record.get("public_accessibility") in {"blocked", "inaccessible", "login_required_for_listing"}:
        return False
    if str(record.get("captcha_blocking_status", "")).lower() in {"blocking", "captcha_blocked", "blocked"}:
        return False
    if not _legacy_source_enabled(profile, record):
        return False
    return True


def active_sources_for_discovery(profile: dict[str, Any] | None, records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not registry_enabled(profile):
        return []
    records = records if records is not None else load_source_registry(profile=profile)
    return [record for record in deduplicate_registry_sources(records) if is_record_active(record, profile)]


def group_active_sources_by_method(profile: dict[str, Any] | None, records: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in active_sources_for_discovery(profile, records):
        grouped.setdefault(record["discovery_method"], []).append(record)
    return grouped


def registry_enhanced_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a profile copy with active registry sources mapped to runtime config."""
    if not registry_enabled(profile):
        return profile

    enhanced = copy.deepcopy(profile)
    job_sources = enhanced.setdefault("job_sources", {})
    active = active_sources_for_discovery(enhanced)
    grouped = group_active_sources_by_method(enhanced, active)
    job_sources["_source_registry_enabled"] = True
    job_sources["_source_registry_active_ids"] = [record["id"] for record in active]
    job_sources["_source_registry_active_methods"] = sorted(grouped)

    def merge_source_config(key: str, record: dict[str, Any]) -> None:
        current = job_sources.get(key) if isinstance(job_sources.get(key), dict) else {}
        merged = {"enabled": True, **record.get("adapter_config", {}), **current}
        # If a legacy profile explicitly disabled the source, preserve that.
        if isinstance(current, dict) and current.get("enabled") is False:
            merged["enabled"] = False
        job_sources[key] = merged

    for record in active:
        method = record["discovery_method"]
        if method == "acbar_html":
            merge_source_config("acbar", record)
        elif method == "reliefweb_api_or_html":
            merge_source_config("reliefweb", record)
        elif method == "unjobs_html":
            merge_source_config("unjobs", record)
        elif method == "unicef_careers_html":
            merge_source_config("unicef", record)
        elif method in {"registry_static_html", "official_career_page_static"}:
            job_sources.setdefault("registry_static_sources", []).append(record)
        elif method == "greenhouse_api":
            slugs = record.get("adapter_config", {}).get("slugs", [])
            job_sources.setdefault("ats", {}).setdefault("greenhouse", [])
            for slug in slugs:
                if slug not in job_sources["ats"]["greenhouse"]:
                    job_sources["ats"]["greenhouse"].append(slug)
        elif method == "lever_api":
            slugs = record.get("adapter_config", {}).get("slugs", [])
            job_sources.setdefault("ats", {}).setdefault("lever", [])
            for slug in slugs:
                if slug not in job_sources["ats"]["lever"]:
                    job_sources["ats"]["lever"].append(slug)
        elif method == "oracle_hcm_api":
            job_sources.setdefault("oracle_hcm_sources", []).append(record)
    return enhanced


def registry_status_counts(records: list[dict[str, Any]] | None = None) -> dict[str, int]:
    records = records if records is not None else load_source_registry()
    counts = {status: 0 for status in sorted(VALID_STATUSES)}
    for record in records:
        status = _normalize_record(record).get("reliability_status", "NOT_IMPLEMENTED")
        counts[status] = counts.get(status, 0) + 1
    return counts


def registry_as_inventory(records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Project the maintained registry into the older source_inventory shape."""
    records = records if records is not None else load_source_registry()
    inventory: list[dict[str, Any]] = []
    for record in records:
        record = _normalize_record(record)
        inventory.append(
            {
                "source_name": record["organization_name"],
                "source_type": record["source_type"],
                "url_or_domain": record.get("official_jobs_url") or record.get("official_website"),
                "country_market_relevance": record["afghanistan_relevance"],
                "health_medical_relevance": record["health_medical_relevance"],
                "discovery_method": record["discovery_method"],
                "implementation_status": record["reliability_status"].lower(),
                "login_required": record["login_required"],
                "captcha_blocks_access": str(record["captcha_blocking_status"]).lower() in {"blocking", "captcha_blocked", "blocked"},
                "public_job_content_accessible": record["public_accessibility"] not in {"blocked", "inaccessible", "login_required_for_listing"},
                "application_url_can_be_extracted": record["application_url_availability"] in {"yes", "partial"},
                "reliability_provenance_level": record["provenance_level"],
                "last_successful_discovery_test": record.get("last_check_result") or "Not checked",
                "notes_limitations": record.get("limitations", ""),
            }
        )
    return inventory
