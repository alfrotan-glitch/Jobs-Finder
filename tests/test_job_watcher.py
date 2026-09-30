from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from utils.discovery import Job
from utils import tracker
from utils.job_watcher import (
    ACTIVE_STATUS,
    EXPIRED_STATUS,
    NEEDS_VERIFICATION,
    READY_TO_APPLY,
    begin_scan,
    canonical_job_id,
    get_actionable_opportunities,
    get_notifications,
    get_scan_audits,
    get_watcher_jobs,
    get_watcher_summary,
    prepare_application_for_watcher_job,
    run_job_watch_scan,
)


@pytest.fixture()
def watcher_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "watcher.db")
    return tmp_path / "watcher.db"


@pytest.fixture()
def profile(tmp_path):
    return {
        "personal": {
            "first_name": "Allah Yar",
            "last_name": "Frotan",
            "email": "doctor@example.org",
            "location": "Kabul, Afghanistan",
            "nationality": "Afghan",
            "gender": "Male",
        },
        "resume_path": str(tmp_path / "missing-cv.txt"),
        "medical_education": [{"degree": "MD", "institution": "Kabul Medical Science University", "verified": True}],
        "license_registration": {"verified": True, "status": "Verified", "authority": "Afghan Medical Council", "number": ""},
        "medical_exit_exam": {"verified": True, "status": "Verified"},
        "clinical_experience": {"years": 3},
        "work_history": [
            {"title": "TFU Medical Doctor", "organization": "ACF", "location": "Daikundi", "start": "2023-05", "end": "2025-07", "bullets": ["Provided clinical care, HMIS reporting, IMAM/CMAM nutrition services, IPC and PSEA."]},
            {"title": "Health and Nutrition Supervisor", "organization": "ACF", "location": "Daikundi", "start": "2022-02", "end": "2022-12", "bullets": ["Supervised BPHS/EPHS mobile health and nutrition teams."]},
        ],
        "skills": {"medical": ["Clinical care", "HMIS", "BPHS", "EPHS", "IMAM", "IPC"], "management": ["Supervision"]},
        "languages": [{"name": "Dari"}, {"name": "Pashto"}, {"name": "English"}],
        "preferences": {"locations": ["Afghanistan", "Kabul"], "willing_to_relocate": True, "field_deployment": True},
        "job_sources": {"test_source": {"enabled": True}},
        "search": {"generic_job_boards_enabled": False},
        "watcher": {"enabled": True, "deadline_alert_days": [7, 3, 1], "auto_prepare_ready_to_apply": False},
        "schedule": {"enabled": True, "job_watch_interval_hours": 6},
    }


def medical_job(
    *,
    job_id="fmic-mo",
    title="Medical Officer",
    company="FMIC",
    source="fmic",
    url="https://www.fmic.org.af/WorkWithUs/vacancies/Pages/Medical-Officer-2026.aspx",
    apply_url="https://docs.google.com/forms/d/test/edit",
    location="Kabul, Afghanistan",
    closing="2026-10-05",
    description_extra="",
):
    description = f"""
    Medical Officer. MD medical degree required. Valid medical registration required.
    At least 1 year clinical experience in a hospital setting. Infection prevention and control,
    patient safety, English, Dari and Pashto required. Afghanistan experience preferred.
    Apply at {apply_url}. Closing date: {closing}. {description_extra}
    """
    return Job(
        id=job_id,
        title=title,
        company=company,
        location=location,
        url=url,
        apply_url=apply_url,
        platform=source,
        description=description,
        metadata={
            "source": source,
            "source_url": f"https://source.example/{source}",
            "original_vacancy_url": url,
            "source_urls": [f"https://source.example/{source}", url],
            "source_provenance": [{"source": source, "url": url, "reliability": "high"}],
            "source_reliability": "high",
            "posting_date": "2026-09-30",
            "closing_date": closing,
        },
    )


def surgeon_needs_verification_job():
    return medical_job(
        job_id="akhs-surgeon",
        title="Surgeon",
        company="AKHS-A",
        source="akdn_careers",
        url="https://akhs.odoo.com/jobs/detail/surgeon-125",
        apply_url="https://akhs.odoo.com/jobs/detail/surgeon-125",
        closing="2026-10-10",
        description_extra="Requires Specialist Surgeon qualification and specialist certification in general surgery.",
    )


async def scan(profile, jobs, **kwargs):
    async def discovery(_profile):
        return jobs

    return await run_job_watch_scan(
        profile,
        discovery_func=discovery,
        now=kwargs.pop("now", datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)),
        today=kwargs.pop("today", date(2026, 9, 30)),
        resume_text="MD doctor with three years clinical experience, HMIS, BPHS, EPHS, IMAM, IPC, Dari, English, Pashto.",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_new_vacancy_detection_persists_state_and_notification(watcher_db, profile):
    result = await scan(profile, [medical_job()])
    assert result["new_count"] == 1
    assert result["ready_to_apply_count"] == 1
    jobs = get_watcher_jobs()
    assert len(jobs) == 1
    assert jobs[0]["canonical_id"] == canonical_job_id(medical_job())
    assert jobs[0]["first_discovered_at"]
    assert jobs[0]["last_seen_at"]
    assert jobs[0]["readiness_status"] == READY_TO_APPLY
    assert jobs[0]["current_status"] == ACTIVE_STATUS
    assert any(n["event_type"] == "new_ready_to_apply_job" for n in get_notifications())


@pytest.mark.asyncio
async def test_unchanged_vacancy_does_not_duplicate_or_renotify(watcher_db, profile):
    job = medical_job()
    await scan(profile, [job])
    before_notifications = len(get_notifications())
    result = await scan(profile, [job], now=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))
    assert result["new_count"] == 0
    assert result["updated_count"] == 0
    assert result["unchanged_count"] == 1
    assert len(get_watcher_jobs()) == 1
    assert len(get_notifications()) == before_notifications


@pytest.mark.asyncio
async def test_material_vacancy_update_detects_changed_fields(watcher_db, profile):
    await scan(profile, [medical_job()])
    updated = medical_job(closing="2026-10-06", description_extra="New requirement: SafeCare audit participation.")
    result = await scan(profile, [updated], now=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc), today=date(2026, 10, 1))
    assert result["updated_count"] == 1
    change = result["changes"][0]
    assert "closing_date" in change["changed_fields"]
    assert "description" in change["changed_fields"]
    assert any(n["event_type"] == "vacancy_updated_materially" for n in get_notifications())


@pytest.mark.asyncio
async def test_closing_expiration_marks_vacancy_not_actionable(watcher_db, profile):
    await scan(profile, [medical_job(closing="2026-09-29")])
    jobs = get_watcher_jobs(active_only=False)
    assert jobs[0]["current_status"] == EXPIRED_STATUS
    assert get_watcher_jobs(active_only=True) == []
    assert tracker.get_job_by_id(jobs[0]["canonical_id"])["status"] == "not_eligible"
    assert tracker.get_recommended_jobs() == []
    assert any(n["event_type"] == "vacancy_closed" for n in get_notifications())


@pytest.mark.asyncio
async def test_duplicate_discovery_only_creates_one_canonical_vacancy(watcher_db, profile):
    job = medical_job(job_id="a")
    duplicate = medical_job(job_id="b", url=job.url, apply_url=job.apply_url)
    result = await scan(profile, [job, duplicate])
    assert result["discovered_count"] == 2
    assert result["deduplicated_count"] == 1
    assert result["new_count"] == 1
    assert len(get_watcher_jobs()) == 1


@pytest.mark.asyncio
async def test_cross_source_duplicate_merges_source_urls(watcher_db, profile):
    official = medical_job(source="fmic", company="FMIC")
    board = medical_job(
        job_id="wazifaha-copy",
        source="wazifaha",
        company="FMIC",
        url="https://www.wazifaha.org/jobs/fmic-medical-officer",
        apply_url=official.apply_url,
    )
    result = await scan(profile, [official, board])
    assert result["deduplicated_count"] == 1
    urls = get_watcher_jobs()[0]["source_urls"]
    assert official.url in urls
    assert board.url in urls


@pytest.mark.asyncio
async def test_source_failure_does_not_destroy_successful_results(watcher_db, profile):
    await scan(profile, [medical_job()])

    async def discovery(_profile):
        return {
            "jobs": [medical_job(job_id="fmic-mo-2", title="Medical Doctor", url="https://example.org/new-md")],
            "sources_attempted": ["fmic", "broken_source"],
            "sources_successful": ["fmic"],
            "source_errors": [{"source": "broken_source", "error": "TLS failure"}],
        }

    result = await run_job_watch_scan(
        profile,
        discovery_func=discovery,
        now=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
        today=date(2026, 9, 30),
        resume_text="MD doctor with clinical experience, English, Dari, Pashto.",
    )
    assert result["new_count"] == 1
    assert any(err.get("source") == "broken_source" for err in result["sources_failed"])
    assert len(get_watcher_jobs()) == 2
    assert any(n["event_type"] == "source_failure" for n in get_notifications())


@pytest.mark.asyncio
async def test_empty_source_response_does_not_delete_existing_vacancy(watcher_db, profile):
    await scan(profile, [medical_job()])
    result = await scan(profile, [], now=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc))
    assert result["discovered_count"] == 0
    assert result["closed_count"] == 0
    assert len(get_watcher_jobs()) == 1


@pytest.mark.asyncio
async def test_restart_persistence_uses_existing_state(watcher_db, profile):
    job = medical_job()
    await scan(profile, [job])
    # Simulate restart by simply running a fresh scan against the same SQLite DB.
    result = await scan(profile, [job], now=datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))
    assert result["unchanged_count"] == 1
    assert get_watcher_summary()["counts"]["active"] == 1


@pytest.mark.asyncio
async def test_deadline_threshold_alerts_are_persistent_and_deduplicated(watcher_db, profile):
    soon = medical_job(closing="2026-10-03")
    await scan(profile, [soon])
    first = [n for n in get_notifications() if n["event_type"] == "deadline_approaching"]
    assert len(first) == 1
    assert first[0]["threshold_days"] == 3
    await scan(profile, [soon], now=datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc))
    second = [n for n in get_notifications() if n["event_type"] == "deadline_approaching"]
    assert len(second) == 1


@pytest.mark.asyncio
async def test_matching_integration_classifies_needs_verification(watcher_db, profile):
    result = await scan(profile, [surgeon_needs_verification_job()])
    assert result["needs_verification_count"] == 1
    job = get_watcher_jobs()[0]
    assert job["readiness_status"] == NEEDS_VERIFICATION
    matches = job["last_matching_result"]["requirement_matches"]
    assert any(item["key"] == "medical_specialist" and item["status"] == "Needs verification" for item in matches)


@pytest.mark.asyncio
async def test_ready_to_apply_application_package_integration(watcher_db, profile, tmp_path):
    await scan(profile, [medical_job()])
    job_id = get_actionable_opportunities()[0]["canonical_id"]
    result = prepare_application_for_watcher_job(
        job_id,
        profile,
        resume_text="MD doctor with clinical experience, HMIS, BPHS, EPHS, IMAM, IPC, Dari, English, Pashto.",
        out_dir=str(tmp_path / "applications"),
    )
    assert result["ok"] is True
    assert result["no_submission_performed"] is True
    assert result["readiness_status"] == READY_TO_APPLY
    paths = result["generated_paths"]
    assert Path(paths["application_package_json"]).exists()
    assert tracker.get_job_by_id(job_id)["status"] == "prepared"


@pytest.mark.asyncio
async def test_not_eligible_watcher_job_does_not_prepare_application_package(watcher_db, profile, tmp_path):
    ineligible = medical_job(
        job_id="female-only-md",
        title="Medical Doctor (Female)",
        description_extra="Gender: Female. Only female candidates are eligible.",
    )
    result = await scan(profile, [ineligible])
    assert result["not_eligible_count"] == 1
    row = get_watcher_jobs(active_only=False)[0]
    assert row["readiness_status"] == "NOT_ELIGIBLE"
    prepared = prepare_application_for_watcher_job(
        row["canonical_id"],
        profile,
        resume_text="MD doctor with clinical experience, HMIS, BPHS, EPHS, IMAM, IPC, Dari, English, Pashto.",
        out_dir=str(tmp_path / "applications"),
    )
    assert prepared["ok"] is False
    assert prepared["readiness_status"] == "NOT_ELIGIBLE"
    assert prepared["generated_paths"] == {}
    assert not (tmp_path / "applications").exists()
    assert tracker.get_job_by_id(row["canonical_id"])["status"] == "not_eligible"


@pytest.mark.asyncio
async def test_rescan_preserves_prepared_not_submitted_application_state(watcher_db, profile, tmp_path):
    job = medical_job()
    await scan(profile, [job])
    job_id = get_actionable_opportunities()[0]["canonical_id"]
    prepared = prepare_application_for_watcher_job(
        job_id,
        profile,
        resume_text="MD doctor with clinical experience, HMIS, BPHS, EPHS, IMAM, IPC, Dari, English, Pashto.",
        out_dir=str(tmp_path / "applications"),
    )
    assert prepared["ok"] is True
    assert tracker.get_job_by_id(job_id)["status"] == "prepared"
    await scan(profile, [job], now=datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc))
    row = tracker.get_job_by_id(job_id)
    assert row["status"] == "prepared"
    assert row["submitted_at"] in (None, "")


@pytest.mark.asyncio
async def test_interrupted_scan_is_marked_on_next_scan_without_deleting_jobs(watcher_db, profile):
    await scan(profile, [medical_job()])
    begin_scan("scan_interrupted", "2026-09-30T17:00:00+00:00", ["fmic"])
    result = await scan(profile, [medical_job()], now=datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc))
    audits = get_scan_audits(limit=5)
    interrupted = next(item for item in audits if item["scan_id"] == "scan_interrupted")
    assert interrupted["status"] == "INTERRUPTED"
    assert result["unchanged_count"] == 1
    assert len(get_watcher_jobs()) == 1


@pytest.mark.asyncio
async def test_scan_audit_contains_required_counts(watcher_db, profile):
    result = await scan(profile, [medical_job(), surgeon_needs_verification_job()])
    audits = get_scan_audits()
    assert audits[0]["scan_id"] == result["scan_id"]
    assert audits[0]["discovered_count"] == 2
    assert audits[0]["deduplicated_count"] == 2
    assert audits[0]["new_count"] == 2
    assert audits[0]["ready_to_apply_count"] == 1
    assert audits[0]["needs_verification_count"] == 1
    assert audits[0]["sources_attempted"]


def test_scheduler_configuration_uses_watcher_defaults(profile):
    from scheduler import get_schedule_settings

    profile["watcher"]["scan_interval_hours"] = 4
    profile["watcher"]["deadline_alert_days"] = [7, 3, 1]
    settings = get_schedule_settings(profile)
    assert settings["enabled"] is True
    assert settings["job_watch_interval_hours"] == 4
    assert settings["deadline_alert_days"] == [7, 3, 1]
