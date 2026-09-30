from datetime import date

import pytest

from utils.discovery import (
    Job,
    RawVacancy,
    deduplicate_jobs,
    is_job_fresh,
    normalize_raw_vacancy,
    normalized_to_job,
    validate_normalized_vacancy,
)
from utils.afghan_sources import _jobs_from_html, _unicef_raw_from_html, _unjobs_raw_from_html, discover_official_career_pages


def test_normalized_vacancy_preserves_required_source_fields_and_provenance():
    raw = RawVacancy(
        source="unicef_careers",
        source_type="official_employer_career_page",
        source_url="https://jobs.unicef.org/en-us/search/?search-keyword=Afghanistan",
        original_url="https://jobs.unicef.org/en-us/job/123/polio-consultant-kabul",
        organization="UNICEF - United Nations Children's Fund",
        title="Information Management Consultant, Polio Section, Afghanistan",
        location="Kabul, Afghanistan",
        description="Polio programme information management role. Deadline: 4 Oct 2026.",
        application_url="https://jobs.unicef.org/en-us/job/123/polio-consultant-kabul",
        reliability="high",
        provenance=[{"source": "UNICEF official careers", "url": "https://jobs.unicef.org", "reliability": "high"}],
    )
    vacancy = normalize_raw_vacancy(raw)
    ok, errors = validate_normalized_vacancy(vacancy)
    assert ok, errors
    assert vacancy.source == "unicef_careers"
    assert vacancy.source_url.startswith("https://jobs.unicef.org")
    assert vacancy.original_vacancy_url.endswith("polio-consultant-kabul")
    assert vacancy.organization == "UNICEF - United Nations Children's Fund"
    assert vacancy.application_url == raw.application_url
    assert vacancy.source_reliability == "high"
    assert vacancy.source_provenance[0]["reliability"] == "high"

    job = normalized_to_job(vacancy)
    assert job.metadata["source_type"] == "official_employer_career_page"
    assert job.metadata["source_urls"] == [raw.source_url, raw.original_url]
    assert job.metadata["requirements"]["facts"]["source_url"] == raw.source_url


def test_duplicate_vacancies_merge_source_urls_and_provenance():
    first = normalized_to_job(normalize_raw_vacancy(RawVacancy(
        source="acbar",
        source_type="afghan_job_board",
        source_url="https://www.acbar.org/en/jobs",
        original_url="https://www.acbar.org/en/jobs/details/1/medical-doctor",
        organization="Health NGO",
        title="Medical Doctor",
        location="Kabul",
        description="Medical Doctor required. Deadline: 10 Oct 2026. Apply at https://ngo.example/jobs/1",
        application_url="https://ngo.example/jobs/1",
        reference_number="HN-1",
        provenance=[{"source": "ACBAR", "url": "https://www.acbar.org/en/jobs/details/1/medical-doctor", "reliability": "medium"}],
    )))
    second = normalized_to_job(normalize_raw_vacancy(RawVacancy(
        source="official_career_page",
        source_type="official_employer_career_page",
        source_url="https://ngo.example/careers",
        original_url="https://ngo.example/jobs/1",
        organization="Health NGO",
        title="Medical Doctor",
        location="Kabul",
        description="Official Medical Doctor vacancy with longer details. Deadline: 10 Oct 2026.",
        application_url="https://ngo.example/jobs/1",
        reference_number="HN-1",
        reliability="high",
        provenance=[{"source": "Official employer", "url": "https://ngo.example/jobs/1", "reliability": "high"}],
    )))
    merged = deduplicate_jobs([first, second])
    assert len(merged) == 1
    canonical = merged[0]
    assert "https://www.acbar.org/en/jobs/details/1/medical-doctor" in canonical.metadata["source_urls"]
    assert "https://ngo.example/jobs/1" in canonical.metadata["source_urls"]
    assert any(item.get("reliability") == "high" for item in canonical.metadata["source_provenance"])
    assert canonical.metadata["duplicate_ids"] == [second.id]


def test_shared_email_apply_destination_does_not_merge_distinct_vacancies():
    first = Job(
        id="arcs-vaccinator",
        title="Vaccinator",
        company="ARCS",
        location="Kandahar",
        url="https://www.acbar.org/en/jobs/details/1/vaccinator",
        apply_url="mailto:hr@arcs.af",
        platform="acbar",
        description="Vaccinator role. Closing date: 2026-10-06.",
        metadata={"source_url": "https://www.acbar.org/en/jobs/details/1/vaccinator"},
    )
    second = Job(
        id="arcs-cardiologist",
        title="Cardiology Specialist Doctor",
        company="ARCS",
        location="Kabul",
        url="https://www.acbar.org/en/jobs/details/2/cardiologist",
        apply_url="mailto:hr@arcs.af",
        platform="acbar",
        description="Cardiology role. Closing date: 2026-10-05.",
        metadata={"source_url": "https://www.acbar.org/en/jobs/details/2/cardiologist"},
    )
    assert len(deduplicate_jobs([first, second])) == 2


def test_deadline_freshness_filter_is_conservative():
    future = {"metadata": {"closing_date": "2026-10-10"}}
    same_day = {"metadata": {"closing_date": "2026-09-30"}}
    expired = {"metadata": {"closing_date": "2026-09-29"}}
    undated = {"metadata": {}}
    assert is_job_fresh(future, today=date(2026, 9, 30))
    assert is_job_fresh(same_day, today=date(2026, 9, 30))
    assert not is_job_fresh(expired, today=date(2026, 9, 30))
    assert is_job_fresh(undated, today=date(2026, 9, 30))


def test_unjobs_adapter_parses_medical_afghanistan_listing_with_medium_provenance():
    html = """
    <html><body>
      <p><a href="/vacancies/1790258574072">Medical Doctor, Mazar-i-Sharif, Afghanistan</a><br>
      UNAMA - United Nations Assistance Mission in Afghanistan<br>
      Updated: 6 days ago<br>
      Closing date: Thursday, 8 October 2026</p>
      <p><a href="/vacancies/2">Finance Officer, Kabul</a><br>UNDP<br>Updated: today</p>
    </body></html>
    """
    raw = _unjobs_raw_from_html(html, "https://unjobs.org/duty_stations/afghanistan", limit=10)
    assert len(raw) == 1
    assert raw[0].title == "Medical Doctor, Mazar-i-Sharif, Afghanistan"
    assert raw[0].source == "unjobs"
    assert raw[0].reliability == "medium"
    assert raw[0].original_url == "https://unjobs.org/vacancies/1790258574072"
    assert raw[0].closing_date == "2026-10-08"


def test_unicef_adapter_parses_official_afghanistan_health_listing_with_high_provenance():
    html = """
    <html><body>
      <h3><a href="/en-us/job/595890/information-management-consultant-polio-section-afghanistan">INTERNATIONALS ONLY - Information Management Consultant, Polio Section, Afghanistan</a></h3>
      <p>UNICEF Afghanistan's Polio Section requires information management support for the polio programme.</p>
      <p><strong>Location:</strong> Afghanistan</p>
      <p><strong>Deadline:</strong> 4 Oct 2026 11:55 PM</p>
      <h3><a href="/en-us/job/595911/contracts-specialist">Contracts Specialist, Kabul, Afghanistan</a></h3>
      <p>Procurement and contracting role.</p>
    </body></html>
    """
    raw = _unicef_raw_from_html(html, "https://jobs.unicef.org/en-us/search/?search-keyword=Afghanistan", limit=10)
    assert len(raw) == 1
    assert raw[0].source == "unicef_careers"
    assert raw[0].reliability == "high"
    assert raw[0].organization.startswith("UNICEF")
    assert "Polio" in raw[0].title
    assert raw[0].closing_date == "2026-10-04"


@pytest.mark.asyncio
async def test_inaccessible_official_career_page_returns_empty_without_exception():
    profile = {
        "job_sources": {
            "official_career_pages": [{"organization": "Broken", "url": "http://127.0.0.1:9/careers"}],
            "career_page_timeout_seconds": 1,
        }
    }
    jobs = await discover_official_career_pages(profile)
    assert jobs == []


def test_existing_acbar_html_behavior_still_extracts_medical_links_with_source_metadata():
    html = """
    <html><body>
      <a href="/en/jobs/details/145999/medical-doctor">Medical Doctor</a>
      <p>HealthNet TPO • Full Time Kabul 2026-10-10. Medical Doctor, health facility and HMIS reporting.</p>
    </body></html>
    """
    jobs = _jobs_from_html(html, base_url="https://www.acbar.org/en/jobs", source="acbar", default_company="ACBAR")
    assert len(jobs) == 1
    assert jobs[0].title == "Medical Doctor"
    assert jobs[0].url == "https://www.acbar.org/en/jobs/details/145999/medical-doctor"
    assert jobs[0].metadata["source"] == "acbar"
    assert jobs[0].metadata["source_urls"] == ["https://www.acbar.org/en/jobs", jobs[0].url]
