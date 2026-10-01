from datetime import date

import pytest

import main
from utils import discovery
from utils.discovery import Job, ScanResult, SourceReport, SourceScanMetrics, run_discovery_scan


def _job(identifier, title="Medical Officer", url=None, description="MD required. Apply to hr@example.org.", **metadata):
    url = url or f"https://example.org/{identifier}"
    return Job(identifier, title, "Org", "Kabul", url, "hr@example.org", "fixture", description, metadata=metadata)


@pytest.mark.asyncio
async def test_canonical_lifecycle_conserves_every_listing(monkeypatch):
    async def fixture(profile):
        return [
            _job("kept", source_name="ACBAR", source_url="https://example.org/jobs", vacancy_url="https://example.org/kept"),
            _job("duplicate", url="https://example.org/kept?tracking=1", source_name="ACBAR", source_url="https://example.org/jobs", vacancy_url="https://example.org/kept?tracking=1"),
            _job("expired", source_name="ACBAR", source_url="https://example.org/jobs", vacancy_url="https://example.org/expired", closing_date="2020-01-01"),
            _job("irrelevant", title="Finance Manager", description="Accounting and finance duties.", source_name="ACBAR", source_url="https://example.org/jobs", vacancy_url="https://example.org/irrelevant"),
            _job("incompatible", title="Pharmacist", description="BSc Pharmacy and pharmacy licence required.", source_name="ACBAR", source_url="https://example.org/jobs", vacancy_url="https://example.org/incompatible"),
            _job("invalid", source_name="UNKNOWN", source_url="", vacancy_url="https://example.org/invalid"),
            None,
        ]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "fixture", {"name": "Fixture", "tier": "A", "fetcher": "fixture", "active": True})
    monkeypatch.setattr(discovery, "fixture", fixture, raising=False)
    result = await run_discovery_scan({"sources": {"enabled": ["fixture"]}}, today=date(2026, 10, 1))
    report = result.source_reports[0]

    assert report.listings_seen == 7
    assert report.listing_parse_failures == 1
    assert report.vacancies_parsed == 6
    assert (report.duplicates_removed, report.expired_excluded, report.irrelevant_excluded) == (1, 1, 1)
    assert report.incompatible_role_classification_excluded == 1
    assert report.source_validation_excluded == 1
    assert report.relevant_retained == 1
    assert report.vacancies_parsed == sum([
        report.duplicates_removed, report.expired_excluded, report.irrelevant_excluded,
        report.incompatible_role_classification_excluded, report.source_validation_excluded,
        report.relevant_retained,
    ])


@pytest.mark.asyncio
async def test_terminal_precedence_for_overlapping_conditions(monkeypatch):
    async def fixture(profile):
        expired = _job("expired", url="https://example.org/same", closing_date="2020-01-01")
        duplicate_expired = _job("duplicate-expired", url="https://example.org/same?x=1", closing_date="2020-01-01")
        incompatible_invalid = _job("bad-role", title="Pharmacist", description="Pharmacy licence required.", source_name="UNKNOWN", source_url="")
        return [expired, duplicate_expired, incompatible_invalid]

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "fixture", {"name": "Fixture", "tier": "A", "fetcher": "fixture", "active": True})
    monkeypatch.setattr(discovery, "fixture", fixture, raising=False)
    report = (await run_discovery_scan({"sources": {"enabled": ["fixture"]}}, today=date(2026, 10, 1))).source_reports[0]
    # First identity expires, the second is terminally duplicate; incompatible
    # precedes source validation for the third item.
    assert report.expired_excluded == 1
    assert report.duplicates_removed == 1
    assert report.incompatible_role_classification_excluded == 1
    assert report.source_validation_excluded == 0
    assert report.irrelevant_excluded == 0


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_acbar_page_failure_preserves_successful_page(monkeypatch):
    page = "<div><a href='/en/jobs/details/9001/medical-officer'>Medical Officer</a><span>Org</span><span>Kabul</span></div>"

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            if url.endswith("?page=2"):
                raise RuntimeError("page two failed")
            if "/details/" in url:
                return Response("<h1>Medical Officer</h1><p>MD required. Apply hr@example.org</p>")
            return Response(page)

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: Client())
    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 3}}})
    assert len(jobs) == 1
    assert jobs.metrics.pages_requested == 2
    assert jobs.metrics.pages_succeeded == 1
    assert jobs.metrics.pages_failed == 1
    assert jobs.metrics.status == "PARTIAL"
    assert "LISTING_PAGE_FAILURE" in jobs.metrics.partial_reasons


@pytest.mark.asyncio
async def test_reliefweb_duplicate_and_detail_failure_metrics(monkeypatch):
    listing = """
      <article><a href='/job/1'>Medical Officer Afghanistan</a><p>Afghanistan</p></article>
      <article><a href='/job/1'>Medical Officer Afghanistan</a><p>Afghanistan</p></article>
    """

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            if "/job/1" in url:
                raise RuntimeError("detail failed")
            return Response(listing)

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: Client())
    jobs = await discovery.discover_reliefweb_jobs({"job_sources": {"reliefweb": {"limit": 20}}})
    assert jobs.metrics.listings_seen == 2
    assert jobs.metrics.duplicates_removed == 1
    assert jobs.metrics.detail_pages_attempted == 1
    assert jobs.metrics.detail_pages_succeeded == 0
    assert jobs.metrics.detail_pages_failed == 1
    assert jobs.metrics.listing_fallback_used == 1


def test_route_and_scan_match_invariants_and_cli_output(capsys):
    report = SourceReport(id="x", name="Example", tier="A", attempted=True, ok=True, status="PARTIAL",
                          pages_requested=2, pages_succeeded=1, pages_failed=1,
                          pagination_stop_reason="REQUEST_FAILED", listings_seen=3,
                          vacancies_parsed=2, not_processed_due_to_budget=1,
                          relevant_retained=2, application_routes_found=1,
                          application_routes_unavailable=1, partial_reasons=["LISTING_PAGE_FAILURE"])
    scan = ScanResult("PARTIAL_SCAN", [], [report], "start", "finish", "partial")
    scan.record_match_results([
        {"readiness_status": "READY_TO_APPLY"},
        {"readiness_status": "NOT_ELIGIBLE"},
    ])
    assert report.application_routes_found + report.application_routes_unavailable == report.relevant_retained
    assert scan.summary()["recommended_from_scan"] == 1
    main.print_scan_accounting(scan)
    output = capsys.readouterr().out
    assert "Source: Example" in output
    assert "Pages: 2 requested / 1 succeeded / 1 failed" in output
    assert "Not processed due to budget: 1" in output
    assert "OVERALL" in output
    assert "Recommended from this scan: 1" in output


def test_scan_specific_recommendations_do_not_share_history():
    first = ScanResult("SCAN_COMPLETE", [], [], "", "", "")
    second = ScanResult("SCAN_COMPLETE", [], [], "", "", "")
    first.record_match_results([{"readiness_status": "READY_TO_APPLY"}])
    second.record_match_results([{"readiness_status": "NOT_ELIGIBLE"}])
    assert first.summary()["recommended_from_scan"] == 1
    assert second.summary()["recommended_from_scan"] == 0

@pytest.mark.asyncio
async def test_pagination_end_page_limit_and_detail_budget_are_distinct(monkeypatch):
    card1 = "<div><a href='/en/jobs/details/1/medical-officer'>Medical Officer</a><span>Org</span></div>"
    card2 = "<div><a href='/en/jobs/details/2/medical-officer'>Medical Officer Two</a><span>Org</span></div>"

    class EndClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            if "?page=2" in url:
                return Response("")
            if "/details/" in url:
                return Response("<h1>Medical Officer</h1><p>MD required</p>")
            return Response(card1)

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: EndClient())
    ended = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 3}}})
    assert ended.metrics.pagination_stop_reason == "END_REACHED"
    assert ended.metrics.status == "SCANNED"

    class LimitClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            if "/details/" in url:
                return Response("<h1>Medical Officer</h1><p>MD required</p>")
            return Response(card1 + card2)

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: LimitClient())
    limited = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 1, "detail_limit": 1}}})
    assert limited.metrics.pagination_stop_reason == "PAGE_LIMIT_REACHED"
    assert limited.metrics.not_processed_due_to_budget == 1
    # Stage 1 still parses both discovered cards; the configured detail cap
    # defers one candidate rather than making it disappear from accounting.
    assert limited.metrics.vacancies_parsed == 2
    assert "PAGE_LIMIT_REACHED" in limited.metrics.partial_reasons
    assert "DETAIL_LIMIT_REACHED" in limited.metrics.partial_reasons

@pytest.mark.asyncio
async def test_explicit_detail_budget_is_a_terminal_lifecycle_outcome(monkeypatch):
    cards = "".join(
        f"<div><a href='/en/jobs/details/{number}/medical-officer-{number}'>Medical Officer {number}</a><span>Org</span><span>Kabul</span><span>2026-12-31</span></div>"
        for number in range(1, 4)
    )

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            if "/details/" in url:
                return Response("<h1>Medical Officer</h1><p>MD required. Apply hr@example.org.</p>")
            return Response(cards)

    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await run_discovery_scan(
        {"sources": {"enabled": ["acbar"]}, "job_sources": {"acbar": {"max_pages": 1, "detail_limit": 1}}},
        today=date(2026, 10, 1),
    )
    report = result.source_reports[0]
    assert result.status == discovery.PARTIAL_SCAN
    assert report.status == "PARTIAL"
    assert report.pagination_stop_reason == "PAGE_LIMIT_REACHED"
    assert report.vacancies_parsed == 3
    assert report.not_processed_due_to_budget == 2
    assert report.detail_pages_attempted == report.detail_pages_succeeded == 1
    assert report.relevant_retained == 1
    assert report.application_routes_found + report.application_routes_unavailable == report.relevant_retained
    assert report.vacancies_parsed == sum([
        report.duplicates_removed,
        report.expired_excluded,
        report.not_processed_due_to_budget,
        report.irrelevant_excluded,
        report.incompatible_role_classification_excluded,
        report.source_validation_excluded,
        report.relevant_retained,
    ])
