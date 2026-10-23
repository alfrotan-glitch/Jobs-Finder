from datetime import date
from pathlib import Path

import pytest

from utils import discovery
from utils.discovery import NO_RELEVANT_JOBS_FOUND, PARTIAL_SCAN, SOURCES_UNAVAILABLE

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_current_acbar_listing_structure_and_host_variants():
    jobs = discovery._parse_acbar_listing(fixture("acbar_listing.html"), "https://www.acbar.org/en/jobs?page=2")
    deduped = discovery._deduplicate_source_vacancies(jobs, today=date(2026, 10, 1))

    assert len(jobs) == 7  # malformed link is isolated
    assert len(deduped) == 6  # www/server aliases for vacancy 145910 collapse
    by_title = {job.title: job for job in deduped}
    assert by_title["Medical Doctor (MD)"].company == "HealthNet TPO"
    assert by_title["Medical Doctor (MD)"].location == "Nangarhar"
    assert by_title["Medical Doctor (MD)"].metadata["closing_date"] == "2026-10-10"
    assert by_title["Medical Doctor (Female) (Re Announced)"].url.startswith("https://server.acbar.org/")
    assert by_title["Nurse"].title == "Nurse"
    assert by_title["Production Pharmacist"].title == "Production Pharmacist"


def test_acbar_detail_email_route_and_provenance():
    summary = discovery._parse_acbar_listing(fixture("acbar_listing.html"), "https://www.acbar.org/en/jobs?page=2")[3]
    job = discovery._parse_acbar_detail(fixture("acbar_detail.html"), summary)

    # A generic current-site h2 must not replace the vacancy title.
    assert job.title == "Medical Doctor (MD)"
    assert job.company == "HealthNet TPO"
    assert job.location == "Nangarhar - Kama"
    assert job.metadata["closing_date"] == "2026-10-10"
    assert job.metadata["reference_number"] == "HNTPO-MD-1012026"
    assert job.apply_email == "recruitment@example.org"
    assert job.application_method == "EMAIL"
    assert job.metadata["gender"] == "Male/Female"
    assert job.metadata["source_provenance"][-1]["source"] == "ACBAR detail"


def test_acbar_employer_is_not_derived_from_organizational_context_heading():
    # Real CTG postings include "Organizational context:" but no field
    # literally called "Organization". Previous substring matching returned
    # the fabricated employer "al context:" and overwrote CTG.
    listing = (
        '<article class="job-card">'
        '<a href="/en/jobs/details/146110/district-polio-officer-dpo">'
        'District Polio Officer (DPO)</a>'
        '<p>CTG • Full Time</p><p>Kandahar 2026-10-24</p></article>'
    )
    job = discovery._parse_acbar_listing(listing, "https://www.acbar.org/en/jobs")[0]
    assert job.company == "CTG"
    detail = (
        '<h1>District Polio Officer (DPO)</h1>'
        '<h2>Job Summary</h2>'
        '<p>Organizational context:</p>'
        '<p>The incumbent will support Polio eradication.</p>'
        '<h2>Job Requirements</h2><p>Medical Doctor preferred.</p>'
        '<h2>Submission Guideline</h2>'
        '<p>Click Register and Apply on Tayo.</p>'
        '<p>Email / Application Form: '
        'https://app.tayohr.io/jobs/detail/vac-75835-district-polio-officer-dpo-74521</p>'
        '<h2>Contact Us</h2><p>webinfo@acbar.org</p>'
    )
    parsed = discovery._parse_acbar_detail(detail, job)
    assert parsed.company == "CTG"
    assert "organization" not in parsed.metadata
    assert parsed.application_method == "WEB"
    assert parsed.apply_url == (
        "https://app.tayohr.io/jobs/detail/vac-75835-district-polio-officer-dpo-74521"
    )
    assert not parsed.apply_email
    assert discovery._labeled_value("Organizational context:\nThe incumbent", r"Organization") == ""


def test_acbar_company_exact_label_and_other_label_whitespace_still_work():
    assert discovery._labeled_value("Organization: HealthNet TPO\nLocation: Kabul", r"Organization") == "HealthNet TPO"
    assert discovery._labeled_value("Organization\nCTG\nLocation: Kabul", r"Organization") == "CTG"
    assert discovery._labeled_value("Job Location: Helmand", r"(?:Job )?Location") == "Helmand"
    assert discovery._labeled_value("Organizational context:\nMisleading", r"Organization") == ""


def test_partial_scan_dashboard_does_not_hide_recommended_deadlines():
    js = (Path(__file__).parents[1] / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    step = js[js.index("function renderNextStep() {"):js.index("function recommendationProvenanceNotice()")]
    assert 'scanStatus === "PARTIAL_SCAN"' in step
    assert "Check requirements before the deadline" in step
    assert 'data-action="view-job"' in step
    assert "Some sources were partially checked" in step
    # A partial scan may retain actionable jobs, so source issues are not
    # allowed to override all of the recommended results.
    assert step.index("const available = state.recommended.filter") < step.index('if (scanStatus === "PARTIAL_SCAN")')


def test_acbar_detail_web_application_route():
    summary = discovery._parse_acbar_listing(fixture("acbar_listing.html"), "https://www.acbar.org/en/jobs?page=2")[0]
    job = discovery._parse_acbar_detail(fixture("acbar_detail_web.html"), summary)
    assert job.title == "Medical Officer"
    assert job.apply_url == "https://careers.example.org/apply/medical-officer"
    assert job.application_method == "WEB"


def test_reliefweb_listing_country_dedup_and_detail():
    jobs = discovery._parse_reliefweb_listing(
        fixture("reliefweb_listing.html"), "https://reliefweb.int/jobs?country=Afghanistan", limit=20, today=date(2026, 10, 1)
    )
    assert len(jobs) == 2
    assert {job.title for job in jobs} == {"Health Programme Officer", "Finance Manager"}
    assert all(job.location == "Afghanistan" for job in jobs)

    medical = discovery._parse_reliefweb_detail(fixture("reliefweb_detail.html"), jobs[0])
    assert medical.company == "World Health Organization"
    assert medical.metadata["closing_date"] == "2026-10-15"
    assert medical.apply_url == "https://careers.who.int/apply/420001"
    assert discovery._job_is_relevant(medical)
    assert not discovery._job_is_relevant(jobs[1])


class Response:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class Client:
    def __init__(self, pages):
        self.pages = pages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if url not in self.pages:
            raise RuntimeError(f"unexpected URL: {url}")
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return Response(value)


@pytest.mark.asyncio
async def test_pipeline_reports_parsed_before_relevance(monkeypatch):
    listing = "https://www.acbar.org/en/jobs"
    parsed = discovery._parse_acbar_listing(fixture("acbar_listing.html"), listing)
    pages = {listing: fixture("acbar_listing.html"), "https://www.acbar.org/en/jobs?page=2": ""}
    for job in parsed:
        pages[job.url] = fixture("acbar_detail.html") if "145902" in job.url else "<h2>Job Requirements</h2><p>Non-medical duties.</p>"
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: Client(pages))

    result = await discovery.run_discovery_scan(
        {"sources": {"enabled": ["acbar"]}},
        today=date(2026, 10, 1),
    )
    report = result.source_reports[0]
    assert report.pagination_stop_reason == "END_REACHED"
    assert report.status == "SCANNED"
    assert report.vacancies_parsed == 7
    assert report.duplicates_removed == 1
    assert report.relevant_retained >= 1
    assert report.relevant_retained == len(result.jobs)
    assert any(job.title == "Medical Doctor (MD)" for job in result.jobs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("good_jobs", "bad", "expected"),
    [
        ([], False, NO_RELEVANT_JOBS_FOUND),
        ([], True, PARTIAL_SCAN),
        (None, True, SOURCES_UNAVAILABLE),
    ],
)
async def test_scan_status_matrix(monkeypatch, good_jobs, bad, expected):
    async def good(profile):
        if good_jobs is None:
            raise RuntimeError("offline")
        return good_jobs

    async def broken(profile):
        raise RuntimeError("blocked")

    monkeypatch.setitem(discovery.SOURCE_REGISTRY, "fixture_good", {"name": "Fixture", "tier": "A", "fetcher": "good", "active": True})
    monkeypatch.setattr(discovery, "good", good, raising=False)
    enabled = ["fixture_good"]
    if bad:
        monkeypatch.setitem(discovery.SOURCE_REGISTRY, "fixture_bad", {"name": "Broken", "tier": "B", "fetcher": "broken", "active": True})
        monkeypatch.setattr(discovery, "broken", broken, raising=False)
        enabled.append("fixture_bad")
    result = await discovery.run_discovery_scan({"sources": {"enabled": enabled}}, today=date(2026, 10, 1))
    assert result.status == expected



def test_reliefweb_fixture_expiry_changes_with_reference_date():
    """Old fixture deadlines must not make this test date-dependent."""
    html = fixture("reliefweb_listing.html")
    url = "https://reliefweb.int/jobs?country=Afghanistan"
    assert len(discovery._parse_reliefweb_listing(html, url, limit=20, today=date(2026, 10, 1))) == 2
    assert discovery._parse_reliefweb_listing(html, url, limit=20, today=date(2026, 11, 1)) == []
