"""
Job discovery for an Afghanistan-first, MD-first assistant.

The discovery layer keeps existing ATS support (Greenhouse, Lever, career pages,
URL resolution downstream) but defaults to high-value Afghanistan medical
sources.  Each source is optional and failure-isolated; one broken source never
breaks the full discovery run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

from utils.medical_requirements import MEDICAL_DISCOVERY_KEYWORDS, extract_requirements_from_job, looks_medical, parse_closing_date, strip_html


@dataclass
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
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class RawVacancy:
    """Source-adapter output before normalization.

    Adapters should preserve source provenance and avoid eligibility decisions.
    The normalized pipeline converts this into the existing ``Job`` shape so the
    application-preparation workflow remains unchanged.
    """

    source: str
    source_type: str
    source_url: str
    original_url: str
    organization: str
    title: str
    location: str = ""
    description: str = ""
    application_url: str = ""
    application_email: str = ""
    application_subject: str = ""
    posting_date: str = ""
    closing_date: str = ""
    reference_number: str = ""
    department: str = ""
    reliability: str = "medium"
    provenance: list[dict[str, str]] = field(default_factory=list)
    discovered_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedVacancy:
    """Canonical vacancy model used by the discovery pipeline."""

    id: str
    source: str
    source_url: str
    original_vacancy_url: str
    organization: str
    title: str
    location: str
    posting_date: str
    closing_date: str
    reference_number: str
    description: str
    application_route: str
    application_url: str
    application_email: str
    application_subject: str
    source_provenance: list[dict[str, str]]
    discovery_timestamp: str
    source_reliability: str
    source_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalization / validation / freshness
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _stable_job_id(source: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{_canonical(source) or 'source'}_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def normalize_raw_vacancy(raw: RawVacancy | dict[str, Any]) -> NormalizedVacancy:
    """Normalize one adapter vacancy without changing the downstream Job API."""
    if isinstance(raw, dict):
        raw = RawVacancy(**raw)
    discovered_at = raw.discovered_at or _utc_now_iso()
    facts_source = "\n".join([raw.title, raw.location, raw.description, raw.application_url, raw.application_email])
    closing_date = raw.closing_date or parse_closing_date(facts_source) or ""
    application_route = raw.application_email or raw.application_url or raw.original_url
    source_urls = []
    for value in [raw.source_url, raw.original_url, raw.application_url]:
        if value and value not in source_urls:
            source_urls.append(value)
    provenance = raw.provenance or [{"source": raw.source, "url": raw.source_url or raw.original_url, "reliability": raw.reliability}]
    metadata = dict(raw.raw or {})
    metadata.update(
        {
            "source": raw.source,
            "source_type": raw.source_type,
            "source_url": raw.source_url,
            "original_vacancy_url": raw.original_url,
            "source_urls": source_urls,
            "posting_date": raw.posting_date,
            "closing_date": closing_date,
            "reference_number": raw.reference_number,
            "application_email": raw.application_email,
            "application_subject": raw.application_subject,
            "discovered_at": discovered_at,
            "source_reliability": raw.reliability,
            "source_provenance": provenance,
        }
    )
    normalized = NormalizedVacancy(
        id=_stable_job_id(raw.source, raw.original_url, raw.title, raw.organization),
        source=raw.source,
        source_url=raw.source_url,
        original_vacancy_url=raw.original_url,
        organization=raw.organization or "Unknown",
        title=raw.title or "Untitled vacancy",
        location=raw.location or "Afghanistan",
        posting_date=raw.posting_date,
        closing_date=closing_date,
        reference_number=raw.reference_number,
        description=raw.description or "",
        application_route=application_route,
        application_url=raw.application_url if raw.application_url and raw.application_url.startswith(("http://", "https://")) else "",
        application_email=raw.application_email,
        application_subject=raw.application_subject,
        source_provenance=provenance,
        discovery_timestamp=discovered_at,
        source_reliability=raw.reliability,
        source_urls=source_urls,
        metadata=metadata,
    )
    return normalized


def normalized_to_job(vacancy: NormalizedVacancy) -> Job:
    """Convert a normalized vacancy into the existing Job dataclass."""
    apply_url = vacancy.application_email or vacancy.application_url or vacancy.application_route or vacancy.original_vacancy_url
    job = Job(
        id=vacancy.id,
        title=vacancy.title,
        company=vacancy.organization,
        location=vacancy.location,
        url=vacancy.original_vacancy_url,
        apply_url=apply_url,
        platform=vacancy.source,
        description=vacancy.description,
        department=vacancy.metadata.get("department", ""),
        metadata=vacancy.metadata,
    )
    _enrich_job(job)
    return job


def raw_vacancies_to_jobs(raw_vacancies: list[RawVacancy | dict[str, Any]]) -> list[Job]:
    jobs = []
    for raw in raw_vacancies:
        normalized = normalize_raw_vacancy(raw)
        if not validate_normalized_vacancy(normalized)[0]:
            continue
        jobs.append(normalized_to_job(normalized))
    return jobs


def validate_normalized_vacancy(vacancy: NormalizedVacancy) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not vacancy.title or vacancy.title == "Untitled vacancy":
        errors.append("missing title")
    if not vacancy.organization or vacancy.organization == "Unknown":
        errors.append("missing organization")
    if not vacancy.original_vacancy_url:
        errors.append("missing original vacancy URL")
    if not vacancy.source:
        errors.append("missing source")
    return not errors, errors


def is_job_fresh(job: Job | dict[str, Any], *, today: date | None = None) -> bool:
    """Return False only when a parsed closing date has definitely passed."""
    today = today or date.today()
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    closing = metadata.get("closing_date") or metadata.get("deadline")
    if not closing:
        return True
    try:
        return date.fromisoformat(str(closing)) >= today
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _canonical(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _metadata(job: Job | dict[str, Any]) -> dict[str, Any]:
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def vacancy_keys(job: Job | dict[str, Any]) -> list[str]:
    """Return candidate duplicate keys, strongest first."""
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = _metadata(job)
    keys: list[str] = []
    reference = metadata.get("reference_number") or metadata.get("requisition_id")
    company = get("company", "") or metadata.get("organization", "") or ""
    title = get("title", "") or ""
    location = get("location", "") or ""
    if reference:
        keys.append("ref:" + _canonical(f"{company} {reference}"))
    if title and company and location:
        keys.append("title:" + _canonical(f"{title} {company} {location}"))
    for url_key in ["original_vacancy_url", "source_url"]:
        value = metadata.get(url_key)
        if value:
            keys.append("url:" + _canonical(value))
    apply_url = get("apply_url", "") or get("url", "")
    # Email destinations are often shared across many vacancies from the same
    # employer, so an email/mailto value is not a safe duplicate key. Strong
    # source URLs/references and title+company+location remain available.
    if apply_url and not str(apply_url).lower().startswith("mailto:") and "@" not in str(apply_url):
        keys.append("url:" + _canonical(apply_url))
    if not keys:
        keys.append("title:" + _canonical(f"{title} {company} {location}"))
    return [key for key in keys if key and key != "title:"]


def job_fingerprint(job: Job | dict[str, Any]) -> str:
    return vacancy_keys(job)[0]


def _append_unique(items: list[Any], values: list[Any]) -> list[Any]:
    for value in values:
        if value and value not in items:
            items.append(value)
    return items


def merge_duplicate_job(primary: Job, duplicate: Job) -> Job:
    """Merge duplicate source provenance into the canonical vacancy."""
    primary.metadata = primary.metadata or {}
    duplicate.metadata = duplicate.metadata or {}
    primary.metadata.setdefault("duplicate_ids", [])
    _append_unique(primary.metadata["duplicate_ids"], [duplicate.id])
    primary.metadata.setdefault("merged_sources", [])
    _append_unique(primary.metadata["merged_sources"], [primary.platform, duplicate.platform])
    primary.metadata["source_urls"] = _append_unique(
        list(primary.metadata.get("source_urls") or [primary.url]),
        list(duplicate.metadata.get("source_urls") or [duplicate.url]),
    )
    primary.metadata["source_provenance"] = _append_unique(
        list(primary.metadata.get("source_provenance") or []),
        list(duplicate.metadata.get("source_provenance") or []),
    )
    for key in ["application_email", "application_subject", "reference_number", "closing_date", "date_posted"]:
        if not primary.metadata.get(key) and duplicate.metadata.get(key):
            primary.metadata[key] = duplicate.metadata[key]
    if not primary.apply_url and duplicate.apply_url:
        primary.apply_url = duplicate.apply_url
    if len(duplicate.description or "") > len(primary.description or ""):
        primary.description = duplicate.description
    duplicate.metadata["duplicate_of"] = primary.id
    return primary


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """Deduplicate vacancies while retaining all known source URLs/provenance."""
    seen: dict[str, Job] = {}
    unique: list[Job] = []
    for job in jobs:
        matched = None
        for key in vacancy_keys(job):
            if key in seen:
                candidate = seen[key]
                # Title/company/location is useful for cross-source merges, but
                # too broad within a single source where several similar posts
                # can share title, organization, and province. Strong URL/ref
                # keys still merge within the same source.
                if key.startswith("title:") and candidate.platform == job.platform:
                    continue
                matched = candidate
                break
        if matched:
            merge_duplicate_job(matched, job)
            for key in vacancy_keys(job):
                seen.setdefault(key, matched)
            continue
        unique.append(job)
        for key in vacancy_keys(job):
            seen[key] = job
    return unique


# ---------------------------------------------------------------------------
# ATS sources retained from the original project
# ---------------------------------------------------------------------------


def _medical_filter(title: str, description: str, role_keywords: list[str]) -> bool:
    combined = f"{title}\n{description}"
    if looks_medical(combined):
        return True
    keywords = [str(k).lower() for k in (role_keywords or [])] + MEDICAL_DISCOVERY_KEYWORDS
    lower = combined.lower()
    return any(kw and kw.lower() in lower for kw in keywords)


async def discover_greenhouse_jobs(company_slug: str, role_keywords: list[str]) -> list[Job]:
    """Discover relevant medical jobs from a Greenhouse board."""
    import httpx

    jobs: list[Job] = []
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"  ⚠ Greenhouse [{company_slug}]: {e}")
        return jobs

    for job_data in data.get("jobs", []):
        title = job_data.get("title", "")
        raw_desc = job_data.get("content", "")
        description = re.sub(r"\s+", " ", strip_html(raw_desc)).strip()
        if not _medical_filter(title, description, role_keywords):
            continue
        location = job_data.get("location", {}).get("name", "Unknown")
        job_id = str(job_data.get("id") or hashlib.sha256(f"{company_slug}{title}".encode()).hexdigest()[:12])
        apply_url = f"https://boards.greenhouse.io/{company_slug}/jobs/{job_id}#app"
        metadata = {
            "updated_at": job_data.get("updated_at", ""),
            "requisition_id": job_data.get("requisition_id", ""),
            "source": "greenhouse",
            "source_url": f"https://boards.greenhouse.io/{company_slug}",
            "reference_number": job_data.get("requisition_id", ""),
        }
        job = Job(
            id=f"greenhouse_{job_id}",
            title=title,
            company=company_slug,
            location=location,
            url=f"https://boards.greenhouse.io/{company_slug}/jobs/{job_id}",
            apply_url=apply_url,
            platform="greenhouse",
            description=description[:8000],
            department=", ".join(d.get("name", "") for d in job_data.get("departments", [])),
            metadata=metadata,
        )
        _enrich_job(job)
        jobs.append(job)
    return jobs


async def discover_lever_jobs(company_slug: str, role_keywords: list[str]) -> list[Job]:
    """Discover relevant medical jobs from a Lever board."""
    import httpx

    jobs: list[Job] = []
    api_url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"  ⚠ Lever [{company_slug}]: {e}")
        return jobs

    for posting in data:
        title = posting.get("text", "")
        description = posting.get("descriptionPlain", "") or strip_html(posting.get("description", ""))
        if not _medical_filter(title, description, role_keywords):
            continue
        categories = posting.get("categories", {})
        location = categories.get("location", "Unknown")
        job = Job(
            id=f"lever_{posting.get('id')}",
            title=title,
            company=company_slug,
            location=location,
            url=posting.get("hostedUrl", ""),
            apply_url=posting.get("applyUrl", posting.get("hostedUrl", "")),
            platform="lever",
            description=description[:8000],
            department=categories.get("team", ""),
            metadata={
                "commitment": categories.get("commitment", ""),
                "created_at": posting.get("createdAt", ""),
                "source": "lever",
                "source_url": f"https://jobs.lever.co/{company_slug}",
            },
        )
        _enrich_job(job)
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def _audit_source(profile: dict, bucket: str, value: Any) -> None:
    """Optional scan audit hook used by the job watcher."""
    if not isinstance(profile, dict):
        return
    audit = profile.setdefault("_watcher_source_audit", {"attempted": [], "successful": [], "failed": []})
    if not isinstance(audit, dict):
        return
    audit.setdefault("attempted", [])
    audit.setdefault("successful", [])
    audit.setdefault("failed", [])
    if bucket == "failed":
        if value not in audit["failed"]:
            audit["failed"].append(value)
        return
    if value and value not in audit[bucket]:
        audit[bucket].append(value)


async def discover_all_jobs(profile: dict) -> list[Job]:
    """
    Discover jobs from configured Afghanistan-first sources and selected ATSs.
    Failed sources are logged and skipped.

    When called by the watcher, source outcomes are written into the caller's
    ``_watcher_source_audit`` dict so failures/no-job successes are visible in
    scan audits instead of being hidden behind stale vacancies.
    """
    from utils.source_registry import registry_enhanced_profile, registry_enabled

    caller_profile = profile
    shared_audit = None
    if isinstance(caller_profile, dict):
        shared_audit = caller_profile.setdefault("_watcher_source_audit", {"attempted": [], "successful": [], "failed": []})
    profile = registry_enhanced_profile(profile)
    if shared_audit is not None:
        profile["_watcher_source_audit"] = shared_audit
    all_jobs: list[Job] = []
    prefs = profile.get("preferences", {})
    role_keywords = prefs.get("roles", []) or MEDICAL_DISCOVERY_KEYWORDS
    boards = profile.get("target_boards", {}) or profile.get("job_sources", {}).get("ats", {}) or {}
    sources = profile.get("job_sources", {}) if isinstance(profile.get("job_sources"), dict) else {}
    using_registry = registry_enabled(profile) and sources.get("_source_registry_enabled")
    active_methods = set(sources.get("_source_registry_active_methods", []))

    def source_method_enabled(method: str, legacy_key: str) -> bool:
        if using_registry:
            return method in active_methods
        configured = sources.get(legacy_key, {})
        if legacy_key in {"registry_static_sources", "oracle_hcm_sources"}:
            return bool(configured)
        if isinstance(configured, dict):
            return configured.get("enabled", True)
        if isinstance(configured, list):
            return bool(configured)
        return True

    async def _run_source(label: str, coro):
        _audit_source(profile, "attempted", label)
        audit = profile.get("_watcher_source_audit", {}) if isinstance(profile, dict) else {}
        failed_before = len(audit.get("failed", [])) if isinstance(audit, dict) else 0
        try:
            jobs = await coro
            for job in jobs:
                _enrich_job(job)
            all_jobs.extend(jobs)
            failed_after = len(audit.get("failed", [])) if isinstance(audit, dict) else failed_before
            if jobs or failed_after == failed_before:
                _audit_source(profile, "successful", label)
            if jobs:
                print(f"   ✅ {label}: {len(jobs)} jobs")
        except Exception as exc:
            _audit_source(profile, "failed", {"source": label, "error": str(exc)})
            print(f"  ⚠ {label} failed: {exc}")

    # Highest-value Afghanistan medical sources.
    if source_method_enabled("acbar_html", "acbar"):
        from utils.afghan_sources import discover_acbar_jobs

        print("\n🇦🇫 Scanning ACBAR / Afghan NGO jobs...")
        await _run_source("ACBAR", discover_acbar_jobs(profile))

    if source_method_enabled("reliefweb_api_or_html", "reliefweb"):
        from utils.afghan_sources import discover_reliefweb_jobs

        print("\n🏥 Scanning ReliefWeb Afghanistan health jobs...")
        await _run_source("ReliefWeb", discover_reliefweb_jobs(profile))

    if source_method_enabled("unjobs_html", "unjobs"):
        from utils.afghan_sources import discover_unjobs_jobs

        print("\n🇺🇳 Scanning UNJobs Afghanistan public listings...")
        await _run_source("UNJobs", discover_unjobs_jobs(profile))

    if source_method_enabled("unicef_careers_html", "unicef"):
        from utils.afghan_sources import discover_unicef_jobs

        print("\n🧒 Scanning UNICEF official Afghanistan careers...")
        await _run_source("UNICEF Careers", discover_unicef_jobs(profile))

    if source_method_enabled("registry_static_html", "registry_static_sources") or source_method_enabled("official_career_page_static", "registry_static_sources"):
        from utils.afghan_sources import discover_registry_static_sources

        print("\n🗂 Scanning registry-managed static sources...")
        await _run_source("Registry static sources", discover_registry_static_sources(profile))

    if source_method_enabled("oracle_hcm_api", "oracle_hcm_sources"):
        from utils.afghan_sources import discover_oracle_hcm_jobs

        print("\n🏛 Scanning registry-managed Oracle HCM sources...")
        await _run_source("Oracle HCM sources", discover_oracle_hcm_jobs(profile))

    if sources.get("official_career_pages") or profile.get("custom_career_pages"):
        from utils.afghan_sources import discover_official_career_pages

        print("\n🌐 Scanning configured official career pages...")
        await _run_source("Official career pages", discover_official_career_pages(profile))

    # Targeted ATS boards (WHO/UNICEF/NGO boards can be added here by slug).
    gh_companies = boards.get("greenhouse", [])
    if gh_companies:
        print(f"\n🌿 Scanning {len(gh_companies)} Greenhouse boards...")
        for slug in gh_companies:
            _audit_source(profile, "attempted", f"Greenhouse:{slug}")
        results = await asyncio.gather(*(discover_greenhouse_jobs(slug, role_keywords) for slug in gh_companies), return_exceptions=True)
        for slug, result in zip(gh_companies, results):
            label = f"Greenhouse:{slug}"
            if isinstance(result, Exception):
                _audit_source(profile, "failed", {"source": label, "error": str(result)})
                print(f"  ⚠ Greenhouse [{slug}] failed: {result}")
            else:
                all_jobs.extend(result)
                _audit_source(profile, "successful", label)
                if result:
                    print(f"   ✅ {slug}: {len(result)} jobs")

    lever_companies = boards.get("lever", [])
    if lever_companies:
        print(f"\n🔧 Scanning {len(lever_companies)} Lever boards...")
        for slug in lever_companies:
            _audit_source(profile, "attempted", f"Lever:{slug}")
        results = await asyncio.gather(*(discover_lever_jobs(slug, role_keywords) for slug in lever_companies), return_exceptions=True)
        for slug, result in zip(lever_companies, results):
            label = f"Lever:{slug}"
            if isinstance(result, Exception):
                _audit_source(profile, "failed", {"source": label, "error": str(result)})
                print(f"  ⚠ Lever [{slug}] failed: {result}")
            else:
                all_jobs.extend(result)
                _audit_source(profile, "successful", label)
                if result:
                    print(f"   ✅ {slug}: {len(result)} jobs")

    # Generic aggregators are opt-in to avoid turning the product generic/noisy.
    search_config = profile.get("search", {}) if isinstance(profile.get("search"), dict) else {}
    if search_config.get("generic_job_boards_enabled", False):
        _audit_source(profile, "attempted", "Generic job boards")
        try:
            from utils.jobspy_source import discover_jobspy_jobs

            print("\n🔍 Searching generic job boards (opt-in)...")
            generic_jobs = [job for job in discover_jobspy_jobs(profile) if looks_medical(f"{job.title}\n{job.description}")]
            all_jobs.extend(generic_jobs)
            _audit_source(profile, "successful", "Generic job boards")
        except Exception as e:
            _audit_source(profile, "failed", {"source": "Generic job boards", "error": str(e)})
            print(f"  ⚠ Generic job board search failed: {e}")

    before_freshness = len(all_jobs)
    all_jobs = [job for job in all_jobs if is_job_fresh(job)]
    if before_freshness != len(all_jobs):
        print(f"\n🗓 Filtered closed vacancies: {before_freshness} -> {len(all_jobs)} still open/undated")

    before = len(all_jobs)
    all_jobs = deduplicate_jobs(all_jobs)
    if before != len(all_jobs):
        print(f"\n🔄 Deduplicated: {before} -> {len(all_jobs)} unique jobs")

    print(f"\n📊 Total: {len(all_jobs)} Afghanistan medical jobs found")
    return all_jobs


def _enrich_job(job: Job) -> None:
    """Attach deterministic requirement facts/provenance to job.metadata."""
    try:
        extracted = extract_requirements_from_job(job).to_dict()
        facts = extracted.get("facts", {})
        job.metadata = job.metadata or {}
        for key in ["reference_number", "application_email", "application_subject", "closing_date", "application_url_valid"]:
            if facts.get(key) is not None and facts.get(key) != "":
                job.metadata[key] = facts.get(key)
        if facts.get("application_url") and (not job.apply_url or not facts.get("application_url_valid")):
            job.apply_url = facts["application_url"]
        job.metadata["requirements"] = extracted
        job.metadata.setdefault("source_url", job.url)
    except Exception as exc:
        job.metadata = job.metadata or {}
        job.metadata["requirements_error"] = str(exc)
