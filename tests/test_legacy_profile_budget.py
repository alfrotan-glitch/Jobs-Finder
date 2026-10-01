"""Regression tests for the LIVE ACBAR cap reported from a real Windows run.

Root cause (confirmed against git history and the user profile): before the
full-market change the registry's ACBAR defaults contained a bounded budget
(``max_pages: 6`` / ``detail_limit: 30``) and ``utils/profile_builder.py``
copied ``source_defaults()`` verbatim into every profile.yaml it generated.
The registry default was later removed, but profiles created during that era
still carry the literal values, so every real scan kept reading them as an
"explicit" cap: 6 pages / 134 of 234 listings / PAGE_LIMIT_REACHED / PARTIAL.

These tests prove:

1. A profile WITHOUT limits scans to the source's real end (END_REACHED,
   SCANNED, every listing seen — the requested "no max_pages/no detail_limit"
   validation).
2. A profile carrying the untouched legacy builder block behaves unbounded
   (load-time migration + discovery-level normalization agree).
3. Explicitly configured limits still work exactly as before (PARTIAL).
4. The CV importer no longer bakes ANY operational defaults into profile.yaml.
5. Any user-touched override block is preserved bit-for-bit.
"""

from datetime import date

import pytest

import main
from utils import discovery
from utils.discovery import Job
from utils.profile_builder import build_profile_from_cv_text
from utils.source_registry import (
    normalize_profile_source_budgets,
    normalize_source_overrides,
)

LEGACY_ACBAR_BLOCK = {"timeout_seconds": 25.0, "detail_limit": 30, "max_pages": 6, "max_detail_concurrency": 5}


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
    """Requested validation #2: no max_pages and no detail_limit → unbounded."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"personal": {"first_name": "A"}})
    _assert_unbounded_full_scan(jobs)


@pytest.mark.asyncio
async def test_legacy_builder_budget_block_does_not_cap_real_scan(monkeypatch):
    """The exact profile.yaml block a CV import wrote during the bounded era."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    profile = {"job_sources": {"acbar": dict(LEGACY_ACBAR_BLOCK)}}
    jobs = await discovery.discover_acbar_jobs(profile)
    _assert_unbounded_full_scan(jobs)


@pytest.mark.asyncio
async def test_explicit_max_pages_still_caps_and_marks_partial(monkeypatch):
    """Requested validation #3: a deliberate user limit is honored + PARTIAL."""
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _paged_client({1: PAGE_ONE, 2: PAGE_TWO, 3: ""})())
    jobs = await discovery.discover_acbar_jobs({"job_sources": {"acbar": {"max_pages": 1}}})
    assert jobs.metrics.configured_page_limit == 1
    assert jobs.metrics.pagination_stop_reason == "PAGE_LIMIT_REACHED"
    assert jobs.metrics.status == "PARTIAL"
    assert "PAGINATION_NOT_EXHAUSTED" in jobs.metrics.partial_reasons
    assert jobs.metrics.pages_requested == 1


@pytest.mark.asyncio
async def test_explicit_detail_limit_defers_candidates_and_marks_partial(monkeypatch):
    """Requested validation #4: a deliberate detail budget defers openly."""
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
# The normalization rule itself
# ---------------------------------------------------------------------------


def test_verbatim_legacy_block_is_stripped_with_report():
    effective, removed = normalize_source_overrides("acbar", dict(LEGACY_ACBAR_BLOCK))
    assert "max_pages" not in effective and "detail_limit" not in effective
    assert removed == {"max_pages": 6, "detail_limit": 30}


def test_user_modified_block_is_never_touched():
    modified = {**LEGACY_ACBAR_BLOCK, "detail_limit": 50}
    effective, removed = normalize_source_overrides("acbar", modified)
    assert removed == {}
    assert effective == modified


def test_user_explicit_single_key_is_never_touched():
    explicit = {"max_pages": 6}  # deliberately typed by the user
    effective, removed = normalize_source_overrides("acbar", explicit)
    assert removed == {}
    assert effective == explicit


def test_unknown_extra_key_marks_block_as_user_owned():
    block = {**LEGACY_ACBAR_BLOCK, "urls": ["https://example.org/jobs"]}
    effective, removed = normalize_source_overrides("acbar", block)
    assert removed == {}
    assert effective == block


def test_profile_level_migration_reports_and_preserves():
    legacy_profile = {"personal": {"first_name": "A"}, "job_sources": {"acbar": dict(LEGACY_ACBAR_BLOCK)}}
    cleaned, notes = normalize_profile_source_budgets(legacy_profile)
    assert "max_pages" not in cleaned["job_sources"]["acbar"]
    assert notes and "max_pages=6" in notes[0] and "detail_limit=30" in notes[0]

    user_profile = {"personal": {"first_name": "A"}, "job_sources": {"acbar": {"max_pages": 6, "detail_limit": 30}}}
    cleaned, notes = normalize_profile_source_budgets(user_profile)
    assert cleaned["job_sources"]["acbar"] == {"max_pages": 6, "detail_limit": 30}
    assert notes == []


def test_cv_import_no_longer_materializes_source_defaults():
    """Root-cause fix: the importer never bakes operational defaults again."""
    profile = build_profile_from_cv_text("Jane Doe\nMedical Doctor\njane@example.org", resume_path="cv.txt")
    acbar = profile["job_sources"]["acbar"]
    reliefweb = profile["job_sources"]["reliefweb"]
    assert "max_pages" not in acbar and "detail_limit" not in acbar
    assert "limit" not in reliefweb
    assert acbar == {} and reliefweb == {}


def test_main_load_profile_migrates_legacy_budget_and_says_so(tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    path.write_text(
        "personal:\n  first_name: Jane\n  last_name: Doe\n  email: j@example.org\n"
        "job_sources:\n  acbar:\n    timeout_seconds: 25.0\n    detail_limit: 30\n"
        "    max_pages: 6\n    max_detail_concurrency: 5\n",
        encoding="utf-8",
    )
    profile = main.load_profile(str(path))
    assert "max_pages" not in profile["job_sources"]["acbar"]
    assert "detail_limit" not in profile["job_sources"]["acbar"]
    out = capsys.readouterr().out
    assert "legacy" in out.lower() and "max_pages=6" in out


@pytest.mark.asyncio
async def test_deferred_candidates_stay_in_canonical_accounting(monkeypatch):
    """Two-stage design: full discovery first, conservative detail enrichment
    second; budget-deferred listings keep one explicit terminal outcome."""
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
