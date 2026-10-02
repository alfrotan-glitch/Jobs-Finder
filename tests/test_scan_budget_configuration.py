"""Contract tests for scan budget configuration.

Operational caps come from ``profile.yaml`` alone:

1. A profile without limits scans to the source's real end (END_REACHED,
   SCANNED, every listing seen).
2. An explicitly configured ``max_pages`` caps pagination and marks the scan
   PARTIAL.
3. An explicitly configured ``detail_limit`` defers candidates openly and
   marks the scan PARTIAL, with budget-deferred listings keeping exactly one
   terminal outcome.
4. A ``job_sources`` block is read exactly as written, and the CV importer
   never writes operational defaults into profile.yaml.
"""

from datetime import date

import pytest

from utils import discovery
from utils.profile_builder import build_profile_from_cv_text


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _paged_client(pages: dict[int, str]):
    """A two-page ACBAR: page=1 full, page=2 listings, page=3 empty (real end)."""

    class Client:
        requested: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            self.requested.append(url)
            if "/details/" in url:
                return Response("<h1>Medical Officer</h1><p>MD required. Apply hr@example.org</p>")
            for page_number, html in pages.items():
                marker = f"?page={page_number}" if page_number > 1 else "jobs"
                if page_number == 1 and url.rstrip("/").endswith("jobs") and "page=" not in url:
                    return Response(html)
                if page_number > 1 and marker in url:
                    return Response(html)
            raise AssertionError(f"unexpected url {url}")

    return Client


PAGE_ONE = """
<div><a href='/en/jobs/details/101/medical-officer'>Medical Officer</a><span>Org</span><span>Kabul</span></div>
<div><a href='/en/jobs/details/102/nutrition-officer'>Nutrition Officer</a><span>Org</span><span>Kabul</span></div>
"""
PAGE_TWO = """
<div><a href='/en/jobs/details/103/health-coordinator'>Health Coordinator</a><span>Org</span><span>Balkh</span></div>
"""


def _assert_unbounded_full_scan(jobs):
    assert jobs.metrics.pagination_stop_reason == "END_REACHED"
    assert jobs.metrics.status == "SCANNED"
    assert jobs.metrics.partial_reasons == []
    assert jobs.metrics.configured_page_limit is None
    assert jobs.metrics.configured_detail_limit is None
    assert jobs.metrics.pages_requested == 3  # 2 listing pages + 1 empty end page
    assert {job.url.rsplit("/", 2)[-2] for job in jobs} == {"101", "102", "103"}
    assert jobs.metrics.listings_seen == 3
    assert jobs.metrics.not_processed_due_to_budget == 0
    assert jobs.metrics.detail_pages_attempted == 3  # no detail budget at all


@pytest.mark.asyncio
async def test_default_scan_without_limits_reaches_real_end(monkeypatch):
    """No max_pages and no detail_limit means an unbounded scan."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"personal": {"first_name": "A"}})
    _assert_unbounded_full_scan(jobs)


@pytest.mark.asyncio
async def test_connection_settings_alone_do_not_cap_a_scan(monkeypatch):
    """Timeout/concurrency settings are not budgets: the scan stays unbounded."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    profile = {"job_sources": {"acbar": {"timeout_seconds": 25.0, "max_detail_concurrency": 5}}}
    jobs = await discovery.discover_acbar_jobs(profile)
    _assert_unbounded_full_scan(jobs)


@pytest.mark.asyncio
async def test_explicit_max_pages_still_caps_and_marks_partial(monkeypatch):
    """A deliberate user limit is honored and reported PARTIAL."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 1}}})
    assert jobs.metrics.configured_page_limit == 1
    assert jobs.metrics.pagination_stop_reason == "PAGE_LIMIT_REACHED"
    assert jobs.metrics.status == "PARTIAL"
    assert "PAGINATION_NOT_EXHAUSTED" in jobs.metrics.partial_reasons
    assert jobs.metrics.pages_requested == 1


@pytest.mark.asyncio
async def test_explicit_detail_limit_defers_candidates_and_marks_partial(monkeypatch):
    """A deliberate detail budget defers candidates openly."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"detail_limit": 2}}})
    assert jobs.metrics.configured_detail_limit == 2
    assert jobs.metrics.detail_pages_attempted == 2
    assert jobs.metrics.not_processed_due_to_budget == 1
    assert jobs.metrics.status == "PARTIAL"
    assert "DETAIL_LIMIT_REACHED" in jobs.metrics.partial_reasons
    # Deferred candidates stay in the canonical lifecycle; they never vanish
    # as "irrelevant" or "missing".
    assert jobs.metrics.listings_seen == 3
    assert jobs.metrics.vacancies_parsed == 3


# ---------------------------------------------------------------------------
# How a job_sources block is read
# ---------------------------------------------------------------------------


def test_falsy_override_forms_mean_no_overrides():
    """Behavioral parity: `job_sources.acbar:` (null), "", false, [] never crash."""
    for falsy in (None, "", False, []):
        assert discovery._source_overrides({"job_sources": {"acbar": falsy}}, "acbar") == {}
    assert discovery._source_overrides({}, "acbar") == {}
    assert discovery._source_overrides({"personal": {}}, "acbar") == {}
    with pytest.raises(ValueError):
        discovery._source_overrides({"job_sources": {"acbar": "yes"}}, "acbar")


def test_configured_block_is_read_exactly_as_written():
    block = {"timeout_seconds": 25.0, "max_pages": 4, "detail_limit": 50, "urls": ["https://example.org/jobs"]}
    assert discovery._source_overrides({"job_sources": {"acbar": dict(block)}}, "acbar") == block


def test_cv_import_does_not_materialize_source_defaults():
    """The importer writes no operational defaults into profile.yaml."""
    profile = build_profile_from_cv_text("Jane Doe\nMedical Doctor\njane@example.org", resume_path="cv.txt")
    acbar = profile["job_sources"]["acbar"]
    reliefweb = profile["job_sources"]["reliefweb"]
    assert "max_pages" not in acbar and "detail_limit" not in acbar
    assert "limit" not in reliefweb
    assert acbar == {} and reliefweb == {}


@pytest.mark.asyncio
async def test_deferred_candidates_stay_in_canonical_accounting(monkeypatch):
    """Full discovery first, conservative detail enrichment second: a
    budget-deferred listing keeps exactly one explicit terminal outcome."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    result = await discovery.run_discovery_scan(
        {"sources": {"enabled": ["acbar"]}, "job_sources": {"acbar": {"detail_limit": 1}}},
        today=date(2026, 10, 1),
    )
    report = result.source_reports[0]
    assert report.not_processed_due_to_budget == 2
    assert report.status == "PARTIAL"
    terminal = (
        report.duplicates_removed + report.expired_excluded + report.not_processed_due_to_budget
        + report.irrelevant_excluded + report.incompatible_role_classification_excluded
        + report.source_validation_excluded + report.relevant_retained
    )
    assert terminal == report.vacancies_parsed
