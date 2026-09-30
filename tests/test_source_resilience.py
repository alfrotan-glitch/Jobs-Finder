import pytest


@pytest.mark.asyncio
async def test_source_failure_does_not_break_discovery(monkeypatch):
    import utils.afghan_sources as afghan_sources
    from utils.discovery import discover_all_jobs

    async def boom(profile):
        raise RuntimeError("source down")

    monkeypatch.setattr(afghan_sources, "discover_acbar_jobs", boom)
    profile = {
        "personal": {"first_name": "A", "last_name": "Doctor", "email": "a@example.org"},
        "preferences": {"roles": ["Medical Officer"], "locations": ["Kabul"]},
        "job_sources": {"acbar": {"enabled": True}, "reliefweb": {"enabled": False}, "official_career_pages": []},
        "search": {"generic_job_boards_enabled": False},
    }
    jobs = await discover_all_jobs(profile)
    assert jobs == []
    audit = profile.get("_watcher_source_audit", {})
    assert "ACBAR" in audit.get("attempted", [])
    assert any(err.get("source") == "ACBAR" and "source down" in err.get("error", "") for err in audit.get("failed", []))
    assert not audit.get("successful")


def test_web_search_ingest_parser_preserves_acbar_description_and_facts():
    from utils.mcp_source import parse_web_search_results

    jobs = parse_web_search_results([
        {
            "title": "ACBAR: Quality of Care and Capacity Building Officer",
            "url": "https://www.acbar.org/en/jobs/details/145861/quality-of-care-and-capacity-building-officer",
            "description": "Organization: Relief International (RI) - Job Location: Nimruz - Deadline: 2026-10-04. Job Requirements: Bachelor's degree in Medicine (MD). Minimum 3-5 years of relevant experience in the health sector, BPHS/EPHS, HMIS. Via email: vacancies.afghanistan@ri.org. Subject like (RI-NIM-SAFE-2026-13)",
        }
    ], platform_hint="acbar_web")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["description"]
    assert job["company"] == "Relief International (RI)"
    assert job["location"] == "Nimruz"
    assert job["metadata"]["application_email"] == "vacancies.afghanistan@ri.org"
    assert job["metadata"]["application_subject"] == "RI-NIM-SAFE-2026-13"
    assert job["metadata"]["closing_date"] == "2026-10-04"
    assert job["metadata"]["source_url"] == "https://www.acbar.org/en/jobs/details/145861/quality-of-care-and-capacity-building-officer"
