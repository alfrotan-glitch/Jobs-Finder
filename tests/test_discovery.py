import pytest

from utils import discovery
from utils.discovery import Job, NO_RELEVANT_JOBS_FOUND, PARTIAL_SCAN, SOURCES_UNAVAILABLE, deduplicate_jobs, run_discovery_scan


@pytest.mark.asyncio
async def test_all_sources_unavailable_is_not_empty_market(monkeypatch):
    async def broken(profile):
        raise RuntimeError("TLS EOF")

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "broken", {"name": "Broken", "tier": "A", "fetcher": "broken", "active": True})
    monkeypatch.setattr(discovery, "broken", broken, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["broken"]}})

    assert result.status == SOURCES_UNAVAILABLE
    assert result.jobs == []
    assert "could not be reached" in result.message
    assert result.source_reports[0].error == "TLS EOF"


@pytest.mark.asyncio
async def test_partial_scan_keeps_successful_jobs(monkeypatch):
    async def good(profile):
        return [Job("j1", "Medical Officer", "FMIC", "Kabul", "https://example.org/job", "hr@example.org", "test", "MD required. Send CV to hr@example.org by 2026-12-31")]

    async def bad(profile):
        raise RuntimeError("blocked")

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "good", {"name": "Good", "tier": "A", "fetcher": "good", "active": True})
    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "bad", {"name": "Bad", "tier": "B", "fetcher": "bad", "active": True})
    monkeypatch.setattr(discovery, "good", good, raising=False)
    monkeypatch.setattr(discovery, "bad", bad, raising=False)

    result = await run_discovery_scan({"sources": {"enabled": ["good", "bad"]}})

    assert result.status == PARTIAL_SCAN
    assert len(result.jobs) == 1
    assert result.failed_sources == 1
    assert result.successful_sources == 1


@pytest.mark.asyncio
async def test_no_relevant_jobs_found_only_when_sources_work(monkeypatch):
    async def empty(profile):
        return []

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "empty", {"name": "Empty", "tier": "A", "fetcher": "empty", "active": True})
    monkeypatch.setattr(discovery, "empty", empty, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["empty"]}})

    assert result.status == NO_RELEVANT_JOBS_FOUND
    assert "No relevant current vacancies" in result.message


def test_deduplicate_and_expired_vacancies_are_removed():
    jobs = [
        Job("a", "Medical Officer", "Org", "Kabul", "https://example.org/1", "", "x", metadata={"closing_date": "2026-12-31"}),
        Job("b", "Medical Officer", "Org", "Kabul", "https://example.org/1?utm=x", "", "x", metadata={"closing_date": "2026-12-31"}),
        Job("c", "Medical Officer", "Org", "Kabul", "https://example.org/2", "", "x", metadata={"closing_date": "2020-01-01"}),
    ]

    assert [job.id for job in deduplicate_jobs(jobs)] == ["a"]


def test_acbar_listing_parser_preserves_url_and_deadline():
    html = '''<a href="/en/jobs/details/145774/medical-officer">Medical Officer</a>
    <span>FMIC</span><span>Kabul</span><span>2026-10-05</span>'''
    jobs = discovery._parse_acbar_listing(html, "https://www.acbar.org/en/jobs")

    assert jobs[0].title == "Medical Officer"
    assert jobs[0].url == "https://www.acbar.org/en/jobs/details/145774/medical-officer"
    assert jobs[0].metadata["closing_date"] == "2026-10-05"

@pytest.mark.asyncio
async def test_malformed_source_item_does_not_crash_scan(monkeypatch):
    async def malformed(profile):
        return [None, {"title": "broken"}]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "malformed", {"name": "Malformed", "tier": "A", "fetcher": "malformed", "active": True})
    monkeypatch.setattr(discovery, "malformed", malformed, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["malformed"]}})
    assert result.status == NO_RELEVANT_JOBS_FOUND
    assert result.jobs == []
