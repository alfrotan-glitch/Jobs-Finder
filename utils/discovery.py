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
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from utils.medical_requirements import AFGHAN_PROVINCES, analyze_professional_role, canonical_source_fields, extract_requirements_from_job, has_actionable_source, looks_medical, parse_closing_date, strip_html
from utils.source_registry import SOURCE_REGISTRY, source_defaults, source_display_name, source_official_url

SCAN_COMPLETE = "SCAN_COMPLETE"
NO_RELEVANT_JOBS_FOUND = "NO_RELEVANT_JOBS_FOUND"
PARTIAL_SCAN = "PARTIAL_SCAN"
SOURCES_UNAVAILABLE = "SOURCES_UNAVAILABLE"
SCAN_FAILED = "SCAN_FAILED"

DEFAULT_USER_AGENT = "Jobs-Finder Afghanistan Job Assistant (+manual, non-automated applications)"

# ACBAR pagination/concurrency budget. This is a deliberate, documented
# performance/safety budget -- not a claim that every page on the source site
# is scanned. See discover_acbar_jobs() and docs/source_registry.md.
_ACBAR_DEFAULTS = source_defaults("acbar")
_RELIEFWEB_DEFAULTS = source_defaults("reliefweb")
ACBAR_DEFAULT_MAX_PAGES = int(_ACBAR_DEFAULTS.get("max_pages", 6))
ACBAR_DEFAULT_DETAIL_LIMIT = int(_ACBAR_DEFAULTS.get("detail_limit", 30))
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
    """Structured per-source scan metrics retained for user audit."""

    source_url: str = ""
    official_source_id: str = ""
    status: str = SOURCE_STATUS_UNAVAILABLE
    pages_attempted: int = 0
    listings_attempted: int = 0
    listings_checked: int = 0
    vacancies_discovered: int = 0
    vacancies_parsed: int = 0
    duplicates_removed: int = 0
    expired_stale_excluded: int = 0
    irrelevant_excluded: int = 0
    incompatible_professional_role_excluded: int = 0
    source_validation_excluded: int = 0
    relevant_retained: int = 0
    application_routes_discovered: int = 0
    partial: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceReport:
    id: str
    name: str
    tier: str
    attempted: bool = False
    ok: bool = False
    jobs_found: int = 0
    relevant_candidates: int = 0
    final_retained: int = 0
    error: str = ""
    timestamp: str = ""
    started_at: str = ""
    finished_at: str = ""
    source_url: str = ""
    official_source_id: str = ""
    status: str = SOURCE_STATUS_UNAVAILABLE
    pages_attempted: int = 0
    listings_attempted: int = 0
    listings_checked: int = 0
    vacancies_discovered: int = 0
    vacancies_parsed: int = 0
    duplicates_removed: int = 0
    expired_stale_excluded: int = 0
    irrelevant_excluded: int = 0
    incompatible_professional_role_excluded: int = 0
    source_validation_excluded: int = 0
    relevant_retained: int = 0
    application_routes_discovered: int = 0
    errors: list[str] = field(default_factory=list)

    def apply_metrics(self, metrics: SourceScanMetrics | dict[str, Any] | None) -> None:
        if not metrics:
            return
        data = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
        if data.get("partial") and self.status == SOURCE_STATUS_SCANNED:
            self.status = SOURCE_STATUS_PARTIAL
        if self.errors and not self.error:
            self.error = "; ".join(self.errors[:2])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    status: str
    jobs: list[Job]
    source_reports: list[SourceReport]
    started_at: str
    finished_at: str
    message: str

    @property
    def successful_sources(self) -> int:
        return sum(1 for report in self.source_reports if report.ok)

    @property
    def failed_sources(self) -> int:
        return sum(1 for report in self.source_reports if report.attempted and not report.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "jobs": [job.to_dict() for job in self.jobs],
            "source_reports": [report.to_dict() for report in self.source_reports],
            "successful_sources": self.successful_sources,
            "failed_sources": self.failed_sources,
            "job_count": len(self.jobs),
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
        source_id = str(job.platform or "").lower()
        if is_expired(job, today=today):
            inc(source_id, "expired_stale_excluded")
            continue
        key = _canonical(job.url or job.apply_url) or _canonical(f"{job.title} {job.company} {job.location}")
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
    job.metadata.setdefault("source_urls", [url for url in [job.metadata.get("source_url"), job.url, job.apply_url] if url])
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
    profile = profile or {}
    today = today or date.today()
    started = utc_now()
    source_reports: list[SourceReport] = []
    jobs: list[Job] = []

    enabled = _enabled_sources(profile)
    if not enabled:
        finished = utc_now()
        return ScanResult(
            status=SCAN_FAILED,
            jobs=[],
            source_reports=[],
            started_at=started,
            finished_at=finished,
            message="No active discovery sources are enabled.",
        )

    for source_id in enabled:
        spec = SOURCE_REGISTRY[source_id]
        report = _new_source_report(source_id, spec)
        try:
            fetcher = globals()[spec["fetcher"]]
            try:
                found = await fetcher(profile, today=today)
            except TypeError:
                found = await fetcher(profile)
            report.ok = True
            report.status = SOURCE_STATUS_SCANNED
            report.apply_metrics(getattr(found, "metrics", None))
            # SourceJobs lets a source report every valid listing item parsed,
            # even though only relevant enriched vacancies leave the fetcher.
            report.jobs_found = int(getattr(found, "parsed_count", len(found)))
            if not report.vacancies_discovered:
                report.vacancies_discovered = report.jobs_found
            if not report.listings_checked:
                report.listings_checked = report.jobs_found
            if not report.vacancies_parsed:
                report.vacancies_parsed = len(found)
            if getattr(found, "metrics", None) and getattr(found.metrics, "partial", False):
                report.status = SOURCE_STATUS_PARTIAL
            jobs.extend(found)
        except Exception as exc:  # source isolation is mandatory
            reason = _concise_error(exc)
            report.ok = False
            report.status = SOURCE_STATUS_UNAVAILABLE
            report.error = reason
            report.errors.append(reason)
        report.finished_at = utc_now()
        source_reports.append(report)

    reports_by_source = {report.id.lower(): report for report in source_reports}
    normalized: list[Job] = []
    per_source_candidates: dict[str, int] = {}
    for job in jobs:
        source_id = str(getattr(job, "platform", "") or "").lower()
        report = reports_by_source.get(source_id)
        try:
            if not isinstance(job, Job):
                if report:
                    report.errors.append("Malformed vacancy item ignored.")
                continue
            if not _job_is_relevant(job):
                if report:
                    report.irrelevant_excluded += 1
                continue
            enriched = enrich_job(job, today=today)
            if enriched.application_method in {"EMAIL", "WEB"} and report:
                report.application_routes_discovered += 1
            role_classification = _role_classification(enriched)
            if role_classification == "incompatible_professional_role":
                if report:
                    report.incompatible_professional_role_excluded += 1
                continue
            if not has_actionable_source(enriched.to_dict()):
                if report:
                    report.source_validation_excluded += 1
                continue
            normalized.append(enriched)
            per_source_candidates[source_id] = per_source_candidates.get(source_id, 0) + 1
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            # A malformed item must not discard valid vacancies or crash the scan.
            if report:
                report.errors.append(f"Vacancy parse skipped: {_concise_error(exc)}")
            continue

    deduped, dedupe_stats = deduplicate_jobs_with_stats(normalized, today=today)
    for report in source_reports:
        source_id = report.id.lower()
        report.relevant_candidates = per_source_candidates.get(source_id, 0)
        report.final_retained = sum(1 for job in deduped if job.platform.lower() == source_id)
        report.relevant_retained = report.final_retained
        report.duplicates_removed += dedupe_stats.get(source_id, {}).get("duplicates_removed", 0)
        report.expired_stale_excluded += dedupe_stats.get(source_id, {}).get("expired_stale_excluded", 0)
        # Keep the legacy jobs_found field useful but do not use it to imply a
        # failed/unavailable source found zero jobs; source status is always
        # displayed alongside counts.
        if report.errors and not report.error:
            report.error = "; ".join(dict.fromkeys(report.errors[:2]))
        if report.ok and (report.errors or report.status == SOURCE_STATUS_PARTIAL):
            report.status = SOURCE_STATUS_PARTIAL

    successful = sum(1 for report in source_reports if report.ok)
    failed = sum(1 for report in source_reports if report.attempted and not report.ok)
    partial = sum(1 for report in source_reports if report.ok and report.status == SOURCE_STATUS_PARTIAL)
    retained = len(deduped)
    if successful == 0:
        status = SOURCES_UNAVAILABLE
        message = "Live scan incomplete. Job sources could not be reached."
    elif failed or partial:
        status = PARTIAL_SCAN
        issues = failed + partial
        issue_word = "source" if issues == 1 else "sources"
        if retained:
            message = f"Partial market scan. {retained} relevant current vacancies retained from scanned portions; {issues} {issue_word} unavailable or partial."
        else:
            message = f"Partial market scan. No relevant current vacancies were retained from scanned portions; {issues} {issue_word} unavailable or partial."
    elif not deduped:
        status = NO_RELEVANT_JOBS_FOUND
        message = "Scan completed. No relevant current vacancies were found in the reachable sources."
    else:
        status = SCAN_COMPLETE
        message = f"Scan completed. {retained} relevant current vacancies found."

    return ScanResult(status=status, jobs=deduped, source_reports=source_reports, started_at=started, finished_at=utc_now(), message=message)


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


async def discover_acbar_jobs(profile: dict[str, Any], *, today: date | None = None) -> list[Job]:
    """Scan ACBAR's listing pages with bounded, documented pagination.

    Coverage: this walks ACBAR listing pages starting at page 1 and keeps
    requesting the next page only while it keeps finding new, not-yet-seen
    vacancy links, up to ``max_pages`` (default
    :data:`ACBAR_DEFAULT_MAX_PAGES`). This is a deliberate, bounded budget --
    not a claim that the entire ACBAR archive is scanned every time. An
    explicit ``job_sources.acbar.urls`` list in profile.yaml overrides this
    auto-pagination entirely and is fetched as-is (useful for pinning a
    specific page range). Detail pages are fetched with bounded concurrency
    (``max_detail_concurrency``) for relevant vacancies up to ``detail_limit``
    so a slow network cannot turn one scan into a very long sequential wait;
    the overall HTTP timeout still applies per request via ``timeout_seconds``.
    """
    spec = SOURCE_REGISTRY["acbar"]
    defaults = spec.get("defaults") or {}
    cfg = ((profile.get("job_sources") or {}).get("acbar") or {}) if isinstance(profile, dict) else {}
    explicit_urls = cfg.get("urls")
    timeout = float(cfg.get("timeout_seconds", defaults.get("timeout_seconds", ACBAR_DEFAULT_TIMEOUT_SECONDS)))
    detail_limit = max(1, int(cfg.get("detail_limit", defaults.get("detail_limit", ACBAR_DEFAULT_DETAIL_LIMIT))))
    max_pages = max(1, int(cfg.get("max_pages", defaults.get("max_pages", ACBAR_DEFAULT_MAX_PAGES))))
    max_detail_concurrency = max(1, int(cfg.get("max_detail_concurrency", defaults.get("max_detail_concurrency", ACBAR_DEFAULT_DETAIL_CONCURRENCY))))
    base_listing_url = str(spec.get("listing_url") or spec.get("official_url") or "")
    metrics = SourceScanMetrics(source_url=base_listing_url, official_source_id=str(spec.get("official_name") or source_display_name(spec)))

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        summaries: list[Job] = []
        reached_configured_limit = False
        if explicit_urls:
            for url in explicit_urls:
                metrics.pages_attempted += 1
                response = await client.get(url)
                response.raise_for_status()
                page_jobs = _parse_acbar_listing(response.text, url)
                metrics.listings_attempted += len(page_jobs)
                summaries.extend(page_jobs)
        else:
            seen_urls: set[str] = set()
            for page in range(1, max_pages + 1):
                url = base_listing_url if page == 1 else f"{base_listing_url}?page={page}"
                metrics.pages_attempted += 1
                response = await client.get(url)
                response.raise_for_status()
                page_jobs = _parse_acbar_listing(response.text, url)
                metrics.listings_attempted += len(page_jobs)
                new_jobs = [job for job in page_jobs if job.url not in seen_urls]
                if not new_jobs:
                    # No new vacancies on this page: either the last page was
                    # reached or the site stopped returning distinct results.
                    break
                seen_urls.update(job.url for job in new_jobs)
                summaries.extend(new_jobs)
                reached_configured_limit = page == max_pages and bool(new_jobs)

        metrics.vacancies_discovered = len(summaries)
        deduped, dedupe_stats = _deduplicate_source_vacancies_with_stats(summaries, today=today)
        metrics.duplicates_removed = dedupe_stats["duplicates_removed"]
        metrics.expired_stale_excluded = dedupe_stats["expired_stale_excluded"]
        metrics.listings_checked = len(deduped)
        # Obvious medical titles are fetched first, but relevance is decided
        # only after detail enrichment. Remaining budget is spent on cards
        # whose short listing text may omit the professional requirements.
        obvious = [job for job in deduped if _job_is_relevant(job)]
        other = [job for job in deduped if job not in obvious]
        candidates = (obvious + other)[:detail_limit]
        if len(deduped) > len(candidates) or reached_configured_limit:
            metrics.partial = True

        semaphore = asyncio.Semaphore(max_detail_concurrency)
        detail_error_count = 0

        async def fetch_detail(job: Job) -> Job:
            nonlocal detail_error_count
            async with semaphore:
                try:
                    detail = await client.get(job.url)
                    detail.raise_for_status()
                    return _parse_acbar_detail(detail.text, job)
                except Exception:
                    detail_error_count += 1
                    return job

        detailed = await asyncio.gather(*(fetch_detail(job) for job in candidates))
        metrics.vacancies_parsed = len(detailed)
        if detail_error_count:
            metrics.partial = True
            metrics.errors.append(f"{detail_error_count} detail page(s) could not be read; listing data was used where possible.")
        relevant = [job for job in detailed if _job_is_relevant(job)]
        metrics.irrelevant_excluded = max(0, len(detailed) - len(relevant))
        metrics.status = SOURCE_STATUS_PARTIAL if metrics.partial or metrics.errors else SOURCE_STATUS_SCANNED
        return SourceJobs(relevant, parsed_count=len(deduped), metrics=metrics)


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
    selector_list = ((spec.get("selectors") or {}).get("listing_links") or ['a[href*="/en/jobs/details/"]', 'a[href^="/jobs/"]'])
    selector = ", ".join(selector_list)
    path_pattern = ((spec.get("path_patterns") or {}).get("listing_path") or r"(?:/en/jobs/details/\d+(?:/[^/]+)?|/jobs/\d+/[^/]+\.jsp)$")
    provenance_label = (spec.get("provenance_labels") or {}).get("listing") or f"{source_name} listing"
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    for anchor in soup.select(selector):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, anchor.get("href", ""))
        path = urlparse(href).path
        if not re.search(path_pattern, path, flags=re.I):
            continue
        if not title or not href or title.lower() in {"more locations", "view all jobs"}:
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
    match = re.search(rf"(?:^|\n)\s*{label}\s*:?\s*([^\n]+)", text, flags=re.I)
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
    job.description = normalize_space(text)[:12000]
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
    """Discover ReliefWeb cards and enrich them before medical relevance."""
    spec = SOURCE_REGISTRY["reliefweb"]
    defaults = spec.get("defaults") or {}
    cfg = ((profile.get("job_sources") or {}).get("reliefweb") or {}) if isinstance(profile, dict) else {}
    timeout = float(cfg.get("timeout_seconds", defaults.get("timeout_seconds", RELIEFWEB_DEFAULT_TIMEOUT_SECONDS)))
    limit = max(1, int(cfg.get("limit", defaults.get("limit", RELIEFWEB_DEFAULT_LIMIT))))
    url = cfg.get("url") or spec.get("listing_url") or spec.get("official_url")
    metrics = SourceScanMetrics(source_url=str(url or ""), official_source_id=str(spec.get("official_name") or source_display_name(spec)))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        metrics.pages_attempted = 1
        response = await client.get(url)
        response.raise_for_status()
        summaries = _parse_reliefweb_listing(response.text, url, limit=limit)
        metrics.vacancies_discovered = len(summaries)
        metrics.listings_attempted = len(summaries)
        metrics.listings_checked = len(summaries)
        if len(summaries) >= limit:
            metrics.partial = True

        detail_error_count = 0

        async def fetch_detail(job: Job) -> Job:
            nonlocal detail_error_count
            try:
                detail = await client.get(job.url)
                detail.raise_for_status()
                return _parse_reliefweb_detail(detail.text, job)
            except Exception:
                detail_error_count += 1
                return job

        detailed = await asyncio.gather(*(fetch_detail(job) for job in summaries))
    metrics.vacancies_parsed = len(detailed)
    if detail_error_count:
        metrics.partial = True
        metrics.errors.append(f"{detail_error_count} detail page(s) could not be read; listing data was used where possible.")
    relevant = [job for job in detailed if _job_is_relevant(job)]
    metrics.irrelevant_excluded = max(0, len(detailed) - len(relevant))
    deduped, dedupe_stats = deduplicate_jobs_with_stats(relevant, today=today)
    metrics.duplicates_removed = dedupe_stats.get("reliefweb", {}).get("duplicates_removed", 0)
    metrics.expired_stale_excluded = dedupe_stats.get("reliefweb", {}).get("expired_stale_excluded", 0)
    metrics.status = SOURCE_STATUS_PARTIAL if metrics.partial or metrics.errors else SOURCE_STATUS_SCANNED
    return SourceJobs(deduped, parsed_count=len(summaries), metrics=metrics)


def _parse_reliefweb_listing(html: str, base_url: str, *, limit: int) -> list[Job]:
    spec = SOURCE_REGISTRY.get("reliefweb", {})
    source_name = source_display_name(spec) or "reliefweb"
    selector_list = ((spec.get("selectors") or {}).get("listing_links") or ['a[href*="/job/"]'])
    selector = ", ".join(selector_list)
    provenance_label = (spec.get("provenance_labels") or {}).get("listing") or f"{source_name} listing"
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    for anchor in soup.select(selector):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, anchor.get("href", ""))
        if not title or not href:
            continue
        card = anchor.find_parent(["article", "li", "div"]) or anchor.parent
        context = normalize_space(card.get_text(" ", strip=True) if card else title)
        if "afghanistan" not in context.lower() and "afghanistan" not in title.lower():
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
    return deduplicate_jobs(jobs)


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
    job.description = normalize_space(text)[:12000]
    company = _labeled_value(text, r"Organization") or _labeled_value(text, r"Source")
    if company:
        job.company = company
        job.metadata["organization"] = company
    country = _labeled_value(text, r"Country")
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
    text = re.sub(r"\bNEW\b|\bFull Time\b|\bPart Time\b", " ", text, flags=re.I)
    text = re.sub(r"\b\d+\s+(?:minutes?|hours?|days?|weeks?)\s+ago\b", " ", text, flags=re.I)
    text = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", " ", text)
    text = re.sub(r"\b(?:close|closing|deadline|expire)[^•\n]{0,40}", " ", text, flags=re.I)
    provinces = _guess_location(text)
    if provinces:
        for province in provinces.split(","):
            text = re.sub(rf"\b{re.escape(province.strip())}\b", " ", text, flags=re.I)
    parts = [normalize_space(p) for p in re.split(r"[•\n|]+", text) if normalize_space(p)]
    for part in parts:
        cleaned = normalize_space(re.sub(r"\bAfghanistan\b|\bKabul\b", " ", part, flags=re.I))
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


def _guess_reliefweb_company(context: str) -> str:
    patterns = [r"Organization\s*[:\-]\s*([^|]+)", r"Source\s*[:\-]\s*([^|]+)"]
    for pattern in patterns:
        match = re.search(pattern, context, flags=re.I)
        if match:
            return normalize_space(match.group(1))[:100]
    return ""


def _extract_email(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", flags=re.I)
    return match.group(0) if match else ""


def _extract_application_url(text: str) -> str:
    for match in re.finditer(r"https?://[^\s)\]]+", text or ""):
        url = match.group(0).rstrip(".,;)]")
        if any(token in url.lower() for token in ["form", "apply", "jobs", "careers"]):
            return url
    return ""


def _extract_reference(text: str) -> str:
    match = re.search(r"(?:Vacancy\s*(?:No\.?|Number)|Reference\s*(?:No\.?|Number))\s*[:#\-]?\s*([A-Z0-9_./\-]+)", text or "", flags=re.I)
    return match.group(1) if match else ""


def _extract_subject(text: str) -> str:
    match = re.search(r"(?:subject line|email subject).*?(?:as|:)?\s*[\"“']?([^\n\"”']{4,120})", text or "", flags=re.I)
    if not match:
        return ""
    subject = normalize_space(match.group(1))
    return subject.rstrip(".")
