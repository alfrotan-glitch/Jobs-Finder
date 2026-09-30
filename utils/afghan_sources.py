"""
Afghanistan-first medical job sources.

Each source is optional and failure-isolated.  The goal is a small, high-value
set rather than dozens of noisy feeds:
- ACBAR and Afghan NGO pages
- ReliefWeb / UN humanitarian jobs filtered for Afghanistan + health terms
- Official organization career pages configured by the user
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from utils.medical_requirements import MEDICAL_DISCOVERY_KEYWORDS, looks_medical, normalize_text, parse_closing_date, strip_html


@dataclass
class SourceResult:
    source: str
    ok: bool
    jobs: list[Any]
    error: str = ""


DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Jobs-Finder Afghanistan Medical Assistant/2.0; +https://acbar.org)"


def _record_source_failure(profile: dict[str, Any], source: str, error: Exception | str) -> None:
    """Expose adapter-internal source failures to the watcher scan audit."""
    if not isinstance(profile, dict):
        return
    audit = profile.setdefault("_watcher_source_audit", {"attempted": [], "successful": [], "failed": []})
    if not isinstance(audit, dict):
        return
    audit.setdefault("failed", [])
    item = {"source": source, "error": str(error)}
    if item not in audit["failed"]:
        audit["failed"].append(item)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part or "" for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def medical_queries(profile: dict[str, Any]) -> list[str]:
    prefs = profile.get("preferences", {}) if isinstance(profile.get("preferences"), dict) else {}
    configured = prefs.get("roles", []) + profile.get("search", {}).get("queries", []) if isinstance(profile.get("search"), dict) else prefs.get("roles", [])
    base = [
        "Medical Officer Afghanistan",
        "Medical Doctor Afghanistan",
        "Physician Afghanistan",
        "Public Health Afghanistan",
        "Nutrition Afghanistan",
        "BPHS EPHS Afghanistan",
    ]
    for item in configured:
        if item and item not in base:
            base.insert(0, str(item))
    # Stable unique order.
    seen = set()
    out = []
    for item in base:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:8]


async def discover_acbar_jobs(profile: dict[str, Any]) -> list[Any]:
    """Scrape ACBAR job listing pages with deterministic link extraction."""
    from utils.discovery import Job

    config = profile.get("job_sources", {}).get("acbar", {}) if isinstance(profile.get("job_sources"), dict) else {}
    urls = config.get("urls") or [
        "https://www.acbar.org/en/jobs",
        "https://www.acbar.org/en/jobs?page=2",
        "https://www.acbar.org/en/jobs?page=3",
    ]
    timeout = config.get("timeout_seconds", 25)
    jobs: list[Job] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                page_text = resp.text
            except Exception as exc:
                _record_source_failure(profile, "ACBAR", exc)
                print(f"  ⚠ ACBAR source failed for {url}: {exc}")
                # Some hosting environments drop TLS handshakes to ACBAR. The
                # caller continues with other sources; in Agent Mode, web-search
                # results can still be ingested through utils.mcp_source while
                # preserving the original ACBAR URL and application instructions.
                continue
            jobs.extend(_jobs_from_html(page_text, base_url=url, source="acbar", default_company="ACBAR"))
    return jobs


async def discover_reliefweb_jobs(profile: dict[str, Any]) -> list[Any]:
    """Discover Afghanistan health/medical vacancies from ReliefWeb.

    ReliefWeb's old v1 API is decommissioned and the v2 API requires an
    approved appname.  Use v2 when configured with an appname; otherwise fall
    back to public HTML search without bypassing controls.
    """
    from utils.discovery import Job, RawVacancy, raw_vacancies_to_jobs

    config = profile.get("job_sources", {}).get("reliefweb", {}) if isinstance(profile.get("job_sources"), dict) else {}
    timeout = config.get("timeout_seconds", 25)
    limit = int(config.get("limit", 25))
    appname = config.get("appname", "")
    query = "Afghanistan health medical nutrition public health"

    if appname:
        jobs = await _discover_reliefweb_api(appname=appname, query=query, limit=limit, timeout=timeout)
        if jobs:
            return jobs

    search_url = config.get("search_url") or f"https://reliefweb.int/jobs?search={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = await client.get(search_url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        _record_source_failure(profile, "ReliefWeb", exc)
        print(f"  ⚠ ReliefWeb source failed: {exc}")
        return []

    raw_items = _reliefweb_raw_from_html(html, search_url, limit=limit)
    return raw_vacancies_to_jobs(raw_items)


async def _discover_reliefweb_api(*, appname: str, query: str, limit: int, timeout: int) -> list[Any]:
    from utils.discovery import Job

    jobs: list[Job] = []
    url = "https://api.reliefweb.int/v2/jobs"
    params = {
        "appname": appname,
        "limit": min(max(limit, 1), 50),
        "query[value]": query,
        "filter[field]": "country.name",
        "filter[value]": "Afghanistan",
        "sort[]": "date.created:desc",
        "profile": "full",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"  ⚠ ReliefWeb API unavailable: {exc}")
        return []

    for item in data.get("data", []):
        fields = item.get("fields", {})
        title = fields.get("title") or "Untitled"
        company = ""
        source = fields.get("source")
        if isinstance(source, list) and source:
            company = source[0].get("name", "")
        elif isinstance(source, dict):
            company = source.get("name", "")
        body = strip_html(fields.get("body", ""))
        url_alias = fields.get("url_alias") or item.get("href") or ""
        apply_url = fields.get("how_to_apply") or url_alias
        description = normalize_text("\n".join([body, strip_html(fields.get("how_to_apply", ""))]))[:8000]
        if not looks_medical(f"{title}\n{description}"):
            continue
        jobs.append(
            Job(
                id=_stable_id("reliefweb", str(item.get("id", "")), title, company),
                title=title,
                company=company or "ReliefWeb source",
                location="Afghanistan",
                url=url_alias,
                apply_url=apply_url if isinstance(apply_url, str) else url_alias,
                platform="reliefweb",
                description=description,
                department="Health / Humanitarian",
                metadata={
                    "source": "reliefweb",
                    "source_type": "public_job_board",
                    "source_url": url_alias,
                    "source_urls": [url_alias],
                    "date_posted": fields.get("date", {}).get("created") if isinstance(fields.get("date"), dict) else "",
                    "organization_source": company,
                    "source_reliability": "medium",
                    "source_provenance": [{"source": "ReliefWeb API", "url": url_alias, "reliability": "medium"}],
                },
            )
        )
    return jobs


async def discover_unjobs_jobs(profile: dict[str, Any]) -> list[Any]:
    """Discover Afghanistan medical/health roles from UNJobs public listings."""
    from utils.discovery import raw_vacancies_to_jobs

    config = profile.get("job_sources", {}).get("unjobs", {}) if isinstance(profile.get("job_sources"), dict) else {}
    timeout = config.get("timeout_seconds", 25)
    limit = int(config.get("limit", 50))
    urls = config.get("urls") or ["https://unjobs.org/duty_stations/afghanistan", "https://unjobs.org/duty_stations/afghanistan/2"]
    raw_items = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                raw_items.extend(_unjobs_raw_from_html(resp.text, url, limit=limit))
            except Exception as exc:
                _record_source_failure(profile, "UNJobs", exc)
                print(f"  ⚠ UNJobs source failed for {url}: {exc}")
    return raw_vacancies_to_jobs(raw_items[:limit])


async def discover_unicef_jobs(profile: dict[str, Any]) -> list[Any]:
    """Discover Afghanistan health-adjacent roles from UNICEF official careers."""
    from utils.discovery import raw_vacancies_to_jobs

    config = profile.get("job_sources", {}).get("unicef", {}) if isinstance(profile.get("job_sources"), dict) else {}
    timeout = config.get("timeout_seconds", 25)
    limit = int(config.get("limit", 25))
    url = config.get("url") or "https://jobs.unicef.org/en-us/search/?search-keyword=Afghanistan"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        _record_source_failure(profile, "UNICEF Careers", exc)
        print(f"  ⚠ UNICEF careers source failed: {exc}")
        return []
    raw_items = _unicef_raw_from_html(html, url, limit=limit)
    return raw_vacancies_to_jobs(raw_items[:limit])


def _soup(html: str):
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html or "", "html.parser")
    except Exception:
        return None


def _anchor_context(anchor: Any, *, max_lines: int = 12) -> str:
    lines = [anchor.get_text(" ", strip=True)]

    def consume(start_node: Any) -> None:
        node = start_node
        guard = 0
        while node is not None and len(lines) < max_lines and guard < 80:
            guard += 1
            name = getattr(node, "name", None)
            if name == "a" and node.get("href") and ("/vacancies/" in node.get("href") or "/job/" in node.get("href")):
                break
            if hasattr(node, "find_all") and node.find("a", href=re.compile(r"/(?:vacancies|job)/")):
                break
            text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node).strip()
            if text:
                for line in re.split(r"\n+", text):
                    clean = normalize_text(line)
                    if clean and clean not in lines:
                        lines.append(clean)
                        if len(lines) >= max_lines:
                            break
            node = node.next_sibling

    consume(anchor.next_sibling)
    if len(lines) < max_lines and getattr(anchor, "parent", None) is not None:
        consume(anchor.parent.next_sibling)
    return "\n".join(lines)


def _first_context_line(context: str, *, skip: list[str] | None = None) -> str:
    skip = skip or []
    for line in [normalize_text(item) for item in context.splitlines()]:
        lower = line.lower()
        if not line or any(term in lower for term in skip):
            continue
        return line
    return ""


def _reliefweb_raw_from_html(html: str, source_url: str, *, limit: int) -> list[Any]:
    from utils.discovery import RawVacancy

    soup = _soup(html)
    if not soup:
        return []
    raw_items: list[RawVacancy] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(source_url, anchor.get("href", ""))
        title = normalize_text(anchor.get_text(" ", strip=True))
        if "/job/" not in href and "/jobs/" not in href:
            continue
        if not title or len(title) < 4:
            continue
        context = _anchor_context(anchor, max_lines=14)
        if "afghanistan" not in context.lower() and "afghanistan" not in title.lower():
            continue
        if not looks_medical(f"{title}\n{context}"):
            continue
        organization = _first_context_line(context.replace(title, "", 1), skip=["updated", "closing", "deadline", "location"])
        raw_items.append(
            RawVacancy(
                source="reliefweb",
                source_type="public_job_board",
                source_url=source_url,
                original_url=href,
                organization=organization or "ReliefWeb source",
                title=title,
                location=_extract_location_hint(title, context) or "Afghanistan",
                description=context[:8000],
                application_url=href,
                closing_date=parse_closing_date(context) or "",
                reliability="medium",
                provenance=[{"source": "ReliefWeb public search page", "url": source_url, "reliability": "medium"}],
                raw={"department": "Health / Humanitarian"},
            )
        )
        if len(raw_items) >= limit:
            break
    return raw_items


def _unjobs_raw_from_html(html: str, source_url: str, *, limit: int) -> list[Any]:
    from utils.discovery import RawVacancy

    soup = _soup(html)
    if not soup:
        return []
    raw_items: list[RawVacancy] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(source_url, anchor.get("href", ""))
        if "/vacancies/" not in href:
            continue
        title = normalize_text(anchor.get_text(" ", strip=True))
        if not title or not looks_medical(title):
            context = _anchor_context(anchor, max_lines=10)
            if not looks_medical(f"{title}\n{context}"):
                continue
        else:
            context = _anchor_context(anchor, max_lines=10)
        organization = _first_context_line(context.replace(title, "", 1), skip=["updated", "closing date", "active locations", "active organizations"])
        raw_items.append(
            RawVacancy(
                source="unjobs",
                source_type="public_job_board",
                source_url=source_url,
                original_url=href,
                organization=organization or "UNJobs source",
                title=title,
                location=_extract_location_hint(title, context) or "Afghanistan",
                description=context[:8000],
                application_url=href,
                closing_date=parse_closing_date(context) or "",
                reliability="medium",
                provenance=[
                    {"source": "UNJobs public listing", "url": source_url, "reliability": "medium"},
                    {"source": "UNJobs note", "url": "https://unjobs.org", "reliability": "medium", "quote": "UNJobs states listings are not official UN documents; verify employer route before applying."},
                ],
                raw={"department": "UN / International public listing"},
            )
        )
        if len(raw_items) >= limit:
            break
    return raw_items


def _unicef_raw_from_html(html: str, source_url: str, *, limit: int) -> list[Any]:
    from utils.discovery import RawVacancy

    soup = _soup(html)
    if not soup:
        return []
    raw_items: list[RawVacancy] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(source_url, anchor.get("href", ""))
        if "/job/" not in href:
            continue
        title = normalize_text(anchor.get_text(" ", strip=True))
        context = _anchor_context(anchor, max_lines=14)
        if "afghanistan" not in f"{title}\n{context}".lower():
            continue
        if not looks_medical(f"{title}\n{context}"):
            continue
        raw_items.append(
            RawVacancy(
                source="unicef_careers",
                source_type="official_employer_career_page",
                source_url=source_url,
                original_url=href,
                organization="UNICEF - United Nations Children's Fund",
                title=title,
                location=_extract_location_hint(title, context) or "Afghanistan",
                description=context[:8000],
                application_url=href,
                closing_date=parse_closing_date(context) or "",
                reliability="high",
                provenance=[{"source": "UNICEF official careers", "url": source_url, "reliability": "high"}],
                raw={"department": "UNICEF Careers"},
            )
        )
        if len(raw_items) >= limit:
            break
    return raw_items


def _audit_profile_source(profile: dict[str, Any], bucket: str, value: Any) -> None:
    audit = profile.setdefault("_watcher_source_audit", {"attempted": [], "successful": [], "failed": []}) if isinstance(profile, dict) else None
    if not isinstance(audit, dict):
        return
    audit.setdefault("attempted", [])
    audit.setdefault("successful", [])
    audit.setdefault("failed", [])
    if bucket == "failed":
        if value not in audit["failed"]:
            audit["failed"].append(value)
    elif value and value not in audit[bucket]:
        audit[bucket].append(value)


async def discover_registry_static_sources(profile: dict[str, Any]) -> list[Any]:
    """Scan registry-managed public/static sources with one conservative parser."""
    from utils.discovery import Job

    records = profile.get("job_sources", {}).get("registry_static_sources", []) if isinstance(profile.get("job_sources"), dict) else []
    if not records:
        return []

    timeout = profile.get("job_sources", {}).get("career_page_timeout_seconds", 25) if isinstance(profile.get("job_sources"), dict) else 25
    jobs: list[Job] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for record in records:
            url = record.get("official_jobs_url") or record.get("official_website")
            source_id = record.get("id") or record.get("organization_name") or url
            if not url or str(url).startswith("mailto:"):
                continue
            _audit_profile_source(profile, "attempted", source_id)
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                _audit_profile_source(profile, "failed", {"source": source_id, "error": str(exc)})
                print(f"  ⚠ Registry source failed for {record.get('organization_name', url)}: {exc}")
                continue
            config = record.get("adapter_config", {}) if isinstance(record.get("adapter_config"), dict) else {}
            extracted = _jobs_from_html(
                html,
                base_url=url,
                source=record.get("id", "registry_static_source"),
                default_company=record.get("organization_name") or _domain_company(url),
                source_type=record.get("source_type"),
                source_record=record,
                require_afghanistan=bool(config.get("require_afghanistan", True)),
            )
            limit = int(config.get("limit", 50))
            if config.get("fetch_detail_pages", True):
                for job in extracted[:limit]:
                    await _enrich_static_job_from_detail(client, job, record)
            jobs.extend(extracted[:limit])
            _audit_profile_source(profile, "successful", source_id)
    return jobs


async def discover_oracle_hcm_jobs(profile: dict[str, Any]) -> list[Any]:
    """Discover vacancies from public Oracle HCM Candidate Experience APIs.

    This reuses the same Oracle REST endpoints used by the public careers pages;
    it does not bypass login or application controls.
    """
    from utils.discovery import RawVacancy, raw_vacancies_to_jobs

    records = profile.get("job_sources", {}).get("oracle_hcm_sources", []) if isinstance(profile.get("job_sources"), dict) else []
    timeout = profile.get("job_sources", {}).get("career_page_timeout_seconds", 25) if isinstance(profile.get("job_sources"), dict) else 25
    raw_items: list[RawVacancy] = []
    if not records:
        return []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for record in records:
            source_id = record.get("id") or record.get("organization_name") or "oracle_hcm"
            _audit_profile_source(profile, "attempted", source_id)
            config = record.get("adapter_config", {}) if isinstance(record.get("adapter_config"), dict) else {}
            base_url = (config.get("oracle_base_url") or _oracle_base_from_url(record.get("official_jobs_url", "")) or record.get("official_jobs_url") or "").rstrip("/")
            site_number = config.get("site_number") or _site_number_from_oracle_url(record.get("official_jobs_url", ""))
            location = config.get("location", "Afghanistan")
            limit = int(config.get("limit", 25))
            if not base_url or not site_number:
                _audit_profile_source(profile, "failed", {"source": source_id, "error": "Missing Oracle base URL or site number"})
                continue
            search_url = (
                f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                f"?onlyData=true&expand=requisitionList.secondaryLocations"
                f"&finder=findReqs;siteNumber={site_number},location={quote_plus(location)},limit={limit}"
            )
            try:
                resp = await client.get(search_url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                _audit_profile_source(profile, "failed", {"source": source_id, "error": str(exc)})
                print(f"  ⚠ Oracle HCM source failed for {record.get('organization_name', base_url)}: {exc}")
                continue
            _audit_profile_source(profile, "successful", source_id)
            requisitions = []
            for item in data.get("items", []):
                requisitions.extend(item.get("requisitionList", []) or [])
            for requisition in requisitions[:limit]:
                if not _oracle_requisition_in_afghanistan(requisition):
                    continue
                detail = await _fetch_oracle_hcm_detail(client, base_url, str(requisition.get("Id", "")))
                combined = _oracle_hcm_description(requisition, detail)
                include_non_medical = bool(config.get("include_non_medical_afghanistan_roles", False))
                if not include_non_medical and not looks_medical(f"{requisition.get('Title', '')}\n{combined}"):
                    continue
                original_url = f"{base_url}/hcmUI/CandidateExperience/en/sites/{site_number}/job/{requisition.get('Id')}"
                locations = _oracle_locations(requisition, detail)
                title = normalize_text(str(detail.get("Title") or requisition.get("Title") or ""))
                organization = record.get("organization_name") or _domain_company(base_url)
                raw_items.append(
                    RawVacancy(
                        source=record.get("id", "oracle_hcm"),
                        source_type=record.get("source_type", "official_employer_career_page"),
                        source_url=record.get("official_jobs_url") or original_url,
                        original_url=original_url,
                        organization=organization,
                        title=title,
                        location=", ".join(locations) or "Afghanistan",
                        description=combined[:12000],
                        application_url=original_url,
                        posting_date=_date10(detail.get("ExternalPostedStartDate") or requisition.get("PostedDate")),
                        closing_date=_date10(detail.get("ExternalPostedEndDate") or requisition.get("PostingEndDate")),
                        reference_number=str(requisition.get("Id") or detail.get("Id") or ""),
                        department=normalize_text(str(detail.get("Category") or requisition.get("Category") or requisition.get("JobFunction") or "")),
                        reliability=record.get("provenance_level", "high"),
                        provenance=[
                            {
                                "source": organization,
                                "url": record.get("official_jobs_url") or original_url,
                                "reliability": record.get("provenance_level", "high"),
                                "registry_id": record.get("id", ""),
                                "method": "oracle_hcm_api",
                            }
                        ],
                        raw={
                            "department": normalize_text(str(detail.get("Category") or requisition.get("Category") or requisition.get("JobFunction") or "")),
                            "source_name": organization,
                            "source_category": record.get("source_category", ""),
                            "registry_status": record.get("reliability_status", ""),
                            "oracle_requisition_id": str(requisition.get("Id") or ""),
                        },
                    )
                )
    return raw_vacancies_to_jobs(raw_items)


async def discover_official_career_pages(profile: dict[str, Any]) -> list[Any]:
    """Deterministically scan configured official organization career pages."""
    from utils.discovery import Job

    pages = []
    sources = profile.get("job_sources", {}) if isinstance(profile.get("job_sources"), dict) else {}
    for item in sources.get("official_career_pages", []) or []:
        if isinstance(item, str):
            pages.append({"url": item, "organization": _domain_company(item)})
        elif isinstance(item, dict) and item.get("url"):
            pages.append({"url": item["url"], "organization": item.get("organization") or _domain_company(item["url"])})
    for url in profile.get("custom_career_pages", []) or []:
        pages.append({"url": url, "organization": _domain_company(url)})

    if not pages:
        return []

    timeout = sources.get("career_page_timeout_seconds", 25)
    jobs: list[Job] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for page in pages:
            url = page["url"]
            source_id = page.get("organization") or url
            _audit_profile_source(profile, "attempted", source_id)
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                _audit_profile_source(profile, "failed", {"source": source_id, "error": str(exc)})
                print(f"  ⚠ Career page source failed for {url}: {exc}")
                continue
            extracted = _jobs_from_html(html, base_url=url, source="official_career_page", default_company=page["organization"])
            jobs.extend(extracted)
            _audit_profile_source(profile, "successful", source_id)
    return jobs


async def _enrich_static_job_from_detail(client: httpx.AsyncClient, job: Any, record: dict[str, Any]) -> None:
    """Fetch a public detail page and attach richer text/provenance if available."""
    if not getattr(job, "url", "") or job.url == job.metadata.get("source_url"):
        return
    try:
        resp = await client.get(job.url)
        resp.raise_for_status()
    except Exception:
        return
    detail_text = normalize_text(strip_html(resp.text))
    if not detail_text:
        return
    # Avoid storing huge site navigation dumps when the vacancy body is small.
    title = normalize_text(getattr(job, "title", ""))
    marker_idx = detail_text.lower().find(title.lower()) if title else -1
    if marker_idx >= 0:
        detail_text = detail_text[marker_idx: marker_idx + 12000]
    else:
        detail_text = detail_text[:12000]
    if len(detail_text) > len(getattr(job, "description", "") or ""):
        job.description = detail_text
    job.metadata = job.metadata or {}
    parsed_closing = parse_closing_date(detail_text)
    if parsed_closing:
        job.metadata["closing_date"] = parsed_closing
    apply_url = _detail_apply_url(resp.text, job.url)
    if apply_url:
        job.apply_url = apply_url
        job.metadata["application_url"] = apply_url
    job.metadata["detail_fetched"] = True
    job.metadata["original_vacancy_url"] = job.url
    job.metadata["source_urls"] = _append_unique_strings(list(job.metadata.get("source_urls") or []), [job.metadata.get("source_url", ""), job.url, apply_url or ""])
    job.metadata.setdefault("source_provenance", [])
    provenance = {
        "source": record.get("organization_name") or job.platform,
        "url": job.url,
        "reliability": record.get("provenance_level", "high"),
        "registry_id": record.get("id", ""),
        "method": "detail_page",
    }
    if provenance not in job.metadata["source_provenance"]:
        job.metadata["source_provenance"].append(provenance)


def _detail_apply_url(html: str, detail_url: str) -> str:
    for label, href in _extract_links(html, detail_url):
        haystack = f"{label} {href}".lower()
        if href.startswith("mailto:"):
            continue
        if any(token in haystack for token in ["apply", "application", "google.com/forms", "forms.gle", "smartr.me", "taleo"]):
            return href
    return ""



def _append_unique_strings(items: list[str], values: list[str]) -> list[str]:
    for value in values:
        if value and value not in items:
            items.append(value)
    return items


def _site_number_from_oracle_url(url: str) -> str:
    match = re.search(r"/sites/(CX_\d+)", url or "", flags=re.I)
    return match.group(1) if match else ""


def _oracle_base_from_url(url: str) -> str:
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _date10(value: Any) -> str:
    if not value:
        return ""
    return str(value)[:10]


def _oracle_requisition_in_afghanistan(requisition: dict[str, Any]) -> bool:
    if str(requisition.get("PrimaryLocationCountry") or "").upper() == "AF":
        return True
    if re.search(r"\bAfghanistan\b", str(requisition.get("PrimaryLocation") or ""), flags=re.I):
        return True
    for location in requisition.get("secondaryLocations") or []:
        if str(location.get("CountryCode") or "").upper() == "AF" or re.search(r"\bAfghanistan\b", str(location.get("Name") or ""), flags=re.I):
            return True
    return False


def _oracle_locations(requisition: dict[str, Any], detail: dict[str, Any]) -> list[str]:
    locations: list[str] = []
    for value in [detail.get("PrimaryLocation"), requisition.get("PrimaryLocation")]:
        if value and value not in locations:
            locations.append(str(value))
    for location in requisition.get("secondaryLocations") or []:
        name = str(location.get("Name") or "")
        if name and name not in locations:
            locations.append(name)
    return locations


async def _fetch_oracle_hcm_detail(client: httpx.AsyncClient, base_url: str, requisition_id: str) -> dict[str, Any]:
    if not requisition_id:
        return {}
    detail_url = f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{requisition_id}?onlyData=true"
    try:
        resp = await client.get(detail_url)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _oracle_hcm_description(requisition: dict[str, Any], detail: dict[str, Any]) -> str:
    parts = [
        detail.get("ShortDescriptionStr") or requisition.get("ShortDescriptionStr"),
        detail.get("ExternalDescriptionStr"),
        detail.get("ExternalResponsibilitiesStr"),
        detail.get("ExternalQualificationsStr"),
        detail.get("CorporateDescriptionStr"),
    ]
    clean_parts = [normalize_text(strip_html(str(part))) for part in parts if part]
    return "\n\n".join(part for part in clean_parts if part)


def _jobs_from_html(
    html: str,
    *,
    base_url: str,
    source: str,
    default_company: str,
    source_type: str | None = None,
    source_record: dict[str, Any] | None = None,
    require_afghanistan: bool = False,
) -> list[Any]:
    from utils.discovery import Job

    text = strip_html(html)
    links = _extract_links(html, base_url)
    jobs: list[Job] = []
    for link_text, href in links:
        label = normalize_text(link_text)
        if len(label) < 4 or len(label) > 180:
            continue
        context = _description_near_label(text, label)
        local_haystack = f"{label}\n{href}\n{context[:1800]}"
        if require_afghanistan and not re.search(r"\bAfghanistan\b|\bKabul\b|\bHerat\b|\bNangarhar\b|\bKandahar\b|\bMazar", local_haystack, flags=re.I):
            continue
        if not looks_medical(local_haystack):
            continue
        if not any(term in label.lower() or term in href.lower() for term in ["job", "vacanc", "career", "position", "medical", "doctor", "health", "nutrition", "physician", "nurse", "pharmacy", "midwife", "public-health", "public health"]):
            continue
        company = _infer_company_from_text(label) or default_company
        title = _clean_title(label)
        reliability = (source_record or {}).get("provenance_level") or ("high" if source == "official_career_page" else "medium")
        record_source_type = source_type or ("official_employer_career_page" if source == "official_career_page" else "job_board")
        provenance = {
            "source": (source_record or {}).get("organization_name") or source,
            "url": base_url,
            "reliability": reliability,
            "registry_id": (source_record or {}).get("id", source),
            "status": (source_record or {}).get("reliability_status", ""),
        }
        closing_date = parse_closing_date(context) or ""
        jobs.append(
            Job(
                id=_stable_id(source, href, title, company),
                title=title,
                company=company,
                location=_extract_location_hint(label, context) or _extract_location_hint(label, text) or "Afghanistan",
                url=href,
                apply_url=href,
                platform=source,
                description=context,
                department="Medical / Health",
                metadata={
                    "source": source,
                    "source_name": (source_record or {}).get("organization_name") or source,
                    "source_category": (source_record or {}).get("source_category", ""),
                    "source_type": record_source_type,
                    "source_url": base_url,
                    "original_vacancy_url": href,
                    "source_urls": [base_url, href],
                    "source_reliability": reliability,
                    "registry_status": (source_record or {}).get("reliability_status", ""),
                    "closing_date": closing_date,
                    "source_provenance": [provenance],
                },
            )
        )
    return _unique_by_url_title(jobs)


def _extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, flags=re.I | re.S):
        attrs, body = match.group(1), match.group(2)
        href_match = re.search(r"href\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I)
        if not href_match:
            continue
        href = urljoin(base_url, href_match.group(1))
        label = strip_html(body)
        if href and label:
            links.append((label, href))
    return links[:300]


def _clean_title(label: str) -> str:
    title = re.sub(r"\s+", " ", label).strip(" -|•\t\n")
    # Drop trailing meta fragments common on listing cards.
    title = re.split(r"\s{2,}|\|\s*(?:Kabul|Afghanistan|Closing|Deadline)", title)[0].strip()
    return title[:160] or "Medical vacancy"


def _infer_company_from_text(label: str) -> str | None:
    # Common card style: "Medical Officer - Organization".
    parts = re.split(r"\s+[-–|]\s+", label)
    if len(parts) >= 2 and len(parts[-1]) <= 80:
        tail = parts[-1].strip()
        if not any(term in tail.lower() for term in ["kabul", "afghanistan", "deadline", "closing"]):
            return tail
    return None


def _extract_location_hint(label: str, text: str) -> str | None:
    from utils.medical_requirements import AFGHAN_PROVINCES

    combined = f"{label}\n{text[:1000]}"
    found = [province for province in AFGHAN_PROVINCES if re.search(rf"\b{re.escape(province)}\b", combined, flags=re.I)]
    if found:
        return ", ".join(dict.fromkeys(found[:3]))
    if re.search(r"\bAfghanistan\b", combined, flags=re.I):
        return "Afghanistan"
    return None


def _description_near_label(text: str, label: str) -> str:
    normalized = normalize_text(text)
    idx = normalized.lower().find(label[:50].lower()) if label else -1
    if idx >= 0:
        return normalized[max(0, idx - 600): idx + 2400]
    return normalized[:3000]


def _domain_company(url: str) -> str:
    match = re.search(r"://(?:www\.)?([^/]+)", url)
    if not match:
        return "Official career page"
    domain = match.group(1).split(":", 1)[0]
    parts = domain.split(".")
    if len(parts) >= 2:
        return parts[-2].replace("-", " ").title()
    return domain.title()


def _unique_by_url_title(jobs: list[Any]) -> list[Any]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job.url.lower(), job.title.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique
