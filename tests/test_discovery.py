import asyncio

import pytest

from utils import discovery
from utils.discovery import (
    NO_RELEVANT_JOBS_FOUND,
    PARTIAL_SCAN,
    SOURCES_UNAVAILABLE,
    Job,
    deduplicate_jobs,
    run_discovery_scan,
)


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
    failed_report = next(report for report in result.source_reports if report.id == "bad")
    assert failed_report.status == "UNAVAILABLE"
    assert failed_report.error == "blocked"
    assert "jobs" not in failed_report.error.lower()


@pytest.mark.asyncio
async def test_scan_report_counts_exclusions_without_calling_failure_zero_jobs(monkeypatch):
    async def mixed(profile):
        return [
            Job("md", "Medical Officer", "Clinic", "Kabul", "https://example.org/md", "hr@example.org", "mixed", "MD required. Apply to hr@example.org by 2026-12-31.", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/md"}),
            Job("ph", "Pharmacist", "Pharmacy", "Kabul", "https://example.org/ph", "hr@example.org", "mixed", "B.Sc. in Pharmacy required. Apply to hr@example.org by 2026-12-31.", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/ph"}),
            Job("dup", "Medical Officer", "Clinic", "Kabul", "https://example.org/md?utm=1", "hr@example.org", "mixed", "MD required. Apply to hr@example.org by 2026-12-31.", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/md?utm=1"}),
            Job("expired", "Medical Officer", "Clinic", "Kabul", "https://example.org/expired", "hr@example.org", "mixed", "MD required. Apply to hr@example.org by 2020-01-01.", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/expired", "closing_date": "2020-01-01"}),
        ]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "mixed", {"name": "Mixed", "tier": "A", "fetcher": "mixed", "active": True, "official_url": "https://example.org/jobs"})
    monkeypatch.setattr(discovery, "mixed", mixed, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["mixed"]}})

    report = result.source_reports[0]
    assert report.status == "SCANNED"
    assert report.incompatible_role_classification_excluded == 1
    assert report.duplicates_removed == 1
    assert report.expired_excluded == 1
    assert report.relevant_retained == 1
    assert len(result.jobs) == 1


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


@pytest.mark.asyncio
async def test_unknown_source_is_excluded_from_actionable_scan(monkeypatch):
    async def unknown(profile):
        return [Job("j", "Medical Officer", "Org", "Kabul", "https://example.org/job", "hr@example.org", "UNKNOWN", "MD required. Apply to hr@example.org.", metadata={"source_name": "UNKNOWN", "source_url": ""})]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "unknown", {"name": "Unknown", "tier": "B", "fetcher": "unknown", "active": True})
    monkeypatch.setattr(discovery, "unknown", unknown, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["unknown"]}})
    assert result.status == NO_RELEVANT_JOBS_FOUND
    assert result.jobs == []


@pytest.mark.asyncio
async def test_valid_source_and_route_are_retained(monkeypatch):
    async def valid(profile):
        return [Job("j", "Medical Officer", "Org", "Kabul", "https://example.org/job", "hr@example.org", "acbar", "MD required. Apply to hr@example.org.", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/job", "application_method": "email"})]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "valid", {"name": "Valid", "tier": "A", "fetcher": "valid", "active": True})
    monkeypatch.setattr(discovery, "valid", valid, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["valid"]}})
    assert result.status == discovery.SCAN_COMPLETE
    assert len(result.jobs) == 1
    assert result.jobs[0].source_name == "ACBAR"
    assert result.jobs[0].application_method == "EMAIL"
    assert result.jobs[0].apply_email == "hr@example.org"
    assert result.jobs[0].apply_url is None


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
async def test_acbar_relevant_vacancy_after_many_non_medical_pages_is_discovered(monkeypatch):
    """Full ACBAR pagination must find relevant vacancies after irrelevant pages."""
    page1 = "".join(_non_medical_acbar_card(i) for i in range(10))
    page2 = "".join(_non_medical_acbar_card(i) for i in range(10, 20))
    page3 = "".join(_non_medical_acbar_card(i) for i in range(20, 30))
    page4 = "".join(_non_medical_acbar_card(i) for i in range(30, 35)) + _acbar_card(1) + _acbar_card(2)
    pages = {
        "https://www.acbar.org/en/jobs": page1,
        "https://www.acbar.org/en/jobs?page=2": page2,
        "https://www.acbar.org/en/jobs?page=3": page3,
        "https://www.acbar.org/en/jobs?page=4": page4,
        "https://www.acbar.org/en/jobs?page=5": "",
    }
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({})

    assert len(jobs) == 37
    assert jobs.metrics.pagination_stop_reason == "END_REACHED"
    assert {
        "https://www.acbar.org/en/jobs/details/1001/medical-officer-1",
        "https://www.acbar.org/en/jobs/details/1002/medical-officer-2",
    }.issubset({j.url for j in jobs})
    assert jobs.metrics.not_processed_due_to_budget == 0
    detail_calls = [c for c in fake_client.get_calls if c not in pages]
    assert len(detail_calls) == 2


@pytest.mark.asyncio
async def test_acbar_fetches_all_relevant_details_without_detail_budget(monkeypatch):
    page1 = "".join(_acbar_card(i) for i in range(10))
    page2 = "".join(_acbar_card(i) for i in range(10, 20))
    pages = {
        "https://www.acbar.org/en/jobs": page1,
        "https://www.acbar.org/en/jobs?page=2": page2,
        "https://www.acbar.org/en/jobs?page=3": "",
    }
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({})

    assert len(jobs) == 20
    assert jobs.metrics.vacancies_parsed == 20
    assert jobs.metrics.not_processed_due_to_budget == 0
    assert jobs.metrics.status == "SCANNED"
    detail_calls = [c for c in fake_client.get_calls if c not in pages]
    assert len(detail_calls) == 20


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
async def test_acbar_rejects_removed_page_budget_setting(monkeypatch):
    pages = {"https://www.acbar.org/en/jobs": ""}
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    with pytest.raises(ValueError, match="job_sources.acbar.max_pages"):
        await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 3}}})


@pytest.mark.asyncio
async def test_acbar_detail_fetch_concurrency_is_bounded(monkeypatch):
    listing_html = "".join(_acbar_card(i) for i in range(6))
    pages = {"https://www.acbar.org/en/jobs": listing_html, "https://www.acbar.org/en/jobs?page=2": ""}
    probe = _ConcurrencyProbe()
    fake_client = _FakeAcbarClient(pages, sleep=0.03, concurrency_probe=probe)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_detail_concurrency": 2}}})

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

@pytest.mark.asyncio
async def test_acbar_default_discovery_follows_real_end_and_matches_reported_total(monkeypatch):
    """Default discovery runs to ACBAR's real end.

    ACBAR publishes a count and twenty cards per full page. Without a
    page budget the adapter walks a 234-card source across twelve
    non-empty pages plus the authoritative empty end page.
    """
    reported_total = 234
    pages = {}
    medical_indexes = {0, 77, 155, 233}
    for page in range(1, 13):
        first = (page - 1) * 20
        last = min(first + 20, reported_total)
        cards = "".join(
            _acbar_card(index) if index in medical_indexes else _non_medical_acbar_card(index)
            for index in range(first, last)
        )
        url = "https://www.acbar.org/en/jobs" if page == 1 else f"https://www.acbar.org/en/jobs?page={page}"
        pages[url] = f"<p>{reported_total} jobs found</p>{cards}"
    pages["https://www.acbar.org/en/jobs?page=13"] = f"<p>{reported_total} jobs found</p><p>No jobs found</p>"
    fake_client = _FakeAcbarClient(pages)
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: fake_client)

    jobs = await discovery.discover_acbar_jobs({})

    assert len(jobs) == reported_total
    assert jobs.metrics.source_listings_reported == reported_total
    assert jobs.metrics.listings_seen == reported_total
    assert jobs.metrics.listing_parse_failures == 0
    assert jobs.metrics.vacancies_parsed == reported_total
    assert jobs.metrics.pages_requested == 13
    assert jobs.metrics.pages_succeeded == 13
    assert jobs.metrics.pagination_stop_reason == "END_REACHED"
    assert jobs.metrics.status == "SCANNED"
    assert jobs.metrics.not_processed_due_to_budget == 0
    # Stage 2 only opens plausible medical cards; Stage 1 nevertheless retains
    # every listing in the source snapshot.
    detail_calls = [call for call in fake_client.get_calls if call not in pages]
    assert len(detail_calls) == len(medical_indexes)
