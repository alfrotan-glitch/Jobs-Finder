"""Contracts for canonical source configuration.

ACBAR has no page/detail scan-budget settings in the current product. It walks
listing pages to the source's real end and processes every relevant detail page.
Only connection/concurrency settings and deliberately scoped URL sets are valid
ACBAR overrides. ReliefWeb keeps its current result limit.
"""

import pytest

from utils import discovery
from utils.profile_builder import build_profile_from_cv_text


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _paged_client(pages: dict[int, str]):
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
                if page_number == 1 and url.rstrip("/").endswith("jobs") and "page=" not in url:
                    return Response(html)
                if page_number > 1 and f"?page={page_number}" in url:
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


def _assert_full_acbar_scan(jobs):
    assert jobs.metrics.pagination_stop_reason == "END_REACHED"
    assert jobs.metrics.status == "SCANNED"
    assert jobs.metrics.partial_reasons == []
    assert jobs.metrics.pages_requested == 3  # 2 listing pages + 1 empty end page
    assert {job.url.rsplit("/", 2)[-2] for job in jobs} == {"101", "102", "103"}
    assert jobs.metrics.listings_seen == 3
    assert jobs.metrics.not_processed_due_to_budget == 0
    assert jobs.metrics.detail_pages_attempted == 3


@pytest.mark.asyncio
async def test_acbar_default_scan_reaches_real_end(monkeypatch):
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"personal": {"first_name": "A"}})
    _assert_full_acbar_scan(jobs)


@pytest.mark.asyncio
async def test_acbar_connection_settings_do_not_cap_scan(monkeypatch):
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    profile = {"job_sources": {"acbar": {"timeout_seconds": 25.0, "max_detail_concurrency": 5}}}
    jobs = await discovery.discover_acbar_jobs(profile)
    _assert_full_acbar_scan(jobs)


@pytest.mark.parametrize("key", ["max_pages", "detail_limit"])
def test_acbar_rejects_removed_scan_budget_settings(key):
    with pytest.raises(ValueError, match=fr"job_sources\.acbar\.{key}"):
        discovery._validate_source_keys({key: 1}, "acbar", {"timeout_seconds", "max_detail_concurrency", "urls"})


def test_source_override_blocks_are_strict_mappings():
    for falsy in (None, "", False, []):
        assert discovery._source_overrides({"job_sources": {"acbar": falsy}}, "acbar") == {}
    assert discovery._source_overrides({}, "acbar") == {}
    assert discovery._source_overrides({"personal": {}}, "acbar") == {}
    with pytest.raises(ValueError):
        discovery._source_overrides({"job_sources": {"acbar": "yes"}}, "acbar")


def test_cv_import_does_not_materialize_source_defaults_or_budgets():
    profile = build_profile_from_cv_text("Sample Applicant\nMedical Doctor\nsample@example.org")
    acbar = profile["job_sources"]["acbar"]
    reliefweb = profile["job_sources"]["reliefweb"]
    assert acbar == {}
    assert reliefweb == {}


@pytest.mark.asyncio
async def test_acbar_explicit_urls_are_scoped_partial_scan(monkeypatch):
    pinned_url = "https://www.acbar.org/en/jobs?page=7"
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({7: PAGE_ONE})())
    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"urls": [pinned_url]}}})
    assert len(jobs) == 2
    assert jobs.metrics.pagination_stop_reason == "EXPLICIT_URL_SET_COMPLETE"
    assert "EXPLICIT_URL_SCOPE" in jobs.metrics.partial_reasons


def test_reliefweb_limit_is_current_positive_source_setting():
    assert discovery._configured_positive_int({"limit": 20}, "reliefweb", "limit", 10) == 20
    with pytest.raises(ValueError):
        discovery._configured_positive_int({"limit": 0}, "reliefweb", "limit", 10)
