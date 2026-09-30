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
from urllib.parse import urljoin

import httpx

from utils.medical_requirements import MEDICAL_DISCOVERY_KEYWORDS, looks_medical, normalize_text, strip_html


@dataclass
class SourceResult:
    source: str
    ok: bool
    jobs: list[Any]
    error: str = ""


DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Jobs-Finder Afghanistan Medical Assistant/2.0; +https://acbar.org)"


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
                print(f"  ⚠ ACBAR source failed for {url}: {exc}")
                # Some hosting environments drop TLS handshakes to ACBAR. The
                # caller continues with other sources; in Agent Mode, web-search
                # results can still be ingested through utils.mcp_source while
                # preserving the original ACBAR URL and application instructions.
                continue
            jobs.extend(_jobs_from_html(page_text, base_url=url, source="acbar", default_company="ACBAR"))
    return jobs


async def discover_reliefweb_jobs(profile: dict[str, Any]) -> list[Any]:
    """Use ReliefWeb's public API for Afghanistan health/medical vacancies."""
    from utils.discovery import Job

    config = profile.get("job_sources", {}).get("reliefweb", {}) if isinstance(profile.get("job_sources"), dict) else {}
    timeout = config.get("timeout_seconds", 25)
    limit = int(config.get("limit", 25))
    jobs: list[Job] = []
    url = "https://api.reliefweb.int/v1/jobs"
    query = " OR ".join(["Afghanistan", "medical", "health", "doctor", "physician", "nutrition", "public health"])
    params = {
        "appname": "jobs-finder-afghanistan-medical",
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
        print(f"  ⚠ ReliefWeb source failed: {exc}")
        return []

    for item in data.get("data", []):
        fields = item.get("fields", {})
        title = fields.get("title") or "Untitled"
        company = ""
        if fields.get("source"):
            source = fields["source"]
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
        locations = fields.get("country", [])
        location = "Afghanistan"
        if isinstance(locations, list) and locations:
            location = ", ".join(loc.get("name", "") for loc in locations if isinstance(loc, dict)) or location
        job = Job(
            id=_stable_id("reliefweb", str(item.get("id", "")), title, company),
            title=title,
            company=company or "ReliefWeb source",
            location=location,
            url=url_alias,
            apply_url=apply_url if isinstance(apply_url, str) else url_alias,
            platform="reliefweb",
            description=description,
            department="Health / Humanitarian",
            metadata={
                "source": "reliefweb",
                "source_url": url_alias,
                "date_posted": fields.get("date", {}).get("created") if isinstance(fields.get("date"), dict) else "",
                "organization_source": company,
            },
        )
        jobs.append(job)
    return jobs


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
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                print(f"  ⚠ Career page source failed for {url}: {exc}")
                continue
            extracted = _jobs_from_html(html, base_url=url, source="official_career_page", default_company=page["organization"])
            jobs.extend(extracted)
    return jobs


def _jobs_from_html(html: str, *, base_url: str, source: str, default_company: str) -> list[Any]:
    from utils.discovery import Job

    text = strip_html(html)
    links = _extract_links(html, base_url)
    jobs: list[Job] = []
    for link_text, href in links:
        label = normalize_text(link_text)
        if len(label) < 4 or len(label) > 180:
            continue
        haystack = f"{label}\n{text[:3000]}"
        if not looks_medical(haystack):
            continue
        if not any(term in label.lower() or term in href.lower() for term in ["job", "vacanc", "career", "position", "medical", "doctor", "health", "nutrition", "physician"]):
            continue
        company = _infer_company_from_text(label) or default_company
        title = _clean_title(label)
        jobs.append(
            Job(
                id=_stable_id(source, href, title, company),
                title=title,
                company=company,
                location=_extract_location_hint(label, text) or "Afghanistan",
                url=href,
                apply_url=href,
                platform=source,
                description=_description_near_label(text, label),
                department="Medical / Health",
                metadata={"source": source, "source_url": base_url},
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
