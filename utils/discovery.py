"""Small Afghanistan-first discovery pipeline.

The product has one discovery path:
fetch a small set of maintained Afghanistan-relevant sources, normalize their
vacancies, deduplicate, extract useful requirements, and return a scan status
that never confuses technical failure with an empty market.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from utils.medical_requirements import (
    AFGHAN_PROVINCES,
    analyze_professional_role,
    canonical_source_fields,
    extract_requirements_from_job,
    has_actionable_source,
    looks_medical,
    parse_closing_date,
    strip_html,
)
from utils.recommendations import collect_scan_recommendations, iter_match_pairs
from utils.source_registry import (
    SOURCE_REGISTRY,
    source_defaults,
    source_display_name,
    source_official_url,
)

SCAN_COMPLETE = "SCAN_COMPLETE"
NO_RELEVANT_JOBS_FOUND = "NO_RELEVANT_JOBS_FOUND"
PARTIAL_SCAN = "PARTIAL_SCAN"
SOURCES_UNAVAILABLE = "SOURCES_UNAVAILABLE"
SCAN_FAILED = "SCAN_FAILED"

DEFAULT_USER_AGENT = "Jobs-Finder Afghanistan Job Assistant (+manual, non-automated applications)"

# ACBAR is discovered to the source's observable end by default. Limits are
# opt-in operational safeguards, never normal completion criteria: when a user
# configures one, the source report is explicitly PARTIAL.
_ACBAR_DEFAULTS = source_defaults("acbar")
_RELIEFWEB_DEFAULTS = source_defaults("reliefweb")
ACBAR_DEFAULT_DETAIL_CONCURRENCY = int(_ACBAR_DEFAULTS.get("max_detail_concurrency", 5))
ACBAR_DEFAULT_TIMEOUT_SECONDS = float(_ACBAR_DEFAULTS.get("timeout_seconds", 25.0))
RELIEFWEB_DEFAULT_LIMIT = int(_RELIEFWEB_DEFAULTS.get("limit", 20))
RELIEFWEB_DEFAULT_TIMEOUT_SECONDS = float(_RELIEFWEB_DEFAULTS.get("timeout_seconds", 25.0))

@dataclass(slots=True)
class Job:
    id: str
    title: str
    company: str
    location: str
    url: str
    apply_url: str | None
    platform: str
    description: str = ""
    department: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source_name: str = ""
    source_url: str = ""
    vacancy_url: str = ""
    application_method: str = ""
    apply_email: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SOURCE_STATUS_SCANNED = "SCANNED"
SOURCE_STATUS_PARTIAL = "PARTIAL"
SOURCE_STATUS_UNAVAILABLE = "UNAVAILABLE"
SOURCE_STATUS_FAILED = "FAILED"


@dataclass(slots=True)
class SourceScanMetrics:
    """Authoritative source accounting.

    ``listings_seen`` counts raw cards on successful listing pages. A card has
    exactly one terminal outcome: parse failure, budget deferral, one canonical
    exclusion, or retention. ``vacancies_parsed`` counts valid minimum vacancy
    objects that entered the canonical exclusion pipeline; detail success is
    deliberately reported separately.
    """

    source_url: str = ""
    official_source_id: str = ""
    # The total published by the source (when present) is retained as a
    # discovery-completeness cross-check, not used to fabricate listings.
    source_listings_reported: int | None = None
    status: str = SOURCE_STATUS_UNAVAILABLE
    pages_requested: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    pagination_stop_reason: str = "UNKNOWN"
    listings_seen: int = 0
    listing_parse_failures: int = 0
    vacancies_parsed: int = 0
    not_processed_due_to_budget: int = 0
    detail_pages_attempted: int = 0
    detail_pages_succeeded: int = 0
    detail_pages_failed: int = 0
    listing_fallback_used: int = 0
    duplicates_removed: int = 0
    expired_excluded: int = 0
    irrelevant_excluded: int = 0
    incompatible_role_classification_excluded: int = 0
    source_validation_excluded: int = 0
    relevant_retained: int = 0
    application_routes_found: int = 0
    application_routes_unavailable: int = 0
    partial_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["partial"] = self.status == SOURCE_STATUS_PARTIAL
        return data

    def add_partial_reason(self, reason: str, error: str = "") -> None:
        if reason and reason not in self.partial_reasons:
            self.partial_reasons.append(reason)
        if error and error not in self.errors:
            self.errors.append(error)


@dataclass(slots=True)
class SourceReport:
    id: str
    name: str
    tier: str
    attempted: bool = False
    ok: bool = False
    error: str = ""
    timestamp: str = ""
    started_at: str = ""
    finished_at: str = ""
    source_url: str = ""
    official_source_id: str = ""
    # The total published by the source (when present) is retained as a
    # discovery-completeness cross-check, not used to fabricate listings.
    source_listings_reported: int | None = None
    status: str = SOURCE_STATUS_UNAVAILABLE
    pages_requested: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    pagination_stop_reason: str = "UNKNOWN"
    listings_seen: int = 0
    listing_parse_failures: int = 0
    vacancies_parsed: int = 0
    not_processed_due_to_budget: int = 0
    detail_pages_attempted: int = 0
    detail_pages_succeeded: int = 0
    detail_pages_failed: int = 0
    listing_fallback_used: int = 0
    duplicates_removed: int = 0
    expired_excluded: int = 0
    irrelevant_excluded: int = 0
    incompatible_role_classification_excluded: int = 0
    source_validation_excluded: int = 0
    relevant_retained: int = 0
    application_routes_found: int = 0
    application_routes_unavailable: int = 0
    partial_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def apply_metrics(self, metrics: SourceScanMetrics | dict[str, Any] | None) -> None:
        if not metrics:
            return
        data = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
        for key, value in data.items():
            if key in self.__dataclass_fields__:
                setattr(self, key, value)
        if self.errors and not self.error:
            self.error = "; ".join(self.errors[:2])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SUMMARY_COUNTERS = (
    "pages_requested", "pages_succeeded", "pages_failed", "listings_seen",
    "listing_parse_failures", "vacancies_parsed", "not_processed_due_to_budget",
    "duplicates_removed", "expired_excluded", "irrelevant_excluded",
    "incompatible_role_classification_excluded", "source_validation_excluded",
    "relevant_retained", "application_routes_found", "application_routes_unavailable",
)


@dataclass(slots=True)
class ScanResult:
    status: str
    jobs: list[Job]
    source_reports: list[SourceReport]
    started_at: str
    finished_at: str
    message: str
    recommended_from_scan: int = 0
    ready_to_apply_from_scan: int = 0
    needs_verification_from_scan: int = 0
    not_eligible_from_scan: int = 0
    # The single authoritative recommendation collection for this scan. The
    # summary count, the CLI list, the dashboard view, and persisted scan
    # activity are all derived from THIS list (utils/recommendations.py), so
    # recommended_from_scan == len(recommendations) holds by construction.
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def successful_sources(self) -> int:
        return sum(1 for report in self.source_reports if report.ok)

    @property
    def failed_sources(self) -> int:
        return sum(1 for report in self.source_reports if report.attempted and not report.ok)

    def record_match_results(self, results: list[Any]) -> None:
        """Attach matcher outcomes for only the jobs retained by this scan.

        ``results`` must be (job, match) pairs. Readiness counters count every
        retained job, while ``recommendations`` is built once by the shared
        recommendation authority (utils/recommendations.py): readiness in
        {READY_TO_APPLY, NEEDS_VERIFICATION} AND a positively compatible
        professional-role classification. ``recommended_from_scan`` is exactly
        ``len(self.recommendations)`` — the same collection that is printed by
        the CLI, served to the dashboard, and persisted with scan activity.
        """
        pairs = iter_match_pairs(results)
        statuses = [str(match.get("readiness_status") or "") for _, match in pairs]
        self.ready_to_apply_from_scan = statuses.count("READY_TO_APPLY")
        self.needs_verification_from_scan = statuses.count("NEEDS_VERIFICATION")
        self.not_eligible_from_scan = statuses.count("NOT_ELIGIBLE")
        self.recommendations = collect_scan_recommendations(pairs)
        self.recommended_from_scan = len(self.recommendations)

    def summary(self) -> dict[str, int]:
        data = {key: sum(int(getattr(r, key, 0) or 0) for r in self.source_reports) for key in SUMMARY_COUNTERS}
        data.update({
            "sources_attempted": sum(1 for r in self.source_reports if r.attempted),
            "sources_scanned": sum(1 for r in self.source_reports if r.status == SOURCE_STATUS_SCANNED),
            "sources_partial": sum(1 for r in self.source_reports if r.status == SOURCE_STATUS_PARTIAL),
            "sources_unavailable": sum(1 for r in self.source_reports if r.status == SOURCE_STATUS_UNAVAILABLE),
            "sources_failed": sum(1 for r in self.source_reports if r.status == SOURCE_STATUS_FAILED),
            "recommended_from_scan": self.recommended_from_scan,
            "ready_to_apply_from_scan": self.ready_to_apply_from_scan,
            "needs_verification_from_scan": self.needs_verification_from_scan,
            "not_eligible_from_scan": self.not_eligible_from_scan,
        })
        return data

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "message": self.message,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "jobs": [job.to_dict() for job in self.jobs],
            "source_reports": [report.to_dict() for report in self.source_reports],
            "successful_sources": self.successful_sources,
            "failed_sources": self.failed_sources, "job_count": len(self.jobs),
            # Persisted verbatim so scan activity and the dashboard render the
            # exact collection the summary counted — no recomputation.
            "recommendations": self.recommendations,
            "summary": self.summary(),
        }


class SourceJobs(list[Job]):
    """Fetcher result retaining parsed counts and source scan metrics."""

    def __init__(self, jobs: list[Job], *, parsed_count: int | None = None, metrics: SourceScanMetrics | None = None):
        super().__init__(jobs)
        self.parsed_count = len(jobs) if parsed_count is None else parsed_count
        self.metrics = metrics


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_job_id(source: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{source}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return normalize_space(value)


def is_expired(job: Job | dict[str, Any], *, today: date | None = None) -> bool:
    today = today or date.today()
    data = job if isinstance(job, dict) else job.to_dict()
    metadata = data.get("metadata") or {}
    closing = metadata.get("closing_date") or data.get("closing_date")
    if not closing:
        return False
    try:
        return date.fromisoformat(str(closing)[:10]) < today
    except ValueError:
        return False


def deduplicate_jobs_with_stats(jobs: list[Job], *, today: date | None = None) -> tuple[list[Job], dict[str, dict[str, int]]]:
    """Deduplicate/open-filter jobs and return per-source exclusion counts."""
    seen: set[str] = set()
    out: list[Job] = []
    stats: dict[str, dict[str, int]] = {}

    def inc(source_id: str, key: str) -> None:
        bucket = stats.setdefault(str(source_id or "").lower(), {"duplicates_removed": 0, "expired_stale_excluded": 0})
        bucket[key] = bucket.get(key, 0) + 1

    for job in jobs:
        source_id = str((job.metadata or {}).get("_scan_source_id") or job.platform or "").lower()
        if is_expired(job, today=today):
            inc(source_id, "expired_stale_excluded")
            continue
        key = _canonical(job.url or job.apply_url or "") or _canonical(f"{job.title} {job.company} {job.location}")
        if not key or key in seen:
            inc(source_id, "duplicates_removed")
            continue
        seen.add(key)
        out.append(job)
    return out, stats


def deduplicate_jobs(jobs: list[Job], *, today: date | None = None) -> list[Job]:
    return deduplicate_jobs_with_stats(jobs, today=today)[0]


def enrich_job(job: Job, *, today: date | None = None) -> Job:
    job.metadata = dict(job.metadata or {})
    job.metadata.setdefault("source", job.platform)
    job.metadata.setdefault("source_name", job.metadata.get("source") or job.platform)
    job.metadata.setdefault("vacancy_url", job.url)
    # Keep source provenance separate from vacancy/application routes. A
    # vacancy page must never become a fabricated replacement source URL.
    job.metadata.setdefault("source_urls", [url for url in [job.metadata.get("source_url")] if url])
    if not job.metadata.get("closing_date"):
        parsed = parse_closing_date("\n".join([job.title, job.location, job.description, str(job.metadata)]))
        if parsed:
            job.metadata["closing_date"] = parsed
    requirements = extract_requirements_from_job(job.to_dict(), today=today)
    facts = requirements.facts
    for key in ["closing_date", "application_email", "application_url", "application_subject", "reference_number"]:
        if facts.get(key) and not job.metadata.get(key):
            job.metadata[key] = facts[key]
    source = canonical_source_fields(job.to_dict())
    job.source_name = str(source.get("source_name") or "")
    job.source_url = str(source.get("source_url") or "")
    job.vacancy_url = str(source.get("vacancy_url") or job.url or "")
    job.apply_url = str(source.get("apply_url")) if source.get("apply_url") else None
    job.apply_email = str(source.get("apply_email") or "")
    job.application_method = str(source.get("application_method") or "UNAVAILABLE")
    if job.vacancy_url:
        job.url = job.vacancy_url
    job.metadata.update(
        {
            "source_name": job.source_name,
            "source_url": job.source_url,
            "vacancy_url": job.vacancy_url,
            "apply_url": job.apply_url or None,
            "apply_email": job.apply_email,
            "application_method": job.application_method,
            "source_valid": source.get("source_valid"),
            "source_problems": source.get("problems") or [],
            "requirements": requirements.to_dict(),
        }
    )
    return job


def _enabled_sources(profile: dict[str, Any]) -> list[str]:
    config = profile.get("sources", {}) if isinstance(profile.get("sources"), dict) else {}
    enabled = config.get("enabled")
    disabled = set(config.get("disabled") or [])
    if enabled:
        return [source for source in enabled if source in SOURCE_REGISTRY and source not in disabled]
    return [source for source, spec in SOURCE_REGISTRY.items() if spec.get("active") and source not in disabled]


def _concise_error(exc: BaseException | str) -> str:
    text = str(exc or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:240] if text else "Source unavailable."


def _new_source_report(source_id: str, spec: dict[str, Any]) -> SourceReport:
    display = source_display_name(spec) or str(spec.get("name") or source_id)
    url = source_official_url(spec)
    return SourceReport(
        id=source_id,
        name=display,
        tier=str(spec.get("tier") or ""),
        attempted=True,
        timestamp=utc_now(),
        started_at=utc_now(),
        source_url=url,
        official_source_id=str(spec.get("official_name") or display or source_id),
    )


def _role_classification(job: Job) -> str:
    requirements = (job.metadata or {}).get("requirements") or {}
    facts = requirements.get("facts") if isinstance(requirements, dict) else {}
    role = (facts or {}).get("role_analysis") if isinstance(facts, dict) else None
    if isinstance(role, dict) and role.get("classification"):
        return str(role.get("classification") or "")
    return str(analyze_professional_role(job.title, job.description).get("classification") or "")


async def run_discovery_scan(profile: dict[str, Any] | None = None, *, today: date | None = None) -> ScanResult:
    """Run adapters then apply the one mutually-exclusive terminal lifecycle.

    Precedence is deliberately fixed: duplicate, expired, irrelevant,
    incompatible role classification, source validation, retained. Once an
    item enters a terminal bucket it is never evaluated for a later bucket.
    Operational budget deferrals happen in adapters and never masquerade as a
    semantic exclusion.
    """
    profile = profile or {}
    today = today or date.today()
    started = utc_now()
    reports: list[SourceReport] = []
    candidates: list[Job] = []
    enabled = _enabled_sources(profile)
    if not enabled:
        return ScanResult(SCAN_FAILED, [], [], started, utc_now(), "No active discovery sources are enabled.")

    for source_id in enabled:
        spec = SOURCE_REGISTRY[source_id]
        report = _new_source_report(source_id, spec)
        try:
            fetcher = globals()[spec["fetcher"]]
            try:
                found = await fetcher(profile, today=today)
            except TypeError:
                found = await fetcher(profile)
            metrics = getattr(found, "metrics", None)
            report.ok = True
            if metrics:
                report.apply_metrics(metrics)
                report.ok = report.status not in {SOURCE_STATUS_UNAVAILABLE, SOURCE_STATUS_FAILED}
            else:
                # A fetcher that reports no metrics: each returned item is one
                # encountered listing and malformed items are counted explicitly.
                report.listings_seen = len(found)
                report.listing_parse_failures = sum(not isinstance(item, Job) for item in found)
                report.vacancies_parsed = report.listings_seen - report.listing_parse_failures
                report.pagination_stop_reason = "END_REACHED"
                report.status = SOURCE_STATUS_SCANNED
            for item in found:
                if isinstance(item, Job):
                    item.metadata = dict(item.metadata or {})
                    item.metadata["_scan_source_id"] = source_id
                    candidates.append(item)
        except Exception as exc:  # complete source isolation remains mandatory
            reason = _concise_error(exc)
            report.ok = False
            report.status = SOURCE_STATUS_UNAVAILABLE
            report.pagination_stop_reason = "REQUEST_FAILED"
            report.error = reason
            report.errors.append(reason)
        report.finished_at = utc_now()
        reports.append(report)

    by_source = {r.id.lower(): r for r in reports}
    retained: list[Job] = []
    seen: set[str] = set()
    for job in candidates:
        source_id = str((job.metadata or {}).get("_scan_source_id") or job.platform or "").lower()
        report_for_job = by_source.get(source_id)
        if not report_for_job:
            continue
        try:
            # Canonical terminal precedence starts here. Cross-source identity
            # uses the normalized official vacancy URL where possible.
            key = _vacancy_identity(job.url or job.apply_url or "") or _canonical(f"{job.title} {job.company} {job.location}")
            if not key or key in seen:
                report_for_job.duplicates_removed += 1
                # An adapter may have earmarked an item for a detail budget,
                # but cross-source canonical deduplication wins the lifecycle
                # precedence; do not count one listing in two terminal buckets.
                if (job.metadata or {}).get("deferred_due_to_budget"):
                    report_for_job.not_processed_due_to_budget = max(0, report_for_job.not_processed_due_to_budget - 1)
                continue
            seen.add(key)
            if is_expired(job, today=today):
                report_for_job.expired_excluded += 1
                # Expiry is a higher-priority terminal result than an adapter's
                # planned detail deferral, so preserve one-outcome accounting.
                if (job.metadata or {}).get("deferred_due_to_budget"):
                    report_for_job.not_processed_due_to_budget = max(0, report_for_job.not_processed_due_to_budget - 1)
                continue
            if (job.metadata or {}).get("deferred_due_to_budget"):
                # It was discovered and parsed, but an explicitly configured
                # detail cap stopped verification. It is not treated as an
                # irrelevant vacancy or a recommendation.
                continue
            if not _job_is_relevant(job):
                report_for_job.irrelevant_excluded += 1
                continue
            enriched = enrich_job(job, today=today)
            if _role_classification(enriched) == "incompatible_professional_role":
                report_for_job.incompatible_role_classification_excluded += 1
                continue
            if not has_actionable_source(enriched.to_dict()):
                report_for_job.source_validation_excluded += 1
                continue
            retained.append(enriched)
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            # This is a parse failure rather than an invented semantic outcome.
            report_for_job.listing_parse_failures += 1
            report_for_job.vacancies_parsed = max(0, report_for_job.vacancies_parsed - 1)
            if "LISTING_PARSE_FAILURE" not in report_for_job.partial_reasons:
                report_for_job.partial_reasons.append("LISTING_PARSE_FAILURE")
            report_for_job.errors.append(f"Vacancy parse skipped: {_concise_error(exc)}")

    for report in reports:
        source_jobs = [job for job in retained if str((job.metadata or {}).get("_scan_source_id") or job.platform).lower() == report.id.lower()]
        report.relevant_retained = len(source_jobs)
        report.application_routes_found = sum(job.application_method in {"EMAIL", "WEB"} for job in source_jobs)
        report.application_routes_unavailable = report.relevant_retained - report.application_routes_found
        # Every parsed item must have exactly one semantic terminal outcome.
        terminal = (report.duplicates_removed + report.expired_excluded + report.not_processed_due_to_budget
                    + report.irrelevant_excluded + report.incompatible_role_classification_excluded
                    + report.source_validation_excluded + report.relevant_retained)
        if terminal != report.vacancies_parsed:
            report.errors.append(f"Accounting invariant failed: {report.vacancies_parsed} parsed != {terminal} terminal outcomes.")
            if "LISTING_PARSE_FAILURE" not in report.partial_reasons:
                report.partial_reasons.append("LISTING_PARSE_FAILURE")
        if report.ok:
            report.status = SOURCE_STATUS_PARTIAL if report.partial_reasons else SOURCE_STATUS_SCANNED
        if report.errors and not report.error:
            report.error = "; ".join(dict.fromkeys(report.errors[:2]))

    successful = sum(r.ok for r in reports)
    unavailable = sum(r.status in {SOURCE_STATUS_UNAVAILABLE, SOURCE_STATUS_FAILED} for r in reports)
    partial = sum(r.status == SOURCE_STATUS_PARTIAL for r in reports)
    if successful == 0:
        status, message = SOURCES_UNAVAILABLE, "Live scan incomplete. Job sources could not be reached."
    elif unavailable or partial:
        status = PARTIAL_SCAN
        message = f"Partial market scan. {len(retained)} relevant current vacancies retained; {unavailable + partial} source(s) unavailable or partial."
    elif not retained:
        status, message = NO_RELEVANT_JOBS_FOUND, "Scan completed. No relevant current vacancies were found in the reachable sources."
    else:
        status, message = SCAN_COMPLETE, f"Scan completed. {len(retained)} relevant current vacancies found."
    return ScanResult(status, retained, reports, started, utc_now(), message)


def _job_is_relevant(job: Job) -> bool:
    text = "\n".join([job.title, job.company, job.location, job.description])
    role = analyze_professional_role(job.title, job.description)
    if role.get("classification") in {"md_physician_role", "health_public_health_compatible", "incompatible_professional_role"}:
        return True
    # A bare word such as "health", "nutrition", "medical", or "hospital" is
    # not enough. Keep only strong medical/public-health terms that identify an
    # actual role family or credential for downstream deterministic matching.
    lower = text.lower()
    strong_terms = [
        "medical officer",
        "medical doctor",
        "physician",
        "public health",
        "health and nutrition",
        "hmis",
        "therapeutic feeding",
        "tfu",
        "imam",
        "cmam",
        "clinical supervisor",
    ]
    return any(term in lower for term in strong_terms) or looks_medical(job.title)


def _source_overrides(profile: dict[str, Any], source_id: str) -> dict[str, Any]:
    """Return the explicit ``job_sources.<id>`` block for a scan."""
    raw = (profile.get("job_sources") or {}) if isinstance(profile, dict) else {}
    cfg = raw.get(source_id) if isinstance(raw, dict) else {}
    if not cfg:  # missing, null, "", false, [] — no overrides
        return {}
    if not isinstance(cfg, dict):
        raise ValueError(f"job_sources.{source_id} must be a mapping")
    return dict(cfg)


def _validate_source_keys(config: dict[str, Any], source_id: str, allowed: set[str]) -> None:
    """Reject non-canonical source settings instead of interpreting them."""
    unknown = sorted(key for key in config if key not in allowed)
    if unknown:
        joined = ", ".join(f"job_sources.{source_id}.{key}" for key in unknown)
        raise ValueError(f"Unsupported source setting(s): {joined}")


def _configured_positive_int(config: dict[str, Any], source_id: str, key: str, default: int) -> int:
    value = config.get(key, default)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"job_sources.{source_id}.{key} must be a positive integer") from exc
    if result < 1:
        raise ValueError(f"job_sources.{source_id}.{key} must be a positive integer")
    return result


def _acbar_page_url(base: str, page_number: int) -> str:
    """Set (rather than append) ACBAR's page parameter while preserving filters."""
    parsed = urlparse(base)
    pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "page"]
    if page_number > 1:
        pairs.append(("page", str(page_number)))
    query = urlencode(pairs)
    return urlunparse(parsed._replace(query=query))


def _acbar_reported_listing_count(html: str) -> int | None:
    """Read ACBAR's visible aggregate count, e.g. ``234 jobs found``."""
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    match = re.search(r"\b([\d,]+)\s+jobs?\s+found\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - guarded by the regex
        return None


def _acbar_listing_anchors(soup: BeautifulSoup) -> list[Any]:
    """One listing-title anchor per card; secondary 'More locations' links do not count."""
    spec = SOURCE_REGISTRY.get("acbar", {})
    selector = ", ".join((spec.get("selectors") or {}).get("listing_links") or ['a[href*="/en/jobs/details/"]', 'a[href^="/jobs/"]'])
    path_pattern = ((spec.get("path_patterns") or {}).get("listing_path") or r"(?:/en/jobs/details/\d+(?:/[^/]+)?|/jobs/\d+/[^/]+\.jsp)$")
    anchors: list[Any] = []
    for anchor in soup.select(selector):
        href = str(anchor.get("href") or "")
        title = normalize_space(anchor.get_text(" ", strip=True))
        if not href or not re.search(path_pattern, urlparse(href).path, flags=re.IGNORECASE):
            continue
        if title.lower() in {"more locations", "view all jobs"}:
            continue
        anchors.append(anchor)
    return anchors


def _acbar_listing_is_clearly_irrelevant(job: Job) -> bool:
    """Avoid detail requests only for unambiguously non-health role families.

    Unknown and programme/operations titles intentionally return ``False`` and
    are enriched. This conservative policy costs requests, but prevents an
    optimisation from hiding a medical/public-health vacancy behind a terse
    listing card.
    """
    title = normalize_space(job.title).lower()
    health_signals = (
        "medical", "doctor", "physician", "nurse", "midwi", "health", "nutrition",
        "clinical", "hospital", "pharma", "therap", "psych", "mental", "watsan",
        "hygiene", "epidemi", "laboratory", "lab ", "surgeon", "dent", "disability",
        "protection", "case worker", "community", "social worker",
    )
    if any(signal in title for signal in health_signals):
        return False
    non_health_terms = (
        "account", "finance", "audit", "cashier", "bank", "it ", "information technology",
        "software", "developer", "network", "system administrator", "help desk", "graphic",
        "designer", "marketing", "sales", "business development", "driver", "guard", "security",
        "cleaner", "storekeeper", "logistics", "procurement", "supply chain", "warehouse",
        "engineer", "electric", "architect", "lawyer", "legal", "translator", "journalist",
        "communications", "media", "teacher", "instructor", "lecturer", "professor",
    )
    return any(term in title for term in non_health_terms)


async def discover_acbar_jobs(profile: dict[str, Any], *, today: date | None = None) -> list[Job]:
    """Discover all ACBAR listing pages, then enrich only plausible candidates.

    Stage 1 has no page ceiling: it requests ``?page=N`` until ACBAR returns
    a page with no listing cards. Stage 2 preserves every discovered listing
    but opens detail pages only for titles that are not clearly outside
    health/medical work.
    """
    spec = SOURCE_REGISTRY["acbar"]
    defaults = spec.get("defaults") or {}
    cfg = _source_overrides(profile, "acbar")
    _validate_source_keys(cfg, "acbar", {"timeout_seconds", "max_detail_concurrency", "urls"})
    explicit_urls = cfg.get("urls")
    if explicit_urls is not None and (not isinstance(explicit_urls, list) or not all(isinstance(url, str) and url.strip() for url in explicit_urls)):
        raise ValueError("job_sources.acbar.urls must be a list of non-empty URLs")
    timeout = float(cfg.get("timeout_seconds", defaults.get("timeout_seconds", ACBAR_DEFAULT_TIMEOUT_SECONDS)))
    concurrency = _configured_positive_int(cfg, "acbar", "max_detail_concurrency", int(defaults.get("max_detail_concurrency", ACBAR_DEFAULT_DETAIL_CONCURRENCY)))
    base = str(spec.get("listing_url") or spec.get("official_url") or "")
    metrics = SourceScanMetrics(
        source_url=base,
        official_source_id=str(spec.get("official_name") or source_display_name(spec)),
    )
    summaries: list[Job] = []
    seen_page_identities: set[str] = set()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        if explicit_urls:
            listing_urls = [str(url).strip() for url in explicit_urls]
            for url in listing_urls:
                metrics.pages_requested += 1
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    metrics.pages_succeeded += 1
                except Exception as exc:
                    metrics.pages_failed += 1
                    metrics.pagination_stop_reason = "REQUEST_FAILED"
                    metrics.add_partial_reason("LISTING_PAGE_FAILURE", f"Listing page could not be read: {_concise_error(exc)}")
                    metrics.add_partial_reason("REQUEST_FAILURE")
                    break
                reported = _acbar_reported_listing_count(response.text)
                if reported is not None:
                    metrics.source_listings_reported = reported
                soup = BeautifulSoup(response.text or "", "html.parser")
                raw_count = len(_acbar_listing_anchors(soup))
                page_jobs = _parse_acbar_listing(response.text, url)
                metrics.listings_seen += raw_count
                metrics.listing_parse_failures += max(0, raw_count - len(page_jobs))
                summaries.extend(page_jobs)
            else:
                metrics.pagination_stop_reason = "EXPLICIT_URL_SET_COMPLETE"
                metrics.add_partial_reason("EXPLICIT_URL_SCOPE")
        else:
            page_number = 1
            while True:
                url = _acbar_page_url(base, page_number)
                metrics.pages_requested += 1
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    metrics.pages_succeeded += 1
                except Exception as exc:
                    metrics.pages_failed += 1
                    metrics.pagination_stop_reason = "REQUEST_FAILED"
                    metrics.add_partial_reason("LISTING_PAGE_FAILURE", f"Listing page could not be read: {_concise_error(exc)}")
                    metrics.add_partial_reason("REQUEST_FAILURE")
                    break
                reported = _acbar_reported_listing_count(response.text)
                if reported is not None:
                    if metrics.source_listings_reported not in (None, reported):
                        metrics.add_partial_reason("SOURCE_COUNT_CHANGED_DURING_SCAN")
                    metrics.source_listings_reported = reported
                soup = BeautifulSoup(response.text or "", "html.parser")
                raw_count = len(_acbar_listing_anchors(soup))
                page_jobs = _parse_acbar_listing(response.text, url)
                metrics.listings_seen += raw_count
                parse_failures = max(0, raw_count - len(page_jobs))
                metrics.listing_parse_failures += parse_failures
                if parse_failures:
                    metrics.add_partial_reason("LISTING_PARSE_FAILURE")
                if raw_count == 0:
                    metrics.pagination_stop_reason = "END_REACHED"
                    break
                if not page_jobs:
                    metrics.pagination_stop_reason = "LISTING_PARSE_FAILURE"
                    metrics.add_partial_reason("LISTING_PARSE_FAILURE")
                    break
                page_identities = {_vacancy_identity(job.url) for job in page_jobs if _vacancy_identity(job.url)}
                summaries.extend(page_jobs)
                if page_identities and page_identities.issubset(seen_page_identities):
                    # A server ignoring page=N must never be mistaken for a
                    # complete market. Stopping avoids an infinite duplicate loop.
                    metrics.pagination_stop_reason = "REPEATED_PAGE"
                    metrics.add_partial_reason("REPEATED_PAGE")
                    break
                seen_page_identities.update(page_identities)
                page_number += 1

        # Deduplicate the complete Stage-1 snapshot before detail enrichment.
        unique_summaries: list[Job] = []
        seen_identities: set[str] = set()
        for job in summaries:
            identity = _vacancy_identity(job.url)
            if not identity or identity in seen_identities:
                metrics.duplicates_removed += 1
                continue
            seen_identities.add(identity)
            unique_summaries.append(job)

        if (
            metrics.pagination_stop_reason == "END_REACHED"
            and metrics.source_listings_reported is not None
            and len(unique_summaries) != metrics.source_listings_reported
        ):
            metrics.add_partial_reason(
                "SOURCE_LISTING_COUNT_MISMATCH",
                "ACBAR reported "
                f"{metrics.source_listings_reported} listings but parser discovered "
                f"{len(unique_summaries)} unique vacancies.",
            )

        enrichment_candidates: list[Job] = []
        for job in unique_summaries:
            job.metadata = dict(job.metadata or {})
            if is_expired(job, today=today):
                # The lifecycle later records the expiry; no detail request is
                # useful for a listing whose advertised deadline has passed.
                job.metadata["listing_relevance"] = "expired_from_listing"
            elif _acbar_listing_is_clearly_irrelevant(job):
                job.metadata["listing_relevance"] = "clearly_irrelevant"
            else:
                job.metadata["listing_relevance"] = "needs_detail_review"
                enrichment_candidates.append(job)

        processable = enrichment_candidates

        semaphore = asyncio.Semaphore(concurrency)

        async def detail(job: Job) -> Job:
            metrics.detail_pages_attempted += 1
            async with semaphore:
                try:
                    response = await client.get(job.url)
                    response.raise_for_status()
                    parsed = _parse_acbar_detail(response.text, job)
                    parsed.metadata["detail_enrichment"] = "succeeded"
                    metrics.detail_pages_succeeded += 1
                    return parsed
                except Exception as exc:
                    job.metadata["detail_enrichment"] = "failed_listing_fallback"
                    job.metadata["detail_error"] = _concise_error(exc)
                    metrics.detail_pages_failed += 1
                    metrics.listing_fallback_used += 1
                    return job

        await asyncio.gather(*(detail(job) for job in processable))

    if metrics.detail_pages_failed:
        metrics.add_partial_reason("DETAIL_FETCH_FAILURE", f"{metrics.detail_pages_failed} detail page(s) failed; valid listing fallback was used.")
    metrics.vacancies_parsed = metrics.listings_seen - metrics.listing_parse_failures
    usable = metrics.pages_succeeded > 0
    metrics.status = (
        SOURCE_STATUS_UNAVAILABLE if not usable else
        SOURCE_STATUS_PARTIAL if metrics.partial_reasons else SOURCE_STATUS_SCANNED
    )
    return SourceJobs(unique_summaries, parsed_count=metrics.vacancies_parsed, metrics=metrics)

def _vacancy_identity(url: str) -> str:
    """Identify official vacancy paths across legitimate registered host aliases."""
    parsed = urlparse(url)
    path = re.sub(r"/+$", "", parsed.path.lower())
    host = parsed.netloc.lower().split(":", 1)[0]
    acbar = SOURCE_REGISTRY.get("acbar", {})
    acbar_hosts = {str(item).lower() for item in acbar.get("host_aliases", [])}
    pattern = ((acbar.get("path_patterns") or {}).get("vacancy_id") or r"/(?:en/)?jobs/(?:details/)?(\d+)(?:/|$)")
    if host in acbar_hosts:
        match = re.search(pattern, path)
        if match:
            return f"acbar:{match.group(1)}"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def _deduplicate_source_vacancies_with_stats(jobs: list[Job], *, today: date | None = None) -> tuple[list[Job], dict[str, int]]:
    seen: set[str] = set()
    result: list[Job] = []
    stats = {"duplicates_removed": 0, "expired_stale_excluded": 0}
    for job in jobs:
        if is_expired(job, today=today):
            stats["expired_stale_excluded"] += 1
            continue
        key = _vacancy_identity(job.url)
        if not key or key in seen:
            stats["duplicates_removed"] += 1
            continue
        seen.add(key)
        result.append(job)
    return result, stats


def _deduplicate_source_vacancies(jobs: list[Job], *, today: date | None = None) -> list[Job]:
    return _deduplicate_source_vacancies_with_stats(jobs, today=today)[0]


def _parse_acbar_listing(html: str, base_url: str) -> list[Job]:
    spec = SOURCE_REGISTRY.get("acbar", {})
    source_name = source_display_name(spec) or "acbar"
    provenance_label = (spec.get("provenance_labels") or {}).get("listing") or f"{source_name} listing"
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    # Uses the same card-anchor definition as listings_seen, so a location
    # expansion link never inflates source accounting.
    for anchor in _acbar_listing_anchors(soup):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = str(urljoin(base_url, str(anchor.get("href") or "")))
        if not title or not href:
            continue
        card = _listing_card(anchor)
        context = normalize_space(card.get_text(" ", strip=True) if card else anchor.get_text(" ", strip=True))
        company = _guess_company_from_listing_context(context, title)
        closing = parse_closing_date(context) or ""
        location = _guess_location(context) or "Afghanistan"
        jobs.append(
            Job(
                id=stable_job_id("acbar", href, title, company),
                title=title,
                company=company,
                location=location,
                url=href,
                apply_url=None,
                platform="acbar",
                description=context,
                source_name=source_name,
                source_url=base_url,
                vacancy_url=href,
                application_method="UNAVAILABLE",
                metadata={
                    "source": source_name,
                    "source_name": source_name,
                    "source_tier": spec.get("tier", ""),
                    "source_url": base_url,
                    "vacancy_url": href,
                    "apply_url": None,
                    "application_method": "UNAVAILABLE",
                    "closing_date": closing,
                    "source_provenance": [{"source": provenance_label, "url": base_url, "field": "listing card"}],
                },
            )
        )
    return jobs


def _listing_card(anchor: Any) -> Any:
    """Return the smallest container that has ACBAR card metadata."""
    fallback = anchor.parent
    for parent in anchor.parents:
        if getattr(parent, "name", None) not in {"div", "article", "li", "section"}:
            continue
        fallback = parent
        text = normalize_space(parent.get_text(" ", strip=True))
        if re.search(r"20\d{2}-\d{2}-\d{2}", text):
            return parent
        if len(text) > 1200:
            break
    return fallback


def _labeled_value(text: str, label: str) -> str:
    match = re.search(rf"(?:^|\n)\s*{label}\s*:?\s*([^\n]+)", text, flags=re.IGNORECASE)
    return normalize_space(match.group(1)) if match else ""


def _parse_acbar_detail(html: str, job: Job) -> Job:
    spec = SOURCE_REGISTRY.get("acbar", {})
    source_name = source_display_name(spec) or job.source_name or "acbar"
    soup = BeautifulSoup(html or "", "html.parser")
    text = strip_html(soup.get_text("\n", strip=True))
    # Generic h2 headings are section labels ("About the Company", "Job
    # Summary") on the current site, not the vacancy title. Preserve the
    # authoritative listing title unless a title-specific element exists.
    title_selector = (spec.get("selectors") or {}).get("detail_title") or "h1.job-title, h1.vacancy-title, [data-vacancy-title], h1"
    title_node = soup.select_one(title_selector)
    if title_node:
        title = normalize_space(title_node.get_text(" ", strip=True)).replace("ACBAR:", "").strip()
        if title and title.lower() not in {"about the company", "job summary", "job requirements", "acbar"}:
            job.title = title
    job.description = normalize_space(text)  # Preserve complete official detail text, including late application instructions.
    organization = _labeled_value(text, r"Organization")
    location = _labeled_value(text, r"(?:Job )?Location") or _labeled_value(text, r"Location")
    if organization:
        job.company = organization
        job.metadata["organization"] = organization
    if location:
        job.location = location
        job.metadata["location"] = location
    gender = _labeled_value(text, r"Gender")
    if gender:
        job.metadata["gender"] = gender
    email = _extract_email(text)
    if email:
        job.apply_email = email
        job.apply_url = None
        job.application_method = "EMAIL"
        job.metadata["apply_email"] = email
        job.metadata["application_email"] = email
        job.metadata["application_method"] = "EMAIL"
    linked_urls = [urljoin(job.url, str(anchor.get("href") or "")) for anchor in soup.select("a[href]")]
    app_url = _extract_application_url("\n".join([text, *linked_urls]))
    if app_url:
        job.metadata["application_url"] = app_url
        job.metadata["apply_url"] = app_url
        if email:
            job.apply_url = app_url
        else:
            job.apply_url = app_url
            job.application_method = "WEB"
            job.metadata["application_method"] = "WEB"
    closing = parse_closing_date(text)
    if closing:
        job.metadata["closing_date"] = closing
    ref = _extract_reference(text)
    if ref:
        job.metadata["reference_number"] = ref
    subject = _extract_subject(text)
    if subject:
        job.metadata["application_subject"] = subject
    job.source_name = source_name
    job.metadata["source"] = source_name
    job.metadata["source_name"] = source_name
    provenance_label = (spec.get("provenance_labels") or {}).get("detail") or f"{source_name} detail"
    job.metadata.setdefault("source_provenance", []).append({"source": provenance_label, "url": job.url, "field": "vacancy page"})
    return job


async def discover_reliefweb_jobs(profile: dict[str, Any], *, today: date | None = None) -> list[Job]:
    """Fetch ReliefWeb using the same card/detail semantics as ACBAR."""
    spec = SOURCE_REGISTRY["reliefweb"]
    defaults = spec.get("defaults") or {}
    cfg = _source_overrides(profile, "reliefweb")
    _validate_source_keys(cfg, "reliefweb", {"timeout_seconds", "limit"})
    timeout = float(cfg.get("timeout_seconds", defaults.get("timeout_seconds", RELIEFWEB_DEFAULT_TIMEOUT_SECONDS)))
    limit = _configured_positive_int(cfg, "reliefweb", "limit", int(defaults.get("limit", RELIEFWEB_DEFAULT_LIMIT)))
    url = str(spec.get("listing_url") or spec.get("official_url") or "")
    metrics = SourceScanMetrics(source_url=url, official_source_id=str(spec.get("official_name") or source_display_name(spec)))
    summaries: list[Job] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        metrics.pages_requested = 1
        try:
            response = await client.get(url)
            response.raise_for_status()
            metrics.pages_succeeded = 1
        except Exception as exc:
            metrics.pages_failed = 1
            metrics.pagination_stop_reason = "REQUEST_FAILED"
            metrics.add_partial_reason("REQUEST_FAILURE", _concise_error(exc))
            metrics.status = SOURCE_STATUS_UNAVAILABLE
            return SourceJobs([], parsed_count=0, metrics=metrics)
        selector = ", ".join((spec.get("selectors") or {}).get("listing_links") or ['a[href*="/job/"]'])
        raw_count = len(BeautifulSoup(response.text or "", "html.parser").select(selector))
        parsed_all = _parse_reliefweb_listing(response.text, url, limit=max(raw_count, 1), deduplicate_result=False)
        metrics.listings_seen = raw_count
        metrics.listing_parse_failures = max(0, raw_count - len(parsed_all))
        if metrics.listing_parse_failures:
            metrics.add_partial_reason("LISTING_PARSE_FAILURE")
        unique_summaries: list[Job] = []
        seen_identities: set[str] = set()
        for job in parsed_all:
            identity = _vacancy_identity(job.url)
            if not identity or identity in seen_identities:
                metrics.duplicates_removed += 1
            else:
                seen_identities.add(identity)
                unique_summaries.append(job)
        summaries = unique_summaries[:limit]
        metrics.not_processed_due_to_budget = max(0, len(unique_summaries) - len(summaries))
        if metrics.not_processed_due_to_budget or raw_count >= limit:
            metrics.pagination_stop_reason = "RESULT_LIMIT_REACHED"
            metrics.add_partial_reason("RESULT_LIMIT_REACHED")
        else:
            # ReliefWeb's maintained adapter currently requests one bounded
            # result page; fewer results than its limit is the observable end.
            metrics.pagination_stop_reason = "END_REACHED"

        async def detail(job: Job) -> Job:
            metrics.detail_pages_attempted += 1
            try:
                response = await client.get(job.url)
                response.raise_for_status()
                parsed = _parse_reliefweb_detail(response.text, job)
                metrics.detail_pages_succeeded += 1
                return parsed
            except Exception:
                metrics.detail_pages_failed += 1
                metrics.listing_fallback_used += 1
                return job

        detailed = await asyncio.gather(*(detail(job) for job in summaries))
    if metrics.detail_pages_failed:
        metrics.add_partial_reason("DETAIL_FETCH_FAILURE", f"{metrics.detail_pages_failed} detail page(s) failed; valid listing fallback was used.")
    metrics.vacancies_parsed = len(detailed) + metrics.duplicates_removed
    metrics.status = SOURCE_STATUS_PARTIAL if metrics.partial_reasons else SOURCE_STATUS_SCANNED
    return SourceJobs(detailed, parsed_count=len(detailed), metrics=metrics)


def _parse_reliefweb_listing(html: str, base_url: str, *, limit: int, deduplicate_result: bool = True) -> list[Job]:
    spec = SOURCE_REGISTRY.get("reliefweb", {})
    source_name = source_display_name(spec) or "reliefweb"
    raw_selector_list = ((spec.get("selectors") or {}).get("listing_links") or ['a[href*="/job/"]'])
    selector_list = [str(item) for item in raw_selector_list]
    selector = ", ".join(selector_list)
    provenance_label = (spec.get("provenance_labels") or {}).get("listing") or f"{source_name} listing"
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    for anchor in soup.select(selector):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = str(urljoin(base_url, str(anchor.get("href") or "")))
        if not title or not href:
            continue
        card = anchor.find_parent(["article", "li", "div"]) or anchor.parent
        context = normalize_space(card.get_text(" ", strip=True) if card else title)
        if deduplicate_result and "afghanistan" not in context.lower() and "afghanistan" not in title.lower():
            continue
        company = _guess_reliefweb_company(context)
        closing = parse_closing_date(context) or ""
        jobs.append(
            Job(
                id=stable_job_id("reliefweb", href, title, company),
                title=title,
                company=company,
                location="Afghanistan",
                url=href,
                apply_url=None,
                platform="reliefweb",
                description=context,
                source_name=source_name,
                source_url=base_url,
                vacancy_url=href,
                application_method="UNAVAILABLE",
                metadata={
                    "source": source_name,
                    "source_name": source_name,
                    "source_tier": spec.get("tier", ""),
                    "source_url": base_url,
                    "vacancy_url": href,
                    "apply_url": None,
                    "application_method": "UNAVAILABLE",
                    "closing_date": closing,
                    "source_provenance": [{"source": provenance_label, "url": base_url, "field": "listing card"}],
                },
            )
        )
        if len(jobs) >= limit:
            break
    return deduplicate_jobs(jobs) if deduplicate_result else jobs


def _parse_reliefweb_detail(html: str, job: Job) -> Job:
    spec = SOURCE_REGISTRY.get("reliefweb", {})
    source_name = source_display_name(spec) or job.source_name or "reliefweb"
    soup = BeautifulSoup(html or "", "html.parser")
    text = strip_html(soup.get_text("\n", strip=True))
    title_selector = (spec.get("selectors") or {}).get("detail_title") or "h1"
    title_node = soup.select_one(title_selector)
    if title_node:
        title = normalize_space(title_node.get_text(" ", strip=True))
        if title and title.lower() not in {"jobs", "reliefweb"}:
            job.title = title
    job.description = normalize_space(text)  # Preserve complete official detail text, including late application instructions.
    company = _clean_reliefweb_employer(_labeled_value(text, r"Organization")) or _clean_reliefweb_employer(
        _labeled_value(text, r"Source")
    )
    if company:
        job.company = company
        job.metadata["organization"] = company
    country = _clean_reliefweb_field(_labeled_value(text, r"Country"))
    if country:
        job.location = country
        job.metadata["location"] = country
    closing = parse_closing_date(text)
    if closing:
        job.metadata["closing_date"] = closing
    linked_urls = [urljoin(job.url, str(anchor.get("href") or "")) for anchor in soup.select("a[href]")]
    app_url = _extract_application_url("\n".join([text, *linked_urls]))
    email = _extract_email(text)
    if email:
        job.apply_email = email
        job.application_method = "EMAIL"
        job.metadata.update({"apply_email": email, "application_email": email, "application_method": "EMAIL"})
    elif app_url and _vacancy_identity(app_url) != _vacancy_identity(job.url):
        job.apply_url = app_url
        job.application_method = "WEB"
        job.metadata.update({"apply_url": app_url, "application_url": app_url, "application_method": "WEB"})
    job.source_name = source_name
    job.metadata["source"] = source_name
    job.metadata["source_name"] = source_name
    provenance_label = (spec.get("provenance_labels") or {}).get("detail") or f"{source_name} detail"
    job.metadata.setdefault("source_provenance", []).append({"source": provenance_label, "url": job.url, "field": "vacancy page"})
    return job


def _guess_company_from_listing_context(context: str, title: str) -> str:
    text = context.replace(title, " ", 1)
    text = re.sub(r"\bNEW\b|\bFull Time\b|\bPart Time\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s+(?:minutes?|hours?|days?|weeks?)\s+ago\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", " ", text)
    text = re.sub(r"\b(?:close|closing|deadline|expire)[^•\n]{0,40}", " ", text, flags=re.IGNORECASE)
    provinces = _guess_location(text)
    if provinces:
        for province in provinces.split(","):
            text = re.sub(rf"\b{re.escape(province.strip())}\b", " ", text, flags=re.IGNORECASE)
    parts = [normalize_space(p) for p in re.split(r"[•\n|]+", text) if normalize_space(p)]
    for part in parts:
        cleaned = normalize_space(re.sub(r"\bAfghanistan\b|\bKabul\b", " ", part, flags=re.IGNORECASE))
        if cleaned and len(cleaned) <= 100:
            return cleaned
    return ""


def _guess_location(text: str) -> str:
    found = []
    lower = text.lower()
    aliases = {
        "Bamian": "Bamyan",
        "Daikondi": "Daykundi",
        "Ghowr": "Ghor",
        "Jawzjan": "Jowzjan",
        "Nimruz": "Nimroz",
        "Orozgan": "Uruzgan",
        "Oruzgan": "Uruzgan",
        "Sar-e Pol": "Sar-e-Pul",
    }
    for province in list(AFGHAN_PROVINCES) + list(aliases):
        if re.search(rf"\b{re.escape(province.lower())}\b", lower):
            found.append(aliases.get(province, province))
    return ", ".join(dict.fromkeys(found[:4]))


# Labels that begin the next ReliefWeb field. A value ends at the first one.
_RELIEFWEB_FIELD_LABELS = (
    r"Organi[sz]ation|Source|Country|Location|Closing date|Closing|Deadline|Posted|"
    r"How to apply|Apply|Career type|Job type|Theme|Type|Experience|Language|"
    r"Reference|Vacancy"
)


def _clean_reliefweb_field(value: str) -> str:
    """Return a single field value, cut at the next label, date or separator.

    ReliefWeb card and detail text run fields together ("Organization: WHO
    Closing date: 2026-10-15"). A value that still contains a date, a closing or
    deadline word, or a URL is not a name, so it is rejected rather than stored.
    """
    text = normalize_space(value or "")
    text = re.split(rf"\s+(?:{_RELIEFWEB_FIELD_LABELS})\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(rf"\s+(?:{_RELIEFWEB_FIELD_LABELS})\s+(?=\d)", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"\s+(?:closing|deadline|posted)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"\s+\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", text, maxsplit=1)[0]
    text = re.split(r"[|\u2022;]", text, maxsplit=1)[0]
    text = normalize_space(text).strip(" .,-:")
    if not text or len(text) > 100:
        return ""
    if re.search(r"\d{4}[-/]\d{1,2}|\b(?:closing|deadline)\b|https?://", text, flags=re.IGNORECASE):
        return ""
    return text


def _clean_reliefweb_employer(value: str) -> str:
    """An employer must be a name: a cleaned field that is not a bare place or placeholder."""
    company = _clean_reliefweb_field(value)
    if company.lower() in {"afghanistan", "kabul", "n/a", "none", "unknown"}:
        return ""
    return company


def _guess_reliefweb_company(context: str) -> str:
    patterns = [r"Organi[sz]ation\s*[:\-]\s*(.+)", r"Source\s*[:\-]\s*(.+)"]
    for pattern in patterns:
        match = re.search(pattern, context, flags=re.IGNORECASE)
        if match:
            company = _clean_reliefweb_employer(match.group(1))
            if company:
                return company
    return ""


def _extract_email(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_application_url(text: str) -> str:
    for match in re.finditer(r"https?://[^\s)\]]+", text or ""):
        url = match.group(0).rstrip(".,;)]")
        if any(token in url.lower() for token in ["form", "apply", "jobs", "careers"]):
            return url
    return ""


def _extract_reference(text: str) -> str:
    match = re.search(r"(?:Vacancy\s*(?:No\.?|Number)|Reference\s*(?:No\.?|Number))\s*[:#\-]?\s*([A-Z0-9_./\-]+)", text or "", flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _extract_subject(text: str) -> str:
    match = re.search(r"(?:subject line|email subject).*?(?:as|:)?\s*[\"“']?([^\n\"”']{4,120})", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    subject = normalize_space(match.group(1))
    # "...in the subject line to recruitment@example.org" names the contact
    # route, not a subject. Never store a route (email address or "to ..."
    # phrase) as the application subject.
    if "@" in subject or re.match(r"(?i)(to|at|via)\b", subject):
        return ""
    return subject.rstrip(".")
