import asyncio

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


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _ConcurrencyProbe:
    def __init__(self):
        self.current = 0
        self.max_seen = 0

    def enter(self):
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)

    def exit(self):
        self.current -= 1


class _FakeAcbarClient:
    def __init__(self, listing_pages, *, sleep=0.0, concurrency_probe=None):
        self.listing_pages = listing_pages
        self.sleep = sleep
        self.concurrency_probe = concurrency_probe
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url):
        self.get_calls.append(url)
        if url in self.listing_pages:
            return _FakeResponse(self.listing_pages[url])
        # Treat anything else as a detail-page fetch.
        if self.concurrency_probe is not None:
            self.concurrency_probe.enter()
            try:
                if self.sleep:
                    await asyncio.sleep(self.sleep)
            finally:
                self.concurrency_probe.exit()
        return _FakeResponse("<h1>Medical Officer</h1><p>Medical role in Kabul. Apply hr@example.org.</p>")


def _acbar_card(index: int) -> str:
    return (
        f'<div><a href="/en/jobs/details/{1000 + index}/medical-officer-{index}">Medical Officer {index}</a>'
        f"<span>Health Org</span><span>Kabul</span><span>2026-12-31</span></div>"
    )


def _non_medical_acbar_card(index: int) -> str:
    return (
        f'<div><a href="/en/jobs/details/{2000 + index}/finance-officer-{index}">Finance Officer {index}</a>'
        f"<span>Finance Org</span><span>Kabul</span><span>2026-12-31</span></div>"
    )


@pytest.mark.asyncio
async def test_acbar_relevant_vacancy_after_detail_limit_is_discovered(monkeypatch):
    """A medical vacancy appearing after detail_limit non-medical vacancies
    must still be discovered; detail fetches must only be spent on relevant jobs."""
    # 35 non-medical vacancies followed by 2 medical vacancies.
    page1 = "".join(_non_medical_acbar_card(i) for i in range(10))
    page2 = "".join(_non_medical_acbar_card(i) for i in range(10, 20))
    page3 = "".join(_non_medical_acbar_card(i) for i in range(20, 30))
    page4 = "".join(_non_medical_acbar_card(i) for i in range(30, 35)) + _acbar_card(1) + _acbar_card(2)
    pages = {
        "https://www.acbar.org/en/jobs": page1,
        "https://www.acbar.org/en/jobs?page=2": page2,
        "https://www.acbar.org/en/jobs?page=3": page3,
        "https://www.acbar.org/en/jobs?page=4": page4,
    }
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    # With detail_limit=10, the old code would truncate summaries[:10] on page 1,
    # completely missing the medical vacancies on page 4.
    jobs = await discovery.discover_acbar_jobs({
        "job_sources": {"acbar": {"max_pages": 4, "detail_limit": 10}}
    })

    assert len(jobs) == 2
    assert {j.title for j in jobs} == {"Medical Officer"}
    assert {j.url for j in jobs} == {
        "https://www.acbar.org/en/jobs/details/1001/medical-officer-1",
        "https://www.acbar.org/en/jobs/details/1002/medical-officer-2",
    }
    # Detail fetches were only made for the 2 medical vacancies, not the 35 non-medical ones.
    detail_calls = [c for c in fake_client.get_calls if c not in pages]
    assert len(detail_calls) == 2
    assert set(detail_calls) == {
        "https://www.acbar.org/en/jobs/details/1001/medical-officer-1",
        "https://www.acbar.org/en/jobs/details/1002/medical-officer-2",
    }


@pytest.mark.asyncio
async def test_acbar_detail_fetches_are_bounded_by_detail_limit(monkeypatch):
    """When there are more relevant vacancies than detail_limit, network fetches
    are strictly capped at detail_limit."""
    page1 = "".join(_acbar_card(i) for i in range(10))
    page2 = "".join(_acbar_card(i) for i in range(10, 20))
    pages = {
        "https://www.acbar.org/en/jobs": page1,
        "https://www.acbar.org/en/jobs?page=2": page2,
    }
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({
        "job_sources": {"acbar": {"max_pages": 2, "detail_limit": 5}}
    })

    assert len(jobs) == 5
    detail_calls = [c for c in fake_client.get_calls if c not in pages]
    assert len(detail_calls) == 5


@pytest.mark.asyncio
async def test_acbar_pagination_stops_when_a_page_has_no_new_vacancies(monkeypatch):
    repeated_page = "".join(_acbar_card(i) for i in range(2))
    pages = {
        "https://www.acbar.org/en/jobs": repeated_page,
        "https://www.acbar.org/en/jobs?page=2": repeated_page,  # identical links -> no new jobs
        "https://www.acbar.org/en/jobs?page=3": "".join(_acbar_card(i) for i in range(10, 12)),
    }
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({})

    listing_calls = [c for c in fake_client.get_calls if c in pages]
    assert listing_calls == [
        "https://www.acbar.org/en/jobs",
        "https://www.acbar.org/en/jobs?page=2",
    ]
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_acbar_pagination_respects_configured_max_pages(monkeypatch):
    pages = {}
    for page in range(1, 6):
        url = "https://www.acbar.org/en/jobs" if page == 1 else f"https://www.acbar.org/en/jobs?page={page}"
        pages[url] = "".join(_acbar_card(i) for i in range((page - 1) * 2, page * 2))
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 3}}})

    listing_calls = [c for c in fake_client.get_calls if c in pages]
    assert listing_calls == [
        "https://www.acbar.org/en/jobs",
        "https://www.acbar.org/en/jobs?page=2",
        "https://www.acbar.org/en/jobs?page=3",
    ]
    assert "https://www.acbar.org/en/jobs?page=4" not in fake_client.get_calls
    assert len(jobs) == 6


@pytest.mark.asyncio
async def test_acbar_detail_fetch_concurrency_is_bounded(monkeypatch):
    listing_html = "".join(_acbar_card(i) for i in range(6))
    pages = {"https://www.acbar.org/en/jobs": listing_html}
    probe = _ConcurrencyProbe()
    fake_client = _FakeAcbarClient(pages, sleep=0.03, concurrency_probe=probe)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 1, "max_detail_concurrency": 2}}})

    assert len(jobs) == 6
    assert probe.max_seen <= 2
    assert probe.max_seen > 0


@pytest.mark.asyncio
async def test_acbar_explicit_urls_override_auto_pagination(monkeypatch):
    pinned_url = "https://www.acbar.org/en/jobs?page=7"
    pages = {pinned_url: "".join(_acbar_card(i) for i in range(2))}
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"urls": [pinned_url]}}})

    listing_calls = [c for c in fake_client.get_calls if c in pages]
    assert listing_calls == [pinned_url]
    assert len(jobs) == 2
