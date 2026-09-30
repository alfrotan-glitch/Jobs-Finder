import json
from pathlib import Path

import pytest

from utils.discovery import Job, discover_all_jobs
from utils.source_registry import (
    active_sources_for_discovery,
    deduplicate_registry_sources,
    load_source_registry,
    registry_enhanced_profile,
    registry_status_counts,
    validate_source_registry,
)
from utils.afghan_sources import _enrich_static_job_from_detail, _jobs_from_html, discover_oracle_hcm_jobs


def _record(**overrides):
    base = {
        "id": "test_source",
        "organization_name": "Test Source",
        "source_category": "afghanistan_job_board",
        "country_coverage": "Afghanistan",
        "official_website": "https://example.org/",
        "official_jobs_url": "https://example.org/jobs",
        "discovery_method": "registry_static_html",
        "source_type": "afghan_job_board",
        "afghanistan_relevance": "High",
        "health_medical_relevance": "High",
        "public_accessibility": "public",
        "login_required": False,
        "captcha_blocking_status": "none_observed",
        "application_url_availability": "yes",
        "provenance_level": "medium",
        "reliability_status": "ACTIVE",
        "last_checked": "2026-09-30",
        "checked_by": "test",
        "last_check_result": "Checked in test",
        "limitations": "None",
        "notes": "Test record",
        "enabled_in_autonomous_discovery": True,
        "adapter_config": {"require_afghanistan": False},
        "tags": ["medical"],
    }
    base.update(overrides)
    return base


def test_default_registry_loads_and_validates():
    records = load_source_registry()
    assert len(records) >= 30
    errors = validate_source_registry(records)
    assert errors == []
    counts = registry_status_counts(records)
    assert counts["ACTIVE"] >= 5
    assert counts["BLOCKED"] >= 2
    assert counts["INACCESSIBLE"] >= 1
    assert counts["NOT_IMPLEMENTED"] >= 1


def test_active_sources_exclude_disabled_blocked_and_inaccessible(tmp_path):
    records = [
        _record(id="active", official_jobs_url="https://active.example/jobs"),
        _record(
            id="blocked",
            official_jobs_url="https://blocked.example/jobs",
            reliability_status="BLOCKED",
            public_accessibility="blocked",
            captcha_blocking_status="blocked",
            enabled_in_autonomous_discovery=False,
        ),
        _record(
            id="disabled",
            official_jobs_url="https://disabled.example/jobs",
            enabled_in_autonomous_discovery=False,
        ),
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    profile = {"source_registry": {"enabled": True, "path": str(path)}}
    active = active_sources_for_discovery(profile)
    assert [item["id"] for item in active] == ["active"]

    profile["source_registry"]["disabled_source_ids"] = ["active"]
    assert active_sources_for_discovery(profile) == []


def test_registry_duplicate_urls_are_reported_and_deduped():
    records = [
        _record(id="one", official_jobs_url="https://example.org/jobs"),
        _record(id="two", official_jobs_url="https://www.example.org/jobs/"),
    ]
    errors = validate_source_registry(records)
    assert any("duplicate jobs URL" in error for error in errors)
    unique = deduplicate_registry_sources(records)
    assert [item["id"] for item in unique] == ["one"]


def test_registry_enhanced_profile_maps_active_sources_to_runtime_config(tmp_path):
    records = [
        _record(
            id="acbar",
            organization_name="ACBAR",
            official_website="https://www.acbar.org/",
            official_jobs_url="https://www.acbar.org/en/jobs",
            discovery_method="acbar_html",
            adapter_config={"legacy_key": "acbar", "urls": ["https://www.acbar.org/en/jobs"]},
        ),
        _record(
            id="moph_vacancies",
            organization_name="MoPH",
            official_website="https://moph.gov.af/en/",
            official_jobs_url="https://moph.gov.af/en/vacancies",
            discovery_method="registry_static_html",
            source_type="government_vacancy_page",
            provenance_level="high",
            adapter_config={"require_afghanistan": False},
        ),
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    profile = {"source_registry": {"enabled": True, "path": str(path)}, "job_sources": {}}
    enhanced = registry_enhanced_profile(profile)
    sources = enhanced["job_sources"]
    assert sources["_source_registry_enabled"] is True
    assert sources["acbar"]["urls"] == ["https://www.acbar.org/en/jobs"]
    assert sources["registry_static_sources"][0]["id"] == "moph_vacancies"


def test_default_registry_maps_oracle_hcm_sources_into_runtime_profile():
    profile = registry_enhanced_profile({"source_registry": {"enabled": True}, "job_sources": {}})
    oracle_ids = [record["id"] for record in profile["job_sources"].get("oracle_hcm_sources", [])]
    assert "iom_recruit" in oracle_ids
    assert "nrc_careers" in oracle_ids
    assert "oracle_hcm_api" in profile["job_sources"]["_source_registry_active_methods"]


def test_registry_static_html_preserves_registry_provenance():
    html = """
    <html><body>
      <a href="/vacancies/medical-director">Medical Director</a>
      <p>Afghanistan Ministry of Public Health hospital leadership role. Doctors and public health specialists. Deadline: 10 Oct 2026.</p>
    </body></html>
    """
    record = _record(
        id="moph_vacancies",
        organization_name="Afghanistan Ministry of Public Health",
        source_category="government_public_sector",
        source_type="government_vacancy_page",
        official_jobs_url="https://moph.gov.af/en/vacancies",
        provenance_level="high",
        reliability_status="ACTIVE",
    )
    jobs = _jobs_from_html(
        html,
        base_url="https://moph.gov.af/en/vacancies",
        source="moph_vacancies",
        default_company="Afghanistan Ministry of Public Health",
        source_type="government_vacancy_page",
        source_record=record,
        require_afghanistan=False,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.metadata["source_name"] == "Afghanistan Ministry of Public Health"
    assert job.metadata["source_category"] == "government_public_sector"
    assert job.metadata["source_reliability"] == "high"
    assert job.metadata["closing_date"] == "2026-10-10"
    assert job.metadata["source_provenance"][0]["registry_id"] == "moph_vacancies"
    assert "https://moph.gov.af/en/vacancies" in job.metadata["source_urls"]


@pytest.mark.asyncio
async def test_orchestrator_uses_registry_active_methods_without_calling_disabled_sources(tmp_path, monkeypatch):
    import utils.afghan_sources as afghan_sources

    records = [
        _record(
            id="unjobs_afghanistan",
            organization_name="UNJobs Afghanistan",
            official_website="https://unjobs.org/",
            official_jobs_url="https://unjobs.org/duty_stations/afghanistan",
            discovery_method="unjobs_html",
            source_type="public_un_international_job_board",
            adapter_config={"legacy_key": "unjobs", "urls": ["https://unjobs.org/duty_stations/afghanistan"]},
        ),
        _record(
            id="acbar",
            organization_name="ACBAR",
            official_website="https://www.acbar.org/",
            official_jobs_url="https://www.acbar.org/en/jobs",
            discovery_method="acbar_html",
            enabled_in_autonomous_discovery=False,
        ),
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(records), encoding="utf-8")

    async def fake_unjobs(profile):
        return [
            Job(
                "u1",
                "Medical Doctor, Kabul",
                "UNAMA",
                "Kabul, Afghanistan",
                "https://unjobs.org/vacancies/1",
                "https://unjobs.org/vacancies/1",
                "unjobs",
                description="Medical Doctor Afghanistan public health. Deadline: 10 Oct 2026.",
                metadata={
                    "source": "unjobs",
                    "source_urls": ["https://unjobs.org/duty_stations/afghanistan", "https://unjobs.org/vacancies/1"],
                    "source_provenance": [{"source": "UNJobs Afghanistan", "url": "https://unjobs.org/duty_stations/afghanistan", "reliability": "medium"}],
                    "closing_date": "2026-10-10",
                },
            )
        ]

    async def should_not_run(profile):
        raise AssertionError("disabled ACBAR source should not be called")

    monkeypatch.setattr(afghan_sources, "discover_unjobs_jobs", fake_unjobs)
    monkeypatch.setattr(afghan_sources, "discover_acbar_jobs", should_not_run)

    profile = {
        "source_registry": {"enabled": True, "path": str(path)},
        "job_sources": {},
        "preferences": {"roles": ["Medical Doctor"], "locations": ["Afghanistan"]},
        "search": {"generic_job_boards_enabled": False},
    }
    jobs = await discover_all_jobs(profile)
    assert [job.id for job in jobs] == ["u1"]
    assert jobs[0].metadata["source_urls"][0] == "https://unjobs.org/duty_stations/afghanistan"



@pytest.mark.asyncio
async def test_oracle_hcm_adapter_parses_afghanistan_detail_and_preserves_provenance(monkeypatch):
    import utils.afghan_sources as afghan_sources

    class FakeResponse:
        def __init__(self, payload=None, text=""):
            self._payload = payload
            self.text = text
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, url):
            if "recruitingCEJobRequisitions" in url:
                return FakeResponse({
                    "items": [{
                        "requisitionList": [{
                            "Id": "9001",
                            "Title": "Medical Doctor",
                            "PostedDate": "2026-09-20",
                            "PostingEndDate": "2026-10-04",
                            "PrimaryLocationCountry": "AF",
                            "PrimaryLocation": "Kabul, Afghanistan",
                            "ShortDescriptionStr": "Medical Doctor for Afghanistan clinic.",
                            "secondaryLocations": [],
                        }]
                    }]
                })
            if "recruitingCEJobRequisitionDetails/9001" in url:
                return FakeResponse({
                    "Id": "9001",
                    "Title": "Medical Doctor",
                    "ExternalPostedStartDate": "2026-09-20T00:00:00+00:00",
                    "ExternalPostedEndDate": "2026-10-04T00:00:00+00:00",
                    "PrimaryLocation": "Kabul, Afghanistan",
                    "PrimaryLocationCountry": "AF",
                    "ExternalDescriptionStr": "Provide clinical consultations and public health reporting in Afghanistan.",
                    "ExternalResponsibilitiesStr": "Diagnose and treat patients; support HMIS reporting.",
                    "ExternalQualificationsStr": "Medical Degree (MD), valid medical registration, two years clinical experience, English and Dari.",
                    "Category": "Medical & Health",
                })
            raise AssertionError(url)

    monkeypatch.setattr(afghan_sources.httpx, "AsyncClient", FakeClient)
    profile = {
        "job_sources": {
            "oracle_hcm_sources": [{
                "id": "iom_recruit",
                "organization_name": "IOM Recruitment",
                "source_category": "international_organization",
                "source_type": "official_employer_career_page",
                "official_jobs_url": "https://oracle.example/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?location=Afghanistan",
                "provenance_level": "high",
                "reliability_status": "ACTIVE",
                "adapter_config": {
                    "oracle_base_url": "https://oracle.example",
                    "site_number": "CX_1001",
                    "location": "Afghanistan",
                    "limit": 10,
                },
            }]
        }
    }
    jobs = await discover_oracle_hcm_jobs(profile)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Medical Doctor"
    assert job.company == "IOM Recruitment"
    assert job.location == "Kabul, Afghanistan"
    assert job.url == "https://oracle.example/hcmUI/CandidateExperience/en/sites/CX_1001/job/9001"
    assert job.metadata["closing_date"] == "2026-10-04"
    assert job.metadata["source_reliability"] == "high"
    assert job.metadata["source_provenance"][0]["method"] == "oracle_hcm_api"
    assert "valid medical registration" in job.description


@pytest.mark.asyncio
async def test_static_registry_detail_fetch_enriches_description_and_source_urls():
    job = Job(
        "akhs_1",
        "Nutrition Counselor",
        "AKHS-A",
        "Kabul",
        "https://akhs.example/jobs/detail/nutrition-counselor-126",
        "https://akhs.example/jobs/detail/nutrition-counselor-126",
        "akdn_careers",
        description="Nutrition Counselor Kabul October 10, 2026",
        metadata={
            "source": "akdn_careers",
            "source_url": "https://akhs.example/jobs",
            "source_urls": ["https://akhs.example/jobs"],
            "source_provenance": [],
        },
    )
    record = {
        "id": "akdn_careers",
        "organization_name": "Aga Khan Health Services Afghanistan (AKHS-A)",
        "provenance_level": "high",
    }

    class FakeResponse:
        text = "<h1>Nutrition Counselor</h1><p>Job Requirements: nutrition counseling, GMP, maternal and child health. Closing Date: Oct 10, 2026.</p><a href='https://forms.example/apply'>Apply now</a>"
        def raise_for_status(self):
            return None

    class FakeClient:
        async def get(self, url):
            assert url == job.url
            return FakeResponse()

    await _enrich_static_job_from_detail(FakeClient(), job, record)
    assert "maternal and child health" in job.description
    assert job.metadata["detail_fetched"] is True
    assert job.metadata["closing_date"] == "2026-10-10"
    assert job.apply_url == "https://forms.example/apply"
    assert job.apply_url in job.metadata["source_urls"]
    assert job.url in job.metadata["source_urls"]
    assert job.metadata["source_provenance"][0]["method"] == "detail_page"
