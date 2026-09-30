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
from typing import Any

from utils.medical_requirements import MEDICAL_DISCOVERY_KEYWORDS, extract_requirements_from_job, looks_medical, strip_html


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


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _canonical(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def job_fingerprint(job: Job | dict[str, Any]) -> str:
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    reference = metadata.get("reference_number") or metadata.get("requisition_id")
    if reference:
        return "ref:" + _canonical(f"{get('company','')} {reference}")
    apply_url = get("apply_url", "") or get("url", "")
    if apply_url:
        return "url:" + _canonical(apply_url)
    return "title:" + _canonical(f"{get('title','')} {get('company','')} {get('location','')}")


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """Deduplicate by reference number, canonical URL, then title/company/location."""
    seen: dict[str, Job] = {}
    unique: list[Job] = []
    for job in jobs:
        key = job_fingerprint(job)
        if key in seen:
            job.metadata["duplicate_of"] = seen[key].id
            continue
        seen[key] = job
        unique.append(job)
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


async def discover_all_jobs(profile: dict) -> list[Job]:
    """
    Discover jobs from configured Afghanistan-first sources and selected ATSs.
    Failed sources are logged and skipped.
    """
    all_jobs: list[Job] = []
    prefs = profile.get("preferences", {})
    role_keywords = prefs.get("roles", []) or MEDICAL_DISCOVERY_KEYWORDS
    boards = profile.get("target_boards", {}) or profile.get("job_sources", {}).get("ats", {}) or {}
    sources = profile.get("job_sources", {}) if isinstance(profile.get("job_sources"), dict) else {}

    async def _run_source(label: str, coro):
        try:
            jobs = await coro
            for job in jobs:
                _enrich_job(job)
            all_jobs.extend(jobs)
            if jobs:
                print(f"   ✅ {label}: {len(jobs)} jobs")
        except Exception as exc:
            print(f"  ⚠ {label} failed: {exc}")

    # Highest-value Afghanistan medical sources.
    if sources.get("acbar", {}).get("enabled", True):
        from utils.afghan_sources import discover_acbar_jobs

        print("\n🇦🇫 Scanning ACBAR / Afghan NGO jobs...")
        await _run_source("ACBAR", discover_acbar_jobs(profile))

    if sources.get("reliefweb", {}).get("enabled", True):
        from utils.afghan_sources import discover_reliefweb_jobs

        print("\n🏥 Scanning ReliefWeb Afghanistan health jobs...")
        await _run_source("ReliefWeb", discover_reliefweb_jobs(profile))

    if sources.get("official_career_pages") or profile.get("custom_career_pages"):
        from utils.afghan_sources import discover_official_career_pages

        print("\n🌐 Scanning configured official career pages...")
        await _run_source("Official career pages", discover_official_career_pages(profile))

    # Targeted ATS boards (WHO/UNICEF/NGO boards can be added here by slug).
    gh_companies = boards.get("greenhouse", [])
    if gh_companies:
        print(f"\n🌿 Scanning {len(gh_companies)} Greenhouse boards...")
        results = await asyncio.gather(*(discover_greenhouse_jobs(slug, role_keywords) for slug in gh_companies), return_exceptions=True)
        for slug, result in zip(gh_companies, results):
            if isinstance(result, Exception):
                print(f"  ⚠ Greenhouse [{slug}] failed: {result}")
            else:
                all_jobs.extend(result)
                if result:
                    print(f"   ✅ {slug}: {len(result)} jobs")

    lever_companies = boards.get("lever", [])
    if lever_companies:
        print(f"\n🔧 Scanning {len(lever_companies)} Lever boards...")
        results = await asyncio.gather(*(discover_lever_jobs(slug, role_keywords) for slug in lever_companies), return_exceptions=True)
        for slug, result in zip(lever_companies, results):
            if isinstance(result, Exception):
                print(f"  ⚠ Lever [{slug}] failed: {result}")
            else:
                all_jobs.extend(result)
                if result:
                    print(f"   ✅ {slug}: {len(result)} jobs")

    # Generic aggregators are opt-in to avoid turning the product generic/noisy.
    search_config = profile.get("search", {}) if isinstance(profile.get("search"), dict) else {}
    if search_config.get("generic_job_boards_enabled", False):
        try:
            from utils.jobspy_source import discover_jobspy_jobs

            print("\n🔍 Searching generic job boards (opt-in)...")
            all_jobs.extend([job for job in discover_jobspy_jobs(profile) if looks_medical(f"{job.title}\n{job.description}")])
        except Exception as e:
            print(f"  ⚠ Generic job board search failed: {e}")

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
