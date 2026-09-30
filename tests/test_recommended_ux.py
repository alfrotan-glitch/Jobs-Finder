from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from utils import tracker
from utils.discovery import Job
from utils.job_watcher import run_job_watch_scan


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "ux.db")
    return tmp_path / "ux.db"


def profile():
    return {
        "personal": {"first_name": "Allah Yar", "last_name": "Frotan", "email": "doctor@example.org", "location": "Kabul", "nationality": "Afghan"},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"verified": True, "status": "Verified"},
        "medical_exit_exam": {"verified": True, "status": "Verified"},
        "clinical_experience": {"years": 3},
        "work_history": [{"title": "Medical Doctor", "organization": "ACF", "location": "Daikundi", "start": "2022-01", "end": "2025-07", "bullets": ["Clinical care, HMIS, BPHS, EPHS, IMAM, IPC."]}],
        "languages": [{"name": "Dari"}, {"name": "Pashto"}, {"name": "English"}],
        "preferences": {"locations": ["Afghanistan", "Kabul"], "willing_to_relocate": True},
        "job_sources": {"test": {"enabled": True}},
        "watcher": {"deadline_alert_days": [7, 3, 1]},
    }


def job(job_id, title, company, closing, description, apply="https://example.org/apply", source="test"):
    return Job(
        job_id,
        title,
        company,
        "Kabul, Afghanistan",
        f"https://example.org/{job_id}",
        apply,
        source,
        description=description + f" Closing date: {closing}. Apply at {apply}.",
        metadata={
            "source": source,
            "source_url": f"https://example.org/jobs/{job_id}",
            "original_vacancy_url": f"https://example.org/{job_id}",
            "source_urls": [f"https://example.org/jobs/{job_id}", f"https://example.org/{job_id}"],
            "source_reliability": "high",
            "closing_date": closing,
            "source_provenance": [{"source": source, "url": f"https://example.org/{job_id}", "reliability": "high"}],
        },
    )


@pytest.mark.asyncio
async def test_recommended_filters_out_not_eligible_and_expired_jobs(db):
    ready = job("ready", "Medical Officer", "FMIC", "2026-10-05", "MD and valid medical registration required. 1 year clinical experience. Dari English Pashto.")
    not_eligible = job("logistics", "Supply Chain Assistant", "IOM", "2026-10-05", "Requires logistics degree and procurement supply chain experience.")
    expired = job("old-md", "Medical Officer", "Hospital", "2026-09-20", "MD and clinical experience required. Dari English Pashto.")

    async def discovery(_profile):
        return [ready, not_eligible, expired]

    await run_job_watch_scan(
        profile(),
        discovery_func=discovery,
        now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc),
        today=date(2026, 9, 30),
        resume_text="MD with clinical experience, Afghan Medical Council registration, Dari, English, Pashto.",
    )
    recommended = tracker.get_recommended_jobs()
    titles = [row["title"] for row in recommended]
    assert "Medical Officer" in titles
    assert "Supply Chain Assistant" not in titles
    assert all(str(row.get("closing_date") or "9999-99-99") >= "2026-09-30" for row in recommended)


@pytest.mark.asyncio
async def test_recommended_excludes_non_health_needs_verification_jobs(db):
    ready = job(
        "ready-medical",
        "Medical Officer",
        "FMIC",
        "2026-10-05",
        "MD and valid medical registration required. 1 year clinical experience. Dari English Pashto.",
        apply="https://example.org/apply-ready-medical",
    )
    non_health_verify = job(
        "iom-supply-chain",
        "Supply Chain Assistant",
        "IOM",
        "2026-10-05",
        "Bachelor degree in Business Administration, Logistics, Procurement or relevant field is required. "
        "Minimum two years of supply chain, procurement and asset management experience. English, Dari and Pashto required.",
        apply="mailto:jobs@iom.int",
    )

    async def discovery(_profile):
        return [non_health_verify, ready]

    await run_job_watch_scan(
        profile(),
        discovery_func=discovery,
        now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc),
        today=date(2026, 9, 30),
        resume_text="MD with clinical experience, Afghan Medical Council registration, Dari, English, Pashto.",
    )

    all_jobs, _ = tracker.get_all_jobs(limit=50)
    stored = next(row for row in all_jobs if row["title"] == "Supply Chain Assistant")
    conn = tracker.get_db()
    watcher = conn.execute(
        "SELECT readiness_status, operational_priority FROM job_watch_vacancies WHERE canonical_id = ?",
        (stored["id"],),
    ).fetchone()
    conn.close()
    # Even if a non-health posting is mechanically complete enough to be READY,
    # it must stay LOW priority and out of Recommended.
    assert watcher["operational_priority"] == "LOW"
    recommended = tracker.get_recommended_jobs()
    assert "Supply Chain Assistant" not in [row["title"] for row in recommended]


@pytest.mark.asyncio
async def test_recommended_orders_new_ready_before_new_needs_verification(db):
    ready = job("ready", "Medical Officer", "FMIC", "2026-10-05", "MD and valid medical registration required. 1 year clinical experience. Dari English Pashto.", apply="https://example.org/apply-ready")
    verify = job("surgeon", "Surgeon", "AKHS-A", "2026-10-10", "Requires Specialist Surgeon qualification and specialist certification in general surgery. Dari Pashto.", apply="https://example.org/apply-surgeon")

    async def discovery(_profile):
        return [verify, ready]

    await run_job_watch_scan(
        profile(),
        discovery_func=discovery,
        now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc),
        today=date(2026, 9, 30),
        resume_text="MD with clinical experience, Afghan Medical Council registration, Dari, English, Pashto.",
    )
    recommended = tracker.get_recommended_jobs()
    assert recommended[0]["title"] == "Medical Officer"
    assert recommended[0]["watcher_readiness_status"] == "READY_TO_APPLY"


def test_settings_sanitization_keeps_nontechnical_values_safe():
    from dashboard.server import _sanitize_profile_settings

    sanitized = _sanitize_profile_settings({
        "watcher": {"enabled": True, "scan_interval_hours": "0", "deadline_alert_days": "7, 3, 1", "auto_prepare_ready_to_apply": "yes"},
        "schedule": {},
        "notifications": {"new_jobs": True, "deadline_alerts": False},
    })
    assert sanitized["watcher"]["scan_interval_hours"] == 1
    assert sanitized["schedule"]["job_watch_interval_hours"] == 1
    assert sanitized["watcher"]["deadline_alert_days"] == [7, 3, 1]
    assert sanitized["notifications"]["deadline_alerts"] is False
    assert sanitized["notifications"]["source_failures"] is True



def test_api_does_not_mark_submitted_without_confirmation(db):
    from fastapi.testclient import TestClient
    from dashboard.server import app

    tracker.log_discovered(job("api-status", "Medical Officer", "FMIC", "2026-10-05", "MD required. Clinical experience required."))
    client = TestClient(app)
    res = client.patch("/api/jobs/api-status", json={"status": "submitted"})
    assert res.status_code == 400
    assert tracker.get_job_by_id("api-status")["status"] == "discovered"


def test_api_blocks_submitted_back_to_prepared(db):
    from fastapi.testclient import TestClient
    from dashboard.server import app

    j = job("api-submitted", "Medical Officer", "FMIC", "2026-10-05", "MD required. Clinical experience required.")
    tracker.log_discovered(j)
    tracker.log_medical_match(j.id, {"priority": "Review first", "readiness_status": "READY_TO_APPLY", "explanation": "Ready", "facts": {}})
    assert tracker.transition_application_state(j.id, "prepared")[0]
    assert tracker.transition_application_state(j.id, "opened")[0]
    assert tracker.transition_application_state(j.id, "submitted", explicit_confirmation=True)[0]
    client = TestClient(app)
    res = client.patch(f"/api/jobs/{j.id}", json={"status": "prepared"})
    assert res.status_code == 400
    assert tracker.get_job_by_id(j.id)["status"] == "submitted"
