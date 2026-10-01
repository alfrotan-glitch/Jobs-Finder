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
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from utils.medical_requirements import extract_requirements_from_job, looks_medical, parse_closing_date, strip_html

SCAN_COMPLETE = "SCAN_COMPLETE"
NO_RELEVANT_JOBS_FOUND = "NO_RELEVANT_JOBS_FOUND"
PARTIAL_SCAN = "PARTIAL_SCAN"
SOURCES_UNAVAILABLE = "SOURCES_UNAVAILABLE"
SCAN_FAILED = "SCAN_FAILED"

DEFAULT_USER_AGENT = "Jobs-Finder Afghanistan Job Assistant (+manual, non-automated applications)"

# ACBAR pagination/concurrency budget. This is a deliberate, documented
# performance/safety budget -- not a claim that every page on the source site
# is scanned. See discover_acbar_jobs() and docs/source_registry.md.
ACBAR_DEFAULT_MAX_PAGES = 6
ACBAR_DEFAULT_DETAIL_LIMIT = 30
ACBAR_DEFAULT_DETAIL_CONCURRENCY = 5
ACBAR_DEFAULT_TIMEOUT_SECONDS = 25.0

MEDICAL_SEARCH_TERMS = (
    "medical",
    "doctor",
    "physician",
    "health",
    "clinic",
    "hospital",
    "nutrition",
    "phc",
    "bphs",
    "ephs",
    "hmis",
    "quality of care",
    "capacity building",
)


@dataclass(slots=True)
class Job:
    id: str
    title: str
    company: str
    location: str
    url: str
    apply_url: str
    platform: str
    description: str = ""
    department: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

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
    error: str = ""

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


SourceFetcher = Callable[[dict[str, Any]], Awaitable[list[Job]]]

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "acbar": {
        "name": "ACBAR Jobs",
        "tier": "A",
        "fetcher": "discover_acbar_jobs",
        "active": True,
    },
    "reliefweb": {
        "name": "ReliefWeb Afghanistan jobs",
        "tier": "B",
        "fetcher": "discover_reliefweb_jobs",
        "active": True,
    },
}


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


def deduplicate_jobs(jobs: list[Job], *, today: date | None = None) -> list[Job]:
    seen: set[str] = set()
    out: list[Job] = []
    for job in jobs:
        if is_expired(job, today=today):
            continue
        key = _canonical(job.url or job.apply_url) or _canonical(f"{job.title} {job.company} {job.location}")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def enrich_job(job: Job, *, today: date | None = None) -> Job:
    job.metadata = dict(job.metadata or {})
    job.metadata.setdefault("source", job.platform)
    job.metadata.setdefault("source_url", job.url)
    job.metadata.setdefault("source_urls", [url for url in [job.url, job.apply_url] if url])
    if not job.metadata.get("closing_date"):
        parsed = parse_closing_date("\n".join([job.title, job.location, job.description, str(job.metadata)]))
        if parsed:
            job.metadata["closing_date"] = parsed
    requirements = extract_requirements_from_job(job.to_dict(), today=today)
    job.metadata["requirements"] = requirements.to_dict()
    facts = requirements.facts
    for key in ["closing_date", "application_email", "application_url", "application_subject", "reference_number"]:
        if facts.get(key) and not job.metadata.get(key):
            job.metadata[key] = facts[key]
    if not job.apply_url:
        job.apply_url = job.metadata.get("application_email") or job.metadata.get("application_url") or job.url
    return job


def _enabled_sources(profile: dict[str, Any]) -> list[str]:
    config = profile.get("sources", {}) if isinstance(profile.get("sources"), dict) else {}
    enabled = config.get("enabled")
    disabled = set(config.get("disabled") or [])
    if enabled:
        return [source for source in enabled if source in SOURCE_REGISTRY and source not in disabled]
    return [source for source, spec in SOURCE_REGISTRY.items() if spec.get("active") and source not in disabled]


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
        report = SourceReport(id=source_id, name=spec["name"], tier=spec["tier"], attempted=True)
        try:
            fetcher = globals()[spec["fetcher"]]
            found = await fetcher(profile)
            report.ok = True
            report.jobs_found = len(found)
            jobs.extend(found)
        except Exception as exc:  # source isolation is mandatory
            report.error = str(exc)
        source_reports.append(report)

    normalized: list[Job] = []
    for job in jobs:
        try:
            if not isinstance(job, Job) or not _job_is_relevant(job):
                continue
            normalized.append(enrich_job(job, today=today))
        except (AttributeError, TypeError, ValueError, KeyError):
            # A malformed item must not discard valid vacancies or crash the scan.
            continue
    deduped = deduplicate_jobs(normalized, today=today)

    successful = sum(1 for report in source_reports if report.ok)
    failed = sum(1 for report in source_reports if report.attempted and not report.ok)
    if successful == 0:
        status = SOURCES_UNAVAILABLE
        message = "Live scan incomplete. Job sources could not be reached."
    elif failed:
        status = PARTIAL_SCAN
        message = f"Partial market scan. {failed} of {len(source_reports)} sources unavailable."
    elif not deduped:
        status = NO_RELEVANT_JOBS_FOUND
        message = "Scan completed. No relevant current vacancies were found in the reachable sources."
    else:
        status = SCAN_COMPLETE
        message = f"Scan completed. {len(deduped)} relevant current vacancies found."

    return ScanResult(status=status, jobs=deduped, source_reports=source_reports, started_at=started, finished_at=utc_now(), message=message)


def _job_is_relevant(job: Job) -> bool:
    text = "\n".join([job.title, job.company, job.location, job.description])
    if looks_medical(text):
        return True
    lower = text.lower()
    return any(term in lower for term in MEDICAL_SEARCH_TERMS)


async def discover_acbar_jobs(profile: dict[str, Any]) -> list[Job]:
    """Scan ACBAR's listing pages with bounded, documented pagination.

    Coverage: this walks ACBAR listing pages starting at page 1 and keeps
    requesting the next page only while it keeps finding new, not-yet-seen
    vacancy links, up to ``max_pages`` (default
    :data:`ACBAR_DEFAULT_MAX_PAGES`). This is a deliberate, bounded budget --
    not a claim that the entire ACBAR archive is scanned every time. An
    explicit ``job_sources.acbar.urls`` list in profile.yaml overrides this
    auto-pagination entirely and is fetched as-is (useful for pinning a
    specific page range). Detail pages are fetched with bounded concurrency
    (``max_detail_concurrency``) so a slow network cannot turn one scan into a
    very long sequential wait; the overall HTTP timeout still applies per
    request via ``timeout_seconds``.
    """
    cfg = ((profile.get("job_sources") or {}).get("acbar") or {}) if isinstance(profile, dict) else {}
    explicit_urls = cfg.get("urls")
    timeout = float(cfg.get("timeout_seconds", ACBAR_DEFAULT_TIMEOUT_SECONDS))
    detail_limit = int(cfg.get("detail_limit", ACBAR_DEFAULT_DETAIL_LIMIT))
    max_pages = max(1, int(cfg.get("max_pages", ACBAR_DEFAULT_MAX_PAGES)))
    max_detail_concurrency = max(1, int(cfg.get("max_detail_concurrency", ACBAR_DEFAULT_DETAIL_CONCURRENCY)))
    base_listing_url = "https://www.acbar.org/en/jobs"

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        summaries: list[Job] = []
        if explicit_urls:
            for url in explicit_urls:
                response = await client.get(url)
                response.raise_for_status()
                summaries.extend(_parse_acbar_listing(response.text, url))
        else:
            seen_urls: set[str] = set()
            for page in range(1, max_pages + 1):
                url = base_listing_url if page == 1 else f"{base_listing_url}?page={page}"
                response = await client.get(url)
                response.raise_for_status()
                page_jobs = _parse_acbar_listing(response.text, url)
                new_jobs = [job for job in page_jobs if job.url not in seen_urls]
                if not new_jobs:
                    # No new vacancies on this page: either the last page was
                    # reached or the site stopped returning distinct results.
                    break
                seen_urls.update(job.url for job in new_jobs)
                summaries.extend(new_jobs)

        summaries = deduplicate_jobs(summaries)[:detail_limit]
        relevant = [job for job in summaries if _job_is_relevant(job)]

        semaphore = asyncio.Semaphore(max_detail_concurrency)

        async def fetch_detail(job: Job) -> Job:
            async with semaphore:
                try:
                    detail = await client.get(job.url)
                    detail.raise_for_status()
                    return _parse_acbar_detail(detail.text, job)
                except Exception:
                    return job

        detailed = await asyncio.gather(*(fetch_detail(job) for job in relevant))
        return list(detailed)


def _parse_acbar_listing(html: str, base_url: str) -> list[Job]:
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    for anchor in soup.select('a[href*="/en/jobs/details/"]'):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, anchor.get("href", ""))
        if not title or not href or title.lower() in {"more locations", "view all jobs"}:
            continue
        card = anchor.find_parent(["div", "article", "li", "section"]) or anchor.parent
        context = normalize_space(card.get_text(" ", strip=True) if card else anchor.get_text(" ", strip=True))
        company = _guess_company_from_listing_context(context, title) or "Unknown"
        closing = parse_closing_date(context) or ""
        location = _guess_location(context) or "Afghanistan"
        jobs.append(
            Job(
                id=stable_job_id("acbar", href, title, company),
                title=title,
                company=company,
                location=location,
                url=href,
                apply_url=href,
                platform="acbar",
                description=context,
                metadata={
                    "source": "ACBAR",
                    "source_tier": "A",
                    "source_url": href,
                    "closing_date": closing,
                    "source_provenance": [{"source": "ACBAR listing", "url": base_url, "field": "listing card"}],
                },
            )
        )
    return jobs


def _parse_acbar_detail(html: str, job: Job) -> Job:
    soup = BeautifulSoup(html or "", "html.parser")
    text = strip_html(soup.get_text("\n", strip=True))
    title_node = soup.find(["h1", "h2"])
    if title_node:
        title = normalize_space(title_node.get_text(" ", strip=True)).replace("ACBAR:", "").strip()
        if title:
            job.title = title
    job.description = normalize_space(text)[:12000]
    email = _extract_email(text)
    if email:
        job.apply_url = email
        job.metadata["application_email"] = email
    app_url = _extract_application_url(text)
    if app_url:
        job.metadata["application_url"] = app_url
        if not email:
            job.apply_url = app_url
    closing = parse_closing_date(text)
    if closing:
        job.metadata["closing_date"] = closing
    ref = _extract_reference(text)
    if ref:
        job.metadata["reference_number"] = ref
    subject = _extract_subject(text)
    if subject:
        job.metadata["application_subject"] = subject
    job.metadata.setdefault("source_provenance", []).append({"source": "ACBAR detail", "url": job.url, "field": "vacancy page"})
    return job


async def discover_reliefweb_jobs(profile: dict[str, Any]) -> list[Job]:
    cfg = ((profile.get("job_sources") or {}).get("reliefweb") or {}) if isinstance(profile, dict) else {}
    timeout = float(cfg.get("timeout_seconds", 25))
    limit = int(cfg.get("limit", 20))
    url = cfg.get("url") or "https://reliefweb.int/jobs?search=Afghanistan%20health%20medical%20nutrition"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        response = await client.get(url)
        response.raise_for_status()
    return _parse_reliefweb_listing(response.text, url, limit=limit)


def _parse_reliefweb_listing(html: str, base_url: str, *, limit: int) -> list[Job]:
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[Job] = []
    for anchor in soup.select('a[href*="/job/"]'):
        title = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, anchor.get("href", ""))
        if not title or not href:
            continue
        card = anchor.find_parent(["article", "li", "div"]) or anchor.parent
        context = normalize_space(card.get_text(" ", strip=True) if card else title)
        if "afghanistan" not in context.lower() and "afghanistan" not in title.lower():
            continue
        if not _job_is_relevant(Job("", title, "", "", href, href, "reliefweb", context)):
            continue
        company = _guess_reliefweb_company(context) or "ReliefWeb source"
        closing = parse_closing_date(context) or ""
        jobs.append(
            Job(
                id=stable_job_id("reliefweb", href, title, company),
                title=title,
                company=company,
                location="Afghanistan",
                url=href,
                apply_url=href,
                platform="reliefweb",
                description=context,
                metadata={
                    "source": "ReliefWeb",
                    "source_tier": "B",
                    "source_url": href,
                    "closing_date": closing,
                    "source_provenance": [{"source": "ReliefWeb listing", "url": base_url, "field": "listing card"}],
                },
            )
        )
        if len(jobs) >= limit:
            break
    return deduplicate_jobs(jobs)


def _guess_company_from_listing_context(context: str, title: str) -> str:
    text = context.replace(title, " ", 1)
    text = re.sub(r"\bNEW\b|\bFull Time\b|\bPart Time\b", " ", text, flags=re.I)
    text = re.sub(r"\b\d+\s+(?:minutes?|hours?|days?|weeks?)\s+ago\b", " ", text, flags=re.I)
    text = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", text)
    parts = [normalize_space(p) for p in re.split(r"[•\n]+", text) if normalize_space(p)]
    for part in parts:
        if not _guess_location(part) and len(part) <= 100:
            return part
    return ""


def _guess_location(text: str) -> str:
    provinces = [
        "Badakhshan", "Badghis", "Baghlan", "Balkh", "Bamian", "Daikondi", "Farah", "Faryab", "Ghazni",
        "Ghowr", "Ghor", "Helmand", "Herat", "Jawzjan", "Kabul", "Kandahar", "Kapisa", "Khost", "Kunar",
        "Kunduz", "Laghman", "Logar", "Maidan Wardak", "Nangarhar", "Nimruz", "Nuristan", "Oruzgan",
        "Paktia", "Paktika", "Panjshir", "Parwan", "Samangan", "Sar-e Pol", "Takhar", "Zabul",
    ]
    found = []
    lower = text.lower()
    for province in provinces:
        if re.search(rf"\b{re.escape(province.lower())}\b", lower):
            found.append(province)
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
